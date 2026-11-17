resource "aws_iam_openid_connect_provider" "eks" {
  url            = aws_eks_cluster.library.identity[0].oidc[0].issuer
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "catalog" {
  name = "${local.name}-catalog"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = aws_iam_openid_connect_provider.eks.arn }
      Condition = { StringEquals = {
        "${trimprefix(aws_iam_openid_connect_provider.eks.url, "https://")}:aud" = "sts.amazonaws.com"
        "${trimprefix(aws_iam_openid_connect_provider.eks.url, "https://")}:sub" = "system:serviceaccount:library:catalog"
      } }
    }]
  })
}

resource "aws_iam_role_policy" "catalog" {
  name = "catalog-storage"
  role = aws_iam_role.catalog.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Scan", "dynamodb:DescribeTable"]
        Resource = aws_dynamodb_table.books.arn
      },
      {
        Effect   = "Allow", Action = ["dynamodb:PutItem", "dynamodb:DescribeTable"]
        Resource = aws_dynamodb_table.copies.arn
      },
      {
        Effect   = "Allow", Action = ["dynamodb:Query"]
        Resource = "${aws_dynamodb_table.copies.arn}/index/book_id-index"
      },
      {
        Effect   = "Allow", Action = ["s3:ListBucket"]
        Resource = aws_s3_bucket.covers.arn
      },
      {
        Effect   = "Allow", Action = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.covers.arn}/covers/*"
      }
    ]
  })
}
