# Use Python 3.11 slim image as the base
FROM python:3.11-slim

# Set default environment variables
ENV RUNTIME_API_HOST=http://localhost
ENV CHROME_INSTANCE_PATH=/usr/bin/chromium

# Install Chromium for browser automation and clean up APT caches
RUN apt-get update && \
    apt-get install -y chromium bash sudo && \
    rm -rf /var/lib/apt/lists/*

# Create the target directory and set it as the working directory
RUN mkdir -p /opt/.manus/.sandbox-runtime
WORKDIR /opt/.manus/.sandbox-runtime

# Copy the repository files into the container
COPY . /opt/.manus/.sandbox-runtime/

# Create a Python virtual environment in the working directory
RUN python -m venv venv

# Upgrade pip and install Python dependencies inside the virtual environment
RUN ./venv/bin/pip install --upgrade pip && \
    ./venv/bin/pip install --no-cache-dir -r requirements.txt

# Create the secrets directory and generate a placeholder API key
RUN mkdir -p $HOME/.secrets && echo "dummy_api_key" > $HOME/.secrets/sandbox_api_token

# Expose the internal API port
EXPOSE 8330

# Use the virtual environment's Python to run the start_server.py script
CMD ["./venv/bin/python", "start_server.py"]
