"""Cloud configuration is explicit; local mode never uses AWS credentials."""
import os


def aws_mode() -> bool:
    mode = os.environ.get("APP_ENV", "local")
    if mode not in {"local", "aws"}:
        raise ValueError("APP_ENV must be local or aws")
    if mode == "aws" and any(os.environ.get(key) for key in (
        "DYNAMODB_ENDPOINT_URL", "S3_ENDPOINT_URL", "S3_PUBLIC_ENDPOINT_URL"
    )):
        raise ValueError("Remove emulator endpoint settings in AWS mode")
    return mode == "aws"


def aws_region() -> str:
    region = os.environ.get("AWS_REGION")
    if not region:
        raise ValueError("AWS_REGION is required in AWS mode")
    return region
