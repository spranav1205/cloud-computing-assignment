data "archive_file" "notification_lambda" {
  type        = "zip"
  source_file = "${path.module}/../services/notification-lambda/handler.py"
  output_path = "${path.module}/.local/notification-lambda.zip"
}

resource "aws_sqs_queue" "notification_dlq" {
  name                      = "${local.name}-notification-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "notification" {
  name                       = "${local.name}-notification"
  visibility_timeout_seconds = 180
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.notification_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_iam_role" "notification_lambda" {
  name = "${local.name}-notification-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "notification_lambda" {
  name = "notification-delivery"
  role = aws_iam_role.notification_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = aws_sqs_queue.notification.arn
      },
      {
        Effect   = "Allow"
        Action   = ["ses:SendEmail", "ses:SendRawEmail"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = aws_dynamodb_table.notification_dedupe.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "notification" {
  function_name    = "${local.name}-notification"
  role             = aws_iam_role.notification_lambda.arn
  filename         = data.archive_file.notification_lambda.output_path
  source_code_hash = data.archive_file.notification_lambda.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 30
  memory_size      = 256
  environment {
    variables = {
      SES_SENDER                = var.ses_sender
      NOTIFICATION_DEDUPE_TABLE = aws_dynamodb_table.notification_dedupe.name
    }
  }
}

resource "aws_lambda_event_source_mapping" "notification" {
  event_source_arn        = aws_sqs_queue.notification.arn
  function_name           = aws_lambda_function.notification.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
  enabled                 = true
}
