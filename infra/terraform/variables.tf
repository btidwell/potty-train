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

variable "xai_model_id" {
  type        = string
  description = "xAI model id used by the Strands chat agent."
  default     = "grok-4-1-fast-reasoning"
}

variable "otel_exporter_otlp_endpoint" {
  type        = string
  description = "Optional OTLP endpoint for agent traces. Empty keeps the console exporter (CloudWatch Logs)."
  default     = ""
}

