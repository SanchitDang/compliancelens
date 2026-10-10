resource "aws_cloudwatch_log_group" "functions" {
  for_each          = local.names.functions
  name              = "/aws/lambda/${each.value}"
  retention_in_days = var.log_retention_days
}
resource "aws_iam_role" "functions" {
  for_each = local.names.roles
  name     = each.value
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}
resource "aws_iam_role_policy" "functions" {
  for_each = local.names.policies
  name     = each.value
  role     = aws_iam_role.functions[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.functions[each.key].arn}:*" }
      ], each.key == "parse" ? [
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.artifacts["raw"].arn}/*" },
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.artifacts["intermediate"].arn}/*" }
      ] : each.key == "chunk" ? [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.artifacts["intermediate"].arn}/*" }
      ] : each.key == "embed" ? [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.artifacts["intermediate"].arn}/runs/*" }
      ] : [
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.artifacts["intermediate"].arn}/runs/*/query/report.json" }
    ])
  })
}
resource "aws_lambda_function" "stages" {
  for_each      = local.names.functions
  function_name = each.value
  role          = aws_iam_role.functions[each.key].arn
  lifecycle { create_before_destroy = false }
  package_type = "Image"
  image_uri    = var.image_uri
  image_config {
    command = ["compliancelens.handlers.${each.key}_handler"]
  }
  environment {
    variables = {
      AWS_ENDPOINT_URL    = replace(replace(var.endpoint, "127.0.0.1", "floci"), "localhost", "floci")
      DATABASE_HOST       = "floci"
      DATABASE_PORT       = tostring(aws_db_instance.vectors.port)
      DATABASE_USER       = var.database_user
      DATABASE_NAME       = var.database_name
      RAW_BUCKET          = aws_s3_bucket.artifacts["raw"].id
      INTERMEDIATE_BUCKET = aws_s3_bucket.artifacts["intermediate"].id
    }
  }
  architectures                  = ["arm64"]
  timeout                        = 120
  memory_size                    = 512
  reserved_concurrent_executions = var.reserved_concurrency
  depends_on                     = [aws_iam_role_policy.functions, aws_cloudwatch_log_group.functions]
}

resource "aws_iam_role" "authorization_probe" {
  name = local.names.authorization_role
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { AWS = data.aws_caller_identity.local.arn } }]
  })
}
resource "aws_iam_role_policy" "authorization_probe" {
  name   = local.names.authorization_policy
  role   = aws_iam_role.authorization_probe.id
  policy = aws_iam_role_policy.functions["parse"].policy
}
