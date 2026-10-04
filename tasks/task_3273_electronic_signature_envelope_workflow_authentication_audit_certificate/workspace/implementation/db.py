"""In-memory data store and the server-owned logical clock.

Storage is in-memory only (plain dicts keyed by id) and the store starts
EMPTY on every boot — no seeding, no preloading, no hardcoded entities. Tests
construct all state through the declared API surface.

The logical clock starts at exactly 2026-09-01T00:00:00Z (SCAFFOLD §1.5
POST /esign/_clock/set_current_utc, PRD §2.5) and never falls back to real
wall-clock time.
"""

import uuid
from collections import OrderedDict
from datetime import datetime, timezone

LOGICAL_CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def new_id():
    """Server-minted identifier: a UUID with no type prefix (PRD §2.5)."""
    return str(uuid.uuid4())


def now_clock():
    """The logical clock instant, truncated to millisecond precision."""
    return db.clock


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.accounts = OrderedDict()
        self.retention_policies = OrderedDict()
        self.templates = OrderedDict()
        self.envelopes = OrderedDict()
        self.documents = OrderedDict()
        self.recipients = OrderedDict()
        self.fields = OrderedDict()
        self.sessions = OrderedDict()
        self.audit_events = OrderedDict()
        self.bulk_sends = OrderedDict()
        self.clock = LOGICAL_CLOCK_START
        self._counter = 0

    # -- insertion helpers -------------------------------------------------
    def insert(self, bucket, obj):
        """Insert and stamp an internal monotonic ordering key.

        The logical clock is frozen or rewound in most tests, so created_at
        ties constantly; `_ord` gives list endpoints a deterministic creation
        order instead of falling back to a random id. It is stripped by
        serialize() before any response is emitted.
        """
        obj["_ord"] = self._counter
        self._counter += 1
        bucket[obj["id"]] = obj
        return obj

    def account(self, account_id):
        return self.accounts.get(account_id)

    def envelope(self, envelope_id):
        return self.envelopes.get(envelope_id)

    def recipient(self, recipient_id):
        return self.recipients.get(recipient_id)

    def document(self, document_id):
        return self.documents.get(document_id)

    def field(self, field_id):
        return self.fields.get(field_id)

    def session(self, session_id):
        return self.sessions.get(session_id)

    def template(self, template_id):
        return self.templates.get(template_id)

    def policy(self, policy_id):
        return self.retention_policies.get(policy_id)

    def event(self, event_id):
        return self.audit_events.get(event_id)

    def bulk_send(self, batch_id):
        return self.bulk_sends.get(batch_id)

    # -- relationship queries ---------------------------------------------
    def documents_of(self, envelope_id):
        return [d for d in self.documents.values() if d["envelope_id"] == envelope_id]

    def recipients_of(self, envelope_id):
        return [
            r for r in self.recipients.values() if r["envelope_id"] == envelope_id
        ]

    def fields_of(self, envelope_id):
        return [f for f in self.fields.values() if f["envelope_id"] == envelope_id]

    def sessions_of(self, envelope_id):
        return [
            s for s in self.sessions.values() if s["envelope_id"] == envelope_id
        ]

    def sessions_of_recipient(self, recipient_id):
        return [
            s for s in self.sessions.values() if s["recipient_id"] == recipient_id
        ]

    def events_of(self, envelope_id):
        return [
            e
            for e in self.audit_events.values()
            if e["envelope_id"] == envelope_id
        ]


db = Store()