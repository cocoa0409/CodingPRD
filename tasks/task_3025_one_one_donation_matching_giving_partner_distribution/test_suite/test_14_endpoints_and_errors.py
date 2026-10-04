"""Action endpoints, their side effects and their refusals (PRD §3.3, §3.7–§3.9)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    commit_allocation,
    confirm_receipt,
    create_active_product,
    create_approved_partner,
    create_season,
    declare_capacity,
    get_liability_for,
    make_auditor_headers,
    onboard_partner,
    register_claim,
    set_clock,
    ship_allocation,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
PLANNER = TEST_USERS["planner_headers"]
FULFILL = TEST_USERS["fulfillment_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
MARKETING = TEST_USERS["marketing_headers"]


class TestSeasonSummaryRead:
    """Corner/endpoints — the roll-up is derived on read."""

    def test_a_partial_receipt_moves_only_the_received_figure(self, api):
        """PRD §3.7: "Selections may be made against the season's aggregates: `liability_carry_in_units` sums the carried-in units of its liabilities, `claim_frozen_units_total` sums the frozen units of its liabilities, `opening_carry_obligation_cents` sums the accrued obligation cents of its carried liabilities, `attributed_units_total` sums the attributed units of the partners who are `APPROVED` at the instant of computation, `total_shipped_units` and `total_received_units` sum the shipped and received units of its distributions, and `liability_reconciliation_delta` is the shipped units minus the frozen claim units, negative when claims understate what actually shipped."

        Design: Corner/endpoints/season_summary_computed_read_reflects_the_current_receipt_position
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=100)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=100, priority_tier="CRITICAL",
        )
        distribution = ship_allocation(allocation["id"], 100, "TRK-CR-1", "UPS")
        confirm_receipt(distribution["id"], 60, "RCV-CR-1")

        summary = validate_success(api_client.get_season_summary(season["id"], AUDITOR), 200)
        assert summary["total_shipped_units"] == 100
        assert summary["total_received_units"] == 60
        assert summary["attributed_units_total"] == 100
        assert summary["attributed_percentage_total"] == 100.0


