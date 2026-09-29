data "archive_file" "command" {
  type        = "zip"
  source_file = "${path.module}/lambda/command_handler.py"
  output_path = "${path.module}/command_handler.zip"
}

data "archive_file" "archive" {
  type        = "zip"
  source_file = "${path.module}/lambda/archive_handler.py"
  output_path = "${path.module}/archive_handler.zip"
}

data "archive_file" "restore" {
  type        = "zip"
  source_file = "${path.module}/lambda/restore_handler.py"
  output_path = "${path.module}/restore_handler.zip"
}

resource "aws_lambda_function" "command" {
  function_name    = "${var.project_name}-command"
  role             = aws_iam_role.command_lambda.arn
  runtime          = "python3.12"
  handler          = "command_handler.handler"
  filename         = data.archive_file.command.output_path
  source_code_hash = data.archive_file.command.output_base64sha256
  timeout          = 15

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.inventory.name
    }
  }
}

resource "aws_lambda_function" "archive" {
  function_name    = "${var.project_name}-archive"
  role             = aws_iam_role.archive_lambda.arn
  runtime          = "python3.12"
  handler          = "archive_handler.handler"
  filename         = data.archive_file.archive.output_path
  source_code_hash = data.archive_file.archive.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      ARCHIVE_BUCKET = aws_s3_bucket.event_archive.bucket
    }
  }
}

resource "aws_lambda_function" "restore" {
  function_name    = "${var.project_name}-restore"
  role             = aws_iam_role.restore_lambda.arn
  runtime          = "python3.12"
  handler          = "restore_handler.handler"
  filename         = data.archive_file.restore.output_path
  source_code_hash = data.archive_file.restore.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.inventory.name
    }
  }
}

resource "aws_lambda_event_source_mapping" "archive_stream" {
  event_source_arn  = aws_dynamodb_table.inventory.stream_arn
  function_name     = aws_lambda_function.archive.arn
  starting_position = "LATEST"
  batch_size        = 100
}

resource "aws_cloudwatch_log_group" "command" {
  name              = "/aws/lambda/${aws_lambda_function.command.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "archive" {
  name              = "/aws/lambda/${aws_lambda_function.archive.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "restore" {
  name              = "/aws/lambda/${aws_lambda_function.restore.function_name}"
  retention_in_days = 14
}
