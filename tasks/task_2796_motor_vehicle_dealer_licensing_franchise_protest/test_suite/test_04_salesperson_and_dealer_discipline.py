"""Discipline: the salesperson's two dimensions, the dealership's point
thresholds and the cascade from one complaint resolution.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import LICENSING_ANALYST


def _licensed_dealer_with_salesperson():
    """A licensed dealership sponsoring one licensed salesperson from 2026-09-02."""
    ctx = fx.setup_licensed_dealer()
    fx.set_clock("2026-09-02T00:00:00Z")
    ctx["salesperson"] = fx.license_salesperson(ctx["dealer"]["id"], full_name="Dana Reyes")
    return ctx


class TestSalespersonParallelDimensions:
    def test_probation_moves_discipline_while_the_licence_stands(self, api):
        """PRD 3.3: "At 6 or more points but fewer than 9, a `CLEAR` salesperson
        moves to `PROBATION`." PRD 3.3: "None of these movements touches
        `license_status`: a salesperson on `PROBATION` keeps selling, and the
        discipline dimension alone is what blocks a renewal approval." PRD 3.9
        fixes the weight: "a `PROBATION` carries 6".

        Design: Difficulty/non_linear_state_machine/salesperson_parallel_license_and_discipline_dimensions
        """
        ctx = _licensed_dealer_with_salesperson()
        salesperson = ctx["salesperson"]
        assert salesperson["license_status"] == "LICENSED"
        assert salesperson["discipline_status"] == "CLEAR"
        assert salesperson["license_expires_on"] == "2027-09-01"

        fx.set_clock("2026-09-05T00:00:00Z")
        fx.sanction_complaint(
            ctx["dealer"]["id"], "PROBATION", 200000, "ADVERTISING_VIOLATION",
            salesperson_id=salesperson["id"],
            findings_code="MISLEADING_PRICE_ADVERTISEMENT")

        after = fx.read_salesperson(salesperson["id"])
        assert after["disciplinary_points"] == 6
        assert after["discipline_status"] == "PROBATION"
        assert after["license_status"] == "LICENSED"
        assert after["license_expires_on"] == "2027-09-01"

    def test_nine_points_suspend_the_discipline_dimension_only(self, api):
        """PRD 3.3: "At 9 or more points, a salesperson on `PROBATION` moves to
        `SUSPENDED_DISCIPLINARY`, and a salesperson still `CLEAR` moves straight
        to `SUSPENDED_DISCIPLINARY` as well". The sponsoring dealership reads the
        same 9 points against its own thresholds and PRD 3.9 only acts "Where the
        recomputed total reaches 12 but stays below 18", so its licence and its
        `licensed_salesperson_count` are untouched.

        Design: Difficulty/non_linear_state_machine/salesperson_parallel_license_and_discipline_dimensions
        """
        ctx = _licensed_dealer_with_salesperson()
        salesperson, dealer = ctx["salesperson"], ctx["dealer"]
        fx.set_clock("2026-09-05T00:00:00Z")
        fx.sanction_complaint(
            dealer["id"], "PROBATION", 200000, "ADVERTISING_VIOLATION",
            salesperson_id=salesperson["id"],
            findings_code="MISLEADING_PRICE_ADVERTISEMENT")

        second = fx.sanction_complaint(
            dealer["id"], "CIVIL_PENALTY", 100000, "DEPOSIT_RETENTION",
            salesperson_id=salesperson["id"],
            findings_code="DEPOSIT_NOT_REFUNDED")

        assert second["points_assessed"] == 3
        assert second["restitution_ordered_cents"] == 100000
        assert second["civil_penalty_cents"] == 80000

        after = fx.read_salesperson(salesperson["id"])
        assert after["disciplinary_points"] == 9
        assert after["discipline_status"] == "SUSPENDED_DISCIPLINARY"
        assert after["license_status"] == "LICENSED"

        sponsor = fx.read_dealer(dealer["id"])
        assert sponsor["disciplinary_points"] == 9
        assert sponsor["license_status"] == "LICENSED"
        assert sponsor["suspension_reason"] == "NONE"
        assert sponsor["licensed_salesperson_count"] == 1
        assert sponsor["restitution_outstanding_cents"] == 300000


class TestDealerPointThresholds:
    def test_nine_points_stay_one_sanction_short_of_suspension(self, api):
        """PRD 3.9: "Where the recomputed total reaches 12 but stays below 18, the
        dealership moves `LICENSED → SUSPENDED` with `suspension_reason` set to
        `DISCIPLINARY_POINTS`". A 6-point probation and a 3-point civil penalty
        total 9, so the licence dimension must not move at all.

        Design: Difficulty/boundary_precision_check/dealer_points_exactly_twelve_triggers_suspension
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        fx.set_clock("2026-09-05T00:00:00Z")
        fx.sanction_complaint(dealer["id"], "PROBATION", 200000, "ADVERTISING_VIOLATION",
                              findings_code="MISLEADING_PRICE_ADVERTISEMENT")
        fx.set_clock("2026-09-06T00:00:00Z")
        fx.sanction_complaint(dealer["id"], "CIVIL_PENALTY", 100000, "DEPOSIT_RETENTION",
                              findings_code="DEPOSIT_NOT_REFUNDED")

        after = fx.read_dealer(dealer["id"])
        assert after["disciplinary_points"] == 9
        assert after["license_status"] == "LICENSED"
        assert after["suspension_reason"] == "NONE"
        assert after["restitution_outstanding_cents"] == 300000

    def test_exactly_twelve_points_suspend_without_revoking(self, api):
        """PRD 3.9: "Where the recomputed total reaches 12 but stays below 18, the
        dealership moves `LICENSED → SUSPENDED` with `suspension_reason` set to
        `DISCIPLINARY_POINTS`". The inclusive edge is 12, and PRD 3.9 reserves
        revocation for the case "Where the recomputed total reaches 18, the
        dealership moves `LICENSED → REVOKED` with `suspension_reason` left at
        `NONE`", so a dealership landing exactly on 12 suspends without revoking.

        Design: Difficulty/boundary_precision_check/dealer_points_exactly_twelve_triggers_suspension
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        fx.set_clock("2026-09-05T00:00:00Z")
        fx.sanction_complaint(dealer["id"], "PROBATION", 200000, "ADVERTISING_VIOLATION",
                              findings_code="MISLEADING_PRICE_ADVERTISEMENT")
        fx.set_clock("2026-09-06T00:00:00Z")
        fx.sanction_complaint(dealer["id"], "CIVIL_PENALTY", 100000, "DEPOSIT_RETENTION",
                              findings_code="DEPOSIT_NOT_REFUNDED")
        assert fx.read_dealer(dealer["id"])["disciplinary_points"] == 9

        fx.set_clock("2026-09-07T00:00:00Z")
        third = fx.sanction_complaint(
            dealer["id"], "CIVIL_PENALTY", 100000, "DEPOSIT_RETENTION",
            findings_code="DEPOSIT_NOT_REFUNDED")

        assert third["points_assessed"] == 3
        assert third["civil_penalty_cents"] == 80000
        after = fx.read_dealer(dealer["id"])
        assert after["disciplinary_points"] == 12
        assert after["license_status"] == "SUSPENDED"
        assert after["license_status"] != "REVOKED"
        assert after["suspension_reason"] == "DISCIPLINARY_POINTS"
        assert after["restitution_outstanding_cents"] == 400000


class TestSanctionCascade:
    def test_one_resolution_suspends_the_dealership_and_both_salespersons(self, api):
        """PRD 3.9: "each of its salespersons in `LICENSED` or `RENEWAL_PENDING`
        moves to `SUSPENDED_BY_SPONSOR`; and because none remain in force,
        `licensed_salesperson_count` is recomputed to 0." Nothing in the
        resolution request names a salesperson or a licence, so the whole effect
        arrives through the dealership's recomputed point total.

        Design: Difficulty/transitive_cascade/complaint_sanction_to_dealer_suspension_to_salesperson_to_count
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        fx.set_clock("2026-09-02T00:00:00Z")
        first = fx.license_salesperson(dealer["id"], full_name="Dana Reyes")
        second = fx.license_salesperson(dealer["id"], full_name="Owen Marsh")
        assert fx.read_dealer(dealer["id"])["licensed_salesperson_count"] == 2

        fx.set_clock("2026-09-05T00:00:00Z")
        fx.sanction_complaint(dealer["id"], "PROBATION", 200000, "ADVERTISING_VIOLATION",
                              findings_code="MISLEADING_PRICE_ADVERTISEMENT")
        fx.set_clock("2026-09-06T00:00:00Z")
        fx.sanction_complaint(dealer["id"], "CIVIL_PENALTY", 100000, "DEPOSIT_RETENTION",
                              findings_code="DEPOSIT_NOT_REFUNDED")
        assert fx.read_dealer(dealer["id"])["license_status"] == "LICENSED"

        fx.set_clock("2026-09-07T00:00:00Z")
        fx.sanction_complaint(dealer["id"], "PROBATION", 400000,
                              "FAILURE_TO_TRANSFER_TITLE",
                              findings_code="TITLE_NOT_TRANSFERRED")

        after = fx.read_dealer(dealer["id"])
        assert after["disciplinary_points"] == 15
        assert after["license_status"] == "SUSPENDED"
        assert after["suspension_reason"] == "DISCIPLINARY_POINTS"
        assert after["licensed_salesperson_count"] == 0
        assert fx.read_salesperson(first["id"])["license_status"] == "SUSPENDED_BY_SPONSOR"
        assert fx.read_salesperson(second["id"])["license_status"] == "SUSPENDED_BY_SPONSOR"
        assert fx.read_salesperson(first["id"])["discipline_status"] == "CLEAR"

    def test_the_cascade_leaves_the_franchise_dimension_and_bills_the_ledger(self, api):
        """PRD 2.7 keeps the dimensions apart, and PRD 3.9 states the ledger
        arithmetic: "`restitution_ordered_cents` is the consumer's
        `alleged_loss_cents` capped at 1,500,000 cents (fifteen thousand
        dollars)." PRD 3.9: "`restitution_due_on` is set to 30 days after the
        resolution date and `restitution_paid_cents` is left at 0."

        Design: Difficulty/transitive_cascade/complaint_sanction_to_dealer_suspension_to_salesperson_to_count
        """
        ctx = fx.setup_licensed_dealer()
        dealer = ctx["dealer"]
        fx.set_clock("2026-09-05T00:00:00Z")
        fx.sanction_complaint(dealer["id"], "PROBATION", 200000, "ADVERTISING_VIOLATION",
                              findings_code="MISLEADING_PRICE_ADVERTISEMENT")
        fx.set_clock("2026-09-06T00:00:00Z")
        fx.sanction_complaint(dealer["id"], "CIVIL_PENALTY", 100000, "DEPOSIT_RETENTION",
                              findings_code="DEPOSIT_NOT_REFUNDED")

        fx.set_clock("2026-09-07T00:00:00Z")
        third = fx.sanction_complaint(dealer["id"], "PROBATION", 400000,
                                      "FAILURE_TO_TRANSFER_TITLE",
                                      findings_code="TITLE_NOT_TRANSFERRED")

        assert third["status"] == "SANCTIONED"
        assert third["points_assessed"] == 6
        assert third["restitution_ordered_cents"] == 400000
        assert third["civil_penalty_cents"] == 120000
        assert third["restitution_due_on"] == "2026-10-07"
        assert third["restitution_paid_cents"] == 0

        after = fx.read_dealer(dealer["id"])
        assert after["restitution_outstanding_cents"] == 700000
        assert after["franchise_status"] == "FRANCHISED"


