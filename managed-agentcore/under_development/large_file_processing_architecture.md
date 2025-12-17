# Large File Processing Architecture (DataPipeline Agent)

> **Status**: Under Development
> **Created**: 2025-12-10
> **Last Updated**: 2025-12-10

## Overview

This document outlines the architecture for processing large files (10GB+) using PySpark/AWS Glue, integrated with the existing Deep Insight multi-agent framework.

### Proposed Workflow

```
Large Dataset (10GB+)
    → PII Removal
    → PySpark Processing
    → Preprocessed Dataset
    → CSV Conversion
    → Deep Insight Execution
    → DOCX Report
```

---

## Architecture Decisions

| Component | Decision | Rationale |
|-----------|----------|-----------|
| **Compute** | AWS Glue | Fully managed, scales to TB, native PySpark, serverless |
| **PII Handling** | Presidio in PySpark | Flexible, customizable, open-source, runs in Glue workers |
| **Data Source** | S3 User Upload | Simple, scalable, supports Parquet/CSV/JSON |
| **Agent Pattern** | New DataPipeline Agent | Clean separation, specialized prompts, clear handoff |
| **Output** | Sampled/Aggregated CSV | Fits existing Coder → Reporter flow |
| **Deployment Model** | On-Demand Module Loading | Glue resources only created when explicitly enabled |

---

## Deployment Strategy: On-Demand Module Loading

### Problem Statement

The existing Deep Insight system uses environment variables for Fargate-based tools (Coder, Validator, Reporter). If DataPipeline Agent with Glue integration is bundled as a standard tool, the Glue-related environment variables and CloudFormation resources would be required even when most tasks don't need large file processing.

**Current Setup (17 env vars for Fargate):**
```bash
FARGATE_SUBNET_IDS=subnet-xxx,subnet-yyy
FARGATE_SECURITY_GROUP_IDS=sg-xxx
ECS_CLUSTER_NAME=deep-insight-cluster
TASK_DEFINITION_ARN=arn:aws:ecs:...
ALB_DNS=internal-deep-insight-alb-xxx.us-west-2.elb.amazonaws.com
# ... 12 more vars
```

**With Always-On Glue (adds 6+ env vars):**
```bash
# All Fargate vars above PLUS:
GLUE_JOB_NAME=deep-insight-etl-prod
GLUE_SCRIPT_BUCKET=deep-insight-glue-scripts-xxx
GLUE_OUTPUT_BUCKET=deep-insight-glue-output-xxx
GLUE_JOB_ROLE_ARN=arn:aws:iam::...
GLUE_WORKER_TYPE=G.1X
GLUE_NUM_WORKERS=10
```

