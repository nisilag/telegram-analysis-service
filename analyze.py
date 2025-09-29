"""
Message analysis pipeline with token extraction and sentiment analysis.
"""
import re
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import List, Optional

from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
import torch
import aiohttp
from loguru import logger

from models import TelegramMessage, MessageAnalysis, SentimentType
from config import config, FINANCE_KEYWORDS, TOKEN_ALIASES

class MessageAnalyzer:
    """Analyzes Telegram messages for investment relevance and sentiment."""
    
    def __init__(self):
        self.model_name = "ProsusAI/finbert"
        self.tokenizer = None
        self.model = None
        self.sentiment_pipeline = None
        self.executor = ThreadPoolExecutor(max_workers=2)
        # Pattern for crypto tokens - must start with a letter, not a number
        # This prevents matching dollar amounts like $10M, $5B, etc.
        self._token_pattern = re.compile(r'\$([A-Z][A-Z0-9_]{1,9})\b')
        self._finance_pattern = self._build_finance_pattern()
        
    def _build_finance_pattern(self) -> re.Pattern:
        """Build regex pattern for finance keywords with word boundaries."""
        keywords = '|'.join(re.escape(keyword) for keyword in FINANCE_KEYWORDS)
        return re.compile(rf'\b(?:{keywords})\b', re.IGNORECASE)
    
    async def initialize(self):
        """Initialize the FinBERT model and tokenizer."""
        logger.info("Initializing FinBERT model...")
        
        def load_model():
            tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            
            # Create sentiment analysis pipeline
            sentiment_pipeline = pipeline(
                "sentiment-analysis",
                model=model,
                tokenizer=tokenizer,
                device=0 if torch.cuda.is_available() else -1,
                return_all_scores=True
            )
            
            return tokenizer, model, sentiment_pipeline
        
        # Load model in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        self.tokenizer, self.model, self.sentiment_pipeline = await loop.run_in_executor(
            self.executor, load_model
        )
        
        logger.info("FinBERT model initialized successfully")
    
    async def analyze_message(self, message: TelegramMessage) -> MessageAnalysis:
        """
        Analyze a message for investment relevance and sentiment.
        
        Args:
            message: The Telegram message to analyze
            
        Returns:
            MessageAnalysis with extracted information
        """
        text = message.text.strip()
        
        # Extract tokens (cashtags)
        tokens = self._extract_tokens(text)
        
        # Check if investment-related
        is_investment = self._is_investment_related(text, tokens)
        
        # Analyze sentiment if investment-related
        sentiment = SentimentType.NEUTRAL
        confidence = None
        
        if is_investment and text:
            sentiment, confidence = await self._analyze_sentiment(text)
        
        # Generate topic key
        topic_key = self._generate_topic_key(tokens, text)
        
        # Extract key points using LLM if investment-related
        if is_investment:
            try:
                key_points = await self._extract_crypto_insights_with_llm(text, tokens)
            except Exception as e:
                logger.warning(f"LLM key points extraction failed: {e}")
                key_points = self._extract_key_points_fallback(text)
        else:
            key_points = []
        
        return MessageAnalysis(
            chat_id=message.chat_id,
            message_id=message.message_id,
            is_investment=is_investment,
            sentiment=sentiment,
            tokens=tokens,
            topic_key=topic_key,
            key_points=key_points,
            confidence=confidence,
            model_version=config.model_version,
            analyzed_at=datetime.utcnow().replace(tzinfo=timezone.utc)
        )
    
    def _extract_tokens(self, text: str) -> List[str]:
        """Extract cryptocurrency tokens/tickers from text."""
        tokens = set()
        
        # Find cashtags ($TOKEN)
        matches = self._token_pattern.findall(text.upper())
        
        # Filter out common monetary suffixes that aren't crypto tokens
        monetary_suffixes = {'K', 'M', 'B', 'T', 'MIL', 'BIL', 'TRIL'}
        for match in matches:
            # Skip if it's just a monetary suffix
            if match not in monetary_suffixes:
                tokens.add(match)
        
        # Check for token aliases
        text_upper = text.upper()
        for token, aliases in TOKEN_ALIASES.items():
            for alias in aliases:
                if re.search(rf'\b{re.escape(alias)}\b', text_upper):
                    tokens.add(token)
        
        return sorted(list(tokens))
    
    def _is_investment_related(self, text: str, tokens: List[str]) -> bool:
        """
        Determine if a message is investment-related.
        
        Criteria:
        1. Contains at least one token/cashtag, OR
        2. Contains 2+ finance keywords with word boundaries
        """
        if tokens:
            return True
        
        # Count finance keywords
        finance_matches = self._finance_pattern.findall(text)
        return len(finance_matches) >= 2
    
    async def _analyze_sentiment(self, text: str) -> tuple[SentimentType, float]:
        """
        Analyze sentiment using FinBERT.
        
        Returns:
            Tuple of (sentiment, confidence)
        """
        if not self.sentiment_pipeline:
            return SentimentType.NEUTRAL, 0.0
        
        try:
            # Properly truncate text using tokenizer (FinBERT has 512 token limit)
            def run_sentiment():
                # Use tokenizer to properly truncate to 512 tokens
                if self.tokenizer:
                    # Tokenize and truncate to max 510 tokens (leaving room for special tokens)
                    tokens = self.tokenizer.encode(text, truncation=True, max_length=510)
                    truncated_text = self.tokenizer.decode(tokens, skip_special_tokens=True)
                else:
                    # Fallback: naive character truncation (less accurate)
                    truncated_text = text[:400]  # Conservative character limit
                
                results = self.sentiment_pipeline(truncated_text)
                return results[0]  # Get first (and only) result
            
            # Run sentiment analysis in thread pool
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(self.executor, run_sentiment)
            
            # Map FinBERT labels to our sentiment types
            sentiment_map = {
                'positive': SentimentType.BULLISH,
                'negative': SentimentType.BEARISH,
                'neutral': SentimentType.NEUTRAL
            }
            
            # Find the highest confidence prediction
            best_result = max(results, key=lambda x: x['score'])
            sentiment = sentiment_map.get(best_result['label'].lower(), SentimentType.NEUTRAL)
            confidence = best_result['score']
            
            # Apply keyword-based sentiment enhancement for NEUTRAL predictions
            if sentiment == SentimentType.NEUTRAL or confidence < config.confidence_threshold:
                enhanced_sentiment = self._enhance_sentiment_with_keywords(text)
                if enhanced_sentiment != SentimentType.NEUTRAL:
                    # Use keyword-based sentiment with boosted confidence
                    return enhanced_sentiment, max(confidence, 0.6)
            
            # Only return non-neutral if confidence is above threshold
            if confidence < config.confidence_threshold:
                sentiment = SentimentType.NEUTRAL
            
            return sentiment, confidence
            
        except Exception as e:
            logger.error(f"Error in sentiment analysis: {e}")
            return SentimentType.NEUTRAL, 0.0
    
    def _enhance_sentiment_with_keywords(self, text: str) -> SentimentType:
        """
        Enhance sentiment analysis using keyword patterns for financial content.
        
        This helps override FinBERT's conservative NEUTRAL predictions when
        clear directional language is present.
        """
        text_lower = text.lower()
        
        # Strong bullish indicators
        bullish_patterns = [
            # Price action
            r'\b(moon|mooning|pump|pumping|rally|rallying|breakout|breaking out)\b',
            r'\b(bullish|bull run|bull market|going up|uptrend|up trend)\b',
            r'\b(buy|buying|long|longing|accumulate|accumulating)\b',
            r'\b(target|targets|price target|tp|take profit)\b',
            r'\b(strong|strength|momentum|explosive|parabolic)\b',
            r'\b(ath|all.?time.?high|new high|higher high)\b',
            
            # Positive sentiment
            r'\b(love|loving|like|liking|bullish on|confident)\b',
            r'\b(gem|alpha|opportunity|potential|undervalued)\b',
            r'\b(rocket|lambo|diamond hands|hodl|hold)\b'
        ]
        
        # Strong bearish indicators  
        bearish_patterns = [
            # Price action
            r'\b(dump|dumping|crash|crashing|drop|dropping|fall|falling)\b',
            r'\b(bearish|bear market|going down|downtrend|down trend)\b',
            r'\b(sell|selling|short|shorting|exit|exiting)\b',
            r'\b(rekt|liquidated|liquidation|stop loss|sl)\b',
            r'\b(weak|weakness|bleeding|red|correction)\b',
            r'\b(resistance|rejection|failed|failure)\b',
            
            # Negative sentiment
            r'\b(hate|hating|avoid|avoiding|stay away|bearish on)\b',
            r'\b(overvalued|bubble|scam|rug|rugpull|dead)\b',
            r'\b(paper hands|panic|fear|fud)\b'
        ]
        
        # Count pattern matches
        bullish_score = sum(1 for pattern in bullish_patterns 
                           if re.search(pattern, text_lower))
        bearish_score = sum(1 for pattern in bearish_patterns 
                           if re.search(pattern, text_lower))
        
        # Determine sentiment based on pattern strength
        if bullish_score > bearish_score and bullish_score >= 1:
            return SentimentType.BULLISH
        elif bearish_score > bullish_score and bearish_score >= 1:
            return SentimentType.BEARISH
        else:
            return SentimentType.NEUTRAL
    
    def _generate_topic_key(self, tokens: List[str], text: str) -> str:
        """
        Generate a topic key for the message.
        
        Priority:
        1. First token if any
        2. Derived phrase from text
        3. "GENERAL" fallback
        """
        if tokens:
            return tokens[0]
        
        # Try to extract a meaningful phrase
        words = text.split()[:10]  # First 10 words
        if len(words) >= 3:
            # Remove common words and create a short phrase
            meaningful_words = [
                word for word in words 
                if len(word) > 3 and word.lower() not in {
                    'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 
                    'can', 'had', 'her', 'was', 'one', 'our', 'out', 'day',
                    'get', 'has', 'him', 'his', 'how', 'its', 'may', 'new',
                    'now', 'old', 'see', 'two', 'who', 'boy', 'did', 'man',
                    'way', 'too', 'any', 'few', 'let', 'put', 'say', 'she',
                    'try', 'use'
                }
            ]
            
            if meaningful_words:
                return '_'.join(meaningful_words[:3]).upper()
        
        return "GENERAL"
    
    async def _extract_crypto_insights_with_llm(self, text: str, tokens: List[str]) -> List[str]:
        """
        Extract Grok-style crypto insights using local Llama model.
        """
        if not config.enable_llm_insights:
            return self._extract_key_points_fallback(text)
            
        try:
            # Prepare the prompt
            tokens_str = ", ".join(tokens) if tokens else "None detected"
            prompt = f"""Extract 1-2 concise crypto investment insights from this message.
Focus on: price targets, market positioning, fundamentals, performance, competitive dynamics.
Format: 4-8 words max per insight, no filler words.

Examples:
- "BTC to 600K goal"
- "SOL vamping ETH ecosystem"
- "Constant buybacks from revenue"
- "First mover in robotics"
- "Up 60% in 24h"

Message: {text[:500]}
Tokens mentioned: {tokens_str}

Insights:"""

            # Call Ollama API
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=config.ollama_timeout)) as session:
                payload = {
                    "model": config.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "top_p": 0.9,
                        "max_tokens": 100
                    }
                }
                
                async with session.post(f"{config.ollama_base_url}/api/generate", json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        insights_text = result.get("response", "").strip()
                        
                        # Parse insights from response
                        insights = self._parse_llm_insights(insights_text)
                        if insights:
                            logger.debug(f"LLM extracted insights: {insights}")
                            return insights
                        else:
                            logger.debug("LLM returned no valid insights, using fallback")
                            return self._extract_key_points_fallback(text)
                    else:
                        logger.warning(f"Ollama API error: {response.status}")
                        return self._extract_key_points_fallback(text)
                        
        except Exception as e:
            logger.warning(f"LLM insight extraction failed: {e}, using fallback")
            return self._extract_key_points_fallback(text)
    
    def _parse_llm_insights(self, llm_response: str) -> List[str]:
        """
        Parse and validate insights from LLM response.
        """
        if not llm_response:
            return []
            
        # Split by lines and clean up
        lines = [line.strip() for line in llm_response.split('\n') if line.strip()]
        insights = []
        
        for line in lines:
            # Remove bullet points and numbering
            line = re.sub(r'^[-•*\d+\.\)\s]+', '', line).strip()
            
            # Skip empty lines or lines that are too long/short
            if not line or len(line) < 10 or len(line) > 80:
                continue
                
            # Skip lines that don't look like insights
            if any(skip_word in line.lower() for skip_word in [
                'here are', 'based on', 'the message', 'insights:', 'analysis:'
            ]):
                continue
                
            # Clean up the insight
            line = line.strip('"\'')
            if line:
                insights.append(line)
                
        return insights[:2]  # Max 2 insights
    
    def _extract_key_points_fallback(self, text: str) -> List[str]:
        """
        Fallback key points extraction using pattern matching.
        """
        if not text.strip():
            return []
        
        # Clean text: remove URLs and emojis
        cleaned_text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
        cleaned_text = re.sub(r'[^\w\s\.,!?$%\-]', '', cleaned_text)
        
        # Extract crypto-specific patterns with better logic
        insights = []
        
        # Price targets: "BTC to 100K", "SOL to $350", "target $50"
        price_patterns = [
            r'\$?([A-Z]{2,6})\s+to\s+\$?(\d+[KMB]?)',
            r'target\s+\$?(\d+[KMB]?)',
            r'\$?([A-Z]{2,6})\s+(\d+[KMB]?)\s+MC'
        ]
        
        for pattern in price_patterns:
            matches = re.finditer(pattern, cleaned_text, re.IGNORECASE)
            for match in matches:
                full_match = match.group(0).strip()
                if len(full_match) < 30 and len(full_match) > 5:
                    insights.append(full_match)
        
        # Performance indicators: "up 60%", "SOL outperforms ETH"
        perf_patterns = [
            r'up\s+\d+%(?:\s+in\s+\w+)?',
            r'\$?([A-Z]{2,6})\s+(?:outperforms?|flips?|vamping?)\s+\$?([A-Z]{2,6})',
            r'(?:bullish|bearish)\s+on\s+\$?([A-Z]{2,6})',
            r'\$?([A-Z]{2,6})\s+(?:pumping?|dumping?)'
        ]
        
        for pattern in perf_patterns:
            matches = re.finditer(pattern, cleaned_text, re.IGNORECASE)
            for match in matches:
                full_match = match.group(0).strip()
                if len(full_match) < 40 and len(full_match) > 5:
                    insights.append(full_match)
        
        # Fundamental catalysts: "token buybacks", "revenue generation"
        fundamental_patterns = [
            r'(?:token\s+)?buybacks?',
            r'revenue\s+generation',
            r'first\s+mover',
            r'enterprise\s+contracts?',
            r'whale\s+accumulation',
            r'ETF\s+(?:launch|filing)'
        ]
        
        for pattern in fundamental_patterns:
            matches = re.finditer(pattern, cleaned_text, re.IGNORECASE)
            for match in matches:
                # Get surrounding context (up to 30 chars before and after)
                start = max(0, match.start() - 15)
                end = min(len(cleaned_text), match.end() + 15)
                context = cleaned_text[start:end].strip()
                if len(context) < 50 and len(context) > 10:
                    insights.append(context)
        
        # Remove duplicates and return best insights
        unique_insights = list(dict.fromkeys(insights))  # Preserve order, remove dupes
        return unique_insights[:2]  # Max 2 insights
    
    def _extract_key_points(self, text: str) -> List[str]:
        """
        Main entry point for key points extraction.
        """
        # Always use enhanced pattern matching (LLM disabled for performance)
        return self._extract_key_points_fallback(text)
    
    async def close(self):
        """Clean up resources."""
        if self.executor:
            self.executor.shutdown(wait=True)
        logger.info("Message analyzer closed")


# Global analyzer instance
analyzer = MessageAnalyzer()