class TestSeasonReopenAction:
    """Corner/endpoints — reopening walks every liability back to accumulation."""

    def test_reopening_a_closed_season_returns_it_to_open(self, api):
        """PRD §3.7: "A closed season can be reopened to `OPEN`, returning its liabilities to `ACCUMULATING`, but only before any audit of the season has been finalized."
        PRD §3.7: "Carry-forward is the make-up mechanism, and it exists because a published claim can promise more than a season actually froze. It requires that `required_stated_units` is strictly greater than `frozen_units` and that the season named by `carry_from_season_code` is `CLOSED`; when either fails the attempt is refused with `ERR_CARRY_PRECONDITION_UNMET` (HTTP 409). A successful carry-forward sets `carried_out_units` to the excess of the required stated units over the frozen units, hands the successor liability for the next season that many `carried_in_units`, places that successor in `ACCUMULATING` so the inherited units are folded into its own freeze, and recomputes the season's `liability_carry_in_units`."

        Design: Corner/endpoints/reopening_a_closed_season_returns_it_to_open_and_unfreezes_liabilities
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        # PRD §3.7 hands the carried-out units to "the successor liability for
        # the next season", so a PLANNED successor must exist for the
        # carry-forward to be in a state from which it is declared.
        create_season(
            season_code="2026-Q4",
            starts_at="2026-12-01T00:00:00Z",
            ends_at="2027-03-31T00:00:00Z",
            freezes_at="2027-02-15T00:00:00Z",
        )
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=100, priority_tier="CRITICAL",
        )
        distribution = ship_allocation(allocation["id"], 100, "TRK-RA-1", "UPS")
        confirm_receipt(distribution["id"], 100, "RCV-RA-1")

        set_clock("2026-12-02T00:00:00Z")
        liability = get_liability_for(product["id"], season["id"])
        validate_success(
            api_client.carry_forward_liability(
                liability["id"],
                {"claim_id": claim["id"], "expected_liability_version": liability["version"]},
                PLANNER,
            ),
            200,
        )
        validate_success(api_client.close_season(season["id"], {}, AUDITOR), 200)
        assert validate_success(
            api_client.get_impact_season(season["id"], AUDITOR), 200
        )["status"] == "CLOSED"

        validate_success(api_client.reopen_season(season["id"], {}, AUDITOR), 200)
        assert validate_success(
            api_client.get_impact_season(season["id"], AUDITOR), 200
        )["status"] == "OPEN"
        assert get_liability_for(product["id"], season["id"])["status"] == "ACCUMULATING"


class TestDistributionReachability:
    """Corner/endpoints — the nested create links the distribution to its allocation."""

    def test_the_distribution_is_reachable_from_its_allocation(self, api):
        """PRD §3.3: "The shipment must not exceed the allocation's `allocated_units` — an excess raises `ERR_SHIPMENT_EXCEEDS_ALLOCATION` (HTTP 409) — and must be at least one unit."

        Design: Corner/endpoints/shipping_creates_a_distribution_reachable_from_its_allocation
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=40, priority_tier="CRITICAL",
        )

        distribution = validate_success(
            api_client.create_distribution(
                allocation["id"],
                {
                    "shipped_units": 40,
                    "shipment_reference": "TRK-XR-1",
                    "carrier_code": "UPS",
                },
                FULFILL,
            ),
            201,
        )
        assert distribution["allocation_id"] == allocation["id"]
        assert distribution["status"] == "SHIPPED"
        assert distribution["received_units"] == 0
        assert distribution["impact_units_confirmed"] == 0

        nested = validate_success(
            api_client.list_allocation_distributions(allocation["id"], FULFILL), 200
        )
        assert len(nested) == 1
        assert nested[0]["id"] == distribution["id"]

        assert validate_success(
            api_client.get_allocation(allocation["id"], PLANNER), 200
        )["status"] == "SHIPPED"


