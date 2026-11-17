"""Local DynamoDB access with explicit dummy credentials and native pagination."""

import os
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config

from app.models import BookCreate


def local_resource():
    endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL", "http://127.0.0.1:8000")
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "dynamodb"}:
        raise ValueError("Only local DynamoDB HTTP endpoints are permitted")
    return boto3.resource(
        "dynamodb", endpoint_url=endpoint, region_name="us-east-1",
        aws_access_key_id="dummy", aws_secret_access_key="dummy",
        config=Config(connect_timeout=3, read_timeout=3, retries={"max_attempts": 0}),
    )


def initialize_tables(resource, books_name: str, copies_name: str) -> None:
    existing = set(resource.meta.client.list_tables()["TableNames"])
    if books_name not in existing:
        resource.create_table(
            TableName=books_name, KeySchema=[{"AttributeName": "book_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "book_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        ).wait_until_exists()
    if copies_name not in existing:
        resource.create_table(
            TableName=copies_name,
            KeySchema=[{"AttributeName": "copy_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": name, "AttributeType": "S"} for name in ("copy_id", "book_id")],
            GlobalSecondaryIndexes=[{
                "IndexName": "book_id-index", "KeySchema": [{"AttributeName": "book_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }], BillingMode="PAY_PER_REQUEST",
        ).wait_until_exists()


class CatalogDatabase:
    def __init__(self, resource, books_name: str, copies_name: str):
        self.books = resource.Table(books_name)
        self.copies = resource.Table(copies_name)

    def ready(self) -> None:
        self.books.meta.client.describe_table(TableName=self.books.name)
        self.copies.meta.client.describe_table(TableName=self.copies.name)

    def create_book(self, data: BookCreate) -> dict:
        book = {**data.model_dump(exclude_none=True), "book_id": str(uuid4()),
                "created_at": datetime.now(timezone.utc).isoformat()}
        self.books.put_item(Item=book, ConditionExpression="attribute_not_exists(book_id)")
        return book

    def get_book(self, book_id: str) -> dict | None:
        return self.books.get_item(Key={"book_id": book_id}, ConsistentRead=True).get("Item")

    def list_books(self, limit: int, key: dict | None) -> dict:
        options = {"Limit": limit}
        if key:
            options["ExclusiveStartKey"] = key
        result = self.books.scan(**options)
        return {"items": result["Items"], "last_evaluated_key": result.get("LastEvaluatedKey")}

    def create_copy(self, book_id: str) -> dict:
        copy = {"copy_id": str(uuid4()), "book_id": book_id}
        self.copies.put_item(Item=copy, ConditionExpression="attribute_not_exists(copy_id)")
        return copy

    def set_pending_cover(self, book_id: str, key: str) -> None:
        self.books.update_item(
            Key={"book_id": book_id}, UpdateExpression="SET pending_cover_key = :key",
            ExpressionAttributeValues={":key": key}, ConditionExpression="attribute_exists(book_id)",
        )

    def confirm_cover(self, book_id: str, key: str) -> dict:
        result = self.books.update_item(
            Key={"book_id": book_id}, UpdateExpression="SET cover_key = :key REMOVE pending_cover_key",
            ExpressionAttributeValues={":key": key}, ConditionExpression="attribute_exists(book_id)",
            ReturnValues="ALL_NEW",
        )
        return result["Attributes"]

    def list_copies(self, book_id: str, limit: int, key: dict | None) -> dict:
        options = {"IndexName": "book_id-index", "KeyConditionExpression": Key("book_id").eq(book_id), "Limit": limit}
        if key:
            options["ExclusiveStartKey"] = key
        result = self.copies.query(**options)
        return {"items": result["Items"], "last_evaluated_key": result.get("LastEvaluatedKey")}
