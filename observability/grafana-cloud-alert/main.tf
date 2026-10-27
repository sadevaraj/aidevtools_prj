locals {
  alert_contract = jsondecode(file("${path.module}/alert-contract.json"))
}

resource "grafana_folder" "sudoku_operations" {
  title = "Simple Sudoku Operations"
}

resource "grafana_contact_point" "save_failures" {
  name = "Simple Sudoku save failures (HTTPS webhook)"

  webhook {
    url                        = var.webhook_url
    authorization_scheme       = "Bearer"
    authorization_credentials = var.webhook_bearer_token
    http_method                = "POST"
    max_alerts                 = 1
    disable_resolve_message    = true
    title                      = "Simple Sudoku save HTTP 5xx"
    message                    = "At least one manual save returned HTTP 5xx in the rolling five-minute window."
  }
}

resource "grafana_rule_group" "save_failures" {
  name             = "sudoku-save-failure"
  folder_uid       = grafana_folder.sudoku_operations.uid
  interval_seconds = 30

  rule {
    uid           = "sudoku-save-http-5xx"
    name          = "Sudoku save HTTP 5xx"
    condition       = "A"
    for             = "0s"
    no_data_state   = "OK"
    exec_err_state  = "Error"
    is_paused       = false
    labels          = local.alert_contract.labels
    annotations     = local.alert_contract.annotations

    notification_settings {
      contact_point = grafana_contact_point.save_failures.name
    }

    data {
      ref_id         = "A"
      query_type     = ""
      datasource_uid = var.prometheus_datasource_uid

      relative_time_range {
        from = 300
        to   = 0
      }

      model = jsonencode({
        datasource = {
          type = "prometheus"
          uid  = var.prometheus_datasource_uid
        }
        editorMode    = "code"
        expr          = local.alert_contract.expression
        instant       = true
        intervalMs    = 1000
        legendFormat  = "__auto"
        maxDataPoints = 43200
        range         = false
        refId         = "A"
      })
    }
  }
}
