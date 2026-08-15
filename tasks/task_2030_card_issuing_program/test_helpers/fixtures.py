"""Composite setup helpers.

Each helper builds a multi-step scenario via PRD-declared endpoints, using
get_success_data so any setup failure surfaces as a clear "Setup step failed"
assertion rather than a confusing downstream error.

Every helper is self-contained: the harness restarts the server (empty DB,
clock reset to 2026-08-01T00:00:00Z) before every test, so helpers begin by
pinning the clock explicitly to make the scenario deterministic.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_account_payload,
    create_authorization_payload,
    create_bin_range_payload,
    create_mandate_ack_payload,
    create_mandate_payload,
    create_production_batch_payload,
    create_program_payload,
    create_reissue_campaign_payload,
    create_vendor_payload,
    issue_card_payload,
)
from .test_users import (
    TEST_USERS,
    make_cardholder_ops_headers,
    make_compliance_officer_headers,
    make_finance_controller_headers,
    make_operations_analyst_headers,
    make_platform_admin_headers,
    make_program_manager_headers,
)

_PM = TEST_USERS["program_manager_headers"]
_PA = TEST_USERS["platform_admin_headers"]
_CO = TEST_USERS["compliance_officer_headers"]
_OA = TEST_USERS["operations_analyst_headers"]
_FC = TEST_USERS["finance_controller_headers"]
_CH = TEST_USERS["cardholder_ops_headers"]


# ---------------------------------------------------------------------------
# Tier 1: clock + single-entity creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK_ISO) -> str:
    resp = api_client.set_clock(to_iso8601, _PA)
    data = get_success_data(resp)
    return data["current_utc"]


def create_program(
    program_code: str,
    *,
    product_class: str = "DEBIT_CONSUMER",
    network: str = "VISA",
    currency_code: str = "USD",
    daily_spend_cap_cents: int = 10_000_000,
) -> Dict[str, Any]:
    resp = api_client.create_program(
        create_program_payload(
            program_code=program_code,
            product_class=product_class,
            network=network,
            currency_code=currency_code,
            daily_spend_cap_cents=daily_spend_cap_cents,
        ),
        _PM,
    )
    return get_success_data(resp)


def create_bin_range(
    program_id: str,
    *,
    bin_prefix: str = "411111",
    range_size: int = 1000,
    effective_from: str = "2026-08-01T00:00:00Z",
    effective_until: str = "2030-12-31T23:59:59Z",
) -> Dict[str, Any]:
    resp = api_client.create_bin_range(
        program_id,
        create_bin_range_payload(
            bin_prefix=bin_prefix,
            range_size=range_size,
            effective_from=effective_from,
            effective_until=effective_until,
        ),
        _PM,
    )
    return get_success_data(resp)


def publish_program(program_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.publish_program(program_id, _PM))


def create_program_with_bin_and_publish(
    program_code: str,
    *,
    product_class: str = "DEBIT_CONSUMER",
    network: str = "VISA",
    currency_code: str = "USD",
    daily_spend_cap_cents: int = 10_000_000,
    bin_prefix: str = "411111",
    range_size: int = 1000,
    effective_from: str = "2026-08-01T00:00:00Z",
    effective_until: str = "2030-12-31T23:59:59Z",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a DRAFT program, add a BinRange, publish. Returns (program, bin_range)."""
    prog = create_program(
        program_code,
        product_class=product_class,
        network=network,
        currency_code=currency_code,
        daily_spend_cap_cents=daily_spend_cap_cents,
    )
    bin_range = create_bin_range(
        prog["id"],
        bin_prefix=bin_prefix,
        range_size=range_size,
        effective_from=effective_from,
        effective_until=effective_until,
    )
    prog = publish_program(prog["id"])
    return prog, bin_range


# ---------------------------------------------------------------------------
# Tier 2: account / card setup
# ---------------------------------------------------------------------------

