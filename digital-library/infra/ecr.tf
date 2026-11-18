# Terraform owns registry creation; publishing images is a separate build step.
resource "aws_ecr_repository" "service" {
  for_each             = toset(["member", "catalog", "reservation", "notification", "fine", "lending", "availability", "frontend"])
  name                 = "${local.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration {
    scan_on_push = true
  }
}
