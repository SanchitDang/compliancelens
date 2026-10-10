resource "aws_db_instance" "vectors" {
  identifier          = local.names.database
  engine              = "postgres"
  instance_class      = "db.t3.micro"
  allocated_storage   = 5
  db_name             = var.database_name
  username            = var.database_user
  password_wo         = var.database_password
  password_wo_version = 1
  skip_final_snapshot = true
  apply_immediately   = true
  publicly_accessible = false
  lifecycle { prevent_destroy = true }
}
