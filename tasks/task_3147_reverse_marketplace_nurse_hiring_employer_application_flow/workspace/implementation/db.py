"""In-memory data store. Fresh on every process boot (per-test-server isolation)."""

# Logical clock: starts at exactly 2026-09-01T00:00:00Z and only advances via
# POST /marketplace/_clock/set_current_utc. Never wall-clock.
from datetime import datetime, timezone

CLOCK_INITIAL = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Entity stores — id -> dict
nurses = {}
license_verifications = {}
certifications = {}
employers = {}
requisitions = {}
matches = {}
applications = {}
interviews = {}
offers = {}
screenings = {}
onboarding_documents = {}
placements = {}
invoices = {}

clock_now = CLOCK_INITIAL
