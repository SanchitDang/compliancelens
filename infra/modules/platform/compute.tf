data "archive_file" "scaffold" {
  type        = "zip"
  source_file = "${path.module}/scaffold_handler.py"
  output_path = "${path.module}/scaffold.zip"
}
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
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.artifacts["intermediate"].arn}/*" }
    ] : [])
  })
}
resource "aws_lambda_function" "stages" {
  for_each                       = local.names.functions
  function_name                  = each.value
  role                           = aws_iam_role.functions[each.key].arn
  filename                       = data.archive_file.scaffold.output_path
  source_code_hash               = data.archive_file.scaffold.output_base64sha256
  handler                        = "scaffold_handler.handler"
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  timeout                        = 120
  memory_size                    = 256
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
