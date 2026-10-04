"""Crew cost constants, royalty pool split, weekly gross report lifecycle."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_active_booking, sell_week1_order, open_report, set_clock,
    submit_report, verify_report, get_report,
    add_pool_participant, create_settlement_payload, TEST_DEFAULTS,
)

HM = TEST_USERS["house_manager_headers"]


def test_crew_cost_uses_union_minimum_when_engaged_below(api):
    """PRD §2.6: "That engaged count is multiplied by a flat crew weekly rate
    of 120000 cents (that is, 1200 dollars per crew member per week) to
    produce `crew_cost_cents`."
    PRD §2.6: "The engaged crew count is the greater of the union minimum for
    the house's size class and the `crew_size` of the booking's crew
    assignment — the latest assignment by `engaged_at`, with ties broken by
    `created_at` ascending — or simply the union minimum if no assignment
    exists."

    Design: Corner/calculations/crew_cost_uses_union_minimum_when_engaged_below
    """
    ctx = setup_active_booking(
        crew_size=8, size_class="MEDIUM", weekly_rent_cents=400000,
        company_name="CrewCo", company_email="cr@x.com", house_name="MidH",
        production_title="Show Cr")
    sell_week1_order(ctx["booking"]["id"], ticket_count=8, is_group_sale=True,
                     face_value_cents=250000)
    rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
    set_clock(TEST_DEFAULTS["WEEK1_END"])
    submit_report(rep["id"], ctx["company"]["id"])
    verify_report(rep["id"])
    data = validate_success(api_client.create_settlement(
        rep["id"], create_settlement_payload(house_expenses_cents=100000), HM),
        expected_status=201)
    assert data["crew_cost_cents"] == 960000, (
        f"8 crew at exactly the MEDIUM minimum, 8 * 120000 = 960000, "
        f"got {data['crew_cost_cents']}")


def test_royalty_pool_remainder_allocation_order(api):
    """PRD §3.8: "Within the pool, each pool-eligible participant's payout is
    the pool amount multiplied by the participant's `royalty_points` and
    divided by the total pool points, taken down to whole cents (floor). The
    cents left over by that flooring are then allocated one cent at a time to
    participants ranked by `royalty_points` descending, with ties broken by
    the participant's `created_at` ascending."

    Design: Corner/calculations/royalty_pool_remainder_allocation_order
    """
    ctx = setup_active_booking(
        crew_size=8, size_class="MEDIUM", weekly_rent_cents=400000,
        company_name="PoolCo", company_email="po@x.com", house_name="MidP",
        production_title="Show Pool")
    add_pool_participant(ctx["production"]["id"], ctx["company"]["id"], "P34", 34)
    add_pool_participant(ctx["production"]["id"], ctx["company"]["id"], "P33a", 33)
    add_pool_participant(ctx["production"]["id"], ctx["company"]["id"], "P33b", 33)
    sell_week1_order(ctx["booking"]["id"], ticket_count=6, is_group_sale=False,
                     face_value_cents=250000)
    rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
    set_clock(TEST_DEFAULTS["WEEK1_END"])
    submit_report(rep["id"], ctx["company"]["id"])
    verify_report(rep["id"])
    data = validate_success(api_client.create_settlement(
        rep["id"], create_settlement_payload(house_expenses_cents=0), HM),
        expected_status=201)
    # theatre_share = max(400000, round(0.30*1500000)=450000) = 450000
    assert data["theatre_share_cents"] == 450000
    # profit = 1500000 - 0 - 960000 - 450000 - 0 = 90000
    assert data["weekly_operating_profit_cents"] == 90000
    # pool = round_half_up(0.65 * 90000) = 58500
    assert data["royalty_pool_cents"] == 58500, (
        f"pool must be 58500, got {data['royalty_pool_cents']}")


class TestGrossReportRevisionCycle:
    def _setup_rejected_report(self, api):
        ctx = setup_active_booking(company_name="CycCo", company_email="c@x.com",
                                   house_name="Bijou4", production_title="Show C")
        sell_week1_order(ctx["booking"]["id"])
        rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
        set_clock(TEST_DEFAULTS["WEEK1_END"])
        submit_report(rep["id"], ctx["company"]["id"])
        validate_success(api_client.reject_weekly_gross_report(rep["id"], HM))
        return ctx, rep

    def test_revise_returns_report_to_draft_with_provisional_gross(self, api):
        """PRD §3.6: "A rejected report can be sent back to `DRAFT` by the
        owning representative through the revise action while the booking
        remains `ACTIVE`, which re-derives the gross provisionally; the report
        may cycle `DRAFT` → `SUBMITTED` → `REJECTED` → `DRAFT` as many times
        as the house requires."

        Design: Difficulty/non_linear_state_machine/gross_report_revision_cycle
        """
        ctx, rep = self._setup_rejected_report(api)
        data = validate_success(api_client.revise_weekly_gross_report(
            rep["id"], ctx["rep"]))
        assert data["status"] == "DRAFT"
        assert data["gross_cents"] == 10000, (
            f"provisional gross re-derived on revise must be 10000, "
            f"got {data['gross_cents']}")

    def test_revision_cycle_is_repeatable(self, api):
        """PRD §3.6: "the report may cycle `DRAFT` → `SUBMITTED` → `REJECTED`
        → `DRAFT` as many times as the house requires."

        Design: Difficulty/non_linear_state_machine/gross_report_revision_cycle
        """
        ctx, rep = self._setup_rejected_report(api)
        validate_success(api_client.revise_weekly_gross_report(rep["id"], ctx["rep"]))
        resubmitted = validate_success(api_client.submit_weekly_gross_report(
            rep["id"], ctx["rep"]))
        assert resubmitted["status"] == "SUBMITTED", (
            "a second submit from DRAFT must be accepted (loop is repeatable)")
        validate_success(api_client.reject_weekly_gross_report(rep["id"], HM))
        again = validate_success(api_client.revise_weekly_gross_report(
            rep["id"], ctx["rep"]))
        assert again["status"] == "DRAFT"
