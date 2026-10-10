resource "aws_api_gateway_rest_api" "query" { name = local.names.api }
resource "aws_api_gateway_resource" "query" {
  rest_api_id = aws_api_gateway_rest_api.query.id
  parent_id   = aws_api_gateway_rest_api.query.root_resource_id
  path_part   = "query"
}
resource "aws_api_gateway_method" "query" {
  rest_api_id   = aws_api_gateway_rest_api.query.id
  resource_id   = aws_api_gateway_resource.query.id
  http_method   = "POST"
  authorization = "NONE"
}
resource "aws_api_gateway_integration" "query" {
  rest_api_id             = aws_api_gateway_rest_api.query.id
  resource_id             = aws_api_gateway_resource.query.id
  http_method             = aws_api_gateway_method.query.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.stages["query"].invoke_arn
}
resource "aws_lambda_permission" "api" {
  statement_id  = "AllowQueryApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.stages["query"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.query.execution_arn}/${var.environment}/POST/query"
}
resource "aws_api_gateway_deployment" "query" {
  rest_api_id = aws_api_gateway_rest_api.query.id
  triggers    = { configuration = sha1(jsonencode([aws_api_gateway_method.query.id, aws_api_gateway_integration.query.uri])) }
  depends_on  = [aws_api_gateway_integration.query, aws_lambda_permission.api]
  lifecycle { create_before_destroy = false }
}
resource "aws_api_gateway_stage" "query" {
  rest_api_id   = aws_api_gateway_rest_api.query.id
  deployment_id = aws_api_gateway_deployment.query.id
  stage_name    = var.environment
}
