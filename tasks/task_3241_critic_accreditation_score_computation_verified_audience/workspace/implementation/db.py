"""In-memory data store, logical clock, and timestamp helpers."""
from datetime import datetime, timezone
import threading

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

_lock = threading.Lock()


def _parse_iso(s):
    """Parse ISO 8601 string; trailing 'Z' means UTC. Naive values treated as UTC."""
    if s is None:
        return None
    text = str(s).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits and trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def now_iso():
    """Current logical-clock instant as an ISO string."""
    with _lock:
        return _fmt_iso(db.logical_clock)


class _DB:
    def __init__(self):
        self.publications = {}
        self.critics = {}
        self.accreditation_reviews = {}
        self.titles = {}
        self.releases = {}
        self.reviews = {}
        self.audience_members = {}
        self.ticket_verifications = {}
        self.audience_ratings = {}
        self.score_snapshots = {}
        self.bombing_incidents = {}
        self.disputes = {}
        self.logical_clock = _parse_iso(DEFAULT_CLOCK_ISO)


db = _DB()
