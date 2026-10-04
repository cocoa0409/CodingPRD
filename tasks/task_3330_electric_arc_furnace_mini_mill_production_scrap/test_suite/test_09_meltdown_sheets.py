"""Meltdown sheet lifecycle: revision cycle, confirm cascade, out-of-spec,
immutability, system-field smuggling (PRD §3.5)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    make_mill, make_grade, make_heat, apply_charge, make_sheet, confirm_sheet,
    setup_supply_pool, setup_charged_heat, get_heat, get_sheet,
)

MET = TEST_USERS["metallurgist_headers"]
MO = TEST_USERS["mill_operator_headers"]


def _charged_heat_setup(lot_tons=50, charge_tons=8, grade_overrides=None):
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": lot_tons, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GR40", **(grade_overrides or {}))
    heat, line = setup_charged_heat(mill["id"], grade["id"], lots[0]["id"], charge_tons)
    return mill, lots[0], grade, heat


def test_meltdown_sheet_revision_cycle_alternates_and_counts():
    """PRD §3.5: "Sheets live in a cyclic revision loop: while the sheet is
    `RECORDED` or `REVISED` and the heat is still `CHARGED`, a revision replaces the
    chemistry, recomputes `chem_ok`, increments `revision_no` by 1, and bumps the
    sheet's `version`. Each revision call counts one revision regardless of the
    `RECORDED`-to-`REVISED` ping-pong — the status alternates with each revise
    (`RECORDED → REVISED`, then `REVISED → RECORDED`, and so on) while `revision_no`
    climbs monotonically."

    Design: Difficulty/non_linear_state_machine/meltdown_sheet_revision_cycle
    """
    mill, lot, grade, heat = _charged_heat_setup()
    sheet = make_sheet(mill["id"], heat["id"], cu_pct=0.002, mn_pct=0.015)
    assert sheet["chem_ok"] is False  # 0.015 > mn_max 0.012

    rev1 = validate_success(
        api_client.revise_sheet(mill["id"], heat["id"], sheet["id"],
                                {"cu_pct": 0.002, "mn_pct": 0.011}, MET), 200)
    assert rev1["status"] == "REVISED"
    assert rev1["revision_no"] == 2
    assert rev1["chem_ok"] is True

    rev2 = validate_success(
        api_client.revise_sheet(mill["id"], heat["id"], sheet["id"],
                                {"cu_pct": 0.002, "mn_pct": 0.008}, MET), 200)
    assert rev2["status"] == "RECORDED"
    assert rev2["revision_no"] == 3


def test_meltdown_sheet_confirm_cascades_heat_to_meltdown_locked():
    """PRD §3.5: "A successful confirmation cascades upward: the heat transitions
    `CHARGED → MELTDOWN_LOCKED`"

    Design: Difficulty/non_linear_state_machine/meltdown_sheet_revision_cycle
    """
    mill, lot, grade, heat = _charged_heat_setup()
    sheet = make_sheet(mill["id"], heat["id"], cu_pct=0.002, mn_pct=0.015)
    validate_success(api_client.revise_sheet(
        mill["id"], heat["id"], sheet["id"], {"cu_pct": 0.002, "mn_pct": 0.011}, MET), 200)
    validate_success(api_client.revise_sheet(
        mill["id"], heat["id"], sheet["id"], {"cu_pct": 0.002, "mn_pct": 0.008}, MET), 200)

    confirmed = validate_success(api_client.confirm_sheet(
        mill["id"], heat["id"], sheet["id"], MET), 200)
    assert confirmed["status"] == "CONFIRMED"
    assert get_heat(mill["id"], heat["id"])["status"] == "MELTDOWN_LOCKED"


def test_meltdown_sheet_confirm_with_bad_chemistry_returns_out_of_spec():
    """PRD §3.5: "Confirming the sheet — from either `RECORDED` or `REVISED`, with
    the heat still `CHARGED` — requires `chem_ok` true; an out-of-band confirmation
    is rejected with `ERR_CHEMISTRY_OUT_OF_SPEC` (HTTP 422)."

    Design: Corner/state_machines/meltdown_sheet_confirm_with_bad_chemistry_returns_out_of_spec
    """
    mill, lot, grade, heat = _charged_heat_setup(lot_tons=20)
    sheet = make_sheet(mill["id"], heat["id"], cu_pct=0.005, mn_pct=0.006)
    assert sheet["chem_ok"] is False  # 0.005 > cu_max 0.004

    resp = api_client.confirm_sheet(mill["id"], heat["id"], sheet["id"], MET)
    validate_error(resp, ApiErrorId.ERR_CHEMISTRY_OUT_OF_SPEC, 422)
    assert get_sheet(mill["id"], heat["id"])["status"] == "RECORDED"
    assert get_heat(mill["id"], heat["id"])["status"] == "CHARGED"


def test_meltdown_sheet_revise_after_confirm_rejected():
    """PRD §3.5: "Revision attempts once the heat has left `CHARGED` fail with
    `ERR_INVALID_STATE`."

    Design: Corner/entities/meltdown_sheet_immutable_after_confirm_has_no_update_path
    """
    mill, lot, grade, heat = _charged_heat_setup(lot_tons=20)
    sheet = make_sheet(mill["id"], heat["id"], cu_pct=0.002, mn_pct=0.006)
    confirm_sheet(mill["id"], heat["id"], sheet["id"])

    resp = api_client.revise_sheet(mill["id"], heat["id"], sheet["id"],
                                   {"cu_pct": 0.001, "mn_pct": 0.005}, MET)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    final = get_sheet(mill["id"], heat["id"])
    assert final["status"] == "CONFIRMED"
    assert final["revision_no"] == 1


def test_meltdown_sheet_create_ignores_smuggled_system_fields():
    """PRD §3.5: "The sheet is born `RECORDED` with `revision_no` 1"
    PRD §3.5: "Confirming the sheet — from either `RECORDED` or `REVISED`, with the
    heat still `CHARGED` — requires `chem_ok` true; an out-of-band confirmation is
    rejected with `ERR_CHEMISTRY_OUT_OF_SPEC` (HTTP 422). A successful confirmation
    cascades upward: the heat transitions `CHARGED → MELTDOWN_LOCKED`"

    Design: Corner/entities/meltdown_sheet_create_system_field_input_ignored
    """
    mill, lot, grade, heat = _charged_heat_setup(lot_tons=20)
    resp = api_client.create_sheet(
        mill["id"], heat["id"],
        {"cu_pct": 0.002, "mn_pct": 0.006, "revision_no": 99, "status": "CONFIRMED"},
        MET,
    )
    sheet = validate_success(resp, 201)
    assert sheet["revision_no"] == 1
    assert sheet["status"] == "RECORDED"
    # The smuggled CONFIRMED did not cascade: the heat stays CHARGED.
    assert get_heat(mill["id"], heat["id"])["status"] == "CHARGED"


def test_scrap_surcharge_credit_sign_and_benchmark():
    """PRD §3.5: "The credit compares the charged mix's value against a blend
    benchmark of 40000 cents per ton: the benchmark value is the total charged tons
    times that per-ton benchmark, the actual value is the exact (pre-rounding) sum
    over charge lines of each line's unit price times its tons, and the credit is the
    difference actual minus benchmark, rounded half-up to whole cents."

    Design: Corner/calculations/scrap_surcharge_credit_sign_and_benchmark
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract, lots = setup_supply_pool(
        mill["id"], price=50000, committed=50,
        supplier_name="Premium Scrap Co",
        lots=[{"received_on": "2026-09-03", "tons_received": 5, "moisture_pct": 0.0}],
    )
    contract_b, lots_b = setup_supply_pool(
        mill["id"], price=42000, committed=50,
        supplier_name="Value Scrap Co",
        lots=[{"received_on": "2026-09-04", "tons_received": 5, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GR40")
    heat = make_heat(mill["id"], grade["id"], target_tap_weight_tons=10,
                     planned_tap_at="2026-09-15T12:00:00Z")
    apply_charge(mill["id"], heat["id"], lots[0]["id"], 5)
    apply_charge(mill["id"], heat["id"], lots_b[0]["id"], 5)
    sheet = make_sheet(mill["id"], heat["id"], cu_pct=0.002, mn_pct=0.006)
    confirm_sheet(mill["id"], heat["id"], sheet["id"])

    locked = get_heat(mill["id"], heat["id"])
    assert locked["status"] == "MELTDOWN_LOCKED"
    # (5*50000 + 5*42000) - 10*40000 = 460000 - 400000 = 60000 (positive: surcharge)
    assert locked["scrap_surcharge_credit_cents"] == 60000
