resource "aws_security_group" "postgres" {
  name        = "${local.name}-postgres"
  description = "PostgreSQL only from EKS node/control-plane security group"
  vpc_id      = aws_vpc.library.id
}

resource "aws_vpc_security_group_ingress_rule" "postgres" {
  security_group_id            = aws_security_group.postgres.id
  referenced_security_group_id = aws_eks_cluster.library.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_db_subnet_group" "member" {
  name       = "${local.name}-member"
  subnet_ids = [for subnet in aws_subnet.database : subnet.id]
}

resource "aws_db_instance" "member" {
  identifier                  = "${local.name}-member"
  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = var.db_instance_class
  allocated_storage           = 20
  storage_type                = "gp3"
  storage_encrypted           = true
  db_name                     = "library"
  username                    = "library_admin"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.member.name
  vpc_security_group_ids      = [aws_security_group.postgres.id]
  publicly_accessible         = false
  multi_az                    = false
  backup_retention_period     = 1
  deletion_protection         = var.protect_data
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${local.name}-member-final"
  auto_minor_version_upgrade  = true
}

resource "aws_dynamodb_table" "books" {
  name                        = "${local.name}-Books"
  billing_mode                = "PROVISIONED"
  read_capacity               = 5
  write_capacity              = 5
  hash_key                    = "book_id"
  deletion_protection_enabled = var.protect_data
  attribute {
    name = "book_id"
    type = "S"
  }
  server_side_encryption {
    enabled = true
  }
}

resource "aws_dynamodb_table" "copies" {
  name                        = "${local.name}-Copies"
  billing_mode                = "PROVISIONED"
  read_capacity               = 5
  write_capacity              = 5
  hash_key                    = "copy_id"
  deletion_protection_enabled = var.protect_data
  attribute {
    name = "copy_id"
    type = "S"
  }
  attribute {
    name = "book_id"
    type = "S"
  }
  global_secondary_index {
    name            = "book_id-index"
    projection_type = "ALL"
    read_capacity   = 5
    write_capacity  = 5
    key_schema {
      attribute_name = "book_id"
      key_type       = "HASH"
    }
  }
  server_side_encryption {
    enabled = true
  }
}

resource "aws_s3_bucket" "covers" {
  bucket        = var.cover_bucket_name
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "covers" {
  bucket                  = aws_s3_bucket.covers.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "covers" {
  bucket = aws_s3_bucket.covers.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "covers" {
  bucket = aws_s3_bucket.covers.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "covers" {
  bucket = aws_s3_bucket.covers.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "RequireTLS", Effect = "Deny", Principal = "*", Action = "s3:*"
      Resource  = [aws_s3_bucket.covers.arn, "${aws_s3_bucket.covers.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}
