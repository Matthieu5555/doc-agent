# Documentation Agent Environment
FROM python:3.12-slim

# Install system dependencies for OpenHands
RUN apt-get update && apt-get install -y \
    git \
    curl \
    tree \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv (modern Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Create workspace
WORKDIR /workspace

# Copy Python project files to temp location
COPY pyproject.toml uv.lock /tmp/

# Install dependencies with uv in a persistent location
RUN cd /tmp && uv sync --no-install-project && \
    cp -r .venv /opt/venv

# Add venv to PATH
ENV PATH="/opt/venv/bin:$PATH"
ENV VIRTUAL_ENV="/opt/venv"

# Set up git config
RUN git config --global user.email "agent@autodoc.local" && \
    git config --global user.name "AutoDoc Agent"

CMD ["tail", "-f", "/dev/null"]
