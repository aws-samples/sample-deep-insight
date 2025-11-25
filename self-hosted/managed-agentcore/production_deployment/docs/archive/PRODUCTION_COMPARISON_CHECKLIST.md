# 🔍 개발 계정 vs 프로덕션 계정 설정 비교 체크리스트

## 📋 이 문서의 목적
개발 계정에서 **성공한 VPC Runtime 설정**을 프로덕션 계정과 비교하여 문제점을 찾습니다.

---

## ✅ 1. VPC 기본 설정

### 개발 계정 (성공 ✅)
| 항목 | 값 |
|------|-----|
| VPC ID | vpc-05975448296a22c21 |
| CIDR | 10.100.0.0/16 |
| DNS Hostnames | Enabled |
| DNS Support | Enabled |

### 프로덕션 계정 확인 명령어
```bash
aws ec2 describe-vpcs --vpc-ids vpc-0be869fcda8ead4b3 --query 'Vpcs[0].[VpcId, CidrBlock, EnableDnsHostnames, EnableDnsSupport]' --output table
```

**확인 사항:**
- [ ] DNS Hostnames: Enabled
- [ ] DNS Support: Enabled

---

## ✅ 2. Subnets 설정

### 개발 계정 (성공 ✅)
| Subnet ID | AZ | AZ ID | CIDR | Type |
|-----------|-----|-------|------|------|
| subnet-0b2fb367d6e823a79 | us-east-1a | use1-az2 | 10.100.1.0/24 | Private |
| subnet-0ed3a6040386768cf | us-east-1c | use1-az6 | 10.100.2.0/24 | Private |

**중요**: Runtime은 **use1-az2**만 사용 (use1-az6은 지원 안 됨)

### 프로덕션 계정 확인 명령어
```bash
aws ec2 describe-subnets \
  --subnet-ids subnet-018b0810d92f3fcdc subnet-0e2f3fa18969bf917 \
  --query 'Subnets[*].[SubnetId, AvailabilityZone, AvailabilityZoneId, CidrBlock]' \
  --output table
```

**확인 사항:**
- [ ] Subnet AZ ID가 지원되는 AZ인지 확인 (use1-az1, use1-az2, use1-az4, use1-az6)
- [ ] Private Subnet인지 확인 (MapPublicIpOnLaunch: false)

---

## ✅ 3. Security Group 규칙 (⭐ 가장 중요!)

### 3.1 VPC Endpoint SG

**개발 계정 (성공 ✅)**
```json
{
  "GroupId": "sg-085cf66da6c4027d2",
  "GroupName": "test-vpc-private-vpce-sg",
  "Inbound": [
    {
      "Protocol": "tcp",
      "Port": "443",
      "Source": "10.100.0.0/16"  ← VPC CIDR 전체 허용
    }
  ],
  "Outbound": [
    {
      "Protocol": "-1",
      "Destination": "0.0.0.0/0"
    }
  ]
}
```

**프로덕션 계정 확인 명령어**
```bash
aws ec2 describe-security-groups \
  --group-ids sg-0d459967379994c48 \
  --query 'SecurityGroups[0].[GroupId, GroupName, IpPermissions]' \
  --output json | jq
```

**확인 사항:**
- [ ] Inbound: HTTPS(443) from VPC CIDR (예: 10.0.0.0/16) 또는 Fargate SG
- [ ] Outbound: All traffic to 0.0.0.0/0

**없으면 추가:**
```bash
# VPC CIDR 허용 방식 (권장)
aws ec2 authorize-security-group-ingress \
  --group-id sg-0d459967379994c48 \
  --protocol tcp \
  --port 443 \
  --cidr <VPC_CIDR>  # 예: 10.0.0.0/16

# 또는 Fargate SG 허용 방식
aws ec2 authorize-security-group-ingress \
  --group-id sg-0d459967379994c48 \
  --protocol tcp \
  --port 443 \
  --source-group sg-0853a2a61c62e135b
```

### 3.2 Fargate SG

