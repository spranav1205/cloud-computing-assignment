# The AWS provider is mocked in EVERY run. These tests never contact AWS.
mock_provider "aws" {}

variables {
  aws_account_id              = "111111111111"
  cluster_admin_principal_arn = "arn:aws:iam::111111111111:role/offline-test-admin"
  kubernetes_version          = "1.35"
  eks_public_access_cidrs     = ["203.0.113.10/32"]
  cover_bucket_name           = "offline-example-library-covers"
  ses_sender                  = "test@example.com"
}

run "private_storage_and_cluster" {
  command = plan

  assert {
    condition     = !aws_db_instance.member.publicly_accessible && aws_db_instance.member.storage_encrypted && aws_db_instance.member.manage_master_user_password
    error_message = "Member database must be private, encrypted, and use an RDS-managed password."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.postgres.from_port == 5432 && aws_vpc_security_group_ingress_rule.postgres.to_port == 5432 && aws_vpc_security_group_ingress_rule.postgres.cidr_ipv4 == null
    error_message = "PostgreSQL ingress must use its EKS source security group, not an IP range."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.covers.block_public_acls && aws_s3_bucket_public_access_block.covers.block_public_policy && aws_s3_bucket_public_access_block.covers.ignore_public_acls && aws_s3_bucket_public_access_block.covers.restrict_public_buckets && !aws_s3_bucket.covers.force_destroy
    error_message = "Covers must block all public access and must not automatically delete objects on teardown."
  }
  assert {
    condition     = aws_eks_cluster.library.vpc_config[0].endpoint_private_access && aws_launch_template.nodes.metadata_options[0].http_tokens == "required" && aws_launch_template.nodes.metadata_options[0].http_put_response_hop_limit == 1
    error_message = "Nodes need private API access and IMDSv2 with restricted container metadata access."
  }
  assert {
    condition     = aws_db_instance.member.deletion_protection && aws_dynamodb_table.books.deletion_protection_enabled && aws_dynamodb_table.copies.deletion_protection_enabled
    error_message = "Data deletion protection must be enabled by default."
  }
  assert {
    condition     = length(aws_subnet.public) == 2 && length(aws_subnet.private) == 2 && length(aws_subnet.database) == 2
    error_message = "Separate public, worker, and database subnets are required in two AZs."
  }
  assert {
    condition     = aws_eks_node_group.library.scaling_config[0].max_size == 1 && aws_launch_template.nodes.credit_specification[0].cpu_credits == "standard" && aws_dynamodb_table.books.read_capacity == 5 && aws_dynamodb_table.books.write_capacity == 5 && aws_dynamodb_table.copies.read_capacity == 5 && aws_dynamodb_table.copies.write_capacity == 5
    error_message = "Trial sizing must retain one worker, standard CPU credits, and small provisioned tables."
  }
}

run "reject_public_cluster_access" {
  command = plan
  variables {
    eks_public_access_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.eks_public_access_cidrs]
}

run "reject_wrong_administrator_account" {
  command = plan
  variables {
    cluster_admin_principal_arn = "arn:aws:iam::222222222222:role/other-account"
  }
  expect_failures = [var.cluster_admin_principal_arn]
}

run "accept_administrator_user" {
  command = plan
  variables {
    cluster_admin_principal_arn = "arn:aws:iam::111111111111:user/library-deployer"
  }
  assert {
    condition     = aws_eks_access_entry.administrator.principal_arn == "arn:aws:iam::111111111111:user/library-deployer"
    error_message = "The IAM deployment user must be usable as the EKS administrator."
  }
}

run "reject_root_access_entry" {
  command = plan
  variables {
    cluster_admin_principal_arn = "arn:aws:iam::111111111111:root"
  }
  expect_failures = [var.cluster_admin_principal_arn]
}
