FROM python:3.11-slim

LABEL version="0.6.1"
LABEL description="Pulse — Self-improving AI Agent (Reliability-First)"
LABEL repository="https://github.com/Alex663028/pulse-agent"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY pulse/ pulse/
COPY examples/ examples/
COPY README.md .
COPY LICENSE .

# Install Pulse
RUN pip install --no-cache-dir -e ".[dev]"

# Create default Pulse home
ENV PULSE_HOME=/root/.pulse

# Default entrypoint
ENTRYPOINT ["python", "-m", "pulse.cli.main"]
CMD ["--help"]