**Issues with Always-On:**
1. Unnecessary complexity for most use cases (90%+ don't need Glue)
2. CloudFormation must deploy Glue resources even if unused
3. S3 buckets and IAM roles exist even when idle
4. More configuration to manage and troubleshoot

### Solution: On-Demand Module Loading

Glue resources are only deployed when explicitly enabled via a deployment flag.

```
┌─────────────────────────────────────────────────────────────────┐
│ Standard Deployment (Default)                                    │
│ ./deploy_phase1_phase2.sh prod us-west-2                        │
│                                                                  │
│ Components:                                                      │
│ ├── VPC, ALB, Security Groups                                   │
│ ├── Fargate (Coder, Validator, Reporter)                        │
│ └── S3 Artifact Bucket                                          │
│                                                                  │
│ Tools Available: Coder, Validator, Reporter, Tracker            │
│ Env Vars: 17 (Fargate only)                                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Extended Deployment (Opt-in)                                     │
│ ./deploy_phase1_phase2.sh prod us-west-2 --enable-glue          │
│                                                                  │
│ Components:                                                      │
│ ├── Everything from Standard                                    │
│ ├── AWS Glue Job + IAM Role                                     │
│ ├── Glue Script Bucket                                          │
│ └── Glue Output Bucket                                          │
│                                                                  │
│ Tools Available: Coder, Validator, Reporter, Tracker,           │
│                  DataPipeline (NEW)                              │
│ Env Vars: 17 + 6 = 23                                           │
└─────────────────────────────────────────────────────────────────┘
```

### Implementation Details

#### 1. Conditional CloudFormation Parameter

```yaml
# phase1-infrastructure.yaml (modified)

Parameters:
  EnableGlueIntegration:
    Type: String
    Default: 'false'
    AllowedValues: ['true', 'false']
    Description: 'Enable AWS Glue for large file processing (10GB+)'

Conditions:
  GlueEnabled: !Equals [!Ref EnableGlueIntegration, 'true']

Resources:
  # Glue resources only created when enabled
  GlueScriptBucket:
    Type: AWS::S3::Bucket
    Condition: GlueEnabled
    Properties:
      BucketName: !Sub '${ProjectName}-glue-scripts-${AWS::AccountId}-${AWS::Region}'
      # ... rest of bucket config

  GlueJobRole:
    Type: AWS::IAM::Role
    Condition: GlueEnabled
    Properties:
      RoleName: !Sub '${ProjectName}-glue-job-role-${Environment}'
      # ... rest of role config

  DeepInsightETLJob:
    Type: AWS::Glue::Job
    Condition: GlueEnabled
    Properties:
      Name: !Sub '${ProjectName}-etl-${Environment}'
      # ... rest of job config

Outputs:
  GlueJobName:
    Condition: GlueEnabled
    Description: Name of the Glue ETL job
    Value: !Ref DeepInsightETLJob

  GlueEnabled:
    Description: Whether Glue integration is enabled
    Value: !Ref EnableGlueIntegration
```

#### 2. Deployment Script with Flag

```bash
#!/bin/bash
# deploy_phase1_phase2.sh (modified)

# Default values
ENABLE_GLUE="false"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --enable-glue)
      ENABLE_GLUE="true"
      echo "Glue integration ENABLED"
      shift
      ;;
    *)
      # Handle other arguments (env, region, etc.)
      shift
      ;;
  esac
done

# Deploy Phase 1 with conditional Glue parameter
aws cloudformation deploy \
  --stack-name "${PROJECT_NAME}-infrastructure-${ENV}" \
  --template-file ../cloudformation/phase1-infrastructure.yaml \
  --parameter-overrides \
    Environment=$ENV \
    EnableGlueIntegration=$ENABLE_GLUE \
  --capabilities CAPABILITY_NAMED_IAM \
  --region $REGION

echo "Deployment complete. Glue enabled: $ENABLE_GLUE"
```

#### 3. Environment Variable Extraction (Conditional)

```bash
#!/bin/bash
# phase3/01_extract_env_vars_from_cf.sh (modified)

# ... existing env var extraction ...

# Check if Glue is enabled
GLUE_ENABLED=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='GlueEnabled'].OutputValue" \
  --output text 2>/dev/null || echo "false")

echo "" >> .env
echo "# Glue Integration" >> .env
echo "GLUE_ENABLED=$GLUE_ENABLED" >> .env

if [ "$GLUE_ENABLED" = "true" ]; then
  echo "# Glue Configuration (Large File Processing)" >> .env
  echo "GLUE_JOB_NAME=$(get_output GlueJobName)" >> .env
  echo "GLUE_SCRIPT_BUCKET=$(get_output GlueScriptBucketName)" >> .env
  echo "GLUE_OUTPUT_BUCKET=$(get_output GlueOutputBucketName)" >> .env
  echo "GLUE_JOB_ROLE_ARN=$(get_output GlueJobRoleArn)" >> .env
  echo "GLUE_WORKER_TYPE=G.1X" >> .env
  echo "GLUE_NUM_WORKERS=10" >> .env
  echo "GLUE_TIMEOUT_MINUTES=60" >> .env
  echo "Glue environment variables extracted."
else
  echo "Glue integration not enabled. Skipping Glue env vars."
fi
```

#### 4. Runtime Tool Registration (Conditional)

```python
# src/graph/nodes.py (modified)

import os
from typing import List

def get_supervisor_tools() -> List:
    """
    Return available tools based on deployment configuration.
    Tools are conditionally loaded based on environment variables.
    """
    from src.tools.coder_agent_fargate_tool import coder_agent_tool
    from src.tools.validator_agent_tool import validator_agent_tool
    from src.tools.reporter_agent_tool import reporter_agent_tool
    from src.tools.tracker_agent_tool import tracker_agent_tool

    # Core tools (always available)
    tools = [
        coder_agent_tool,
        validator_agent_tool,
        reporter_agent_tool,
        tracker_agent_tool,
    ]

    # Glue/DataPipeline tools (only if enabled)
    glue_enabled = os.getenv("GLUE_ENABLED", "false").lower() == "true"

    if glue_enabled:
        try:
            from src.tools.data_pipeline_agent_tool import data_pipeline_agent_tool
            tools.append(data_pipeline_agent_tool)
            print("[INFO] DataPipeline Agent enabled (Glue integration active)")
        except ImportError as e:
            print(f"[WARNING] Failed to load DataPipeline Agent: {e}")
    else:
        print("[INFO] DataPipeline Agent disabled (Glue integration not enabled)")

    return tools
```

#### 5. Supervisor Prompt (Conditional Awareness)

```python
# src/graph/nodes.py - supervisor node creation

def create_supervisor_node():
    glue_enabled = os.getenv("GLUE_ENABLED", "false").lower() == "true"

    # Base supervisor prompt
    system_prompt = load_prompt("supervisor")

    # Add Glue-specific instructions if enabled
    if glue_enabled:
        glue_instructions = """

## DataPipeline Agent (Large File Processing)

You have access to the DataPipeline Agent for processing large files (10GB+).

**When to use DataPipeline Agent:**
- User provides S3 URI to large file (>1GB recommended, required for >10GB)
- Data contains PII that needs anonymization before analysis
- Data needs aggregation/sampling to reduce size for Coder Agent

**DataPipeline Agent workflow:**
1. Validates S3 source (format, size)
2. Removes PII using Presidio
3. Aggregates/samples data as needed
4. Outputs manageable CSV for Coder Agent analysis

**Example handoff:**
- DataPipeline outputs: s3://output/preprocessed/data.csv (50MB)
- Coder Agent inputs: the preprocessed CSV for pandas analysis
"""
        system_prompt += glue_instructions

    return Agent(
        model_id=SUPERVISOR_MODEL_ID,
        system_prompt=system_prompt,
        tools=get_supervisor_tools()
    )
```

### Resulting Environment Files

**Standard .env (Glue disabled):**
```bash
# Fargate Configuration
FARGATE_SUBNET_IDS=subnet-xxx,subnet-yyy
FARGATE_SECURITY_GROUP_IDS=sg-xxx
ECS_CLUSTER_NAME=deep-insight-cluster-prod
TASK_DEFINITION_ARN=arn:aws:ecs:us-west-2:123456789012:task-definition/deep-insight-task:1
CONTAINER_NAME=dynamic-executor
ALB_DNS=internal-deep-insight-alb-xxx.us-west-2.elb.amazonaws.com
ALB_TARGET_GROUP_ARN=arn:aws:elasticloadbalancing:...
S3_BUCKET_NAME=deep-insight-artifacts-xxx
# ... other Fargate vars

# Glue Integration
GLUE_ENABLED=false
# (No Glue-specific vars)
```

**Extended .env (Glue enabled):**
```bash
# Fargate Configuration
FARGATE_SUBNET_IDS=subnet-xxx,subnet-yyy
FARGATE_SECURITY_GROUP_IDS=sg-xxx
ECS_CLUSTER_NAME=deep-insight-cluster-prod
TASK_DEFINITION_ARN=arn:aws:ecs:us-west-2:123456789012:task-definition/deep-insight-task:1
CONTAINER_NAME=dynamic-executor
ALB_DNS=internal-deep-insight-alb-xxx.us-west-2.elb.amazonaws.com
ALB_TARGET_GROUP_ARN=arn:aws:elasticloadbalancing:...
S3_BUCKET_NAME=deep-insight-artifacts-xxx
# ... other Fargate vars

# Glue Integration
GLUE_ENABLED=true

# Glue Configuration (Large File Processing)
GLUE_JOB_NAME=deep-insight-etl-prod
GLUE_SCRIPT_BUCKET=deep-insight-glue-scripts-123456789012-us-west-2
GLUE_OUTPUT_BUCKET=deep-insight-glue-output-123456789012-us-west-2
GLUE_JOB_ROLE_ARN=arn:aws:iam::123456789012:role/deep-insight-glue-job-role-prod
GLUE_WORKER_TYPE=G.1X
GLUE_NUM_WORKERS=10
GLUE_TIMEOUT_MINUTES=60
```

### Deployment Comparison

| Aspect | Standard Deployment | Extended Deployment (--enable-glue) |
|--------|---------------------|-------------------------------------|
| **Command** | `./deploy.sh prod us-west-2` | `./deploy.sh prod us-west-2 --enable-glue` |
| **CloudFormation Resources** | VPC, ALB, Fargate, S3 | + Glue Job, Glue Buckets, Glue IAM |
| **Environment Variables** | 17 | 17 + 6 = 23 |
| **Available Tools** | Coder, Validator, Reporter, Tracker | + DataPipeline |
| **Monthly Base Cost** | ~$56-93 | ~$56-93 (Glue pay-per-use) |
| **Use Case** | Small-medium files (<10GB) | Any file size |

### Upgrade Path

Users can upgrade from Standard to Extended deployment:

```bash
# Step 1: Update CloudFormation with Glue enabled
cd production_deployment/scripts
./deploy_phase1_phase2.sh prod us-west-2 --enable-glue

# Step 2: Re-extract environment variables
cd phase3
./01_extract_env_vars_from_cf.sh prod us-west-2

# Step 3: Rebuild runtime (optional - if using AgentCore)
cd ../../../
uv run 01_create_agentcore_runtime_vpc.py
```

### Downgrade Path

Users can disable Glue to reduce complexity:

```bash
# Step 1: Update CloudFormation with Glue disabled
./deploy_phase1_phase2.sh prod us-west-2  # No --enable-glue flag

# Step 2: Re-extract environment variables
./01_extract_env_vars_from_cf.sh prod us-west-2

# Note: Glue S3 buckets will be deleted (ensure no needed data remains)
```

---

## System Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User Query                                   │
│  "Analyze this 15GB dataset at s3://bucket/large-data.parquet"      │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         COORDINATOR                                  │
│  Detects: Large file reference → Routes to Planner                  │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          PLANNER                                     │
│  Creates multi-phase plan:                                          │
│  1. DataPipeline: S3 → PII Removal → PySpark → Preprocessed CSV     │
│  2. Analysis: Preprocessed CSV → Deep Insight Analysis              │
│  3. Report: Generate DOCX with insights                             │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         SUPERVISOR                                   │
│                              │                                       │
│    ┌─────────────────────────┼─────────────────────────┐            │
│    │                         │                         │            │
│    ▼                         ▼                         ▼            │
│ ┌──────────────┐    ┌──────────────┐    ┌──────────────┐           │
│ │ DataPipeline │    │    Coder     │    │   Reporter   │           │
│ │    Agent     │    │    Agent     │    │    Agent     │           │
│ │   (NEW)      │    │  (existing)  │    │  (existing)  │           │
│ └──────────────┘    └──────────────┘    └──────────────┘           │
│        │                   │                   │                    │
│        ▼                   ▼                   ▼                    │
│   AWS Glue Job      Fargate Container    Fargate Container         │
│   (PySpark)         (Python analysis)    (DOCX generation)         │
└─────────────────────────────────────────────────────────────────────┘
```

### Agent Hierarchy (Updated)

```
User Query
    ↓
COORDINATOR (Entry Point)
  - Handles initial requests
  - Detects large file references (S3 URIs, file size mentions)
  - Routes complex data tasks to Planner
  - Model: Claude Sonnet 4 (no reasoning)
    ↓ (if complex/large data)
PLANNER (Strategic Thinking)
  - Analyzes task complexity
  - Creates multi-phase execution plan
  - Determines if DataPipeline Agent is needed
  - Model: Claude Sonnet 4 (reasoning enabled)
    ↓
SUPERVISOR (Task Orchestrator)
  - Delegates to specialized tool agents
  - Monitors progress and coordinates workflow
  - Aggregates results from multiple agents
  - Model: Claude Sonnet 4 (prompt caching)
    ↓
TOOL AGENTS:
  - DataPipeline Agent (NEW) - Large file ETL via AWS Glue
  - Coder Agent - Python/Bash execution (Fargate)
  - Validator Agent - Quality validation
  - Reporter Agent - DOCX generation
  - Tracker Agent - Progress monitoring
```

---

## DataPipeline Agent Design

### Component Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    DataPipeline Agent                            │
│                                                                  │
│  Prompts: src/prompts/data_pipeline_agent.md                    │
│  Tool: src/tools/data_pipeline_agent_tool.py                    │
│                                                                  │
│  Responsibilities:                                               │
│  1. Validate S3 source (exists, size, format)                   │
│  2. Generate PII detection/removal PySpark code                 │
│  3. Generate transformation/aggregation PySpark code            │
│  4. Submit AWS Glue job                                         │
│  5. Monitor job completion                                      │
│  6. Return output S3 path (CSV) for downstream processing       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    GlueJobController                             │
│           src/tools/glue_job_controller.py                       │
│                                                                  │
│  Similar pattern to FargateContainerController:                  │
│  - create_glue_job() → Start job                                │
│  - get_job_status() → Poll for completion                       │
│  - get_job_output() → Retrieve S3 output path                   │
│  - terminate_job() → Cancel if needed                           │
└─────────────────────────────────────────────────────────────────┘
```

### GlueJobController Interface

```python
# src/tools/glue_job_controller.py

import boto3
import os
import time
from typing import Optional, Dict, Any

class GlueJobController:
    """
    Manages AWS Glue job lifecycle for large file processing.
    Follows similar patterns to FargateContainerController.
    """

    def __init__(self):
        self.glue_client = boto3.client('glue')
        self.s3_client = boto3.client('s3')

        # Environment variables (set by CloudFormation)
        self.job_name = os.getenv("GLUE_JOB_NAME", "deep-insight-etl")
        self.script_bucket = os.getenv("GLUE_SCRIPT_BUCKET")
        self.output_bucket = os.getenv("GLUE_OUTPUT_BUCKET")
        self.worker_type = os.getenv("GLUE_WORKER_TYPE", "G.1X")
        self.num_workers = int(os.getenv("GLUE_NUM_WORKERS", "10"))
        self.timeout_minutes = int(os.getenv("GLUE_TIMEOUT_MINUTES", "60"))

    def upload_script(self, pyspark_code: str, script_name: str) -> str:
        """
        Upload generated PySpark script to S3.

        Args:
            pyspark_code: The PySpark code to execute
            script_name: Unique name for the script file

        Returns:
            S3 URI of the uploaded script
        """
        script_key = f"scripts/{script_name}.py"
        self.s3_client.put_object(
            Bucket=self.script_bucket,
            Key=script_key,
            Body=pyspark_code.encode('utf-8')
        )
        return f"s3://{self.script_bucket}/{script_key}"

    def submit_job(
        self,
        input_s3_path: str,
        output_s3_path: str,
        pyspark_code: str,
        job_name_suffix: str = "",
        worker_type: Optional[str] = None,
        num_workers: Optional[int] = None,
        timeout_minutes: Optional[int] = None
    ) -> str:
        """
        Submit a Glue job with the provided PySpark code.

        Args:
            input_s3_path: S3 path to input data
            output_s3_path: S3 path for output data
            pyspark_code: PySpark code to execute
            job_name_suffix: Optional suffix for job identification
            worker_type: Override default worker type (G.1X, G.2X, etc.)
            num_workers: Override default number of workers
            timeout_minutes: Override default timeout

        Returns:
            Job run ID
        """
        # Upload script to S3
        script_name = f"etl_{job_name_suffix}_{int(time.time())}"
        script_location = self.upload_script(pyspark_code, script_name)

        # Start Glue job
        response = self.glue_client.start_job_run(
            JobName=self.job_name,
            Arguments={
                '--INPUT_PATH': input_s3_path,
                '--OUTPUT_PATH': output_s3_path,
                '--scriptLocation': script_location,
            },
            WorkerType=worker_type or self.worker_type,
            NumberOfWorkers=num_workers or self.num_workers,
            Timeout=timeout_minutes or self.timeout_minutes
        )

        return response['JobRunId']

    def get_job_status(self, job_run_id: str) -> Dict[str, Any]:
        """
        Get the current status of a Glue job run.

        Args:
            job_run_id: The job run ID

        Returns:
            Dictionary with status information
        """
        response = self.glue_client.get_job_run(
            JobName=self.job_name,
            RunId=job_run_id
        )

        job_run = response['JobRun']
        return {
            'status': job_run['JobRunState'],
            'started_on': job_run.get('StartedOn'),
            'completed_on': job_run.get('CompletedOn'),
            'execution_time': job_run.get('ExecutionTime'),
            'error_message': job_run.get('ErrorMessage'),
            'dpu_seconds': job_run.get('DPUSeconds')
        }

    def wait_for_completion(
        self,
        job_run_id: str,
        poll_interval: int = 30,
        max_wait_seconds: int = 3600
    ) -> Dict[str, Any]:
        """
        Wait for a Glue job to complete.

        Args:
            job_run_id: The job run ID
            poll_interval: Seconds between status checks
            max_wait_seconds: Maximum time to wait

        Returns:
            Final status dictionary
        """
        terminal_states = ['SUCCEEDED', 'FAILED', 'STOPPED', 'TIMEOUT']
        elapsed = 0

        while elapsed < max_wait_seconds:
            status = self.get_job_status(job_run_id)

            if status['status'] in terminal_states:
                return status

            time.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(f"Glue job {job_run_id} did not complete within {max_wait_seconds}s")

    def get_output_metadata(self, output_s3_path: str) -> Dict[str, Any]:
        """
        Get metadata about the output files.

        Args:
            output_s3_path: S3 path to output data

        Returns:
            Dictionary with file count, total size, etc.
        """
        bucket, prefix = self._parse_s3_path(output_s3_path)

        paginator = self.s3_client.get_paginator('list_objects_v2')
        total_size = 0
        file_count = 0

        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                total_size += obj['Size']
                file_count += 1

        return {
            'output_path': output_s3_path,
            'file_count': file_count,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2)
        }

    def terminate_job(self, job_run_id: str) -> bool:
        """
        Stop a running Glue job.

        Args:
            job_run_id: The job run ID

        Returns:
            True if successfully stopped
        """
        try:
            self.glue_client.batch_stop_job_run(
                JobName=self.job_name,
                JobRunIds=[job_run_id]
            )
            return True
        except Exception as e:
            print(f"Failed to stop job {job_run_id}: {e}")
            return False

    def _parse_s3_path(self, s3_path: str) -> tuple:
        """Parse s3://bucket/key into (bucket, key)"""
        path = s3_path.replace("s3://", "")
        parts = path.split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        return bucket, key
```

---

## PII Removal with Presidio

### PySpark Template for PII Detection/Removal

```python
# glue-scripts/pii_removal_template.py

"""
PySpark script template for PII detection and removal using Presidio.
This script is dynamically generated by the DataPipeline Agent.
"""

import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql.functions import udf, col
from pyspark.sql.types import StringType

# Initialize Glue context
args = getResolvedOptions(sys.argv, ['JOB_NAME', 'INPUT_PATH', 'OUTPUT_PATH'])
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Import Presidio (installed via --additional-python-modules)
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

# Initialize Presidio engines (broadcast to workers for efficiency)
analyzer_broadcast = sc.broadcast(AnalyzerEngine())
anonymizer_broadcast = sc.broadcast(AnonymizerEngine())

def anonymize_text(text: str) -> str:
    """
    Anonymize PII in text using Presidio.

    Detected entities:
    - PERSON (names)
    - EMAIL_ADDRESS
    - PHONE_NUMBER
    - CREDIT_CARD
    - US_SSN
    - IP_ADDRESS
    - LOCATION
    - DATE_TIME
    """
    if text is None or text == "":
        return text

    try:
        analyzer = analyzer_broadcast.value
        anonymizer = anonymizer_broadcast.value

        # Analyze text for PII
        results = analyzer.analyze(
            text=str(text),
            language='en',
            entities=[
                "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
                "CREDIT_CARD", "US_SSN", "IP_ADDRESS",
                "LOCATION", "DATE_TIME"
            ]
        )

        if not results:
            return text

        # Anonymize detected PII
        anonymized = anonymizer.anonymize(
            text=str(text),
            analyzer_results=results
        )

        return anonymized.text

    except Exception as e:
        # Log error but don't fail the job
        print(f"Anonymization error: {e}")
        return text

# Register UDF
anonymize_udf = udf(anonymize_text, StringType())

# Read input data
input_path = args['INPUT_PATH']
print(f"Reading data from: {input_path}")

# Auto-detect format based on extension
if input_path.endswith('.parquet'):
    df = spark.read.parquet(input_path)
elif input_path.endswith('.json'):
    df = spark.read.json(input_path)
else:  # Default to CSV
    df = spark.read.option("header", "true").option("inferSchema", "true").csv(input_path)

print(f"Input schema: {df.schema}")
print(f"Input row count: {df.count()}")

# Columns to anonymize (will be replaced by DataPipeline Agent)
# PLACEHOLDER: SENSITIVE_COLUMNS
sensitive_columns = ["customer_name", "email", "phone", "address"]

# Apply anonymization to sensitive columns
for col_name in sensitive_columns:
    if col_name in df.columns:
        print(f"Anonymizing column: {col_name}")
        df = df.withColumn(col_name, anonymize_udf(col(col_name)))

# Write output as CSV (for downstream Deep Insight processing)
output_path = args['OUTPUT_PATH']
print(f"Writing preprocessed data to: {output_path}")

df.coalesce(1).write.mode("overwrite").option("header", "true").csv(output_path)

# Job completion
job.commit()
print("PII removal completed successfully")
```

### Aggregation Template

```python
# glue-scripts/aggregation_template.py

"""
PySpark script template for data aggregation.
Reduces large datasets to manageable size for Deep Insight analysis.
"""

import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql import functions as F

# Initialize
args = getResolvedOptions(sys.argv, ['JOB_NAME', 'INPUT_PATH', 'OUTPUT_PATH'])
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Read preprocessed data (after PII removal)
input_path = args['INPUT_PATH']
df = spark.read.option("header", "true").option("inferSchema", "true").csv(input_path)

print(f"Input row count: {df.count()}")
print(f"Input columns: {df.columns}")

# PLACEHOLDER: AGGREGATION_LOGIC
# Example aggregation (customized by DataPipeline Agent based on user query)

# Group by dimensions and calculate metrics
aggregated_df = df.groupBy(
    "region",
    "product_category",
    F.date_trunc("month", F.col("order_date")).alias("month")
).agg(
    F.count("*").alias("order_count"),
    F.sum("revenue").alias("total_revenue"),
    F.avg("revenue").alias("avg_revenue"),
    F.countDistinct("customer_id").alias("unique_customers"),
    F.sum("quantity").alias("total_quantity")
)

# Sort for readability
aggregated_df = aggregated_df.orderBy("month", "region", "product_category")

print(f"Aggregated row count: {aggregated_df.count()}")

# Write output
output_path = args['OUTPUT_PATH']
aggregated_df.coalesce(1).write.mode("overwrite").option("header", "true").csv(output_path)

job.commit()
print("Aggregation completed successfully")
```

---

## CloudFormation Resources

### Phase 2.5: Glue Infrastructure

```yaml
# cloudformation/phase2-glue.yaml

AWSTemplateFormatVersion: '2010-09-09'
Description: 'Deep Insight - AWS Glue resources for large file processing'

Parameters:
  Environment:
    Type: String
    Default: prod
    AllowedValues: [dev, staging, prod]

  ProjectName:
    Type: String
    Default: deep-insight

Resources:
  #============================================================================
  # S3 Buckets
  #============================================================================

  GlueScriptBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub '${ProjectName}-glue-scripts-${AWS::AccountId}-${AWS::Region}'
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: AES256
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true
      Tags:
        - Key: Project
          Value: !Ref ProjectName
        - Key: Environment
          Value: !Ref Environment

  GlueOutputBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub '${ProjectName}-glue-output-${AWS::AccountId}-${AWS::Region}'
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: AES256
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true
      LifecycleConfiguration:
        Rules:
          - Id: DeleteOldOutput
            Status: Enabled
            ExpirationInDays: 7  # Auto-cleanup after 7 days
      Tags:
        - Key: Project
          Value: !Ref ProjectName
        - Key: Environment
          Value: !Ref Environment

  #============================================================================
  # IAM Role for Glue
  #============================================================================

  GlueJobRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: !Sub '${ProjectName}-glue-job-role-${Environment}'
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: glue.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole
      Policies:
        - PolicyName: S3Access
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              # Access to script bucket
              - Effect: Allow
                Action:
                  - s3:GetObject
                  - s3:PutObject
                  - s3:DeleteObject
                  - s3:ListBucket
                Resource:
                  - !GetAtt GlueScriptBucket.Arn
                  - !Sub '${GlueScriptBucket.Arn}/*'
              # Access to output bucket
              - Effect: Allow
                Action:
                  - s3:GetObject
                  - s3:PutObject
                  - s3:DeleteObject
                  - s3:ListBucket
                Resource:
                  - !GetAtt GlueOutputBucket.Arn
                  - !Sub '${GlueOutputBucket.Arn}/*'
              # Read access to user data buckets (broad - customize as needed)
              - Effect: Allow
                Action:
                  - s3:GetObject
                  - s3:ListBucket
                Resource:
                  - 'arn:aws:s3:::*'
        - PolicyName: CloudWatchLogs
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - logs:CreateLogGroup
                  - logs:CreateLogStream
                  - logs:PutLogEvents
                Resource:
                  - !Sub 'arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws-glue/*'
      Tags:
        - Key: Project
          Value: !Ref ProjectName
        - Key: Environment
          Value: !Ref Environment

  #============================================================================
  # Glue Job Definition
  #============================================================================

  DeepInsightETLJob:
    Type: AWS::Glue::Job
    Properties:
      Name: !Sub '${ProjectName}-etl-${Environment}'
      Description: 'Large file ETL job for Deep Insight framework'
      Role: !GetAtt GlueJobRole.Arn
      Command:
        Name: glueetl
        ScriptLocation: !Sub 's3://${GlueScriptBucket}/scripts/placeholder.py'
        PythonVersion: '3'
      DefaultArguments:
        '--enable-metrics': 'true'
        '--enable-spark-ui': 'true'
        '--spark-event-logs-path': !Sub 's3://${GlueScriptBucket}/spark-logs/'
        '--enable-continuous-cloudwatch-log': 'true'
        '--enable-continuous-log-filter': 'true'
        '--additional-python-modules': 'presidio-analyzer==2.2.354,presidio-anonymizer==2.2.354'
        '--TempDir': !Sub 's3://${GlueScriptBucket}/temp/'
      GlueVersion: '4.0'
      WorkerType: G.1X  # 4 vCPU, 16 GB memory
      NumberOfWorkers: 10
      Timeout: 60  # minutes
      MaxRetries: 1
      ExecutionProperty:
        MaxConcurrentRuns: 5
      Tags:
        Project: !Ref ProjectName
        Environment: !Ref Environment

  #============================================================================
  # CloudWatch Log Group
  #============================================================================

  GlueLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub '/aws-glue/jobs/${ProjectName}-etl-${Environment}'
      RetentionInDays: 30
      Tags:
        - Key: Project
          Value: !Ref ProjectName
        - Key: Environment
          Value: !Ref Environment

Outputs:
  GlueJobName:
    Description: Name of the Glue ETL job
    Value: !Ref DeepInsightETLJob
    Export:
      Name: !Sub '${AWS::StackName}-GlueJobName'

  GlueJobRoleArn:
    Description: ARN of the Glue job IAM role
    Value: !GetAtt GlueJobRole.Arn
    Export:
      Name: !Sub '${AWS::StackName}-GlueJobRoleArn'

  GlueScriptBucketName:
    Description: S3 bucket for Glue scripts
    Value: !Ref GlueScriptBucket
    Export:
      Name: !Sub '${AWS::StackName}-GlueScriptBucket'

  GlueOutputBucketName:
    Description: S3 bucket for Glue job outputs
    Value: !Ref GlueOutputBucket
    Export:
      Name: !Sub '${AWS::StackName}-GlueOutputBucket'
```

---

## DataPipeline Agent Prompt

### System Prompt

```markdown
# src/prompts/data_pipeline_agent.md

You are the DataPipeline Agent, a specialized agent for processing large datasets (10GB+) using AWS Glue and PySpark.

## Your Responsibilities

1. **Validate Input Data**
   - Verify S3 path exists and is accessible
   - Detect file format (Parquet, CSV, JSON)
   - Estimate data size and complexity

2. **PII Detection and Removal**
   - Identify columns likely containing PII (names, emails, phones, addresses, SSN, etc.)
   - Generate PySpark code using Presidio for anonymization
   - Apply appropriate anonymization strategies (redact, hash, mask)

3. **Data Transformation**
   - Generate aggregation logic based on user requirements
   - Reduce large datasets to manageable size for analysis
   - Preserve statistical validity in sampling/aggregation

4. **Job Management**
   - Submit AWS Glue jobs with appropriate worker configuration
   - Monitor job progress and handle failures
   - Return output location for downstream processing

## Output Format

Your output should always include:
1. **Data Assessment**: Size, format, schema overview
2. **PII Findings**: Columns identified as containing PII
3. **Transformation Plan**: How data will be aggregated/sampled
4. **Glue Job Parameters**: Worker type, count, timeout
5. **Output Path**: S3 location of preprocessed data

## PySpark Code Generation Guidelines

When generating PySpark code:
- Always use AWS Glue context (`GlueContext`, not raw SparkContext)
- Include proper error handling
- Use `coalesce(1)` for single CSV output when data is small enough
- Add print statements for logging progress
- Use broadcast variables for Presidio engines

## Worker Type Selection

| Data Size | Worker Type | Workers | Timeout |
|-----------|-------------|---------|---------|
| < 10GB    | G.1X        | 5       | 30 min  |
| 10-50GB   | G.1X        | 10      | 60 min  |
| 50-100GB  | G.2X        | 10      | 90 min  |
| > 100GB   | G.2X        | 20      | 120 min |

## Example Interaction

User: "Process s3://data-lake/sales-2024.parquet (15GB) for quarterly analysis"

Your response:
```
## Data Assessment
- **Source**: s3://data-lake/sales-2024.parquet
- **Estimated Size**: 15GB
- **Format**: Parquet

## PII Analysis
Columns requiring anonymization:
- `customer_name` → PERSON
- `email` → EMAIL_ADDRESS
- `phone` → PHONE_NUMBER
- `shipping_address` → LOCATION

## Transformation Plan
1. Remove PII from identified columns
2. Aggregate by: quarter, region, product_category
3. Metrics: total_revenue, order_count, unique_customers

## Glue Job Configuration
- **Worker Type**: G.1X (4 vCPU, 16GB)
- **Workers**: 10
- **Timeout**: 60 minutes

## Submitting Job...
Job ID: jr_abc123
Status: RUNNING

## Job Completed
- **Duration**: 12 minutes
- **Output**: s3://deep-insight-output/preprocessed/sales-2024-q-agg/
- **Output Size**: 2.4 MB (15,234 rows)

Ready for Deep Insight analysis.
```
```

---

## Environment Variables

### New Variables for .env

```bash
# Glue Configuration (added by phase2-glue CloudFormation)
GLUE_JOB_NAME=deep-insight-etl-prod
GLUE_JOB_ROLE_ARN=arn:aws:iam::123456789012:role/deep-insight-glue-job-role-prod
GLUE_SCRIPT_BUCKET=deep-insight-glue-scripts-123456789012-us-west-2
GLUE_OUTPUT_BUCKET=deep-insight-glue-output-123456789012-us-west-2
GLUE_WORKER_TYPE=G.1X
GLUE_NUM_WORKERS=10
GLUE_TIMEOUT_MINUTES=60
```

---

## Integration with Existing Graph

### Modified Graph Builder

```python
# src/graph/builder.py - Supervisor tool list update

from src.tools.coder_agent_fargate_tool import coder_agent_tool
from src.tools.data_pipeline_agent_tool import data_pipeline_agent_tool  # NEW
from src.tools.validator_agent_tool import validator_agent_tool
from src.tools.reporter_agent_tool import reporter_agent_tool
from src.tools.tracker_agent_tool import tracker_agent_tool

# Supervisor's available tools
supervisor_tools = [
    coder_agent_tool,
    data_pipeline_agent_tool,  # NEW
    validator_agent_tool,
    reporter_agent_tool,
    tracker_agent_tool
]
```

### DataPipeline Agent Tool

```python
# src/tools/data_pipeline_agent_tool.py

from strands import Agent, tool
from src.tools.glue_job_controller import GlueJobController
from src.prompts.template import load_prompt

@tool
def data_pipeline_agent_tool(
    input_s3_path: str,
    task_description: str,
    sensitive_columns: list[str] = None,
    aggregation_dimensions: list[str] = None,
    aggregation_metrics: list[str] = None
) -> str:
    """
    Process large datasets (10GB+) using AWS Glue and PySpark.

    This tool handles:
    1. PII detection and removal using Presidio
    2. Data aggregation and transformation
    3. Output generation in CSV format for Deep Insight analysis

    Args:
        input_s3_path: S3 URI of the input data (e.g., s3://bucket/data.parquet)
        task_description: Description of what analysis is needed
        sensitive_columns: List of column names containing PII (auto-detected if not provided)
        aggregation_dimensions: Columns to group by (e.g., ["region", "month"])
        aggregation_metrics: Metrics to calculate (e.g., ["sum:revenue", "count:orders"])

    Returns:
        S3 path to the preprocessed CSV file ready for Deep Insight analysis
    """

    # Initialize controller
    controller = GlueJobController()

    # Create DataPipeline agent for intelligent code generation
    system_prompt = load_prompt("data_pipeline_agent")

    agent = Agent(
        model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        system_prompt=system_prompt
    )

    # Generate PySpark code using the agent
    code_generation_prompt = f"""
    Generate PySpark code for the following task:

    Input: {input_s3_path}
    Task: {task_description}
    Sensitive Columns: {sensitive_columns or 'Auto-detect'}
    Group By: {aggregation_dimensions or 'Determine based on task'}
    Metrics: {aggregation_metrics or 'Determine based on task'}

    Generate complete Glue ETL script with PII removal and aggregation.
    """

    response = agent(code_generation_prompt)
    pyspark_code = extract_code_from_response(response)

    # Submit Glue job
    output_path = f"s3://{controller.output_bucket}/preprocessed/{generate_job_id()}/"

    job_run_id = controller.submit_job(
        input_s3_path=input_s3_path,
        output_s3_path=output_path,
        pyspark_code=pyspark_code
    )

    # Wait for completion
    result = controller.wait_for_completion(job_run_id)

    if result['status'] != 'SUCCEEDED':
        raise RuntimeError(f"Glue job failed: {result.get('error_message')}")

    # Get output metadata
    metadata = controller.get_output_metadata(output_path)

    return f"""
    ## DataPipeline Processing Complete

    **Job ID**: {job_run_id}
    **Status**: {result['status']}
    **Duration**: {result.get('execution_time', 'N/A')} seconds

    **Output Location**: {output_path}
    **Output Size**: {metadata['total_size_mb']} MB
    **File Count**: {metadata['file_count']}

    The preprocessed data is ready for Deep Insight analysis.
    """


def extract_code_from_response(response: dict) -> str:
    """Extract PySpark code from agent response."""
    text = response.get('text', '')
    # Extract code between ```python and ``` markers
    import re
    match = re.search(r'```python\n(.*?)```', text, re.DOTALL)
    if match:
        return match.group(1)
    return text


def generate_job_id() -> str:
    """Generate unique job identifier."""
    import uuid
    from datetime import datetime
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    short_uuid = str(uuid.uuid4())[:8]
    return f"{timestamp}-{short_uuid}"
```

---

## Complete Workflow Example

```
User: "Analyze customer behavior from s3://data-lake/customers-2024.parquet (12GB)"

┌─────────────────────────────────────────────────────────────────┐
│ COORDINATOR                                                      │
│ - Detects: S3 URI + large file indicator                        │
│ - Action: handoff_to_planner                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ PLANNER (Extended Thinking)                                      │
│                                                                  │
│ Analysis:                                                        │
│ - 12GB parquet file requires preprocessing                      │
│ - Customer data likely contains PII                             │
│ - Need aggregation for meaningful analysis                      │
│                                                                  │
│ Plan:                                                            │
│ 1. [DataPipeline] PII removal + aggregation                     │
│    - Anonymize: customer_name, email, phone, address            │
│    - Aggregate: by region, month                                │
│    - Output: ~50MB CSV                                          │
│ 2. [Coder] Statistical analysis on preprocessed data            │
│ 3. [Coder] Generate visualizations                              │
│ 4. [Validator] Verify analysis accuracy                         │
│ 5. [Reporter] Compile DOCX report                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ SUPERVISOR                                                       │
│                                                                  │
│ Step 1: Call DataPipeline Agent                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ DataPipeline Agent                                          │ │
│ │ - Generates PySpark code with Presidio                      │ │
│ │ - Submits Glue job (10 G.1X workers)                       │ │
│ │ - Waits ~8 minutes                                          │ │
│ │ - Returns: s3://output/preprocessed-customers.csv           │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│ Step 2: Call Coder Agent (Fargate)                              │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Coder Agent                                                  │ │
│ │ - Downloads 50MB CSV                                         │ │
│ │ - Pandas analysis: trends, correlations                     │ │
│ │ - Matplotlib charts: regional breakdown, time series        │ │
│ │ - Returns: insights + chart paths                           │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│ Step 3: Call Validator Agent                                    │
│ Step 4: Call Reporter Agent → DOCX                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ OUTPUT                                                           │
│ - Report: customer_behavior_analysis.docx                       │
│ - Charts: 5 visualizations embedded                             │
│ - Data source: 12GB → 50MB (anonymized, aggregated)            │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Structure Summary

```
managed-agentcore/
├── src/
│   ├── tools/
│   │   ├── data_pipeline_agent_tool.py      # NEW: Agent wrapper
│   │   └── glue_job_controller.py           # NEW: Glue API interface
│   └── prompts/
│       └── data_pipeline_agent.md           # NEW: ETL-focused prompts
│
├── glue-scripts/                             # NEW: PySpark templates
│   ├── pii_removal_template.py
│   └── aggregation_template.py
│
├── production_deployment/
│   └── cloudformation/
│       └── phase2-glue.yaml                 # NEW: Glue infrastructure
│
└── under_development/
    └── large_file_processing_architecture.md  # This document
```

---

## Cost Estimation

### AWS Glue Costs (us-west-2)

| Worker Type | vCPU | Memory | Cost/DPU-Hour |
|-------------|------|--------|---------------|
| G.1X        | 4    | 16 GB  | $0.44         |
| G.2X        | 8    | 32 GB  | $0.44         |

**Example: 15GB file processing**
- Workers: 10 × G.1X
- Duration: 12 minutes (0.2 hours)
- DPU-Hours: 10 × 0.2 = 2 DPU-hours
- **Cost: ~$0.88 per job**

### Monthly Estimate (100 jobs/month)
- Glue Jobs: $88
- S3 Storage: $2-5 (auto-cleanup after 7 days)
- **Total: ~$90-95/month**

---

## Next Steps

### Phase 1: CloudFormation Updates (On-Demand Module Loading)
1. Add `EnableGlueIntegration` parameter to `phase1-infrastructure.yaml`
2. Add conditional Glue resources (S3 buckets, IAM role, Glue job)
3. Add conditional outputs for Glue configuration

### Phase 2: Deployment Script Updates
1. Modify `deploy_phase1_phase2.sh` to accept `--enable-glue` flag
2. Update `01_extract_env_vars_from_cf.sh` to conditionally extract Glue vars
3. Test both standard and extended deployments

### Phase 3: Implement GlueJobController
1. Create `src/tools/glue_job_controller.py`
2. Implement job submission, monitoring, and output retrieval
3. Add error handling and retry logic

### Phase 4: Implement DataPipeline Agent Tool
1. Create `src/tools/data_pipeline_agent_tool.py`
2. Create `src/prompts/data_pipeline_agent.md`
3. Integrate with GlueJobController

### Phase 5: Create and Test PySpark Templates
1. Create `glue-scripts/pii_removal_template.py`
2. Create `glue-scripts/aggregation_template.py`
3. Test with sample large dataset

### Phase 6: Runtime Integration
1. Modify `src/graph/nodes.py` for conditional tool loading
2. Update Supervisor prompt for DataPipeline awareness
3. End-to-end testing with both deployment modes

---

## Open Questions

1. **Multi-language PII**: Should Presidio support Korean/Japanese PII patterns?
2. **Data Catalog**: Should output be registered in AWS Glue Data Catalog?
3. **Scheduling**: Should we support scheduled ETL jobs (not just on-demand)?
4. **Cost Controls**: Should we add budget limits per job or per user?

---

## References

- [AWS Glue Developer Guide](https://docs.aws.amazon.com/glue/latest/dg/)
- [Presidio Documentation](https://microsoft.github.io/presidio/)
- [PySpark SQL Functions](https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/functions.html)
- [Deep Insight CLAUDE.md](../CLAUDE.md)
