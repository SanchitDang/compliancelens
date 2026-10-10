variable "endpoint" {
  type = string
  validation {
    condition     = can(regex("^http://(localhost|127\\.0\\.0\\.1|floci):[0-9]+/?$", var.endpoint))
    error_message = "Infrastructure must use the local Floci HTTP endpoint."
  }
}
variable "region" { type = string }
variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "Environment must be dev or prod."
  }
}
variable "database_user" { type = string }
variable "database_name" { type = string }
variable "database_password" {
  type      = string
  sensitive = true
  ephemeral = true
}
variable "log_retention_days" { type = number }
variable "reserved_concurrency" { type = number }
