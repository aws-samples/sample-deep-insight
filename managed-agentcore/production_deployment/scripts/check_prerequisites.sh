#!/bin/bash
# check_prerequisites.sh - Verify and install required tools for Deep Insight deployment
#
# Usage: ./check_prerequisites.sh [--install]
#
# Options:
#   --install    Automatically install missing packages
#
# Checks: AWS CLI v2, Docker, jq, uv, Python 3.12+

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
AUTO_INSTALL=false
if [ "$1" = "--install" ]; then
    AUTO_INSTALL=true
fi

echo "============================================"
echo "  Deep Insight Prerequisites Check"
if [ "$AUTO_INSTALL" = true ]; then
    echo "  (Auto-install mode enabled)"
fi
echo "============================================"
echo ""

MISSING_CRITICAL=0
MISSING_OPTIONAL=0

# Detect OS and architecture
detect_platform() {
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)

    if [ "$OS" = "darwin" ]; then
        PLATFORM="macos"
    elif [ "$OS" = "linux" ]; then
        if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
            PLATFORM="linux-arm64"
        else
            PLATFORM="linux-x86_64"
        fi
    else
        PLATFORM="unknown"
    fi
    echo "$PLATFORM"
}

PLATFORM=$(detect_platform)
echo -e "${BLUE}Detected platform:${NC} $PLATFORM"
echo ""

# Function to install jq
install_jq() {
    echo -e "${BLUE}Installing jq...${NC}"
    if [ "$PLATFORM" = "macos" ]; then
        brew install jq
    else
        sudo apt-get update && sudo apt-get install -y jq
    fi
}

# Function to install uv
install_uv() {
    echo -e "${BLUE}Installing uv...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
}

# Function to install Docker
install_docker() {
    echo -e "${BLUE}Installing Docker...${NC}"
    if [ "$PLATFORM" = "macos" ]; then
        echo "Please install Docker Desktop from: https://docs.docker.com/desktop/install/mac-install/"
        return 1
    else
        sudo apt-get update
        sudo apt-get install -y docker.io
        sudo systemctl start docker
        sudo systemctl enable docker
        sudo usermod -aG docker $USER
        echo -e "${YELLOW}Note: You may need to log out and back in for Docker group changes to take effect.${NC}"
    fi
}

# Function to install AWS CLI
install_aws_cli() {
    echo -e "${BLUE}Installing AWS CLI v2...${NC}"
    local tmpdir=$(mktemp -d)
    cd "$tmpdir"

    if [ "$PLATFORM" = "macos" ]; then
        curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o "AWSCLIV2.pkg"
        sudo installer -pkg AWSCLIV2.pkg -target /
    elif [ "$PLATFORM" = "linux-arm64" ]; then
        curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
        unzip -o awscliv2.zip
        sudo ./aws/install --update
    else
        curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
        unzip -o awscliv2.zip
        sudo ./aws/install --update
    fi

    cd - > /dev/null
    rm -rf "$tmpdir"
}

# Function to install Python 3.12
install_python() {
    echo -e "${BLUE}Installing Python 3.12...${NC}"
    if [ "$PLATFORM" = "macos" ]; then
        brew install python@3.12
    else
        sudo apt-get update
        sudo apt-get install -y python3.12 python3.12-venv
    fi
}

# Function to check and optionally install
check_and_install() {
    local cmd=$1
    local name=$2
    local required_for=$3
    local install_func=$4
    local is_critical=${5:-true}

    if command -v "$cmd" &> /dev/null; then
        version=$($cmd --version 2>&1 | head -n1)
        echo -e "${GREEN}✅ $name${NC}: $version"
        return 0
    else
        if [ "$is_critical" = true ]; then
            echo -e "${RED}❌ $name${NC}: NOT INSTALLED (Required for: $required_for)"
            MISSING_CRITICAL=$((MISSING_CRITICAL + 1))
        else
            echo -e "${YELLOW}⚠️  $name${NC}: NOT INSTALLED (Required for: $required_for)"
            MISSING_OPTIONAL=$((MISSING_OPTIONAL + 1))
        fi

        if [ "$AUTO_INSTALL" = true ] && [ -n "$install_func" ]; then
            $install_func
            if command -v "$cmd" &> /dev/null; then
                echo -e "${GREEN}✅ $name installed successfully${NC}"
                MISSING_CRITICAL=$((MISSING_CRITICAL - 1))
                return 0
            fi
        fi
        return 1
    fi
}

# Function to check Python version
check_python_version() {
    if command -v python3 &> /dev/null; then
        version=$(python3 --version 2>&1 | awk '{print $2}')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)

        if [ "$major" -ge 3 ] && [ "$minor" -ge 12 ]; then
            echo -e "${GREEN}✅ Python${NC}: $version"
            return 0
        else
            echo -e "${RED}❌ Python${NC}: $version (Required: 3.12+)"
            MISSING_CRITICAL=$((MISSING_CRITICAL + 1))

            if [ "$AUTO_INSTALL" = true ]; then
                install_python
                # Re-check after install
                if command -v python3.12 &> /dev/null; then
                    echo -e "${GREEN}✅ Python 3.12 installed successfully${NC}"
                    MISSING_CRITICAL=$((MISSING_CRITICAL - 1))
                    return 0
                fi
            fi
            return 1
        fi
    else
        echo -e "${RED}❌ Python${NC}: NOT INSTALLED (Required: 3.12+)"
        MISSING_CRITICAL=$((MISSING_CRITICAL + 1))

        if [ "$AUTO_INSTALL" = true ]; then
            install_python
            if command -v python3 &> /dev/null || command -v python3.12 &> /dev/null; then
                echo -e "${GREEN}✅ Python installed successfully${NC}"
                MISSING_CRITICAL=$((MISSING_CRITICAL - 1))
                return 0
            fi
        fi
        return 1
    fi
}

