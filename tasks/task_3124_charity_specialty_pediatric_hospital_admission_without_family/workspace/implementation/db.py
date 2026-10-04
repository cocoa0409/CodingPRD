"""In-memory data store. The store starts empty on every boot — no seeding."""
from datetime import datetime, timezone

# Logical clock: startup default is exactly 2026-09-01T00:00:00Z and it must NOT
# fall back to wall-clock time before the first explicit set_current_utc call.
CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

hospitals = {}
programs = {}
referral_sources = {}
applications = {}
reviews = {}
policies = {}
billing_accounts = {}
claims = {}
care_plans = {}
stages = {}
grants = {}
clinics = {}
screenings = {}
funds = {}
allocations = {}
