"""Two rules broken at once: the higher rung of PRD §2.9 must be the one reported."""

import pytest

from test_helpers import (
    RESOURCE_MANAGER,
    SALES_LEAD,
    ApiErrorId,
    AssignmentStatus,
    AvailabilityStatus,
    fixtures,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import INSTANT_AUG_03, UNKNOWN_UUID_ALT


class TestStateBeatsCapacity:
    @staticmethod
    def _cancelled_row_over_a_full_consultant(api):
        """A1 CONFIRMED at 100.00 percent and A2 CANCELLED over the same interval."""
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
            required_fte=2.00,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        first = fixtures.confirmed_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        second = fixtures.propose_assignment(
            api,
            consultant_id,
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        fixtures.cancel(api, second["id"], reason="duplicate request")
        return world, staff, demand, first, second

    def test_confirming_a_cancelled_row_reports_the_state_rung(self, api):
        """PRD §2.9: "9. **Assignment state** — confirmation requires `PROPOSED`;
        release requires `CONFIRMED` or `ACTIVE`; cancellation requires `PROPOSED` or
        `CONFIRMED`. A second confirmation, or a release of an already-`RELEASED` row,
        is rejected here; idempotency is **not** granted. Failure:
        `ERR_ASSIGNMENT_STATE_INVALID` (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_assignment_confirm
        """
        _, _, _, _, second = self._cancelled_row_over_a_full_consultant(api)

        response = api.confirm_assignment(second["id"], RESOURCE_MANAGER)

        # Confirming would also have driven allocation to 200.00, which is rung 32.
        error = validate_error(response, ApiErrorId.ERR_ASSIGNMENT_STATE_INVALID, 409)
        assert error["error_id"] != ApiErrorId.ERR_ALLOCATION_CAPACITY_EXCEEDED

    def test_the_refusal_leaves_every_row_exactly_as_it_was(self, api):
        """PRD §2.9: "When a single request violates several rules, exactly one error
        is returned and **no mutation of any kind occurs**."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_assignment_confirm
        """
        _, staff, demand, first, second = self._cancelled_row_over_a_full_consultant(api)

        response = api.confirm_assignment(second["id"], RESOURCE_MANAGER)
        validate_error(response, ApiErrorId.ERR_ASSIGNMENT_STATE_INVALID)

        refused = fixtures.read_assignment(api, second["id"])
        assert refused["status"] == AssignmentStatus.CANCELLED
        assert refused["confirmed_on"] is None

        untouched = fixtures.read_assignment(api, first["id"])
        assert untouched["status"] == AssignmentStatus.CONFIRMED

        consultant = fixtures.read_consultant(api, staff["consultant"]["id"])
        assert consultant["allocated_pct"] == pytest.approx(100.00, abs=0.005)

        after = fixtures.read_demand(api, demand["id"])
        assert after["covered_internal_fte"] == pytest.approx(1.00, abs=0.005)
        assert after["open_fte"] == pytest.approx(1.00, abs=0.005)


class TestAuthorisationBeatsExistence:
    def test_an_unauthorised_role_never_learns_whether_the_id_exists(self, api):
        """PRD §2.9: "2. **Authorisation** — the caller's role appears in the target
        endpoint's authorised-role list. Applies to every endpoint. Failure:
        `ERR_UNAUTHORIZED` (403)."

        Design: Difficulty/priority_pair_validation_conflict/authz_beats_existence_on_assignment_confirm
        """
        fixtures.base_world(api, clock=INSTANT_AUG_03)

        response = api.confirm_assignment(UNKNOWN_UUID_ALT, SALES_LEAD)

        error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)
        # Rung 2 short-circuits before the rung 4 existence lookup can run.
        assert error["error_id"] != ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND

    def test_the_authorised_role_reaches_the_existence_rung_and_nothing_was_created(
        self, api
    ):
        """PRD §2.9: "4. **Path existence** — every templated identifier in the path
        resolves, checked left to right as described in §2.7. Applies to every
        endpoint with a templated segment. Failure: the relevant 404 code."

        Design: Difficulty/priority_pair_validation_conflict/authz_beats_existence_on_assignment_confirm
        """
        fixtures.base_world(api, clock=INSTANT_AUG_03)

        refused_for_role = api.confirm_assignment(UNKNOWN_UUID_ALT, SALES_LEAD)
        validate_error(refused_for_role, ApiErrorId.ERR_UNAUTHORIZED)

        # The very same id, reached by an authorised role, falls through to rung 4.
        refused_for_absence = api.confirm_assignment(UNKNOWN_UUID_ALT, RESOURCE_MANAGER)
        validate_error(refused_for_absence, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND, 404)

        rows, meta = validate_paginated(api.list_assignments(RESOURCE_MANAGER))
        assert meta["total_count"] == 0
        assert rows == []


class TestTravelBeatsMarginFloor:
    @staticmethod
    def _homebound_candidate_on_a_thin_deal(api):
        """A 1-night traveller proposed onto a 3-night, 4.00 percent margin demand."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Homebound Hal",
            proficiency_level=4,
            cost_rate_usd_per_hour=240.00,
            standard_bill_rate_usd_per_hour=400.00,
            travel_max_nights_per_week=1,
        )
        demand = fixtures.qualified_demand(
            api,
            world,
            client_name="Roadwork Retail",
            min_proficiency_level=3,
            required_fte=1.00,
            onsite_nights_per_week=3,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        assignment = fixtures.propose_assignment(
            api,
            staff["consultant"]["id"],
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        return world, staff, demand, assignment

    def test_the_travel_rung_outranks_the_fiscal_rung(self, api):
        """PRD §2.9: "26. **Travel fit** — the demand's `onsite_nights_per_week` must
        be at most the consultant's `travel_max_nights_per_week`, and when the demand's
        `is_international` is true the consultant's `travel_willing_international` must
        also be true. Applies to assignment confirmation only. Failure:
        `ERR_TRAVEL_CONSTRAINT_VIOLATED` (409)."

        Design: Difficulty/priority_pair_validation_conflict/travel_constraint_beats_margin_floor_on_confirm
        """
        _, _, _, assignment = self._homebound_candidate_on_a_thin_deal(api)

        response = api.confirm_assignment(assignment["id"], RESOURCE_MANAGER)

        # A 240.00 cost against a 250.00 effective rate projects a 4.00 percent
        # margin, so rung 40 is broken too and still loses.
        error = validate_error(response, ApiErrorId.ERR_TRAVEL_CONSTRAINT_VIOLATED, 409)
        assert error["error_id"] != ApiErrorId.ERR_MARGIN_FLOOR_BREACH

    def test_the_zero_travel_component_is_already_visible_on_the_stored_score(self, api):
        """PRD §3.5: "The travel component is 0.0000 outright when the demand's
        `onsite_nights_per_week` exceeds the consultant's
        `travel_max_nights_per_week`, or when the demand's `is_international` is true
        while the consultant's `travel_willing_international` is false; otherwise it is
        one minus the demand's `onsite_nights_per_week` divided by five, so a fully
        remote engagement scores 1.0000 and a five-night-a-week engagement scores
        0.0000."

        Design: Difficulty/priority_pair_validation_conflict/travel_constraint_beats_margin_floor_on_confirm
        """
        _, staff, demand, assignment = self._homebound_candidate_on_a_thin_deal(api)

        # 0.35*0.8000 + 0.15*0.0400, with the travel component already at 0.0000.
        assert assignment["match_score"] == pytest.approx(0.2860, abs=0.00005)

        validate_error(
            api.confirm_assignment(assignment["id"], RESOURCE_MANAGER),
            ApiErrorId.ERR_TRAVEL_CONSTRAINT_VIOLATED,
        )

        refused = fixtures.read_assignment(api, assignment["id"])
        assert refused["status"] == AssignmentStatus.PROPOSED
        assert refused["confirmed_on"] is None

        consultant = fixtures.read_consultant(api, staff["consultant"]["id"])
        assert consultant["allocated_pct"] == pytest.approx(0.00, abs=0.005)
        assert consultant["availability_status"] == AvailabilityStatus.BENCH

        after = fixtures.read_demand(api, demand["id"])
        assert after["covered_internal_fte"] == pytest.approx(0.00, abs=0.005)
        assert after["blended_margin_pct"] is None
        assert after["margin_breach"] is False
