terraform {
  required_providers {
    aws = {
      version = ">= 3.20.0"
      source  = "hashicorp/aws"
    }
  }
}

# data "aws_caller_identity" "current" {}

# SNS -> SQS -> Lambda -> SNS -> PagerDuty -> Slack

provider "aws" {
  region  = "eu-west-1"
  profile = "prod"
}

resource "aws_sqs_queue" "enriched_alerts_queue" {
  name                       = "anya-test-enriched-alerts-queue"
  visibility_timeout_seconds = 300
}

resource "aws_sqs_queue_redrive_policy" "enriched_alerts_dl_policy" {
  queue_url = aws_sqs_queue.enriched_alerts_queue.id
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.enriched_alerts_dl_queue.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue" "enriched_alerts_dl_queue" {
  name = "anya-test-enriched-alerts-queue-dead-letter"
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue",
    sourceQueueArns   = [aws_sqs_queue.enriched_alerts_queue.arn]
  })
}

resource "aws_sns_topic_subscription" "test_alerts_sqs_target" {
  topic_arn = "arn:aws:sns:eu-west-1:707186164241:cloudwatch-to-pagerduty-prod"
  protocol  = "sqs"
  endpoint  = "${aws_sqs_queue.enriched_alerts_queue.arn}"
}

resource "aws_sqs_queue_policy" "enriched_alerts_queue_policy" {
  queue_url = aws_sqs_queue.enriched_alerts_queue.id

  policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "sns.amazonaws.com"
      },
      "Action": [
        "sqs:SendMessage"
      ],
      "Resource": [
        "${aws_sqs_queue.enriched_alerts_queue.arn}"
      ],
      "Condition": {
        "ArnEquals": {
          "aws:SourceArn": "arn:aws:sns:eu-west-1:707186164241:cloudwatch-to-pagerduty-prod"
        }
      }
    }
  ]
}
POLICY
}

resource "aws_lambda_function" "results_updates_lambda" {
  filename         = "${path.module}/../enriched_alerts.zip"
  function_name    = "enriched_alerts_lambda"
  role             = aws_iam_role.lambda_role.arn
  handler          = "main.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60
}

resource "aws_iam_role" "lambda_role" {
  name               = "anya-test-lambda-role"
  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
        "Action": "sts:AssumeRole",
        "Effect": "Allow",
        "Principal": {
            "Service": "lambda.amazonaws.com"
        }
    }
  ]
}
EOF
}

resource "aws_iam_role_policy" "lambda_role_sqs_policy" {
  name   = "AllowSQSPermissions"
  role   = aws_iam_role.lambda_role.id
  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": [
        "sqs:ChangeMessageVisibility",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ReceiveMessage"
      ],
      "Effect": "Allow",
      "Resource": "*"
    }
  ]
}
EOF
}

resource "aws_iam_role_policy" "lambda_role_cloudwatch_policy" {
  name   = "AllowToReadFromCloudwatch"
  role   = aws_iam_role.lambda_role.id
  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": [
        "cloudwatch:DescribeAlarmsForMetric",
        "cloudwatch:DescribeAlarmHistory",
        "cloudwatch:DescribeAlarms",
        "cloudwatch:ListMetrics",
        "cloudwatch:GetMetricData",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:GetInsightRuleReport"
      ],
      "Effect": "Allow",
      "Resource": "*"
    }
  ]
}
EOF
}

resource "aws_iam_role_policy" "lambda_role_logs_policy" {
  name   = "AllowToWriteAndReadLogs"
  role   = aws_iam_role.lambda_role.id
  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:GetLogGroupFields",
        "logs:StartQuery",
        "logs:StopQuery",
        "logs:GetQueryResults",
        "logs:GetLogEvents"
      ],
      "Effect": "Allow",
      "Resource": "*"
    }
  ]
}
EOF
}

module "enriched_alerts" {
  source          = "git::ssh://git@gitlab.com/altruistiq/terrablocks.git//blocks/lambda-s3-event?ref=v1.66.0"
  s3_bucket       = var.source_code_bucket
  name            = "enriched_alerts"
  s3_key          = "enriched_alerts.zip"
  handler_name    = "main.handler"
  bucket_id       = var.application_file_store_bucket_id
  lambda_runtime  = "python3.10"
  filter_suffix   = ".pdf"
  environment     = local.environment
}