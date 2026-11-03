"""Runtime settings, operating modes and repository-root discovery.

Values come from environment variables (prefix ``TESSERA_``) and the optional ``.env`` file at the
repository root. No secret has a default value, and settings are never written back to disk.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

#: A file that exists only at the repository root; used to locate the root from anywhere.
ROOT_MARKER = Path("policies") / "sources.yaml"


class Mode(StrEnum):
    """Operating mode. Only ``RESEARCH_INTERNAL`` may load restricted (DFSA) facts."""

    RESEARCH_INTERNAL = "RESEARCH_INTERNAL"
    RESTRICTED_DEMO = "RESTRICTED_DEMO"


def find_repo_root(start: Path | None = None) -> Path:
    """Return the nearest ancestor of ``start`` that contains ``policies/sources.yaml``.

    The ``TESSERA_ROOT`` environment variable overrides the search.
    """
    override = os.environ.get("TESSERA_ROOT")
    if override:
        root = Path(override).resolve()
        if not (root / ROOT_MARKER).is_file():
            raise FileNotFoundError(f"TESSERA_ROOT={root} has no {ROOT_MARKER.as_posix()}")
        return root
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ROOT_MARKER).is_file():
            return candidate
    raise FileNotFoundError(f"no {ROOT_MARKER.as_posix()} found above {here}")


class Settings(BaseSettings):
    """Process-wide settings. Prefer :func:`load_settings`, which also reads ``.env``."""

    model_config = SettingsConfigDict(env_prefix="TESSERA_", extra="ignore", populate_by_name=True)

    #: Safe default: restricted data never loads unless research mode is chosen explicitly.
    mode: Mode = Mode.RESTRICTED_DEMO
    root: Path = Field(default_factory=find_repo_root)
    data_dir: Path | None = None
    #: Free NVIDIA API catalog key (Part 2 onwards). Never logged, never committed.
    nvidia_api_key: SecretStr | None = Field(default=None, validation_alias="NVIDIA_API_KEY")

    @property
    def data_path(self) -> Path:
        return (self.data_dir or self.root / "data").resolve()

    @property
    def policies_dir(self) -> Path:
        return self.root / "policies"

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "knowledge"

    @property
    def restricted_dir(self) -> Path:
        return self.data_path / "restricted"

    @property
    def restricted_allowed(self) -> bool:
        return self.mode is Mode.RESEARCH_INTERNAL


def load_settings(**overrides: Any) -> Settings:
    """Build settings from the environment, the root ``.env`` file and explicit overrides."""
    root = Path(overrides["root"]) if overrides.get("root") else find_repo_root()
    env_file = root / ".env"
    return Settings(_env_file=env_file if env_file.is_file() else None, **overrides)
