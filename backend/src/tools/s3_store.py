"""
MandateIQ S3 artifact storage.
Owner: Sreeja Sunkeswaram
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def upload_file(
    local_path: str | Path,
    bucket: str,
    key: str,
    region_name: str = "us-east-1",
) -> str:
    """Upload an artifact using the active AWS credentials."""
    import boto3

    client = boto3.client(
        "s3",
        region_name=region_name,
    )

    client.upload_file(
        str(local_path),
        bucket,
        key,
    )

    return f"s3://{bucket}/{key}"


def upload_json(
    data: Any,
    bucket: str,
    key: str,
    region_name: str = "us-east-1",
) -> str:
    """Upload JSON without writing AWS credentials to source code."""
    import boto3

    client = boto3.client(
        "s3",
        region_name=region_name,
    )

    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(
            data,
            default=str,
            indent=2,
        ).encode("utf-8"),
        ContentType="application/json",
    )

    return f"s3://{bucket}/{key}"