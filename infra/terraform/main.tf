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
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/potty-log-api"
  retention_in_days = 30
}

data "archive_file" "api" {
  type        = "zip"
  source_dir  = "${path.module}/build/lambda"
  output_path = "${path.module}/build/api.zip"
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
  timeout     = 10

  environment {
    variables = {
      DATA_BUCKET             = aws_s3_bucket.data.bucket
      STATE_KEY               = local.state_key
      APP_PASSWORD_SECRET_ARN = aws_secretsmanager_secret.password.arn
      APP_TOKEN_SECRET_ARN    = aws_secretsmanager_secret.token_key.arn
      POTTY_ORIGIN_SECRET     = random_password.origin_header.result
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
  authorization_type = "NONE"
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

  provisioner "local-exec" {
    interpreter = ["powershell.exe", "-NoProfile", "-Command"]
    command     = "$ErrorActionPreference = 'Stop'; aws s3 sync '${local.ui_dir}' 's3://${aws_s3_bucket.ui.bucket}' --delete --region us-east-1 --only-show-errors; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; aws cloudfront create-invalidation --distribution-id ${aws_cloudfront_distribution.site.id} --paths '/*'; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }"
  }
}
