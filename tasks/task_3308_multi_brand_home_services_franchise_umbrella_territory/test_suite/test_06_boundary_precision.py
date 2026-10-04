"""Boundary precision: the expansion threshold and the SLA due instant."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_agreement,
    award_territory,
    create_agreement,
    create_brand,
    create_franchisee,
    create_territory,
    create_work_order,
    dispatch_work_order,
    get_territory,
    get_work_order,
    make_franchisee_operator_headers,
    offer_agreement,
    offer_territory,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestExpansionThresholdExactEquality:
    def _two_active_territories_across_the_threshold(self):
        """One territory exactly at its expansion threshold, one a single
        household below it; both ACTIVE under the same franchisee."""
        set_clock("2026-09-01T00:00:00Z")
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        franchisee = create_franchisee()
        ter_eq = create_territory(
            brand["id"], franchisee_id=franchisee["id"], territory_code="MS-EQ",
            household_count=45000, postal_codes=["75101", "75102"],
            expansion_right_households=45000,
        )
        ter_under = create_territory(
            brand["id"], franchisee_id=franchisee["id"], territory_code="MS-UN",
            household_count=44999, postal_codes=["75201", "75202"],
            expansion_right_households=45000,
        )
        agt_eq = create_agreement(franchisee["id"], brand["id"], ter_eq["id"])
        agt_under = create_agreement(franchisee["id"], brand["id"], ter_under["id"])
        for territory, agreement in ((ter_eq, agt_eq), (ter_under, agt_under)):
            offer_agreement(agreement["id"])
            offer_territory(territory["id"], franchisee["id"])
            award_territory(territory["id"])
            activate_agreement(agreement["id"])
        return franchisee, ter_eq, ter_under

    def test_a_count_exactly_at_the_threshold_qualifies(self, api):
        """PRD §3.3: "The comparison is inclusive: a territory whose
        `household_count` exactly equals its `expansion_right_households`
        qualifies, and only a count strictly below the threshold is refused,
        with `ERR_EXPANSION_THRESHOLD_NOT_MET`."

        Design: Difficulty/boundary_precision_check/expansion_threshold_exact_equality_qualifies
        """
        franchisee, ter_eq, _ = self._two_active_territories_across_the_threshold()

        resp = api.request_expansion(
            ter_eq["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        expanded = validate_success(resp, 200)
        assert expanded["status"] == "EXPANSION_REQUESTED", (
            f"household_count 45000 >= expansion_right_households 45000 must "
            f"qualify, got {expanded['status']}"
        )

    def test_a_count_one_household_below_the_threshold_is_refused(self, api):
        """PRD §3.3: "only a count strictly below the threshold is refused, with
        `ERR_EXPANSION_THRESHOLD_NOT_MET`."

        Design: Difficulty/boundary_precision_check/expansion_threshold_exact_equality_qualifies
        """
        franchisee, _, ter_under = self._two_active_territories_across_the_threshold()

        resp = api.request_expansion(
            ter_under["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EXPANSION_THRESHOLD_NOT_MET)

        refused = get_territory(ter_under["id"])
        assert refused["status"] == "ACTIVE", (
            f"a refused expansion leaves the territory ACTIVE, got {refused['status']}"
        )
        assert refused["allocated_households"] == 44999, (
            f"the territory keeps its allocation, got {refused['allocated_households']}"
        )


class TestSlaBreachClockBoundary:
    def _dispatched_work_order(self):
        set_clock("2026-09-01T00:00:00Z")
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        franchisee = create_franchisee()
        territory = create_territory(brand["id"], franchisee_id=franchisee["id"])
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
        work_order = create_work_order(
            agreement["id"], source="DIRECT", priority="STANDARD",
            service_level_hours=4, parts_cents=0,
        )
        dispatch_work_order(
            work_order["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        return franchisee, work_order

    def test_breach_one_second_before_the_due_instant_is_refused(self, api):
        """PRD §3.4: "A `FranchiseAdmin` may also mark a work order breached
        explicitly, but only from `IN_PROGRESS` and only once the deadline has
        been reached; attempting it earlier is refused with
        `ERR_SLA_NOT_BREACHED`."

        Design: Difficulty/boundary_precision_check/sla_breach_clock_exactly_at_due_instant
        """
        franchisee, work_order = self._dispatched_work_order()
        # PRD 3.4: a breach may be marked explicitly only from IN_PROGRESS.
        api.start_work_order(
            work_order["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        dispatched = get_work_order(work_order["id"])
        assert dispatched["sla_due_iso"] == "2026-09-01T04:00:00Z", (
            f"a STANDARD four-hour window must be due four hours out, got "
            f"{dispatched['sla_due_iso']}"
        )

        set_clock("2026-09-01T03:59:59Z")
        resp = api.breach_work_order(work_order["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SLA_NOT_BREACHED)

    def test_breach_exactly_at_the_due_instant_succeeds(self, api):
        """PRD §3.4: "A `FranchiseAdmin` may also mark a work order breached
        explicitly, but only from `IN_PROGRESS` and only once the deadline has
        been reached".

        Design: Difficulty/boundary_precision_check/sla_breach_clock_exactly_at_due_instant
        """
        franchisee, work_order = self._dispatched_work_order()
        api.start_work_order(
            work_order["id"], make_franchisee_operator_headers(franchisee["id"]),
        )

        set_clock("2026-09-01T04:00:00Z")
        resp = api.breach_work_order(work_order["id"], ADMIN)
        breached = validate_success(resp, 200)

        assert breached["status"] == "SLA_BREACHED", (
            f"the breach at exactly the due instant must be permitted, got "
            f"{breached['status']}"
        )
        assert breached["closed_clock_iso"] == "2026-09-01T04:00:00Z", (
            f"the closing instant must be the logical clock, got "
            f"{breached['closed_clock_iso']}"
        )