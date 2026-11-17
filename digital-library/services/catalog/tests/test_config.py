"""AWS wiring tests replace SDK factories; they never use real AWS credentials."""
from unittest.mock import Mock

import pytest

from app.config import aws_mode
from app.covers import CoverStorage
from app.database import configured_resource


@pytest.fixture
def aws_environment(monkeypatch):
    for key in ("DYNAMODB_ENDPOINT_URL", "S3_ENDPOINT_URL", "S3_PUBLIC_ENDPOINT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "aws")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    monkeypatch.setenv("COVERS_BUCKET", "example-covers")


def test_aws_factories_use_workload_credentials(aws_environment, monkeypatch):
    resource = Mock()
    client = Mock()
    monkeypatch.setattr("boto3.resource", resource)
    monkeypatch.setattr("boto3.client", client)
    assert configured_resource() is resource.return_value
    storage = CoverStorage()
    assert storage.client is storage.signer is client.return_value
    assert storage.bucket == "example-covers"
    for factory in (resource, client):
        assert factory.call_args.kwargs["region_name"] == "ap-south-1"
        assert "aws_access_key_id" not in factory.call_args.kwargs
        assert "endpoint_url" not in factory.call_args.kwargs


def test_reject_mixed_cloud_emulator_settings(aws_environment, monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://minio:9000")
    with pytest.raises(ValueError, match="Remove emulator"):
        aws_mode()


def test_require_cloud_region(aws_environment, monkeypatch):
    monkeypatch.delenv("AWS_REGION")
    with pytest.raises(ValueError, match="AWS_REGION"):
        configured_resource()


def test_require_cloud_bucket(aws_environment, monkeypatch):
    monkeypatch.delenv("COVERS_BUCKET")
    with pytest.raises(ValueError, match="COVERS_BUCKET"):
        CoverStorage()


def test_invalid_mode(monkeypatch):
    monkeypatch.setenv("APP_ENV", "typo")
    with pytest.raises(ValueError, match="APP_ENV"):
        aws_mode()