def create_account(
    program_id: str,
    external_account_ref: str,
    *,
    account_class: str = "INDIVIDUAL",
    daily_spend_cap_cents: int = 100_000,
    credit_limit_cents: Optional[int] = None,
) -> Dict[str, Any]:
    payload_overrides: Dict[str, Any] = {
        "account_class": account_class,
        "daily_spend_cap_cents": daily_spend_cap_cents,
    }
    if credit_limit_cents is not None:
        payload_overrides["credit_limit_cents"] = credit_limit_cents
    resp = api_client.create_account(
        create_account_payload(program_id, external_account_ref, **payload_overrides),
        _PM,
    )
    return get_success_data(resp)


def activate_account(account_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.activate_account(account_id, _PM))


def create_open_account(
    program_id: str,
    external_account_ref: str,
    *,
    account_class: str = "INDIVIDUAL",
    daily_spend_cap_cents: int = 100_000,
    fund_cents: int = 0,
    credit_limit_cents: Optional[int] = None,
) -> Dict[str, Any]:
    acct = create_account(
        program_id,
        external_account_ref,
        account_class=account_class,
        daily_spend_cap_cents=daily_spend_cap_cents,
        credit_limit_cents=credit_limit_cents,
    )
    acct = activate_account(acct["id"])
    if fund_cents:
        acct = get_success_data(api_client.fund_account(acct["id"], fund_cents, _FC))
    return acct


def issue_card_for_account(
    account_id: str,
    *,
    expiry_month: int = 12,
    expiry_year: int = 2030,
    form_factor: str = "PHYSICAL",
    bin_range_id: Optional[str] = None,
) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {
        "expiry_month": expiry_month,
        "expiry_year": expiry_year,
        "form_factor": form_factor,
    }
    if bin_range_id is not None:
        overrides["bin_range_id"] = bin_range_id
    resp = api_client.issue_card(account_id, issue_card_payload(**overrides), _PM)
    return get_success_data(resp)


def set_card_pin(card_id: str, pin: str, user_id: str = "test-cardholder-ops-1") -> Dict[str, Any]:
    return get_success_data(api_client.set_pin(card_id, pin, make_cardholder_ops_headers(user_id)))


def get_pending_activation_token_value(card_id: str) -> str:
    resp = api_client.list_card_activation_tokens(card_id, _CH)
    tokens = get_success_data(resp)
    pending = [t for t in tokens if t.get("status") == "PENDING"]
    assert pending, f"Setup: expected a PENDING activation token for card {card_id}"
    return pending[0]["token_value"]


def activate_card(card_id: str, token_value: str,
                  user_id: str = "test-cardholder-ops-1") -> Dict[str, Any]:
    return get_success_data(
        api_client.activate_card(card_id, token_value, make_cardholder_ops_headers(user_id)),
    )


def create_active_card(
    account_id: str,
    *,
    pin: str = "1234",
    expiry_month: int = 12,
    expiry_year: int = 2030,
    form_factor: str = "PHYSICAL",
    bin_range_id: Optional[str] = None,
    user_id: str = "test-cardholder-ops-1",
) -> Dict[str, Any]:
    """Issue → set PIN → activate. Returns the ACTIVE card."""
    card = issue_card_for_account(
        account_id,
        expiry_month=expiry_month,
        expiry_year=expiry_year,
        form_factor=form_factor,
        bin_range_id=bin_range_id,
    )
    set_card_pin(card["id"], pin, user_id=user_id)
    token = get_pending_activation_token_value(card["id"])
    return activate_card(card["id"], token, user_id=user_id)


# ---------------------------------------------------------------------------
# Tier 3: full issuing scenario (program + bin + account + active card)
# ---------------------------------------------------------------------------

