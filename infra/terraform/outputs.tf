output "site_url" {
  description = "HTTPS URL of the CloudFront distribution."
  value       = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "user_pool_id" {
  description = "Cognito user pool. Sign-in is the email address."
  value       = aws_cognito_user_pool.users.id
}

output "user_pool_client_id" {
  description = "Public app client for the browser. It has no client secret."
  value       = aws_cognito_user_pool_client.web.id
}

output "data_bucket_name" {
  description = "Private bucket that holds state/potty-log.json."
  value       = aws_s3_bucket.data.bucket
}

output "distribution_id" {
  description = "CloudFront distribution id."
  value       = aws_cloudfront_distribution.site.id
}

output "github_deploy_role_arn" {
  description = "Role GitHub Actions assumes when it deploys main."
  value       = aws_iam_role.github_deploy.arn
}

output "viewer_countries" {
  description = "CloudFront geographic allow list."
  value       = aws_cloudfront_distribution.site.restrictions[0].geo_restriction[0].locations
}
