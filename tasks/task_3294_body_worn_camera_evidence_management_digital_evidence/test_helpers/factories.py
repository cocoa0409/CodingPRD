"""Payload factories — one per entity, input fields only."""

VALID_HASH = "a" * 64

DEFAULTS = {
    "AGENCY_NAME": "Metro PD",
    "POLICY_TRIGGERS": ["MANUAL"],
    "POLICY_TAGGING_REQUIRED": True,
    "POLICY_REVIEW_RATE": 0,
    "POLICY_SHARE_EXPIRY_DAYS": 30,
    "BADGE_NUMBER": "B-100",
    "OFFICER_NAME": "Ana Ruiz",
    "OFFICER_RANK": "OFFICER",
    "SERIAL_NUMBER": "SN-1",
    "DEVICE_MODEL": "AXON-B4",
    "TRIGGER_CODE": "MANUAL",
    "DURATION_SECONDS": 60,
    "SIZE_BYTES": 1048576,
    "RECORDED_AT": "2026-09-01T00:00:00Z",
    "CATEGORY": "INCIDENT",
    "CASE_NUMBER": "CN-1",
    "CASE_TITLE": "Case One",
    "REQUEST_REFERENCE": "PRR-1",
    "RECIPIENT_ROLE": "PROSECUTOR",
    "RECIPIENT_EMAIL": "da@county.gov",
    "AUTHORITY_REFERENCE": "SUBP-2027-01",
    "FISCAL_YEAR_START_MONTH": 1,
    "MONTHLY_BUDGET_CENTS": 10000,
    "COST_PER_GB_MONTH_CENTS": 1000,
    "ALERT_THRESHOLD_PCT": 80,
    "EFFECTIVE_FROM_MONTH": "2026-01",
}


def create_agency_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["AGENCY_NAME"]}
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "recording_triggers": list(DEFAULTS["POLICY_TRIGGERS"]),
        "tagging_required": DEFAULTS["POLICY_TAGGING_REQUIRED"],
        "supervisor_review_rate_pct": DEFAULTS["POLICY_REVIEW_RATE"],
        "default_share_expiry_days": DEFAULTS["POLICY_SHARE_EXPIRY_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_budget_plan_payload(**overrides) -> dict:
    defaults = {
        "fiscal_year_start_month": DEFAULTS["FISCAL_YEAR_START_MONTH"],
        "monthly_budget_cents": DEFAULTS["MONTHLY_BUDGET_CENTS"],
        "cost_per_gb_month_cents": DEFAULTS["COST_PER_GB_MONTH_CENTS"],
        "alert_threshold_pct": DEFAULTS["ALERT_THRESHOLD_PCT"],
        "effective_from_month": DEFAULTS["EFFECTIVE_FROM_MONTH"],
    }
    defaults.update(overrides)
    return defaults


def create_officer_payload(**overrides) -> dict:
    defaults = {
        "badge_number": DEFAULTS["BADGE_NUMBER"],
        "full_name": DEFAULTS["OFFICER_NAME"],
        "rank": DEFAULTS["OFFICER_RANK"],
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    defaults = {
        "serial_number": DEFAULTS["SERIAL_NUMBER"],
        "model": DEFAULTS["DEVICE_MODEL"],
    }
    defaults.update(overrides)
    return defaults


def create_recording_payload(device_id, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "trigger_code": DEFAULTS["TRIGGER_CODE"],
        "duration_seconds": DEFAULTS["DURATION_SECONDS"],
        "size_bytes": DEFAULTS["SIZE_BYTES"],
        "recorded_at": DEFAULTS["RECORDED_AT"],
        "content_hash_sha256": VALID_HASH,
        "category": DEFAULTS["CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(lead_officer_id, **overrides) -> dict:
    defaults = {
        "case_number": DEFAULTS["CASE_NUMBER"],
        "title": DEFAULTS["CASE_TITLE"],
        "lead_officer_id": lead_officer_id,
    }
    defaults.update(overrides)
    return defaults


def create_redaction_job_payload(**overrides) -> dict:
    defaults = {
        "request_reference": DEFAULTS["REQUEST_REFERENCE"],
        "scope_face": True,
        "scope_audio": False,
        "passes": "SINGLE_PASS",
    }
    defaults.update(overrides)
    return defaults


def create_share_grant_payload(expected_case_version, **overrides) -> dict:
    defaults = {
        "recipient_role": DEFAULTS["RECIPIENT_ROLE"],
        "recipient_email": DEFAULTS["RECIPIENT_EMAIL"],
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_legal_hold_payload(**overrides) -> dict:
    defaults = {
        "scope_type": "RECORDING",
        "authority_reference": DEFAULTS["AUTHORITY_REFERENCE"],
    }
    defaults.update(overrides)
    return defaults
