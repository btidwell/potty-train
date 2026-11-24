"""Private potty-log hosting.

The site and the API sit behind one CloudFront distribution. A viewer-request
function allows only the CIDRs passed at deploy time (`-c allowedCidrs=`).
The Lambda function URL requires IAM, and CloudFront is the only caller, via
origin access control. The data object and the password live in private S3
and Secrets Manager. The Lambda role can read those two secrets and read or
write the single log object.
"""

from __future__ import annotations

import json
import re

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as aws_lambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

_CIDR = re.compile(r"^[0-9A-Fa-f:.]+(?:/\d{1,3})?$")
_STATE_KEY = "state/potty-log.json"


class PottyTrainStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        allowed = _allowed_cidrs(self.node.try_get_context("allowedCidrs"))

        data_bucket = s3.Bucket(
            self,
            "Data",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        ui_bucket = s3.Bucket(
            self,
            "Ui",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        password = secretsmanager.Secret(
            self,
            "Password",
            description="Password for the potty training log.",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True,
                password_length=20,
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )
        token_key = secretsmanager.Secret(
            self,
            "TokenKey",
            description="HMAC key for potty log session tokens.",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True,
                password_length=48,
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )

        log_group = logs.LogGroup(
            self,
            "ApiLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        api = aws_lambda.Function(
            self,
            "Api",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            handler="potty_train.handler.handler",
            code=aws_lambda.Code.from_asset(
                "../backend",
                exclude=[
                    "tests",
                    "tests/**",
                    ".pytest_cache",
                    ".pytest_cache/**",
                    "**/__pycache__/**",
                    ".local-*",
                    "local_server.py",
                    "pytest.ini",
                    "requirements-dev.txt",
                ],
            ),
            timeout=Duration.seconds(10),
            memory_size=256,
            reserved_concurrent_executions=5,
            log_group=log_group,
            environment={
                "DATA_BUCKET": data_bucket.bucket_name,
                "STATE_KEY": _STATE_KEY,
                "APP_PASSWORD_SECRET_ARN": password.secret_arn,
                "APP_TOKEN_SECRET_ARN": token_key.secret_arn,
            },
        )
        api.add_to_role_policy(
            iam.PolicyStatement(
                sid="ReadWriteLogObject",
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[data_bucket.arn_for_objects(_STATE_KEY)],
            )
        )
        password.grant_read(api)
        token_key.grant_read(api)

        function_url = api.add_function_url(auth_type=aws_lambda.FunctionUrlAuthType.AWS_IAM)
        allow_home = cloudfront.Function(
            self,
            "AllowHome",
            comment="Allow only the networks passed in allowedCidrs.",
            code=cloudfront.FunctionCode.from_inline(_allow_function(allowed)),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )
        ip_gate = [
            cloudfront.FunctionAssociation(
                function=allow_home,
                event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
            )
        ]
        distribution = cloudfront.Distribution(
            self,
            "Site",
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(ui_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
                function_associations=ip_gate,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.FunctionUrlOrigin.with_origin_access_control(function_url),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD_OPTIONS,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
                    function_associations=ip_gate,
                )
            },
        )
        s3deploy.BucketDeployment(
            self,
            "DeployUi",
            sources=[s3deploy.Source.asset("../frontend/dist/frontend/browser")],
            destination_bucket=ui_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
            memory_limit=512,
        )

        CfnOutput(self, "SiteUrl", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "PasswordSecretName", value=password.secret_name)
        CfnOutput(self, "DataBucketName", value=data_bucket.bucket_name)
        CfnOutput(self, "AllowedCidrs", value=",".join(allowed))


def _allowed_cidrs(raw: object) -> list[str]:
    if raw is None or not str(raw).strip():
        raise ValueError(
            "Refusing to deploy an open site. Pass -c allowedCidrs=203.0.113.10/32 "
            "(comma-separated if you need more than one)."
        )
    cidrs = [part.strip() for part in str(raw).split(",") if part.strip()]
    bad = [cidr for cidr in cidrs if not _CIDR.fullmatch(cidr)]
    if bad:
        raise ValueError(f"These allowlist entries are not IP addresses or CIDRs: {', '.join(bad)}")
    return cidrs


def _allow_function(cidrs: list[str]) -> str:
    encoded = json.dumps(cidrs)
    return f"""
function handler(event) {{
  var ip = normalize(event.viewer.ip || '');
  var cidrs = {encoded};
  for (var i = 0; i < cidrs.length; i++) {{
    if (matches(ip, cidrs[i])) {{
      return event.request;
    }}
  }}
  return {{
    statusCode: 403,
    statusDescription: 'Forbidden',
    headers: {{ 'content-type': {{ value: 'text/plain; charset=utf-8' }}, 'cache-control': {{ value: 'no-store' }} }},
    body: 'This app is only available from an allowed network.'
  }};
}}
function normalize(ip) {{
  if (ip.indexOf('::ffff:') === 0) {{
    return ip.substring(7);
  }}
  return ip;
}}
function matches(ip, cidr) {{
  var slash = cidr.indexOf('/');
  var base = slash === -1 ? cidr : cidr.substring(0, slash);
  if (ip.indexOf(':') !== -1 || base.indexOf(':') !== -1) {{
    return ip.toLowerCase() === base.toLowerCase();
  }}
  var bits = slash === -1 ? 32 : parseInt(cidr.substring(slash + 1), 10);
  if (bits < 0 || bits > 32) {{
    return false;
  }}
  var mask = bits === 0 ? 0 : ((0xffffffff << (32 - bits)) >>> 0);
  return (ipv4(ip) & mask) === (ipv4(base) & mask);
}}
function ipv4(ip) {{
  var parts = ip.split('.');
  if (parts.length !== 4) {{
    return -1;
  }}
  var value = 0;
  for (var i = 0; i < 4; i++) {{
    var n = parseInt(parts[i], 10);
    if (isNaN(n) || n < 0 || n > 255) {{
      return -1;
    }}
    value = (value * 256 + n) >>> 0;
  }}
  return value;
}}
"""