# Function to check AWS CLI version
check_aws_cli_version() {
    if command -v aws &> /dev/null; then
        version=$(aws --version 2>&1 | awk '{print $1}' | cut -d/ -f2)
        major=$(echo "$version" | cut -d. -f1)

        if [ "$major" -ge 2 ]; then
            echo -e "${GREEN}✅ AWS CLI${NC}: $version"
            return 0
        else
            echo -e "${RED}❌ AWS CLI${NC}: $version (Required: v2.x)"
            MISSING_CRITICAL=$((MISSING_CRITICAL + 1))

            if [ "$AUTO_INSTALL" = true ]; then
                install_aws_cli
                if aws --version 2>&1 | grep -q "aws-cli/2"; then
                    echo -e "${GREEN}✅ AWS CLI v2 installed successfully${NC}"
                    MISSING_CRITICAL=$((MISSING_CRITICAL - 1))
                    return 0
                fi
            fi
            return 1
        fi
    else
        echo -e "${RED}❌ AWS CLI${NC}: NOT INSTALLED"
        MISSING_CRITICAL=$((MISSING_CRITICAL + 1))

        if [ "$AUTO_INSTALL" = true ]; then
            install_aws_cli
            if command -v aws &> /dev/null; then
                echo -e "${GREEN}✅ AWS CLI installed successfully${NC}"
                MISSING_CRITICAL=$((MISSING_CRITICAL - 1))
                return 0
            fi
        fi
        return 1
    fi
}

# Function to check Docker is running
check_docker_running() {
    if command -v docker &> /dev/null; then
        version=$(docker --version 2>&1 | awk '{print $3}' | tr -d ',')
        if docker ps &> /dev/null; then
            echo -e "${GREEN}✅ Docker${NC}: $version (running)"
            return 0
        else
            echo -e "${YELLOW}⚠️  Docker${NC}: $version (not running or no permission)"
            echo "   Fix: sudo systemctl start docker && sudo usermod -aG docker \$USER && newgrp docker"
            MISSING_OPTIONAL=$((MISSING_OPTIONAL + 1))
            return 1
        fi
    else
        echo -e "${RED}❌ Docker${NC}: NOT INSTALLED (Required for: Phase 2)"
        MISSING_CRITICAL=$((MISSING_CRITICAL + 1))

        if [ "$AUTO_INSTALL" = true ]; then
            install_docker
            if command -v docker &> /dev/null; then
                echo -e "${GREEN}✅ Docker installed successfully${NC}"
                MISSING_CRITICAL=$((MISSING_CRITICAL - 1))
                return 0
            fi
        fi
        return 1
    fi
}

echo "Checking required tools..."
echo ""

# Check all prerequisites
check_aws_cli_version
check_docker_running
check_and_install "jq" "jq" "Phase 3" "install_jq"
check_and_install "uv" "uv" "Phase 3" "install_uv"
check_python_version

echo ""
echo "============================================"

# Check AWS credentials
echo ""
echo "Checking AWS credentials..."
if command -v aws &> /dev/null && aws sts get-caller-identity &> /dev/null; then
    account=$(aws sts get-caller-identity --query Account --output text)
    region=$(aws configure get region 2>/dev/null || echo "not set")
    echo -e "${GREEN}✅ AWS credentials${NC}: Account $account, Region: $region"
else
    echo -e "${YELLOW}⚠️  AWS credentials${NC}: Not configured or invalid"
    echo "   Run: aws configure"
    MISSING_OPTIONAL=$((MISSING_OPTIONAL + 1))
fi

echo ""
echo "============================================"

# Summary
if [ $MISSING_CRITICAL -eq 0 ] && [ $MISSING_OPTIONAL -eq 0 ]; then
    echo -e "${GREEN}All prerequisites satisfied!${NC}"
    echo "You can proceed with deployment."
    exit 0
elif [ $MISSING_CRITICAL -eq 0 ]; then
    echo -e "${YELLOW}$MISSING_OPTIONAL optional issue(s) found.${NC}"
    echo "You may proceed, but some features might not work."
    exit 0
else
    echo -e "${RED}$MISSING_CRITICAL critical tool(s) missing.${NC}"
    echo ""
    if [ "$AUTO_INSTALL" = false ]; then
        echo "Run with --install to automatically install missing tools:"
        echo "  ./check_prerequisites.sh --install"
        echo ""
    fi
    echo "Or see detailed installation guide:"
    echo "  production_deployment/docs/PREREQUISITES.md"
    exit 1
fi