def setup_active_card_scenario(
    program_code: str,
    *,
    product_class: str = "DEBIT_CONSUMER",
    network: str = "VISA",
    program_daily_cap_cents: int = 10_000_000,
    account_daily_cap_cents: int = 100_000,
    fund_cents: int = 0,
    account_class: str = "INDIVIDUAL",
    credit_limit_cents: Optional[int] = None,
    pin: str = "1234",
    expiry_month: int = 12,
    expiry_year: int = 2030,
    form_factor: str = "PHYSICAL",
    clock_iso: str = DEFAULT_CLOCK_ISO,
    bin_prefix: str = "411111",
) -> Dict[str, Any]:
    """Pin clock → program (LIVE) → bin (ACTIVE) → account (OPEN, funded) → card (ACTIVE).

    Returns dict with keys: program, bin_range, account, card.
    """
    set_clock(clock_iso)
    prog, bin_range = create_program_with_bin_and_publish(
        program_code,
        product_class=product_class,
        network=network,
        daily_spend_cap_cents=program_daily_cap_cents,
        bin_prefix=bin_prefix,
    )
    acct = create_open_account(
        prog["id"],
        f"{program_code}-A1",
        account_class=account_class,
        daily_spend_cap_cents=account_daily_cap_cents,
        fund_cents=fund_cents,
        credit_limit_cents=credit_limit_cents,
    )
    card = create_active_card(
        acct["id"],
        pin=pin,
        expiry_month=expiry_month,
        expiry_year=expiry_year,
        form_factor=form_factor,
    )
    return {
        "program": prog,
        "bin_range": bin_range,
        "account": acct,
        "card": card,
    }


# ---------------------------------------------------------------------------
# Tier 4: vendor / batch setup
# ---------------------------------------------------------------------------

def create_vendor(
    vendor_code: str,
    *,
    capability_flags: Optional[List[str]] = None,
    daily_capacity_cards: int = 5000,
    supported_networks: Optional[List[str]] = None,
    is_active: bool = True,
) -> Dict[str, Any]:
    resp = api_client.create_vendor(
        create_vendor_payload(
            vendor_code=vendor_code,
            capability_flags=capability_flags or ["EMV_CHIP"],
            daily_capacity_cards=daily_capacity_cards,
            supported_networks=supported_networks or ["VISA"],
            is_active=is_active,
        ),
        _PA,
    )
    return get_success_data(resp)


def create_production_batch(
    program_id: str,
    vendor_id: str,
    *,
    scheduled_for_utc_date: str = "2026-08-15",
    requested_card_count: int = 100,
    unit_cost_cents: int = 100,
) -> Dict[str, Any]:
    resp = api_client.create_production_batch(
        program_id,
        create_production_batch_payload(
            vendor_id,
            scheduled_for_utc_date=scheduled_for_utc_date,
            requested_card_count=requested_card_count,
            unit_cost_cents=unit_cost_cents,
        ),
        _OA,
    )
    return get_success_data(resp)


def create_submitted_batch(
    program_id: str,
    vendor_id: str,
    *,
    scheduled_for_utc_date: str = "2026-08-15",
    requested_card_count: int = 100,
    unit_cost_cents: int = 100,
) -> Dict[str, Any]:
    batch = create_production_batch(
        program_id,
        vendor_id,
        scheduled_for_utc_date=scheduled_for_utc_date,
        requested_card_count=requested_card_count,
        unit_cost_cents=unit_cost_cents,
    )
    return get_success_data(api_client.submit_batch(batch["id"], _OA))


def create_in_production_batch(
    program_id: str,
    vendor_id: str,
    *,
    scheduled_for_utc_date: str = "2026-08-15",
    requested_card_count: int = 100,
    unit_cost_cents: int = 100,
) -> Dict[str, Any]:
    batch = create_submitted_batch(
        program_id,
        vendor_id,
        scheduled_for_utc_date=scheduled_for_utc_date,
        requested_card_count=requested_card_count,
        unit_cost_cents=unit_cost_cents,
    )
    return get_success_data(api_client.start_batch(batch["id"], _OA))


