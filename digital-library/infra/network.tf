resource "aws_vpc" "library" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

resource "aws_internet_gateway" "library" {
  vpc_id = aws_vpc.library.id
}

resource "aws_subnet" "public" {
  for_each          = local.zones
  vpc_id            = aws_vpc.library.id
  availability_zone = each.key
  cidr_block        = cidrsubnet(aws_vpc.library.cidr_block, 8, each.value)
  tags = {
    Name                     = "${local.name}-public-${each.key}"
    "kubernetes.io/role/elb" = "1"
  }
}

resource "aws_subnet" "private" {
  for_each          = local.zones
  vpc_id            = aws_vpc.library.id
  availability_zone = each.key
  cidr_block        = cidrsubnet(aws_vpc.library.cidr_block, 8, 10 + each.value)
  tags = {
    Name                              = "${local.name}-private-${each.key}"
    "kubernetes.io/role/internal-elb" = "1"
  }
}

resource "aws_subnet" "database" {
  for_each          = local.zones
  vpc_id            = aws_vpc.library.id
  availability_zone = each.key
  cidr_block        = cidrsubnet(aws_vpc.library.cidr_block, 8, 20 + each.value)
  tags              = { Name = "${local.name}-database-${each.key}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.library.id
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.library.id
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  domain = "vpc"
}

# One NAT is a development cost/availability tradeoff; both private AZs share it.
resource "aws_nat_gateway" "library" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[var.availability_zones[0]].id
  depends_on    = [aws_internet_gateway.library]
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.library.id
}

resource "aws_route" "private_internet" {
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.library.id
}

resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

# Database subnets have only the VPC-local route, with no internet/NAT default.
resource "aws_route_table" "database" {
  vpc_id = aws_vpc.library.id
}

resource "aws_route_table_association" "database" {
  for_each       = aws_subnet.database
  subnet_id      = each.value.id
  route_table_id = aws_route_table.database.id
}

resource "aws_vpc_endpoint" "storage" {
  for_each          = toset(["s3", "dynamodb"])
  vpc_id            = aws_vpc.library.id
  service_name      = "com.amazonaws.${var.aws_region}.${each.key}"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
}
