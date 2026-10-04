"""In-memory data store. No persistence; a fresh process starts empty."""
from datetime import datetime, timezone

STARTUP_CLOCK_ISO = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.members = {}
        self.signers = {}
        self.loans = {}
        self.transfers = {}
        self.matches = {}
        self.reviews = {}
        self.findings = {}
        self.reports = {}
        self.sanctions = {}
        self.runs = {}
        self.exceptions = {}
        self.member_serials = {}  # member_id -> next serial to assign
        self.clock = datetime(2026, 9, 1, tzinfo=timezone.utc)


store = Store()


def iso(dt: datetime) -> str:
    """Logical-clock timestamps: whole-second ISO 8601 UTC with Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
