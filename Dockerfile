# Use the official Playwright image (v1.50.0-noble) as the base
FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

# Set default environment variables (update HOME for the ubuntu user)
ENV RUNTIME_API_HOST=http://localhost
ENV CHROME_INSTANCE_PATH=/usr/bin/chromium
ENV HOME=/home/ubuntu

# Install required packages: bash, sudo, curl, bc,
# and then use NodeSource to set up Node.js 20.x
RUN apt-get update && \
    apt-get install -y bash sudo curl bc && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install software-properties-common to add PPA
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    rm -rf /var/lib/apt/lists/*

# Add Deadsnakes PPA for Python 3.11
RUN add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update

# Install Python 3.11 and its venv module
RUN apt-get install -y python3.11 python3.11-venv && \
    rm -rf /var/lib/apt/lists/*

# Add ubuntu to sudoers (the ubuntu user already exists in the base image)
RUN echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ubuntu && \
    chmod 0440 /etc/sudoers.d/ubuntu

# Set working directory; adjust as needed for your project
WORKDIR /home/ubuntu/app

# Copy the repository files into the container with proper ownership
COPY --chown=ubuntu:ubuntu . .

# Switch to the non-root user
USER ubuntu

# Create a Python virtual environment explicitly using Python 3.11
RUN python3.11 -m venv venv

# Upgrade pip and install project dependencies (including Playwright from requirements.txt)
RUN ./venv/bin/pip install --upgrade pip && \
    ./venv/bin/pip install --no-cache-dir -r requirements.txt && \
    ./venv/bin/playwright install --with-deps

# Expose the application port (adjust if needed)
EXPOSE 8330

# Use the virtual environment's Python to run your start_server.py script
CMD ["./venv/bin/python", "start_server.py"]
