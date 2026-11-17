"""Direct uploads to local private MinIO; no staging or image proxy."""

import os
from urllib.parse import urlparse
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import HTTPException
from app.config import aws_mode, aws_region

MAX_COVER_BYTES = 5_000_000
URL_SECONDS = 300
MEDIA_TYPES = {"image/jpeg": "jpg", "image/png": "png"}


def local_s3(endpoint: str | None = None):
    endpoint = endpoint or os.environ.get("S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "minio"}:
        raise ValueError("Only local MinIO HTTP endpoints are permitted")
    return boto3.client(
        "s3", endpoint_url=endpoint, region_name="us-east-1",
        aws_access_key_id="local-library", aws_secret_access_key="local-library-password",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                      connect_timeout=3, read_timeout=3, retries={"max_attempts": 0}),
    )


class CoverStorage:
    def __init__(self):
        if aws_mode():
            self.bucket = os.environ.get("COVERS_BUCKET")
            if not self.bucket:
                raise ValueError("COVERS_BUCKET is required in AWS mode")
            # IRSA supplies temporary credentials through the SDK's default chain.
            self.client = boto3.client("s3", region_name=aws_region(),
                config=Config(signature_version="s3v4", connect_timeout=3, read_timeout=3))
            self.signer = self.client
        else:
            self.client = local_s3()
            # Sign the browser-reachable host directly; changing a signed URL breaks it.
            self.signer = local_s3(os.environ.get("S3_PUBLIC_ENDPOINT_URL") or None)
            self.bucket = "library-covers"

    def ready(self) -> None:
        self.client.head_bucket(Bucket=self.bucket)

    def upload_url(self, book_id: str, content_type: str) -> tuple[str, dict]:
        key = f"covers/{book_id}/{uuid4()}.{MEDIA_TYPES[content_type]}"
        url = self.signer.generate_presigned_url(
            "put_object", Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=URL_SECONDS,
        )
        return key, {"upload_url": url, "method": "PUT", "headers": {"Content-Type": content_type}, "expires_in": URL_SECONDS}

    def verify(self, key: str) -> None:
        try:
            metadata = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                raise HTTPException(404, "Uploaded cover not found") from None
            raise
        if not 1 <= metadata["ContentLength"] <= MAX_COVER_BYTES:
            raise HTTPException(422, "Cover must be between 1 byte and 5 MB")
        if metadata.get("ContentType") not in MEDIA_TYPES:
            raise HTTPException(422, "Cover must declare image/jpeg or image/png")

    def download_url(self, key: str) -> dict:
        return {"url": self.signer.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=URL_SECONDS,
        ), "expires_in": URL_SECONDS}
