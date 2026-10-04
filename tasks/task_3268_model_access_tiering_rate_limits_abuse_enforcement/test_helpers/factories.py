"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Test Organization",
    "MODEL_SLUG": "claude-sonnet",
    "VERSION_TAG": "4-5",
    "PRICING": {
        "input_per_mtok_cents": 300,
        "output_per_mtok_cents": 1500,
        "cached_per_mtok_cents": 30,
    },
    "TOPUP_AMOUNT_CENTS": 1000000,
    "COMMITTED_TPM": 10000,
    "DEDICATED_CAPACITY_PCT": 50,
    "EFFECTIVE_AT": "2026-08-01T00:00:00Z",
    "EXPIRES_AT": "2027-08-01T00:00:00Z",
    "PERIOD_START": "2026-09-01T00:00:00Z",
    "PERIOD_END": "2026-09-02T00:00:00Z",
    "MINUTE_WINDOW_START": "2026-09-01T00:00:00Z",
}


def create_organization_payload(**overrides) -> dict:
    defaults = {"legal_name": DEFAULTS["LEGAL_NAME"]}
    defaults.update(overrides)
    return defaults


def create_payment_event_payload(organization_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "kind": "PREPAID_TOPUP",
        "amount_cents": DEFAULTS["TOPUP_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_model_version_payload(**overrides) -> dict:
    defaults = {
        "model_slug": DEFAULTS["MODEL_SLUG"],
        "version_tag": DEFAULTS["VERSION_TAG"],
        "pricing": dict(DEFAULTS["PRICING"]),
    }
    defaults.update(overrides)
    return defaults


def create_safety_evaluation_payload(**overrides) -> dict:
    defaults = {"capability_class": "STANDARD"}
    defaults.update(overrides)
    return defaults


def create_usage_record_payload(organization_id, model_version_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "model_version_id": model_version_id,
        "minute_window_start": DEFAULTS["MINUTE_WINDOW_START"],
        "requests": 1,
        "input_tokens": 10,
        "output_tokens": 0,
        "cached_tokens": 0,
    }
    defaults.update(overrides)
    return defaults


def create_queued_request_payload(organization_id, model_version_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "model_version_id": model_version_id,
        "requests_cost": 1,
        "tokens_cost": 100,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_line_payload(model_version_id, **overrides) -> dict:
    defaults = {
        "model_version_id": model_version_id,
        "kind": "INPUT_TOKENS",
        "quantity": 10000,
        "rate_per_mtok_cents": 300,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(organization_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_enterprise_agreement_payload(organization_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "committed_tpm": DEFAULTS["COMMITTED_TPM"],
        "dedicated_capacity_pct": DEFAULTS["DEDICATED_CAPACITY_PCT"],
        "effective_at": DEFAULTS["EFFECTIVE_AT"],
        "expires_at": DEFAULTS["EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_abuse_case_payload(organization_id, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "source": "MANUAL",
        "severity": "MEDIUM",
    }
    defaults.update(overrides)
    return defaults


def create_abuse_action_payload(expected_abuse_case_version, **overrides) -> dict:
    defaults = {
        "action_type": "WARN",
        "expected_abuse_case_version": expected_abuse_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(abuse_case_id, **overrides) -> dict:
    defaults = {"abuse_case_id": abuse_case_id}
    defaults.update(overrides)
    return defaults
