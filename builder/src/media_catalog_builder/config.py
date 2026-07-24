from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True, slots=True)
class CatalogConfig:
    schema_version: int
    manifest_schema_version: int
    bootstrap_start_year: int
    future_years: int
    languages: tuple[str, ...]
    max_names_per_work: int
    max_compressed_mib: int
    max_installed_mib: int
    target_delta_mib: int
    request_timeout_seconds: int
    request_interval_seconds: float
    request_retries: int
    modified_window_overlap_hours: int
    supported_delta_versions: int
    user_agent: str
    sparql_endpoint: str

    @classmethod
    def load(cls, path: Path) -> "CatalogConfig":
        with path.open("rb") as handle:
            values = tomllib.load(handle)

        values["languages"] = tuple(values.get("languages", ()))
        config = cls(**values)
        config._validate()
        return config

    def _validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError("schema_version must be 1")
        if self.manifest_schema_version != 1:
            raise ValueError("manifest_schema_version must be 1")
        if self.max_names_per_work > 4:
            raise ValueError("max_names_per_work cannot exceed 4")
        if self.max_compressed_mib > 100:
            raise ValueError("max_compressed_mib cannot exceed 100")
        if self.max_installed_mib > 250:
            raise ValueError("max_installed_mib cannot exceed 250")
        if self.max_names_per_work < 1:
            raise ValueError("max_names_per_work must be positive")
        if self.bootstrap_start_year < 1800:
            raise ValueError("bootstrap_start_year must be at least 1800")
        if self.future_years < 0:
            raise ValueError("future_years cannot be negative")
        if not self.languages:
            raise ValueError("at least one language is required")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if self.request_interval_seconds < 0:
            raise ValueError("request_interval_seconds cannot be negative")
        if self.request_retries < 1:
            raise ValueError("request_retries must be positive")
        if not self.user_agent.strip():
            raise ValueError("user_agent is required")
        if not self.sparql_endpoint.startswith("https://"):
            raise ValueError("sparql_endpoint must use HTTPS")
