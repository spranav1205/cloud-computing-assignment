"""Create only local DynamoDB Books/Copies tables. No S3 at checkpoint 3."""
import os

from app.database import initialize_tables, local_resource

if __name__ == "__main__":
    resource = local_resource()
    initialize_tables(resource, os.environ.get("BOOKS_TABLE", "Books"), os.environ.get("COPIES_TABLE", "Copies"))
    resource.meta.client.close()
    print("Local Books and Copies tables initialized.")
