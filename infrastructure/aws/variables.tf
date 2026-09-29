variable "project_name" {
  description = "Short name used for AWS resource names."
  type        = string
  default     = "inventory-event-platform"
}

variable "aws_region" {
  description = "AWS region for the serverless reference deployment."
  type        = string
  default     = "eu-west-2"
}

variable "restore_schedule_expression" {
  description = "How often the restore worker checks due temporary moves."
  type        = string
  default     = "rate(5 minutes)"
}
