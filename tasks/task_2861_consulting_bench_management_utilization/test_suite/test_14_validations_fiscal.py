"""Fiscal and sourcing validations: margin, hours, discounts, firms, seats, separation."""

import pytest

from test_helpers import (
    FINANCE_CONTROLLER,
    FINANCE_CONTROLLER_USER_ID,
    PRACTICE_PARTNER,
    PRACTICE_PARTNER_USER_ID,
    RESOURCE_MANAGER,
    RESOURCE_MANAGER_USER_ID,
    SALES_LEAD,
    SALES_LEAD_2,
    SALES_LEAD_2_USER_ID,
    SALES_LEAD_USER_ID,
    ApiErrorId,
    ApprovalStatus,
    ApprovalTier,
    AssignmentCategory,
    AssignmentStatus,
    AvailabilityStatus,
    BenchSpellState,
    FirmApprovalStatus,
    PeriodStatus,
    PlacementStatus,
    Posture,
    ProgramStatus,
    SeparationDecision,
    StaffingStatus,
    factories,
    fixtures,
    make_practice_partner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    INSTANT_AUG_03,
    INSTANT_AUG_29,
    INSTANT_AUG_31,
    INSTANT_SEP_30,
)


class TestMarginFloorIsScopedToBillable:
    @staticmethod
    def _three_proposals_against_one_rate(api):
        """A 250.00 effective rate and three PROPOSED rows at costs 220 / 200 / 220."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        # PRD §3.5 refuses an INVESTMENT confirmation when the demand's practice
        # group posture is FROZEN, and PRD §2.10 freezes any group whose whole
        # headcount is on the bench, so the three consultants are hired elsewhere.
        fixtures.add_bench_group(api, world)
        demand = fixtures.qualified_demand(
            api,
            world,
            min_proficiency_level=3,
            onsite_nights_per_week=2,
            required_fte=3.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        rows = {}
        recipes = (
            ("high", "Ada Byron", 220.00, AssignmentCategory.BILLABLE),
            ("edge", "Grace Hopper", 200.00, AssignmentCategory.BILLABLE),
            ("investment", "Alan Turing", 220.00, AssignmentCategory.INVESTMENT),
        )
        for key, full_name, cost, category in recipes:
            staff = fixtures.hire(
                api,
                world,
                full_name=full_name,
                proficiency_level=4,
                group_key="bench_group",
                cost_rate_usd_per_hour=cost,
            )
            rows[key] = {
                "staff": staff,
                "assignment": fixtures.propose_assignment(
                    api,
                    staff["consultant"]["id"],
                    demand["id"],
                    allocation_pct=100.00,
                    start_date="2026-08-17",
                    end_date="2026-08-29",
                    category=category,
                ),
            }
        return world, demand, rows

    def test_twelve_percent_is_refused_while_exactly_twenty_is_admitted(self, api):
        """PRD §3.5: "And when `category` is `BILLABLE`, the margin must hold: one hundred
        multiplied by the demand's `effective_rate_usd_per_hour` less this row's
        `cost_rate_usd_per_hour`, divided by that effective rate, rounded half-up to two
        decimals, must be at least 20.00 percent, else `ERR_MARGIN_FLOOR_BREACH`."

        Design: Corner/validations/margin_floor_gates_billable_confirms_only_and_admits_exactly_twenty
        """
        _, demand, rows = self._three_proposals_against_one_rate(api)

        # round(100 * (250.00 - 220.00) / 250.00, 2) == 12.00
        validate_error(
            api.confirm_assignment(rows["high"]["assignment"]["id"], RESOURCE_MANAGER),
            ApiErrorId.ERR_MARGIN_FLOOR_BREACH,
            422,
        )
        refused = fixtures.read_assignment(api, rows["high"]["assignment"]["id"])
        assert refused["status"] == AssignmentStatus.PROPOSED
        assert fixtures.read_consultant(api, rows["high"]["staff"]["consultant"]["id"])[
            "allocated_pct"
        ] == pytest.approx(0.00, abs=0.005)

        # round(100 * (250.00 - 200.00) / 250.00, 2) == 20.00, which "at least" admits.
        confirmed = fixtures.confirm(api, rows["edge"]["assignment"]["id"])
        assert confirmed["status"] == AssignmentStatus.CONFIRMED
        assert confirmed["bill_rate_usd_per_hour"] == pytest.approx(250.00, abs=0.01)

        after = fixtures.read_demand(api, demand["id"])
        assert after["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)
        assert after["staffing_status"] == StaffingStatus.PARTIALLY_COVERED

    def test_the_same_cost_confirms_as_an_investment_row(self, api):
        """PRD §3.5: "And when `category` is `BILLABLE`, the margin must hold: one hundred
        multiplied by the demand's `effective_rate_usd_per_hour` less this row's
        `cost_rate_usd_per_hour`, divided by that effective rate, rounded half-up to two
        decimals, must be at least 20.00 percent, else `ERR_MARGIN_FLOOR_BREACH`."

        Design: Corner/validations/margin_floor_gates_billable_confirms_only_and_admits_exactly_twenty
        """
        _, demand, rows = self._three_proposals_against_one_rate(api)

        investment = fixtures.confirm(api, rows["investment"]["assignment"]["id"])
        assert investment["category"] == AssignmentCategory.INVESTMENT
        assert investment["status"] == AssignmentStatus.CONFIRMED
        assert investment["bill_rate_usd_per_hour"] == pytest.approx(0.00, abs=0.01)

        fixtures.confirm(api, rows["edge"]["assignment"]["id"])

        after = fixtures.read_demand(api, demand["id"])
        assert after["covered_internal_fte"] == pytest.approx(2.00, abs=0.005)
        assert after["open_fte"] == pytest.approx(1.00, abs=0.005)
        # Clock 2026-08-03 is before the 2026-08-17 start, so nothing is delivered.
        assert after["blended_cost_rate_usd_per_hour"] == pytest.approx(0.00, abs=0.01)
        assert after["blended_margin_pct"] is None
        assert after["margin_breach"] is False


class TestPeriodStateOutranksHourOverallocation:
    @staticmethod
    def _overallocated_open_period(api):
        """A period with 120.00 holiday hours carrying 160.00 billable hours."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=120.00,
        )
        consultant_id = staff["consultant"]["id"]
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=1.00,
            start_date="2026-08-03",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        period = fixtures.create_period(
            api, consultant_id, "2026-08-03", "2026-08-28", holiday_hours=120.00
        )
        fixtures.confirmed_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        return world, staff, period

    def test_an_unfinished_period_is_refused_before_the_hours_are_examined(self, api):
        """PRD §3.9: "The period must be `OPEN` and its `period_end_on` must be strictly
        before the logical clock date — closing a period that is already `CLOSED`, or one
        that has not finished, is `ERR_PERIOD_STATE_INVALID` — and a period whose
        `hour_overallocated` is true cannot be closed at all, which is
        `ERR_HOUR_OVERALLOCATION`."

        Design: Corner/validations/period_state_outranks_hour_overallocation_on_close
        """
        _, staff, period = self._overallocated_open_period(api)
        consultant_id = staff["consultant"]["id"]

        assert period["capacity_hours"] == pytest.approx(160.00, abs=0.01)
        assert period["net_available_hours"] == pytest.approx(40.00, abs=0.01)

        loaded = fixtures.read_period(api, consultant_id, period["id"])
        assert loaded["billable_hours"] == pytest.approx(160.00, abs=0.01)
        assert loaded["hour_overallocated"] is True

        # Clock 2026-08-03 is not strictly after period_end_on 2026-08-28.
        validate_error(
            api.close_utilization_period(
                consultant_id, period["id"], FINANCE_CONTROLLER
            ),
            ApiErrorId.ERR_PERIOD_STATE_INVALID,
            409,
        )
        assert (
            fixtures.read_period(api, consultant_id, period["id"])["status"]
            == PeriodStatus.OPEN
        )

    def test_once_the_period_has_finished_the_hour_rule_is_exposed(self, api):
        """PRD §2.9: "33. **Hour conservation** — a period whose `hour_overallocated` flag
        is true may not be closed. Applies to period closure. Failure:
        `ERR_HOUR_OVERALLOCATION` (409)."

        Design: Corner/validations/period_state_outranks_hour_overallocation_on_close
        """
        _, staff, period = self._overallocated_open_period(api)
        consultant_id = staff["consultant"]["id"]

        fixtures.set_clock(api, INSTANT_AUG_31)

        validate_error(
            api.close_utilization_period(
                consultant_id, period["id"], FINANCE_CONTROLLER
            ),
            ApiErrorId.ERR_HOUR_OVERALLOCATION,
            409,
        )

        after = fixtures.read_period(api, consultant_id, period["id"])
        assert after["status"] == PeriodStatus.OPEN
        assert after["hour_overallocated"] is True
        assert after["billable_hours"] == pytest.approx(160.00, abs=0.01)
        # bench_hours is floored at 0.00, so the conservation identity is broken.
        assert after["bench_hours"] == pytest.approx(0.00, abs=0.01)
        # Still the available-basis figure: 100 * 160.00 / 40.00.
        assert after["utilization_pct_of_record"] == pytest.approx(400.00, abs=0.01)