def _two_dealers_one_suspended():
    """Two licensed dealerships, each sponsoring a salesperson left at PENDING;
    the first is then driven to exactly 12 points and suspended."""
    fx.set_clock("2026-09-01T00:00:00Z")
    suspended = fx.create_dealer(legal_name="Lakeside Aurora", site_x_km=0, site_y_km=0)
    fx.license_dealer(suspended["id"])
    intact = fx.create_dealer(legal_name="Harbor Aurora", site_x_km=20, site_y_km=0)
    fx.license_dealer(intact["id"])

    fx.set_clock("2026-09-02T00:00:00Z")
    pending_suspended = fx.sponsor_salesperson(suspended["id"], full_name="Dana Reyes")
    pending_intact = fx.sponsor_salesperson(intact["id"], full_name="Owen Marsh")

    fx.set_clock("2026-09-05T00:00:00Z")
    fx.sanction_complaint(suspended["id"], "PROBATION", 200000, "ADVERTISING_VIOLATION",
                          findings_code="MISLEADING_PRICE_ADVERTISEMENT")
    fx.set_clock("2026-09-06T00:00:00Z")
    fx.sanction_complaint(suspended["id"], "CIVIL_PENALTY", 100000, "DEPOSIT_RETENTION",
                          findings_code="DEPOSIT_NOT_REFUNDED")
    fx.set_clock("2026-09-07T00:00:00Z")
    fx.sanction_complaint(suspended["id"], "CIVIL_PENALTY", 100000, "DEPOSIT_RETENTION",
                          findings_code="DEPOSIT_NOT_REFUNDED")
    return {
        "suspended_dealer": fx.read_dealer(suspended["id"]),
        "intact_dealer": fx.read_dealer(intact["id"]),
        "pending_suspended": pending_suspended,
        "pending_intact": pending_intact,
    }


