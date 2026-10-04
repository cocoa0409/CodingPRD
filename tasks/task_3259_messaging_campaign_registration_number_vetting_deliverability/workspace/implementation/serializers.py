"""Entity serializers. Entities are stored as plain dicts; these functions
project the public representation (identical field set for this scaffold)."""


def _project(entity, fields):
    return {f: entity.get(f) for f in fields}


COMMON_VERSIONED = ["id", "created_at", "updated_at", "version"]
COMMON_APPEND = ["id", "created_at"]

ACCOUNT_FIELDS = COMMON_VERSIONED + [
    "name", "plan_tier", "country_code", "suspend_reason", "status",
]

BRAND_FIELDS = COMMON_VERSIONED + [
    "account_id", "legal_name", "tax_id", "business_type", "address_line1",
    "city", "region_code", "postal_code", "country_code", "website_url",
    "opt_in_mechanism", "identity_score", "resubmission_count", "status",
]

CAMPAIGN_FIELDS = COMMON_VERSIONED + [
    "account_id", "brand_id", "use_case", "description", "sample_messages",
    "help_message", "stop_message", "path_kind", "trust_score", "allocated_mps",
    "rejection_reason_code", "rejected_cycle_count",
    "recurring_fee_last_charge_at", "status",
]

NUMBER_FIELDS = COMMON_VERSIONED + [
    "account_id", "campaign_id", "e164", "phone_number", "number_type",
    "country_code", "provisioning_source", "port_phone_number",
    "port_letter_of_agency", "port_losing_carrier", "base_mps",
    "suspended_reason", "port_requested_at", "status",
]

CONSENT_FIELDS = COMMON_APPEND + [
    "account_id", "brand_id", "phone_number", "evidence_url", "evidence_text",
    "captured_at", "retention_expires_at", "consent_method", "revoked_at",
    "revoked_by_keyword", "status",
]

MESSAGE_FIELDS = COMMON_VERSIONED + [
    "account_id", "campaign_id", "sender_number_id", "to_number",
    "consent_record_id", "body", "carrier_code", "segments", "queued_at",
    "queued_run_index", "failed_error_code", "status",
]

FEEDBACK_FIELDS = COMMON_APPEND + [
    "account_id", "campaign_id", "message_id", "kind", "keyword", "to_number",
    "status",
]

CHARGE_FIELDS = COMMON_APPEND + [
    "account_id", "kind", "reference_type", "reference_id", "amount_cents",
    "currency", "status",
]

SNAPSHOT_FIELDS = COMMON_APPEND + [
    "account_id", "campaign_id", "day_utc", "attempted", "delivered",
    "blocked", "spam", "delivery_rate_pct", "block_rate_bps", "spam_rate_bps",
]

OPSRUN_FIELDS = COMMON_APPEND + [
    "account_id", "run_index", "executed_at", "messages_dequeued",
    "messages_stale_cancelled", "recurring_fees_charged", "number_fees_charged",
]


def ser_account(e):
    return _project(e, ACCOUNT_FIELDS)


def ser_brand(e):
    return _project(e, BRAND_FIELDS)


def ser_campaign(e):
    return _project(e, CAMPAIGN_FIELDS)


def ser_number(e):
    return _project(e, NUMBER_FIELDS)


def ser_consent(e):
    return _project(e, CONSENT_FIELDS)


def ser_message(e):
    return _project(e, MESSAGE_FIELDS)


def ser_feedback(e):
    return _project(e, FEEDBACK_FIELDS)


def ser_charge(e):
    return _project(e, CHARGE_FIELDS)


def ser_snapshot(e):
    return _project(e, SNAPSHOT_FIELDS)


def ser_opsrun(e):
    return _project(e, OPSRUN_FIELDS)
