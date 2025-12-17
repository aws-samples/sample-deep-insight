#!/usr/bin/env python3
"""
create_agentcore_runtime_vpc.py

Purpose:
    Creates an AgentCore Runtime in VPC Private mode.
    Uses the native launch() method from the latest boto3/bedrock_agentcore_starter_toolkit.

Container Architecture:
    This script manages TWO types of containers:

    1. AgentCore Runtime Container (created by this script):
       - Main container that runs the AgentCore runtime
       - Runs in VPC with specified subnet and security group
       - Receives environment variables for spawning Fargate containers
       - Handles agent orchestration and task delegation

    2. ECS Fargate Containers (spawned BY the runtime):
       - Dynamic executor containers created by the runtime on-demand
       - Execute actual agent tasks (Python code, tools, etc.)
       - Communicate with runtime via ALB
       - Configured via env vars passed to the runtime container

Usage:
    cd setup && uv sync && ./patch_dockerignore_template.sh
    cd ..
    python3 create_agentcore_runtime_vpc.py

Main Tasks:
    1. Load VPC information from production_deployment/.env
    2. Reuse existing IAM Role (created in Phase 1)
    3. Configure AgentCore Runtime Container with VPC settings using Runtime.configure()
    4. Prepare environment variables to pass TO runtime (tells it how to spawn Fargate containers)
    5. Build Docker + Push to ECR + Create Runtime using Runtime.launch(env_vars=...)
    6. Save Runtime ARN to .env file

Important Notes:
    - Requires latest boto3 (>=1.40.65) and bedrock_agentcore_starter_toolkit (>=0.1.28)
    - Must run setup/patch_dockerignore_template.sh beforehand!
    - Use only supported AZs (use1-az2, use1-az4, etc.)
    - Observability automatically enabled (CloudWatch Logs)

Execution Order:
    01_create_agentcore_runtime_vpc.py → 02_invoke_agentcore_runtime_vpc.py (testing)
"""

import os
import sys
import yaml
import time
from datetime import datetime
from dotenv import load_dotenv
import boto3

# Color definitions
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color

# Environment variable groups
# NOTE: This script manages TWO types of containers:
# 1. AgentCore Runtime Container: Main container running the AgentCore runtime (this script creates it)
# 2. ECS Fargate Containers: Dynamic executor containers spawned by the runtime to execute tasks
ENV_VAR_GROUPS = {
    'required': {
        'AWS_REGION': None,
        'AWS_ACCOUNT_ID': None,
        'VPC_ID': None,
        'PRIVATE_SUBNET_1_ID': None,  # For AgentCore Runtime Container VPC configuration
        'SG_AGENTCORE_ID': None,      # For AgentCore Runtime Container security group
        'TASK_EXECUTION_ROLE_ARN': None,
    },
    'container': {
        # These variables are passed TO the AgentCore Runtime Container
        # The runtime uses them to spawn ECS Fargate Containers for task execution
        'ECS_CLUSTER_NAME': None,       # ECS cluster where Fargate containers run
        'ALB_DNS': None,                # ALB endpoint for Fargate containers
        'TASK_DEFINITION_ARN': None,    # Task definition for Fargate containers
        'CONTAINER_NAME': None,         # Container name in Fargate task definition
        'S3_BUCKET_NAME': None,
        'BEDROCK_MODEL_ID': None,
        # Agent Model IDs
        'DEFAULT_MODEL_ID': None,
        'COORDINATOR_MODEL_ID': None,
        'PLANNER_MODEL_ID': None,
        'SUPERVISOR_MODEL_ID': None,
        'CODER_MODEL_ID': None,
        'VALIDATOR_MODEL_ID': None,
        'REPORTER_MODEL_ID': None,
        'TRACKER_MODEL_ID': None,
    },
    'fargate': {
        # Network configuration for ECS Fargate Containers (spawned by runtime)
        'FARGATE_SUBNET_IDS': None,
        'FARGATE_SECURITY_GROUP_IDS': None,
        'FARGATE_ASSIGN_PUBLIC_IP': 'DISABLED',  # Default value
        'ALB_TARGET_GROUP_ARN': None,
    },
    'observability': {
        # Observability settings for AgentCore Runtime Container
        'OTEL_PYTHON_DISTRO': None,
        'OTEL_PYTHON_CONFIGURATOR': None,
        'OTEL_EXPORTER_OTLP_PROTOCOL': None,
        'OTEL_EXPORTER_OTLP_LOGS_HEADERS': None,
        'OTEL_RESOURCE_ATTRIBUTES': None,
        'AGENT_OBSERVABILITY_ENABLED': None,
    },
    'runtime': {
        'RUNTIME_ARN': None,
    }
}

