"""In-memory data store for the observability billing API.

The store starts empty on every boot; nothing is seeded. All entities are
constructed through the declared API surface.
"""

# Entity tables: id -> record dict
billing_accounts = {}
plan_tier_configs = {}
billing_periods = {}
host_hour_records = {}
meter_accumulators = {}
log_events = {}
retention_tiers = {}
exclusion_filters = {}
custom_metric_series = {}
cardinality_incidents = {}
commitments = {}
teams = {}
usage_records = {}
attribution_disputes = {}
tag_policies = {}
monitors = {}
invoices = {}
invoice_lines = {}

# Logical clock (ISO string). Startup default per PRD §2.6; never wall clock.
logical_clock = {"current_utc": "2026-09-01T00:00:00Z"}
