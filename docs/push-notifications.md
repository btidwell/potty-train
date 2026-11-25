# Closed-app timer notifications

Handoff for a later session. This note is the plan only. Do not treat it as implemented.

The live stack is Terraform in `infra/terraform/`: data bucket `potty-log-data-143977713810`, Lambda `potty-log-api`, Python 3.12, region `us-east-1`, account `143977713810`. The CDK app in `infra/potty_train_stack.py` is not what is deployed. Leave that file alone.

## What works today

The potty log timer is an absolute deadline stored in the S3 state object, not a countdown that pauses when the phone sleeps.

- `schedule.next_sit_at` is the off-potty deadline. `start_timer` in `backend/potty_train/service.py` sets it to `now + interval`.
- A sit ends at `active_sit.started_at` plus `settings.sit_minutes`.

The Now page (`frontend/src/app/now.ts`) keeps a 250ms `setInterval` that writes `Date.now()` into `nowMs`. `offLeft` subtracts that clock from `next_sit_at`, and `sitLeft` does the same for the sit end. The displayed countdown therefore looks like it kept running after the iPhone app was closed, because the deadline never depended on the page staying open.

The alert is not a push. `maybeNotify()` calls `showNotification()`, which calls `registration.showNotification()`, only while that page's JavaScript is running. Tags already in use:

- off-potty: `off:${next_sit_at}` with title `Time to go potty`
- sit end: `sit:${started_at}` with title `Sit time is up`

`maybeNotify` returns as soon as `schedule.active_sit` is set, so an off-potty alert is not shown during a sit. The same early return applies to the chime in `maybeChime`.

`frontend/public/sw.js` handles `install`, `activate`, and `notificationclick` only. It has no `push` listener. The app never calls `pushManager.subscribe`. The Allow notifications button in `frontend/src/app/now.html` calls `Notification.requestPermission()` from a click, then `navigator.serviceWorker.register('/sw.js')`.

iOS suspends and then kills the installed web app's page and service worker when it is closed. The notification appears only when the app is opened again and the interval sees the deadline has already passed. That matches the reported behavior.

A closed-app alert on iPhone (iOS 16.4+, installed to the Home Screen, manifest `display: standalone`) requires Web Push sent by a server at the deadline. This app already has `display: standalone` in `frontend/public/manifest.webmanifest`.

## What was not built

No EventBridge schedules, VAPID keys, push subscriptions, or service-worker `push` handler were added. No Terraform, Lambda, or frontend notification code was changed for this plan.

## Target behavior

- The installed iPhone home-screen app receives `Time to go potty` at `next_sit_at` and `Sit time is up` at the end of the sit, including when the app is closed.
- While the app is open, the existing local notification and chime stay. Use the same tags the page already uses so a push and a local notification collapse: `off:${next_sit_at}` and `sit:${started_at}`.
- Do not show the off-potty notification while a sit is active. That matches `maybeNotify`, which returns early during `active_sit`.
- An accident sit does not reset the off-potty clock (`_finish_sit_if_needed` restores `preserved_next_sit_at`). If the off deadline passes during the sit, skip that push. When the sit is saved or canceled, sync again: if the restored `next_sit_at` is still in the future, schedule it; if it is already due and not yet sent, send once.

Build the push payload with the same copy as `maybeNotify`:

- Off: title `Time to go potty`. Body is `{child_name}. {timer_interval_minutes} min off potty.` when the name is non-empty, otherwise `{timer_interval_minutes} min off potty.` If `timer_interval_minutes` is not a number, the length phrase is `Off-potty interval`.
- Sit: title `Sit time is up`. Body is `{child_name}. {sit_minutes} min sit.` or `{sit_minutes} min sit.`

## Design

### Keys

- Terraform `tls_private_key` ECDSA P-256 (`algorithm = "ECDSA"`, `ecdsa_curve = "P256"`), stored in Secrets Manager as `potty-log-vapid`. Secret string JSON: `private_pem` and `public_pem`. `prevent_destroy` on the secret, same as `potty-log-password` and `potty-log-token-key`.
- Lambda derives the browser `applicationServerKey`: uncompressed X9.62 point (`0x04 || X || Y`, 65 bytes), base64url, no padding. `pywebpush` already pulls `cryptography`; load the public PEM and encode `public_numbers()`.
- Include `push.public_key` (that base64url string) on the authenticated public state. Do not return stored subscriptions from `public_state`. Strip `state["reminders"]` and `state["push_subscriptions"]` from the public response.
- VAPID `sub` claim: a stable mailto, from env `VAPID_SUBJECT`. Set it to `mailto:btidwel3@gmail.com` unless a different contact is supplied at deploy. Apple expects a contact `sub`.

The Lambda is not in a VPC, so it can reach the push services without extra networking.

### Subscriptions