class TestTheLegalDiscountWindow:
    @staticmethod
    def _unstaffed_qualified_demand(api):
        """A QUALIFIED demand at 250.00 with no assignments, so the level-floor
        variant of the third step applies at 80.00."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        demand = fixtures.qualified_demand(
            api,
            world,
            min_proficiency_level=3,
            required_fte=1.00,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        return world, demand

    def test_a_premium_is_refused_on_the_demand_and_on_the_approval_alike(self, api):
        """PRD §2.9: "38. **No premium disguised as a discount** — a discount approval's
        `requested_rate_usd_per_hour` must be at most the demand's
        `standard_rate_usd_per_hour`, and a demand's own `requested_rate_usd_per_hour` must
        be at most its `standard_rate_usd_per_hour` at creation. Applies to demand
        creation, discount-approval creation and discount revision. Failure:
        `ERR_RATE_ABOVE_STANDARD` (422)."

        Design: Corner/validations/rate_above_standard_and_hard_cap_bound_the_discount_window
        """
        world, demand = self._unstaffed_qualified_demand(api)

        validate_error(
            api.create_demand(
                factories.demand_payload(
                    world["group"]["id"],
                    world["skill"]["id"],
                    client_name="Globex Bank",
                    standard_rate_usd_per_hour=250.00,
                    requested_rate_usd_per_hour=300.00,
                ),
                SALES_LEAD,
            ),
            ApiErrorId.ERR_RATE_ABOVE_STANDARD,
            422,
        )
        _, demands_meta = validate_paginated(api.list_demands(SALES_LEAD))
        assert demands_meta["total_count"] == 1

        validate_error(
            api.create_discount_approval(
                factories.discount_approval_payload(
                    demand["id"], 260.00, fixtures.demand_version(api, demand["id"])
                ),
                SALES_LEAD,
            ),
            ApiErrorId.ERR_RATE_ABOVE_STANDARD,
            422,
        )
        _, approvals_meta = validate_paginated(api.list_discount_approvals(SALES_LEAD))
        assert approvals_meta["total_count"] == 0

        untouched = fixtures.read_demand(api, demand["id"])
        assert untouched["approved_rate_usd_per_hour"] is None
        assert untouched["effective_rate_usd_per_hour"] == pytest.approx(250.00, abs=0.01)

    def test_a_forty_percent_discount_is_turned_away_rather_than_tiered(self, api):
        """PRD §2.9: "39. **Discount hard cap** — the computed `discount_pct` must not
        exceed 35.00 percent. No role may approve past the cap, so the request is refused
        outright rather than routed to a tier. Applies to discount-approval creation, the
        discount decision and discount revision. Failure: `ERR_DISCOUNT_CAP_EXCEEDED`
        (422)."

        Design: Corner/validations/rate_above_standard_and_hard_cap_bound_the_discount_window
        """
        _, demand = self._unstaffed_qualified_demand(api)
        version = fixtures.demand_version(api, demand["id"])

        # round(100 * (250.00 - 150.00) / 250.00, 2) == 40.00
        validate_error(
            api.create_discount_approval(
                factories.discount_approval_payload(demand["id"], 150.00, version),
                SALES_LEAD,
            ),
            ApiErrorId.ERR_DISCOUNT_CAP_EXCEEDED,
            422,
        )

        _, approvals_meta = validate_paginated(api.list_discount_approvals(SALES_LEAD))
        assert approvals_meta["total_count"] == 0
        assert fixtures.demand_version(api, demand["id"]) == version

    def test_exactly_five_percent_auto_approves_at_the_seventh_step(self, api):
        """PRD §3.7: "The seventh step decides the row's `status`: when `required_tier` came
        out of the sixth step as `NONE`, the approval is created already `APPROVED` with
        `decided_by_user_id` set to the literal string `SYSTEM_AUTO` and the demand's full
        rate cascade is applied immediately; in every other case the row is created
        `PENDING`."

        Design: Corner/validations/rate_above_standard_and_hard_cap_bound_the_discount_window
        """
        _, demand = self._unstaffed_qualified_demand(api)

        # round(100 * (250.00 - 237.50) / 250.00, 2) == 5.00, the top of tier NONE.
        approval = fixtures.request_discount(api, demand["id"], 237.50)
        assert approval["discount_pct"] == pytest.approx(5.00, abs=0.005)
        assert approval["required_tier"] == ApprovalTier.NONE
        assert approval["tier_escalated"] is False
        assert approval["status"] == ApprovalStatus.APPROVED
        assert approval["decided_by_user_id"] == "SYSTEM_AUTO"
        assert approval["provisional_realization_pct"] == pytest.approx(95.00, abs=0.005)

        after = fixtures.read_demand(api, demand["id"])
        assert after["approved_rate_usd_per_hour"] == pytest.approx(237.50, abs=0.01)
        assert after["effective_rate_usd_per_hour"] == pytest.approx(237.50, abs=0.01)
        assert after["booked_realization_pct"] == pytest.approx(95.00, abs=0.005)

        _, approvals_meta = validate_paginated(api.list_discount_approvals(SALES_LEAD))
        assert approvals_meta["total_count"] == 1


class TestTheApprovalNegotiationCycle:
    @staticmethod
    def _pending_finance_tier_request(api):
        """A 200.00 request on a 250.00 demand: 20.00% discount, tier L2_FINANCE,
        projected margin 60.00 against the 80.00 level floor."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        demand = fixtures.qualified_demand(
            api,
            world,
            min_proficiency_level=3,
            required_fte=1.00,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        approval = fixtures.request_discount(api, demand["id"], 200.00, headers=SALES_LEAD)
        return world, demand, approval

    def test_the_requesters_own_identity_outranks_the_tier_failure(self, api):
        """PRD §2.9: "19. **Segregation of duties** — the user deciding a discount approval
        must differ from its `requested_by_user_id`, and the user deciding a separation must
        differ from the spell's `separation_proposed_by_user_id`. Applies to the discount
        decision and the separation decision. Failure: `ERR_SELF_APPROVAL_FORBIDDEN` (403)."

        Design: Corner/validations/approval_cycle_enforces_duties_tier_revision_and_terminality
        """
        _, _, approval = self._pending_finance_tier_request(api)
        assert approval["status"] == ApprovalStatus.PENDING
        assert approval["required_tier"] == ApprovalTier.L2_FINANCE
        assert approval["tier_escalated"] is False
        assert approval["requested_by_user_id"] == SALES_LEAD_USER_ID
        assert approval["revision_count"] == 0

        # A PracticePartner wearing the requester's own X-User-ID: rung 19 wins even
        # though this caller also fails the L2_FINANCE tier at rung 20.
        validate_error(
            api.decide_discount_approval(
                approval["id"],
                "APPROVED",
                make_practice_partner_headers(SALES_LEAD_USER_ID),
            ),
            ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN,
            403,
        )
        still = fixtures.read_approval(api, approval["id"])
        assert still["status"] == ApprovalStatus.PENDING
        assert still["decided_by_user_id"] is None

    def test_a_partner_may_not_decide_a_finance_tier_row(self, api):
        """PRD §2.9: "20. **Approval tier authority** — the caller's role must satisfy the
        approval's `required_tier`. Applies to the discount decision only. Failure:
        `ERR_APPROVAL_TIER_INSUFFICIENT` (403)."

        Design: Corner/validations/approval_cycle_enforces_duties_tier_revision_and_terminality
        """
        _, demand, approval = self._pending_finance_tier_request(api)

        validate_error(
            api.decide_discount_approval(approval["id"], "APPROVED", PRACTICE_PARTNER),
            ApiErrorId.ERR_APPROVAL_TIER_INSUFFICIENT,
            403,
        )
        still = fixtures.read_approval(api, approval["id"])
        assert still["status"] == ApprovalStatus.PENDING
        assert still["decided_by_user_id"] is None
        assert PRACTICE_PARTNER_USER_ID != still["requested_by_user_id"]
        assert fixtures.read_demand(api, demand["id"])["approved_rate_usd_per_hour"] is None

    def test_the_rejected_row_reopens_only_on_a_higher_rate(self, api):
        """PRD §3.7: "The row must be `REJECTED`, and the new rate must be strictly greater
        than the rate currently stored on the row — a revision must give ground on price —
        else `ERR_REVISION_NOT_HIGHER`."

        Design: Corner/validations/approval_cycle_enforces_duties_tier_revision_and_terminality
        """
        _, demand, approval = self._pending_finance_tier_request(api)

        rejected = fixtures.decide_discount(
            api, approval["id"], "REJECTED", headers=FINANCE_CONTROLLER
        )
        assert rejected["status"] == ApprovalStatus.REJECTED
        assert rejected["decided_by_user_id"] == FINANCE_CONTROLLER_USER_ID
        assert fixtures.read_demand(api, demand["id"])["approved_rate_usd_per_hour"] is None

        validate_error(
            api.revise_discount_approval(approval["id"], 190.00, SALES_LEAD_2),
            ApiErrorId.ERR_REVISION_NOT_HIGHER,
            422,
        )
        assert (
            fixtures.read_approval(api, approval["id"])["status"]
            == ApprovalStatus.REJECTED
        )

        revised = fixtures.revise_discount(api, approval["id"], 210.00, headers=SALES_LEAD_2)
        assert revised["status"] == ApprovalStatus.PENDING
        assert revised["revision_count"] == 1
        # round(100 * (250.00 - 210.00) / 250.00, 2) == 16.00, still above 15.00.
        assert revised["discount_pct"] == pytest.approx(16.00, abs=0.005)
        assert revised["required_tier"] == ApprovalTier.L2_FINANCE
        assert revised["decided_by_user_id"] is None
        assert revised["requested_by_user_id"] == SALES_LEAD_2_USER_ID

    def test_the_approved_row_is_terminal_for_both_verbs(self, api):
        """PRD §3.7: "Deciding a row that is not `PENDING`, or revising one that is
        `PENDING` or already `APPROVED`, is `ERR_APPROVAL_STATE_INVALID`."

        Design: Corner/validations/approval_cycle_enforces_duties_tier_revision_and_terminality
        """
        _, demand, approval = self._pending_finance_tier_request(api)
        fixtures.decide_discount(
            api, approval["id"], "REJECTED", headers=FINANCE_CONTROLLER
        )
        fixtures.revise_discount(api, approval["id"], 210.00, headers=SALES_LEAD_2)

        approved = fixtures.decide_discount(
            api, approval["id"], "APPROVED", headers=FINANCE_CONTROLLER
        )
        assert approved["status"] == ApprovalStatus.APPROVED

        after = fixtures.read_demand(api, demand["id"])
        assert after["approved_rate_usd_per_hour"] == pytest.approx(210.00, abs=0.01)
        assert after["effective_rate_usd_per_hour"] == pytest.approx(210.00, abs=0.01)
        assert after["booked_realization_pct"] == pytest.approx(84.00, abs=0.005)

        validate_error(
            api.decide_discount_approval(approval["id"], "REJECTED", FINANCE_CONTROLLER),
            ApiErrorId.ERR_APPROVAL_STATE_INVALID,
            409,
        )
        validate_error(
            api.revise_discount_approval(approval["id"], 220.00, SALES_LEAD_2),
            ApiErrorId.ERR_APPROVAL_STATE_INVALID,
            409,
        )
        assert (
            fixtures.read_approval(api, approval["id"])["status"]
            == ApprovalStatus.APPROVED
        )


