"""Loaner units: the eligibility gate (tier and live contract), the
empty-pool fallback, the selector's serial tie-break, and the automatic
return on resolve.
"""

from test_helpers import (
    DISPATCHER,
    ApiErrorId,
    api_client,
    cancel_service_contract,
    create_service_request,
    dispatch_request,
    ensure_engineer,
    get_service_request,
    list_loaner_units,
    reserve_loaner,
    resolve_request,
    setup_loaner_scenario,
    validate_error,
)


def test_loaner_rejected_on_silver_tier(api):
    """PRD section 3.5: "the instrument must also carry a contract reading
    `ACTIVE` or `RENEWAL_DUE` whose tier is loaner-eligible — `GOLD` or
    `PLATINUM`. A request of the wrong type or severity, or an instrument
    without such a contract, is refused with `ERR_LOANER_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/loaner_requires_contract_active_and_tier
    """
    scene = setup_loaner_scenario(tier="SILVER", severity="HIGH",
                                  unit_serials=("LN-1",))
    response = api_client.reserve_loaner(scene["request"]["id"], headers=DISPATCHER)
    validate_error(response, ApiErrorId.ERR_LOANER_NOT_ELIGIBLE)
    units = list_loaner_units(status="AVAILABLE")
    assert [u["id"] for u in units] == [scene["units"][0]["id"]], (
        "the rejected reservation must not leak: the unit stays AVAILABLE"
    )


def test_loaner_rejected_without_live_contract(api):
    """PRD section 3.5: "A request of the wrong type or severity, or an
    instrument without such a contract, is refused with
    `ERR_LOANER_NOT_ELIGIBLE`."  Cancelling the only contract leaves the
    instrument with no live contract, and the gate still refuses.

    Design: Difficulty/cross_entity_state_dependency/loaner_requires_contract_active_and_tier
    """
    scene = setup_loaner_scenario(tier="SILVER", severity="HIGH",
                                  unit_serials=("LN-1",))
    cancel_service_contract(scene["contract"])
    second = create_service_request(
        scene["instrument"], scene["account"],
        request_type="BREAK_FIX", severity="HIGH",
    )
    response = api_client.reserve_loaner(second["id"], headers=DISPATCHER)
    validate_error(response, ApiErrorId.ERR_LOANER_NOT_ELIGIBLE)
    units = list_loaner_units(status="AVAILABLE")
    assert [u["id"] for u in units] == [scene["units"][0]["id"]]


def test_loaner_empty_pool_rejected(api):
    """PRD section 3.5: "Among units that are `AVAILABLE` and whose `model`
    equals the instrument's `model`, the selector picks the unit with the
    earliest `created_at`, breaking ties by `serial_number` ascending; when no
    unit qualifies the reservation fails with `ERR_NO_LOANER_AVAILABLE`."

    Design: Corner/cross_cutting_layers/loaner_empty_pool_rejected
    """
    scene = setup_loaner_scenario(
        tier="GOLD", severity="HIGH",
        unit_serials=("LN-OTHER",), unit_model="GC-200",
        instrument_model="SEQ-5000",
    )
    response = api_client.reserve_loaner(scene["request"]["id"], headers=DISPATCHER)
    validate_error(response, ApiErrorId.ERR_NO_LOANER_AVAILABLE)
    fresh = get_service_request(scene["request"])
    assert fresh["loaner_unit_id"] is None, "no reservation leaked"


def test_loaner_selector_serial_tiebreak(api):
    """PRD section 3.5: "the selector picks the unit with the earliest
    `created_at`, breaking ties by `serial_number` ascending".  Both units
    are registered at the same logical instant, so the created_at tie is
    broken by serial number: LN-100 wins over LN-200 even though LN-200 was
    registered first.

    Design: Corner/cross_cutting_layers/loaner_selector_serial_tiebreak
    """
    scene = setup_loaner_scenario(
        tier="GOLD", severity="HIGH", unit_serials=("LN-200", "LN-100")
    )
    reserved = reserve_loaner(scene["request"])
    by_serial = {u["serial_number"]: u["id"] for u in scene["units"]}
    assert reserved["loaner_unit_id"] == by_serial["LN-100"], (
        "created_at ties at the same logical instant; serial_number ASC decides"
    )


def test_loaner_auto_returns_on_resolve(api):
    """PRD section 3.5: "Resolution also returns any reserved loaner unit to
    `AVAILABLE` with a `version` increment on the unit" and "the
    `loaner_unit_id` is retained on the request even after the unit is
    returned, for audit."

    Design: Corner/state_machines/loaner_auto_returns_on_resolve
    """
    scene = setup_loaner_scenario(tier="GOLD", severity="HIGH",
                                  unit_serials=("LN-RET",))
    unit = scene["units"][0]
    reserved = reserve_loaner(scene["request"])
    assert reserved["loaner_unit_id"] == unit["id"]

    # Dispatch needs a non-empty eligible set: an ACTIVE engineer in the
    # account's territory holding the BREAK_FIX skill (PRD section 3.5).
    ensure_engineer(scene["account"], ["BREAK_FIX"])
    dispatched = dispatch_request(reserved)
    resolved = resolve_request(dispatched, hours_on_site=1, parts_cost_cents=0)
    assert resolved["loaner_unit_id"] == unit["id"], (
        "the loaner reference is retained on the request for audit"
    )
    units = list_loaner_units(model="SEQ-5000")
    assert units[0]["id"] == unit["id"]
    assert units[0]["status"] == "AVAILABLE", (
        "resolving the holding request returns the unit to AVAILABLE"
    )
