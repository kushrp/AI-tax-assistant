from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from tax_assistant.config import Settings


class StorageBackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class StorageObject:
    key: str
    location: str


class BaseObjectStorage:
    def store_bytes(self, key: str, payload: bytes) -> StorageObject:
        raise NotImplementedError

    def read_bytes(self, location: str) -> bytes:
        raise NotImplementedError

    def delete(self, location: str) -> None:
        raise NotImplementedError

    def exists(self, location: str) -> bool:
        raise NotImplementedError


class LocalObjectStorage(BaseObjectStorage):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def store_bytes(self, key: str, payload: bytes) -> StorageObject:
        relative = _sanitize_key(key)
        path = (self.root / relative).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return StorageObject(key=relative, location=f"file://{path}")

    def read_bytes(self, location: str) -> bytes:
        path = _local_path_from_location(location, self.root)
        return path.read_bytes()

    def delete(self, location: str) -> None:
        path = _local_path_from_location(location, self.root)
        if path.exists():
            path.unlink()

    def exists(self, location: str) -> bool:
        path = _local_path_from_location(location, self.root)
        return path.exists()


class S3ObjectStorage(BaseObjectStorage):
    def __init__(self, settings: Settings):
        if not settings.storage_bucket.strip():
            raise StorageBackendError("TAX_ASSISTANT_STORAGE_BUCKET is required for s3 backend")

        try:
            import boto3
        except Exception as exc:  # pragma: no cover - only exercised when s3 backend is selected.
            raise StorageBackendError("boto3 is required for s3 storage backend") from exc

        self.bucket = settings.storage_bucket.strip()
        self.prefix = settings.storage_prefix.strip().strip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url or None,
            region_name=settings.storage_region or None,
            aws_access_key_id=settings.storage_access_key_id or None,
            aws_secret_access_key=settings.storage_secret_access_key or None,
        )

    def store_bytes(self, key: str, payload: bytes) -> StorageObject:
        relative = _sanitize_key(key)
        full_key = f"{self.prefix}/{relative}" if self.prefix else relative
        self.client.put_object(Bucket=self.bucket, Key=full_key, Body=payload)
        return StorageObject(key=full_key, location=f"s3://{self.bucket}/{full_key}")

    def read_bytes(self, location: str) -> bytes:
        bucket, key = _parse_s3_location(location, default_bucket=self.bucket)
        response = self.client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def delete(self, location: str) -> None:
        bucket, key = _parse_s3_location(location, default_bucket=self.bucket)
        self.client.delete_object(Bucket=bucket, Key=key)

    def exists(self, location: str) -> bool:
        bucket, key = _parse_s3_location(location, default_bucket=self.bucket)
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False


def build_object_storage(settings: Settings) -> BaseObjectStorage:
    backend = settings.normalized_storage_backend
    if backend == "local":
        return LocalObjectStorage(settings.storage_path)
    if backend == "s3":
        return S3ObjectStorage(settings)
    raise StorageBackendError(f"Unsupported storage backend '{settings.storage_backend}'")


def build_storage_key(*, tax_year: int, return_id: str, digest: str, extension: str) -> str:
    safe_extension = extension.lower() if extension else ".bin"
    if not safe_extension.startswith("."):
        safe_extension = f".{safe_extension}"
    return f"{tax_year}/{return_id}/{digest}{safe_extension}"


def _sanitize_key(key: str) -> str:
    normalized = key.strip().lstrip("/")
    if not normalized:
        raise StorageBackendError("Storage key cannot be empty")
    return normalized


def _local_path_from_location(location: str, root: Path) -> Path:
    raw = location.strip()
    if raw.startswith("file://"):
        return Path(raw.removeprefix("file://")).resolve()
    if raw.startswith("s3://"):
        raise StorageBackendError("Cannot read s3:// location with local storage backend")
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    return (root / raw).resolve()


def _parse_s3_location(location: str, *, default_bucket: str) -> tuple[str, str]:
    raw = location.strip()
    if raw.startswith("s3://"):
        parsed = urlparse(raw)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
    else:
        bucket = default_bucket
        key = raw.lstrip("/")

    if not bucket or not key:
        raise StorageBackendError(f"Invalid s3 location '{location}'")
    return bucket, key
