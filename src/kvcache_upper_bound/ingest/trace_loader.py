from __future__ import annotations

import io
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import urlparse
from urllib.request import urlopen

from kvcache_upper_bound.core.models import RequestRecord


TIMESTAMP_KEYS = ("timestamp_ms", "timestamp", "time", "ts")
INPUT_LENGTH_KEYS = ("input_length", "prompt_length", "prompt_len")
OUTPUT_LENGTH_KEYS = ("output_length", "completion_length", "completion_len")


@dataclass(frozen=True)
class TraceLoadStats:
    total_lines: int
    loaded_records: int
    skipped_records: int


@dataclass(frozen=True)
class TraceLoadResult:
    records: list[RequestRecord]
    stats: TraceLoadStats


def load_request_records(path: str | Path, max_records: int | None = None) -> TraceLoadResult:
    records: list[RequestRecord] = []
    skipped_records = 0
    total_lines = 0

    with _open_text_source(path) as handle:
        for source_index, line in enumerate(handle):
            total_lines += 1
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                records.append(_parse_request_record(payload, source_index))
            except (json.JSONDecodeError, TypeError, ValueError):
                skipped_records += 1
            if max_records is not None and len(records) >= max_records:
                break

    records.sort(key=lambda record: (record.timestamp_ms, record.source_index))
    return TraceLoadResult(
        records=records,
        stats=TraceLoadStats(
            total_lines=total_lines,
            loaded_records=len(records),
            skipped_records=skipped_records,
        ),
    )


def _parse_request_record(payload: Mapping[str, Any], source_index: int) -> RequestRecord:
    timestamp_ms = _parse_timestamp_ms(_extract_required(payload, TIMESTAMP_KEYS))
    chat_id = str(_extract_required(payload, ("chat_id",)))
    parent_chat_id = _parse_optional_parent_chat_id(payload.get("parent_chat_id"))
    turn = int(_extract_required(payload, ("turn",)))
    request_type = str(payload.get("type", "unknown"))
    input_length = int(_extract_required(payload, INPUT_LENGTH_KEYS))
    output_length = int(
        payload.get(
            OUTPUT_LENGTH_KEYS[0],
            payload.get(OUTPUT_LENGTH_KEYS[1], payload.get(OUTPUT_LENGTH_KEYS[2], 0)),
        )
    )
    hash_ids = _parse_hash_ids(_extract_required(payload, ("hash_ids",)))
    request_id = _parse_optional_string(payload.get("request_id")) or _parse_optional_string(
        payload.get("id")
    )
    if request_id is None:
        request_id = f"req-{source_index:08d}"

    return RequestRecord(
        request_id=request_id,
        source_index=source_index,
        timestamp_ms=timestamp_ms,
        chat_id=chat_id,
        parent_chat_id=parent_chat_id,
        turn=turn,
        request_type=request_type,
        input_length=input_length,
        output_length=output_length,
        hash_ids=hash_ids,
    )


def _extract_required(payload: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    joined = ", ".join(keys)
    raise ValueError(f"missing required field: {joined}")


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
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("unsupported timestamp format") from exc
        return int(dt.timestamp() * 1000)
    raise ValueError("unsupported timestamp type")


def _normalize_numeric_timestamp(value: float) -> int:
    if value >= 1_000_000_000_000:
        return int(value)
    if value >= 1_000_000_000:
        return int(value * 1000)
    return int(value * 1000)


def _looks_like_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


@contextmanager
def _open_text_source(path: str | Path) -> Iterator[io.TextIOBase]:
    source = str(path)
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        with urlopen(source) as response:
            yield io.TextIOWrapper(response, encoding="utf-8")
        return

    source_path = Path(source)
    with source_path.open("r", encoding="utf-8") as handle:
        first_line = handle.readline()
        if first_line.startswith("version https://git-lfs.github.com/spec/v1"):
            raise ValueError(
                f"{source_path} looks like a Git LFS pointer; use a real JSONL file or the media.githubusercontent.com URL"
            )
        handle.seek(0)
        yield handle