def print_header(message):
    """Print header message"""
    print(f"\n{BLUE}{'='*60}{NC}")
    print(f"{BLUE}{message}{NC}")
    print(f"{BLUE}{'='*60}{NC}\n")

def print_success(message):
    """Print success message"""
    print(f"{GREEN}✅ {message}{NC}")

def print_error(message):
    """Print error message"""
    print(f"{RED}❌ {message}{NC}")

def print_warning(message):
    """Print warning message"""
    print(f"{YELLOW}⚠️  {message}{NC}")

def print_info(message):
    """Print info message"""
    print(f"{BLUE}ℹ️  {message}{NC}")

def load_environment_variables():
    """
    Load environment variables from .env file and organize them into groups.

    Returns:
        dict: Dictionary containing all environment variable groups with loaded values
    """
    # Initialize result dictionary with all groups
    config = {group: {} for group in ENV_VAR_GROUPS.keys()}

    # Load variables for each group
    for group_name, var_dict in ENV_VAR_GROUPS.items():
        for var_name, default_value in var_dict.items():
            value = os.getenv(var_name, default_value)
            config[group_name][var_name] = value

    return config

def validate_required_variables(config):
    """
    Validate that all required environment variables are set.

    Args:
        config (dict): Configuration dictionary from load_environment_variables()

    Returns:
        bool: True if all required variables are set, False otherwise
    """
    missing_vars = []

    for var_name, var_value in config['required'].items():
        if not var_value:
            missing_vars.append(var_name)

    if missing_vars:
        print_error("Missing required environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        return False

    return True

def load_and_validate_config():
    """
    Load and validate environment configuration from .env file.

    Returns:
        tuple: (env_file_path, config_dict) or exits on error
    """
    print(f"{YELLOW}[1/5] Loading environment configuration...{NC}")

    # Get current directory
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Load .env from project root
    env_file = os.path.join(current_dir, ".env")
    if not os.path.exists(env_file):
        print_error(f".env file not found: {env_file}")
        print_warning("Please deploy Phase 1 and 2 first")
        print_warning("Or run ./production_deployment/scripts/setup_env.sh")
        sys.exit(1)

    load_dotenv(env_file, override=True)

    # Load all environment variables into organized groups
    config = load_environment_variables()

    # Validate required variables
    if not validate_required_variables(config):
        sys.exit(1)

    # Extract commonly used variables for display
    AWS_REGION = config['required']['AWS_REGION']
    VPC_ID = config['required']['VPC_ID']
    PRIVATE_SUBNET_1_ID = config['required']['PRIVATE_SUBNET_1_ID']
    SG_AGENTCORE_ID = config['required']['SG_AGENTCORE_ID']
    EXISTING_RUNTIME_ARN = config['runtime']['RUNTIME_ARN']
    EXISTING_RUNTIME_ID = EXISTING_RUNTIME_ARN.split('/')[-1] if EXISTING_RUNTIME_ARN else None

    print_success("Environment configuration loaded")
    print(f"  - Region: {AWS_REGION}")
    print(f"  - VPC: {VPC_ID}")
    print(f"  - Subnet: {PRIVATE_SUBNET_1_ID}")
    print(f"  - Security Group: {SG_AGENTCORE_ID}")
    if EXISTING_RUNTIME_ID:
        print(f"  - Existing Runtime: {EXISTING_RUNTIME_ID} (will update)")

    # Display environment variables that will be passed to AgentCore Runtime Container
    # These variables tell the runtime HOW to spawn ECS Fargate Containers
    container_vars = config['container']
    fargate_vars = config['fargate']
    has_container_config = container_vars['ECS_CLUSTER_NAME'] or container_vars['ALB_DNS']

    if has_container_config:
        print(f"\n  Environment variables for AgentCore Runtime Container:")
        print(f"  (Runtime will use these to spawn ECS Fargate Containers)")
        for var_name, var_value in {**container_vars, **fargate_vars}.items():
            if var_value:
                print(f"    - {var_name}: {var_value}")
    else:
        print_warning("  Fargate configuration variables not set (ECS_CLUSTER_NAME, ALB_DNS)")
        print_warning("  AgentCore Runtime Container won't be able to spawn ECS Fargate Containers")

    print()
    return env_file, config

def configure_agentcore_runtime(config, execution_role_arn):
    """
    Configure AgentCore Runtime Container with VPC settings.

    This configures the MAIN runtime container that will:
    1. Run in the specified VPC/subnet
    2. Use the specified security group
    3. Spawn ECS Fargate Containers for task execution

    Args:
        config (dict): Configuration dictionary
        execution_role_arn (str): IAM execution role ARN for the AgentCore Runtime Container

    Returns:
        tuple: (agentcore_runtime, agent_name) or exits on error
    """
    print(f"{YELLOW}[3/5] Configuring AgentCore Runtime Container...{NC}")

    try:
        from bedrock_agentcore_starter_toolkit import Runtime
    except ImportError:
        print_error("bedrock_agentcore_starter_toolkit is not installed")
        print_info("Install: cd setup && uv sync && ./patch_dockerignore_template.sh")
        sys.exit(1)

    # Runtime name (using fixed name)
    agent_name = "deep_insight_runtime_vpc"

    EXISTING_RUNTIME_ARN = config['runtime']['RUNTIME_ARN']
    EXISTING_RUNTIME_ID = EXISTING_RUNTIME_ARN.split('/')[-1] if EXISTING_RUNTIME_ARN else None

    if EXISTING_RUNTIME_ID:
        print_info(f"Updating existing Runtime: {agent_name}")
    else:
        print_info(f"Creating new Runtime: {agent_name}")

    agentcore_runtime = Runtime()

    print(f"  - Agent Name: {agent_name}")
    print(f"  - Entrypoint: agentcore_runtime.py")
    print(f"  - Requirements: requirements.txt")
    print()

    # Configure AgentCore Runtime Container with VPC settings
    print_info("Calling configure()... (with VPC settings for AgentCore Runtime Container)")
    print_info("Parameters: vpc_enabled=True, vpc_subnets=[...], vpc_security_groups=[...]")
    print()

    # NOTE: CodeBuild Execution Role Configuration
    # - Current: toolkit automatically creates or reuses Role (recommended)
    # - Future: If CodeBuild Role is created in Phase 1 CloudFormation,
    #           uncomment below and load CODEBUILD_EXECUTION_ROLE_ARN from .env
    #
    # CODEBUILD_EXECUTION_ROLE_ARN = os.getenv("CODEBUILD_EXECUTION_ROLE_ARN")
    # if CODEBUILD_EXECUTION_ROLE_ARN:
    #     print_info(f"Using Phase 1 CodeBuild Role: {CODEBUILD_EXECUTION_ROLE_ARN}")

    AWS_REGION = config['required']['AWS_REGION']
    PRIVATE_SUBNET_1_ID = config['required']['PRIVATE_SUBNET_1_ID']  # Where AgentCore Runtime Container runs
    SG_AGENTCORE_ID = config['required']['SG_AGENTCORE_ID']          # Security group for AgentCore Runtime Container

    response = agentcore_runtime.configure(
        agent_name=agent_name,
        entrypoint="agentcore_runtime.py",
        execution_role=execution_role_arn,
        # code_build_execution_role=CODEBUILD_EXECUTION_ROLE_ARN,  # Uncomment to use
        auto_create_ecr=True,
        requirements_file="requirements.txt",
        region=AWS_REGION,
        # VPC settings for AgentCore Runtime Container (NOT for Fargate containers)
        vpc_enabled=True,
        vpc_subnets=[PRIVATE_SUBNET_1_ID],       # Subnet where AgentCore Runtime Container runs
        vpc_security_groups=[SG_AGENTCORE_ID],   # Security group for AgentCore Runtime Container
        # Additional settings
        non_interactive=True
    )

    print_success("Configuration completed")
    print(f"  - Config: {response.config_path}")
    print(f"  - Dockerfile: {response.dockerfile_path}")
    print()

    # Verify YAML file (check if VPC settings are properly saved)
    print_info("Checking YAML file...")
    config_file_path = response.config_path
    with open(config_file_path, 'r') as f:
        bedrock_config = yaml.safe_load(f)

    if agent_name in bedrock_config['agents']:
        agent_config = bedrock_config['agents'][agent_name]
        if 'network_configuration' in agent_config.get('aws', {}):
            print_success("✅ VPC settings saved to YAML!")
            print(f"  {agent_config['aws']['network_configuration']}")
        else:
            print_warning("⚠️ VPC settings not saved to YAML")
            print_warning("Please verify you're using the latest toolkit version")
    print()

    return agentcore_runtime, agent_name

def launch_runtime(agentcore_runtime, config):
    """
    Launch Runtime by building Docker image, pushing to ECR, and creating AgentCore Runtime Container.

    This function builds the AgentCore Runtime Container and passes environment variables
    that tell it HOW to spawn ECS Fargate Containers for task execution.

    Args:
        agentcore_runtime: Runtime instance from configure_agentcore_runtime()
        config (dict): Configuration dictionary

    Returns:
        dict: Runtime information {agent_arn, agent_id} or exits on error
    """
    print(f"{YELLOW}[4/5] Deploying AgentCore Runtime Container (launch)...{NC}")
    print_warning("This step takes 5-10 minutes (Docker build + ECR push + Runtime creation)")
    print()

    print_info("🐳 Building Docker image for AgentCore Runtime Container...")
    print_info("📦 Pushing to ECR...")
    print_info("🚀 Creating AgentCore Runtime Container...")
    print()

    try:
        # Prepare environment variables to pass TO the AgentCore Runtime Container
        # These tell the runtime HOW to spawn ECS Fargate Containers
        container_env_vars = {}

        # Add AWS configuration
        AWS_REGION = config['required']['AWS_REGION']
        AWS_ACCOUNT_ID = config['required']['AWS_ACCOUNT_ID']
        container_env_vars["AWS_REGION"] = AWS_REGION
        container_env_vars["AWS_ACCOUNT_ID"] = AWS_ACCOUNT_ID

        # Add variables that tell runtime HOW to spawn ECS Fargate Containers
        for var_name, var_value in config['container'].items():
            if var_value:
                container_env_vars[var_name] = var_value

        # Add network configuration for ECS Fargate Containers
        for var_name, var_value in config['fargate'].items():
            if var_value:
                container_env_vars[var_name] = var_value

        # Add observability settings for AgentCore Runtime Container
        for var_name, var_value in config['observability'].items():
            if var_value:
                container_env_vars[var_name] = var_value

        # launch() does not accept agent_name parameter (already set in configure())
        # Pass environment variables TO the AgentCore Runtime Container via env_vars parameter
        launch_kwargs = {}
        if container_env_vars:
            launch_kwargs["env_vars"] = container_env_vars
            print_info(f"Passing {len(container_env_vars)} environment variables to AgentCore Runtime Container")
            if config['observability']['AGENT_OBSERVABILITY_ENABLED']:
                print_info("  [OTEL] Observability: ENABLED ✅")

        # Enable auto-update if runtime already exists
        launch_kwargs["auto_update_on_conflict"] = True

        launch_response = agentcore_runtime.launch(**launch_kwargs)

        print_success("launch() completed!")

        # Use correct attribute names from LaunchResult
        agent_arn = launch_response.agent_arn
        agent_id = launch_response.agent_id

        print(f"  - Runtime ARN: {agent_arn}")
        print(f"  - Runtime ID: {agent_id}")
        print()

        return {
            'agent_arn': agent_arn,
            'agent_id': agent_id
        }

    except Exception as e:
        print_error(f"launch() failed: {e}")
        print()
        print_warning("Possible causes:")
        print(f"  1. VPC configuration issues (unsupported AZ, Security Group rules)")
        print(f"  2. Docker build failure (requirements.txt error)")
        print(f"  3. ECR push failure (insufficient permissions)")
        print(f"  4. Patch script not executed (coordinator.md missing)")
        print()
        print_info("Solution:")
        print(f"  cd setup && ./patch_dockerignore_template.sh")
        print()
        sys.exit(1)

def finalize_deployment(runtime_info, agent_name, config, env_file):
    """
    Wait for Runtime to become READY and update .env file.

    Args:
        runtime_info (dict): Runtime information from launch_runtime()
        agent_name (str): Agent name
        config (dict): Configuration dictionary
        env_file (str): Path to .env file

    Returns:
        None (exits on failure)
    """
    print(f"{YELLOW}[5/5] Checking Runtime status...{NC}")

    AWS_REGION = config['required']['AWS_REGION']
    runtime_id = runtime_info['agent_id']
    agent_arn = runtime_info['agent_arn']

    agentcore_control = boto3.client('bedrock-agentcore-control', region_name=AWS_REGION)

    end_status = ['READY', 'CREATE_FAILED', 'DELETE_FAILED', 'UPDATE_FAILED']
    current_status = 'CREATING'

    print(f"⏳ Waiting for Runtime to become READY...")
    print()

    max_attempts = 60  # 10 minutes (10 seconds x 60)
    attempts = 0

    while current_status not in end_status and attempts < max_attempts:
        time.sleep(10)
        attempts += 1

        try:
            response_data = agentcore_control.get_agent_runtime(agentRuntimeId=runtime_id)
            current_status = response_data['status']
            print(f"  [{attempts}/{max_attempts}] Status: {current_status}")
        except Exception as e:
            print_error(f"Status check failed: {e}")
            break

    print()

    if current_status == 'READY':
        print_success("Runtime is READY!")
        print()

        # Runtime detailed information
        print_info("Runtime details:")
        response_data = agentcore_control.get_agent_runtime(agentRuntimeId=runtime_id)

        print(f"  - Runtime Name: {response_data['agentRuntimeName']}")
        print(f"  - Runtime ARN: {response_data['agentRuntimeArn']}")
        print(f"  - Network Mode: {response_data.get('networkConfiguration', {}).get('networkMode', 'N/A')}")

        if 'networkConfiguration' in response_data:
            network_config = response_data['networkConfiguration']
            if 'networkModeConfig' in network_config:
                mode_config = network_config['networkModeConfig']
                print(f"  - Subnets: {mode_config.get('subnets', [])}")
                print(f"  - Security Groups: {mode_config.get('securityGroups', [])}")

        print()

        # Update .env file
        print_info("Updating .env file...")

        with open(env_file, 'r') as f:
            env_lines = f.readlines()

        # Remove existing Runtime information
        new_lines = []
        skip_section = False
        for line in env_lines:
            if line.strip().startswith("# Phase 3: AgentCore Runtime"):
                skip_section = True
                continue
            if skip_section and (line.startswith("RUNTIME_NAME=") or
                               line.startswith("RUNTIME_ARN=") or
                               line.startswith("RUNTIME_ID=")):
                continue
            elif skip_section and line.strip() == "":
                skip_section = False
                continue
            else:
                skip_section = False
                new_lines.append(line)

        # Add new Runtime information
        new_lines.append(f"\n# Phase 3: AgentCore Runtime (Latest - {datetime.now().strftime('%Y-%m-%d')})\n")
        new_lines.append(f"RUNTIME_NAME={agent_name}\n")
        new_lines.append(f"RUNTIME_ARN={agent_arn}\n")
        new_lines.append(f"RUNTIME_ID={runtime_id}\n")

        # Write .env file
        with open(env_file, 'w') as f:
            f.writelines(new_lines)

        print_success(".env file updated")
        print()

        print_success("🎉 VPC Runtime deployment successful!")
        print()

        # CloudWatch Logs check
        print_info("CloudWatch Logs:")
        print(f"  aws logs tail /aws/bedrock-agentcore/runtimes/{agent_name} --follow --region {AWS_REGION}")
        print()

    else:
        print_error(f"Runtime status: {current_status}")
        print_warning("Please check CloudWatch Logs for details")
        print()

        if attempts >= max_attempts:
            print_warning(f"Maximum wait time exceeded ({max_attempts * 10} seconds)")

        sys.exit(1)

def print_completion_summary(runtime_info, agent_name, config):
    """
    Print deployment completion summary.

    Args:
        runtime_info (dict): Runtime information
        agent_name (str): Agent name
        config (dict): Configuration dictionary
    """
    print_header("✅ Deployment Complete!")

    PRIVATE_SUBNET_1_ID = config['required']['PRIVATE_SUBNET_1_ID']
    SG_AGENTCORE_ID = config['required']['SG_AGENTCORE_ID']

    print(f"{BLUE}Runtime Information:{NC}")
    print(f"  Runtime Name: {agent_name}")
    print(f"  Runtime ARN: {runtime_info['agent_arn']}")
    print(f"  Runtime ID: {runtime_info['agent_id']}")
    print(f"  Network Mode: VPC")
    print(f"  Subnet: {PRIVATE_SUBNET_1_ID}")
    print(f"  Security Group: {SG_AGENTCORE_ID}")
    print()

    print(f"{BLUE}Next Steps:{NC}")
    print(f"  1. Test Runtime: python3 02_invoke_agentcore_runtime_vpc.py")
    print(f"  2. Check CloudWatch Logs:")
    print(f"     - Verify 'Coordinator started' message")
    print(f"     - Ensure no 'FileNotFoundError: coordinator.md'")
    print()

def main():
    """
    Main function - orchestrates AgentCore Runtime Container deployment.

    This creates the AgentCore Runtime Container with all necessary configuration
    to spawn ECS Fargate Containers for task execution.
    """
    print_header("AgentCore Runtime Creation - Native launch() Method")

    # Step 1: Load and validate configuration
    env_file, config = load_and_validate_config()

    # Step 2: Setup IAM roles (for AgentCore Runtime Container)
    print(f"{YELLOW}[2/5] Setting up IAM Role...{NC}")
    execution_role_arn = config['required']['TASK_EXECUTION_ROLE_ARN']
    print_success(f"Reusing existing IAM Role: {execution_role_arn}")
    print()

    # Step 3: Configure AgentCore Runtime Container (VPC, subnet, security group)
    agentcore_runtime, agent_name = configure_agentcore_runtime(config, execution_role_arn)

    # Step 4: Launch AgentCore Runtime Container (with env vars for spawning Fargate containers)
    runtime_info = launch_runtime(agentcore_runtime, config)

    # Step 5: Wait for AgentCore Runtime Container to be ready and update .env
    finalize_deployment(runtime_info, agent_name, config, env_file)

    # Display completion summary
    print_completion_summary(runtime_info, agent_name, config)

if __name__ == "__main__":
    main()