**개발 계정 (성공 ✅)**
```json
{
  "GroupId": "sg-0e1314a2421686c2c",
  "Inbound": [
    {
      "Protocol": "tcp",
      "Port": "8080",
      "Source": "sg-061896ca7967f6183"  ← ALB SG
    }
  ],
  "Outbound": [
    {
      "Protocol": "-1",
      "Destination": "0.0.0.0/0"
    }
  ]
}
```

**프로덕션 확인:**
- [ ] Inbound: Port 8080 from ALB SG
- [ ] Outbound: All traffic (ECR, S3, Logs 접근 위해 필요)

### 3.3 ALB SG

**개발 계정 (성공 ✅)**
```json
{
  "GroupId": "sg-061896ca7967f6183",
  "Inbound": [
    {
      "Protocol": "tcp",
      "Port": "80",
      "Source": "sg-0affaea9ac4dc26b1"  ← AgentCore SG
    }
  ],
  "Outbound": [
    {
      "Protocol": "tcp",
      "Port": "8080",
      "Destination": "sg-0e1314a2421686c2c"  ← Fargate SG
    }
  ]
}
```

**프로덕션 확인:**
- [ ] Inbound: Port 80 from AgentCore SG
- [ ] Outbound: Port 8080 to Fargate SG

### 3.4 AgentCore SG

**개발 계정 (성공 ✅)**
```json
{
  "GroupId": "sg-0affaea9ac4dc26b1",
  "Inbound": [
    {
      "Protocol": "-1",
      "Source": "sg-085cf66da6c4027d2",  ← VPC Endpoint
      "Description": "From VPC Endpoint"
    },
    {
      "Protocol": "-1",
      "Source": "sg-0affaea9ac4dc26b1",  ← Self
      "Description": "Self-referencing"
    },
    {
      "Protocol": "tcp",
      "Port": "443",
      "Source": "sg-0e1314a2421686c2c"  ← Fargate SG
    }
  ],
  "Outbound": [
    {
      "Protocol": "tcp",
      "Port": "80",
      "Destination": "sg-061896ca7967f6183"  ← ALB
    },
    {
      "Protocol": "tcp",
      "Port": "443",
      "Destination": "sg-085cf66da6c4027d2"  ← VPC Endpoint
    }
  ]
}
```

**프로덕션 확인:**
- [ ] Inbound: All from VPC Endpoint SG
- [ ] Inbound: All from Self
- [ ] Inbound: HTTPS(443) from Fargate SG
- [ ] Outbound: HTTP(80) to ALB SG
- [ ] Outbound: HTTPS(443) to VPC Endpoint SG

---

## ✅ 4. ALB 및 Target Group 설정

### 개발 계정 (성공 ✅)

**ALB:**
- Scheme: **internal** (중요!)
- Type: application
- Security Groups: sg-061896ca7967f6183
- Subnets: Private 2개 (use1-az2, use1-az6)

**Target Group:**
- Protocol: HTTP
- Port: **8080** (중요!)
- TargetType: **ip** (중요!)
- VpcId: vpc-05975448296a22c21
- Health Check:
  - Path: **/health**
  - Interval: 30s
  - Timeout: 5s
  - Healthy Threshold: 2
  - Unhealthy Threshold: 3
- **Stickiness: Enabled** (중요!)
  - Type: lb_cookie
  - Duration: 86400s (24시간)

### 프로덕션 확인 명령어
```bash
# Target Group 상세
TG_ARN="arn:aws:elasticloadbalancing:us-east-1:738490718699:targetgroup/deep-insight-tg-prod/767388ad73745aa7"

aws elbv2 describe-target-groups --target-group-arns $TG_ARN --output json | jq '.TargetGroups[0]'

# Stickiness 확인
aws elbv2 describe-target-group-attributes --target-group-arn $TG_ARN --output json | jq '.Attributes[] | select(.Key | contains("stickiness"))'
```

**확인 사항:**
- [ ] Port: 8080
- [ ] TargetType: ip
- [ ] Health Check Path: /health
- [ ] Stickiness Enabled: true
- [ ] Stickiness Duration: 86400 (24시간)

