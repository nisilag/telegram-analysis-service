"""
Message analysis pipeline with token extraction and sentiment analysis.
"""
import re
import asyncio
from datetime import datetime, timezone
from typing import List, Set, Optional
from concurrent.futures import ThreadPoolExecutor

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
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
        
        # Extract key points
        key_points = self._extract_key_points(text)
        
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
            
            # Only return non-neutral if confidence is above threshold
            if confidence < config.confidence_threshold:
                sentiment = SentimentType.NEUTRAL
            
            return sentiment, confidence
            
        except Exception as e:
            logger.error(f"Error in sentiment analysis: {e}")
            return SentimentType.NEUTRAL, 0.0
    
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
    
    def _extract_key_points(self, text: str) -> List[str]:
        """
        Extract key points from the message text.
        
        Returns concise bullet points with URLs and emojis stripped.
        """
        if not text.strip():
            return []
        
        # Clean text: remove URLs and emojis
        cleaned_text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
        cleaned_text = re.sub(r'[^\w\s\.,!?$%\-]', '', cleaned_text)
        
        # Filter out newsletter/spam patterns
        spam_patterns = [
            r'new edition.*newsletter',
            r'top \d+ mindshare',
            r'ive published.*newsletter',
            r'trading.*investing.*indicators',
            r'see how i.*',
            r'subscribe.*',
            r'follow.*for.*updates'
        ]
        
        # Check if this looks like newsletter spam
        text_lower = cleaned_text.lower()
        if any(re.search(pattern, text_lower) for pattern in spam_patterns):
            # For newsletter content, extract only token-specific insights
            token_sentences = []
            sentences = re.split(r'[.!?]+', cleaned_text)
            for sentence in sentences:
                if any(token in sentence.upper() for token in ['$', 'BTC', 'ETH', 'SOL', 'BULLISH', 'BEARISH', 'PUMP', 'DUMP']):
                    if len(sentence.strip()) > 15:
                        token_sentences.append(sentence.strip())
            return token_sentences[:2]  # Limit to 2 token-specific points
        
        # Split into sentences
        sentences = re.split(r'[.!?]+', cleaned_text)
        sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 15]
        
        # Take up to 3 most meaningful sentences
        key_points = []
        for sentence in sentences[:3]:
            if len(sentence) > 20:  # Only meaningful sentences
                # Skip generic phrases
                if not any(generic in sentence.lower() for generic in [
                    'honestly asking', 'what do you think', 'let me know', 'thoughts?',
                    'anyone else', 'does anyone', 'what are your'
                ]):
                    # Truncate if too long
                    if len(sentence) > 120:
                        sentence = sentence[:117] + "..."
                    key_points.append(sentence)
        
        return key_points
    
    async def close(self):
        """Clean up resources."""
        if self.executor:
            self.executor.shutdown(wait=True)
        logger.info("Message analyzer closed")


# Global analyzer instance
analyzer = MessageAnalyzer()
