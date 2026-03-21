#!/bin/bash
# CloudWatch Logs Agent setup for Deep Insight EC2
# Run via SSM after EC2 is provisioned

set -euxo pipefail

# Install CloudWatch Agent
dnf install -y amazon-cloudwatch-agent

# Create config
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << 'EOF'
{
  "logs": {
    "logs_collected": {
      "journald": {
        "units": ["deep-insight"],
        "collect_list": [
          {
            "unit": "deep-insight",
            "log_group_name": "/deep-insight/app",
            "log_stream_name": "{instance_id}",
            "retention_in_days": 14
          }
        ]
      }
    }
  }
}
EOF

# Start agent
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json -s

systemctl enable amazon-cloudwatch-agent
echo "CloudWatch Agent configured"
