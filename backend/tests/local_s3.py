"""An S3 server on this machine for the tests, so no test reaches a storage provider."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from moto.server import ThreadedMotoServer
from types_boto3_s3 import S3Client


@contextmanager
def local_s3_server() -> Iterator[str]:
    """Moto's S3 server on a free loopback port, stopped on leaving; yields its address."""
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    try:
        host, port = server.get_host_and_port()
        yield f"http://{host}:{port}"
    finally:
        server.stop()


@dataclass(frozen=True)
class LocalBucket:
    """A bucket on the local server, with a client to look inside it."""

    name: str
    client: S3Client

    def stored_keys(self) -> list[str]:
        listed = self.client.list_objects_v2(Bucket=self.name)
        return sorted(item["Key"] for item in listed.get("Contents", []))

    def read(self, key: str) -> tuple[bytes, str]:
        """An object's bytes and its content type."""
        stored = self.client.get_object(Bucket=self.name, Key=key)
        return stored["Body"].read(), stored["ContentType"]

    def put(self, key: str, body: bytes) -> None:
        self.client.put_object(Bucket=self.name, Key=key, Body=body)
