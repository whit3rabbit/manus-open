# Use the official Playwright image (v1.50.0-noble) as the base
FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

# Set environment variables
ENV RUNTIME_API_HOST=http://localhost \
    CHROME_INSTANCE_PATH=/usr/bin/chromium \
    HOME=/home/ubuntu

# Install system dependencies and Node.js 20.x in a single layer
RUN apt-get update && \
    apt-get install -y \
        bash \
        sudo \
        curl \
        bc \
        software-properties-common && \
    # Add NodeSource and Python PPA
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && \
    # Install all packages
    apt-get install -y \
        nodejs \
        python3.11 \
        python3.11-venv && \
    # Clean up
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Configure sudo for ubuntu user
RUN echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ubuntu && \
    chmod 0440 /etc/sudoers.d/ubuntu

# Create the new directory structure and set ownership
RUN mkdir -p /opt/.manus/.sandbox-runtime && \
    chown -R ubuntu:ubuntu /opt/.manus

# Set working directory to the new path
WORKDIR /opt/.manus/.sandbox-runtime

# Copy application files to the new location
COPY --chown=ubuntu:ubuntu . .

# Switch to non-root user
USER ubuntu

# Create and configure Python virtual environment in the new location
RUN python3.11 -m venv venv && \
    ./venv/bin/pip install --no-cache-dir --upgrade pip && \
    ./venv/bin/pip install --no-cache-dir -r requirements.txt && \
    ./venv/bin/playwright install --with-deps

# Expose application port
EXPOSE 8330

# Start the application from the new location
CMD ["./venv/bin/python", "start_server.py"]