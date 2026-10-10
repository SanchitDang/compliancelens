include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  environment          = "prod"
  log_retention_days   = 30
  reserved_concurrency = 2
}
