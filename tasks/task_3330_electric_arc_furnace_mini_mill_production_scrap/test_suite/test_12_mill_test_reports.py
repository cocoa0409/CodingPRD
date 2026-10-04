"""Mill test report issuance gates and happy path (PRD §3.7)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    validate_paginated, make_mill, make_grade, make_account, make_order,
    setup_supply_pool, setup_cast_heat, record_interval_payload,
)

MO = TEST_USERS["mill_operator_headers"]
QE = TEST_USERS["quality_engineer_headers"]


def _setup_certified_cast_heat(with_interval=True):
    """CERTIFIED-grade heat processed to CAST; optionally one NORMAL interval."""
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": 40, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="CERT-A", certification_class="CERTIFIED",
                       requires_energy_certified=True)
    account = make_account(mill["id"], name="Bridge Authority", market="CONSTRUCTION",
                           pricing_mode="CONTRACT")
    order = make_order(mill["id"], account["id"], grade["id"], tons=8,
                       fulfillment_month="2026-09", base_price_cents_per_ton=25000)
    heat = setup_cast_heat(mill["id"], grade["id"], lots[0]["id"], 8,
                           tap_at="2026-09-08T12:00:00Z")
    if with_interval:
        validate_success(
            api_client.record_interval(
                mill["id"], heat["id"],
                {"interval_start": "2026-09-08T08:00:00Z",
                 "interval_end": "2026-09-08T09:00:00Z", "kwh": 450},
                MO), 201)
    return mill, grade, account, order, heat


def test_mtr_issue_happy_path_with_energy_certification():
    """PRD §3.7: "The clean-record rule is pinned at the boundary: the report's
    `energy_certified` flag is true exactly when the count of the heat's intervals
    with `posture_at_interval` `INTERRUPTED` is zero — one or more interrupted
    intervals fails certification"
    PRD §3.7: "On issuance the server mints the `report_no` in the format
    MTR-<sequence> numbered per mill, copies the confirmed sheet's chemistry
    (`cu_pct`, `mn_pct`, and `revision_no`) into the report's `chemistry_snapshot`,
    and stores the computed `energy_certified`."

    Design: Corner/endpoints/mtr_issue_happy_path_with_energy_certification
    """
    mill, grade, account, order, heat = _setup_certified_cast_heat(with_interval=True)
    mtr = validate_success(
        api_client.issue_mtr(mill["id"], heat["id"], {"order_id": order["id"]}, QE), 201)
    assert mtr["energy_certified"] is True
    assert mtr["report_no"] == "MTR-1"
    assert mtr["chemistry_snapshot"]["cu_pct"] == 0.002
    assert mtr["chemistry_snapshot"]["revision_no"] == 1


def test_mtr_issue_certified_grade_with_zero_intervals_rejected():
    """PRD §3.7: "A heat with no intervals at all is vacuously clean, but a
    `CERTIFIED`-class grade still demands at least one recorded interval before a
    report can issue."
    PRD §3.7: "Any shortfall is rejected with `ERR_MTR_NOT_ISSUABLE` (HTTP 409)."

    Design: Corner/calculations/energy_compliance_vacuous_truth_and_single_interrupt_fails
    """
    mill, grade, account, order, heat = _setup_certified_cast_heat(with_interval=False)
    resp = api_client.issue_mtr(mill["id"], heat["id"], {"order_id": order["id"]}, QE)
    validate_error(resp, ApiErrorId.ERR_MTR_NOT_ISSUABLE, 409)
    rows, meta = validate_paginated(api_client.list_mtrs(mill["id"], heat["id"], QE))
    assert meta["total_count"] == 0
