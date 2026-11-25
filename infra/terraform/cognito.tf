resource "aws_cognito_user_pool" "users" {
  name = "potty-log-users"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "ON"
  # Refresh-token rotation is not available on Lite. Essentials includes it
  # and the same 10,000 monthly-active-user allowance as Lite.
  user_pool_tier           = "ESSENTIALS"
  deletion_protection      = "ACTIVE"

  username_configuration {
    case_sensitive = false
  }

  software_token_mfa_configuration {
    enabled = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # A remembered device can skip the authenticator code on a later sign-in.
  # The user has to opt in. Signing that device out forgets it.
  device_configuration {
    challenge_required_on_new_device      = true
    device_only_remembered_on_user_prompt = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  # Cognito's own mailer sends the sign-up and reset codes. SNS email only
  # reaches addresses that have already confirmed a topic subscription, so it
  # cannot deliver a code to a new account.
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "Your Potty Log code"
    email_message        = "Your Potty Log code is {####}."
  }

  admin_create_user_config {
    allow_admin_create_user_only = true

    invite_message_template {
      email_subject = "You're invited to Potty Log"
      email_message = "You have been invited to Potty Log. Sign in at the site with username {username} and temporary password {####}. Then choose your own password and set up an authenticator app. The temporary password expires in 7 days."
      sms_message   = "Potty Log username {username}, temporary password {####}."
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "potty-log-web"
  user_pool_id = aws_cognito_user_pool.users.id

  generate_secret = false
  # Refresh-token rotation rejects the REFRESH_TOKEN_AUTH flow. The browser
  # uses GetTokensFromRefreshToken instead. The refresh token stays valid for
  # seven days from the original login.
  explicit_auth_flows = ["ALLOW_USER_SRP_AUTH"]

  refresh_token_validity = 7
  access_token_validity  = 1
  id_token_validity      = 1
  auth_session_validity  = 15

  token_validity_units {
    refresh_token = "days"
    access_token  = "hours"
    id_token      = "hours"
  }

  enable_token_revocation       = true
  prevent_user_existence_errors = "ENABLED"

  refresh_token_rotation {
    feature                    = "ENABLED"
    retry_grace_period_seconds = 30
  }
}

resource "aws_cognito_user_group" "owners" {
  name         = "owners"
  user_pool_id = aws_cognito_user_pool.users.id
  description  = "Can invite people to Potty Log."
}

resource "aws_cognito_user_in_group" "owner" {
  user_pool_id = aws_cognito_user_pool.users.id
  group_name   = aws_cognito_user_group.owners.name
  username     = "9458e4e8-30d1-708e-ef4b-17355f6326ff"
}

resource "local_file" "cognito" {
  filename = abspath("${path.module}/../../backend/.local-cognito.json")
  content = jsonencode({
    userPoolId       = aws_cognito_user_pool.users.id
    userPoolClientId = aws_cognito_user_pool_client.web.id
    region           = var.aws_region
    sessionDays      = 7
  })
}
