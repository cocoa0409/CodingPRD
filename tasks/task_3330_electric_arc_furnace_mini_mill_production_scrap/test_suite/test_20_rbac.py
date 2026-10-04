"""RBAC corners: role denial precedence and shared read access (PRD §2.1, §2.7)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    validate_paginated, make_mill, make_grade, make_account, make_order,
    setup_supply_pool, setup_charged_heat,
)

PM = TEST_USERS["plant_manager_headers"]
AM = TEST_USERS["account_manager_headers"]
MET = TEST_USERS["metallurgist_headers"]
SCH = TEST_USERS["scheduler_headers"]
MO = TEST_USERS["mill_operator_headers"]
ED = TEST_USERS["energy_dispatcher_headers"]
QE = TEST_USERS["quality_engineer_headers"]


def test_metallurgist_cannot_confirm_order_returns_forbidden():
    """PRD §2.1: "A request whose role is authenticated but not listed among the
    roles permitted for that endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).
    These two checks run ahead of every other rule on every endpoint, in that order:
    authentication first, authorization second."

    Design: Corner/rbac/metallurgist_cannot_confirm_order_returns_forbidden
    """
    mill = make_mill(name="Crawfordsville Bar Mill", division="CONSTRUCTION")
    acct = make_account(mill["id"], name="Contract Builders Inc",
                        market="CONSTRUCTION", pricing_mode="CONTRACT")
    grade = make_grade(mill["id"], grade_code="GR40")
    order = make_order(mill["id"], acct["id"], grade["id"], tons=5,
                       fulfillment_month="2026-09", base_price_cents_per_ton=25000)

    # Authorization (priority 2) beats existence (priority 4): even a non-existent
    # order id returns 403 for a role not permitted on order-confirm.
    resp = api_client.confirm_order(
        mill["id"], acct["id"], "00000000-0000-4000-8000-000000000009",
        {"expected_order_version": order["version"]}, MET)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_scheduler_cannot_record_meltdown_sheet_returns_forbidden():
    """PRD §2.1: "the `Metallurgist` owns meltdown sheets and their
    revise/confirm/reject actions"
    PRD §2.1: "A request whose role is authenticated but not listed among the roles
    permitted for that endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/scheduler_cannot_record_meltdown_sheet_returns_forbidden
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": 20, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GR40")
    heat, _line = setup_charged_heat(mill["id"], grade["id"], lots[0]["id"], 8)

    resp = api_client.create_sheet(
        mill["id"], heat["id"], {"cu_pct": 0.002, "mn_pct": 0.006}, SCH)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
    _rows, meta = validate_paginated(api_client.list_sheets(mill["id"], heat["id"], MET))
    assert meta["total_count"] == 0


def test_mill_operator_cannot_issue_mtr_returns_forbidden():
    """PRD §3.7: "A mill test report certifies a heat against an order and is issued
    exclusively by a `QualityEngineer`, naming the target `order_id`."
    PRD §2.1: "A request whose role is authenticated but not listed among the roles
    permitted for that endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/mill_operator_cannot_issue_mtr_returns_forbidden
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    # Role denial fires before the 404 existence checks on heat/order.
    resp = api_client.issue_mtr(
        mill["id"], "00000000-0000-4000-8000-000000000009",
        {"order_id": "00000000-0000-4000-8000-000000000010"}, MO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_all_roles_share_get_endpoints():
    """PRD §2.1: "Every role may call every read (GET) endpoint."

    Design: Corner/rbac/all_roles_share_get_endpoints
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    for headers in (ED, QE):
        resp = api_client.list_heats(mill["id"], headers)
        rows, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert meta["total_count"] == 0
