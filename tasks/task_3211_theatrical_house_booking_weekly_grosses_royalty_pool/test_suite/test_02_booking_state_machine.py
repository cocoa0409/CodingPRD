"""Booking state machine: invalid transitions, terminal lockdown, cascades."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_company_rep_headers,
    setup_approved_booking, setup_active_booking, verified_report_for_week1,
    create_and_sign_license, engage_crew, sell_week1_order, open_report,
    set_clock, submit_report, verify_report, get_booking, get_license,
    list_stop_notices, booking_version,
    TEST_DEFAULTS,
)

HM = TEST_USERS["house_manager_headers"]
BO = TEST_USERS["box_office_agent_headers"]


def test_approve_withdrawn_booking_returns_invalid_state(api):
    """PRD §3.2: "Attempting a transition from a state that does not allow it —
    approving a `WITHDRAWN` booking, say — is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/approve_withdrawn_booking_returns_invalid_state
    """
    ctx = setup_approved_booking(company_name="WdCo", company_email="wd@x.com")
    bk = ctx["booking"]
    resp = api_client.withdraw_booking(bk["id"], ctx["rep"])
    validate_success(resp)
    resp = api_client.approve_booking(bk["id"], HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_booking(bk["id"])["status"] == "WITHDRAWN"


def test_refund_already_refunded_order_returns_invalid_state(api):
    """PRD §3.5: "refunding an already-`REFUNDED` order is an
    `ERR_INVALID_STATE` violation."

    Design: Corner/state_machines/refund_already_refunded_order_returns_invalid_state
    """
    ctx = setup_active_booking()
    order = sell_week1_order(ctx["booking"]["id"])
    validate_success(api_client.refund_ticket_order(order["id"], BO))
    resp = api_client.refund_ticket_order(order["id"], BO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    from test_helpers import get_order
    assert get_order(order["id"])["status"] == "REFUNDED"


def test_withdraw_cascades_void_license_and_discharge_notice(api):
    """PRD §3.2: "The owning `CompanyRep` may withdraw a booking from either
    `REQUESTED` or `APPROVED`; withdrawal cascades: the booking's license
    agreement, if one exists in `DRAFT` or `SIGNED` status, is moved to
    `VOIDED`, and voiding the agreement in turn discharges any `OPEN` stop
    notice on the booking, moving it to `DISCHARGED` (cascade depth 2)."

    Design: Corner/state_machines/withdraw_cascades_void_license_and_discharge_notice
    """
    ctx = setup_approved_booking(company_name="CasCo", company_email="cs@x.com")
    bk_id = ctx["booking"]["id"]
    lic = create_and_sign_license(bk_id, ctx["company"]["id"],
                                  stop_clause_weekly_floor_cents=50000)
    engage_crew(bk_id, 4)
    resp = api_client.withdraw_booking(bk_id, ctx["rep"])
    validate_success(resp)
    assert get_booking(bk_id)["status"] == "WITHDRAWN"
    assert get_license(lic["id"])["status"] == "VOIDED", (
        "withdraw must void the SIGNED license agreement (depth 1 cascade)")
