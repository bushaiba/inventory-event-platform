resource "aws_apigatewayv2_api" "inventory" {
  name          = var.project_name
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "command" {
  api_id                 = aws_apigatewayv2_api.inventory.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.command.invoke_arn
  payload_format_version = "2.0"
}

locals {
  routes = toset([
    "GET /health",
    "GET /containers/{container_id}",
    "GET /containers/{container_id}/events",
    "GET /inventory/lookup/{sku}",
    "POST /commands/create",
    "POST /commands/move",
    "POST /commands/adjust",
    "POST /commands/close"
  ])
}

resource "aws_apigatewayv2_route" "routes" {
  for_each = local.routes

  api_id    = aws_apigatewayv2_api.inventory.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.command.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.inventory.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.command.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.inventory.execution_arn}/*/*"
}
