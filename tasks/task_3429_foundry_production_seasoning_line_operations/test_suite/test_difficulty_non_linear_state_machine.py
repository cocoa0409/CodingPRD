"""Difficulty queue: non-linear state machines — the MeltBatch chemistry
adjustment cycle and the CastingUnit rework loop with its hard cap."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    certify_melt,
    charge_melt,
    disposition_report,
    get_melt,
    get_order,
    get_success_data,
    get_unit,
    inspect_unit_defect,
    record_chemistry,
    rework_unit_via_defect,
    setup_charging_melt,
    setup_shaken_units,
    validate_error,
)

_QI = TEST_USERS["quality_inspector_headers"]


def _adjusted_melt():
    """Charge -> out-of-spec reading (CE 4.49) -> ORDER_ADJUSTMENT."""
    ctx = setup_charging_melt()
    batch_id = ctx["melt"]["id"]
    charge_melt(batch_id)
    record_chemistry(batch_id, carbon_pct=3.45, silicon_pct=3.10,
                     phosphorus_pct=0.020)
    return ctx, batch_id


def test_chemistry_adjustment_cycle_orders_adjustment(api):
    """PRD §3.3: "computes `carbon_equivalent` as `carbon_pct` plus one third of the
    sum of `silicon_pct` and `phosphorus_pct`, rounded half-up to 2 decimal places."
    PRD §3.3: "A decision of `ORDER_ADJUSTMENT` instead moves the batch to
    `ADJUSTMENT` and increments `adjustment_count` by 1, with no further spec
    evaluation"
    3.45 + (3.10 + 0.020)/3 == 4.49, outside [3.90, 4.30], so the inspector loops
    the batch instead of certifying.

    Design: Difficulty/non_linear_state_machine/melt_chemistry_adjustment_cycle
    """
    _, batch_id = _adjusted_melt()
    melt = get_melt(batch_id)
    assert melt["carbon_equivalent"] == pytest.approx(4.49, abs=1e-9)
    melt = certify_melt(batch_id, decision="ORDER_ADJUSTMENT")
    assert melt["state"] == "ADJUSTMENT"
    assert melt["adjustment_count"] == 1


def test_adjustment_then_recertify_reaches_certified(api):
    """PRD §3.3: "the adjustment cycle then loops — `ADJUSTMENT` accepts only a
    supplemental charge, which returns the batch to `MELTING`, from which new
    readings re-enter `CHEMISTRY_CHECK` — and there is no cap on the number of
    cycles."
    PRD §3.3: "A certified batch moves to `CERTIFIED` and records `certified_by`."
    After a 10-lb alloy supplement (alloy 90 -> 100) the second reading computes
    CE 4.30 — exactly the inclusive upper bound — and CERTIFY succeeds.

    Design: Difficulty/non_linear_state_machine/melt_chemistry_adjustment_cycle
    """
    _, batch_id = _adjusted_melt()
    certify_melt(batch_id, decision="ORDER_ADJUSTMENT")
    charge_melt(batch_id, pig_iron_lbs=0, scrap_steel_lbs=0, returns_lbs=0,
                alloy_lbs=10)
    record_chemistry(batch_id)  # 3.30 + (2.99 + 0.010)/3 == 4.30
    melt = certify_melt(batch_id, decision="CERTIFY")
    assert melt["state"] == "CERTIFIED"
    assert melt["adjustment_count"] == 1
    assert melt["carbon_equivalent"] == pytest.approx(4.30, abs=1e-9)
    assert melt["certified_by"] == "qi-1"
    assert melt["alloy_lbs"] == 100


def _unit_at_rework_limit():
    """One unit reworked twice (rework_count 2) with a third OPEN report."""
    ctx = setup_shaken_units(num_units=1)
    unit_id = ctx["unit_ids"][0]
    rework_unit_via_defect(unit_id, defect_type="POROSITY", severity="MINOR")
    rework_unit_via_defect(unit_id, defect_type="COLD_SHUT", severity="MAJOR")
    _, report_id = inspect_unit_defect(unit_id, defect_type="MISRUN",
                                       severity="MAJOR")
    return ctx, unit_id, report_id


def test_third_rework_disposition_rejected(api):
    """PRD §3.5: "and requires the unit's `rework_count` to be below 2, because a
    unit may carry at most two completed rework dispositions; a third rework attempt
    is rejected with `ERR_REWORK_LIMIT_EXCEEDED` (HTTP 422)."
    The rejected third REWORK leaves the unit in DEFECT_REVIEW with the report
    still OPEN.

    Design: Difficulty/non_linear_state_machine/casting_unit_rework_cycle_limit_rejected
    """
    _, unit_id, report_id = _unit_at_rework_limit()
    resp = api.disposition_defect_report(report_id, {"disposition": "REWORK"}, _QI)
    validate_error(resp, ApiErrorId.ERR_REWORK_LIMIT_EXCEEDED)
    unit = get_unit(unit_id)
    assert unit["state"] == "DEFECT_REVIEW"
    assert unit["rework_count"] == 2
    reports = get_success_data(api.list_unit_defect_reports(unit_id, _QI))
    report = next(r for r in reports if r["id"] == report_id)
    assert report["status"] == "OPEN"


def test_scrap_remains_available_at_rework_limit(api):
    """PRD §3.5: "A `disposition` of `SCRAP` has no severity precondition and moves
    the unit to `SCRAPPED`."
    PRD §3.5: "The order's `scrapped_units` and `defect_scrapped_units` each
    increment by 1, and the order's `scrap_weighted_units` accumulates 1.5 for a
    unit scrapped after rework but 1.0 for a unit never reworked."
    After the failed third REWORK, the SCRAP branch still closes the loop: the unit
    is SCRAPPED after rework and weighs 1.5 into the scrap index.

    Design: Difficulty/non_linear_state_machine/casting_unit_rework_cycle_limit_rejected
    """
    ctx, unit_id, report_id = _unit_at_rework_limit()
    resp = api.disposition_defect_report(report_id, {"disposition": "REWORK"}, _QI)
    validate_error(resp, ApiErrorId.ERR_REWORK_LIMIT_EXCEEDED)
    disposition_report(report_id, "SCRAP")
    unit = get_unit(unit_id)
    assert unit["state"] == "SCRAPPED"
    assert unit["scrapped_after_rework"] is True
    assert unit["scrap_reason"] == "DEFECT"
    order = get_order(ctx["order"]["id"])
    assert order["scrap_weighted_units"] == pytest.approx(1.5, abs=1e-9)
