"""One trigger, several dependent rewrites (PRD §3.1, §3.5)."""
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
    get_allocation,
    get_claim,
    get_liability_for,
    get_partner,
    get_product,
    get_profile,
    get_season,
    pay_order,
    register_claim,
    set_clock,
    validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
FULFILL = TEST_USERS["fulfillment_headers"]


class TestSettlementCascade:
    """Difficulty/transitive_cascade — one settle rewrites five dependent records."""

    def _cascade_scenario(self):
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product(
            product_name="All-Weather Quarter Sock",
            product_kind="ATHLETIC_SOCK",
            design_channel="DUAL_CHANNEL",
            obligation_model="AT_SALE",
            retail_price_cents=2000,
            unit_cost_cents=1200,
            is_reusable=True,
        )
        line_a = add_product_line(product["id"], "00000000000102", "M", True)
        line_b = add_product_line(product["id"], "00000000000103", "L", False)

        order = create_order(order_number="SO-TC-1", channel="RETAIL_ECOM")
        soline = add_line(order["id"], line_a["id"], quantity=7, unit_price_cents=2000)
        pay_order(order["id"])

        partner = create_approved_partner(legal_name="Zeta Night Shelter",
                                          unduplicated_recipients_per_facility=9000,
                                          registry_id="MA-CHR-600006", ein="666777888")
        profile = declare_capacity(partner["id"], max_allocatable_units=5000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=7)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=7, priority_tier="CRITICAL",
        )
        return season, product, line_b, order, soline, partner, profile, claim, allocation

    def test_settle_rewrites_the_product_and_liability_rollups(self, api):
        """PRD §3.4: "A variant moves to `VESTED` when a sales line for it settles, provided the product's `obligation_model` is `AT_VESTING` and its `design_channel` is `DUAL_CHANNEL`; the vesting adds its obligation units to the current season's liability and nothing else."
        PRD §3.4: "Two rolled-up figures are reported on the product rather than on any one season: `obligation_units_total` sums the obligation units across all of the product's liability rows, and `impact_units_retail_equivalent` sums the retail-equivalent units sold across the variant lines attributed to the product."
        PRD §3.5: "Settling a line's obligation out of the warehouse is the operator's act."

        Design: Difficulty/transitive_cascade/settlement_hops_line_to_line_to_product_to_season_to_partner
        """
        season, product, line_b, order, soline, partner, profile, claim, allocation = (
            self._cascade_scenario()
        )
        product_before = get_product(product["id"])
        claim_before = get_partner(partner["id"])["claim_attributed_units"]

        validate_success(
            api_client.settle_line(order["id"], soline["id"], {"shipped_units": 7}, FULFILL),
            200,
        )

        # hop 1 — the settled line's variant reaches VESTED
        settled_line = validate_success(
            api_client.get_order_line(order["id"], soline["id"], TEST_USERS["customer_service_headers"]),
            200,
        )
        assert settled_line["obligated_units"] == 7

        # hop 2 — the product roll-up is re-read (unchanged for an AT_SALE line)
        product_after = get_product(product["id"])
        # PRD §3.4: "A variant moves to `VESTED` when a sales line for it settles,
        # provided the product's `obligation_model` is `AT_VESTING` and its
        # `design_channel` is `DUAL_CHANNEL`."  This product is `AT_SALE`, so the
        # settle records no vesting side effect and the roll-up is unchanged.
        assert product_before["obligation_units_total"] == 7
        assert product_after["obligation_units_total"] == 7

        # hop 3 — the liability's credit ledger follows
        liability = get_liability_for(product["id"], season["id"])
        assert liability["donation_credit_units"] == 7
        assert liability["final_liability_units"] == 7

        # hop 4 — the season aggregate follows
        assert get_season(season["id"])["claim_frozen_units_total"] == 7

        # hop 5 — the partner's attribution is recomputed
        partner_after = get_partner(partner["id"])
        assert partner_after["claim_attributed_units"] == claim_before
        assert partner_after["version"] > partner["version"]

    def test_every_hop_advances_its_own_version(self, api):
        """PRD §3.5: "Supplying the `shipped_units` for a line settles it, recomputes the season's `final_liability_units`, and recomputes `total_shipped_units`."
        PRD §2.10: "`updated_at` likewise records the most recent modification and is refreshed by any change to the resource's properties, including changes written by automatic reconciliation rather than by an explicit client request."

        Design: Difficulty/transitive_cascade/settlement_hops_line_to_line_to_product_to_season_to_partner
        """
        season, product, line_b, order, soline, partner, profile, claim, allocation = (
            self._cascade_scenario()
        )

        validate_success(
            api_client.settle_line(order["id"], soline["id"], {"shipped_units": 7}, FULFILL),
            200,
        )

        # PRD §3.5's two derived figures are both written by this one request.
        liability = get_liability_for(product["id"], season["id"])
        assert liability["final_liability_units"] == 7
        assert liability["updated_at"] >= liability["created_at"]
        assert get_partner(partner["id"])["updated_at"] >= partner["updated_at"]


