terraform {
  required_version = ">= 1.11, < 2.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
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
    apigateway     = var.endpoint
    cloudwatchlogs = var.endpoint
    ec2            = var.endpoint
    iam            = var.endpoint
    kms            = var.endpoint
    lambda         = var.endpoint
    rds            = var.endpoint
    s3             = var.endpoint
    secretsmanager = var.endpoint
    sfn            = var.endpoint
    sts            = var.endpoint
  }
}

locals {
  prefix = "compliancelens-${var.environment}"
  stages = ["parse", "chunk", "embed", "query"]
  names = {
    raw_bucket           = "${local.prefix}-raw"
    intermediate_bucket  = "${local.prefix}-intermediate"
    database             = "${local.prefix}-db"
    functions            = { for stage in local.stages : stage => "${local.prefix}-${stage}" }
    roles                = { for stage in local.stages : stage => "${local.prefix}-${stage}-role" }
    policies             = { for stage in local.stages : stage => "${local.prefix}-${stage}-access" }
    workflow             = "${local.prefix}-ingestion"
    workflow_role        = "${local.prefix}-ingestion-role"
    workflow_policy      = "${local.prefix}-ingestion-invoke"
    authorization_role   = "${local.prefix}-authorization-role"
    authorization_policy = "${local.prefix}-authorization-access"
    image_repository     = "compliancelens-application"
    api                  = "${local.prefix}-api"
  }
}

data "aws_caller_identity" "local" {}
