# Prerequisites Installation Guide

> Detailed installation instructions for all required tools

**→ Back to [Main README](../../README.md)**

---

## 📋 Required Tools

| Tool | Version | Required For | Check Command |
|------|---------|--------------|---------------|
| AWS CLI | v2.x | All phases | `aws --version` |
| Docker | 20.x+ | Phase 2 | `docker --version` |
| jq | 1.6+ | Phase 3 | `jq --version` |
| uv | 0.4+ | Phase 3 | `uv --version` |
| Python | 3.12+ | Phase 4 | `python3 --version` |

> 💡 Run `./production_deployment/scripts/check_prerequisites.sh` to verify all tools

---

## 🔧 AWS CLI v2

### Linux x86_64 (Intel/AMD)

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip -o awscliv2.zip
sudo ./aws/install --update
rm -rf awscliv2.zip aws/

# Verify
aws --version
```

### Linux ARM64 (Graviton)

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
unzip -o awscliv2.zip
sudo ./aws/install --update
rm -rf awscliv2.zip aws/

# Verify
aws --version
```

### macOS (Apple Silicon M1/M2/M3 or Intel)

```bash
curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o "AWSCLIV2.pkg"
sudo installer -pkg AWSCLIV2.pkg -target /
rm AWSCLIV2.pkg

# Verify
aws --version
```

### Configure Credentials

```bash
aws configure
# Enter: AWS Access Key ID, Secret Access Key, Region (e.g., us-west-2)

# Verify
aws sts get-caller-identity
```

---

## 🐳 Docker

### Ubuntu/Debian

```bash
# Install Docker
sudo apt-get update
sudo apt-get install -y docker.io

# Start and enable service
sudo systemctl start docker
sudo systemctl enable docker

# Add current user to docker group (run without sudo)
sudo usermod -aG docker $USER

# Apply group change (or logout/login)
newgrp docker

# Verify
docker --version
docker ps
```

### Amazon Linux 2 / RHEL

```bash
sudo yum install -y docker
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
```

### macOS

Download and install [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)

```bash
# Verify
docker --version
docker ps
```

### Troubleshooting

**"permission denied" when running docker:**
```bash
# Ensure user is in docker group
groups $USER
# Should show: ... docker ...

# If not, add and relogin
sudo usermod -aG docker $USER
# Logout and login again, or run:
newgrp docker
```

---

## 📦 jq (JSON processor)

### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install -y jq

# Verify
jq --version
```

### Amazon Linux 2 / RHEL

```bash
sudo yum install -y jq

# Verify
jq --version
```

### macOS

```bash
brew install jq

# Verify
jq --version
```

---

## 🐍 uv (Python package manager)

### All Platforms

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh

# Add to PATH (if not automatic)
export PATH="$HOME/.local/bin:$PATH"

# Verify
uv --version
```

### Alternative: pip

```bash
pip install uv

# Verify
uv --version
```

---

## 🐍 Python 3.12+

### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv

# Verify
python3.12 --version
```

### Using pyenv (Recommended for version management)

```bash
# Install pyenv
curl https://pyenv.run | bash

# Add to shell (add to ~/.bashrc or ~/.zshrc)
export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init -)"

# Install Python 3.12
pyenv install 3.12
pyenv global 3.12

# Verify
python --version
```

---

## 🛠️ Troubleshooting

### "Invalid type for parameter" during CloudFormation deployment

**Cause:** Outdated AWS CLI version

**Solution:** Update AWS CLI (see above)

### boto3/awscli version conflict in Phase 3

**Symptom:** Version resolution errors when running `02_create_uv_env.sh`

**Solution:** Edit `production_deployment/scripts/phase3/pyproject.toml`:
```diff
- "boto3==1.42.0",
+ "boto3>=1.42.1",

- "awscli==1.43.6",
+ "awscli>=1.43.7",
```

### ".env file not found" in Phase 4

**Symptom:**
```
❌ .env file not found: /home/ubuntu/.../managed-agentcore/.env
```

**Cause:** Phase 3 script `01_extract_env_vars_from_cf.sh` was not run

**Solution:**
```bash
cd production_deployment/scripts/phase3
./01_extract_env_vars_from_cf.sh prod us-west-2
```

### "jq: command not found" in Phase 3

**Cause:** jq not installed

**Solution:**
```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y jq

# Amazon Linux / RHEL
sudo yum install -y jq

# macOS
brew install jq
```

---

## ✅ Quick Verification

Run all checks at once:

```bash
echo "=== Prerequisites Check ==="
echo -n "AWS CLI: "; aws --version 2>/dev/null || echo "NOT INSTALLED"
echo -n "Docker:  "; docker --version 2>/dev/null || echo "NOT INSTALLED"
echo -n "jq:      "; jq --version 2>/dev/null || echo "NOT INSTALLED"
echo -n "uv:      "; uv --version 2>/dev/null || echo "NOT INSTALLED"
echo -n "Python:  "; python3 --version 2>/dev/null || echo "NOT INSTALLED"
echo "==========================="
```

Or use the automated script:
```bash
./production_deployment/scripts/check_prerequisites.sh
```

---

**→ Back to [Main README](../../README.md)**
