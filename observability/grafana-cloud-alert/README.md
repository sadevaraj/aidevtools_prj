# SAVE-ERROR LOG — authenticated development save alert

The [#20 replacement](../../docs/specs/issue-20-replacement.md), approved in
user chat at 2026-10-28T09:39:20Z (“approved do it”), replaces the old metric
rule/demo-fault procedure with the **actual existing SAVE-ERROR LOG** alert
and authenticated bounded repair path. No Grafana change is applied here.

## Contract

`alert-contract.json` describes a five-minute Loki count of structured
`service_name=sudoku-api`, `operation=save_game`, `outcome=server_error` logs.
Only a positive finite `values.A`, one firing alert and these notification
labels qualify:

- `alertname=SAVE-ERROR LOG`
- `operation=save_game`
- `service=sudoku-api`
- `severity=warning`

Save 4xx rejections, unrelated operation failures, exporter diagnostics, no-data,
query errors and resolved notifications do not trigger repair. Rule evaluation
is every 30 seconds with no extra pending period. No-data is OK; query errors
are Error but fail the receiver's strict positive save-alert validation.

The contact point uses HTTPS POST, Bearer authorization, one alert per message
and no resolve delivery. The receiver uses its existing private credential;
normal player authentication/CSRF is not repurposed for this webhook.

## Owner-operated setup (not executed)

Use the **existing** Grafana SAVE-ERROR LOG rule, not a second duplicate rule.
Inspect/export its actual UID and data source privately; import/adapt the
Terraform resource to that UID before applying an authorized update. The UID
in source is a configuration identifier, not evidence that it is the live UID.
The existing Loki source must expose the service label and structured JSON
fields above; independently confirm the actual exported log schema.

Supply `loki_datasource_uid`, `webhook_url` pointing to the existing Sudoku
backend `/api/alerts/grafana`, and `webhook_bearer_token` privately. Terraform
Grafana authentication and sensitive variables belong in private process/
secret configuration, never Git, logs or chat. State/plan files can contain
credentials and must remain ignored/private. Do not print a plan with secrets.
Pinned Terraform/provider versions are in `versions.tf`; no new tooling is
required by this cleanup's configured tests.

Update the existing rule's notification policy/contact point to deliver the
authenticated webhook. Verify with a genuine qualifying save-server-error
event only during a separately confirmed future exercise; a generic contact
point test does not prove real SAVE-ERROR LOG evaluation and routing.
Keep `ALERT_REPAIR_ENABLED=false` until operational prerequisites are verified.

## Verification boundaries

The configured backend tests validate the rule contract, private webhook
configuration, negative event cases and isolated mock HTTPS delivery. Receiver
tests cover authentication, positive finite values, malformed/oversized input,
durable deduplication, bounded outbox retry and signed run claims.
These are offline tests, not evidence of live Grafana routing, Copilot, PR
auto-merge, CI publication, Render deployment or recovery. No provider call,
dispatch or live fault is authorized now. Follow the
[operator runbook](../../docs/runbooks/development-save-demo.md) for all live
prerequisites and the 15-minute fail-stop/restoration timer.
