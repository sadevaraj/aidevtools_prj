# Grafana Cloud save-failure alert

This Terraform configuration manages only the approved Grafana Cloud alert rule
and its webhook contact point. It does not add an application receiver, alter
save handling, retry a save, or perform remediation. It is not applied by this
repository's tests.

The rule queries the existing `sudoku_save_requests_total` counter for the
`server_error` outcome and fires immediately when
`sum(increase(sudoku_save_requests_total{outcome="server_error"}[5m])) > 0`.
Expected 4xx outcomes have different bounded `outcome` values and are excluded.
An empty result/no metric sample is `OK`, not a save-failure alert. The rule has
only fixed service/operation/severity labels and fixed summary/description
annotations. The contact point limits each request to one alert, sends only
firing notifications, and uses the Grafana webhook integration's default
certificate verification; it does not disable TLS verification.

The webhook payload is the Grafana-managed webhook format. Its application-
supplied labels and annotations are static metadata; the query is aggregated so
per-request or per-game metric labels are not forwarded. No username, game or
player identifier, board/request content, credential, cookie, session/CSRF
value, raw header, or trace ID is added by this configuration. Grafana may add
its own alert-state and rule metadata.

Grafana's notification template reference describes `Alert.Values` as the
expression values used to evaluate a condition; query/condition rules may use
additional expressions. Accordingly, the issue #19 development receiver
requires `A` to be a positive finite JSON number and accepts other expression
entries only when each has a non-empty bounded name and a finite numeric value.
Additional values cannot replace `A` or relax the receiver's expected firing
status, alert name, labels, single-alert, fingerprint, authentication, or replay
checks. Error/no-data statuses and malformed or non-numeric expression values
are rejected. This is based on Grafana's published payload documentation, not
on a captured live notification payload; no live delivery is claimed.

- [Grafana notification template reference](https://grafana.com/docs/grafana/latest/alerting/configure-notifications/template-notifications/reference/#alert)
- [Grafana alert queries and conditions](https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rules/queries-conditions/)

## Owner-operated setup

No live Grafana or webhook configuration is included here. When the owner
chooses to apply this configuration, supply the existing Grafana Cloud stack
URL and a narrowly scoped Grafana API token through the provider's
`GRAFANA_URL` and `GRAFANA_AUTH` environment variables. Also supply the actual
Prometheus data-source UID and private HTTPS endpoint/token through
`TF_VAR_prometheus_datasource_uid`, `TF_VAR_webhook_url`, and
`TF_VAR_webhook_bearer_token`. The endpoint must be HTTPS, must not contain URL
user-info or a fragment, and both endpoint and token are marked sensitive.
Configuration validation errors use generic messages rather than echoing their
values.

Grafana Cloud does not support Grafana's local file-provisioning mechanism for
alert resources; this configuration uses Grafana's Terraform provider and
Grafana-managed alerting API. The provider needs a Grafana Cloud API token and
the Grafana-managed notification-settings capability supported by the target
stack. Before any owner-operated apply, use a protected state backend: Terraform
state can contain contact-point secrets even when inputs are marked sensitive.
Never commit state, plans, credentials, or `.tfvars` files. Do not apply against
an unverified target stack.

The local developer tests validate the rule contract and exercise a
Grafana-compatible, metadata-only notification against a disposable HTTPS
mock. They do not authenticate to Grafana Cloud, validate/apply the Terraform
provider configuration, or prove remote delivery. Grafana Cloud and Render
configuration/delivery remain **NOT VERIFIED** until separately configured
and evidenced by the owner.
