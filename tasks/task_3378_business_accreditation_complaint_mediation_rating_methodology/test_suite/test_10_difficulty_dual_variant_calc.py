"""Difficulty queue — dual-variant calculations: identical inputs priced or
scored through two pinned variants (rating PROVISIONAL vs PUBLISHED in PRD
§3.6; dues ANNUAL_PREPAID vs QUARTERLY in PRD §3.3)."""

from test_helpers import (
    CLOCK_START_ISO,
    TEST_USERS,
    WORKED_ANNUAL_TOTAL_CENTS,
    WORKED_QUARTERLY_INSTALLMENTS_CENTS,
    WORKED_QUARTERLY_TOTAL_CENTS,
    assert_dues_invoice,
    assert_rating_snapshot,
    business_respond,
    consumer_reject,
    create_application,
    create_bureau,
    create_business,
    create_consumer,
    create_rating_snapshot_payload,
    decide_application_payload,
    file_and_forward_complaint,
    get_business,
    make_business_rep_headers,
    run_daily_close,
    set_clock,
    submit_application,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
REVIEWER = TEST_USERS["standards_reviewer_headers"]


def _setup_rating_mix():
    """LARGE business with one UNANSWERED (12), one UNRESOLVED (8) and one
    still-open RESPONSE_RECEIVED complaint at 2026-09-16T00:00:00Z."""
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    business = create_business(legal_name="BigBox Services Inc",
                               home_state_code="IA", employee_count=250,
                               founded_on="2018-01-01T00:00:00Z")
    # c1: forwarded, then lapses past the 14-day response window at the sweep.
    c1 = file_and_forward_complaint(consumer, business, category="SERVICE",
                                    description="c1 never answered")
    set_clock("2026-09-16T00:00:00Z")
    run_daily_close(bureau["id"])
    # c2: answered, then rejected by the consumer.
    c2 = file_and_forward_complaint(consumer, business, category="BILLING",
                                    description="c2 rejected answer")
    c2 = business_respond(c2, business, body="we offered a refund")
    consumer_reject(c2, consumer, body="not good enough")
    # c3: answered, awaiting the consumer verdict (still open / pending).
    c3 = file_and_forward_complaint(consumer, business, category="DELIVERY",
                                    description="c3 open")
    business_respond(c3, business, body="package resent")
    return bureau, consumer, business


def _approve_and_fetch_invoice(api, business, billing_plan, license_number):
    """Drive DRAFT -> SUBMITTED -> APPROVED_PENDING_DUES and read the issued
    invoice back through the business's invoice listing."""
    app = create_application(business, billing_plan=billing_plan,
                             license_number=license_number)
    app = submit_application(app)
    resp = api.decide_application(app["id"], decide_application_payload(),
                                  REVIEWER)
    decided = validate_success(resp, 200)
    invoice_id = decided["dues_invoice_id"]
    assert invoice_id, "approval must record the issued invoice id"
    resp = api.list_dues_invoices(business["id"],
                                  make_business_rep_headers(business["id"]))
    rows, _meta = validate_paginated(resp)
    for row in rows:
        if row["id"] == invoice_id:
            return row
    raise AssertionError(f"invoice {invoice_id} missing from listing")


class TestRatingVariantDivergence:
    def test_published_snapshot_ignores_pending_complaint(self, api):
        """PRD §3.6: "`PUBLISHED` is the public record: pending complaints are
        invisible to it, contributing neither to the volume input nor to any
        pending deduction, so the score reflects closed outcomes only."
        PRD §3.6: "`pending_deduction` exists only on `PROVISIONAL` snapshots:
        4 points for each pending-set complaint, capped at 12 points. On
        `PUBLISHED` snapshots it is always 0."

        Design: Difficulty/dual_variant_calc/rating_provisional_counts_pending_published_ignores_it
        """
        _bureau, _consumer, business = _setup_rating_mix()
        resp = api.create_rating_snapshot(
            business["id"], create_rating_snapshot_payload("PUBLISHED"), ADMIN)
        pub = validate_success(resp, 201)
        assert_rating_snapshot(pub)
        # Outcome set: {UNANSWERED, UNRESOLVED} = 2 <= LARGE threshold 24.
        assert pub["volume_deduction"] == 0
        assert pub["unanswered_deduction"] == 12
        assert pub["unresolved_deduction"] == 8
        assert pub["pending_deduction"] == 0, \
            "PUBLISHED never carries a pending deduction"
        assert pub["score"] == 80
        assert pub["grade"] == "B"
        mirror = get_business(business["id"])
        assert mirror["current_published_score"] == 80
        assert mirror["current_published_grade"] == "B"

    def test_provisional_snapshot_counts_pending_complaint(self, api):
        """PRD §3.6: "`PROVISIONAL` is the live preview: pending complaints
        count toward the volume input and draw the pending deduction, so
        identical underlying data yields a different provisional score
        whenever any complaint is open."

        Design: Difficulty/dual_variant_calc/rating_provisional_counts_pending_published_ignores_it
        """
        _bureau, _consumer, business = _setup_rating_mix()
        pub = validate_success(api.create_rating_snapshot(
            business["id"], create_rating_snapshot_payload("PUBLISHED"),
            ADMIN), 201)
        resp = api.create_rating_snapshot(
            business["id"], create_rating_snapshot_payload("PROVISIONAL"),
            ADMIN)
        prov = validate_success(resp, 201)
        assert_rating_snapshot(prov)
        # One open RESPONSE_RECEIVED complaint: pending 4; volume input
        # 2 outcomes + 1 pending = 3 <= 24, still no volume deduction.
        assert prov["pending_deduction"] == 4
        assert prov["volume_deduction"] == 0
        assert prov["unanswered_deduction"] == 12
        assert prov["unresolved_deduction"] == 8
        assert prov["score"] == 76
        assert prov["grade"] == "B_MINUS"
        mirror = get_business(business["id"])
        assert mirror["current_provisional_score"] == 76
        assert mirror["current_provisional_grade"] == "B_MINUS"
        assert pub["score"] != prov["score"], \
            "the two variants must diverge on identical underlying data"


class TestDuesPlanDivergence:
    def _setup_plans(self, api):
        set_clock(CLOCK_START_ISO)
        create_bureau(name="Prairie Bureau",
                      territory_state_codes=["KS", "MO"],
                      local_dues_fee_cents=333)
        biz_a = create_business(legal_name="Alpha Medium LLC",
                                home_state_code="KS", employee_count=50,
                                founded_on="2020-01-01T00:00:00Z")
        biz_b = create_business(legal_name="Beta Medium LLC",
                                home_state_code="KS", employee_count=50,
                                founded_on="2020-01-01T00:00:00Z")
        inv_a = _approve_and_fetch_invoice(api, biz_a, "ANNUAL_PREPAID",
                                           "LIC-A-1")
        inv_b = _approve_and_fetch_invoice(api, biz_b, "QUARTERLY", "LIC-B-1")
        return biz_a, biz_b, inv_a, inv_b

    def test_annual_prepaid_single_discounted_installment(self, api):
        """PRD §3.3: "A worked example pins the arithmetic: with a `MEDIUM`
        base of 115000 cents and a bureau local fee of 333 cents, the subtotal
        is 115333 cents; `ANNUAL_PREPAID` yields an amount due of 109566 cents
        in a single installment, while `QUARTERLY` yields a plan total of
        119946 cents with installments of 29987, 29987, 29987, and 29985
        cents."

        Design: Difficulty/dual_variant_calc/dues_prepaid_vs_quarterly_diverge_on_same_tier_and_fee
        """
        _biz_a, _biz_b, inv_a, _inv_b = self._setup_plans(api)
        assert_dues_invoice(inv_a)
        assert inv_a["billing_plan"] == "ANNUAL_PREPAID"
        assert inv_a["base_amount_cents"] == 115000
        assert inv_a["local_fee_cents"] == 333
        assert inv_a["amount_due_cents"] == WORKED_ANNUAL_TOTAL_CENTS == 109566
        assert inv_a["installments"] == [
            {"installment": 1, "amount_cents": 109566}]

    def test_quarterly_surcharge_installments_diverge(self, api):
        """PRD §3.3: "A worked example pins the arithmetic: with a `MEDIUM`
        base of 115000 cents and a bureau local fee of 333 cents, the subtotal
        is 115333 cents; `ANNUAL_PREPAID` yields an amount due of 109566 cents
        in a single installment, while `QUARTERLY` yields a plan total of
        119946 cents with installments of 29987, 29987, 29987, and 29985
        cents."

        Design: Difficulty/dual_variant_calc/dues_prepaid_vs_quarterly_diverge_on_same_tier_and_fee
        """
        _biz_a, _biz_b, inv_a, inv_b = self._setup_plans(api)
        assert_dues_invoice(inv_b)
        assert inv_b["billing_plan"] == "QUARTERLY"
        assert inv_b["amount_due_cents"] == WORKED_QUARTERLY_TOTAL_CENTS == 119946
        assert [i["installment"] for i in inv_b["installments"]] == [1, 2, 3, 4]
        assert [i["amount_cents"] for i in inv_b["installments"]] == \
            WORKED_QUARTERLY_INSTALLMENTS_CENTS
        assert inv_a["amount_due_cents"] != inv_b["amount_due_cents"], \
            "identical tier and fee must price differently per billing plan"
