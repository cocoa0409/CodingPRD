"""Payload factories - one per entity, input fields only."""

from . import constants as c

DEFAULTS = {
    "COMMUNITY_NAME": "C1",
    "STATE_CODE": "TX",
    "POLICY": "STANDARD",
    "LOT_NUMBER": "L1",
    "ADDRESS": "1 Elm",
    "BUYER_NAME": "Ada",
    "BUYER_EMAIL": "ada@x.com",
    "APPLICATION_NUMBER": "APP-1",
    "COMMITMENT_CODE": "FC1",
    "INVESTOR_NAME": "Fannie",
    "ESTIMATED_COMPLETION_ISO": "2026-10-01T00:00:00Z",
    "ADVERTISED_RATE_EXPIRES_ISO": "2027-01-01T00:00:00Z",
    "COMMITMENT_START_ISO": "2026-09-01T00:00:00Z",
    "COMMITMENT_END_ISO": "2030-01-01T00:00:00Z",
}


def community_payload(
    name=None,
    state_code=None,
    incentive_policy_code=None,
    price_reduction_cap_cents=None,
    closing_cost_cap_cents=None,
    rate_buydown_cap_cents=None,
    **overrides,
):
    """New-community body. ``capture_rate_target_bps`` is left out so the
    declared default applies unless a caller passes it explicitly."""
    payload = {
        "name": name or DEFAULTS["COMMUNITY_NAME"],
        "state_code": state_code or DEFAULTS["STATE_CODE"],
        "incentive_policy_code": incentive_policy_code or DEFAULTS["POLICY"],
        "price_reduction_cap_cents": (
            c.STANDARD_CAPS["price_reduction_cap_cents"]
            if price_reduction_cap_cents is None else price_reduction_cap_cents
        ),
        "closing_cost_cap_cents": (
            c.STANDARD_CAPS["closing_cost_cap_cents"]
            if closing_cost_cap_cents is None else closing_cost_cap_cents
        ),
        "rate_buydown_cap_cents": (
            c.STANDARD_CAPS["rate_buydown_cap_cents"]
            if rate_buydown_cap_cents is None else rate_buydown_cap_cents
        ),
    }
    payload.update(overrides)
    return payload


def home_site_payload(
    lot_number=None,
    address=None,
    base_price_cents=None,
    construction_stage="DRYWALL",
    estimated_completion_iso=None,
    advertised_rate_bps=None,
    advertised_rate_expires_iso=None,
    **overrides,
):
    payload = {
        "lot_number": lot_number or DEFAULTS["LOT_NUMBER"],
        "address": address or DEFAULTS["ADDRESS"],
        "base_price_cents": (
            c.DEFAULT_BASE_PRICE_CENTS if base_price_cents is None else base_price_cents
        ),
        "construction_stage": construction_stage,
        "estimated_completion_iso": estimated_completion_iso or DEFAULTS["ESTIMATED_COMPLETION_ISO"],
        "advertised_rate_bps": (
            c.DEFAULT_ADVERTISED_RATE_BPS if advertised_rate_bps is None else advertised_rate_bps
        ),
        "advertised_rate_expires_iso": (
            advertised_rate_expires_iso or DEFAULTS["ADVERTISED_RATE_EXPIRES_ISO"]
        ),
    }
    payload.update(overrides)
    return payload


def buyer_payload(full_name=None, email=None, state_code=None, **overrides):
    payload = {
        "full_name": full_name or DEFAULTS["BUYER_NAME"],
        "email": email or DEFAULTS["BUYER_EMAIL"],
        "state_code": state_code or DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def contract_payload(
    buyer_id,
    purchase_price_cents=None,
    earnest_money_cents=None,
    **overrides,
):
    payload = {
        "buyer_id": buyer_id,
        "purchase_price_cents": (
            c.DEFAULT_PURCHASE_PRICE_CENTS
            if purchase_price_cents is None else purchase_price_cents
        ),
        "earnest_money_cents": (
            c.DEFAULT_EARNEST_MONEY_CENTS if earnest_money_cents is None else earnest_money_cents
        ),
    }
    payload.update(overrides)
    return payload


def forward_commitment_payload(
    commitment_code=None,
    investor_name=None,
    committed_rate_bps=None,
    committed_units=10,
    commitment_start_iso=None,
    commitment_end_iso=None,
    **overrides,
):
    payload = {
        "commitment_code": commitment_code or DEFAULTS["COMMITMENT_CODE"],
        "investor_name": investor_name or DEFAULTS["INVESTOR_NAME"],
        "committed_rate_bps": (
            c.DEFAULT_COMMITTED_RATE_BPS if committed_rate_bps is None else committed_rate_bps
        ),
        "committed_units": committed_units,
        "commitment_start_iso": commitment_start_iso or DEFAULTS["COMMITMENT_START_ISO"],
        "commitment_end_iso": commitment_end_iso or DEFAULTS["COMMITMENT_END_ISO"],
    }
    payload.update(overrides)
    return payload


def loan_application_payload(
    lender_entity_code="AFFILIATED_LENDER",
    application_number=None,
    qualifying_income_cents=None,
    monthly_debt_cents=None,
    **overrides,
):
    payload = {
        "lender_entity_code": lender_entity_code,
        "application_number": application_number or DEFAULTS["APPLICATION_NUMBER"],
        "qualifying_income_cents": (
            c.DEFAULT_QUALIFYING_INCOME_CENTS
            if qualifying_income_cents is None else qualifying_income_cents
        ),
        "monthly_debt_cents": (
            c.DEFAULT_MONTHLY_DEBT_CENTS if monthly_debt_cents is None else monthly_debt_cents
        ),
    }
    payload.update(overrides)
    return payload


def rate_lock_payload(
    commitment_id,
    lock_rate_bps=None,
    lock_days=180,
    expected_application_version=1,
    **overrides,
):
    payload = {
        "commitment_id": commitment_id,
        "lock_rate_bps": (
            c.DEFAULT_LOCK_RATE_BPS if lock_rate_bps is None else lock_rate_bps
        ),
        "lock_days": lock_days,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def incentive_allocation_payload(bucket, requested_cents, expected_contract_version, **overrides):
    payload = {
        "bucket": bucket,
        "requested_cents": requested_cents,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def buydown_record_payload(allocation_id, gross_buydown_cents, expected_contract_version, **overrides):
    payload = {
        "allocation_id": allocation_id,
        "gross_buydown_cents": gross_buydown_cents,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def deposit_forfeiture_payload(statute_class, expected_contract_version, **overrides):
    payload = {
        "statute_class": statute_class,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload