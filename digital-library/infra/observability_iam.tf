resource "aws_iam_role" "fluent_bit" {
  name = "${local.name}-fluent-bit"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = aws_iam_openid_connect_provider.eks.arn }
      Condition = {
        StringEquals = {
          "${trimprefix(aws_iam_openid_connect_provider.eks.url, "https://")}:aud" = "sts.amazonaws.com"
          "${trimprefix(aws_iam_openid_connect_provider.eks.url, "https://")}:sub" = "system:serviceaccount:library:fluent-bit"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "fluent_bit" {
  name = "cloudwatch-log-writer"
  role = aws_iam_role.fluent_bit.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:DescribeLogGroups", "logs:DescribeLogStreams", "logs:PutLogEvents"]
      Resource = "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/digital-library/*"
    }]
  })
}