---

## ✅ 5. ECS 설정

### 개발 계정 (성공 ✅)

**Cluster:**
- Name: my-fargate-cluster
- Status: ACTIVE

**Task Definition:**
- Family: fargate-dynamic-task
- Revision: 6
- Network Mode: **awsvpc** (중요!)
- Requires Compatibilities: FARGATE
- CPU: 256
- Memory: 512
- Task Role: arn:aws:iam::057716757052:role/ecsTaskRole
- Execution Role: arn:aws:iam::057716757052:role/ecsTaskExecutionRole
- Container:
  - Name: dynamic-executor
  - Image: 057716757052.dkr.ecr.us-east-1.amazonaws.com/dynamic-executor:v19-fix-exec-exception
  - Port: 8080
  - Environment:
    - AWS_REGION: us-east-1

### 프로덕션 확인 명령어
```bash
# Task Definition 상세
aws ecs describe-task-definition \
  --task-definition deep-insight-fargate-task-prod:1 \
  --output json | jq '.taskDefinition | {
    family,
    networkMode,
    cpu,
    memory,
    taskRoleArn,
    executionRoleArn,
    containerDefinitions: .containerDefinitions[0] | {name, image, portMappings, environment}
  }'
```

**확인 사항:**
- [ ] Network Mode: awsvpc
- [ ] Container Port: 8080
- [ ] Task Role 존재
- [ ] Execution Role 존재

---

## ✅ 6. ECR 이미지

### 개발 계정 (성공 ✅)

**Fargate Runtime:**
- Repository: dynamic-executor
- Latest Tag: v19-fix-exec-exception

**AgentCore Runtime:**
- Repository: bedrock-agentcore-deep_insight_runtime_vpc
- **Latest Tag 존재** ✅

### 프로덕션 확인 명령어
```bash
# AgentCore ECR 이미지
aws ecr list-images \
  --repository-name bedrock-agentcore-deep_insight_runtime_vpc \
  --output json | jq '.imageIds | map(select(.imageTag))'

# latest 태그 확인
aws ecr list-images \
  --repository-name bedrock-agentcore-deep_insight_runtime_vpc \
  --filter tagStatus=TAGGED \
  --output json | jq '.imageIds[] | select(.imageTag == "latest")'
```

**확인 사항:**
- [ ] latest 태그가 존재하는가?
- [ ] 이미지가 최근에 빌드되었는가?

**없으면:**
```bash
# 가장 최근 이미지에 latest 태그 추가
DIGEST=$(aws ecr describe-images \
  --repository-name bedrock-agentcore-deep_insight_runtime_vpc \
  --query 'sort_by(imageDetails, &imagePushedAt)[-1].imageDigest' \
  --output text)

MANIFEST=$(aws ecr batch-get-image \
  --repository-name bedrock-agentcore-deep_insight_runtime_vpc \
  --image-ids imageDigest=$DIGEST \
  --query 'images[0].imageManifest' \
  --output text)

aws ecr put-image \
  --repository-name bedrock-agentcore-deep_insight_runtime_vpc \
  --image-tag latest \
  --image-manifest "$MANIFEST"
```

---

## ✅ 7. IAM 권한

### 개발 계정 Task Execution Role 권한

**Managed Policies:**
- AmazonECSTaskExecutionRolePolicy

**Inline Policies:**
1. ECRAccess
2. CloudWatchLogsAccess
3. BedrockAccess
4. XRayAccess
5. **ECSAccess** (중요!)
6. **ELBAccess** (중요!)

### 프로덕션 확인 명령어
```bash
# Inline Policies 목록
aws iam list-role-policies \
  --role-name deep-insight-task-execution-role-prod

# 각 Policy 상세 (특히 ECSAccess, ELBAccess)
aws iam get-role-policy \
  --role-name deep-insight-task-execution-role-prod \
  --policy-name ECSAccess

aws iam get-role-policy \
  --role-name deep-insight-task-execution-role-prod \
  --policy-name ELBAccess
```