class TestSalespersonDecisionReadsTheSponsor:
    def test_suspended_sponsor_bars_the_initial_licence(self, api):
        """PRD 3.3: "Every approval, initial or renewal, requires the sponsoring
        dealership's `license_status` to be `LICENSED`; a sponsor that has fallen
        out of `LICENSED` bars the approval with `ERR_SPONSOR_NOT_LICENSED`
        unless the analyst records `waiver_granted` as true." The applicant is
        still `PENDING`, so PRD 3.3's cascade — which moves "each of its
        salespersons in `LICENSED` or `RENEWAL_PENDING`" — never touched it.

        Design: Difficulty/cross_entity_state_dependency/salesperson_license_decision_blocked_by_suspended_sponsor
        """
        ctx = _two_dealers_one_suspended()
        assert ctx["suspended_dealer"]["license_status"] == "SUSPENDED"
        applicant = ctx["pending_suspended"]
        assert applicant["license_status"] == "PENDING"

        response = api.decide_salesperson_license(
            applicant["id"], f.salesperson_decision_payload("APPROVED"), LICENSING_ANALYST)
        validate_error(response, ApiErrorId.ERR_SPONSOR_NOT_LICENSED.value)

        after = fx.read_salesperson(applicant["id"])
        assert after["license_status"] == "PENDING"
        assert after["license_effective_on"] is None
        assert after["license_expires_on"] is None
        assert fx.read_dealer(ctx["suspended_dealer"]["id"])["licensed_salesperson_count"] == 0

    def test_licensed_sponsor_admits_the_identical_decision(self, api):
        """PRD 3.3: "An approval from `PENDING` moves the licence dimension
        `PENDING → LICENSED`, sets `license_effective_on` to the clock date and
        `license_expires_on` to 364 days later — a salesperson term is 365 days,
        with the expiry date the last day of the term inclusive — and increments
        the sponsoring dealership's `licensed_salesperson_count`." The
        neighbouring dealership carries no discipline, so the same request at the
        same clock instant succeeds.

        Design: Difficulty/cross_entity_state_dependency/salesperson_license_decision_blocked_by_suspended_sponsor
        """
        ctx = _two_dealers_one_suspended()
        assert ctx["intact_dealer"]["license_status"] == "LICENSED"
        applicant = ctx["pending_intact"]

        licensed = get_success_data(api.decide_salesperson_license(
            applicant["id"], f.salesperson_decision_payload("APPROVED"), LICENSING_ANALYST))

        assert licensed["license_status"] == "LICENSED"
        assert licensed["license_effective_on"] == "2026-09-07"
        assert licensed["license_expires_on"] == "2027-09-06"
        assert licensed["discipline_status"] == "CLEAR"
        assert fx.read_dealer(ctx["intact_dealer"]["id"])["licensed_salesperson_count"] == 1
