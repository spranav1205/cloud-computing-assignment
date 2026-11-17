"""Create only local DynamoDB Books/Copies tables. No S3 at checkpoint 3."""
import os
from time import sleep

from botocore.exceptions import EndpointConnectionError

from app.database import initialize_tables, local_resource
from app.config import aws_mode

if __name__ == "__main__":
    if aws_mode():
        raise SystemExit("This initializer is local-only; provision AWS tables through approved Terraform operations")
    resource = local_resource()
    # DynamoDB Local's Java process can take a few seconds to accept connections.
    for attempt in range(20):
        try:
            initialize_tables(resource, os.environ.get("BOOKS_TABLE", "Books"), os.environ.get("COPIES_TABLE", "Copies"))
            break
        except EndpointConnectionError:
            if attempt == 19:
                raise
            sleep(1)
    resource.meta.client.close()
    print("Local Books and Copies tables initialized.")
