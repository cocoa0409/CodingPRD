from datetime import datetime, timezone

from util import EPOCH_DEFAULT, parse_iso

_state = {"current": parse_iso(EPOCH_DEFAULT)}


def now():
    """Current logical time as an aware UTC datetime. Never wall-clock."""
    return _state["current"]


def set_now(dt):
    _state["current"] = dt
    return dt
