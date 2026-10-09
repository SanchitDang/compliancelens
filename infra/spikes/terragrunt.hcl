terraform_binary = "terraform"

generate "local_state" {
  path      = "backend.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<-EOF
    terraform {
      backend "local" {
        path = "${get_original_terragrunt_dir()}/terraform.tfstate"
      }
    }
  EOF
}

locals {
  settings = jsondecode(run_cmd("--terragrunt-quiet", "../../.venv/bin/python", "-c", "import json; from compliancelens.config import Settings; s = Settings(_env_file='../../.env'); print(json.dumps({'endpoint': s.aws_endpoint_url, 'region': s.aws_default_region}))"))
}

inputs = {
  endpoint = local.settings.endpoint
  region   = local.settings.region
}
