"""Cross-cutting layers: optimistic concurrency, selector re-evaluation, immediacy."""

import pytest

from test_helpers import (
    FINANCE_CONTROLLER,
    PRACTICE_PARTNER,
    RESOURCE_MANAGER,
    SALES_LEAD,
    ApiErrorId,
    ApprovalStatus,
    ApprovalTier,
    AssignmentStatus,
    AvailabilityStatus,
    Posture,
    StaffingStatus,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import INSTANT_AUG_03, INSTANT_AUG_16, INSTANT_AUG_17

MISSING_CONSULTANT = "00000000-0000-4000-8000-0000000000e1"
MISSING_DEMAND = "00000000-0000-4000-8000-0000000000e2"


class TestAssignmentCreateGuardsTheConsultantVersion:
    @staticmethod
    def _a_consultant_and_a_three_fte_demand(api):
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=4)
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=3.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        return world, staff["consultant"], demand

    @staticmethod
    def _proposal(consultant_id, demand_id, version):
        return factories.assignment_payload(
            consultant_id,
            demand_id,
            version,
            allocation_pct=50.00,
            start_date="2026-08-17",
            end_date="2026-08-29",
        )

    def test_the_version_observed_before_the_first_proposal_is_already_stale(self, api):
        """PRD §2.8: "**Proposing an assignment** requires a non-optional
        `expected_consultant_version` field carrying the `version` of the target `Consultant` as
        the client last observed it. If that value does not equal the consultant's current
        `version`, the create is rejected with `ERR_STALE_CONSULTANT_VERSION` (HTTP 412)."
        PRD §2.9: "7. **Optimistic concurrency** — the supplied parent-version field equals the
        parent's current `version`, per §2.8. Applies to discount-approval creation and
        assignment proposal. Deliberately evaluated *after* existence, so a request quoting both
        a missing foreign key and a stale version returns the 404, not the 412. Failure:
        `ERR_STALE_OPPORTUNITY_VERSION` or `ERR_STALE_CONSULTANT_VERSION` (412)."

        Design: Corner/cross-cutting complexity layers/assignment_create_occ_rejects_a_stale_consultant_version_and_bumps_on_every_write
        """
        _, consultant, demand = self._a_consultant_and_a_three_fte_demand(api)
        first_version = consultant["version"]
        assert first_version == 1

        first = validate_success(
            api.create_assignment(
                self._proposal(consultant["id"], demand["id"], first_version),
                RESOURCE_MANAGER,
            ),
            201,
        )
        assert first["status"] == AssignmentStatus.PROPOSED

        # Nothing about the request changed except that the consultant is now at
        # version 2, and a consultant may legitimately hold several proposals.
        validate_error(
            api.create_assignment(
                self._proposal(consultant["id"], demand["id"], first_version),
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_STALE_CONSULTANT_VERSION,
            412,
        )

        # Both defects at once: existence (rung 5) decides before the version (rung 7).
        validate_error(
            api.create_assignment(
                self._proposal(MISSING_CONSULTANT, demand["id"], first_version),
                RESOURCE_MANAGER,
            ),
            ApiErrorId.ERR_CONSULTANT_NOT_FOUND,
            404,
        )

    def test_every_accepted_proposal_bumps_the_version_and_reserves_nothing(self, api):
        """PRD §3.5: "Creating the proposal increments the consultant's `version` by one but
        changes no coverage and no allocation whatsoever — a `PROPOSED` assignment reserves
        nothing, which is precisely why this creation needs the stale-version guard instead of a
        state precondition."

        Design: Corner/cross-cutting complexity layers/assignment_create_occ_rejects_a_stale_consultant_version_and_bumps_on_every_write
        """
        _, consultant, demand = self._a_consultant_and_a_three_fte_demand(api)

        validate_success(
            api.create_assignment(
                self._proposal(consultant["id"], demand["id"], consultant["version"]),
                RESOURCE_MANAGER,
            ),
            201,
        )

        after_first = fixtures.read_consultant(api, consultant["id"])
        assert after_first["version"] == 2
        assert after_first["allocated_pct"] == pytest.approx(0.00, abs=0.005)
        assert after_first["availability_status"] == AvailabilityStatus.BENCH

        second = validate_success(
            api.create_assignment(
                self._proposal(consultant["id"], demand["id"], after_first["version"]),
                RESOURCE_MANAGER,
            ),
            201,
        )
        assert second["status"] == AssignmentStatus.PROPOSED
        assert fixtures.read_consultant(api, consultant["id"])["version"] == 3

        _, meta = validate_paginated(
            api.list_assignments(RESOURCE_MANAGER, {"consultant_id": consultant["id"]})
        )
        assert meta["total_count"] == 2
        assert fixtures.read_demand(api, demand["id"])["covered_internal_fte"] == pytest.approx(
            0.00, abs=0.005
        )


class TestDiscountCreateGuardsTheOpportunityVersion:
    @staticmethod
    def _a_qualified_demand_and_its_two_versions(api):
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        created = fixtures.create_demand(
            api,
            world["group"]["id"],
            world["skill"]["id"],
            required_fte=1.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        qualified = fixtures.qualify(api, created["id"])
        return created, qualified

    def test_qualify_is_a_write_so_the_creation_version_no_longer_holds(self, api):
        """PRD §2.8: "**Creating a discount approval** requires a non-optional
        `expected_opportunity_version` field carrying the `version` of the target
        `DemandOpportunity` as the client last observed it. If that value does not equal the
        demand's current `version`, the create is rejected with `ERR_STALE_OPPORTUNITY_VERSION`
        (HTTP 412)."
        PRD §3.3: "Qualification recomputes `weighted_fte` as `required_fte` multiplied by
        `win_probability_pct` divided by one hundred, rounded half-up to two decimals — the
        staffing-priority weight that sales visibility exposes to everyone downstream — and
        increments the demand's `version` by one."

        Design: Corner/cross-cutting complexity layers/discount_create_occ_rejects_a_stale_opportunity_version_after_qualify
        """
        created, qualified = self._a_qualified_demand_and_its_two_versions(api)
        assert created["version"] == 1
        assert qualified["version"] == 2

        validate_error(
            api.create_discount_approval(
                factories.discount_approval_payload(created["id"], 230.00, created["version"]),
                SALES_LEAD,
            ),
            ApiErrorId.ERR_STALE_OPPORTUNITY_VERSION,
            412,
        )
        _, meta = validate_paginated(api.list_discount_approvals(FINANCE_CONTROLLER))
        assert meta["total_count"] == 0

        # The stale version is not even consulted when the demand itself is unknown.
        validate_error(
            api.create_discount_approval(
                factories.discount_approval_payload(MISSING_DEMAND, 230.00, created["version"]),
                SALES_LEAD,
            ),
            ApiErrorId.ERR_OPPORTUNITY_NOT_FOUND,
            404,
        )

    def test_the_re_read_version_is_accepted_and_prices_against_the_level_floor(self, api):
        """PRD §3.7: "The first step snapshots the demand's `standard_rate_usd_per_hour` onto the
        approval row and computes `discount_pct` as one hundred multiplied by the snapshot
        standard rate less the requested rate, divided by that snapshot standard rate, rounded
        half-up to two decimals."
        PRD §3.7: "Where no such assignment exists, the **level-floor** variant applies: a policy
        proxy indexed by the demand's `min_proficiency_level`, being 45.00 at level 1, 60.00 at
        level 2, 80.00 at level 3, 105.00 at level 4 and 130.00 at level 5."
        PRD §3.7: "The fifth step routes the approval to a tier by `discount_pct` alone: `NONE`
        when the discount is at most 5.00 percent, `L1_PRACTICE_PARTNER` when it is above 5.00
        and at most 15.00 percent, and `L2_FINANCE` when it is above 15.00 percent."

        Design: Corner/cross-cutting complexity layers/discount_create_occ_rejects_a_stale_opportunity_version_after_qualify
        """
        created, qualified = self._a_qualified_demand_and_its_two_versions(api)

        approval = validate_success(
            api.create_discount_approval(
                factories.discount_approval_payload(
                    created["id"], 230.00, qualified["version"]
                ),
                SALES_LEAD,
            ),
            201,
        )
        # 100*(250.00-230.00)/250.00 = 8.00; 100*230.00/250.00 = 92.00;
        # level floor at min_proficiency_level 3 = 80.00; 100*(230-80)/230 = 65.22.
        assert approval["discount_pct"] == pytest.approx(8.00, abs=0.005)
        assert approval["provisional_realization_pct"] == pytest.approx(92.00, abs=0.005)
        assert approval["blended_cost_rate_usd_per_hour"] == pytest.approx(80.00, abs=0.01)
        assert approval["projected_margin_pct"] == pytest.approx(65.22, abs=0.005)
        assert approval["required_tier"] == ApprovalTier.L1_PRACTICE_PARTNER
        assert approval["status"] == ApprovalStatus.PENDING
        assert approval["revision_count"] == 0

        after = fixtures.read_demand(api, created["id"])
        assert after["version"] == 3
        assert after.get("approved_rate_usd_per_hour") is None
        assert after["effective_rate_usd_per_hour"] == pytest.approx(250.00, abs=0.01)


class TestTheSelectorIsReEvaluatedOnEveryCall:
    @staticmethod
    def _two_candidates_and_a_three_fte_demand(api):
        """Ada scores 0.35*1.0000 + 0.20*0.6000 + 0.15*0.5200 = 0.5480 and Grace scores
        0.35*0.8000 + 0.20*0.6000 + 0.15*0.6000 = 0.4900; neither has industry experience
        for RETAIL nor a development goal, so those two components are 0.0000 for both.

        Deviation from the design recipe: the design sets the clock to 2026-08-03 and still
        asserts that the confirmed winner reads back `ASSIGNED` at `allocated_pct` 100.00.
        PRD §3.2 sums only assignments "whose effective interval contains the logical clock
        date", so a [2026-08-17, 2026-08-29) commitment contributes 0.00 at 2026-08-03 and
        the winner would stay `BENCH`. The clock is therefore set to the window's first day,
        which leaves every match score, eligibility filter and rank untouched.
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_17)
        ada = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=5)
        grace = fixtures.hire(
            api,
            world,
            full_name="Grace Hopper",
            proficiency_level=4,
            cost_rate_usd_per_hour=100.00,
            standard_bill_rate_usd_per_hour=280.00,
        )
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=3.00,
            start_date="2026-08-17",
            end_date="2026-08-28",
            onsite_nights_per_week=2,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        return ada["consultant"], grace["consultant"], demand

    def test_the_first_run_takes_the_highest_scoring_candidate(self, api):
        """PRD §3.5: "The winner receives one new assignment with `status` at `PROPOSED`,
        `allocation_pct` of 100.00, `category` of `BILLABLE`, `start_date` equal to the demand's
        `start_date`, `end_date` equal to the day *after* the demand's `end_date` — because the
        demand's window is inclusive on the right while the assignment's is exclusive — and the
        winner's `match_score` stored on the row."

        Design: Corner/cross-cutting complexity layers/selector_re_runs_against_the_pool_as_it_stands_at_each_call
        """
        ada, _, demand = self._two_candidates_and_a_three_fte_demand(api)

        first = validate_success(api.auto_staff_demand(demand["id"], RESOURCE_MANAGER), 201)
        assert first["consultant_id"] == ada["id"]
        assert first["match_score"] == pytest.approx(0.5480, abs=0.00005)
        assert first["allocation_pct"] == pytest.approx(100.00, abs=0.005)
        assert first["status"] == AssignmentStatus.PROPOSED
        assert first["start_date"] == "2026-08-17"
        assert first["end_date"] == "2026-08-29"

        confirmed = validate_success(
            api.confirm_assignment(first["id"], RESOURCE_MANAGER), 200
        )
        assert confirmed["status"] == AssignmentStatus.CONFIRMED

        after = fixtures.read_consultant(api, ada["id"])
        assert after["allocated_pct"] == pytest.approx(100.00, abs=0.005)
        assert after["availability_status"] == AvailabilityStatus.ASSIGNED

    def test_each_later_run_re_reads_the_pool_until_it_is_empty(self, api):
        """PRD §3.5: "Fifth, they have headroom: taking the maximum, over every date in the
        demand's inclusive delivery window, of the summed `allocation_pct` of that consultant's
        `CONFIRMED` and `ACTIVE` assignments whose half-open interval contains the date, one
        hundred less that peak must be at least 100.00 — which is to say the selector only takes
        a consultant who is entirely free for the whole window, since the assignment it creates
        commits the full 100.00."
        PRD §3.5: "If the candidate set is empty the request is rejected with
        `ERR_NO_ELIGIBLE_CONSULTANT` and **nothing at all is mutated**: no assignment row, no
        `version` bump on the demand or on any consultant, and no change to coverage or
        `staffing_status`."

        Design: Corner/cross-cutting complexity layers/selector_re_runs_against_the_pool_as_it_stands_at_each_call
        """
        _, grace, demand = self._two_candidates_and_a_three_fte_demand(api)

        first = validate_success(api.auto_staff_demand(demand["id"], RESOURCE_MANAGER), 201)
        validate_success(api.confirm_assignment(first["id"], RESOURCE_MANAGER), 200)

        # The lower-scoring candidate wins only because the higher one is no longer eligible.
        second = validate_success(api.auto_staff_demand(demand["id"], RESOURCE_MANAGER), 201)
        assert second["consultant_id"] == grace["id"]
        assert second["match_score"] == pytest.approx(0.4900, abs=0.00005)
        confirmed = validate_success(
            api.confirm_assignment(second["id"], RESOURCE_MANAGER), 200
        )
        assert confirmed["status"] == AssignmentStatus.CONFIRMED

        staffed = fixtures.read_demand(api, demand["id"])
        assert staffed["covered_internal_fte"] == pytest.approx(2.00, abs=0.005)
        assert staffed["open_fte"] == pytest.approx(1.00, abs=0.005)
        assert staffed["staffing_status"] == StaffingStatus.PARTIALLY_COVERED

        validate_error(
            api.auto_staff_demand(demand["id"], RESOURCE_MANAGER),
            ApiErrorId.ERR_NO_ELIGIBLE_CONSULTANT,
            409,
        )
        _, meta = validate_paginated(
            api.list_assignments(RESOURCE_MANAGER, {"demand_opportunity_id": demand["id"]})
        )
        assert meta["total_count"] == 2


class TestEveryCascadedFieldIsReadableImmediately:
    @staticmethod
    def _one_benched_consultant_and_a_proposal_ready_to_confirm(api):
        """Deviation from the design recipe: the design puts the clock at 2026-08-03 with a
        [2026-08-17, 2026-08-29) commitment, then asserts both that the confirm leaves the
        consultant `ASSIGNED` at 100.00 and that `earned_realization_pct` stays absent. Under
        PRD §3.2 the allocation is clock-relative, so the first claim needs the clock inside
        the interval, while PRD §3.7 counts "the Monday-to-Friday dates from its `start_date`
        inclusive up to — but excluding — the earlier of its effective end and the day after
        the logical clock date", so the second needs no workday delivered. Both hold at once
        when the window opens on Saturday 2026-08-16, so that date is used throughout.
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_16)
        staff = fixtures.hire(api, world, full_name="Ada Byron", proficiency_level=4)
        demand = fixtures.qualified_demand(
            api,
            world,
            required_fte=1.00,
            start_date="2026-08-16",
            end_date="2026-08-28",
            onsite_nights_per_week=2,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        assignment = fixtures.propose_assignment(
            api,
            staff["consultant"]["id"],
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-16",
            end_date="2026-08-29",
        )
        return world, staff["consultant"], demand, assignment

    def test_the_confirm_response_and_the_very_next_reads_show_a_settled_cascade(self, api):
        """PRD §1: "First, **every derived number is recomputed inside the request that changed
        its inputs** — there is no batch reconciliation, no read-time lag, and no eventual
        consistency anywhere in the product."
        PRD §3.5: "A successful confirmation sets `status` to `CONFIRMED` and stamps
        `confirmed_on` with the logical clock date, and re-pins `bill_rate_usd_per_hour` from the
        demand's current `effective_rate_usd_per_hour` — or to 0.00 when the category is
        `INVESTMENT`."

        Design: Corner/consistency model/every_cascaded_field_is_readable_in_the_same_response_and_the_next_read
        """
        world, consultant, demand, assignment = (
            self._one_benched_consultant_and_a_proposal_ready_to_confirm(api)
        )
        assert assignment["bill_rate_usd_per_hour"] == pytest.approx(250.00, abs=0.01)

        before = fixtures.read_group(api, world["group"]["id"])
        assert before["bench_headcount"] == 1
        assert before["own_bench_ratio"] == pytest.approx(1.0000, abs=0.00005)
        assert before["posture"] == Posture.FROZEN

        confirmed = validate_success(
            api.confirm_assignment(assignment["id"], RESOURCE_MANAGER), 200
        )
        assert confirmed["status"] == AssignmentStatus.CONFIRMED
        assert confirmed["confirmed_on"] == "2026-08-16"

        settled_consultant = fixtures.read_consultant(api, consultant["id"])
        assert settled_consultant["allocated_pct"] == pytest.approx(100.00, abs=0.005)
        assert settled_consultant["availability_status"] == AvailabilityStatus.ASSIGNED

        settled_group = validate_success(
            api.get_practice_group(world["group"]["id"], PRACTICE_PARTNER), 200
        )
        assert settled_group["bench_headcount"] == 0
        assert settled_group["own_bench_ratio"] == pytest.approx(0.0000, abs=0.00005)
        assert settled_group["posture"] == Posture.OPEN

        settled_demand = fixtures.read_demand(api, demand["id"])
        assert settled_demand["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)
        assert settled_demand["open_fte"] == pytest.approx(0.00, abs=0.005)
        assert settled_demand["staffing_status"] == StaffingStatus.COVERED
        assert settled_demand.get("earned_realization_pct") is None
        # create, qualify, staffing-mode, confirm.
        assert settled_demand["version"] == 4

    def test_the_auto_approval_carries_its_own_cascade_in_its_own_response(self, api):
        """PRD §3.7: "The seventh step decides the row's `status`: when `required_tier` came out
        of the sixth step as `NONE`, the approval is created already `APPROVED` with
        `decided_by_user_id` set to the literal string `SYSTEM_AUTO` and the demand's full rate
        cascade is applied immediately; in every other case the row is created `PENDING`."
        PRD §3.7: "Hop two to three: because the effective rate changed, every assignment on the
        demand whose `status` is `PROPOSED`, `CONFIRMED` or `ACTIVE` and whose `category` is
        `BILLABLE` has its `bill_rate_usd_per_hour` re-pinned to the new effective rate, while
        `RELEASED` and `CANCELLED` rows keep their frozen values."

        Design: Corner/consistency model/every_cascaded_field_is_readable_in_the_same_response_and_the_next_read
        """
        _, _, demand, assignment = (
            self._one_benched_consultant_and_a_proposal_ready_to_confirm(api)
        )
        validate_success(api.confirm_assignment(assignment["id"], RESOURCE_MANAGER), 200)

        approval = validate_success(
            api.create_discount_approval(
                factories.discount_approval_payload(
                    demand["id"], 245.00, fixtures.demand_version(api, demand["id"])
                ),
                SALES_LEAD,
            ),
            201,
        )
        # 100*(250.00-245.00)/250.00 = 2.00, so the tier is NONE; the mix-weighted variant
        # applies because one CONFIRMED assignment exists, and with no workday delivered it
        # weights that single row by its allocation_pct, giving 120.00.
        assert approval["discount_pct"] == pytest.approx(2.00, abs=0.005)
        assert approval["required_tier"] == ApprovalTier.NONE
        assert approval["blended_cost_rate_usd_per_hour"] == pytest.approx(120.00, abs=0.01)
        assert approval["projected_margin_pct"] == pytest.approx(51.02, abs=0.005)
        assert approval["status"] == ApprovalStatus.APPROVED
        assert approval["decided_by_user_id"] == "SYSTEM_AUTO"

        repriced = fixtures.read_demand(api, demand["id"])
        assert repriced["approved_rate_usd_per_hour"] == pytest.approx(245.00, abs=0.01)
        assert repriced["effective_rate_usd_per_hour"] == pytest.approx(245.00, abs=0.01)
        assert repriced["booked_realization_pct"] == pytest.approx(98.00, abs=0.005)

        re_pinned = fixtures.read_assignment(api, assignment["id"])
        assert re_pinned["bill_rate_usd_per_hour"] == pytest.approx(245.00, abs=0.01)
