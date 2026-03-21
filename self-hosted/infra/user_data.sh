#!/bin/bash
set -euxo pipefail

# ============================================================
# EC2 User Data — Deep Insight self-hosted setup
# Amazon Linux 2023, t3.xlarge
# ============================================================

# --- System packages ---
dnf update -y
dnf install -y git python3.12 python3.12-pip gcc python3.12-devel fontconfig

# --- Install uv (fast Python package manager) ---
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="/root/.local/bin:$PATH"

# --- Korean font for matplotlib charts ---
# AL2023: google-noto-cjk-fonts includes 80 CJK fonts
dnf install -y google-noto-cjk-fonts
fc-cache -fv

# --- Clone and setup application ---
APP_DIR="/opt/deep-insight"
mkdir -p "$APP_DIR"
cd "$APP_DIR"

# NOTE: Replace with your actual repo URL or use CodeDeploy/S3 for deployment
# git clone <your-repo-url> .
# cd self-hosted/setup
# uv sync

# --- Systemd service ---
cat > /etc/systemd/system/deep-insight.service << 'EOF'
[Unit]
Description=Deep Insight Self-Hosted
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/deep-insight/self-hosted
Environment=PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=WEB_PORT=8080
ExecStart=/root/.local/bin/uv run python -m web.app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable deep-insight.service
# systemctl start deep-insight.service  # Uncomment after deploying app code

echo "=== User data setup complete ==="
