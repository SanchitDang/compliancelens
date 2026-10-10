resource "aws_iam_role" "workflow" {
  name = local.names.workflow_role
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "states.amazonaws.com" } }]
  })
}
resource "aws_iam_role_policy" "workflow" {
  name = local.names.workflow_policy
  role = aws_iam_role.workflow.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [for stage in ["parse", "chunk", "embed"] : aws_lambda_function.stages[stage].arn] }]
  })
}
resource "aws_sfn_state_machine" "ingestion" {
  name     = local.names.workflow
  role_arn = aws_iam_role.workflow.arn
  definition = jsonencode({
    StartAt = "Parse"
    States = {
      Parse = { Type = "Task", Resource = aws_lambda_function.stages["parse"].arn, TimeoutSeconds = 120, Next = "Chunk" }
      Chunk = { Type = "Task", Resource = aws_lambda_function.stages["chunk"].arn, TimeoutSeconds = 120, Next = "Embed" }
      Embed = { Type = "Task", Resource = aws_lambda_function.stages["embed"].arn, TimeoutSeconds = 120, End = true }
    }
  })
  depends_on = [aws_iam_role_policy.workflow]
}
