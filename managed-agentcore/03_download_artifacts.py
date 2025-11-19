#!/usr/bin/env python3
"""
Download S3 Artifacts Script

Downloads all artifacts from the most recent Deep Insight session stored in S3.
Creates a local 'artifacts/' folder in the project root with the following structure:

artifacts/
├── {session_id}/
│   ├── artifacts/     # Generated files (charts, PDFs, reports)
│   ├── data/          # Data files (CSV, input files)
│   └── debug/         # Debug info (execution logs, session status)

Usage:
    python3 download_artifacts.py [session_id]

    # Download latest session
    python3 download_artifacts.py

    # Download specific session
    python3 download_artifacts.py 2025-11-08-02-35-13
"""

import os
import sys
import boto3
from datetime import datetime
from pathlib import Path

# Configuration from .env
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'bedrock-logs-738490718699')
S3_PREFIX = 'deep-insight/fargate_sessions/'

# Local artifacts directory
ARTIFACTS_DIR = Path(__file__).parent / 'artifacts'


def load_env_vars():
    """Load environment variables from .env file"""
    env_file = Path(__file__).parent / '.env'
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

    global AWS_REGION, S3_BUCKET_NAME
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
    S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'bedrock-logs-738490718699')


def list_sessions(s3_client):
    """List all available sessions in S3"""
    try:
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET_NAME,
            Prefix=S3_PREFIX,
            Delimiter='/'
        )

        if 'CommonPrefixes' not in response:
            print("❌ No sessions found in S3")
            return []

        sessions = []
        for prefix in response['CommonPrefixes']:
            session_id = prefix['Prefix'].replace(S3_PREFIX, '').rstrip('/')
            sessions.append(session_id)

        return sorted(sessions, reverse=True)  # Most recent first

    except Exception as e:
        print(f"❌ Error listing sessions: {e}")
        return []


def download_session(s3_client, session_id):
    """Download all files for a specific session"""
    session_prefix = f"{S3_PREFIX}{session_id}/"
    local_session_dir = ARTIFACTS_DIR / session_id

    print(f"📦 Downloading session: {session_id}")
    print(f"   S3: s3://{S3_BUCKET_NAME}/{session_prefix}")
    print(f"   Local: {local_session_dir}")
    print()

    # Create local directories
    for subdir in ['artifacts', 'data', 'debug']:
        (local_session_dir / subdir).mkdir(parents=True, exist_ok=True)

    # List all objects in session
    downloaded_count = 0
    total_size = 0

    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=session_prefix)

        for page in pages:
            if 'Contents' not in page:
                continue

            for obj in page['Contents']:
                s3_key = obj['Key']

                # Extract relative path from S3 key
                relative_path = s3_key.replace(session_prefix, '')
                if not relative_path:  # Skip directory markers
                    continue

                local_file_path = local_session_dir / relative_path

                # Create parent directory
                local_file_path.parent.mkdir(parents=True, exist_ok=True)

                # Download file
                try:
                    s3_client.download_file(S3_BUCKET_NAME, s3_key, str(local_file_path))
                    file_size = obj['Size']
                    total_size += file_size
                    downloaded_count += 1

                    # Display progress
                    size_str = format_size(file_size)
                    print(f"  ✅ {relative_path} ({size_str})")

                except Exception as e:
                    print(f"  ❌ Failed to download {relative_path}: {e}")

        print()
        print(f"✅ Download complete!")
        print(f"   Files: {downloaded_count}")
        print(f"   Total size: {format_size(total_size)}")
        print(f"   Location: {local_session_dir}")

        return True

    except Exception as e:
        print(f"❌ Error downloading session: {e}")
        return False


def format_size(size_bytes):
    """Format bytes to human-readable size"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def main():
    """Main entry point"""
    # Load environment variables
    load_env_vars()

    print("=" * 60)
    print("📥 Deep Insight Artifact Downloader")
    print("=" * 60)
    print(f"Bucket: s3://{S3_BUCKET_NAME}")
    print(f"Prefix: {S3_PREFIX}")
    print(f"Region: {AWS_REGION}")
    print("=" * 60)
    print()

    # Initialize S3 client
    s3_client = boto3.client('s3', region_name=AWS_REGION)

    # Check if specific session ID provided
    if len(sys.argv) > 1:
        session_id = sys.argv[1]
        print(f"📋 Downloading specific session: {session_id}")
        print()
    else:
        # List available sessions
        print("🔍 Finding available sessions...")
        sessions = list_sessions(s3_client)

        if not sessions:
            print("❌ No sessions found in S3")
            sys.exit(1)

        print(f"✅ Found {len(sessions)} session(s)")
        print()

        # Show available sessions
        print("Available sessions:")
        for i, session in enumerate(sessions[:10], 1):  # Show latest 10
            print(f"  {i}. {session}")

        if len(sessions) > 10:
            print(f"  ... and {len(sessions) - 10} more")

        print()

        # Use most recent session
        session_id = sessions[0]
        print(f"📋 Downloading latest session: {session_id}")
        print()

    # Download session
    success = download_session(s3_client, session_id)

    if success:
        print()
        print("🎉 Artifacts downloaded successfully!")
        print(f"📁 Check the artifacts/{session_id}/ folder")
        sys.exit(0)
    else:
        print()
        print("❌ Download failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
