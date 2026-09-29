"""Type aliases and shared field groupings for the compliance domain."""

from typing import Any, Dict, List, Tuple

# A parsed JSON object returned inside the ``data`` member of the envelope.
Entity = Dict[str, Any]
# A request body.
Payload = Dict[str, Any]
# A header bundle carrying X-User-ID and X-User-Role.
Headers = Dict[str, str]
# The ``(items, meta)`` pair produced by a paginated list read.
Page = Tuple[List[Entity], Dict[str, Any]]

# Identity fields present on every persisted row.
IDENTITY_FIELDS = ("id", "created_at")

# Mutable rows additionally carry a refreshed timestamp and an integer version.
MUTABLE_AUDIT_FIELDS = ("updated_at", "version")

# Rows that carry the mutable audit pair.
VERSIONED_ENTITIES = (
    "Provider",
    "Certificate",
    "MitigationPlan",
    "Customer",
    "NumberAssignment",
    "TracebackRequest",
    "IllegalTrafficNotice",
    "BlockingEvent",
    "BlockingDispute",
    "EnforcementAction",
    "EffectivenessReport",
)

# Append-only rows: identity fields only, no updated_at and no version.
APPEND_ONLY_ENTITIES = ("CallAttestation", "TrafficObservation")

# Envelope members.
ENVELOPE_META_FIELDS = (
    "api_request_id",
    "api_request_timestamp",
    "limit",
    "offset",
    "total_count",
    "has_more",
)

# Every derived compliance counter carried on a provider row.
PROVIDER_COUNTER_FIELDS = (
    "penalty_points",
    "overdue_traceback_count",
    "open_notice_count",
    "active_assigned_number_count",
    "outstanding_forfeiture_cents",
    "blocking_false_positive_rate",
    "sweep_index",
)

# The five call-detail fields a produced attestation must match.
CALL_DETAIL_FIELDS = (
    "customer_id",
    "calling_number",
    "called_number",
    "origination_time",
    "attestation_level",
)

# Quantities held to four-decimal precision.
FOUR_DECIMAL_FIELDS = (
    "traffic_risk_index",
    "resulting_risk_index",
    "analytics_score",
    "blocking_false_positive_rate",
    "attestation_component",
    "traceback_component",
    "notice_component",
    "effectiveness_score",
)

# The single quantity held to two-decimal precision.
TWO_DECIMAL_FIELDS = ("window_subscore",)
