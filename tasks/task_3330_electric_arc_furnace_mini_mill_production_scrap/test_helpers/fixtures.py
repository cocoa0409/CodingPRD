"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, and uses get_success_data() so setup failures surface as clear
'Setup failed' errors. Sequential setup calls embed a monotonic counter in
human-facing unique-per-mill fields (heat_number, grade_code) so recipes that
stand up several heats/grades in one mill do not collide on uniqueness.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_mill_payload, publish_index_payload, create_contract_payload,
    record_lot_payload, create_grade_payload, create_heat_payload,
    create_sheet_payload, create_campaign_payload, create_account_payload,
    create_order_payload, create_window_payload, declare_event_payload,
    grant_waiver_payload, create_scorecard_payload,
)
from .test_users import TEST_USERS

_COUNTER = itertools.count(1)

PM = TEST_USERS["plant_manager_headers"]
MO = TEST_USERS["mill_operator_headers"]
SCH = TEST_USERS["scheduler_headers"]
MET = TEST_USERS["metallurgist_headers"]
PO = TEST_USERS["procurement_officer_headers"]
AM = TEST_USERS["account_manager_headers"]
QE = TEST_USERS["quality_engineer_headers"]
ED = TEST_USERS["energy_dispatcher_headers"]


def _u(tag: str) -> str:
    return f"{tag}-{next(_COUNTER)}"


def set_clock(current_utc="2026-09-10T00:00:00Z"):
    resp = api_client.set_clock({"current_utc": current_utc}, PM)
    return get_success_data(resp)


def make_mill(**overrides) -> dict:
    resp = api_client.create_mill(create_mill_payload(**overrides), PM)
    return get_success_data(resp)


def publish_index(mill_id, **overrides) -> dict:
    resp = api_client.publish_index(mill_id, publish_index_payload(**overrides), PM)
    return get_success_data(resp)


def make_contract(mill_id, **overrides) -> dict:
    resp = api_client.create_contract(mill_id, create_contract_payload(**overrides), PO)
    return get_success_data(resp)


def make_lot(mill_id, contract_id, **overrides) -> dict:
    resp = api_client.record_lot(mill_id, contract_id, record_lot_payload(**overrides), PO)
    return get_success_data(resp)


def make_grade(mill_id, **overrides) -> dict:
    overrides.setdefault("grade_code", _u("GR"))
    resp = api_client.create_grade(mill_id, create_grade_payload(**overrides), MET)
    return get_success_data(resp)


def make_heat(mill_id, grade_id, **overrides) -> dict:
    overrides.setdefault("heat_number", _u("H"))
    payload = create_heat_payload(**overrides)
    payload["grade_id"] = grade_id
    resp = api_client.create_heat(mill_id, payload, MO)
    return get_success_data(resp)


def apply_charge(mill_id, heat_id, lot_id, tons) -> dict:
    resp = api_client.apply_charge(mill_id, heat_id, {"scrap_lot_id": lot_id, "tons": tons}, MO)
    return get_success_data(resp)


def make_sheet(mill_id, heat_id, **overrides) -> dict:
    resp = api_client.create_sheet(mill_id, heat_id, create_sheet_payload(**overrides), MET)
    return get_success_data(resp)


def confirm_sheet(mill_id, heat_id, sheet_id) -> dict:
    resp = api_client.confirm_sheet(mill_id, heat_id, sheet_id, MET)
    return get_success_data(resp)


def make_campaign(mill_id, **overrides) -> dict:
    overrides.setdefault("name", _u("Camp"))
    resp = api_client.create_campaign(mill_id, create_campaign_payload(**overrides), SCH)
    return get_success_data(resp)


def make_account(mill_id, **overrides) -> dict:
    overrides.setdefault("name", _u("Acct"))
    resp = api_client.create_account(mill_id, create_account_payload(**overrides), AM)
    return get_success_data(resp)


def make_order(mill_id, account_id, grade_id, **overrides) -> dict:
    payload = create_order_payload(**overrides)
    payload["grade_id"] = grade_id
    resp = api_client.create_order(mill_id, account_id, payload, AM)
    return get_success_data(resp)


def confirm_order(mill_id, account_id, order) -> dict:
    """Confirm using the order's current version (OCC field per PRD §2.8)."""
    resp = api_client.confirm_order(
        mill_id, account_id, order["id"],
        {"expected_order_version": order["version"]}, AM,
    )
    return get_success_data(resp)


def make_window(mill_id, **overrides) -> dict:
    overrides.setdefault("label", _u("WIN"))
    resp = api_client.create_window(mill_id, create_window_payload(**overrides), ED)
    return get_success_data(resp)


