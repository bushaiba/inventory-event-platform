resource "aws_iam_role" "scheduler" {
  name_prefix = "${var.project_name}-scheduler-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "lambda:InvokeFunction"
      Resource = aws_lambda_function.restore.arn
    }]
  })
}

resource "aws_scheduler_schedule" "restore_worker" {
  name                = "${var.project_name}-restore-worker"
  schedule_expression = var.restore_schedule_expression

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.restore.arn
    role_arn = aws_iam_role.scheduler.arn
  }
}
