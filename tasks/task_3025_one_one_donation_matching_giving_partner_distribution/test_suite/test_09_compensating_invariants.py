"""Compensating actions that must restore a ledger with zero drift (PRD §3.5, §3.2)."""
from test_helpers import (
    TEST_USERS,
    add_line,
    add_product_line,
    api_client,
    create_active_product,
    create_order,
    create_season,
    declare_capacity,
    get_allocation,
    get_liability_for,
    get_partner,
    get_product,
    get_profile,
    onboard_partner,
    pay_order,
    record_round,
    register_claim,
    set_clock,
    approve_round,
    validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
COORD = TEST_USERS["coordinator_headers"]

class TestCancellationAndCompensatingSettlement:
    """Difficulty/compensating_invariant — the unit ledger round-trips 13 → 9 → 13."""

    def _ledger_scenario(self):
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product(
            product_name="Workwear Crew",
            product_kind="ATHLETIC_SOCK",
            design_channel="DUAL_CHANNEL",
            obligation_model="AT_SALE",
            retail_price_cents=1650,
            unit_cost_cents=1150,
            is_reusable=True,
        )
        line_sold = add_product_line(product["id"], "00000000000204", "M", True)
        line_held = add_product_line(product["id"], "00000000000205", "L", False)

        order_paid = create_order(order_number="SO-CI-1", channel="RETAIL_ECOM")
        add_line(order_paid["id"], line_sold["id"], quantity=9, unit_price_cents=1650)
        pay_order(order_paid["id"])

        order_held = create_order(order_number="SO-CI-2", channel="RETAIL_POS")
        add_line(order_held["id"], line_held["id"], quantity=4, unit_price_cents=1650)
        return season, product, line_held, order_held

    def test_cancelling_an_unpaid_order_drops_only_the_provisional_ledger(self, api):
        """PRD §3.5: "The provisional ledger counts units of obligation across all lines whose owning order is in `CREATED` or any later non-cancelled status — `CREATED`, `PAID`, `DONATION_SATISFIED`, `PARTIALLY_REFUNDED` or `REFUNDED` — but only for lines whose variant is donation-eligible and whose product's obligation model is `AT_SALE`."
        PRD §3.5: "The final ledger is narrower and counts only settled, completed sales."
        PRD §3.5: "An order still in `CREATED` — no payment captured — may be cancelled with an optional `reason`, moving it to `CANCELLED` and its `fulfillment_status` to `CANCELLED`, and no liability row is created for that order at all."

        Design: Difficulty/compensating_invariant/cancellation_and_compensating_settlement_restore_the_unit_ledger_exactly
        """
        season, product, line_held, order_held = self._ledger_scenario()

        before = get_liability_for(product["id"], season["id"])
        assert before["provisional_liability_units"] == 13
        assert before["final_liability_units"] == 9

        validate_success(
            api_client.cancel_order(
                order_held["id"],
                {"reason": "Customer abandoned checkout before payment"},
                TEST_USERS["customer_service_headers"],
            ),
            200,
        )

        cancelled = get_liability_for(product["id"], season["id"])
        assert cancelled["provisional_liability_units"] == 9
        assert cancelled["final_liability_units"] == 9
        assert get_product(product["id"])["obligation_units_total"] == 9

    def test_readding_and_paying_restores_the_ledger_with_zero_drift(self, api):
        """PRD §3.5: "Paying an order requires every line to be in status `OPEN`, moves the order to `PAID`, stamps `paid_at`, advances `fulfillment_status` to `PLACED`, materializes each line's `obligated_units` from its variant line's rules, and recomputes `provisional_liability_units` for every line."
        PRD §3.5: "The provisional ledger counts units of obligation across all lines whose owning order is in `CREATED` or any later non-cancelled status — `CREATED`, `PAID`, `DONATION_SATISFIED`, `PARTIALLY_REFUNDED` or `REFUNDED` — but only for lines whose variant is donation-eligible and whose product's obligation model is `AT_SALE`."
        PRD §3.5: "The final ledger is narrower and counts only settled, completed sales."

        Design: Difficulty/compensating_invariant/cancellation_and_compensating_settlement_restore_the_unit_ledger_exactly
        """
        season, product, line_held, order_held = self._ledger_scenario()

        validate_success(
            api_client.cancel_order(
                order_held["id"], {"reason": "Abandoned checkout"},
                TEST_USERS["customer_service_headers"],
            ),
            200,
        )
        # PRD §3.5: "A line may never be added, settled or paid on an order that
        # has been cancelled, which raises `ERR_SALES_ORDER_CANCELLED`." The
        # compensating flow therefore opens a fresh order for the same units.
        replacement = create_order(order_number="SO-CI-3", channel="RETAIL_POS")
        add_line(replacement["id"], line_held["id"], quantity=4, unit_price_cents=1650)
        pay_order(replacement["id"])

        restored = get_liability_for(product["id"], season["id"])
        assert restored["provisional_liability_units"] == 13
        assert restored["final_liability_units"] == 13
        assert get_product(product["id"])["obligation_units_total"] == 13


class TestCancelAndReallocateRestoreTheCommitmentPool:
    """Difficulty/compensating_invariant — commitment round-trips 80 → 50 → 80."""

    def _two_partner_scenario(self):
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product(
            product_name="Compensating Crew",
            product_kind="ATHLETIC_SOCK",
            design_channel="DUAL_CHANNEL",
            obligation_model="AT_SALE",
            retail_price_cents=1700,
            unit_cost_cents=1000,
            is_reusable=True,
        )
        add_product_line(product["id"], "00000000000206", "M", True)

        partner_a = onboard_partner(
            legal_name="Rho Basin Shelter",
            operating_region="SOUTHWEST",
            operating_state_code="NM",
            registry_id="NM-CHR-170017",
            ein="100200900",
            unduplicated_recipients_per_facility=3000,
        )
        record_round(partner_a["latest_vetting_round_id"], need_verification_points=1)
        approve_round(partner_a["latest_vetting_round_id"])
        profile_a = declare_capacity(partner_a["id"], max_allocatable_units=100)

        set_clock("2026-09-02T00:00:00Z")
        partner_b = onboard_partner(
            legal_name="Sigma Basin Outreach",
            partner_type="YOUTH_OUTREACH",
            operating_region="SOUTHWEST",
            operating_state_code="NV",
            registry_id="NV-CHR-180018",
            ein="100201000",
            unduplicated_recipients_per_facility=4000,
            need_tier="MODERATE",
        )
        record_round(partner_b["latest_vetting_round_id"], need_verification_points=1)
        approve_round(partner_b["latest_vetting_round_id"])
        profile_b = declare_capacity(partner_b["id"], max_allocatable_units=100)

        claim = register_claim(product["id"], partner_a["id"], stated_donation_units=80)
        alloc_a = validate_success(
            api_client.commit_allocation_plan(
                season["id"],
                {
                    "giving_partner_id": partner_a["id"],
                    "claim_id": claim["id"],
                    "donation_product_id": product["id"],
                    "allocated_units": 30,
                    "priority_tier": "CRITICAL",
                    "liquidity_cap": 10,
                    "expected_partner_version": get_partner(partner_a["id"])["version"],
                },
                PLANNER,
            ),
            200,
        )
        alloc_b = validate_success(
            api_client.commit_allocation_plan(
                season["id"],
                {
                    "giving_partner_id": partner_b["id"],
                    "claim_id": claim["id"],
                    "donation_product_id": product["id"],
                    "allocated_units": 50,
                    "priority_tier": "HIGH",
                    "liquidity_cap": 10,
                    "expected_partner_version": get_partner(partner_b["id"])["version"],
                },
                PLANNER,
            ),
            200,
        )
        return season, product, partner_a, partner_b, profile_a, profile_b, claim, alloc_a, alloc_b

    def test_cancel_drops_only_the_cancelled_partner_commitment(self, api):
        """PRD §2.6: "`committed_units` is the sum of `allocated_units` over the partner's benefit allocations that are `APPROVED`, `SHIPPED`, `PARTIALLY_RECEIVED` or `RECEIVED`."
        PRD §3.2: "A successful cancel lowers `committed_units` by `allocated_units`, returns a profile sitting at `EXHAUSTED` to `ACTIVE` when headroom reappears, and advances the partner's `version`."
        PRD §2.6: "`reserved_units` holds units forecast to return in a later season by reversal allocations."

        Design: Difficulty/compensating_invariant/reversal_and_forward_carry_restore_the_committed_unit_pool
        """
        season, product, pa, pb, profile_a, profile_b, claim, alloc_a, alloc_b = (
            self._two_partner_scenario()
        )

        pool_before = get_profile(profile_a["id"])["committed_units"] + get_profile(
            profile_b["id"]
        )["committed_units"]
        assert pool_before == 80

        current = get_allocation(alloc_a["id"])
        validate_success(
            api_client.cancel_allocation(
                alloc_a["id"], {"expected_allocation_version": current["version"]}, PLANNER
            ),
            200,
        )

        assert get_profile(profile_a["id"])["committed_units"] == 0
        assert get_profile(profile_b["id"])["committed_units"] == 50
        assert get_profile(profile_a["id"])["reserved_units"] == 0

    def test_reallocation_restores_the_pool_and_never_parks_units_in_the_reserve(self, api):
        """PRD §3.2: "Reallocating a cancelled allocation — guarded by `expected_allocation_version` — re-activates it with a refreshed `rank_score` and a fresh `created_at` provided `allocated_units` fits the emptied profile's headroom, recomputes the ranking across the plan's candidate pool, and advances the partner's `version`; an attempt against an allocation whose cancellation has already been superseded by a reversal is refused with `ERR_ALLOCATION_VERSION_SUPERSEDED` (HTTP 409), and an attempt whose reallocation would breach the ceiling reports `ERR_CAPACITY_EXCEEDED`."
        PRD §2.6: "`committed_units` is the sum of `allocated_units` over the partner's benefit allocations that are `APPROVED`, `SHIPPED`, `PARTIALLY_RECEIVED` or `RECEIVED`."
        PRD §2.6: "`reserved_units` holds units forecast to return in a later season by reversal allocations."

        Design: Difficulty/compensating_invariant/reversal_and_forward_carry_restore_the_committed_unit_pool
        """
        season, product, pa, pb, profile_a, profile_b, claim, alloc_a, alloc_b = (
            self._two_partner_scenario()
        )
        current = get_allocation(alloc_a["id"])
        validate_success(
            api_client.cancel_allocation(
                alloc_a["id"], {"expected_allocation_version": current["version"]}, PLANNER
            ),
            200,
        )

        cancelled = get_allocation(alloc_a["id"])
        validate_success(
            api_client.reallocate_allocation(
                alloc_a["id"],
                {
                    "expected_allocation_version": cancelled["version"],
                    "giving_partner_id": pa["id"],
                    "allocated_units": 30,
                },
                PLANNER,
            ),
            200,
        )

        refreshed_a = get_profile(profile_a["id"])
        assert refreshed_a["committed_units"] == 30
        assert refreshed_a["reserved_units"] == 0
        pool_after = refreshed_a["committed_units"] + get_profile(
            profile_b["id"]
        )["committed_units"]
        assert pool_after == 80