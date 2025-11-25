# ==============================================================================
# Fargate Runtime Container - Code Executor Server
# ==============================================================================
#
# Docker image for AWS Fargate container that executes Python/Bash code
# dynamically via HTTP API. This container runs a Flask server that receives
# code execution requests from the AgentCore Runtime.
#
# Base Image: Python 3.12-slim
# Architecture: Multi-agent workflow execution environment
#
# Key Features:
#   - Flask HTTP server for code execution
#   - Korean font support (NanumGothic)
#   - Data visualization libraries (matplotlib, seaborn, plotly)
#   - PDF generation support (weasyprint)
#   - AWS SDK integration (boto3)
#   - Session-based execution with S3 result storage
#
# Network: Private VPC with ALB routing
# Storage: Ephemeral container storage + S3 for results
# ==============================================================================

FROM python:3.12-slim

WORKDIR /app

# Update system packages and install essential tools
RUN apt-get update && apt-get install -y \
    # Korean fonts
    fonts-nanum \
    # Font management
    fontconfig \
    # pandoc and texlive (for document conversion)
    pandoc \
    texlive \
    texlive-xetex \
    texlive-fonts-recommended \
    # PDF processing
    poppler-utils \
    # Other useful tools
    curl \
    && rm -rf /var/lib/apt/lists/*

# Refresh font cache
RUN fc-cache -f -v

# Copy requirements.txt for Python packages installation
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Clear matplotlib font cache
RUN python -c "import matplotlib.font_manager as fm; fm.get_font_names()" || true

# Copy application code
COPY code_executor_server.py .

# Data files are provided via dynamic upload only (not copied in Dockerfile)

# Set environment variables
# Note: AWS_REGION and S3_BUCKET_NAME are passed at runtime via ECS task overrides
ENV PYTHONUNBUFFERED=1
ENV ENV_NAME=production

# Run Python script when container starts
CMD ["python", "-u", "code_executor_server.py"]
