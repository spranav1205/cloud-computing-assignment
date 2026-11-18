resource "aws_security_group" "streaming" {
  name        = "${local.name}-streaming"
  description = "Private Kafka and EMR traffic for analytics"
  vpc_id      = aws_vpc.library.id
}

resource "aws_vpc_security_group_ingress_rule" "streaming_internal" {
  security_group_id            = aws_eks_cluster.library.vpc_config[0].cluster_security_group_id
  referenced_security_group_id = aws_security_group.streaming.id
  ip_protocol                  = "tcp"
  from_port                    = 30094
  to_port                      = 30094
}

# EMR's private-subnet service-access group must be separate from its node group.
resource "aws_security_group" "emr_service_access" {
  name        = "${local.name}-emr-service-access"
  description = "Dedicated private-subnet EMR service access"
  vpc_id      = aws_vpc.library.id
}

resource "aws_vpc_security_group_egress_rule" "streaming" {
  security_group_id = aws_security_group.streaming.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_egress_rule" "emr_service_access" {
  security_group_id = aws_security_group.emr_service_access.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_ingress_rule" "emr_internal" {
  security_group_id            = aws_security_group.streaming.id
  referenced_security_group_id = aws_security_group.streaming.id
  ip_protocol                  = "-1"
}

resource "aws_vpc_security_group_ingress_rule" "emr_control" {
  security_group_id            = aws_security_group.streaming.id
  referenced_security_group_id = aws_security_group.emr_service_access.id
  ip_protocol                  = "tcp"
  from_port                    = 8443
  to_port                      = 8443
}

resource "aws_vpc_security_group_ingress_rule" "emr_service_access" {
  security_group_id            = aws_security_group.emr_service_access.id
  referenced_security_group_id = aws_security_group.streaming.id
  ip_protocol                  = "tcp"
  from_port                    = 9443
  to_port                      = 9443
}

resource "aws_iam_role" "emr_service" {
  name = "${local.name}-emr-service"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "elasticmapreduce.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "emr_service" {
  role       = aws_iam_role.emr_service.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonElasticMapReduceRole"
}

resource "aws_iam_role" "emr_ec2" {
  name = "${local.name}-emr-ec2"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "emr_ec2" {
  role       = aws_iam_role.emr_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonElasticMapReduceforEC2Role"
}

resource "aws_iam_role_policy" "emr_s3" {
  name = "analytics-artifacts"
  role = aws_iam_role.emr_ec2.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.covers.arn,
        "${aws_s3_bucket.covers.arn}/emr-logs/*",
        "${aws_s3_bucket.covers.arn}/flink/*"
      ]
    }]
  })
}

resource "aws_emr_cluster" "analytics" {
  name                              = "${local.name}-analytics"
  release_label                     = "emr-7.14.0"
  applications                      = ["Flink"]
  service_role                      = aws_iam_role.emr_service.arn
  log_uri                           = "s3://${aws_s3_bucket.covers.bucket}/emr-logs/"
  keep_job_flow_alive_when_no_steps = true
  termination_protection            = var.protect_data

  ec2_attributes {
    subnet_id                         = aws_subnet.private[var.availability_zones[0]].id
    emr_managed_master_security_group = aws_security_group.streaming.id
    emr_managed_slave_security_group  = aws_security_group.streaming.id
    service_access_security_group     = aws_security_group.emr_service_access.id
    instance_profile                  = aws_iam_instance_profile.emr_ec2.arn
  }

  master_instance_group {
    instance_type  = "m5.xlarge"
    instance_count = 1
  }

  core_instance_group {
    instance_type  = "m5.xlarge"
    instance_count = 1
  }

  configurations_json = jsonencode([{
    Classification = "flink-conf"
    Properties = {
      "execution.checkpointing.interval" = "30 s"
      "state.checkpoints.dir"            = "s3://${aws_s3_bucket.covers.bucket}/flink/checkpoints/"
    }
  }])

  depends_on = [aws_iam_role_policy_attachment.emr_service, aws_iam_role_policy_attachment.emr_ec2, aws_iam_role_policy.emr_s3, aws_route.private_internet, aws_vpc_security_group_egress_rule.streaming, aws_vpc_security_group_egress_rule.emr_service_access, aws_vpc_security_group_ingress_rule.emr_control, aws_vpc_security_group_ingress_rule.emr_service_access]
}

resource "aws_iam_instance_profile" "emr_ec2" {
  name = "${local.name}-emr-ec2"
  role = aws_iam_role.emr_ec2.name
}
