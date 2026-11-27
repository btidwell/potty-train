# Potty Log

A phone-friendly log for the scheduled-sit plan in `ABA Potty Training.pdf`.

The data sheet is the rule the app follows, because that is the rule the filled-in example uses:

- Dry for 3 intervals in a row, with a pee or poop on the toilet in at least one of them: add the step (5 minutes by default).
- Accidents on 2 intervals in a row: subtract the step.
- An accident sit does not reset the off-potty timer. A scheduled sit, or a sit he asked for, starts the next interval when it is saved.

The instruction pages also mention adding 5–10 minutes. Change the step in Settings if you want 10.

## Run it on this computer

Two terminals, from the project root.

```powershell
python -m pip install -r backend/requirements-dev.txt
python backend/local_server.py
```

Sign-in uses the Cognito user pool. Terraform writes the pool ids to `backend/.local-cognito.json` (gitignored). Without that file the API still runs, and the sign-in page reports that sign-in is not configured.

```powershell
cd frontend
npm start
```

Open http://localhost:4200 . The dev server proxies `/api` to http://127.0.0.1:8787 . This local server is only a stand-in. The deployed API is the Lambda function.

Optional local chat: put `{"xai_api_key":"..."}` in gitignored `backend/.local-secrets.json`, then use **Ask** in the top-right on any signed-in page.

## Deploy to AWS

The live stack is Terraform, in `infra/terraform/`.

- **S3** `ui` holds the Angular build. It is private. CloudFront reads it with origin access control.
- **S3** `data` holds one versioned object, `state/potty-log.json`. Public access is blocked, TLS is required, and the bucket is kept if you delete the stack.
- **Lambda** `potty-log-api` runs `potty_train.handler.handler`. It can read and write that one object, read the app secret, and manage the two reminder schedules.
- **Lambda** `potty-log-mcp` serves schedule/sheet tools over MCP (IAM Function URL).
- **Lambda** `potty-log-agent` is a streaming Strands chat agent (x.ai + OTEL). CloudFront routes `/api/chat*` to it.
- **Secrets Manager** holds one aggregated secret (`potty-log`) as JSON key/value pairs: `password`, `token_key`, `vapid_private_pem`, `vapid_public_pem`, `xai_api_key`. Add the xAI key in the console after apply; Terraform will not overwrite later edits.
- **Cognito** is the user directory. The username is the email address. Public sign-up is off. The owner invites someone from Settings, and Cognito emails a temporary password. MFA is a TOTP authenticator app. The refresh token lasts 7 days from login. The browser holds tokens in cookies.
- **CloudFront** serves the site and `/api/*` to viewers in the United States. The geographic restriction is CloudFront's built-in allow list. The API origin checks a shared header, so skipping CloudFront does not reach the Lambda.

CloudFront is created from `us-east-1`.

```powershell
cd frontend
npm ci
npm run build
cd ..
python backend/package_lambda.py
cd infra/terraform
terraform apply
```

Pushes to any branch other than `main` run the backend tests and a production frontend build (`.github/workflows/ci.yml`). A push to `main` runs those same checks, then packages the Lambda and runs `terraform apply` (`.github/workflows/deploy.yml`). That workflow assumes `potty-log-github-deploy`.

Open the `site_url` output. The UI uses hash routes (`/#/now`), so a refresh stays on the page you were on.

New accounts are invite-only. The owner sends the invite from Settings. Every account sees the same log.

Cost is mostly CloudFront, plus a little Lambda, S3, and Cognito. There is no WAF. Expect a few dollars a month for a single household, plus whatever CloudFront serves. The user pool is on the Essentials plan because that is the plan that can rotate refresh tokens. Essentials and Lite both include 10,000 monthly active users at no charge, so a household stays inside that allowance. Sign-up and reset emails use Cognito's built-in mailer.

Deleting the stack does not delete the data bucket, the user pool, or the secrets. Empty and delete those yourself if you really want them gone.

## Tests

```powershell
cd backend
python -m pytest
```
