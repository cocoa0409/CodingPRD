"""Combinatorial calculations: per-allocation fee rounding order, frozen candidate
snapshots for displacement, and the pinned lifecycle-floor evaluation order.
"""
from test_helpers import (
    api, validate_success, get_success_data,
    TEST_USERS, make_partner_ops_headers,
    startup_clock, create_certified_blueprint, create_validated_partner,
    create_product, create_supply_node, create_allocation_hold,
    create_and_commit_allocation_hold, create_allocation_forecast,
    get_product, get_supply_node, advance_product_lifecycle,
    create_lifecycle_commitment,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["supply_planner_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
LIFECYCLE = TEST_USERS["lifecycle_program_manager_headers"]


class TestCommitmentFeeRounding:
    """The pool's committed fee rounds half-even per allocation, then sums."""

    def _two_hold_pool(self):
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        forecast = create_allocation_forecast(product["id"], partner["id"],
                                              requested_quantity_units=1000)
        return partner, product, node, forecast

    def test_committed_fee_rounds_each_allocation_before_summing(self):
        """PRD §2.11: "the commitment fee is rounded half-even to whole cents per
        allocation and only then summed".
        PRD §3.3: "the commitment fee is the sum, over those same holds, of each
        hold's fee rounded half-even to whole cents before the sum is taken".

        Design: Difficulty/combinatorial_formula/allocation_commitment_fee_per_allocation_rounding_order
        """
        partner, product, node, forecast = self._two_hold_pool()
        small = create_and_commit_allocation_hold(product["id"], node["id"], 100,
                                                  partner["id"], forecast_id=forecast["id"])
        big = create_allocation_hold(product["id"], node["id"], 250, partner["id"],
                                     forecast_id=forecast["id"])

        assert small["committed_rate_v2"] == 1.75, "a 100-unit hold is a single band"
        assert big["committed_rate_v2"] == 1.95, (
            "a 250-unit hold spans bands averaging to 1.95 per unit"
        )
        node = get_supply_node(node["id"])
        assert node["committed_fee_cents"] == 23187, (
            f"per-allocation rounding gives 6125 + 17062 = 23187, "
            f"got {node['committed_fee_cents']}"
        )

    def test_sum_then_round_once_is_not_the_pinned_order(self):
        """PRD §2.11: "summing first and rounding once afterwards is explicitly not the
        required semantics because it produces a different total".

        Design: Difficulty/combinatorial_formula/allocation_commitment_fee_per_allocation_rounding_order
        """
        partner, product, node, forecast = self._two_hold_pool()
        create_and_commit_allocation_hold(product["id"], node["id"], 100,
                                          partner["id"], forecast_id=forecast["id"])
        create_allocation_hold(product["id"], node["id"], 250, partner["id"],
                               forecast_id=forecast["id"])

        node = get_supply_node(node["id"])
        assert node["committed_fee_cents"] != 23188, (
            "the sum-then-round-once total is explicitly not the pinned semantics"
        )


class TestPreemptionDisplacement:
    """Displacement consumes the ranking from the lowest score upward."""

    def _three_requested_holds(self, capacity_units=1000):
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"], capacity_units=capacity_units)
        holds = [
            create_allocation_hold(product["id"], node["id"], qty, partner["id"])
            for qty in (200, 300, 400)
        ]
        return partner, product, node, holds

    def test_displacing_request_reclaims_the_lowest_scoring_prefix(self):
        """PRD §2.7: "Displacement consumes that ranking from the lowest score upward,
        accumulating quantities until the accumulated total is at least the incoming
        request's quantity, and every member of that prefix becomes `RECLAIMED`."
        PRD §2.7: "Candidates are ordered by score descending; ties are broken by the
        earliest creation timestamp among the candidate's holds on that SKU ascending".

        Design: Difficulty/combinatorial_formula/preemption_displacement_frozen_candidate_snapshot
        """
        partner, product, node, holds = self._three_requested_holds(capacity_units=1000)
        h200, h300, h400 = holds

        incoming = create_allocation_hold(product["id"], node["id"], 250, partner["id"],
                                          preempt_lower_tier=True)
        assert incoming["state"] == "COMMITTED", (
            f"the incoming displacing hold commits, got {incoming['state']!r}"
        )

        assert api.get_allocation_hold(h200["id"],
                                       make_partner_ops_headers(partner["id"])).json()["data"]["state"] == "RECLAIMED"
        assert api.get_allocation_hold(h300["id"],
                                       make_partner_ops_headers(partner["id"])).json()["data"]["state"] == "RECLAIMED"
        assert api.get_allocation_hold(h400["id"],
                                       make_partner_ops_headers(partner["id"])).json()["data"]["state"] == "REQUESTED"
        node = get_supply_node(node["id"])
        assert node["held_units"] == 650, (
            f"the 400-unit standby survives and the 250 incoming commits, so the pool "
            f"holds 400 + 250 = 650, got {node['held_units']}"
        )

    def test_rank_surface_orders_candidates_by_score_descending(self):
        """PRD §2.7: "Candidates are ordered by score descending; ties are broken by the
        earliest creation timestamp among the candidate's holds on that SKU ascending,
        and any remaining tie is broken by the hold's own creation timestamp ascending."
        PRD §3.3: "The review surface for ranking is an explicit capability on the pool
        that returns the ordered candidate list without mutating anything, so the
        ordering and its tie-breaks are directly observable."

        Design: Difficulty/combinatorial_formula/preemption_displacement_frozen_candidate_snapshot
        """
        partner, product, node, holds = self._three_requested_holds(capacity_units=1000)
        h200, h300, h400 = holds

        response = api.rank_supply_node(node["id"], PLANNER)
        ranking = validate_success(response)
        ids = [row["id"] for row in ranking]
        assert ids == [h400["id"], h300["id"], h200["id"]], (
            f"score rises with the requested quantity, so the largest standby ranks "
            f"first, got {ids}"
        )


class TestLifecycleFloor:
    """The commitment floor is derived from the requested horizon, then clamped by stage."""

    def test_embedded_commitment_floor_is_the_minimum_plus_the_extension(self):
        """PRD §3.9: "the commitment floor is the larger of the requested floor and the
        sum of the 1825-day minimum floor and the extension" and "an extension of 730
        days applies if the partner's type is `EMBEDDED_VENDOR`".

        Design: Difficulty/combinatorial_formula/lifecycle_commitment_floor_pinned_evaluation_order
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(
            legal_name="Vector Embedded Ltd", partner_type="EMBEDDED_VENDOR",
            destination_country="SG", export_restriction_tier="LICENSE_REQUIRED",
            blueprint_id=blueprint["id"])
        product = create_product(sku_code="AC-EMB-PCIE", product_family="EMBEDDED",
                                 tdp_watts=900, supply_ceiling_units=10000,
                                 long_term_availability_through="2032-01-01T00:00:00Z")
        product = advance_product_lifecycle(product["id"])

        commitment = create_lifecycle_commitment(
            product["id"], partner["id"], availability_through="2029-05-29T00:00:00Z",
            covered_units=500)
        product = get_product(product["id"])
        data = validate_success(api.grant_lifecycle_commitment(
            commitment["id"], {"expected_product_version": product["version"]}, LIFECYCLE))
        assert data["commitment_floor_days"] == 2555, (
            f"1825 minimum plus 730 embedded extension is 2555, got {data['commitment_floor_days']}"
        )

    def test_product_minimum_remaining_recovers_once_the_sku_reaches_maturity(self):
        """PRD §3.9: "the product's minimum remaining days is the commitment floor when
        the product's lifecycle stage is `MATURE` or `END_OF_LIFE`, and otherwise the
        commitment floor clamped down to a ceiling of 1825 days."

        Design: Difficulty/combinatorial_formula/lifecycle_commitment_floor_pinned_evaluation_order
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(
            legal_name="Vector Embedded Ltd", partner_type="EMBEDDED_VENDOR",
            destination_country="SG", export_restriction_tier="LICENSE_REQUIRED",
            blueprint_id=blueprint["id"])
        product = create_product(sku_code="AC-EMB-PCIE", product_family="EMBEDDED",
                                 tdp_watts=900, supply_ceiling_units=10000,
                                 long_term_availability_through="2032-01-01T00:00:00Z")
        product = advance_product_lifecycle(product["id"])

        commitment = create_lifecycle_commitment(
            product["id"], partner["id"], availability_through="2029-05-29T00:00:00Z",
            covered_units=500)
        product = get_product(product["id"])
        data = validate_success(api.grant_lifecycle_commitment(
            commitment["id"], {"expected_product_version": product["version"]}, LIFECYCLE))
        assert data["commitment_floor_days"] == 2555

        product = get_product(product["id"])
        assert product["lifecycle_stage"] == "GENERAL_AVAILABILITY"
        assert product["lifecycle_min_remaining_days"] == 1825, (
            f"at GENERAL_AVAILABILITY the floor is clamped back to 1825, "
            f"got {product['lifecycle_min_remaining_days']}"
        )

        product = advance_product_lifecycle(product["id"])
        get_success_data(api.advance_epoch(ADMIN))
        product = get_product(product["id"])
        assert product["lifecycle_stage"] == "MATURE"
        assert product["lifecycle_min_remaining_days"] == 2555, (
            f"MATURE is in the exempt set, so the floor is not clamped, "
            f"got {product['lifecycle_min_remaining_days']}"
        )