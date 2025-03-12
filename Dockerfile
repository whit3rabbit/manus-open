# Use Python 3.11 slim image as the base
FROM python:3.11-slim

# Set default environment variables
ENV RUNTIME_API_HOST=http://localhost
ENV CHROME_INSTANCE_PATH=/usr/bin/chromium
ENV HOME=/home/manus

# Install Chromium for browser automation and clean up APT caches
RUN apt-get update && \
    apt-get install -y chromium bash sudo && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user and add to sudoers
RUN useradd -m -s /bin/bash manus && \
    echo "manus ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/manus && \
    chmod 0440 /etc/sudoers.d/manus

# Create the target directory structure and set proper permissions
RUN mkdir -p /opt/.manus/.sandbox-runtime && \
    chown -R manus:manus /opt/.manus

# Set working directory
WORKDIR /opt/.manus/.sandbox-runtime

# Copy the repository files into the container
COPY --chown=manus:manus . /opt/.manus/.sandbox-runtime/

# Switch to non-root user
USER manus

# Create a Python virtual environment in the working directory
RUN python -m venv venv

# Upgrade pip and install Python dependencies inside the virtual environment
RUN ./venv/bin/pip install --upgrade pip && \
    ./venv/bin/pip install --no-cache-dir -r requirements.txt

# Create the secrets directory with proper permissions
RUN mkdir -p $HOME/.secrets && \
    chmod 700 $HOME/.secrets

# Expose the internal API port
EXPOSE 8330

# Use the virtual environment's Python to run the start_server.py script
CMD ["./venv/bin/python", "start_server.py"]