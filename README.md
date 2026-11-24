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

The API prints a local password and stores it in `backend/.local-password`. That file is gitignored.

```powershell
cd frontend
npm start
```

Open http://localhost:4200 . The dev server proxies `/api` to http://127.0.0.1:8787 . This local server is only a stand-in. The deployed API is the Lambda function.

## Deploy to AWS

The stack is CDK, in `infra/`.

- **S3** `Ui` holds the Angular build. It is private. CloudFront reads it with origin access control.
- **S3** `Data` holds one versioned object, `state/potty-log.json`. Public access is blocked, TLS is required, and the bucket is kept if you delete the stack.
- **Lambda** runs `potty_train.handler.handler`. Its role can `s3:GetObject` and `s3:PutObject` on that one key, and `secretsmanager:GetSecretValue` on the two secrets below. Nothing else.
- **Secrets Manager** stores the site password and the separate key used to sign login tokens.
- **CloudFront** serves the site and `/api/*`. A viewer-request function returns 403 for every IP outside the allowlist. The function URL itself uses IAM auth, and only this distribution can invoke it, so the API is not reachable by skipping CloudFront.
- Login is the second check, for anyone who is already on an allowed network.

CloudFront has to be deployed from a region that can create it. The app defaults to `us-east-1`.

Install the AWS CLI, sign in so `aws sts get-caller-identity` works, then:

```powershell
cd frontend
npm ci
npm run build
cd ../infra
python -m pip install -r requirements.txt
npx aws-cdk bootstrap
npx aws-cdk deploy -c allowedCidrs=YOUR.IP.ADDRESS/32
```

`https://checkip.amazonaws.com` shows the IPv4 address you are on right now. Home addresses are often stable. A phone on cellular data usually is not, so the allowlist is a poor fit for mobile data unless you add that address again when it changes. Several networks are fine: `-c allowedCidrs=1.2.3.4/32,5.6.7.0/24`. If your own browser gets a 403, it may be connecting over IPv6; add that address as well. An IPv6 entry has to be the exact address.

Changing the allowlist means deploying again with the new value.

The password is not printed. After deploy:

```powershell
aws secretsmanager get-secret-value --secret-id <PasswordSecretName output> --query SecretString --output text
```

Open the `SiteUrl` output. The UI uses hash routes (`/#/now`), so a refresh stays on the page you were on.

Cost is mostly CloudFront and a little Lambda and S3. There is no WAF. Expect a few dollars a month for a single household, plus whatever CloudFront serves.

Deleting the stack does not delete the data bucket or the secrets. Empty and delete those yourself if you really want them gone.

## Tests

```powershell
cd backend
python -m pytest
```
