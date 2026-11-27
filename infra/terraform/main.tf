locals {
  state_key = "state/potty-log.json"
  ui_dir    = abspath("${path.module}/../../frontend/dist/frontend/browser")
  ui_files  = fileset(local.ui_dir, "**")
  ui_hash = sha256(join("", [
    for name in sort(tolist(local.ui_files)) :
    "${name}:${filesha256("${local.ui_dir}/${name}")}"
  ]))
}

resource "aws_s3_bucket" "data" {
  bucket        = "potty-log-data-143977713810"
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "data" {
  bucket = aws_s3_bucket.data.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.data.arn,
          "${aws_s3_bucket.data.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.data]
}

resource "aws_s3_bucket" "ui" {
  bucket        = "potty-log-ui-143977713810"
  force_destroy = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ui" {
  bucket = aws_s3_bucket.ui.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "ui" {
  bucket                  = aws_s3_bucket.ui.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "random_password" "password" {
  length  = 20
  special = false
}

resource "random_password" "token_key" {
  length  = 48
  special = false
}

resource "random_password" "origin_header" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "password" {
  name        = "potty-log-password"
  description = "Password for the potty training log."

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "password" {
  secret_id     = aws_secretsmanager_secret.password.id
  secret_string = random_password.password.result

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "token_key" {
  name        = "potty-log-token-key"
  description = "HMAC key for potty log session tokens."

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "token_key" {
  secret_id     = aws_secretsmanager_secret.token_key.id
  secret_string = random_password.token_key.result

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "tls_private_key" "vapid" {
  algorithm   = "ECDSA"
  ecdsa_curve = "P256"
}

resource "aws_secretsmanager_secret" "vapid" {
  name        = "potty-log-vapid"
  description = "VAPID signing key for potty log web push."

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "vapid" {
  secret_id = aws_secretsmanager_secret.vapid.id
  secret_string = jsonencode({
    private_pem = tls_private_key.vapid.private_key_pem
    public_pem  = tls_private_key.vapid.public_key_pem
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# One ARN for every app secret. Existing values are copied in once; later
# edits (for example adding xai_api_key) are done in the console and kept.
data "aws_secretsmanager_secret_version" "password_current" {
  secret_id  = aws_secretsmanager_secret.password.id
  depends_on = [aws_secretsmanager_secret_version.password]
}

data "aws_secretsmanager_secret_version" "token_key_current" {
  secret_id  = aws_secretsmanager_secret.token_key.id
  depends_on = [aws_secretsmanager_secret_version.token_key]
}

data "aws_secretsmanager_secret_version" "vapid_current" {
  secret_id  = aws_secretsmanager_secret.vapid.id
  depends_on = [aws_secretsmanager_secret_version.vapid]
}

locals {
  vapid_current = jsondecode(data.aws_secretsmanager_secret_version.vapid_current.secret_string)
}

resource "aws_secretsmanager_secret" "app" {
  name        = "potty-log"
  description = "All potty-log secrets as JSON key/value pairs."

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    password          = data.aws_secretsmanager_secret_version.password_current.secret_string
    token_key         = data.aws_secretsmanager_secret_version.token_key_current.secret_string
    vapid_private_pem = local.vapid_current.private_pem
    vapid_public_pem  = local.vapid_current.public_pem
    xai_api_key       = ""
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/potty-log-api"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "mcp" {
  name              = "/aws/lambda/potty-log-mcp"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "agent" {
  name              = "/aws/lambda/potty-log-agent"
  retention_in_days = 30
}

data "archive_file" "api" {
  type        = "zip"
  source_dir  = "${path.module}/build/lambda"
  output_path = "${path.module}/build/api.zip"
  excludes    = ["__pycache__", "**/__pycache__/**", "**/*.pyc"]
}

data "archive_file" "mcp" {
  type        = "zip"
  source_dir  = "${path.module}/build/mcp"
  output_path = "${path.module}/build/mcp.zip"
  excludes    = ["__pycache__", "**/__pycache__/**", "**/*.pyc"]
}

data "archive_file" "agent" {
  type        = "zip"
  source_dir  = "${path.module}/build/agent"
  output_path = "${path.module}/build/agent.zip"
  excludes    = ["__pycache__", "**/__pycache__/**", "**/*.pyc"]
}

resource "aws_lambda_function" "api" {
  function_name                  = "potty-log-api"
  role                           = aws_iam_role.api.arn
  runtime                        = "python3.12"
  handler                        = "potty_train.handler.handler"
  filename                       = data.archive_file.api.output_path
  source_code_hash               = data.archive_file.api.output_base64sha256
  memory_size = 256
  timeout     = 20

  environment {
    variables = {
      DATA_BUCKET             = aws_s3_bucket.data.bucket
      STATE_KEY               = local.state_key
      SESSIONS_KEY            = "state/sessions.json"
      COGNITO_USER_POOL_ID    = aws_cognito_user_pool.users.id
      COGNITO_CLIENT_ID       = aws_cognito_user_pool_client.web.id
      COGNITO_REGION          = var.aws_region
      POTTY_ORIGIN_SECRET     = random_password.origin_header.result
      APP_SECRET_ARN          = aws_secretsmanager_secret.app.arn
      VAPID_SECRET_ARN        = aws_secretsmanager_secret.vapid.arn
      VAPID_SUBJECT           = var.vapid_subject
      SCHEDULER_ROLE_ARN      = aws_iam_role.scheduler.arn
      # Literal on purpose. Referencing aws_lambda_function.api from its own
      # environment block makes Terraform plan a cycle.
      SCHEDULE_TARGET_ARN     = "arn:aws:lambda:us-east-1:143977713810:function:potty-log-api"
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.api.name
  }

  depends_on = [
    aws_cloudwatch_log_group.api,
    aws_iam_role_policy_attachment.api_basic,
    aws_iam_role_policy.api,
  ]
}

resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "AWS_IAM"
}

resource "aws_lambda_function" "mcp" {
  function_name    = "potty-log-mcp"
  role             = data.aws_iam_role.mcp.arn
  runtime          = "python3.12"
  handler          = "potty_mcp.handler.handler"
  filename         = data.archive_file.mcp.output_path
  source_code_hash = data.archive_file.mcp.output_base64sha256
  memory_size      = 512
  timeout          = 30

  environment {
    variables = {
      DATA_BUCKET  = aws_s3_bucket.data.bucket
      STATE_KEY    = local.state_key
      SESSIONS_KEY = "state/sessions.json"
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.mcp.name
  }

  depends_on = [
    aws_cloudwatch_log_group.mcp,
  ]
}

resource "aws_lambda_function_url" "mcp" {
  function_name      = aws_lambda_function.mcp.function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "BUFFERED"
}

resource "aws_lambda_function" "agent" {
  function_name = "potty-log-agent"
  role          = data.aws_iam_role.agent.arn
  runtime       = "python3.12"
  # Lambda Web Adapter starts uvicorn via run.sh.
  handler          = "run.sh"
  filename         = data.archive_file.agent.output_path
  source_code_hash = data.archive_file.agent.output_base64sha256
  memory_size      = 1024
  timeout          = 60

  layers = [
    "arn:aws:lambda:${var.aws_region}:753240598075:layer:LambdaAdapterLayerX86:30",
  ]

  environment {
    variables = merge(
      {
        AWS_LAMBDA_EXEC_WRAPPER   = "/opt/bootstrap"
        AWS_LWA_INVOKE_MODE       = "response_stream"
        AWS_LWA_PORT              = "8080"
        AWS_LWA_READINESS_CHECK_PATH = "/health"
        DATA_BUCKET               = aws_s3_bucket.data.bucket
        STATE_KEY                 = local.state_key
        SESSIONS_KEY              = "state/sessions.json"
        COGNITO_USER_POOL_ID      = aws_cognito_user_pool.users.id
        COGNITO_CLIENT_ID         = aws_cognito_user_pool_client.web.id
        COGNITO_REGION            = var.aws_region
        POTTY_ORIGIN_SECRET       = random_password.origin_header.result
        APP_SECRET_ARN            = aws_secretsmanager_secret.app.arn
        MCP_FUNCTION_URL          = aws_lambda_function_url.mcp.function_url
        XAI_MODEL_ID              = var.xai_model_id
        OTEL_SERVICE_NAME         = "potty-log-agent"
      },
      var.otel_exporter_otlp_endpoint != "" ? {
        OTEL_EXPORTER_OTLP_ENDPOINT = var.otel_exporter_otlp_endpoint
      } : {}
    )
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.agent.name
  }

  depends_on = [
    aws_cloudwatch_log_group.agent,
  ]
}

resource "aws_lambda_function_url" "agent" {
  function_name      = aws_lambda_function.agent.function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "RESPONSE_STREAM"
}

resource "terraform_data" "ui" {
  triggers_replace = [local.ui_hash]

  depends_on = [
    aws_cloudfront_distribution.site,
    aws_s3_bucket_policy.ui,
  ]

  lifecycle {
    precondition {
      condition     = fileexists("${local.ui_dir}/index.html")
      error_message = "frontend/dist/frontend/browser/index.html is missing. Build the frontend before apply."
    }
  }

  # python, not powershell, so the same apply works on Windows and on the Linux runner.
  provisioner "local-exec" {
    working_dir = abspath("${path.module}/../..")
    command     = "python scripts/publish_ui.py"
    environment = {
      POTTY_UI_DIR          = local.ui_dir
      POTTY_UI_BUCKET       = aws_s3_bucket.ui.bucket
      POTTY_DISTRIBUTION_ID = aws_cloudfront_distribution.site.id
    }
  }
}
