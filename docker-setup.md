# Docker Setup Guide

## Quick Start

### 1. Environment Setup
```bash
# Copy the Docker environment template
cp .env.docker .env

# Edit .env with your actual values
nano .env
```

**Required values to update in `.env`:**
- `TELEGRAM_API_ID` - Get from https://my.telegram.org
- `TELEGRAM_API_HASH` - Get from https://my.telegram.org  
- `TARGET_CHAT_ID` - Chat ID to monitor
- `POSTGRES_PASSWORD` - Secure database password

### 2. Build and Start
```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f

# View only app logs
docker-compose logs -f app
```

### 3. First Run Authentication
On first run, you'll need to authenticate with Telegram:

```bash
# Follow the authentication prompts
docker-compose logs -f app

# The app will prompt for phone number and verification code
# Session will be saved in the session_data volume
```

## Service Management

### Start/Stop Services
```bash
# Start services
docker-compose up -d

# Stop services
docker-compose down

# Restart just the app
docker-compose restart app

# View service status
docker-compose ps
```

### Logs and Monitoring
```bash
# View all logs
docker-compose logs

# Follow app logs in real-time
docker-compose logs -f app

# View PostgreSQL logs
docker-compose logs postgres

# View last 100 lines
docker-compose logs --tail=100 app
```

### Database Management

#### Connect to Database
```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U telegram_user -d telegram_analysis

# Or from host (if port 5432 is exposed)
psql -h localhost -U telegram_user -d telegram_analysis
```

#### Backup Database
```bash
# Run backup
docker-compose --profile backup run --rm backup

# View backups
docker-compose exec postgres ls -la /backup/
```

#### Restore Database
```bash
# List available backups
docker-compose exec postgres ls -la /backup/

# Restore from backup
docker-compose exec postgres /restore.sh /backup/telegram_analysis_backup_20240127_143022.sql.gz
```

## Volume Management

### Persistent Data Locations
- **Database**: `postgres_data` volume
- **Session Files**: `session_data` volume  
- **Logs**: `logs_data` volume
- **Model Cache**: `model_cache` volume
- **Backups**: `backup_data` volume

### Backup Volumes
```bash
# Create volume backup
docker run --rm -v telegram-analysis-service_postgres_data:/data -v $(pwd):/backup alpine tar czf /backup/postgres_data_backup.tar.gz -C /data .

# Restore volume backup
docker run --rm -v telegram-analysis-service_postgres_data:/data -v $(pwd):/backup alpine tar xzf /backup/postgres_data_backup.tar.gz -C /data
```

### Clean Up Volumes
```bash
# Remove all volumes (WARNING: This deletes all data!)
docker-compose down -v

# Remove specific volume
docker volume rm telegram-analysis-service_postgres_data
```

## Development

### Development Mode
```bash
# Override for development with local code mounting
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

### Rebuild After Code Changes
```bash
# Rebuild app container
docker-compose build app

# Restart with new image
docker-compose up -d app
```

### Run Commands in Container
```bash
# Run setup diagnostics
docker-compose exec app python setup.py test

# Create sample data
docker-compose exec app python setup.py sample

# Access container shell
docker-compose exec app bash
```

## Troubleshooting

### Common Issues

#### Authentication Problems
```bash
# Check if session file exists
docker-compose exec app ls -la /app/data/

# Remove session to re-authenticate
docker-compose exec app rm -f /app/data/telegram_session*
docker-compose restart app
```

#### Database Connection Issues
```bash
# Check if PostgreSQL is running
docker-compose ps postgres

# Check database logs
docker-compose logs postgres

# Test connection
docker-compose exec postgres pg_isready -U telegram_user -d telegram_analysis
```

#### Permission Issues
```bash
# Check file permissions in container
docker-compose exec app ls -la /app/

# Fix ownership (if needed)
docker-compose exec --user root app chown -R telegram:telegram /app/data /app/logs
```

#### Out of Disk Space
```bash
# Check Docker disk usage
docker system df

# Clean up unused images/containers
docker system prune

# Check volume sizes
docker system df -v
```

### Performance Tuning

#### PostgreSQL Configuration
Edit `docker-compose.yml` to add PostgreSQL performance settings:

```yaml
postgres:
  environment:
    # Add performance settings
    POSTGRES_SHARED_BUFFERS: 256MB
    POSTGRES_EFFECTIVE_CACHE_SIZE: 1GB
    POSTGRES_MAINTENANCE_WORK_MEM: 64MB
```

#### App Container Resources
```yaml
app:
  deploy:
    resources:
      limits:
        memory: 4G
        cpus: '2'
      reservations:
        memory: 2G
        cpus: '1'
```

## Security

### Network Security
- Services communicate on internal `telegram_network`
- Only expose necessary ports
- Use strong passwords
- Consider using Docker secrets for production

### File Permissions
- App runs as non-root user `telegram`
- Volumes have appropriate permissions
- Environment files are read-only mounted

### Production Considerations
- Use Docker secrets instead of environment variables
- Set up log rotation
- Monitor resource usage
- Regular security updates
- Backup automation

## Monitoring

### Health Checks
```bash
# Check service health
docker-compose ps

# App health check (if implemented)
curl http://localhost:8080/healthz
```

### Resource Usage
```bash
# Container resource usage
docker stats

# Disk usage
docker system df
```

### Log Analysis
```bash
# Search logs for errors
docker-compose logs app | grep ERROR

# Monitor ingestion rate
docker-compose logs app | grep "messages processed"
```