class TestInactiveRequiresTerminalAllocations:
    """Corner/endpoints — deactivation is conditional on the allocation set."""

    def test_deactivation_is_refused_then_accepted_once_the_allocation_is_cancelled(self, api):
        """PRD §3.1: "Moving an `APPROVED` or a `SUSPENDED` partner to `INACTIVE` requires the target value to be `INACTIVE` and every allocation attributed to the partner to be in a terminal status; it supersedes all of the partner's capacity profiles."

        Design: Corner/endpoints/partner_cannot_be_deactivated_while_an_allocation_is_live
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=40, priority_tier="CRITICAL",
        )

        refused = api_client.set_partner_status(partner["id"], {"status": "INACTIVE"}, COORD)
        validate_error(refused, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
        from test_helpers import get_partner

        assert get_partner(partner["id"])["status"] == "APPROVED"

        current = validate_success(api_client.get_allocation(allocation["id"], PLANNER), 200)
        validate_success(
            api_client.cancel_allocation(
                allocation["id"], {"expected_allocation_version": current["version"]}, PLANNER
            ),
            200,
        )
        validate_success(
            api_client.set_partner_status(partner["id"], {"status": "INACTIVE"}, COORD), 200
        )
        assert get_partner(partner["id"])["status"] == "INACTIVE"

        profiles = validate_success(
            api_client.list_partner_capacity_profiles(partner["id"], PLANNER), 200
        )
        assert all(p["status"] == "SUPERSEDED" for p in profiles)


class TestShippingAndReceiptCeilings:
    """Corner/errors — the two shipment/ receipt bounds."""

    def _approved_allocation(self, units):
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=units, priority_tier="CRITICAL",
        )
        return season, product, partner, claim, allocation

    def test_shipping_one_unit_over_the_allocation_is_refused(self, api):
        """PRD §3.3: "The shipment must not exceed the allocation's `allocated_units` — an excess raises `ERR_SHIPMENT_EXCEEDS_ALLOCATION` (HTTP 409) — and must be at least one unit."

        Design: Corner/errors/shipping_more_than_the_allocation_returns_shipment_exceeds_allocation
        """
        season, product, partner, claim, allocation = self._approved_allocation(40)

        res = api_client.create_distribution(
            allocation["id"],
            {
                "shipped_units": 41,
                "shipment_reference": "TRK-ERR-1",
                "carrier_code": "UPS",
            },
            FULFILL,
        )
        validate_error(res, "ERR_SHIPMENT_EXCEEDS_ALLOCATION", expected_status=409)
        assert validate_success(
            api_client.get_allocation(allocation["id"], PLANNER), 200
        )["status"] == "APPROVED"

        validate_success(
            api_client.create_distribution(
                allocation["id"],
                {
                    "shipped_units": 40,
                    "shipment_reference": "TRK-ERR-1B",
                    "carrier_code": "UPS",
                },
                FULFILL,
            ),
            201,
        )
        assert validate_success(
            api_client.get_allocation(allocation["id"], PLANNER), 200
        )["status"] == "SHIPPED"

    def test_a_receipt_that_would_exceed_the_shipment_is_refused(self, api):
        """PRD §3.3: "A confidence that would push the cumulative confirmed figure above `shipped_units` is refused with `ERR_RECEIPT_EXCEEDS_SHIPMENT` (HTTP 409), and a receipt confirmed against a distribution that has already been completed, written off or voided is refused with `ERR_DISTRIBUTION_NOT_IN_TRANSIT` (HTTP 409)."
        PRD §3.3: "Receipt is confirmed by the partner side. A `GivingPartnerCoordinator` confirms `received_units` against a `receipt_reference`, and the confirmation accumulates rather than replacing: `received_units` is the running sum of confirmed receipts, and the distribution is addressed through its `distribution_id` on every subsequent step of its life."

        Design: Corner/errors/confirming_more_units_than_were_shipped_returns_receipt_exceeds_shipment
        """
        season, product, partner, claim, allocation = self._approved_allocation(10)
        distribution = ship_allocation(allocation["id"], 10, "TRK-ERR-2", "UPS")
        confirm_receipt(distribution["id"], 6, "RCV-ERR-2A")

        over = api_client.create_receipt(
            distribution["id"],
            {"received_units": 5, "receipt_reference": "RCV-ERR-2B"},
            COORD,
        )
        validate_error(over, "ERR_RECEIPT_EXCEEDS_SHIPMENT", expected_status=409)

        current = validate_success(
            api_client.get_distribution(distribution["id"], FULFILL), 200
        )
        assert current["received_units"] == 6
        assert current["status"] == "PARTIALLY_RECEIVED"

        validate_success(
            api_client.create_receipt(
                distribution["id"],
                {"received_units": 4, "receipt_reference": "RCV-ERR-2C"},
                COORD,
            ),
            200,
        )
        final = validate_success(
            api_client.get_distribution(distribution["id"], FULFILL), 200
        )
        assert final["status"] == "RECEIVED"
        assert final["received_units"] == 10


class TestAuditSegregationOfDuties:
    """Corner/errors — the four-eyes rule is on the acting identifier."""

    def test_the_auditor_who_opened_the_fieldwork_cannot_finalize(self, api):
        """PRD §2.12: "The acting `X-User-ID` may not be the same identifier that performed the preliminary review of that audit; if it is, the finalization is refused with `ERR_AUDIT_SOD_VIOLATION` (HTTP 403) rather than the generic stale or state errors."

        Design: Corner/errors/the_auditor_who_started_the_audit_cannot_finalize_it
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=100)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=100, priority_tier="CRITICAL",
        )
        distribution = ship_allocation(allocation["id"], 100, "TRK-SOD-1", "UPS")
        confirm_receipt(distribution["id"], 100, "RCV-SOD-1")

        set_clock("2026-12-02T00:00:00Z")
        audit = validate_success(
            api_client.create_impact_audit(
                {
                    "impact_season_id": season["id"],
                    "claim_id": claim["id"],
                    "audit_kind": "ANNUAL_IMPACT",
                },
                AUDITOR,
            ),
            201,
        )
        started = validate_success(
            api_client.start_audit(audit["id"], {}, make_auditor_headers("aud-alpha")), 200
        )

        blocked = api_client.finalize_audit(
            audit["id"],
            {
                "transaction_test_sample_size": 20,
                "transaction_test_exceptions": 0,
                "claimed_donation_units": 100,
                "expected_audit_version": started["version"],
            },
            make_auditor_headers("aud-alpha"),
        )
        validate_error(blocked, "ERR_AUDIT_SOD_VIOLATION", expected_status=403)
        assert validate_success(
            api_client.get_impact_audit(audit["id"], AUDITOR), 200
        )["status"] == "IN_PROGRESS"

        validate_success(
            api_client.finalize_audit(
                audit["id"],
                {
                    "transaction_test_sample_size": 20,
                    "transaction_test_exceptions": 0,
                    "claimed_donation_units": 100,
                    "expected_audit_version": started["version"],
                },
                make_auditor_headers("aud-beta"),
            ),
            200,
        )


