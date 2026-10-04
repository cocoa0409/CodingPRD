"""Boundary precision: stop-clause floor equality, group-sale 8-ticket rule."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    TEST_USERS, setup_active_booking, sell_week1_order, open_report,
    set_clock, submit_report, verify_report, list_stop_notices,
    TEST_DEFAULTS,
)

HM = TEST_USERS["house_manager_headers"]
BO = TEST_USERS["box_office_agent_headers"]


class TestStopFloorBoundary:
    def test_exact_floor_gross_creates_no_notice(self, api):
        """PRD §3.7: "The boundary is strict: a week whose gross is **strictly
        below** the floor increments the booking's under-floor counter, and a
        stop notice is created in `OPEN` status for the booking if none
        exists. A week whose gross is at or above the floor — equality does
        **not** accrue a demerit — resets the counter to zero and, if an
        `OPEN` notice exists, discharges it to `DISCHARGED`."

        Design: Difficulty/boundary_precision_check/stop_floor_exact_gross_does_not_increment
        """
        ctx = setup_active_booking(stop_clause_weekly_floor_cents=10000)
        sell_week1_order(ctx["booking"]["id"])  # 2 x 5000 = 10000 == floor
        rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
        set_clock(TEST_DEFAULTS["WEEK1_END"])
        submit_report(rep["id"], ctx["company"]["id"])
        verify_report(rep["id"])
        notices = list_stop_notices(ctx["booking"]["id"])
        assert len(notices) == 0, (
            f"gross == floor exactly must not accrue a demerit; "
            f"found notices: {notices}")

    def test_one_cent_below_floor_creates_open_notice(self, api):
        """PRD §3.7: "The boundary is strict: a week whose gross is **strictly
        below** the floor increments the booking's under-floor counter, and a
        stop notice is created in `OPEN` status for the booking if none
        exists."

        Design: Difficulty/boundary_precision_check/stop_floor_exact_gross_does_not_increment
        """
        ctx = setup_active_booking(stop_clause_weekly_floor_cents=10001)
        sell_week1_order(ctx["booking"]["id"])  # 10000 < 10001
        rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
        set_clock(TEST_DEFAULTS["WEEK1_END"])
        submit_report(rep["id"], ctx["company"]["id"])
        verify_report(rep["id"])
        notices = list_stop_notices(ctx["booking"]["id"])
        assert len(notices) == 1 and notices[0]["status"] == "OPEN", (
            f"a strictly-below-floor week must open a stop notice, "
            f"got {notices}")
        assert notices[0]["consecutive_under_floor_weeks"] == 1


class TestGroupSaleBoundary:
    def test_eight_tickets_without_group_flag_rejected(self, api):
        """PRD §3.5: "Group-sale coherence is enforced: an order of eight or
        more tickets must carry `is_group_sale` true, and an order of fewer
        than eight must not — violations are rejected with
        `ERR_GROUP_SALE_FLAG_MISMATCH` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/group_sale_flag_at_exactly_eight_tickets
        """
        ctx = setup_active_booking()
        resp = api_client.create_ticket_order(
            ctx["booking"]["id"],
            {"performance_date": "2026-09-08T19:00:00Z", "ticket_count": 8,
             "is_group_sale": False, "face_value_cents": 5000},
            BO)
        validate_error(resp, ApiErrorId.ERR_GROUP_SALE_FLAG_MISMATCH)

    def test_eight_tickets_with_group_flag_succeeds(self, api):
        """PRD §3.5: "Group-sale coherence is enforced: an order of eight or
        more tickets must carry `is_group_sale` true, and an order of fewer
        than eight must not — violations are rejected with
        `ERR_GROUP_SALE_FLAG_MISMATCH` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/group_sale_flag_at_exactly_eight_tickets
        """
        ctx = setup_active_booking()
        data = validate_success(api_client.create_ticket_order(
            ctx["booking"]["id"],
            {"performance_date": "2026-09-08T19:00:00Z", "ticket_count": 8,
             "is_group_sale": True, "face_value_cents": 5000},
            BO), expected_status=201)
        assert data["ticket_count"] == 8 and data["is_group_sale"] is True


def test_stop_clause_not_met_error_triggerable(api):
    """PRD §3.7: "Executing while the counter is still below the threshold —
    or when no `OPEN` notice exists — is rejected with
    `ERR_STOP_CLAUSE_NOT_MET` (HTTP 409)."

    Design: Corner/errors/stop_clause_not_met_error_triggerable
    """
    ctx = setup_active_booking(stop_clause_weekly_floor_cents=50000,
                               stop_clause_consecutive_weeks=2)
    sell_week1_order(ctx["booking"]["id"])  # 10000 < 50000 -> counter 1
    rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
    set_clock(TEST_DEFAULTS["WEEK1_END"])
    submit_report(rep["id"], ctx["company"]["id"])
    verify_report(rep["id"])
    resp = api_client.execute_stop_notice(ctx["booking"]["id"], HM)
    validate_error(resp, ApiErrorId.ERR_STOP_CLAUSE_NOT_MET)
