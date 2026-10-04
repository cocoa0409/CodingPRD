"""In-memory data store. Empty at every boot — nothing is seeded."""

# entity collections: id -> dict
programs = {}
assets = {}
scope_versions = {}
researchers = {}
invitations = {}
reports = {}
awards = {}
disclosure_requests = {}
remediation_tickets = {}

# reputation delta ledger: researcher_id -> list of events
# event: {"delta": int, "occurred_at": datetime, "reversed": bool, "kind": str}
reputation_ledger = {}
