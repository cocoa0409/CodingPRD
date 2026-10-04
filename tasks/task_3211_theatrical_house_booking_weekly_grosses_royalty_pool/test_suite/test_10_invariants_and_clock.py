"""Invariants, immediate consistency, computed reads, logical clock."""
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    TEST_USERS, setup_active_booking, setup_approved_booking,
    sell_week1_order, open_report, set_clock, submit_report, verify_report,
    get_report, get_booking, engage_crew, TEST_DEFAULTS,
)

HM = TEST_USERS["house_manager_headers"]
BO = TEST_USERS["box_office_agent_headers"]


class TestSellRefundPreservesWeeklyGross:
    def test_sell_then_refund_restores_draft_gross(self, api):
        """PRD §3.6: "A report's `gross_cents` is the sum of
        `computed_gross_cents` over the booking's ticket orders whose status
        is `SOLD` and whose `performance_date` falls inside the half-open
        week; refunded orders are excluded."

        Design: Difficulty/compensating_invariant/sell_refund_preserves_weekly_gross
        """
        ctx = setup_active_booking(company_name="InvCo", company_email="i@x.com")
        sell_week1_order(ctx["booking"]["id"])  # 10000
        rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
        assert rep["gross_cents"] == 10000
        o2 = sell_week1_order(ctx["booking"]["id"], face_value_cents=3000,
                              performance_date="2026-09-09T19:00:00Z")  # +6000
        validate_success(api_client.refund_ticket_order(o2["id"], BO))
        assert get_report(rep["id"])["gross_cents"] == 10000, (
            f"sell+refund pair must restore gross to the pre-sell value, "
            f"got {get_report(rep['id'])['gross_cents']}")

    def test_report_excludes_refunded_orders_from_sum(self, api):
        """PRD §3.5: "Refund cascades into reporting: if the weekly gross
        report covering the order's `performance_date` is still `DRAFT` or
        `SUBMITTED`, its `gross_cents` is recomputed under the provisional
        variant."

        Design: Difficulty/compensating_invariant/sell_refund_preserves_weekly_gross
        """
        ctx = setup_active_booking(company_name="InvCo", company_email="i@x.com")
        sell_week1_order(ctx["booking"]["id"])  # 10000
        rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
        o2 = sell_week1_order(ctx["booking"]["id"], face_value_cents=3000,
                              performance_date="2026-09-09T19:00:00Z")
        assert get_report(rep["id"])["gross_cents"] == 16000
        validate_success(api_client.refund_ticket_order(o2["id"], BO))
        assert get_report(rep["id"])["gross_cents"] == 10000


def test_immediate_consistency_after_refund(api):
    """PRD §3.5: "Refund cascades into reporting: if the weekly gross report
    covering the order's `performance_date` is still `DRAFT` or `SUBMITTED`,
    its `gross_cents` is recomputed under the provisional variant."
    PRD §3.6: "the gross is computed live from the current order set each
    time, so a later refund or a new sale changes it."

    Design: Corner/consistency_model/immediate_consistency_after_refund
    """
    ctx = setup_active_booking(company_name="ImmCo", company_email="im@x.com")
    order = sell_week1_order(ctx["booking"]["id"])  # 10000
    rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
    refunded = validate_success(api_client.refund_ticket_order(order["id"], BO))
    assert refunded["status"] == "REFUNDED"
    report_now = get_report(rep["id"])
    assert report_now["gross_cents"] == 0, (
        f"immediately after refund the DRAFT report must read 0, "
        f"got {report_now['gross_cents']}")


def test_settlement_list_for_report_returns_zero_or_one(api):
    """PRD §3.8: "The report's settlement can also be read back through the
    report itself, which yields zero or one element."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/settlement_list_for_report_returns_zero_or_one
    """
    ctx = setup_active_booking(company_name="LstCo", company_email="ls@x.com")
    sell_week1_order(ctx["booking"]["id"])
    rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
    set_clock(TEST_DEFAULTS["WEEK1_END"])
    submit_report(rep["id"], ctx["company"]["id"])
    verify_report(rep["id"])
    resp = api_client.get_report_settlement(rep["id"], HM)
    body = resp.json()
    assert body["response_type"] == "array"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["data"] == [], (
        f"before settlement creation the list must be empty, got {body['data']}")


class TestClockDefaultAndActivation:
    def test_booking_stays_approved_before_loadin_at_default_clock(self, api):
        """PRD §2.9: "Before any such call, the server's clock at startup is
        exactly 2026-09-01T00:00:00Z and must never fall back to wall-clock
        time."
        PRD §3.4: "The booking then moves from `APPROVED` to `ACTIVE`
        automatically: when the logical clock reaches `loadin_start`, the
        system activates the booking, but only if a crew assignment exists for
        it whose `crew_size` meets the union minimum for the house."

        Design: Corner/cross_cutting_layers/clock_default_is_fixed_startup_time
        """
        ctx = setup_approved_booking(company_name="ClkCo", company_email="ck@x.com")
        engage_crew(ctx["booking"]["id"], 4)
        # clock left at startup default 2026-09-01T00:00:00Z < loadin 09-06
        assert get_booking(ctx["booking"]["id"])["status"] == "APPROVED"

    def test_clock_advance_to_loadin_activates_booking(self, api):
        """PRD §3.4: "The booking then moves from `APPROVED` to `ACTIVE`
        automatically: when the logical clock reaches `loadin_start`, the
        system activates the booking, but only if a crew assignment exists for
        it whose `crew_size` meets the union minimum for the house."
        PRD §2.9: "Time-driven transitions — a booking becoming `ACTIVE` when
        its load-in begins, a closed or evicted booking moving to
        `MAINTENANCE_HOLD` or `DONE` when load-out completes — are evaluated
        against the logical clock whenever it advances."

        Design: Corner/cross_cutting_layers/clock_default_is_fixed_startup_time
        """
        ctx = setup_approved_booking(company_name="ClkCo", company_email="ck@x.com")
        engage_crew(ctx["booking"]["id"], 4)
        set_clock(TEST_DEFAULTS["WEEK1_START"])  # 2026-09-07 >= loadin 09-06
        assert get_booking(ctx["booking"]["id"])["status"] == "ACTIVE"