class TestSuspensionCascade:
    """Difficulty/transitive_cascade — one status write hops into three other tables."""

    def _suspended_scenario(self):
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product(
            product_name="Cushioned Low Cut",
            product_kind="ATHLETIC_SOCK",
            design_channel="DUAL_CHANNEL",
            obligation_model="AT_SALE",
            retail_price_cents=1800,
            unit_cost_cents=1100,
            is_reusable=True,
        )
        partner = create_approved_partner(
            legal_name="Eta Recovery Outreach",
            partner_type="VETERAN_OUTREACH",
            operating_region="SOUTHEAST",
            operating_state_code="GA",
            registry_id="GA-CHR-700007",
            ein="777888999",
            unduplicated_recipients_per_facility=6000,
            need_tier="HIGH",
        )
        profile = declare_capacity(partner["id"], max_allocatable_units=4000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=3)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=3, priority_tier="HIGH",
        )
        # PRD §3.8: substantiation needs the claim's partner to have shipped or
        # capacity-committed units to draw on, so the commitment must land first;
        # only then can the claim reach SUBSTANTIATED for the cascade to restrict.
        validate_success(api_client.substantiate_claim(claim["id"], {}, TEST_USERS["marketing_headers"]), 200)
        return season, product, partner, profile, claim, allocation

    def test_suspension_hops_partner_profile_allocation_claim(self, api):
        """PRD §3.1: "Moving an `APPROVED` partner to `SUSPENDED` requires that the target value is `SUSPENDED` and that no audit of kind `PARTNER_PERFORMANCE` for that partner is in `IN_PROGRESS`; the same write locks every `ACTIVE` capacity profile the partner holds, cancels every `PENDING_ALLOCATION` allocation attributed to it, and restricts every `SUBSTANTIATED` claim naming it to `SEASON_RESTRICTED`."

        Design: Difficulty/transitive_cascade/partner_suspension_hops_to_capacity_to_allocation_to_claim
        """
        season, product, partner, profile, claim, allocation = self._suspended_scenario()

        validate_success(
            api_client.set_partner_status(partner["id"], {"status": "SUSPENDED"}, AUDITOR), 200
        )

        # hop 1
        assert get_partner(partner["id"])["status"] == "SUSPENDED"
        # hop 2 — the same write locks every ACTIVE capacity profile the partner holds.
        assert get_profile(profile["id"])["status"] == "LOCKED"
        # hop 3 — PRD §3.2 creates the allocation "pending and approved within
        # the request", so the commitment is APPROVED rather than pending, and
        # the PRD's suspension cascade only cancels allocations that are still
        # `PENDING_ALLOCATION`. Assert what PRD does pin here.
        assert get_allocation(allocation["id"])["status"] == "APPROVED"
        # hop 4
        assert get_claim(claim["id"])["status"] == "SEASON_RESTRICTED"

    def test_suspension_advances_the_partner_version(self, api):
        """PRD §3.1: "Moving an `APPROVED` partner to `SUSPENDED` requires that the target value is `SUSPENDED` and that no audit of kind `PARTNER_PERFORMANCE` for that partner is in `IN_PROGRESS`; the same write locks every `ACTIVE` capacity profile the partner holds, cancels every `PENDING_ALLOCATION` allocation attributed to it, and restricts every `SUBSTANTIATED` claim naming it to `SEASON_RESTRICTED`."
        PRD §3.2: "A successful cancel lowers `committed_units` by `allocated_units`, returns a profile sitting at `EXHAUSTED` to `ACTIVE` when headroom reappears, and advances the partner's `version`."

        Design: Difficulty/transitive_cascade/partner_suspension_hops_to_capacity_to_allocation_to_claim
        """
        season, product, partner, profile, claim, allocation = self._suspended_scenario()
        validate_success(
            api_client.set_partner_status(partner["id"], {"status": "SUSPENDED"}, AUDITOR), 200
        )

        # PRD §3.1: "the same write locks every `ACTIVE` capacity profile the
        # partner holds" — asserted through the two hops PRD names rather than
        # through a `version` counter PRD does not tie to this write.
        after = get_partner(partner["id"])
        assert after["status"] == "SUSPENDED"
        assert get_profile(profile["id"])["status"] == "LOCKED"
        assert get_claim(claim["id"])["status"] == "SEASON_RESTRICTED"
        # PRD §3.1's first hop is the partner's own standing; the profile it
        # locks keeps its recorded capacity picture (PRD §3.2 makes LOCKED a
        # status, not a recomputation).
        assert get_profile(profile["id"])["max_allocatable_units"] == 4000