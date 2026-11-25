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

variable "allowed_cidrs" {
  type        = list(string)
  description = "Viewer addresses allowed to open the site. IPv4 must include a prefix. IPv6 must be one exact address."

  validation {
    condition     = length(var.allowed_cidrs) > 0
    error_message = "Pass at least one allowlist entry. Refusing to deploy an open site."
  }

  validation {
    condition = alltrue([
      for cidr in var.allowed_cidrs : cidr != "0.0.0.0/0" && cidr != "::/0"
    ])
    error_message = "Refusing to deploy an open site. 0.0.0.0/0 and ::/0 are not allowed."
  }

  validation {
    condition = alltrue([
      for cidr in var.allowed_cidrs :
      (!strcontains(cidr, ":") && can(cidrhost(cidr, 0))) ||
      (strcontains(cidr, ":") && !strcontains(cidr, "/"))
    ])
    error_message = "IPv4 entries must be CIDRs such as a /32. IPv6 entries must be an exact address with no prefix."
  }
}
