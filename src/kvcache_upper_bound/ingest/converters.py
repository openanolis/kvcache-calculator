from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


TIMESTAMP_KEYS = ("timestamp_ms", "timestamp", "time", "ts", "created_at")
INPUT_LENGTH_KEYS = ("input_length", "prompt_length", "prompt_len")
OUTPUT_LENGTH_KEYS = ("output_length", "completion_length", "completion_len")
MESSAGE_LIST_KEYS = ("conversation", "conversations", "messages", "turns")
MESSAGE_ROLE_KEYS = ("role", "from", "speaker", "author")
MESSAGE_CONTENT_KEYS = ("content", "value", "text")
DATASET_ID_KEYS = ("conversation_id", "chat_id", "id")
_TOKEN_PATTERN = re.compile(r"\S+")


@dataclass(frozen=True)
class ConversionStats:
    total_items: int
    emitted_records: int
    skipped_items: int
    synthetic_timestamps: int
    synthetic_hash_records: int
    degraded_session_records: int


@dataclass(frozen=True)
class ConversionResult:
    mode: str
    source_format: str
    input_path: str
    output_trace_path: str
    output_metadata_path: str
    block_size: int
    stats: ConversionStats
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class _CanonicalMessage:
    role: str
    content: str


def convert_conversation_dataset(
    input_path: str | Path,
    output_trace_path: str | Path,
    *,
    source_format: str,
    block_size: int = 16,
) -> ConversionResult:
    _validate_block_size(block_size)
    total_items = 0
    emitted_records = 0
    skipped_items = 0
    synthetic_timestamps = 0
    output_path = Path(output_trace_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        for item_index, payload in enumerate(_iter_input_payloads(input_path)):
            total_items += 1
            session_id = _parse_optional_string(_extract_optional(payload, DATASET_ID_KEYS))
            if session_id is None:
                session_id = f"{source_format}-session-{item_index:08d}"
            messages = _extract_canonical_messages(payload)
            if not messages:
                skipped_items += 1
                continue

            base_timestamp_ms, used_synthetic_timestamp = _resolve_timestamp_ms(
                payload=payload,
                synthetic_base_ms=item_index * 1000,
            )
            synthetic_timestamps += int(used_synthetic_timestamp)

            prompt_messages: list[_CanonicalMessage] = []
            parent_chat_id: str | None = None
            assistant_turn = 0
            emitted_for_item = 0
            for message in messages:
                if message.role != "assistant":
                    prompt_messages.append(message)
                    continue
                if not prompt_messages:
                    prompt_messages.append(message)
                    continue

                assistant_turn += 1
                prompt_tokens = _flatten_prompt_tokens(prompt_messages)
                output_tokens = _tokenize_text(message.content)
                if not prompt_tokens:
                    prompt_messages.append(message)
                    continue

                chat_id = f"{session_id}/turn-{assistant_turn}"
                record = {
                    "request_id": chat_id,
                    "chat_id": chat_id,
                    "parent_chat_id": parent_chat_id,
                    "turn": assistant_turn,
                    "type": f"conversation_dataset:{source_format}",
                    "timestamp_ms": base_timestamp_ms + assistant_turn - 1,
                    "input_length": len(prompt_tokens),
                    "output_length": len(output_tokens),
                    "hash_ids": _tokens_to_hash_ids(prompt_tokens, block_size=block_size),
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                parent_chat_id = chat_id
                emitted_records += 1
                emitted_for_item += 1
                prompt_messages.append(message)

            if emitted_for_item == 0:
                skipped_items += 1

    limitations = (
        "converted trace is derived from conversation datasets, not a native serving trace",
        "hash_ids are generated from deterministic whitespace-token blocks with role markers",
        "timestamps fall back to synthetic monotonic values when source timestamps are absent",
    )
    return _finalize_conversion_result(
        mode="conversation_dataset_conversion",
        source_format=source_format,
        input_path=input_path,
        output_trace_path=output_path,
        block_size=block_size,
        stats=ConversionStats(
            total_items=total_items,
            emitted_records=emitted_records,
            skipped_items=skipped_items,
            synthetic_timestamps=synthetic_timestamps,
            synthetic_hash_records=0,
            degraded_session_records=0,
        ),
        limitations=limitations,
    )


def convert_benchmark_results(
    input_path: str | Path,
    output_trace_path: str | Path,
    *,
    block_size: int = 16,
    allow_synthetic_hash_ids: bool = False,
) -> ConversionResult:
    _validate_block_size(block_size)
    total_items = 0
    emitted_records = 0
    skipped_items = 0
    synthetic_timestamps = 0
    synthetic_hash_records = 0
    degraded_session_records = 0
    output_path = Path(output_trace_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        for item_index, payload in enumerate(_iter_input_payloads(input_path)):
            total_items += 1
            try:
                request_id = _parse_optional_string(payload.get("request_id")) or _parse_optional_string(
                    payload.get("id")
                )
                if request_id is None:
                    request_id = f"benchmark-{item_index:08d}"
                timestamp_ms, used_synthetic_timestamp = _resolve_timestamp_ms(
                    payload=payload,
                    synthetic_base_ms=item_index,
                )
                input_length = int(_extract_required(payload, INPUT_LENGTH_KEYS))
                output_length = int(_extract_optional(payload, OUTPUT_LENGTH_KEYS) or 0)
                hash_ids = _extract_benchmark_hash_ids(
                    payload=payload,
                    request_id=request_id,
                    source_index=item_index,
                    input_length=input_length,
                    block_size=block_size,
                    allow_synthetic_hash_ids=allow_synthetic_hash_ids,
                )
            except (TypeError, ValueError):
                skipped_items += 1
                continue

            synthetic_timestamps += int(used_synthetic_timestamp)
            if hash_ids and hash_ids[0].startswith("__synthetic__"):
                synthetic_hash_records += 1

            raw_chat_id = _parse_optional_string(payload.get("chat_id"))
            turn_value = payload.get("turn")
            degraded_session = raw_chat_id is None or turn_value is None
            degraded_session_records += int(degraded_session)

            chat_id = raw_chat_id or request_id
            turn = 1 if turn_value is None else int(turn_value)
            parent_chat_id = None if degraded_session else _parse_optional_parent_chat_id(
                payload.get("parent_chat_id")
            )

            record = {
                "request_id": request_id,
                "chat_id": chat_id,
                "parent_chat_id": parent_chat_id,
                "turn": turn,
                "type": str(payload.get("type", "benchmark_result")),
                "timestamp_ms": timestamp_ms,
                "input_length": input_length,
                "output_length": output_length,
                "hash_ids": hash_ids,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            emitted_records += 1

    limitations = [
        "benchmark-result conversion is replay-oriented and must not be interpreted as native strict-prefix truth",
        "missing chat/session fields degrade to standalone requests rooted at request_id",
    ]
    if allow_synthetic_hash_ids:
        limitations.append(
            "synthetic hash_ids create replay-only unique prefixes and intentionally do not claim real reuse"
        )
    else:
        limitations.append("records without hash_ids are rejected unless --allow-synthetic-hash-ids is set")
    return _finalize_conversion_result(
        mode="benchmark_replay_conversion",
        source_format="benchmark_result_jsonl",
        input_path=input_path,
        output_trace_path=output_path,
        block_size=block_size,
        stats=ConversionStats(
            total_items=total_items,
            emitted_records=emitted_records,
            skipped_items=skipped_items,
            synthetic_timestamps=synthetic_timestamps,
            synthetic_hash_records=synthetic_hash_records,
            degraded_session_records=degraded_session_records,
        ),
        limitations=tuple(limitations),
    )


def write_conversion_metadata(result: ConversionResult, path: str | Path) -> dict[str, Any]:
    metadata = {
        "mode": result.mode,
        "source_format": result.source_format,
        "input": result.input_path,
        "output_trace": result.output_trace_path,
        "output_metadata": str(Path(path).resolve()),
        "block_size": result.block_size,
        "stats": asdict(result.stats),
        "limitations": list(result.limitations),
    }
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def _finalize_conversion_result(
    *,
    mode: str,
    source_format: str,
    input_path: str | Path,
    output_trace_path: Path,
    block_size: int,
    stats: ConversionStats,
    limitations: tuple[str, ...],
) -> ConversionResult:
    metadata_path = output_trace_path.parent / "metadata.json"
    result = ConversionResult(
        mode=mode,
        source_format=source_format,
        input_path=str(Path(input_path).resolve()),
        output_trace_path=str(output_trace_path.resolve()),
        output_metadata_path=str(metadata_path.resolve()),
        block_size=block_size,
        stats=stats,
        limitations=limitations,
    )
    write_conversion_metadata(result, metadata_path)
    return result


def _iter_input_payloads(path: str | Path) -> Iterator[Mapping[str, Any]]:
    source_path = Path(path)
    text = source_path.read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError("JSON array input must contain a list of objects")
        for item in payload:
            if isinstance(item, Mapping):
                yield item
        return

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if isinstance(payload, Mapping):
            yield payload


def _extract_canonical_messages(payload: Mapping[str, Any]) -> list[_CanonicalMessage]:
    raw_messages = _extract_optional(payload, MESSAGE_LIST_KEYS)
    if not isinstance(raw_messages, list):
        return []

    messages: list[_CanonicalMessage] = []
    for raw_message in raw_messages:
        if not isinstance(raw_message, Mapping):
            continue
        role = _canonicalize_role(_extract_optional(raw_message, MESSAGE_ROLE_KEYS))
        content = _parse_optional_string(_extract_optional(raw_message, MESSAGE_CONTENT_KEYS))
        if role is None or content is None:
            continue
        messages.append(_CanonicalMessage(role=role, content=content))
    return messages


def _canonicalize_role(value: Any) -> str | None:
    role = _parse_optional_string(value)
    if role is None:
        return None
    lowered = role.strip().lower()
    if lowered in {"user", "human", "prompter"}:
        return "user"
    if lowered in {"assistant", "gpt", "bot", "model"}:
        return "assistant"
    if lowered == "system":
        return "system"
    return None


def _resolve_timestamp_ms(
    *,
    payload: Mapping[str, Any],
    synthetic_base_ms: int,
) -> tuple[int, bool]:
    raw_value = _extract_optional(payload, TIMESTAMP_KEYS)
    if raw_value is None:
        return synthetic_base_ms, True
    return _parse_timestamp_ms(raw_value), False


def _flatten_prompt_tokens(messages: Iterable[_CanonicalMessage]) -> list[str]:
    prompt_tokens: list[str] = []
    for message in messages:
        prompt_tokens.append(f"<{message.role}>")
        prompt_tokens.extend(_tokenize_text(message.content))
        prompt_tokens.append("</message>")
    return prompt_tokens


def _tokenize_text(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text)


def _tokens_to_hash_ids(tokens: list[str], *, block_size: int) -> list[str]:
    """Build deterministic synthetic block hashes for converted traces.

    These hashes preserve prefix-path equality for identical token blocks inside the
    converted dataset, but they are not serving-runtime block hashes.
    """
    if not tokens:
        return []
    hash_ids: list[str] = []
    for block_index in range(0, len(tokens), block_size):
        block_tokens = tokens[block_index : block_index + block_size]
        digest = hashlib.sha256(
            json.dumps(block_tokens, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        hash_ids.append(digest[:16])
    return hash_ids


def _extract_benchmark_hash_ids(
    *,
    payload: Mapping[str, Any],
    request_id: str,
    source_index: int,
    input_length: int,
    block_size: int,
    allow_synthetic_hash_ids: bool,
) -> list[str]:
    raw_hash_ids = payload.get("hash_ids")
    if raw_hash_ids is not None:
        return list(_parse_hash_ids(raw_hash_ids))
    if not allow_synthetic_hash_ids:
        raise ValueError("hash_ids are required for benchmark conversion unless synthetic mode is enabled")
    block_count = (input_length + block_size - 1) // block_size
    return [f"__synthetic__:{request_id}:{source_index}:{block_index}" for block_index in range(block_count)]


def _validate_block_size(block_size: int) -> None:
    if block_size <= 0:
        raise ValueError("block_size must be positive")


def _extract_required(payload: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    value = _extract_optional(payload, keys)
    if value is None:
        raise ValueError(f"missing required field (tried: {', '.join(keys)})")
    return value


def _extract_optional(payload: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _parse_hash_ids(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        if "," in text:
            return tuple(part.strip() for part in text.split(",") if part.strip())
        return (text,)
    raise ValueError("hash_ids must be a list, tuple, or string")


def _parse_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_optional_parent_chat_id(value: Any) -> str | None:
    text = _parse_optional_string(value)
    if text in {None, "-1", "none", "null"}:
        return None
    return text


def _parse_timestamp_ms(value: Any) -> int:
    if isinstance(value, float):
        return _normalize_numeric_timestamp(value)
    if isinstance(value, int):
        return _normalize_numeric_timestamp(float(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("timestamp cannot be empty")
        if _looks_like_number(text):
            return _normalize_numeric_timestamp(float(text))
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return int(datetime.fromisoformat(text).timestamp() * 1000)
        except ValueError as exc:
            raise ValueError(f"unsupported timestamp format: {text!r}") from exc
    raise ValueError("unsupported timestamp type")


def _normalize_numeric_timestamp(value: float) -> int:
    if value >= 1_000_000_000_000:
        return int(value)
    return int(value * 1000)


def _looks_like_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
