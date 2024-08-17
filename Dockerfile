# Base image
FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Install system-level dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    libpq-dev \
    libsasl2-dev \
    libsasl2-modules \
    librdkafka-dev \
    && rm -rf /var/lib/apt/lists/*

# Set the timezone
ENV TZ=Europe/Berlin

# Upgrade pip, setuptools, and wheel
RUN pip install --upgrade pip setuptools wheel

# Copy the requirements file into the container
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
COPY . .

# Copy the config file into the container
COPY config.yaml /app/config.yaml

# Create logs directory
RUN mkdir -p /app/logs

# Create output directory
RUN mkdir -p /app/output

# Create an entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Command to run the application
ENTRYPOINT ["/app/entrypoint.sh"]