- `POST /api/push/subscribe` (auth required, same token check as the other routes) upserts by `endpoint` into `state["push_subscriptions"]`. Each item is `{endpoint, keys: {p256dh, auth}}`. Cap the list at 10; when a new endpoint would exceed the cap, drop the oldest other entries. Reject endpoints that do not start with `https://`. This route does not change the timer. It does not need the schedule sync.
- Frontend: the existing Allow notifications button already calls `Notification.requestPermission` from a click. After grant, register `/sw.js`, decode `push.public_key` into a `Uint8Array` (subscribe expects bytes, not the base64url string), call `pushManager.subscribe({ userVisibleOnly: true, applicationServerKey })`, and POST `subscription.toJSON()`. Also refresh the subscription on load when permission is already granted. That refresh must not set `api.busy()`, so Save buttons do not flash disabled.
- On iOS, subscribe fails unless the app is installed to the Home Screen. Surface that failure on the existing button. `Notification.permission === "granted"` is not enough to show `Notifications are on`.
- `sw.js` `push` handler reads JSON `{title, body, tag}` and calls `showNotification`. Always show a notification, including when the payload fails to parse (iOS drops subscriptions that do not show one). Omit `renotify` (Safari can throw). Keep the existing `notificationclick` behavior.
- `pywebpush` `webpush()` with the default content encoding `aes128gcm` (required by Apple). Do not pass the older `aesgcm` encoding. `ttl` 300. Header `Urgency: high`. The private key can be the PEM string (`Vapid.from_string`). `vapid_claims` is `{"sub": VAPID_SUBJECT}`. Remove subscriptions that return 404 or 410, then save the list. A 404/410 is a stale browser, not a failed invocation.

### Schedules

Two one-time schedules in the default group: `potty-log-off` and `potty-log-sit`.

- Expression `at(yyyy-mm-ddThh:mm:ss)` in UTC, with no `Z` inside the parentheses. Example: `at(2026-11-25T02:30:00)`.
- `FlexibleTimeWindow` mode `OFF`.
- `ActionAfterCompletion` `DELETE`.
- Target is the same Lambda. Input is the event object, not an HTTP request:

```json
{"reminder": {"kind": "off", "due": "<next_sit_at>"}}
{"reminder": {"kind": "sit", "started_at": "<started_at>"}}
```

- The sit schedule fires at `started_at + settings.sit_minutes`, not at `started_at`. The off schedule fires at `next_sit_at`.
- Scheduler invokes Lambda directly, not the function URL. The handler accepts that event only when it is not an HTTP event (`httpMethod` and `requestContext` both absent) and the top-level `reminder.kind` is `off` or `sit`. It must not require the CloudFront `X-Potty-Origin` header. An HTTP body must not be able to trigger a reminder, even if the JSON contains a `reminder` field. Branch on the event shape before `_from_cloudfront`.

EventBridge one-time schedules invoke with 60 second precision, and a time in the past is rejected. Sync after every mutation that can change the schedule. Hook that sync at the end of `_mutate` in `backend/potty_train/handler.py` (settings, entries, start/stop timer, start/cancel sit). `_mutate` already saves the domain change before it returns `public_state`.

Bookkeeping lives on `state["reminders"]`:

- `off_scheduled_for`, `sit_scheduled_for`: the deadline token last written to Scheduler
- `off_sent_for`, `sit_sent_for`: the deadline token already pushed

The sent token is the deadline string (`next_sit_at` or `started_at`), not the fire time. Strip `reminders` from the public response.

Off-potty sync:

- Timer stopped or `next_sit_at` empty: delete `potty-log-off` and clear `off_scheduled_for`.
- Due time more than about 60 seconds ahead, and `off_scheduled_for` differs from `next_sit_at`: upsert the schedule and store that `next_sit_at` on `off_scheduled_for`.
- A schedule for that same `next_sit_at` already exists (`off_scheduled_for` equals it): do not update it on later saves. Updating would slide the fire time.
- Due time already past, no active sit, and `off_sent_for` is not that `next_sit_at`: send the push immediately and set `off_sent_for` to that string. Do not send 60 seconds early. Do not create a schedule for a past or too-soon `at()` time.
- Active sit: do not send the off push, including when `next_sit_at` is already due. A future off schedule that still matches `off_scheduled_for` stays as it is.

Sit sync:

- No `active_sit`: delete `potty-log-sit` and clear `sit_scheduled_for`.
- Sit end more than about 60 seconds ahead, and `sit_scheduled_for` differs from `started_at`: upsert and store `started_at`.
- Same `started_at` already scheduled: do not update the schedule.
- Sit end already past and `sit_sent_for` is not that `started_at`: send once and record it. Do not send early.

The window from now through about 60 seconds ahead is neither scheduled nor sent early. Scheduler will reject that `at()` time. The open page still notifies itself.

When the reminder Lambda runs, reload state from S3. Send only if the token still matches and it was not already sent:

