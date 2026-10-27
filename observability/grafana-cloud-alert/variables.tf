variable "prometheus_datasource_uid" {
  description = "UID of the Grafana Cloud Prometheus data source that receives the Sudoku save metric."
  type        = string
  nullable    = false

  validation {
    condition     = length(trimspace(var.prometheus_datasource_uid)) > 0
    error_message = "prometheus_datasource_uid must be a non-empty data-source UID."
  }
}

variable "webhook_url" {
  description = "Owner-managed HTTPS webhook URL. Keep it private; it may itself contain a secret."
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition = (
      length(var.webhook_url) <= 2048 &&
      can(regex("^https://[^/@\\s]+([/?#]|$)", var.webhook_url)) &&
      !strcontains(var.webhook_url, "#")
    )
    error_message = "webhook_url must be an HTTPS URL without user-info or a fragment."
  }
}

variable "webhook_bearer_token" {
  description = "Owner-managed webhook bearer token. Supply it privately through TF_VAR_webhook_bearer_token."
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = length(trimspace(var.webhook_bearer_token)) > 0
    error_message = "webhook_bearer_token must be non-empty."
  }
}
