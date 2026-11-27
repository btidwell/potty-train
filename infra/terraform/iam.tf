resource "aws_iam_role" "api" {
  name = "potty-log-api"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "api_basic" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "api" {
  name = "potty-log-api"
  role = aws_iam_role.api.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadWriteLogObject"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          "${aws_s3_bucket.data.arn}/state/potty-log.json",
          "${aws_s3_bucket.data.arn}/state/sessions.json",
        ]
      },
      {
        Sid    = "InviteUsers"
        Effect = "Allow"
        Action = [
          "cognito-idp:AdminCreateUser",
          "cognito-idp:AdminForgetDevice",
          "cognito-idp:AdminGetUser",
          "cognito-idp:AdminSetUserMFAPreference",
          "cognito-idp:AdminListGroupsForUser",
          "cognito-idp:ListUsers",
        ]
        Resource = aws_cognito_user_pool.users.arn
      },
      {
        Sid      = "ReadAppSecrets"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
        Resource = [
          aws_secretsmanager_secret.app.arn,
          aws_secretsmanager_secret.vapid.arn,
        ]
      },
      {
        Sid    = "ManageTimerSchedules"
        Effect = "Allow"
        Action = [
          "scheduler:CreateSchedule",
          "scheduler:UpdateSchedule",
          "scheduler:DeleteSchedule",
          "scheduler:GetSchedule",
        ]
        Resource = "arn:aws:scheduler:us-east-1:143977713810:schedule/default/potty-log-*"
      },
      {
        Sid      = "PassSchedulerRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = aws_iam_role.scheduler.arn
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "scheduler.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role" "scheduler" {
  name = "potty-log-scheduler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "scheduler.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "potty-log-scheduler"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeApi"
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = "arn:aws:lambda:us-east-1:143977713810:function:potty-log-api"
      }
    ]
  })
}

# Owner-created Lambda roles. Ben creates these outside Terraform; see AGENTS.md.
data "aws_iam_role" "mcp" {
  name = "potty-log-mcp"
}

data "aws_iam_role" "agent" {
  name = "potty-log-agent"
}
