terraform_binary = "terraform"

terraform {
  source = "${get_repo_root()}/infra/modules//platform"
}

locals {
  settings = jsondecode(run_cmd("--terragrunt-quiet", "${get_repo_root()}/.venv/bin/python", "${get_repo_root()}/infra/settings.py"))
}

inputs = local.settings

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