def make_event(mill_id, **overrides) -> dict:
    resp = api_client.declare_event(mill_id, declare_event_payload(**overrides), ED)
    return get_success_data(resp)


def activate_event(mill_id, event_id) -> dict:
    resp = api_client.activate_event(mill_id, event_id, ED)
    return get_success_data(resp)


def release_event(mill_id, event_id) -> dict:
    resp = api_client.release_event(mill_id, event_id, ED)
    return get_success_data(resp)


def grant_waiver(mill_id, **overrides) -> dict:
    resp = api_client.grant_waiver(mill_id, grant_waiver_payload(**overrides), ED)
    return get_success_data(resp)


def make_scorecard(mill_id, **overrides) -> dict:
    resp = api_client.create_scorecard(mill_id, create_scorecard_payload(**overrides), PM)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3: hierarchy + lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_supply_pool(mill_id, price=39000, committed=100, lots=None, **contract_overrides):
    """Create one FIXED contract with its receipt lots.

    lots: list of dicts passed to make_lot (received_on/tons_received/...).
    Returns (contract, [lot, ...]).
    """
    contract = make_contract(
        mill_id, contract_price_cents=price, committed_tons=committed, **contract_overrides
    )
    made = [make_lot(mill_id, contract["id"], **lot) for lot in (lots or [{}])]
    return contract, made


def setup_charged_heat(mill_id, grade_id, lot_id, charge_tons, tap_at="2026-09-15T12:00:00Z",
                       target_tap_weight_tons=None, **heat_overrides):
    """Heat created and charged once -> CHARGED. Returns (heat, line)."""
    heat = make_heat(
        mill_id, grade_id, planned_tap_at=tap_at,
        target_tap_weight_tons=target_tap_weight_tons if target_tap_weight_tons is not None else charge_tons,
        **heat_overrides,
    )
    line = apply_charge(mill_id, heat["id"], lot_id, charge_tons)
    return heat, line


def setup_cast_heat(mill_id, grade_id, lot_id, charge_tons, tap_at, sheet_chem=None):
    """Full lifecycle to CAST: charge -> sheet -> confirm -> tap -> cast."""
    heat, _line = setup_charged_heat(mill_id, grade_id, lot_id, charge_tons, tap_at=tap_at)
    sheet = make_sheet(mill_id, heat["id"], **(sheet_chem or {}))
    confirm_sheet(mill_id, heat["id"], sheet["id"])
    get_success_data(api_client.tap_heat(mill_id, heat["id"], MO))
    cast = get_success_data(api_client.cast_heat(mill_id, heat["id"], MO))
    heat = get_success_data(api_client.get_heat(mill_id, heat["id"], PM))
    return heat


def commit_campaign(mill_id, campaign_id):
    """Commit with the campaign's current version (OCC field per PRD §2.8)."""
    camp = get_success_data(api_client.get_campaign(mill_id, campaign_id, SCH))
    return get_success_data(
        api_client.commit_campaign(mill_id, campaign_id,
                                   {"expected_campaign_version": camp["version"]}, SCH)
    )


def get_heat(mill_id, heat_id) -> dict:
    return get_success_data(api_client.get_heat(mill_id, heat_id, PM))


def get_lot(mill_id, lot_id) -> dict:
    return get_success_data(api_client.get_lot(mill_id, lot_id, PO))


def get_contract(mill_id, contract_id) -> dict:
    return get_success_data(api_client.get_contract(mill_id, contract_id, PO))


def get_scorecard(mill_id, scorecard_id) -> dict:
    return get_success_data(api_client.get_scorecard(mill_id, scorecard_id, PM))


def get_mill(mill_id) -> dict:
    return get_success_data(api_client.get_mill(mill_id, PM))


def get_account(mill_id, account_id) -> dict:
    return get_success_data(api_client.get_account(mill_id, account_id, AM))


def get_order(mill_id, order_id) -> dict:
    return get_success_data(api_client.get_order(mill_id, order_id, AM))


def get_sheet(mill_id, heat_id) -> dict:
    """Return the heat's single sheet row (the sheets list holds 0 or 1 rows)."""
    data, _meta = validate_paginated(api_client.list_sheets(mill_id, heat_id, MET))
    assert len(data) == 1, "expected exactly one meltdown sheet row"
    return data[0]


def get_window(mill_id, window_id) -> dict:
    return get_success_data(api_client.get_window(mill_id, window_id, ED))


def get_event(mill_id, event_id) -> dict:
    return get_success_data(api_client.get_event(mill_id, event_id, ED))
