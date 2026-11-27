# Potty Log

Phone-friendly log for a scheduled-sit potty plan. The practice sheet is the rule the code follows. Read `README.md` before changing interval logic.

## Layout

- `frontend/` is the Angular app. Routes are hash URLs: `/#/now`, `/#/sheet`, `/#/people`, `/#/guide`, `/#/settings`, `/#/login`. The dev server proxies `/api` to `127.0.0.1:8787`.
- `backend/potty_train/` is the API. Production is the Lambda `potty_train.handler.handler`. `backend/local_server.py` is the local stand-in. It writes gitignored `backend/.local-*` files.
- `backend/tests/` is pytest. Those tests are the spec for the schedule, especially `test_rules.py`. The frontend has no unit tests.
- `infra/terraform/` is the live AWS stack. `infra/app.py` is the old CDK app.

## Commands

Cloud Builds create `.venv` at the repo root. Use that interpreter.

```bash
cd backend && ../.venv/bin/python -m pytest -q
```

```bash
npm run build --prefix frontend -- --configuration development
```

Start the app only when the task needs a running UI. The API first, then the dev server:

```bash
.venv/bin/python backend/local_server.py
npm start --prefix frontend -- --host 127.0.0.1 --port 4200
```

Open `http://127.0.0.1:4200/#/login`.

## Product rules

Leave these in place unless the task changes them:

- Three dry intervals in a row, with a pee or poop on the toilet in at least one, add the step (5 minutes by default).
- Accidents on two intervals in a row subtract the step.
- An accident sit does not reset the off-potty timer. A scheduled sit, or a sit he asked for, starts the next interval when it is saved.

## Cursor Cloud specific instructions

`.cursor/environment.json` builds the image from `.cursor/Dockerfile` and runs `scripts/cloud-install.sh` during each Build. Dependencies are already on disk when an agent starts. Re-run `bash scripts/cloud-install.sh` only when this branch changes `backend/requirements-dev.txt` or `frontend/package-lock.json`.

- Backend tests do not need AWS, Cognito, or network.
- Sign-in needs `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, and optionally `COGNITO_REGION` (default `us-east-1`). On a laptop those come from gitignored `backend/.local-cognito.json`. In the cloud they have to be [Cursor Secrets](https://cursor.com/dashboard/cloud-agents). Without them the API still starts, and the login page reports that sign-in is not configured. Do not add an auth bypass.
- Do not run `terraform apply`, `scripts/deploy.ps1`, or `python backend/package_lambda.py` unless the task is a deploy.
- Do not commit `.env`, `backend/.local-*`, `deploy.auto.tfvars`, or Terraform state.
- Ports 4200 (web) and 8787 (API) are forwarded. Nothing listens on them until the processes above are started.
