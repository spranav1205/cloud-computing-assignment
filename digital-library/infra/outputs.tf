output "network" {
  value = {
    vpc_id              = aws_vpc.library.id
    public_subnet_ids   = [for subnet in aws_subnet.public : subnet.id]
    private_subnet_ids  = [for subnet in aws_subnet.private : subnet.id]
    database_subnet_ids = [for subnet in aws_subnet.database : subnet.id]
  }
}

output "eks" {
  value = {
    cluster_name              = aws_eks_cluster.library.name
    endpoint                  = aws_eks_cluster.library.endpoint
    certificate_authority     = aws_eks_cluster.library.certificate_authority[0].data
    cluster_security_group_id = aws_eks_cluster.library.vpc_config[0].cluster_security_group_id
    oidc_provider_arn         = aws_iam_openid_connect_provider.eks.arn
  }
}

output "member_database" {
  value = {
    address           = aws_db_instance.member.address
    port              = aws_db_instance.member.port
    database_name     = aws_db_instance.member.db_name
    master_secret_arn = aws_db_instance.member.master_user_secret[0].secret_arn
  }
  description = "Connection metadata only. Bootstrap a restricted application user separately; never use the master user in the API."
}

output "catalog" {
  value = {
    books_table_name  = aws_dynamodb_table.books.name
    copies_table_name = aws_dynamodb_table.copies.name
    copies_index_name = "book_id-index"
    bucket_name       = aws_s3_bucket.covers.bucket
    role_arn          = aws_iam_role.catalog.arn
    namespace         = "library"
    service_account   = "catalog"
  }
}