- `off`: `schedule.running`, `schedule.next_sit_at` equals `reminder.due`, `active_sit` is empty, and `off_sent_for` is not that due string. Then save `off_sent_for`.
- `sit`: `active_sit.started_at` equals `reminder.started_at`, and `sit_sent_for` is not that string. Then save `sit_sent_for`.
- If a sit is in progress when the off schedule fires, do not send and clear `off_scheduled_for`. The one-time schedule deletes itself. The next save or cancel syncs again. Do not set `off_sent_for` in this case, so a restored deadline that is already due can still send once.
- A stale reminder (different `due` or `started_at`, timer stopped, or sit already cleared) sends nothing and does not set `*_sent_for`. Clear `*_scheduled_for` only when it still equals the token that just fired. Leave it alone when bookkeeping already points at a newer token.
- No subscriptions left is still a successful invocation: record `*_sent_for` so retries do not repeat the work.
- After removing 404/410 subscriptions, save and return success. Raise on any other push failure so Scheduler retries.

If Scheduler sync throws, log it and still return the saved state. A failed save of a row, sit, or timer must not be turned into an HTTP error because CreateSchedule or DeleteSchedule failed. A failed reminder invocation should raise so Scheduler retries.

Retry policy on each target: `MaximumRetryAttempts` 2, `MaximumEventAgeInSeconds` 300 (the chosen window is 300 to 600). Default Scheduler retries (up to 185, over many hours) would deliver a late "time to go potty" long after the deadline. Set the short policy.

`POTTY_ENV=local` or a missing `SCHEDULER_ROLE_ARN` skips AWS scheduling. Local notifications still work from the open page. If VAPID material is missing locally, skip the immediate push send and do not fail the mutation.

### IAM and packaging

Lambda role (`potty-log-api`), in addition to the S3 and secret reads it already has:

- `scheduler:CreateSchedule`, `scheduler:UpdateSchedule`, `scheduler:DeleteSchedule`, `scheduler:GetSchedule` on `arn:aws:scheduler:us-east-1:143977713810:schedule/default/potty-log-*`
- `iam:PassRole` on the scheduler role, conditioned on `iam:PassedToService` = `scheduler.amazonaws.com`
- `secretsmanager:GetSecretValue` and `secretsmanager:DescribeSecret` on `potty-log-vapid`, matching the existing secret statements

Scheduler role (new) trusts `scheduler.amazonaws.com` and can `lambda:InvokeFunction` on `potty-log-api`.

Lambda env, added to the existing variables:

- `VAPID_SECRET_ARN`
- `SCHEDULER_ROLE_ARN`
- `SCHEDULE_TARGET_ARN`: build `arn:aws:lambda:us-east-1:143977713810:function:potty-log-api` from the known function name. Do not reference the Lambda resource inside its own environment block (that self-reference cycles).
- `VAPID_SUBJECT`

The scheduler role's invoke permission may use the function ARN. That reference is outside the Lambda environment block.

Lambda timeout is 10 seconds today (`aws_lambda_function.api` in `infra/terraform/main.tf`). Raise it to 20 seconds so a couple of push sends can finish.

New dependency `pywebpush` (pulls cryptography, http-ece, requests, py-vapid). Runtime already provides boto3; do not vendor boto3. There is no requirements file for the Lambda yet. Add one (for example `backend/requirements-lambda.txt` containing `pywebpush`) and a small package script rather than committing `build/`. The script should install those wheels into `infra/terraform/build/lambda` and copy the `potty_train` package beside them. That directory is gitignored and is the Terraform `archive_file` source (`infra/terraform/main.tf`). Install the same requirements in the test environment so the handler import succeeds.

Add the `hashicorp/tls` provider in `infra/terraform/versions.tf`, with a pessimistic constraint in the same style as the other providers (`~> 4.0`).

## Tests to add when implementing

- Future off timer schedules `potty-log-off` and does not send yet.
- Stop timer deletes it.
- Active sit schedules the sit end and does not send an off notification that is already due.
- After the sit ends, a past off deadline sends once and a second sync does not send again.
- Stale reminder (different `due` or `started_at`) sends nothing.
- `public_state` does not include subscriptions.
- Local env does not call AWS.

## Deploy notes

- Apply Terraform only after the Lambda package is built. Viewers are limited to the United States by CloudFront geographic restrictions. `allowed_cidrs` is no longer an input. If `deploy.auto.tfvars` still sets it, remove that line before apply.
- Rebuild and sync the frontend so the service worker and subscribe flow ship. CloudFront invalidation already happens from the Terraform UI `local-exec` provisioner in `infra/terraform/main.tf` (`aws s3 sync` of the UI bucket, then `aws cloudfront create-invalidation`).
- iPhone check: installed app, permission granted from the button, start a short timer, close the app, confirm the notification arrives without reopening. A last-minute close (under about a minute) can be late or missed because Scheduler will not accept a past or too-soon `at()` time. The open app still notifies itself.

## Cost

Checked against the AWS EventBridge pricing page. Scheduler is $1.00 per million invocations after a permanent 14 million invocations/month free allowance, shared across commercial regions. This household creates on the order of a few thousand fires a month, so Scheduler is $0. Creating or deleting a schedule before it fires is not billed. Lambda invoked by those fires is a separate line and is also about $0 at this volume. Default Scheduler retries (up to 185) still stay inside the free allowance here; the plan sets a short retry policy anyway (2 attempts, max age 300 seconds) so a failed send does not arrive hours late.

The 60-second schedule precision is the behavioral limit, not a cost limit. A deadline inside that window is left to the open page.
