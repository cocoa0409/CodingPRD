"""Difficulty queue: compensating invariants — allocation create/cancel
conserving inventory units, and pour/defect-scrap conserving accounted iron."""
import pytest

from test_helpers import (
    assert_iron_mass_conserved,
    cancel_allocation,
    confirm_allocation,
    create_allocation,
    get_allocation,
    get_inventory_record,
    get_melt,
    get_unit,
    inspect_unit_defect,
    disposition_report,
    setup_inventory_with_stock,
    setup_poured_units,
    shakeout,
)


def _reserve_confirm_ctx():
    """10 units on hand; allocation of 4 created then CONFIRMED (ship week 2027,
    outside the product's peak window so no freeze applies)."""
    ctx = setup_inventory_with_stock(num_units=10)
    record_id = ctx["inventory_record"]["id"]
    allocation = create_allocation(record_id, allocated_qty=4,
                                   ship_week="2027-01-11")
    confirm_allocation(allocation["id"])
    return ctx, record_id, allocation


def test_reserve_and_confirm_move_only_reserved_units(api):
    """PRD §3.8: "Only three acts change `on_hand_units`: a seasoning release adds
    its `unit_count`, an allocation ship subtracts its `allocated_qty`, and an
    outlet sale subtracts its `qty`. Only three acts change `reserved_units`: an
    allocation create adds its `allocated_qty`, an allocation cancel subtracts it,
    and an allocation ship subtracts it."
    Create + confirm: on_hand stays 10, reserved goes 0 -> 4, shipped stays 0.

    Design: Difficulty/compensating_invariant/inventory_reserve_cancel_roundtrip_conserves_units
    """
    _, record_id, _ = _reserve_confirm_ctx()
    record = get_inventory_record(record_id)
    assert record["on_hand_units"] == 10
    assert record["reserved_units"] == 4
    assert record["available_units"] == 6
    assert record["shipped_units"] == 0


def test_compensating_cancel_restores_exact_prior_state(api):
    """PRD §3.8: "Consequently a create followed by a cancel of the same allocation
    leaves both `on_hand_units` and `reserved_units` exactly as before the pair."
    After the cancel: on_hand 10, reserved 0, available 10, shipped 0, allocation
    CANCELLED.

    Design: Difficulty/compensating_invariant/inventory_reserve_cancel_roundtrip_conserves_units
    """
    _, record_id, allocation = _reserve_confirm_ctx()
    cancel_allocation(allocation["id"])
    record = get_inventory_record(record_id)
    assert record["on_hand_units"] == 10
    assert record["reserved_units"] == 0
    assert record["available_units"] == 10
    assert record["shipped_units"] == 0
    assert get_allocation(allocation["id"])["status"] == "CANCELLED"


def _poured_ten_ctx():
    return setup_poured_units(num_units=10, order_overrides={"planned_quantity": 30})


def test_pour_debits_iron_ledger_conserving_mass(api):
    """PRD §3.3: "The tap computes `slag_loss_lbs` as `tapped_lbs` multiplied by
    0.03, rounded half-up to 2 decimal places, and sets `remaining_iron_lbs` to
    `tapped_lbs` minus `slag_loss_lbs`"
    PRD §3.3: "at every observable moment, `tapped_lbs` equals `poured_lbs` plus
    `slag_loss_lbs` plus `remaining_iron_lbs`."
    Tap 2010 -> slag 60.3, remaining 1949.7; pour 10 x 128 oz == 80.0 lbs ->
    remaining 1869.7; 80.0 + 60.3 + 1869.7 == 2010.0.

    Design: Difficulty/compensating_invariant/pour_and_scrap_conserve_iron_mass
    """
    ctx = _poured_ten_ctx()
    melt = get_melt(ctx["melt"]["id"])
    assert melt["tapped_lbs"] == pytest.approx(2010.0, abs=1e-9)
    assert melt["slag_loss_lbs"] == pytest.approx(60.3, abs=1e-9)
    assert melt["poured_lbs"] == pytest.approx(80.0, abs=1e-9)
    assert melt["remaining_iron_lbs"] == pytest.approx(1869.7, abs=1e-9)
    assert_iron_mass_conserved(melt)


def test_defect_scrap_recredits_iron_as_returns(api):
    """PRD §3.3: "When a unit poured from this batch is later scrapped by defect
    disposition, the batch's `returns_credit_lbs` accumulates that unit's
    `pour_weight_oz` divided by 16.0 and rounded half-up to 2 decimal places — the
    scrapped iron returns to the ledger as credit for future charge mixes, so a
    pour followed by a defect-scrap of one of its units conserves accounted iron
    mass."
    One 128-oz unit scrapped -> returns_credit_lbs 8.0 while the pour-side ledger
    still conserves.

    Design: Difficulty/compensating_invariant/pour_and_scrap_conserve_iron_mass
    """
    ctx = _poured_ten_ctx()
    unit_id = ctx["unit_ids"][0]
    # Unit must be shaken out and defected before it can be scrapped.
    shakeout(ctx["mold"]["id"])
    _, report_id = inspect_unit_defect(unit_id, defect_type="POROSITY",
                                       severity="MINOR")
    disposition_report(report_id, "SCRAP")
    melt = get_melt(ctx["melt"]["id"])
    assert melt["returns_credit_lbs"] == pytest.approx(8.0, abs=1e-9)
    assert_iron_mass_conserved(melt)
    assert get_unit(unit_id)["scrap_reason"] == "DEFECT"