class TestFirmEligibilityIsRecheckedAtApprove:
    @staticmethod
    def _one_external_demand_and_three_firms(api):
        """An EXTERNAL demand for 2.00 FTE in an NA group whose cap is 100.00, plus a
        PENDING NA firm, an APPROVED EMEA firm and an APPROVED NA firm."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03, external_sourcing_cap_pct=100.00)
        demand = fixtures.qualified_demand(
            api,
            world,
            staffing_mode="EXTERNAL",
            required_fte=2.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        firms = {
            "pending": fixtures.create_firm(
                api,
                name="Pending Partners",
                geo_code="NA",
                max_concurrent_placements=2,
                pass_through_rate_usd_per_hour=150.00,
                approval_status=FirmApprovalStatus.PENDING,
            ),
            "foreign": fixtures.create_firm(
                api,
                name="Continental Partners",
                geo_code="EMEA",
                max_concurrent_placements=2,
                pass_through_rate_usd_per_hour=150.00,
                approval_status=FirmApprovalStatus.APPROVED,
            ),
            "eligible": fixtures.create_firm(
                api,
                name="NorthStar Partners",
                geo_code="NA",
                max_concurrent_placements=2,
                pass_through_rate_usd_per_hour=150.00,
                approval_status=FirmApprovalStatus.APPROVED,
            ),
        }
        return world, demand, firms

    def test_an_unvetted_firm_and_a_foreign_firm_are_both_turned_away(self, api):
        """PRD §2.9: "37. **Firm vetting** — the firm's `approval_status` must be `APPROVED`
        (a `PENDING` or `SUSPENDED` firm may not be used) and the firm's `geo_code` must
        equal the demand's practice group's `geography_code`. Applies to external-placement
        request and placement approval. Failure: `ERR_FIRM_NOT_APPROVED` (409)."

        Design: Corner/validations/firm_approval_is_rechecked_at_approve_and_placements_are_single_shot
        """
        _, demand, firms = self._one_external_demand_and_three_firms(api)

        for key in ("pending", "foreign"):
            validate_error(
                api.create_placement(
                    factories.placement_payload(
                        firms[key]["id"],
                        demand["id"],
                        fte=1.00,
                        start_date="2026-08-17",
                        end_date="2026-08-28",
                    ),
                    RESOURCE_MANAGER,
                ),
                ApiErrorId.ERR_FIRM_NOT_APPROVED,
                409,
            )
        _, meta = validate_paginated(
            api.list_placements(RESOURCE_MANAGER, {"demand_opportunity_id": demand["id"]})
        )
        assert meta["total_count"] == 0

        legal = fixtures.create_placement(
            api,
            firms["eligible"]["id"],
            demand["id"],
            fte=1.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
        )
        assert legal["status"] == PlacementStatus.REQUESTED
        assert legal["bill_rate_usd_per_hour"] == pytest.approx(0.00, abs=0.01)

    def test_a_suspension_landing_after_the_create_is_caught_at_the_approve(self, api):
        """PRD §3.6: "The firm's `approval_status` must still be `APPROVED`."

        Design: Corner/validations/firm_approval_is_rechecked_at_approve_and_placements_are_single_shot
        """
        _, demand, firms = self._one_external_demand_and_three_firms(api)
        placement = fixtures.create_placement(
            api,
            firms["eligible"]["id"],
            demand["id"],
            fte=1.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
        )

        suspended = validate_success(
            api.patch_firm(
                firms["eligible"]["id"],
                {"approval_status": FirmApprovalStatus.SUSPENDED},
                PRACTICE_PARTNER,
            ),
            200,
        )
        assert suspended["approval_status"] == FirmApprovalStatus.SUSPENDED

        validate_error(
            api.approve_placement(placement["id"], PRACTICE_PARTNER),
            ApiErrorId.ERR_FIRM_NOT_APPROVED,
            409,
        )
        assert (
            fixtures.read_placement(api, placement["id"])["status"]
            == PlacementStatus.REQUESTED
        )
        assert fixtures.read_demand(api, demand["id"])[
            "covered_external_fte"
        ] == pytest.approx(0.00, abs=0.005)

    def test_approve_and_terminate_each_refuse_their_own_repeat(self, api):
        """PRD §3.6: "Approving anything other than a `REQUESTED` row, or terminating a
        `REQUESTED` or already-`TERMINATED` row, is `ERR_PLACEMENT_STATE_INVALID`."

        Design: Corner/validations/firm_approval_is_rechecked_at_approve_and_placements_are_single_shot
        """
        _, demand, firms = self._one_external_demand_and_three_firms(api)
        firm_id = firms["eligible"]["id"]
        placement = fixtures.create_placement(
            api,
            firm_id,
            demand["id"],
            fte=1.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
        )

        approved = fixtures.approve_placement(api, placement["id"])
        assert approved["status"] == PlacementStatus.APPROVED
        assert approved["bill_rate_usd_per_hour"] == pytest.approx(250.00, abs=0.01)
        covered = fixtures.read_demand(api, demand["id"])
        assert covered["covered_external_fte"] == pytest.approx(1.00, abs=0.005)
        assert covered["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert covered["staffing_status"] == StaffingStatus.PARTIALLY_COVERED

        validate_error(
            api.approve_placement(placement["id"], PRACTICE_PARTNER),
            ApiErrorId.ERR_PLACEMENT_STATE_INVALID,
            409,
        )

        terminated = fixtures.terminate_placement(
            api, placement["id"], reason="client deferred"
        )
        assert terminated["status"] == PlacementStatus.TERMINATED
        assert terminated["terminated_on"] == "2026-08-03"

        validate_error(
            api.terminate_placement(placement["id"], PRACTICE_PARTNER, reason="again"),
            ApiErrorId.ERR_PLACEMENT_STATE_INVALID,
            409,
        )

        restored = fixtures.read_demand(api, demand["id"])
        assert restored["covered_external_fte"] == pytest.approx(0.00, abs=0.005)
        assert restored["open_fte"] == pytest.approx(2.00, abs=0.005)
        assert restored["staffing_status"] == StaffingStatus.EXTERNAL_SOURCING
        assert fixtures.read_firm(api, firm_id)["active_placements_count"] == 0


class TestPostureAndCapGuardDifferentMoments:
    @staticmethod
    def _a_frozen_group_and_a_capped_group(api):
        """One group whose whole headcount is benched (own_bench_ratio 1.0000, FROZEN) and
        one empty group at the default 20.00 percent cap, each carrying an EXTERNAL demand
        for 2.00 FTE."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03, group_name="Frozen Practice NA")
        for name in ("Bench One", "Bench Two"):
            fixtures.hire(api, world, full_name=name, proficiency_level=None)
        world["capped"] = fixtures.create_group(
            api, name="Capped Practice NA", geography_code="NA"
        )
        firm = fixtures.create_firm(
            api,
            name="NorthStar Partners",
            geo_code="NA",
            max_concurrent_placements=5,
            pass_through_rate_usd_per_hour=150.00,
            approval_status=FirmApprovalStatus.APPROVED,
        )
        demands = {}
        for key, group_key, client in (
            ("frozen", "group", "Frozen Client"),
            ("capped", "capped", "Capped Client"),
        ):
            demands[key] = fixtures.qualified_demand(
                api,
                world,
                staffing_mode="EXTERNAL",
                group_key=group_key,
                client_name=client,
                required_fte=2.00,
                start_date="2026-08-17",
                end_date="2026-08-28",
                standard_rate_usd_per_hour=250.00,
                requested_rate_usd_per_hour=250.00,
            )
        return world, demands, firm

    def test_a_frozen_practice_admits_no_placement_at_all(self, api):
        """PRD §2.9: "42. **Frozen posture** — the demand's practice group `posture` must not
        be `FROZEN` for any external-sourcing write; a `FROZEN` posture admits no carve-out
        of any kind. Applies to external-placement request and placement approval. Failure:
        `ERR_PRACTICE_POSTURE_FROZEN` (409)."

        Design: Corner/validations/frozen_posture_blocks_creation_while_the_cap_blocks_approval
        """
        world, demands, firm = self._a_frozen_group_and_a_capped_group(api)

        frozen_group = fixtures.read_group(api, world["group"]["id"])
        assert frozen_group["own_bench_ratio"] == pytest.approx(1.0000, abs=0.00005)
        assert frozen_group["posture"] == Posture.FROZEN
        capped_group = fixtures.read_group(api, world["capped"]["id"])
        assert capped_group["own_bench_ratio"] == pytest.approx(0.0000, abs=0.00005)
        assert capped_group["posture"] == Posture.OPEN
        # The 0.5000 scarcity index would not have supplied a carve-out either.
        assert fixtures.read_skill(api, world["skill"]["id"])[
            "scarcity_index"
        ] == pytest.approx(0.5000, abs=0.00005)

        validate_error(
            api.create_placement(
                factories.placement_payload(
                    firm["id"],
                    demands["frozen"]["id"],
                    fte=1.00,
                    start_date="2026-08-17",
                    end_date="2026-08-28",
                ),
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_PRACTICE_POSTURE_FROZEN,
            409,
        )
        _, meta = validate_paginated(
            api.list_placements(
                RESOURCE_MANAGER, {"demand_opportunity_id": demands["frozen"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_the_cap_is_examined_only_at_approve_and_admits_the_exact_share(self, api):
        """PRD §2.9: "44. **External sourcing cap** — approving the placement must keep the
        group's external coverage share at or below its `external_sourcing_cap_pct`. Applies
        to placement approval. Failure: `ERR_EXTERNAL_SOURCING_CAP_EXCEEDED` (422)."

        Design: Corner/validations/frozen_posture_blocks_creation_while_the_cap_blocks_approval
        """
        _, demands, firm = self._a_frozen_group_and_a_capped_group(api)
        demand_id = demands["capped"]["id"]

        big = fixtures.create_placement(
            api,
            firm["id"],
            demand_id,
            fte=1.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
        )
        assert big["status"] == PlacementStatus.REQUESTED

        # round((0.00 + 1.00) / 2.00, 4) == 0.5000, well past 20.00 / 100.
        validate_error(
            api.approve_placement(big["id"], PRACTICE_PARTNER),
            ApiErrorId.ERR_EXTERNAL_SOURCING_CAP_EXCEEDED,
            422,
        )

        # round((0.00 + 0.40) / 2.00, 4) == 0.2000, exactly the cap.
        small = fixtures.create_placement(
            api,
            firm["id"],
            demand_id,
            fte=0.40,
            start_date="2026-08-17",
            end_date="2026-08-28",
        )
        assert fixtures.approve_placement(api, small["id"])["status"] == PlacementStatus.APPROVED

        after = fixtures.read_demand(api, demand_id)
        assert after["covered_external_fte"] == pytest.approx(0.40, abs=0.005)
        assert after["open_fte"] == pytest.approx(1.60, abs=0.005)
        assert fixtures.read_placement(api, big["id"])["status"] == PlacementStatus.REQUESTED


class TestASingleCohortSeat:
    @staticmethod
    def _two_escalated_consultants_and_one_seat(api):
        """Two never-staffed consultants at ESCALATED_L1 and a cohort with room for one."""
        world = fixtures.base_world(api, clock="2026-08-01T00:00:00Z")
        first = fixtures.hire(api, world, full_name="Bench One", proficiency_level=None)
        second = fixtures.hire(api, world, full_name="Bench Two", proficiency_level=None)
        fixtures.advance_clock_and_run(api, "2026-08-15T00:00:00Z")
        program = fixtures.create_program(
            api,
            world["skill"]["id"],
            target_proficiency_level=5,
            cohort_start_on="2026-09-01",
            cohort_end_on="2026-09-30",
            seat_capacity=1,
        )
        assert program["seats_taken"] == 0
        return world, first["consultant"], second["consultant"], program

    def test_the_second_candidate_finds_the_seat_already_taken(self, api):
        """PRD §2.9: "30. **Cohort capacity** — `seats_taken` must be strictly below
        `seat_capacity` at the moment of enrolment. Applies to cohort enrolment. Failure:
        `ERR_COHORT_CAPACITY_EXCEEDED` (409)."

        Design: Corner/validations/cohort_seats_are_finite_and_a_reskilling_spell_cannot_re_enrol
        """
        _, first, second, program = self._two_escalated_consultants_and_one_seat(api)
        assert (
            fixtures.open_spell_of(api, second["id"])["state"]
            == BenchSpellState.ESCALATED_L1
        )

        enrolled = fixtures.enrol(api, program["id"], first["id"])
        assert enrolled["state"] == BenchSpellState.RESKILLING
        assert enrolled["reskilling_program_id"] == program["id"]
        assert fixtures.read_program(api, program["id"])["seats_taken"] == 1
        assert (
            fixtures.read_consultant(api, first["id"])["availability_status"]
            == AvailabilityStatus.RESKILLING
        )

        validate_error(
            api.enrol_in_program(program["id"], second["id"], RESOURCE_MANAGER),
            ApiErrorId.ERR_COHORT_CAPACITY_EXCEEDED,
            409,
        )
        assert fixtures.read_program(api, program["id"])["seats_taken"] == 1
        assert (
            fixtures.open_spell_of(api, second["id"])["state"]
            == BenchSpellState.ESCALATED_L1
        )
        assert (
            fixtures.read_consultant(api, second["id"])["availability_status"]
            == AvailabilityStatus.BENCH
        )

    def test_the_enrolled_spell_is_refused_for_its_state_not_for_the_seat(self, api):
        """PRD §2.9: "10. **Bench spell state** — cohort enrolment requires `ESCALATED_L1` or
        `ESCALATED_L2`; internal-project placement requires `ESCALATED_L1` or `ESCALATED_L2`;
        a separation proposal requires `ESCALATED_L2`; a separation decision requires
        `SEPARATION_PROPOSED`. A `CLOSED` or `SEPARATED` spell accepts nothing at all.
        Failure: `ERR_BENCH_SPELL_STATE_INVALID` (409)."

        Design: Corner/validations/cohort_seats_are_finite_and_a_reskilling_spell_cannot_re_enrol
        """
        _, first, _, program = self._two_escalated_consultants_and_one_seat(api)
        fixtures.enrol(api, program["id"], first["id"])

        # The seat is also full, but rung 10 sits above rung 30 on the ladder.
        validate_error(
            api.enrol_in_program(program["id"], first["id"], RESOURCE_MANAGER),
            ApiErrorId.ERR_BENCH_SPELL_STATE_INVALID,
            409,
        )
        assert fixtures.read_program(api, program["id"])["seats_taken"] == 1
        assert (
            fixtures.open_spell_of(api, first["id"])["state"]
            == BenchSpellState.RESKILLING
        )


class TestTheCooldownBelongsToTheNewCohort:
    @staticmethod
    def _a_graduate_re_escalated_in_october(api):
        """A consultant who graduated from a cohort ending 2026-09-30 and has climbed back
        to ESCALATED_L1 by 2026-10-14."""
        world = fixtures.base_world(api, clock="2026-08-01T00:00:00Z")
        staff = fixtures.hire(api, world, full_name="Bench One", proficiency_level=None)
        consultant_id = staff["consultant"]["id"]
        fixtures.advance_clock_and_run(api, "2026-08-15T00:00:00Z")
        first_program = fixtures.create_program(
            api,
            world["skill"]["id"],
            target_proficiency_level=5,
            cohort_start_on="2026-09-01",
            cohort_end_on="2026-09-30",
            seat_capacity=2,
        )
        fixtures.enrol(api, first_program["id"], consultant_id)
        fixtures.advance_clock_and_run(api, INSTANT_SEP_30)
        graduated = fixtures.complete_program(api, first_program["id"])
        assert graduated["status"] == ProgramStatus.COMPLETED
        fixtures.advance_clock_and_run(api, "2026-10-14T00:00:00Z")
        spell = fixtures.open_spell_of(api, consultant_id)
        assert spell["state"] == BenchSpellState.ESCALATED_L1
        assert spell["age_reset_on"] == "2026-09-30"
        assert spell["escalation_count"] == 2
        return world, consultant_id, spell

    @staticmethod
    def _candidate_cohort(api, world, cohort_start_on):
        return fixtures.create_program(
            api,
            world["skill"]["id"],
            target_proficiency_level=5,
            cohort_start_on=cohort_start_on,
            cohort_end_on="2026-10-31",
            seat_capacity=2,
            cooldown_days=3,
        )

    def test_the_boundary_day_itself_is_still_too_early(self, api):
        """PRD §2.9: "29. **Reskilling cooldown** — `cohort_start_on` must be strictly later
        than the `cohort_end_on` of the consultant's most recent `COMPLETED` programme
        advanced by the *new* programme's `cooldown_days`. Applies to cohort enrolment.
        Failure: `ERR_RESKILLING_COOLDOWN_ACTIVE` (409)."

        Design: Corner/validations/cooldown_is_measured_against_the_new_programmes_own_window
        """
        world, consultant_id, _ = self._a_graduate_re_escalated_in_october(api)

        # 2026-09-30 advanced by 3 days is 2026-10-03; neither 10-01 nor 10-03 clears it.
        for cohort_start_on in ("2026-10-01", "2026-10-03"):
            candidate = self._candidate_cohort(api, world, cohort_start_on)
            validate_error(
                api.enrol_in_program(candidate["id"], consultant_id, RESOURCE_MANAGER),
                ApiErrorId.ERR_RESKILLING_COOLDOWN_ACTIVE,
                409,
            )
            assert fixtures.read_program(api, candidate["id"])["seats_taken"] == 0
        assert (
            fixtures.open_spell_of(api, consultant_id)["state"]
            == BenchSpellState.ESCALATED_L1
        )

    def test_one_day_past_the_boundary_admits_the_enrolment(self, api):
        """PRD §3.8: "Note which cooldown governs: the waiting period is a property of the
        cohort being joined, not of the one just finished."

        Design: Corner/validations/cooldown_is_measured_against_the_new_programmes_own_window
        """
        world, consultant_id, _ = self._a_graduate_re_escalated_in_october(api)
        candidate = self._candidate_cohort(api, world, "2026-10-04")

        enrolled = fixtures.enrol(api, candidate["id"], consultant_id)
        assert enrolled["state"] == BenchSpellState.RESKILLING
        assert enrolled["reskilling_program_id"] == candidate["id"]
        assert fixtures.read_program(api, candidate["id"])["seats_taken"] == 1


class TestTheSeparationDecisionNeedsTwoThings:
    @staticmethod
    def _proposed_spell_of_a_partly_committed_consultant(api):
        """A consultant carrying a live 40% BILLABLE assignment — enough to keep
        `allocated_pct` at 40.00, too little to leave the bench — proposed for separation
        by the ResourceManager u_rm_1.

        Deviation from the design recipe: the design confirms a [2026-09-01, 2026-10-01)
        assignment while the clock sits at 2026-08-01, yet asserts `allocated_pct == 40.00`.
        PRD §3.2 sums only assignments "whose effective interval contains the logical clock
        date", so that future row would contribute 0.00 and the APPROVED decision would
        succeed. The interval is therefore opened at 2026-08-01 so the asserted 40.00 is
        genuinely PRD-derived at every clock this test uses.
        """
        world = fixtures.base_world(api, clock="2026-08-01T00:00:00Z")
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=120.00,
        )
        consultant_id = staff["consultant"]["id"]
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=1.00,
            start_date="2026-08-01",
            end_date="2026-09-30",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        fixtures.confirmed_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=40.00,
            start_date="2026-08-01",
            end_date="2026-10-01",
        )
        committed = fixtures.read_consultant(api, consultant_id)
        assert committed["allocated_pct"] == pytest.approx(40.00, abs=0.005)
        assert committed["availability_status"] == AvailabilityStatus.BENCH

        spell = fixtures.bench_spell_at_l2(
            api,
            world,
            consultant_id,
            l1_instant="2026-08-15T00:00:00Z",
            l2_instant=INSTANT_AUG_31,
        )
        assert spell["state"] == BenchSpellState.ESCALATED_L2
        assert spell["escalation_count"] == 2

        proposed = validate_success(
            api.propose_separation(
                spell["id"], RESOURCE_MANAGER, rationale="two escalations on the bench"
            ),
            200,
        )
        assert proposed["state"] == BenchSpellState.SEPARATION_PROPOSED
        assert proposed["separation_proposed_by_user_id"] == RESOURCE_MANAGER_USER_ID
        return world, consultant_id, spell

    def test_the_proposers_own_identity_is_named_before_the_allocation(self, api):
        """PRD §2.9: "19. **Segregation of duties** — the user deciding a discount approval
        must differ from its `requested_by_user_id`, and the user deciding a separation must
        differ from the spell's `separation_proposed_by_user_id`. Applies to the discount
        decision and the separation decision. Failure: `ERR_SELF_APPROVAL_FORBIDDEN` (403)."

        Design: Corner/validations/separation_decision_needs_a_second_user_and_a_zero_allocation
        """
        _, _, spell = self._proposed_spell_of_a_partly_committed_consultant(api)

        # This one call breaks rungs 19 and 22 at once; the lower number wins.
        validate_error(
            api.decide_separation(
                spell["id"],
                SeparationDecision.APPROVED,
                make_practice_partner_headers(RESOURCE_MANAGER_USER_ID),
            ),
            ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN,
            403,
        )
        assert (
            fixtures.read_spell(api, spell["id"])["state"]
            == BenchSpellState.SEPARATION_PROPOSED
        )

    def test_a_second_user_still_cannot_approve_a_committed_consultant(self, api):
        """PRD §2.9: "22. **Separation eligibility** — a separation proposal requires the
        spell's `escalation_count` to be at least 2, and an `APPROVED` separation decision
        requires the consultant's `allocated_pct` to be exactly 0.00. Applies to the
        separation proposal and the separation decision. Failure:
        `ERR_SEPARATION_NOT_ELIGIBLE` (409)."

        Design: Corner/validations/separation_decision_needs_a_second_user_and_a_zero_allocation
        """
        _, consultant_id, spell = self._proposed_spell_of_a_partly_committed_consultant(api)

        validate_error(
            api.decide_separation(
                spell["id"], SeparationDecision.APPROVED, PRACTICE_PARTNER
            ),
            ApiErrorId.ERR_SEPARATION_NOT_ELIGIBLE,
            409,
        )
        untouched = fixtures.read_spell(api, spell["id"])
        assert untouched["state"] == BenchSpellState.SEPARATION_PROPOSED
        assert untouched["separation_decision"] is None
        consultant = fixtures.read_consultant(api, consultant_id)
        assert consultant["availability_status"] == AvailabilityStatus.BENCH
        assert consultant["separated_on"] is None

    def test_the_rejection_carries_no_allocation_precondition(self, api):
        """PRD §3.8: "A `REJECTED` decision instead returns the `state` to `ESCALATED_L2`
        with `escalation_count` untouched and `escalated_l2_count` unchanged, sets
        `separation_decision` to `REJECTED`, and stamps `separation_decided_by_user_id`."

        Design: Corner/validations/separation_decision_needs_a_second_user_and_a_zero_allocation
        """
        world, consultant_id, spell = self._proposed_spell_of_a_partly_committed_consultant(
            api
        )

        decided = validate_success(
            api.decide_separation(
                spell["id"], SeparationDecision.REJECTED, PRACTICE_PARTNER
            ),
            200,
        )
        assert decided["state"] == BenchSpellState.ESCALATED_L2
        assert decided["separation_decision"] == SeparationDecision.REJECTED
        assert decided["separation_decided_by_user_id"] == PRACTICE_PARTNER_USER_ID
        assert decided["escalation_count"] == 2

        consultant = fixtures.read_consultant(api, consultant_id)
        assert consultant["availability_status"] == AvailabilityStatus.BENCH
        assert consultant["separated_on"] is None
        assert fixtures.read_group(api, world["group"]["id"])["escalated_l2_count"] == 1


class TestExactLimitsAreAdmitted:
    def test_a_discount_of_exactly_thirty_five_percent_is_created_not_refused(self, api):
        """PRD §2.9: "39. **Discount hard cap** — the computed `discount_pct` must not exceed
        35.00 percent. No role may approve past the cap, so the request is refused outright
        rather than routed to a tier. Applies to discount-approval creation, the discount
        decision and discount revision. Failure: `ERR_DISCOUNT_CAP_EXCEEDED` (422)."
        PRD §3.7: "The fifth step routes the approval to a tier by `discount_pct` alone:
        `NONE` when the discount is at most 5.00 percent, `L1_PRACTICE_PARTNER` when it is
        above 5.00 and at most 15.00 percent, and `L2_FINANCE` when it is above 15.00
        percent."

        Design: Corner/validations/rules_at_their_exact_limits_let_the_operation_through
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        demand = fixtures.qualified_demand(
            api,
            world,
            staffing_mode=None,
            min_proficiency_level=3,
            required_fte=1.00,
            start_date="2026-09-01",
            end_date="2026-09-30",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )

        # round(100 * (250.00 - 162.50) / 250.00, 2) == 35.00, exactly the cap.
        approval = fixtures.request_discount(api, demand["id"], 162.50)
        assert approval["discount_pct"] == pytest.approx(35.00, abs=0.005)
        assert approval["status"] == ApprovalStatus.PENDING
        assert approval["required_tier"] == ApprovalTier.L2_FINANCE
        assert approval["tier_escalated"] is False
        assert approval["provisional_realization_pct"] == pytest.approx(65.00, abs=0.005)
        # No CONFIRMED assignment exists, so the level floor at min_proficiency_level 3
        # supplies 80.00: round(100 * (162.50 - 80.00) / 162.50, 2) == 50.77.
        assert approval["projected_margin_pct"] == pytest.approx(50.77, abs=0.005)

    def test_a_period_ending_one_day_before_the_clock_closes_cleanly(self, api):
        """PRD §3.9: "The period must be `OPEN` and its `period_end_on` must be strictly
        before the logical clock date — closing a period that is already `CLOSED`, or one
        that has not finished, is `ERR_PERIOD_STATE_INVALID` — and a period whose
        `hour_overallocated` is true cannot be closed at all, which is
        `ERR_HOUR_OVERALLOCATION`."
        PRD §3.9: "Both are persisted side by side, and `utilization_pct_of_record` is the
        available-basis figure while the period is `OPEN` and the target-basis figure once it
        is `CLOSED`."

        Design: Corner/validations/rules_at_their_exact_limits_let_the_operation_through
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=None,
            cost_rate_usd_per_hour=120.00,
        )
        consultant_id = staff["consultant"]["id"]
        period = fixtures.create_period(api, consultant_id, "2026-08-03", "2026-08-28")
        assert period["holiday_hours"] == pytest.approx(0.00, abs=0.01)
        assert period["capacity_hours"] == pytest.approx(160.00, abs=0.01)
        assert period["net_available_hours"] == pytest.approx(160.00, abs=0.01)
        assert period["target_utilization_pct"] == pytest.approx(75.00, abs=0.005)
        assert period["status"] == PeriodStatus.OPEN

        fixtures.set_clock(api, INSTANT_AUG_29)
        closed = fixtures.close_period(api, consultant_id, period["id"])
        assert closed["status"] == PeriodStatus.CLOSED
        assert closed["hour_overallocated"] is False
        assert closed["utilization_pct_of_record"] == pytest.approx(0.00, abs=0.005)
        assert closed["variance_pp"] == pytest.approx(-75.00, abs=0.005)
        assert closed["bench_hours"] == pytest.approx(160.00, abs=0.01)