**확인 사항:**
- [ ] ECSAccess Policy 존재
  - ecs:RunTask
  - ecs:DescribeTasks
  - ecs:ListTasks
  - ecs:StopTask
  - iam:PassRole
- [ ] ELBAccess Policy 존재
  - elasticloadbalancing:RegisterTargets
  - elasticloadbalancing:DeregisterTargets
  - elasticloadbalancing:DescribeTargetHealth

---

## ✅ 8. Runtime 환경 변수

### 개발 계정 (성공 ✅)
```json
{
  "ECS_CLUSTER_NAME": "my-fargate-cluster",
  "ALB_TARGET_GROUP_ARN": "arn:aws:elasticloadbalancing:us-east-1:057716757052:targetgroup/test-vpc-private-tg/...",
  "AWS_REGION": "us-east-1",
  "AWS_ACCOUNT_ID": "057716757052",
  ...
}
```

### 프로덕션 확인 명령어
```bash
aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id deep_insight_runtime_vpc-rSd9kKHDB2 \
  --query 'environmentVariables' \
  --output json
```

**확인 사항:**
- [ ] ALB_TARGET_GROUP_ARN 존재 (최근 수정됨)
- [ ] ECS_CLUSTER_NAME 존재
- [ ] AWS_REGION 존재

---

## 🎯 가장 가능성 높은 원인 TOP 3

### 1. VPC Endpoint Security Group 규칙 누락 (90% 확률) ⭐⭐⭐

**증상:** Fargate Container가 ECR에서 이미지를 pull하지 못함

**확인:**
```bash
aws ec2 describe-security-groups \
  --group-ids sg-0d459967379994c48 \
  --query 'SecurityGroups[0].IpPermissions[*].[IpProtocol, FromPort, ToPort, IpRanges, UserIdGroupPairs]'
```

**해결:**
```bash
# VPC CIDR 허용 (권장)
aws ec2 authorize-security-group-ingress \
  --group-id sg-0d459967379994c48 \
  --protocol tcp \
  --port 443 \
  --cidr 10.0.0.0/16  # Production VPC CIDR로 변경

# 또는 Fargate SG 허용
aws ec2 authorize-security-group-ingress \
  --group-id sg-0d459967379994c48 \
  --protocol tcp \
  --port 443 \
  --source-group sg-0853a2a61c62e135b
```

### 2. Target Group Stickiness 미설정 (60% 확률) ⭐⭐

**증상:** Cookie 획득 실패, 매번 다른 Container로 요청 전달

**확인:**
```bash
aws elbv2 describe-target-group-attributes \
  --target-group-arn arn:aws:elasticloadbalancing:us-east-1:738490718699:targetgroup/deep-insight-tg-prod/... \
  | jq '.Attributes[] | select(.Key == "stickiness.enabled")'
```

**해결:**
```bash
aws elbv2 modify-target-group-attributes \
  --target-group-arn arn:aws:elasticloadbalancing:us-east-1:738490718699:targetgroup/deep-insight-tg-prod/... \
  --attributes \
    Key=stickiness.enabled,Value=true \
    Key=stickiness.type,Value=lb_cookie \
    Key=stickiness.lb_cookie.duration_seconds,Value=86400
```

### 3. ECS/ELB IAM 권한 누락 (50% 확률) ⭐

**증상:** Fargate Task 시작 실패

**확인:**
```bash
aws iam list-role-policies --role-name deep-insight-task-execution-role-prod
```

**해결:** CloudFormation 템플릿에 이미 추가됨 (Git Pull 후 Stack Update 필요)

---

## 📝 체크리스트 사용 방법

1. **이 문서를 프로덕션 계정에서 접근 가능한 곳에 복사**
2. **각 섹션의 "확인 명령어"를 프로덕션 계정에서 실행**
3. **개발 계정 값과 비교하여 차이점 찾기**
4. **차이가 있으면 "해결" 섹션의 명령어 실행**
5. **모든 체크박스 완료 후 Runtime Update 및 재시도**

---

생성 날짜: 2025-11-05
개발 계정: 057716757052
프로덕션 계정: 738490718699
