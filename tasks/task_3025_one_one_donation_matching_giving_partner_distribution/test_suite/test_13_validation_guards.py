"""Guards that are satisfied, violated, or conditional on another field (PRD §2.6, §2.7, §3.1–§3.7)."""
from test_helpers import (
    TEST_USERS,
    add_line,
    add_product_line,
    api_client,
    commit_allocation,
    create_active_product,
    create_approved_partner,
    create_order,
    create_season,
    declare_capacity,
    get_partner,
    get_profile,
    onboard_partner,
    pay_order,
    record_round,
    register_claim,
    set_clock,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
DESIGN = TEST_USERS["designer_headers"]
PLANNER = TEST_USERS["planner_headers"]
SERVICE = TEST_USERS["customer_service_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestCommitVersionGuard:
    """Corner/validations — the OCC guard on the commit."""

    def _ready_partner(self):
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        return season, product, partner, claim

    def test_a_stale_partner_version_is_refused_without_debiting_capacity(self, api):
        """PRD §2.7: "Committing a benefit allocation plan requires `expected_partner_version`, carrying the planner's last observed `version` of the target `GivingPartner`."

        Design: Corner/validations/stale_partner_version_returns_precondition_failed_on_commit
        """
        season, product, partner, claim = self._ready_partner()
        stale = get_partner(partner["id"])["version"] - 1

        res = api_client.commit_allocation_plan(
            season["id"],
            {
                "giving_partner_id": partner["id"],
                "claim_id": claim["id"],
                "donation_product_id": product["id"],
                "allocated_units": 10,
                "priority_tier": "HIGH",
                "liquidity_cap": 10,
                "expected_partner_version": stale,
            },
            PLANNER,
        )
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)

        allocations = validate_success(
            api_client.list_allocations(PLANNER, {"giving_partner_id": partner["id"]}), 200
        )
        assert len(allocations) == 0
        assert get_partner(partner["id"])["capacity_utilization_units"] == 0

    def test_the_current_version_commits_and_advances_the_partner(self, api):
        """PRD §3.2: "The allocation is created pending and approved within the request, its `rank_score` is computed, the partner's `committed_units` rises by `allocated_units`, and the partner's `version` advances by one."

        Design: Corner/validations/fresh_partner_version_commits_and_advances_the_parent_version
        """
        season, product, partner, claim = self._ready_partner()
        observed = get_partner(partner["id"])["version"]

        allocation = validate_success(
            api_client.commit_allocation_plan(
                season["id"],
                {
                    "giving_partner_id": partner["id"],
                    "claim_id": claim["id"],
                    "donation_product_id": product["id"],
                    "allocated_units": 10,
                    "priority_tier": "HIGH",
                    "liquidity_cap": 10,
                    "expected_partner_version": observed,
                },
                PLANNER,
            ),
            200,
        )
        assert allocation["status"] == "APPROVED"
        assert get_partner(partner["id"])["version"] > observed

        replay = api_client.commit_allocation_plan(
            season["id"],
            {
                "giving_partner_id": partner["id"],
                "claim_id": claim["id"],
                "donation_product_id": product["id"],
                "allocated_units": 10,
                "priority_tier": "HIGH",
                "liquidity_cap": 10,
                "expected_partner_version": observed,
            },
            PLANNER,
        )
        validate_error(replay, "ERR_STALE_VERSION", expected_status=412)


class TestReturnWindowGuard:
    """Corner/validations — the window is paid_at plus the line's window length."""

    def _paid_line(self, order_number):
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        line = add_product_line(product["id"], f"000000000006{order_number}", "M", True)
        order = create_order(order_number=f"SO-WIN-{order_number}", channel="RETAIL_ECOM")
        soline = add_line(order["id"], line["id"], quantity=2, unit_price_cents=1600)
        pay_order(order["id"])
        return season, product, order, soline

    def test_a_change_of_mind_outside_the_window_is_refused(self, api):
        """PRD §3.6: "A return opened after the window expires is normally refused with `ERR_RETURN_WINDOW_CLOSED` (HTTP 422), but is accepted in exactly two situations: when the season containing the order has the window-reset flag enabled, or when the request is a defect claim."

        Design: Corner/validations/return_outside_the_window_returns_window_closed
        """
        season, product, order, soline = self._paid_line("11")
        set_clock("2026-10-02T00:00:00Z")
        line_version = validate_success(
            api_client.get_order_line(order["id"], soline["id"], SERVICE), 200
        )["version"]

        res = api_client.open_line_return_request(
            order["id"], soline["id"],
            {
                "request_reason": "CHANGE_OF_MIND",
                "requested_units": 1,
                "is_exchange": False,
                "expected_line_version": line_version,
            },
            SERVICE,
        )
        validate_error(res, "ERR_RETURN_WINDOW_CLOSED")
        assert validate_success(
            api_client.get_order_line(order["id"], soline["id"], SERVICE), 200
        )["status"] == "OPEN"

    def test_a_return_inside_the_window_is_accepted_at_the_boundary(self, api):
        """PRD §3.6: "A return opened inside the window is accepted."
        PRD §3.6: "A return opened after the window expires is normally refused with `ERR_RETURN_WINDOW_CLOSED` (HTTP 422), but is accepted in exactly two situations: when the season containing the order has the window-reset flag enabled, or when the request is a defect claim."

        Design: Corner/validations/return_outside_the_window_returns_window_closed
        """
        season, product, order, soline = self._paid_line("12")
        # The window closes at paid_at plus the line's 30 days; the boundary is inclusive.
        set_clock("2026-10-01T00:00:00Z")
        line_version = validate_success(
            api_client.get_order_line(order["id"], soline["id"], SERVICE), 200
        )["version"]

        validate_success(
            api_client.open_line_return_request(
                order["id"], soline["id"],
                {
                    "request_reason": "CHANGE_OF_MIND",
                    "requested_units": 1,
                    "is_exchange": False,
                    "expected_line_version": line_version,
                },
                SERVICE,
            ),
            201,
        )


class TestCapacityCeilingBoundary:
    """Corner/validations — a shortage of exactly zero units passes."""

    def test_a_commit_that_exactly_fills_the_ceiling_is_accepted(self, api):
        """PRD §2.6: "The governing fiscal rule of the surface is that `capacity_utilization_units` must not exceed `max_allocatable_units` for the resolved partner-and-season profile, and that a shortage of exactly zero units passes."
        PRD §3.2: "`committed_units` is the sum of `allocated_units` over the partner's benefit allocations that are `APPROVED`, `SHIPPED`, `PARTIALLY_RECEIVED` or `RECEIVED`."

        Design: Corner/validations/capacity_utilization_exactly_at_the_ceiling_is_accepted
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        profile = declare_capacity(partner["id"], max_allocatable_units=100)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=100)

        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=100, priority_tier="CRITICAL",
        )
        assert allocation["status"] == "APPROVED"

        refreshed = get_profile(profile["id"])
        assert refreshed["committed_units"] == 100
        assert refreshed["capacity_utilization_units"] == 100
        assert refreshed["max_allocatable_units"] == 100

        over = api_client.commit_allocation_plan(
            season["id"],
            {
                "giving_partner_id": partner["id"],
                "claim_id": claim["id"],
                "donation_product_id": product["id"],
                "allocated_units": 1,
                "priority_tier": "CRITICAL",
                "liquidity_cap": 10,
                "expected_partner_version": get_partner(partner["id"])["version"],
            },
            PLANNER,
        )
        validate_error(over, "ERR_CAPACITY_EXCEEDED", expected_status=409)

        zero = api_client.commit_allocation_plan(
            season["id"],
            {
                "giving_partner_id": partner["id"],
                "claim_id": claim["id"],
                "donation_product_id": product["id"],
                "allocated_units": 0,
                "priority_tier": "CRITICAL",
                "liquidity_cap": 10,
                "expected_partner_version": get_partner(partner["id"])["version"],
            },
            PLANNER,
        )
        validate_error(zero, "ERR_INVALID_REQUEST", expected_status=400)


class TestSuspendedPartnerTierConditional:
    """Corner/validations — the standing rule is conditional on the priority tier."""

    def _suspended_partner(self):
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        validate_success(
            api_client.set_partner_status(partner["id"], {"status": "SUSPENDED"}, AUDITOR), 200
        )
        return season, product, partner, claim

    def test_an_emergency_allocation_still_commits_for_a_suspended_partner(self, api):
        """PRD §2.5: "A partner that is `SUSPENDED` may still receive goods, but only on an allocation whose `priority_tier` is `EMERGENCY`; any other priority tier produces `ERR_PARTNER_SUSPENDED` (HTTP 409)."
        PRD §3.1: "Moving an `APPROVED` partner to `SUSPENDED` requires that the target value is `SUSPENDED` and that no audit of kind `PARTNER_PERFORMANCE` for that partner is in `IN_PROGRESS`; the same write locks every `ACTIVE` capacity profile the partner holds, cancels every `PENDING_ALLOCATION` allocation attributed to it, and restricts every `SUBSTANTIATED` claim naming it to `SEASON_RESTRICTED`."

        Design: Corner/validations/suspended_partner_accepts_an_emergency_allocation_and_refuses_a_normal_one
        """
        season, product, partner, claim = self._suspended_partner()
        assert get_partner(partner["id"])["status"] == "SUSPENDED"

        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=10, priority_tier="EMERGENCY",
        )
        assert allocation["status"] == "APPROVED"

    def test_the_same_allocation_at_a_normal_tier_is_refused(self, api):
        """PRD §2.5: "A partner that is `SUSPENDED` may still receive goods, but only on an allocation whose `priority_tier` is `EMERGENCY`; any other priority tier produces `ERR_PARTNER_SUSPENDED` (HTTP 409)."

        Design: Corner/validations/suspended_partner_accepts_an_emergency_allocation_and_refuses_a_normal_one
        """
        season, product, partner, claim = self._suspended_partner()

        res = api_client.commit_allocation_plan(
            season["id"],
            {
                "giving_partner_id": partner["id"],
                "claim_id": claim["id"],
                "donation_product_id": product["id"],
                "allocated_units": 10,
                "priority_tier": "HIGH",
                "liquidity_cap": 10,
                "expected_partner_version": get_partner(partner["id"])["version"],
            },
            PLANNER,
        )
        validate_error(res, "ERR_PARTNER_SUSPENDED", expected_status=409)


class TestApprovalVerificationFlags:
    """Corner/validations — a false flag blocks approval however high the score is."""

    def test_one_false_flag_blocks_approval_above_the_threshold(self, api):
        """PRD §3.1: "Approval is gated on two independent conditions and either failure aborts it. The partner's `registry_verified` must be true and all four verification flags must be true on that round; any false flag or an unverified registry is rejected with `ERR_REGISTRY_NOT_VERIFIED` (HTTP 409)."

        Design: Corner/validations/unverified_registry_check_blocks_approval_even_above_the_need_threshold
        """
        set_clock("2026-09-01T00:00:00Z")
        partner = onboard_partner()
        vetting_id = partner["latest_vetting_round_id"]
        record_round(vetting_id, registry_check_passed=True, tax_check_passed=False)

        row = validate_success(api_client.get_giving_partner(partner["id"], COORD), 200)
        # PRD §3.1: a homeless shelter in the northeast is 70 + 3 plus the
        # access component min(20, 15000 // 1000), so 88 — well above the 40
        # minimum, which is the point of this test.
        assert row["need_score"] == 88, "well above the 40 minimum"

        res = api_client.approve_vetting_round(vetting_id, {}, COORD)
        validate_error(res, "ERR_REGISTRY_NOT_VERIFIED", expected_status=409)
        assert validate_success(
            api_client.get_giving_partner(partner["id"], COORD), 200
        )["status"] == "VETTING"

        record_round(vetting_id, registry_check_passed=True, tax_check_passed=True)
        validate_success(api_client.approve_vetting_round(vetting_id, {}, COORD), 200)


class TestFreezeBoundaryGuard:
    """Corner/validations — no write may fall after the resolved season's freeze instant."""

    def test_a_write_after_the_freeze_instant_is_refused(self, api):
        """PRD §2.11: "No write may fall after the resolved season's `freezes_at` instant, and no write may mutate a season whose status is `FINALIZED`; a violation of either is rejected with `ERR_SEASON_FROZEN` (HTTP 409)."

        Design: Corner/validations/a_commit_after_the_freeze_boundary_returns_season_frozen
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)

        set_clock("2026-12-01T00:00:00Z")
        res = api_client.commit_allocation_plan(
            season["id"],
            {
                "giving_partner_id": partner["id"],
                "claim_id": claim["id"],
                "donation_product_id": product["id"],
                "allocated_units": 10,
                "priority_tier": "HIGH",
                "liquidity_cap": 10,
                "expected_partner_version": get_partner(partner["id"])["version"],
            },
            PLANNER,
        )
        validate_error(res, "ERR_SEASON_FROZEN", expected_status=409)


class TestGtinAgreementGuard:
    """Corner/validations — the two records must agree on the identity of the good."""

    def test_a_mismatched_capture_gtin_is_refused(self, api):
        """PRD §3.5: "when a `gtin` is supplied it must agree with the referenced variant line's `gtin` or the request is rejected with `ERR_ENTITY_UNRESOLVED` (HTTP 409), because the two records disagree about the identity of the good."

        Design: Corner/validations/gtin_mismatch_between_variant_and_capture_returns_entity_unresolved
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        line = add_product_line(product["id"], "00000000000405", "M", True)
        add_product_line(product["id"], "00000000000403", "L", False)
        order = create_order(order_number="SO-GTIN-1", channel="RETAIL_ECOM")

        res = api_client.add_order_line(
            order["id"],
            {
                "donation_product_line_id": line["id"],
                "quantity": 2,
                "unit_price_cents": 1600,
                "line_discount_cents": 0,
                "gtin": "00000000000403",
            },
            SERVICE,
        )
        validate_error(res, "ERR_ENTITY_UNRESOLVED", expected_status=409)

        lines = validate_success(api_client.list_order_lines(order["id"], SERVICE), 200)
        assert len(lines) == 0

        liability = validate_success(
            api_client.list_liabilities(
                AUDITOR, {"donation_product_id": product["id"], "impact_season_id": season["id"]}
            ),
            200,
        )
        assert liability == [] or liability[0]["provisional_liability_units"] == 0