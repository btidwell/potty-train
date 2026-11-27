variable "vapid_subject" {
  type        = string
  description = "VAPID sub claim sent with web push. Apple expects a contact, usually a mailto URL."
  default     = "mailto:btidwel3@gmail.com"
}

variable "aws_region" {
  type        = string
  description = "Region for the app. CloudFront is created from us-east-1."
  default     = "us-east-1"
}

variable "github_repository" {
  type        = string
  description = "GitHub repository allowed to deploy, as owner/name."
  default     = "btidwell/potty-train"
}

