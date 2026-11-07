"""The resume store: one bucket in an S3-compatible store, such as R2 or S3.

Invariant: the store's address, region and credentials come from the five
storage settings and nowhere else. boto3 would otherwise also read them from
``AWS_`` environment variables and the shared AWS config and credentials files,
so a variable set in the shell for another project could send resumes to
another store; the client here is built on a session that reads neither.

Every call to the store runs in a worker thread, since boto3 blocks, and a
store that does not answer, or refuses, raises ``StoreDidNotAnswer`` after one
warning that names the operation and the error, never the credentials, the
file or the store's address.
"""

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import boto3
import botocore.session
from botocore.config import Config
from botocore.configprovider import BOTOCORE_DEFAUT_SESSION_VARIABLES
from botocore.exceptions import BotoCoreError, ClientError
from starlette.concurrency import run_in_threadpool

from job_board.settings import StorageSettings

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client  # the stubs are a development dependency

logger = logging.getLogger(__name__)

# A store that never answers is given up on after about 51 seconds at worst:
# two tries, each up to 5 seconds to connect and 20 to answer, and one pause
# between them of at most a second. Standard mode retries a read or connect
# timeout (botocore/retries/standard.py, _TRANSIENT_EXCEPTION_CLS), and its
# first pause is random() * min(2 ** 0, 20) seconds, or 0.05 of that where
# AWS_NEW_RETRIES_2026 is true (ExponentialBackoff.delay_amount). The panel
# waits longer than this on an upload and a removal.
CLIENT_CONFIG = Config(
    connect_timeout=5,  # seconds; a store that cannot be reached is not waited on
    read_timeout=20,  # seconds; 5 MiB to a store that is slow to answer
    # Tries in all, the first included. Its "max_attempts" would count retries,
    # one try more (botocore/config.py, the retries parameter).
    retries={"total_max_attempts": 2, "mode": "standard"},
    # Checksums only where an operation requires one: some S3-compatible stores
    # refuse the checksum headers that boto3 now sends by default.
    request_checksum_calculation="when_required",
    response_checksum_validation="when_required",
)

# Every botocore session setting with its environment variable and config file
# entry taken away, keeping only its default; the config and credentials files
# themselves are the null device, so nothing is read from ~/.aws either.
SETTINGS_FROM_NOWHERE = {
    name: (None, None, default, convert)
    for name, (_, _, default, convert) in BOTOCORE_DEFAUT_SESSION_VARIABLES.items()
} | {
    "config_file": (None, None, os.devnull, None),
    "credentials_file": (None, None, os.devnull, None),
}


class StoreDidNotAnswer(Exception):
    """The store could not be reached, or refused the operation."""


@dataclass(frozen=True)
class ResumeStore:
    client: S3Client
    bucket: str

    async def put(self, key: str, body: bytes) -> None:
        """Writes the file at ``key`` as a PDF, replacing any file already there."""
        try:
            await run_in_threadpool(
                self.client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType="application/pdf",
            )
        except (BotoCoreError, ClientError) as error:
            raise did_not_answer("put_object", error) from None

    async def delete(self, key: str) -> None:
        """Deletes the file at ``key``; the store answers alike when there is none."""
        try:
            await run_in_threadpool(self.client.delete_object, Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as error:
            raise did_not_answer("delete_object", error) from None

    def close(self) -> None:
        self.client.close()


def did_not_answer(operation: str, error: BotoCoreError | ClientError) -> StoreDidNotAnswer:
    # The error's own message can carry the store's address, so only its class
    # and, from a refusal, the store's error code are logged.
    # boto3 raises a refusal as a subclass named after its code, so a refusal is
    # logged as ClientError with the code.
    if isinstance(error, ClientError):
        cause = f"ClientError {error.response.get('Error', {}).get('Code', 'without a code')}"
    else:
        cause = type(error).__name__
    logger.warning("resume storage did not answer %s: %s", operation, cause)
    return StoreDidNotAnswer(operation)


def open_store(storage: StorageSettings | None) -> ResumeStore | None:
    """The store the settings name, or None, with a warning, when they name none."""
    if storage is None:
        logger.warning("resume storage is not set up: the resume routes answer 503")
        return None
    session = botocore.session.Session(session_vars=SETTINGS_FROM_NOWHERE)
    client = boto3.session.Session(botocore_session=session).client(
        "s3",
        endpoint_url=storage.endpoint_url,
        region_name=storage.region,
        aws_access_key_id=storage.access_key_id.get_secret_value(),
        aws_secret_access_key=storage.secret_access_key.get_secret_value(),
        config=CLIENT_CONFIG,
    )
    return ResumeStore(client, storage.bucket)
