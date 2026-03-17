from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, TypeAlias

BlockHash: TypeAlias = str
GLOBAL_SCOPE_ROOT = "__global__"


class Scope(str, Enum):
    SESSION = "session"
    GLOBAL = "global"


@dataclass(frozen=True)
class RequestRecord:
    request_id: str
    source_index: int
    timestamp_ms: int
    chat_id: str
    parent_chat_id: Optional[str]
    turn: int
    request_type: str
    input_length: int
    output_length: int
    hash_ids: tuple[BlockHash, ...]

    @property
    def block_count(self) -> int:
        return len(self.hash_ids)


@dataclass(frozen=True)
class EffectiveRequest:
    request_id: str
    source_index: int
    timestamp_ms: int
    chat_id: str
    scope: Scope
    scope_root_id: str
    turn: int
    request_type: str
    input_length: int
    output_length: int
    total_blocks: int
    effective_blocks: int
    effective_tokens: int
    effective_hash_ids: tuple[BlockHash, ...]


@dataclass(frozen=True)
class ModelProfile:
    n_layers: int
    n_kv_heads: int
    head_dim: int
    dtype_bytes: int
    kv_cache_layer_count: int | None = None
    tp_size: int = 1
    pp_size: int = 1
    block_size: int = 16
    parameter_count: int | None = None
    weight_dtype_bytes: int | None = None

    def kv_bytes_per_token(self) -> int:
        return (
            2
            * self.resolved_kv_cache_layer_count()
            * self.n_kv_heads
            * self.head_dim
            * self.dtype_bytes
        )

    def kv_bytes_per_token_per_rank(self) -> int:
        shard_factor = self.tp_size * self.pp_size
        if shard_factor <= 0:
            raise ValueError("tp_size * pp_size must be positive")
        return self.kv_bytes_per_token() // shard_factor

    def kv_bytes_per_block(self) -> int:
        return self.block_size * self.kv_bytes_per_token()

    def resolved_kv_cache_layer_count(self) -> int:
        if self.kv_cache_layer_count is None:
            return self.n_layers
        return self.kv_cache_layer_count

    def resolved_weight_dtype_bytes(self) -> int:
        if self.weight_dtype_bytes is None:
            return self.dtype_bytes
        return self.weight_dtype_bytes

    def weight_bytes_total(self) -> int | None:
        if self.parameter_count is None:
            return None
        return self.parameter_count * self.resolved_weight_dtype_bytes()

    def weight_bytes_per_rank(self) -> int | None:
        total_weight_bytes = self.weight_bytes_total()
        if total_weight_bytes is None:
            return None
        shard_factor = self.tp_size * self.pp_size
        if shard_factor <= 0:
            raise ValueError("tp_size * pp_size must be positive")
        return (total_weight_bytes + shard_factor - 1) // shard_factor


@dataclass(frozen=True)
class MachineProfile:
    gpu_kv_budget_bytes: int
    cpu_kv_budget_bytes: int = 0
    cpu_to_gpu_bandwidth_bytes_per_sec: int = 0
    remote_to_cpu_bandwidth_bytes_per_sec: int = 0
