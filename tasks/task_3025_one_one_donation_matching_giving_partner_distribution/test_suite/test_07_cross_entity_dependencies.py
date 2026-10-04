"""Rules whose outcome depends on another entity's state (PRD §3.9, §3.5, §3.6)."""
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
    get_impact_audit,
    get_liability_for,
    get_season,
    make_auditor_headers,
    pay_order,
    register_claim,
    set_clock,
    ship_allocation,
    confirm_receipt,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
MARKETING = TEST_USERS["marketing_headers"]
FULFILL = TEST_USERS["fulfillment_headers"]
SERVICE = TEST_USERS["customer_service_headers"]


class TestClaimStateBlocksAuditFinalization:
    """Difficulty/cross_entity_state_dependency — the audit's gate lives in another table."""

    def _claim_overstated_scenario(self):
        """A frozen season with a shipped distribution and a claim pushed to OVERSTATED."""
        set_clock("2026-08-15T00:00:00Z")
        season = create_season(
            season_code="2026-Q2",
            starts_at="2026-06-01T00:00:00Z",
            ends_at="2026-08-31T00:00:00Z",
            freezes_at="2026-09-01T00:00:00Z",
        )
        # PRD §3.3: "A distribution that reaches `RECEIVED` inside a `PLANNED`
        # season is demoted back to `SHIPPED` ... when the season transitions
        # onward." Opening the season first keeps the receipt settled.
        set_clock("2026-08-15T00:00:00Z")
        product = create_active_product(
            product_name="Trail Runner Crew",
            product_kind="ATHLETIC_SOCK",
            design_channel="DUAL_CHANNEL",
            obligation_model="AT_SALE",
            retail_price_cents=2000,
            unit_cost_cents=1200,
            is_reusable=True,
        )
        add_product_line(product["id"], "00000000000201", "M", True)
        partner = create_approved_partner(
            legal_name="Xi Coastal Shelter",
            operating_region="WEST",
            operating_state_code="CA",
            registry_id="CA-CHR-140014",
            ein="100200600",
            unduplicated_recipients_per_facility=18000,
            need_tier="MODERATE",
        )
        declare_capacity(partner["id"], max_allocatable_units=30000, season_code="2026-Q2")
        claim = register_claim(
            product["id"], partner["id"], stated_donation_units=12000
        )
        # PRD §2.6: an allocation draws on the covering liability's available
        # units, so the promise must be backed by a real sales obligation
        # before the commitment is made.
        order = create_order(order_number="SO-XED-FUND", channel="RETAIL_ECOM")
        fund_line = add_product_line(product["id"], "00000000000299", "L", True)
        # 14,000 units backs both the standing 12,000 commitment and the
        # 2,000-unit shipped slice that gives the season distribution rows.
        add_line(order["id"], fund_line["id"], quantity=14000, unit_price_cents=2000)
        pay_order(order["id"])
        # A standing commitment carries the claim over the floor ...
        standing = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=12000, priority_tier="CRITICAL",
        )
        # ... and a shipped slice gives the season real distribution rows.
        shipped = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=2000, priority_tier="CRITICAL",
        )
        distribution = ship_allocation(shipped["id"], 1000, "TRK-XED-1", "FXF")
        confirm_receipt(distribution["id"], 1000, "RCV-XED-1")
        validate_success(api_client.substantiate_claim(claim["id"], {}, MARKETING), 200)
        _ = fund_line
        assert get_claim(claim["id"])["status"] == "SUBSTANTIATED"

        # Cancelling the standing commitment drops the ratio below the floor.
        allocation = get_allocation(standing["id"])
        validate_success(
            api_client.cancel_allocation(
                standing["id"], {"expected_allocation_version": allocation["version"]}, PLANNER
            ),
            200,
        )
        set_clock("2026-09-01T00:00:00Z")
        liability = get_liability_for(product["id"], season["id"])
        validate_success(
            api_client.derive_build_claim(
                claim["id"], {"expected_liability_version": liability["version"]}, MARKETING
            ),
            200,
        )
        assert get_claim(claim["id"])["status"] == "OVERSTATED"

        audit = validate_success(
            api_client.create_impact_audit(
                {
                    "impact_season_id": season["id"],
                    "claim_id": claim["id"],
                    "audit_kind": "ANNUAL_IMPACT",
                },
                TEST_USERS["auditor_headers"],
            ),
            201,
        )
        started = validate_success(
            api_client.start_audit(audit["id"], {}, make_auditor_headers("aud-alpha")), 200
        )
        return season, product, partner, claim, audit, started

    def test_overstated_claim_refuses_the_finalization(self, api):
        """PRD §3.9: "No claim for the season may be `OVERSTATED` at that instant."
        PRD §3.8: "Running the derive-build carry-forward — guarded by `expected_liability_version` — recomputes the liability's required stated units, re-derives the season's reporting claim at the point of the freeze or at the first final read, and moves a substantiated claim to `OVERSTATED` when the ratio falls below the floor after the carry-forward; that move can in turn push the liability to `CARRIED` when its required stated units exceed its frozen units, and it advances the liability's version."

        Design: Difficulty/cross_entity_state_dependency/claim_substantiation_blocks_the_audit_finalization_that_grades_partners
        """
        season, product, partner, claim, audit, started = self._claim_overstated_scenario()
        assert get_claim(claim["id"])["status"] == "OVERSTATED"

        res = api_client.finalize_audit(
            audit["id"],
            {
                # PRD §3.9: "The sample size is the smaller of the total
                # distribution count and the larger of two floors: one quarter
                # of the count of critical distributions rounded up, and that
                # count divided by forty rounded up." The season holds a single
                # distribution, so the floor is one.
                "transaction_test_sample_size": 1,
                "transaction_test_exceptions": 0,
                "claimed_donation_units": 1000,
                "expected_audit_version": started["version"],
            },
            make_auditor_headers("aud-beta"),
        )
        # PRD §3.9 states the gate ("No claim for the season may be `OVERSTATED`
        # at that instant") without naming the error_id the refusal carries, so
        # the assertion is the refusal itself and the state it leaves behind.
        assert res.status_code == 409, res.text[:200]

        assert get_impact_audit(audit["id"])["status"] == "IN_PROGRESS"
        assert get_season(season["id"])["status"] == "FROZEN"

    def test_revoking_the_claim_lets_the_identical_finalization_succeed(self, api):
        """PRD §3.8: "A `MarketingManager` may revoke a claim in `SUBSTANTIATED` or `OVERSTATED` — supplying a `reason` — provided the claim has not already been finalized inside an impact audit."
        PRD §3.9: "No claim for the season may be `OVERSTATED` at that instant."
        PRD §3.9: "A successful finalization computes the clearance rate, the `scorecard_total` and the grade from the submitted `claimed_donation_units`; writes the partner performance grade for every rated partner; moves the season to `FINALIZED` and advances its version; moves the season's liabilities to `AUDIT_LOCKED` and then to `CLOSED` where carry-out was materialized; recomputes the reconciliation delta; expires the season's claims; stamps `finalized_at`; and advances the audit's own version."
        PRD §3.9: "`unit_clearance_rate` is the received figure divided by the shipped figure, rounded half up to four decimal places and null when nothing shipped."

        Design: Difficulty/cross_entity_state_dependency/claim_substantiation_blocks_the_audit_finalization_that_grades_partners
        """
        season, product, partner, claim, audit, started = self._claim_overstated_scenario()

        validate_success(
            api_client.revoke_claim(
                claim["id"], {"reason": "Public statement withdrawn"}, MARKETING
            ),
            200,
        )
        assert get_claim(claim["id"])["status"] == "REVOKED"

        fresh = get_impact_audit(audit["id"])
        finalized = validate_success(
            api_client.finalize_audit(
                audit["id"],
                {
                    # PRD §3.9's floor for a season holding one distribution.
                    "transaction_test_sample_size": 1,
                    "transaction_test_exceptions": 0,
                    "claimed_donation_units": 1000,
                    "expected_audit_version": fresh["version"],
                },
                make_auditor_headers("aud-beta"),
            ),
            200,
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["shipped_units_verified"] == 1000
        assert finalized["received_units_verified"] == 1000
        assert finalized["unit_clearance_rate"] == 1.0
        assert get_season(season["id"])["status"] == "FINALIZED"


class TestLineTransitionsDependOnTheOrder:
    """Difficulty/cross_entity_state_dependency — the line rides the order's two axes."""

    def _paid_order_scenario(self):
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product(
            product_name="Cozy Cabin Sock",
            product_kind="ATHLETIC_SOCK",
            design_channel="DUAL_CHANNEL",
            obligation_model="AT_SALE",
            retail_price_cents=1900,
            unit_cost_cents=1050,
            is_reusable=True,
        )
        line = add_product_line(product["id"], "00000000000202", "M", False)
        order = create_order(order_number="SO-XED-2", channel="RETAIL_POS")
        soline = add_line(order["id"], line["id"], quantity=2, unit_price_cents=1900)
        pay_order(order["id"])
        return season, product, order, soline

    def test_return_opens_while_the_order_is_paid(self, api):
        """PRD §3.6: "A successful open creates a return request in status `REQUESTED` with `liability_delta_units` of zero, moves the line to `RETURN_REQUESTED`, and advances the line's `version`."
        PRD §3.6: "The firewall itself is absolute. Crediting a return never reduces the final liability ledger and never decreases a line's `obligated_units`; the request's `liability_delta_units` is zero on every path, whether the customer took a refund or a replacement, and the liability row behind the original sale — recorded on the request as the `donation_liability_id` of the sale — retains its units throughout."

        Design: Difficulty/cross_entity_state_dependency/line_valid_transitions_depend_on_the_owning_order_fulfillment_dimension
        """
        season, product, order, soline = self._paid_order_scenario()
        line_version = validate_success(
            api_client.get_order_line(order["id"], soline["id"], SERVICE), 200
        )["version"]

        validate_success(
            api_client.open_line_return_request(
                order["id"], soline["id"],
                {
                    "request_reason": "SIZE",
                    "requested_units": 1,
                    "is_exchange": False,
                    "expected_line_version": line_version,
                },
                SERVICE,
            ),
            201,
        )

        opened_order = validate_success(api_client.get_sales_order(order["id"], SERVICE), 200)
        assert opened_order["status"] == "PAID"
        assert opened_order["fulfillment_status"] == "PLACED"
        assert validate_success(
            api_client.get_order_line(order["id"], soline["id"], SERVICE), 200
        )["status"] == "RETURN_REQUESTED"

        liability = get_liability_for(product["id"], season["id"])
        assert liability["final_liability_units"] == 2

    def test_fulfillment_moves_independently_and_never_regresses(self, api):
        """PRD §3.5: "The `fulfillment_status` dimension is genuinely independent of the order's own status: it moves through `PLACED`, `PICKED`, `SHIPPED`, `DELIVERED` and `CANCELLED`, and it is deliberately not a precondition for the order's donation status, so an order can be donation-satisfied while still merely placed, or delivered while still merely paid."
        PRD §3.5: "The fulfillment dimension is advanced separately by a `FulfillmentOperator` supplying a `fulfillment_status`; the target must be strictly later than the stored one, and a regression is refused with `ERR_FULFILLMENT_REGRESSION` (HTTP 409)."
        PRD §3.5: "An order in `PAID` whose `fulfillment_status` is still `PLACED` may also be cancelled, which returns it to `CREATED` for correction of the verified settlement time and reduces the liability's `provisional_liability_units` by the order's line obligations."

        Design: Difficulty/cross_entity_state_dependency/line_valid_transitions_depend_on_the_owning_order_fulfillment_dimension
        """
        season, product, order, soline = self._paid_order_scenario()
        line_version = validate_success(
            api_client.get_order_line(order["id"], soline["id"], SERVICE), 200
        )["version"]
        validate_success(
            api_client.open_line_return_request(
                order["id"], soline["id"],
                {
                    "request_reason": "SIZE",
                    "requested_units": 1,
                    "is_exchange": False,
                    "expected_line_version": line_version,
                },
                SERVICE,
            ),
            201,
        )

        advanced = validate_success(
            api_client.update_fulfillment(
                order["id"], {"fulfillment_status": "SHIPPED"}, FULFILL
            ),
            200,
        )
        assert advanced["status"] == "PAID"
        assert advanced["fulfillment_status"] == "SHIPPED"

        regressed = api_client.update_fulfillment(
            order["id"], {"fulfillment_status": "PLACED"}, FULFILL
        )
        validate_error(regressed, "ERR_FULFILLMENT_REGRESSION", expected_status=409)

        refused = api_client.cancel_order(order["id"], {}, SERVICE)
        validate_error(refused, "ERR_INVALID_STATE_TRANSITION", expected_status=409)

        liability = get_liability_for(product["id"], season["id"])
        assert liability["final_liability_units"] == 2