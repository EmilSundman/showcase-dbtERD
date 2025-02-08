FROM python:3.11-slim

# Install system dependencies including Graphviz and curl
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    graphviz \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv using pip
RUN pip install uv

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies using uv with --system flag
RUN uv pip install --system --no-cache -r requirements.txt

# Copy application files
COPY . .

# Expose the port Streamlit runs on
EXPOSE 1000

# Set environment variables for Streamlit
ENV STREAMLIT_SERVER_PORT=1000
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

# Command to run the application
CMD ["streamlit", "run", "app.py"] 