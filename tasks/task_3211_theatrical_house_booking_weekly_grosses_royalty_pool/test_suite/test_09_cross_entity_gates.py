"""Cross-entity state gates: settlement creation, report submit, ticket sales."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    TEST_USERS, setup_active_booking, setup_approved_booking,
    create_and_sign_license, engage_crew, set_clock,
    sell_week1_order, open_report, submit_report, verify_report,
    create_settlement_payload, TEST_DEFAULTS,
)

HM = TEST_USERS["house_manager_headers"]
BO = TEST_USERS["box_office_agent_headers"]


class TestSettlementRequiresVerifiedReport:
    def _setup_submitted_not_verified(self, api):
        ctx = setup_active_booking(company_name="XCo", company_email="x@x.com")
        sell_week1_order(ctx["booking"]["id"])
        rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
        set_clock(TEST_DEFAULTS["WEEK1_END"])
        submit_report(rep["id"], ctx["company"]["id"])
        return ctx, rep

    def test_settlement_create_on_submitted_report_rejected(self, api):
        """PRD §3.8: "Once a report is `VERIFIED`, a `HouseManager` creates
        the **settlement** for it by referencing the report's `report_id` and
        supplying the itemized `house_expenses_cents`".
        PRD §3.2: "Attempting a transition from a state that does not allow it
        — approving a `WITHDRAWN` booking, say — is rejected with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/settlement_finalize_requires_report_verified_and_license_signed
        """
        ctx, rep = self._setup_submitted_not_verified(api)
        resp = api_client.create_settlement(
            rep["id"], create_settlement_payload(house_expenses_cents=100000), HM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_settlement_create_on_verified_report_succeeds(self, api):
        """PRD §3.8: "Once a report is `VERIFIED`, a `HouseManager` creates
        the **settlement** for it by referencing the report's `report_id` and
        supplying the itemized `house_expenses_cents`".

        Design: Difficulty/cross_entity_state_dependency/settlement_finalize_requires_report_verified_and_license_signed
        """
        ctx, rep = self._setup_submitted_not_verified(api)
        verify_report(rep["id"])
        data = validate_success(api_client.create_settlement(
            rep["id"], create_settlement_payload(house_expenses_cents=100000), HM),
            expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["booking_id"] == ctx["booking"]["id"]


class TestReportSubmitRequiresBookingActive:
    def _setup_closed_booking_with_draft_week2(self, api):
        ctx = setup_active_booking(company_name="YCo", company_email="y@x.com")
        sell_week1_order(ctx["booking"]["id"])
        rep1 = open_report(ctx["booking"]["id"], ctx["company"]["id"])
        set_clock(TEST_DEFAULTS["WEEK1_END"])
        submit_report(rep1["id"], ctx["company"]["id"])
        verify_report(rep1["id"])
        validate_success(api_client.close_booking(ctx["booking"]["id"], ctx["rep"]))
        rep2 = open_report(ctx["booking"]["id"], ctx["company"]["id"],
                           week_start=TEST_DEFAULTS["WEEK2_START"])
        set_clock(TEST_DEFAULTS["WEEK2_END"])
        return ctx, rep2

    def test_submit_on_closed_booking_rejected(self, api):
        """PRD §3.6: "A `CompanyRep` submits a `DRAFT` report once the booking
        is `ACTIVE` and the week has fully elapsed — that is, `week_end` is at
        or before the logical clock; submitting earlier is not permitted."

        Design: Difficulty/cross_entity_state_dependency/report_submit_requires_booking_active
        """
        ctx, rep2 = self._setup_closed_booking_with_draft_week2(api)
        resp = api_client.submit_weekly_gross_report(rep2["id"], ctx["rep"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_close_with_open_draft_report_rejected(self, api):
        """PRD §3.10: "When a run ends, the owning `CompanyRep` closes an
        `ACTIVE` booking — provided no weekly gross report for the booking is
        still sitting in `DRAFT` or `SUBMITTED` — moving it to `CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/report_submit_requires_booking_active
        """
        ctx = setup_active_booking(company_name="Y2Co", company_email="y2@x.com")
        sell_week1_order(ctx["booking"]["id"])
        open_report(ctx["booking"]["id"], ctx["company"]["id"])  # stays DRAFT
        resp = api_client.close_booking(ctx["booking"]["id"], ctx["rep"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_ticket_order_create_on_non_active_booking_rejected(api):
    """PRD §3.5: "A `BoxOfficeAgent` sells a **ticket order** against an
    `ACTIVE` booking by providing the `performance_date` ...".

    Design: Corner/endpoints/ticket_order_create_on_non_active_booking_rejected
    """
    ctx = setup_approved_booking(company_name="CondCo", company_email="cd@x.com")
    bk_id = ctx["booking"]["id"]
    create_and_sign_license(bk_id, ctx["company"]["id"])
    engage_crew(bk_id, 4)
    # clock still at 2026-09-01 < loadin 2026-09-06: booking stays APPROVED
    resp = api_client.create_ticket_order(
        bk_id,
        {"performance_date": "2026-09-08T19:00:00Z", "ticket_count": 2,
         "is_group_sale": False, "face_value_cents": 5000},
        BO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
