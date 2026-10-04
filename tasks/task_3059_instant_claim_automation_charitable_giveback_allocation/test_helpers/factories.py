"""Payload factories — one per creatable resource, input fields only."""

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_rate_filing_payload(**overrides) -> dict:
    defaults = {
        "state_code": "TX",
        "max_flat_fee_pct": 0.30,
        "max_flat_fee_cap_cents": 90000,
        "filing_mode": "PCT_OF_PREMIUM",
    }
    defaults.update(overrides)
    return defaults


def create_fee_config_payload(**overrides) -> dict:
    defaults = {
        "state_code": "TX",
        "filing_id": "",  # caller must supply a real filing id
        "flat_fee_pct": 0.20,
        "flat_fee_cents": 90000,
    }
    defaults.update(overrides)
    return defaults


def create_treaty_payload(**overrides) -> dict:
    defaults = {"name": "QS-75", "quota_share_pct": 0.75}
    defaults.update(overrides)
    return defaults


def create_cause_payload(**overrides) -> dict:
    defaults = {"name": f"Cause {_next()}"}
    defaults.update(overrides)
    return defaults


def create_cohort_payload(**overrides) -> dict:
    defaults = {"cohort_year": 2026, "cause_id": ""}
    defaults.update(overrides)
    return defaults


def create_policyholder_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "email": f"policyholder-{n}@example.com",
        "full_name": f"Policy Holder {n}",
        "state_code": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(**overrides) -> dict:
    defaults = {"coverage_amount_cents": 500000, "premium_cents": 100000}
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "quote_id": "",
        "checkout_velocity_seconds": 60,
        "device_reuse_count": 0,
        "answers_ipa_acknowledged": True,
    }
    defaults.update(overrides)
    return defaults


def create_bind_payload(**overrides) -> dict:
    defaults = {
        "checkout_velocity_seconds": 60,
        "device_reuse_count": 0,
        "answers_ipa_acknowledged": True,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "policy_id": "",
        "video_statement_ref": "vid-statement",
        "claimed_amount_cents": 1000,
        "fraud_score": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_premium_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 100000}
    defaults.update(overrides)
    return defaults


def create_appeal_payload(**overrides) -> dict:
    defaults = {"statement": "please review this denial"}
    defaults.update(overrides)
    return defaults