class TestExpiredVettingRound:
    """Corner/errors — a terminal round refuses a late outcome."""

    def test_a_late_outcome_write_is_refused(self, api):
        """PRD §3.1: "Rounds can also expire. If the logical clock passes a round's `valid_until` while the round is still `REQUESTED`, the system expires it: the round's outcome becomes `EXPIRED`, the partner returns to `CANDIDATE`, and — when the season containing the current clock has reached `FROZEN` or `CLOSED` — a capacity profile is created for the next `PLANNED` season. Any attempt to record a further outcome against a round that is already terminal produces `ERR_VETTING_ROUND_TERMINAL` (HTTP 409)."

        Design: Corner/errors/an_expired_vetting_round_refuses_a_late_outcome
        """
        set_clock("2026-09-01T00:00:00Z")
        partner = onboard_partner(
            legal_name="Psi Short Window Coop",
            partner_type="YOUTH_OUTREACH",
            operating_region="SOUTHEAST",
            operating_state_code="NC",
            registry_id="NC-CHR-230023",
            ein="300400700",
            unduplicated_recipients_per_facility=2500,
            need_tier="MODERATE",
        )
        vetting_id = partner["latest_vetting_round_id"]
        # PRD §2.11: "No write may fall after the resolved season's `freezes_at`
        # instant", and §3.1's expiry needs the season holding the clock to have
        # reached `FROZEN` or `CLOSED`.  A second season whose calendar the
        # clock's later instant actually falls inside keeps the fixture on the
        # expiry path rather than on the freeze boundary.
        create_season(
            season_code="2026-Q4",
            starts_at="2026-09-01T00:00:00Z",
            ends_at="2027-03-31T00:00:00Z",
            freezes_at="2027-02-15T00:00:00Z",
        )
        validate_success(
            api_client.update_vetting_round(
                vetting_id,
                {
                    "outcome": "DOCUMENTS_SUBMITTED",
                    "registry_check_passed": True,
                    "tax_check_passed": True,
                    "valid_until": "2026-09-10T00:00:00Z",
                },
                COORD,
            ),
            200,
        )

        set_clock("2026-09-20T00:00:00Z")
        res = api_client.update_vetting_round(
            vetting_id,
            {
                "outcome": "EVALUATING",
                "registry_check_passed": True,
                "tax_check_passed": True,
                "on_site_check_passed": True,
                "capacity_check_passed": True,
                "need_verification_points": 1,
                "valid_until": "2027-01-01T00:00:00Z",
            },
            COORD,
        )
        validate_error(res, "ERR_VETTING_ROUND_TERMINAL", expected_status=409)

        round_row = validate_success(api_client.get_vetting_round(vetting_id, COORD), 200)
        assert round_row["outcome"] == "EXPIRED"
        assert validate_success(
            api_client.get_giving_partner(partner["id"], COORD), 200
        )["status"] == "CANDIDATE"