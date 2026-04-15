# Build: docker build -t lift-repair-tickets .
# Run: docker run -d -p 8081:8081 -p 8082:8082 -v tickets-db:/app/instance lift-repair-tickets

FROM python:3.13-slim

WORKDIR /app

# Install system dependencies for image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg-dev \
    zlib1g-dev \
    libraqm-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    flask \
    gunicorn \
    pillow \
    requests \
    python-dotenv

# Copy application files (only needed ones)
COPY ticket_system.py /app/
COPY ticket_db.py /app/
COPY max_bot.py /app/
COPY notification_service.py /app/
COPY simple_mcp.py /app/
COPY templates/ /app/templates/

# Create required directories
RUN mkdir -p /app/instance /app/uploads

# Copy database if exists
COPY instance/ /app/instance/

# Create uploads directory
RUN mkdir -p /app/uploads

# Copy uploaded files
COPY uploads/ /app/uploads/

# Copy new API server
COPY tickets_api.py /app/

# Expose ports
EXPOSE 8081 8082 8084

# Environment variables
ENV FLASK_ENV=production
ENV MAX_BOT_TOKEN=f9LHodD0cOJr6-3caEEtEU-KqU42RaPXLpz3wkHbJMQc0vANY8fVYJfXn0bsZh7IdSq0sNqBkyGwfySDPS8l
ENV LM_STUDIO_URL=http://host.docker.internal:1234

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8081/api/health || exit 1

# Health check for MCP (8082)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8082/mcp/tools || exit 1

# Run all Flask servers and Max bot
CMD sh -c "python ticket_system.py & python simple_mcp.py & python tickets_api.py & python max_bot.py & wait"