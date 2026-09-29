output "api_endpoint" {
  value = aws_apigatewayv2_api.inventory.api_endpoint
}

output "dynamodb_table" {
  value = aws_dynamodb_table.inventory.name
}

output "event_archive_bucket" {
  value = aws_s3_bucket.event_archive.bucket
}
