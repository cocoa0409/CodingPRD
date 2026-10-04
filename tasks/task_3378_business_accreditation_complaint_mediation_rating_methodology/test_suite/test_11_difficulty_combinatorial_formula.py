"""Difficulty queue — combinatorial formulas: the rating score combining
per-tier volume threshold, unanswered cap and age deduction (PRD §3.6), and
the quarterly dues plan's nested rounding order (PRD §3.3)."""

from datetime import timedelta

from test_helpers import (
    CLOCK_START_ISO,
    TEST_USERS,
    assert_dues_invoice,
    assert_rating_snapshot,
    create_application,
    create_bureau,
    create_business,
    create_consumer,
    create_rating_snapshot_payload,
    decide_application_payload,
    get_business,
    make_business_rep_headers,
    parse_iso,
    set_clock,
    setup_business_with_unanswered_complaints,
    submit_application,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
REVIEWER = TEST_USERS["standards_reviewer_headers"]


def _setup_micro_with_five_unanswered():
    """MICRO business (volume threshold 3, one full year old at the sweep
    instant) carrying five UNANSWERED complaints."""
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    business = create_business(legal_name="Tiny Tools Co",
                               home_state_code="IA", employee_count=4,
                               founded_on="2025-06-15T00:00:00Z")
    setup_business_with_unanswered_complaints(bureau, consumer, business, 5)
    return bureau, consumer, business


def _approve_quarterly_invoice(api):
    """MEDIUM business approved on a QUARTERLY plan in a bureau whose local
    fee is 111 cents; returns the issued invoice."""
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Gateway Bureau", territory_state_codes=["IL"],
                  local_dues_fee_cents=111)
    business = create_business(legal_name="River Medium LLC",
                               home_state_code="IL", employee_count=50,
                               founded_on="2020-01-01T00:00:00Z")
    app = create_application(business, billing_plan="QUARTERLY",
                             license_number="LIC-R-1")
    app = submit_application(app)
    resp = api.decide_application(app["id"], decide_application_payload(),
                                  REVIEWER)
    decided = validate_success(resp, 200)
    resp = api.list_dues_invoices(business["id"],
                                  make_business_rep_headers(business["id"]))
    rows, _meta = validate_paginated(resp)
    for row in rows:
        if row["id"] == decided["dues_invoice_id"]:
            return row
    raise AssertionError("issued invoice missing from listing")


class TestRatingMultifactorInteraction:
    def test_volume_threshold_cap_and_age_combine(self, api):
        """PRD §3.6: "The deduction is 6 points for every complaint above the
        threshold, capped at 30 points; a business at or below its threshold
        loses nothing to volume."
        PRD §3.6: "`unanswered_deduction` charges 12 points for each
        `UNANSWERED` complaint in the window, capped at 36 points."
        PRD §3.6: "the deduction is 2 points for each full year by which the
        business is younger than 3 years, capped at 6 points; a business 3 or
        more full years old loses nothing here."

        Design: Difficulty/combinatorial_formula/rating_multifactor_tier_threshold_cap_and_age_interaction
        """
        _bureau, _consumer, business = _setup_micro_with_five_unanswered()
        resp = api.create_rating_snapshot(
            business["id"], create_rating_snapshot_payload("PUBLISHED"),
            ADMIN)
        snap = validate_success(resp, 201)
        assert_rating_snapshot(snap)
        # 5 outcomes over the MICRO threshold of 3: 6 * (5 - 3) = 12.
        assert snap["volume_deduction"] == 12
        # 12 * 5 = 60 would exceed the cap; the cap binds at 36.
        assert snap["unanswered_deduction"] == 36
        # Founded 2025-06-15, computed at 2026-09-16: one full calendar year.
        assert snap["age_deduction"] == 4
        assert snap["total_deductions"] == 52
        assert snap["score"] == 48
        assert snap["grade"] == "F"

    def test_business_counters_and_provisional_agree_when_nothing_pending(
            self, api):
        """PRD §3.6: "`PROVISIONAL` is the live preview: pending complaints
        count toward the volume input and draw the pending deduction, so
        identical underlying data yields a different provisional score
        whenever any complaint is open."
        PRD §3.4: "`complaints_unanswered_36m` counts those in `UNANSWERED`
        within the same window."

        Design: Difficulty/combinatorial_formula/rating_multifactor_tier_threshold_cap_and_age_interaction
        """
        _bureau, _consumer, business = _setup_micro_with_five_unanswered()
        mirror = get_business(business["id"])
        assert mirror["complaints_unanswered_36m"] == 5
        resp = api.create_rating_snapshot(
            business["id"], create_rating_snapshot_payload("PROVISIONAL"),
            ADMIN)
        prov = validate_success(resp, 201)
        assert_rating_snapshot(prov)
        # Every complaint is closed: the pending set is empty and the two
        # variants converge on the same deductions and score.
        assert prov["pending_deduction"] == 0
        assert prov["unanswered_deduction"] == 36
        assert prov["score"] == 48
        assert prov["grade"] == "F"


class TestQuarterlyRoundingOrder:
    def test_surcharge_rounds_at_total_then_per_installment(self, api):
        """PRD §3.3: "Under `QUARTERLY`, a 4 percent plan surcharge applies
        with a pinned rounding order: first the plan total is computed as the
        subtotal multiplied by 1.04 and rounded half-up to whole cents; then
        the base installment is the plan total divided by 4 and rounded
        half-up to whole cents; the first three installments each carry the
        base installment, and the fourth installment carries the remainder —
        the plan total minus three times the base installment — so every
        rounding residue lands on the final installment."

        Design: Difficulty/combinatorial_formula/dues_quarterly_rounding_remainder_lands_on_last_installment
        """
        inv = _approve_quarterly_invoice(api)
        assert_dues_invoice(inv)
        # subtotal 115000 + 111 = 115111; S = round_half_up(115111 * 1.04)
        assert inv["base_amount_cents"] == 115000
        assert inv["local_fee_cents"] == 111
        assert inv["amount_due_cents"] == 119715
        # P = round_half_up(119715 / 4) = round_half_up(29928.75) = 29929.
        amounts = [i["amount_cents"] for i in inv["installments"]]
        assert amounts[:3] == [29929, 29929, 29929]

    def test_remainder_lands_on_final_installment(self, api):
        """PRD §3.3: "the fourth installment carries the remainder — the plan
        total minus three times the base installment — so every rounding
        residue lands on the final installment."
        PRD §3.3: "`issued_at` is the decision instant, and `due_date` is
        exactly 30 days after `issued_at`."

        Design: Difficulty/combinatorial_formula/dues_quarterly_rounding_remainder_lands_on_last_installment
        """
        inv = _approve_quarterly_invoice(api)
        assert_dues_invoice(inv)
        amounts = [i["amount_cents"] for i in inv["installments"]]
        assert amounts[3] == 29928, "29928 = 119715 - 3 * 29929"
        assert sum(amounts) == 119715 == inv["amount_due_cents"]
        assert inv["status"] == "ISSUED"
        assert parse_iso(inv["due_date"]) == parse_iso(inv["issued_at"]) + \
            timedelta(days=30)
