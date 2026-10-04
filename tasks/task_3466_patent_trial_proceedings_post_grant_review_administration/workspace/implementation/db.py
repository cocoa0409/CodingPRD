"""In-memory data store and the logical clock.

The store starts empty on every boot: no seeding, no preloaded entities, no
disk persistence. Every entity any caller needs is constructed via the
declared API surface.

The logical clock (PRD section 2.4) defaults to exactly 2026-09-01T00:00:00Z
and never falls back to wall-clock time. It is set through the platform-level
POST /_clock/set_current_utc endpoint.
"""

import threading
import uuid
from datetime import datetime, timezone


DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Clock:
    def __init__(self):
        self._dt = parse_iso(DEFAULT_CLOCK_ISO)
        self._echo = DEFAULT_CLOCK_ISO

    def set(self, to_iso8601):
        self._dt = parse_iso(to_iso8601)
        self._echo = to_iso8601
        return self._echo

    def now(self):
        return self._dt

    def now_iso(self):
        return format_iso(self._dt)


class Store:
    """All entity tables plus a monotonic insertion sequence used as the
    stable tie-breaker for created_at-ordered listings."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = Clock()
        self.seq = 0
        self.parties = {}
        self.patents = {}
        self.matters = {}
        self.petitions = {}
        self.decisions = {}          # InstitutionDecision by id
        self.proceedings = {}
        self.briefs = {}
        self.declarations = {}
        self.discovery_requests = {}
        self.motions = {}
        self.hearings = {}
        self.rooms = {}
        self.fwds = {}               # FinalWrittenDecision by id
        self.appeals = {}

    def next_seq(self):
        self.seq += 1
        return self.seq

    def new_id(self):
        return str(uuid.uuid4())

    def new_common(self):
        """Fresh system-managed common fields (PRD section 2.5)."""
        now = self.clock.now_iso()
        return {
            "id": self.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": self.next_seq(),
        }

    def touch(self, entity):
        """Refresh updated_at and bump version on a versioned entity."""
        entity["updated_at"] = self.clock.now_iso()
        entity["version"] += 1


def strip_internal(entity):
    """Return a JSON-serializable view without internal bookkeeping keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# Module-level singleton store; re-created per process boot.
store = Store()
