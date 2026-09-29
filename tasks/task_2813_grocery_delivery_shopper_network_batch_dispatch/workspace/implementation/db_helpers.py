"""Small shared mutation helpers."""
from store import touch


def touch_if(row, changed):
    """Bump a row only when a derived input actually changed (PRD 2.10)."""
    if changed:
        touch(row)
