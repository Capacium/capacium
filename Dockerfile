FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set up work directory
WORKDIR /workspace

# Install capacium with all extras
COPY . /app
WORKDIR /app
RUN pip install --no-cache-dir .[signing,yaml]

# Default workspace directory for capability context
WORKDIR /workspace

# Expose CLI as entrypoint
ENTRYPOINT ["cap"]
CMD ["--help"]
