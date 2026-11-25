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

