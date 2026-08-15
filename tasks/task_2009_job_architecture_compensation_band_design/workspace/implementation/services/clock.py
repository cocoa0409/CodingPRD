"""Server-owned logical clock. Default before any set: 2026-08-01T00:00:00Z.
Never falls back to wall-clock time."""
from datetime import datetime, timezone

_DEFAULT_ISO = "2026-08-01T00:00:00.000Z"
_current_iso = _DEFAULT_ISO


def _parse_iso(value: str) -> datetime:
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now() -> datetime:
    return _parse_iso(_current_iso)


def now_iso() -> str:
    return _current_iso


def set_current(to_iso8601: str) -> str:
    global _current_iso
    dt = _parse_iso(to_iso8601)  # raises ValueError on malformed input
    _current_iso = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return _current_iso


def reset():
    """Test helper: restore startup default. Not exposed via API."""
    global _current_iso
    _current_iso = _DEFAULT_ISO
