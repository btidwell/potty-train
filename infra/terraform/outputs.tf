output "site_url" {
  description = "HTTPS URL of the CloudFront distribution."
  value       = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "password_secret_name" {
  description = "Secrets Manager name of the site password. The value is not an output."
  value       = aws_secretsmanager_secret.password.name
}

output "token_key_secret_name" {
  description = "Secrets Manager name of the session token key. The value is not an output."
  value       = aws_secretsmanager_secret.token_key.name
}

output "data_bucket_name" {
  description = "Private bucket that holds state/potty-log.json."
  value       = aws_s3_bucket.data.bucket
}

output "distribution_id" {
  description = "CloudFront distribution id."
  value       = aws_cloudfront_distribution.site.id
}

output "allowed_cidrs" {
  description = "Viewer allowlist baked into the CloudFront function."
  value       = var.allowed_cidrs
}
