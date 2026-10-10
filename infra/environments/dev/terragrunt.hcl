include "root" {
  path = find_in_parent_folders("root.hcl")
}

inputs = {
  environment          = "dev"
  log_retention_days   = 7
  reserved_concurrency = 1
}
