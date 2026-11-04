"""Load and validate ``policies/models.yaml``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from tessera.errors import PolicyError
from tessera.governance.network import host_matches
from tessera.governance.policies import load_sources_policy


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderConfig(_Frozen):
    name: str
    base_url: str
    api_key_env: str


class RateLimitConfig(_Frozen):
    requests_per_minute: float = Field(gt=0)
    max_concurrent: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    base_backoff_seconds: float = Field(ge=0)
    max_backoff_seconds: float = Field(ge=0)
    request_timeout_seconds: float = Field(gt=0)


class DecodingConfig(_Frozen):
    temperature: float = 0.0
    seed: int | None = None
    max_tokens: int = Field(default=8192, ge=1)


class LimitsConfig(_Frozen):
    tool_calls_per_turn: int = Field(ge=0)
    repair_attempts: int = Field(ge=0)
    requests_per_case: int = Field(ge=1)


class ModelOptions(_Frozen):
    extra_body: dict[str, Any] = Field(default_factory=dict)


class ModelsPolicy(_Frozen):
    version: int
    provider: ProviderConfig
    rate_limit: RateLimitConfig
    decoding: DecodingConfig
    limits: LimitsConfig
    roles: dict[str, str]
    candidates: dict[str, tuple[str, ...]]
    model_options: dict[str, ModelOptions] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _roles_are_candidates(self) -> ModelsPolicy:
        for role, model in self.roles.items():
            if model not in self.candidates.get(role, ()):
                raise ValueError(f"role {role}: {model} is not listed under candidates")
        return self

    def options_for(self, model: str) -> dict[str, Any]:
        options = self.model_options.get(model)
        return dict(options.extra_body) if options else {}

    def with_thinking(self, enabled: bool) -> ModelsPolicy:
        """A copy with the primary model's reasoning switched on or off, for comparisons."""
        primary = self.roles["primary"]
        body = {**self.options_for(primary), "chat_template_kwargs": {"enable_thinking": enabled}}
        options = {**self.model_options, primary: ModelOptions(extra_body=body)}
        return self.model_copy(update={"model_options": options})


@lru_cache(maxsize=8)
def load_models_policy(policies_dir: Path) -> ModelsPolicy:
    path = policies_dir / "models.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        policy = ModelsPolicy(**data)
    except FileNotFoundError as exc:
        raise PolicyError(f"missing policy file: {path}") from exc
    except (yaml.YAMLError, ValidationError, TypeError) as exc:
        raise PolicyError(f"invalid policies/models.yaml:\n{exc}") from exc
    host = urlsplit(policy.provider.base_url).hostname or ""
    allowed = load_sources_policy(policies_dir).network.allowed_llm_hosts
    if not host_matches(host, allowed):
        raise PolicyError(f"{host} is not in allowed_llm_hosts in policies/sources.yaml")
    return policy
