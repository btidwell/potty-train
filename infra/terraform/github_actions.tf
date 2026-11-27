# GitHub Actions on main assumes this role. There are no long-lived keys.
# The subject claim is limited to a push to main of this repository. This
# repo uses immutable subject claims, so sub includes the owner id and
# repository id. AWS does not accept workflow_ref as a condition key, so
# the workflow file is not part of the trust policy.
# The first apply has to come from a principal that already has IAM access.
# After the role exists, later applies can come from the workflow.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "github_deploy" {
  name = "potty-log-github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            "token.actions.githubusercontent.com:sub" = "repo:btidwell@2204439/potty-train@1470478707:ref:refs/heads/main"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_deploy" {
  name = "potty-log-github-deploy"
  role = aws_iam_role.github_deploy.id

  # Scoped to this stack. CloudFront and a few list calls have no resource ARN.
  # The data bucket and the three app secrets cannot be deleted from CI.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TerraformState"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:GetBucketVersioning",
          "s3:GetEncryptionConfiguration",
        ]
        Resource = "arn:aws:s3:::potty-log-tfstate-143977713810"
      },
      {
        Sid    = "TerraformStateObjects"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = "arn:aws:s3:::potty-log-tfstate-143977713810/potty-log/*"
      },
      {
        Sid    = "AppBuckets"
        Effect = "Allow"
        Action = ["s3:*"]
        Resource = [
          "arn:aws:s3:::potty-log-data-143977713810",
          "arn:aws:s3:::potty-log-data-143977713810/*",
          "arn:aws:s3:::potty-log-ui-143977713810",
          "arn:aws:s3:::potty-log-ui-143977713810/*",
        ]
      },
      {
        Sid      = "KeepDataBucket"
        Effect   = "Deny"
        Action   = ["s3:DeleteBucket"]
        Resource = "arn:aws:s3:::potty-log-data-143977713810"
      },
      {
        Sid    = "Lambda"
        Effect = "Allow"
        Action = ["lambda:*"]
        Resource = [
          "arn:aws:lambda:us-east-1:143977713810:function:potty-log-api",
          "arn:aws:lambda:us-east-1:143977713810:function:potty-log-api:*",
        ]
      },
      {
        Sid    = "AppRoles"
        Effect = "Allow"
        Action = [
          "iam:GetRole",
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:UpdateRole",
          "iam:UpdateAssumeRolePolicy",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:ListRoleTags",
          "iam:ListRolePolicies",
          "iam:GetRolePolicy",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:ListAttachedRolePolicies",
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy",
          "iam:ListInstanceProfilesForRole",
        ]
        Resource = [
          "arn:aws:iam::143977713810:role/potty-log-api",
          "arn:aws:iam::143977713810:role/potty-log-scheduler",
          "arn:aws:iam::143977713810:role/potty-log-github-deploy",
        ]
      },
      {
        Sid    = "PassAppRoles"
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          "arn:aws:iam::143977713810:role/potty-log-api",
          "arn:aws:iam::143977713810:role/potty-log-scheduler",
        ]
        Condition = {
          StringEquals = {
            "iam:PassedToService" = [
              "lambda.amazonaws.com",
              "scheduler.amazonaws.com",
            ]
          }
        }
      },
      {
        Sid      = "LambdaBasicPolicy"
        Effect   = "Allow"
        Action   = ["iam:GetPolicy", "iam:GetPolicyVersion"]
        Resource = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
      },
      {
        Sid    = "GitHubOidcProvider"
        Effect = "Allow"
        Action = [
          "iam:GetOpenIDConnectProvider",
          "iam:CreateOpenIDConnectProvider",
          "iam:DeleteOpenIDConnectProvider",
          "iam:UpdateOpenIDConnectProviderThumbprint",
          "iam:AddClientIDToOpenIDConnectProvider",
          "iam:RemoveClientIDFromOpenIDConnectProvider",
          "iam:TagOpenIDConnectProvider",
          "iam:UntagOpenIDConnectProvider",
          "iam:ListOpenIDConnectProviderTags",
        ]
        Resource = "arn:aws:iam::143977713810:oidc-provider/token.actions.githubusercontent.com"
      },
      {
        Sid      = "Cognito"
        Effect   = "Allow"
        Action   = ["cognito-idp:*"]
        Resource = "arn:aws:cognito-idp:us-east-1:143977713810:userpool/*"
      },
      {
        Sid      = "CognitoList"
        Effect   = "Allow"
        Action   = ["cognito-idp:ListUserPools"]
        Resource = "*"
      },
      {
        Sid      = "PottySecrets"
        Effect   = "Allow"
        Action   = ["secretsmanager:*"]
        Resource = "arn:aws:secretsmanager:us-east-1:143977713810:secret:potty-log-*"
      },
      {
        Sid      = "KeepPottySecrets"
        Effect   = "Deny"
        Action   = ["secretsmanager:DeleteSecret"]
        Resource = "arn:aws:secretsmanager:us-east-1:143977713810:secret:potty-log-*"
      },
      {
        Sid      = "ListLogGroups"
        Effect   = "Allow"
        Action   = ["logs:DescribeLogGroups"]
        Resource = "*"
      },
      {
        Sid    = "ApiLogGroup"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:PutRetentionPolicy",
          "logs:ListTagsForResource",
          "logs:TagResource",
          "logs:UntagResource",
          "logs:ListTagsLogGroup",
          "logs:TagLogGroup",
          "logs:UntagLogGroup",
        ]
        Resource = [
          "arn:aws:logs:us-east-1:143977713810:log-group:/aws/lambda/potty-log-api",
          "arn:aws:logs:us-east-1:143977713810:log-group:/aws/lambda/potty-log-api:*",
        ]
      },
      {
        Sid    = "CloudFront"
        Effect = "Allow"
        Action = [
          "cloudfront:CreateDistribution",
          "cloudfront:GetDistribution",
          "cloudfront:GetDistributionConfig",
          "cloudfront:UpdateDistribution",
          "cloudfront:DeleteDistribution",
          "cloudfront:ListDistributions",
          "cloudfront:TagResource",
          "cloudfront:UntagResource",
          "cloudfront:ListTagsForResource",
          "cloudfront:CreateOriginAccessControl",
          "cloudfront:GetOriginAccessControl",
          "cloudfront:GetOriginAccessControlConfig",
          "cloudfront:UpdateOriginAccessControl",
          "cloudfront:DeleteOriginAccessControl",
          "cloudfront:ListOriginAccessControls",
          "cloudfront:CreateInvalidation",
          "cloudfront:GetInvalidation",
        ]
        Resource = "*"
      },
    ]
  })
}
