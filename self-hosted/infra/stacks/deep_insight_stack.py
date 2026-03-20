"""
Deep Insight self-hosted infrastructure stack.

Architecture:
    Browser -> CloudFront -> ALB -> EC2 (FastAPI handles Cognito JWT auth)

Components:
    - VPC: 2 AZ, public + private subnets, 1 NAT Gateway
    - EC2: private subnet, SSM access, Amazon Linux 2023
    - ALB: public subnet, idle timeout 4000s, origin-verify header check
    - CloudFront: HTTPS termination, SSE pass-through
    - Cognito: User Pool + Hosted UI (auth handled by FastAPI middleware)
"""

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_cognito as cognito,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_elasticloadbalancingv2_targets as elbv2_targets,
    aws_iam as iam,
)
from constructs import Construct


class DeepInsightStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Context values ---
        instance_type_str = self.node.try_get_context("instance_type") or "t3.xlarge"
        admin_email = self.node.try_get_context("admin_email") or ""
        origin_verify_secret = self.node.try_get_context("origin_verify_secret") or "CHANGE-ME"

        # ============================================================
        # 1. VPC
        # ============================================================
        vpc = ec2.Vpc(
            self, "Vpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=24,
                ),
            ],
        )

        # ============================================================
        # 2. Security Groups
        # ============================================================
        alb_sg = ec2.SecurityGroup(self, "AlbSg", vpc=vpc, description="ALB - HTTP from CloudFront")
        alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "CloudFront via HTTP")

        ec2_sg = ec2.SecurityGroup(self, "Ec2Sg", vpc=vpc, description="EC2 - app traffic from ALB only")
        ec2_sg.add_ingress_rule(alb_sg, ec2.Port.tcp(8080), "FastAPI from ALB")

        # ============================================================
        # 3. EC2 Instance (private subnet, SSM + CloudWatch access)
        # ============================================================
        role = iam.Role(
            self, "Ec2Role",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonBedrockFullAccess"),
                iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3ReadOnlyAccess"),
            ],
        )

        user_data = ec2.UserData.for_linux()
        user_data_script = (Path(__file__).parent.parent / "user_data.sh").read_text()
        user_data.add_commands(user_data_script)

        instance = ec2.Instance(
            self, "AppServer",
            vpc=vpc,
            instance_type=ec2.InstanceType(instance_type_str),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_group=ec2_sg,
            role=role,
            user_data=user_data,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(50, volume_type=ec2.EbsDeviceVolumeType.GP3),
                )
            ],
        )

        # ============================================================
        # 4. ALB (public subnet, idle timeout 4000s)
        # ============================================================
        alb = elbv2.ApplicationLoadBalancer(
            self, "Alb",
            vpc=vpc,
            internet_facing=True,
            security_group=alb_sg,
        )
        alb.set_attribute("idle_timeout.timeout_seconds", "4000")

        listener = alb.add_listener("Http", port=80)
        listener.add_targets(
            "AppTarget",
            port=8080,
            targets=[elbv2_targets.InstanceTarget(instance, 8080)],
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=Duration.seconds(30),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
            ),
            deregistration_delay=Duration.seconds(30),
        )

        # ============================================================
        # 5. Cognito User Pool
        # ============================================================
        user_pool = cognito.UserPool(
            self, "UserPool",
            user_pool_name="deep-insight-users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        if admin_email:
            cognito.CfnUserPoolUser(
                self, "AdminUser",
                user_pool_id=user_pool.user_pool_id,
                username=admin_email,
                user_attributes=[
                    cognito.CfnUserPoolUser.AttributeTypeProperty(
                        name="email", value=admin_email,
                    ),
                    cognito.CfnUserPoolUser.AttributeTypeProperty(
                        name="email_verified", value="true",
                    ),
                ],
            )

        cognito_domain = user_pool.add_domain(
            "CognitoDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=cdk.Fn.join("-", ["deep-insight", cdk.Aws.ACCOUNT_ID]),
            ),
        )

        # ============================================================
        # 6. CloudFront (no Lambda@Edge — auth handled by FastAPI)
        # ============================================================
        distribution = cloudfront.Distribution(
            self, "Cdn",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.LoadBalancerV2Origin(
                    alb,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    custom_headers={"X-Origin-Verify": origin_verify_secret},
                    read_timeout=Duration.seconds(60),
                    keepalive_timeout=Duration.seconds(60),
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
            ),
        )

        # ============================================================
        # 7. Cognito App Client (needs CloudFront URL for callback)
        # ============================================================
        cf_url = cdk.Fn.join("", ["https://", distribution.distribution_domain_name])
        callback_url = cdk.Fn.join("", [cf_url, "/auth/callback"])
        cognito_domain_url = cognito_domain.base_url()

        app_client = user_pool.add_client(
            "WebAppClient",
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
                callback_urls=[callback_url],
                logout_urls=[cf_url],
            ),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
        )

        # ============================================================
        # 8. Outputs
        # ============================================================
        cdk.CfnOutput(self, "CloudFrontURL", value=cf_url, description="Application URL")
        cdk.CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        cdk.CfnOutput(self, "AppClientId", value=app_client.user_pool_client_id)
        cdk.CfnOutput(self, "CognitoDomainURL", value=cognito_domain_url)
        cdk.CfnOutput(self, "AlbDnsName", value=alb.load_balancer_dns_name, description="ALB DNS (internal)")
        cdk.CfnOutput(self, "Ec2InstanceId", value=instance.instance_id, description="SSM target")
        cdk.CfnOutput(self, "OriginVerifySecret", value=origin_verify_secret, description="Set this in .env.deploy ORIGIN_VERIFY_SECRET")
