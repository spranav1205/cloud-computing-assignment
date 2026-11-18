# Official controller permissions, pinned to the deployed controller release.
resource "aws_iam_role" "load_balancer_controller" {
  name = "${local.name}-load-balancer-controller"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = aws_iam_openid_connect_provider.eks.arn }
      Condition = { StringEquals = {
        "${trimprefix(aws_iam_openid_connect_provider.eks.url, "https://")}:aud" = "sts.amazonaws.com"
        "${trimprefix(aws_iam_openid_connect_provider.eks.url, "https://")}:sub" = "system:serviceaccount:kube-system:aws-load-balancer-controller"
      } }
    }]
  })
}

resource "aws_iam_role_policy" "load_balancer_controller" {
  name   = "load-balancer-management"
  role   = aws_iam_role.load_balancer_controller.id
  policy = jsonencode(jsondecode(file("${path.module}/policies/aws-load-balancer-controller.json")))
}

output "load_balancer_controller_role_arn" {
  value = aws_iam_role.load_balancer_controller.arn
}
