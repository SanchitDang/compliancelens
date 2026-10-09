terraform {
  required_version = ">= 1.6, < 2.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "endpoint" {
  type = string
  validation {
    condition     = can(regex("^http://(localhost|127\\.0\\.0\\.1|floci):[0-9]+/?$", var.endpoint))
    error_message = "Phase 0 requires a local Floci endpoint."
  }
}

variable "region" {
  type = string
}

provider "aws" {
  region                      = var.region
  access_key                  = "test"
  secret_key                  = "test" # pragma: allowlist secret - Floci dummy credential
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  s3_use_path_style           = true

  endpoints {
    s3 = var.endpoint
  }
}

locals {
  raw_bucket      = "compliancelens-dev-spike-raw"
  sdk_bucket      = "compliancelens-dev-spike-sdk"
  database        = "compliancelens-dev-spike-db"
  lambda_function = "compliancelens-dev-spike-query"
  lambda_role     = "compliancelens-dev-spike-lambda"
}

resource "aws_s3_bucket" "raw" {
  bucket = local.raw_bucket
}

output "names" {
  value = {
    raw_bucket      = local.raw_bucket
    sdk_bucket      = local.sdk_bucket
    database        = local.database
    lambda_function = local.lambda_function
    lambda_role     = local.lambda_role
  }
}

output "raw_bucket" {
  value = aws_s3_bucket.raw.id
}