# ---------------------------------------------------------------------------
# Tier 4: mandate / ack setup
# ---------------------------------------------------------------------------

def create_mandate(
    mandate_code: str,
    *,
    network: str = "VISA",
    title: str = "Mandate",
    effective_at: str = "2026-09-01T00:00:00Z",
    compliance_deadline: str = "2026-12-01T00:00:00Z",
    severity: str = "REQUIRED",
) -> Dict[str, Any]:
    resp = api_client.create_mandate(
        create_mandate_payload(
            mandate_code=mandate_code,
            network=network,
            title=title,
            effective_at=effective_at,
            compliance_deadline=compliance_deadline,
            severity=severity,
        ),
        _CO,
    )
    return get_success_data(resp)


def create_mandate_ack(mandate_id: str, program_id: str,
                        implementation_notes: str = "implementation notes") -> Dict[str, Any]:
    resp = api_client.create_mandate_ack(
        mandate_id,
        create_mandate_ack_payload(program_id, implementation_notes=implementation_notes),
        _CO,
    )
    return get_success_data(resp)


def create_submitted_ack(
    mandate_id: str,
    program_id: str,
    submitter_user_id: str,
    implementation_notes: str = "implementation notes",
) -> Dict[str, Any]:
    """Create DRAFT ack then submit it as `submitter_user_id`. Returns SUBMITTED ack."""
    ack = create_mandate_ack(mandate_id, program_id, implementation_notes)
    resp = api_client.submit_mandate_ack(
        mandate_id, ack["id"], make_compliance_officer_headers(submitter_user_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: authorization-rule setup
# ---------------------------------------------------------------------------

def create_and_activate_rule(payload: Dict[str, Any]) -> Dict[str, Any]:
    rule = get_success_data(api_client.create_authorization_rule(payload, _CO))
    return get_success_data(
        api_client.activate_authorization_rule(rule["id"], rule["version"], _CO),
    )


# ---------------------------------------------------------------------------
# Tier 4: authorization + settlement helpers
# ---------------------------------------------------------------------------

def create_approved_auth(
    card_id: str,
    *,
    amount_cents: int = 1000,
    mcc: str = "5411",
    country_code: str = "US",
    user_id: str = "test-cardholder-ops-1",
) -> Dict[str, Any]:
    resp = api_client.create_authorization(
        card_id,
        create_authorization_payload(
            amount_cents=amount_cents, mcc=mcc, country_code=country_code,
        ),
        make_cardholder_ops_headers(user_id),
    )
    data = get_success_data(resp)
    assert data.get("decision") == "APPROVED", (
        f"Setup: expected APPROVED auth, got {data.get('decision')}"
    )
    return data


def settle_auth(auth_event_id: str, settled_amount_cents: int) -> Dict[str, Any]:
    resp = api_client.settle_authorization(auth_event_id, settled_amount_cents, _FC)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: reissue campaign helpers
# ---------------------------------------------------------------------------

def create_reissue_campaign(
    program_id: str,
    *,
    campaign_kind: str = "EXPIRY_SWEEP",
    scheduled_for: str = "2026-08-05T00:00:00Z",
    selection_filter: Optional[Dict[str, Any]] = None,
    targeted_unit_fee_cents: Optional[int] = None,
    blanket_unit_fee_cents: Optional[int] = None,
) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {
        "campaign_kind": campaign_kind,
        "scheduled_for": scheduled_for,
        "selection_filter": selection_filter or {},
    }
    if targeted_unit_fee_cents is not None:
        overrides["targeted_unit_fee_cents"] = targeted_unit_fee_cents
    if blanket_unit_fee_cents is not None:
        overrides["blanket_unit_fee_cents"] = blanket_unit_fee_cents
    resp = api_client.create_reissue_campaign(
        program_id, create_reissue_campaign_payload(**overrides), _OA,
    )
    return get_success_data(resp)
