"""Difficulty probe — combinatorial_formula: the tiered reschedule fee with
its late branch, per-prior scaling and hard cap; and the pinned per-line
round-half-up scholarship rounding order."""
from test_helpers import (
    PROGRAM_FEE_CENTS,
    book_appointment,
    compute_reschedule_fee_cents,
    create_candidate,
    create_enrollment_pending,
    expected_charge_cents,
    get_enrollment_of_candidate,
    pay_enrollment,
    reschedule_appointment_payload,
    set_logical_clock,
    setup_bookable_context,
    validate_success,
)

EARLY_FEE = 94000


def _reschedule_chain_start():
    """ENROLLED candidate booked EARLY for exam 2027-03-10 (fee paid); clock
    then sits at 2027-03-01 — nine days before the exam, inside the late
    surcharge band and before the window's reschedule deadline."""
    context = setup_bookable_context()
    appointment = book_appointment(context, exam_date="2027-03-10")
    set_logical_clock("2027-03-01T00:00:00Z")
    return context, appointment


def _reschedule(api, appointment_id, version, exam_date, candidate_headers):
    resp = api.reschedule_appointment(
        appointment_id,
        reschedule_appointment_payload(version, exam_date=exam_date),
        candidate_headers,
    )
    return validate_success(resp, 200)


class TestRescheduleFeeTiers:
    def test_reschedule_fee_first_two_tiers(self, api):
        """PRD §3.4: "The fee starts at a base of 25,000 cents. If the notice
        period is shorter than 14 days, a late surcharge of 25,000 cents is
        added. Then 10,000 cents is added for each prior reschedule on the
        appointment, counting at most two priors — the `reschedule_count` as it
        stands before this reschedule. The total is capped at 60,000 cents. So a
        first reschedule nine days before the exam costs the base plus the
        surcharge, 50,000 cents; with one prior reschedule the per-prior
        component brings the quote to exactly 60,000 cents, where the cap just
        binds"

        Design: Difficulty/combinatorial_formula/reschedule_fee_tiered_branch_min_cap
        """
        assert compute_reschedule_fee_cents(9, 0) == 50000
        assert compute_reschedule_fee_cents(11, 1) == 60000
        context, appointment = _reschedule_chain_start()
        first = _reschedule(
            api,
            appointment["id"],
            appointment["version"],
            "2027-03-12",
            context["candidate_headers"],
        )
        assert first["reschedule_fees_total_cents"] == 50000
        pay_enrollment(context["enrollment"]["id"], 50000)
        second = _reschedule(
            api,
            appointment["id"],
            first["version"],
            "2027-03-13",
            context["candidate_headers"],
        )
        assert second["reschedule_fees_total_cents"] == 110000

    def test_reschedule_fee_third_hits_cap(self, api):
        """PRD §3.4: "with two prior reschedules the uncapped 70,000 cents is
        trimmed to the same 60,000-cent cap; and a first reschedule twenty days
        out costs only the 25,000-cent base. The fee is never
        scholarship-discounted."
        PRD §3.4: "The fee starts at a base of 25,000 cents."

        Design: Difficulty/combinatorial_formula/reschedule_fee_tiered_branch_min_cap
        """
        assert compute_reschedule_fee_cents(12, 2) == 60000
        context, appointment = _reschedule_chain_start()
        first = _reschedule(
            api,
            appointment["id"],
            appointment["version"],
            "2027-03-12",
            context["candidate_headers"],
        )
        pay_enrollment(context["enrollment"]["id"], 50000)
        second = _reschedule(
            api,
            appointment["id"],
            first["version"],
            "2027-03-13",
            context["candidate_headers"],
        )
        pay_enrollment(context["enrollment"]["id"], 60000)
        third = _reschedule(
            api,
            appointment["id"],
            second["version"],
            "2027-03-14",
            context["candidate_headers"],
        )
        assert third["reschedule_fees_total_cents"] == 170000
        assert third["reschedule_count"] == 3
        assert third["exam_date"] == "2027-03-14"
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["lifetime_charges_cents"] == (
            PROGRAM_FEE_CENTS + EARLY_FEE + 50000 + 60000 + 60000
        )


class TestScholarshipRoundingOrder:
    def test_program_fee_line_rounded_half_up(self, api):
        """PRD §2.8: "Rounding is **per line, then sum**: each individual charge
        line is its list price multiplied by one minus the enrollment's
        `scholarship_pct`, rounded half-up to whole cents, and only then added
        into `lifetime_charges_cents`."
        PRD §3.1: "Creation posts the program's enrollment charge: a list price
        of 35,003 cents, discounted per line by the enrollment's
        `scholarship_pct` with half-up rounding before the line enters
        `lifetime_charges_cents` (§2.8)."

        Design: Difficulty/combinatorial_formula/scholarship_per_line_rounding_beats_sum_rounding
        """
        assert expected_charge_cents(PROGRAM_FEE_CENTS, 0.10) == 31503
        set_logical_clock("2027-01-05T00:00:00Z")
        candidate = create_candidate()
        enrollment = create_enrollment_pending(candidate["id"], scholarship_pct=0.10)
        assert enrollment["scholarship_pct"] == 0.10
        assert enrollment["lifetime_charges_cents"] == 31503
        assert enrollment["outstanding_balance_cents"] == 31503

    def test_exam_fee_line_rounded_independently(self, api):
        """PRD §2.8: "Rounding is **per line, then sum**: each individual charge
        line is its list price multiplied by one minus the enrollment's
        `scholarship_pct`, rounded half-up to whole cents, and only then added
        into `lifetime_charges_cents`. Summing list prices first and rounding
        the total once is a rejected interpretation — the two orders can differ
        by a cent or more, and the per-line order is the contract."
        PRD §3.3: "The `exam_fee_cents` line is the level's fee for that tier,
        scholarship-discounted per line with half-up rounding per §2.8"

        Design: Difficulty/combinatorial_formula/scholarship_per_line_rounding_beats_sum_rounding
        """
        assert expected_charge_cents(99995, 0.10) == 89996
        context = setup_bookable_context(
            enrollment_overrides={"scholarship_pct": 0.10},
            level_overrides={"early_fee_cents": 99995},
        )
        assert context["enrollment"]["status"] == "ENROLLED"
        appointment = book_appointment(context, exam_date="2027-03-03", pay_fee=False)
        assert appointment["fee_tier"] == "EARLY"
        assert appointment["exam_fee_cents"] == 89996
        enrollment = get_enrollment_of_candidate(context["candidate"]["id"])
        assert enrollment["lifetime_charges_cents"] == 121499
        assert enrollment["outstanding_balance_cents"] == 89996
