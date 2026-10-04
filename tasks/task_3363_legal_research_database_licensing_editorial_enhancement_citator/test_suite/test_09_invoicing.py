"""Invoicing: the FLAT_RATE/TRANSACTIONAL dual variants, pinned per-component
rounding, quota and discount boundaries, the cost-recovery waterfall, lazy
OVERDUE materialization, closed windows, and the VOID auto-resume cascade
(PRD §2.4, §3.6)."""
from test_helpers import (
    CLOCK_SEP_10,
    ApiErrorId,
    advance_clock_days_past,
    assert_cost_recovery_allocation_total,
    assert_invoice,
    assign_seat,
    create_account,
    create_plan,
    create_subscription,
    generate_invoice,
    get_invoice,
    get_subscription,
    invoice_window_payload,
    make_researcher_headers,
    record_usage,
    set_clock,
    setup_issued_invoice,
    setup_subscribed_user,
    usage_event_payload,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

_LICENSING = TEST_USERS["licensing_manager_headers"]
_BILLING = TEST_USERS["billing_admin_headers"]


def test_flat_rate_invoice_worked_example(api):
    """PRD §3.6: "A concrete walkthrough: a plan with a 5000-cent monthly fee, two
    included searches, one included view, overage fees of 250 and 105 cents, and a
    discount threshold the combined overage meets sees five searches and four views
    produce three overage searches and three overage views, an overage fee of 906
    cents, and a `total_cents` of 5906."

    Design: Difficulty/dual_variant_calc/flat_vs_transactional_invoice_divergence
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(plan_overrides={"name": "Flat Small Lit"},
                                seats_total=2, searches=5, doc_views=4,
                                user_email="f1@flat.com")
    invoice = generate_invoice(ctx["subscription"]["id"])
    assert_invoice(invoice)
    assert invoice["billing_model"] == "FLAT_RATE"
    assert invoice["base_fee_cents"] == 5000
    assert invoice["search_count"] == 5
    assert invoice["doc_view_count"] == 4
    assert invoice["overage_search_units"] == 3
    assert invoice["overage_view_units"] == 3
    assert invoice["overage_fee_cents"] == 906
    assert invoice["total_cents"] == 5906


def test_transactional_invoice_same_usage_diverges(api):
    """PRD §3.6: "On a `TRANSACTIONAL` plan there is no base fee, no quota, and no
    discount: `base_fee_cents`, `overage_search_units`, `overage_view_units`, and
    `overage_fee_cents` are all 0, and `total_cents` is the `search_count` times
    `per_search_fee_cents` plus the `doc_view_count` times `per_doc_view_fee_cents`.
    The same five searches and four views billed transactionally at, say, 300 cents
    per search and 120 cents per view total 1980 cents — identical usage, a
    different regime, a different bill."

    Design: Difficulty/dual_variant_calc/flat_vs_transactional_invoice_divergence
    """
    set_clock(CLOCK_SEP_10)
    flat_ctx = setup_subscribed_user(plan_overrides={"name": "Flat Small Lit"},
                                     seats_total=2, searches=5, doc_views=4,
                                     user_email="f1@flat.com")
    txn_ctx = setup_subscribed_user(flat=False,
                                    plan_overrides={"name": "Gov Transactional"},
                                    account_overrides={"org_name": "Txn Agency",
                                                       "account_type": "GOVERNMENT"},
                                    seats_total=2, searches=5, doc_views=4,
                                    user_email="t1@txn.gov")
    flat_invoice = generate_invoice(flat_ctx["subscription"]["id"])
    txn_invoice = generate_invoice(txn_ctx["subscription"]["id"])
    assert txn_invoice["billing_model"] == "TRANSACTIONAL"
    assert txn_invoice["base_fee_cents"] == 0
    assert txn_invoice["overage_search_units"] == 0
    assert txn_invoice["overage_view_units"] == 0
    assert txn_invoice["overage_fee_cents"] == 0
    assert txn_invoice["total_cents"] == 1980
    assert flat_invoice["total_cents"] != txn_invoice["total_cents"], (
        "identical usage must price differently across the two billing models"
    )


def test_overage_components_rounded_before_summation(api):
    """PRD §3.6: "Summing first and rounding once is a different, forbidden
    calculation: three overage searches at 250 cents and three overage views at 105
    cents under a 15 percent discount yield per-component results of 638 and 268
    cents, an `overage_fee_cents` of 906, whereas rounding the combined 1065 times
    0.85 once would yield 905."

    Design: Difficulty/combinatorial_formula/invoice_per_component_rounding_then_sum
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(plan_overrides={"name": "Round Plan"},
                                seats_total=1, searches=5, doc_views=4,
                                user_email="r1@round.com")
    invoice = generate_invoice(ctx["subscription"]["id"])
    assert invoice["overage_fee_cents"] == 906, (
        f"per-component rounding 638 + 268 = 906, not sum-then-round 905; "
        f"got {invoice['overage_fee_cents']}"
    )


def test_overage_rounding_total_and_units(api):
    """PRD §3.6: "A concrete walkthrough: a plan with a 5000-cent monthly fee, two
    included searches, one included view, overage fees of 250 and 105 cents, and a
    discount threshold the combined overage meets sees five searches and four views
    produce three overage searches and three overage views, an overage fee of 906
    cents, and a `total_cents` of 5906."

    Design: Difficulty/combinatorial_formula/invoice_per_component_rounding_then_sum
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(plan_overrides={"name": "Round Plan"},
                                seats_total=1, searches=5, doc_views=4,
                                user_email="r1@round.com")
    invoice = generate_invoice(ctx["subscription"]["id"])
    assert invoice["overage_search_units"] == 3
    assert invoice["overage_view_units"] == 3
    assert invoice["total_cents"] == 5906


def test_usage_at_exactly_included_quota_not_over(api):
    """PRD §3.6: "Overage units are the shortfall past the included quotas, never
    below zero: `overage_search_units` is however many searches exceed
    `included_searches`, and `overage_view_units` however many views exceed
    `included_doc_views`."
    PRD §3.6: "The invoice `total_cents` is `base_fee_cents` plus
    `overage_fee_cents`."

    Design: Difficulty/boundary_precision_check/overage_units_at_exactly_included_quota
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(plan_overrides={"name": "Boundary Plan"},
                                searches=2, doc_views=1, user_email="x@ba.com")
    invoice = generate_invoice(ctx["subscription"]["id"])
    assert invoice["overage_search_units"] == 0, "exactly-at-quota is NOT over"
    assert invoice["overage_view_units"] == 0
    assert invoice["overage_fee_cents"] == 0
    assert invoice["total_cents"] == 5000


def test_one_search_over_quota_adds_undiscounted_unit(api):
    """PRD §3.6: "Overage units are the shortfall past the included quotas, never
    below zero: `overage_search_units` is however many searches exceed
    `included_searches`, and `overage_view_units` however many views exceed
    `included_doc_views`."
    PRD §3.6: "Below the threshold, no discount applies and each component is
    simply units times its overage fee."

    Design: Difficulty/boundary_precision_check/overage_units_at_exactly_included_quota
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(plan_overrides={"name": "Boundary Plan"},
                                searches=3, doc_views=1, user_email="y@bb.com",
                                account_overrides={"org_name": "Boundary B",
                                                   "account_type": "CORPORATE"})
    invoice = generate_invoice(ctx["subscription"]["id"])
    assert invoice["overage_search_units"] == 1
    assert invoice["overage_view_units"] == 0
    assert invoice["overage_fee_cents"] == 250, (
        "one unit over, combined 1 < discount threshold 4: no discount"
    )
    assert invoice["total_cents"] == 5250


def test_invoice_discount_threshold_boundary_nonmonotonic(api):
    """PRD §3.6: "When the two overage quantities together reach at least the plan's
    `discount_threshold_overage_units` — exactly at the threshold does qualify —
    the volume discount applies, and the rounding order is pinned: each component
    is rounded half-up to whole cents on its own, the search component being the
    overage search units times `overage_search_fee_cents` times
    one-minus-`volume_discount_pct`, the view component the overage view units
    times `overage_doc_view_fee_cents` times the same factor, and
    `overage_fee_cents` is the sum of the two rounded components."

    Design: Corner/calculations/invoice_discount_threshold_boundary_nonmonotonic
    """
    set_clock(CLOCK_SEP_10)
    ctx_x = setup_subscribed_user(plan_overrides={"name": "Thr Plan"},
                                  searches=4, doc_views=3, user_email="x@thr.com")
    ctx_y = setup_subscribed_user(plan_overrides={"name": "Thr Plan"},
                                  searches=4, doc_views=2, user_email="y@thr.com",
                                  account_overrides={"org_name": "Thr Y",
                                                     "account_type": "CORPORATE"})
    inv_x = generate_invoice(ctx_x["subscription"]["id"])
    inv_y = generate_invoice(ctx_y["subscription"]["id"])
    # X: overage 2s + 2v = 4 units >= 4 -> discount ON -> 425 + 179 = 604.
    assert inv_x["overage_fee_cents"] == 604
    assert inv_x["total_cents"] == 5604
    # Y: overage 2s + 1v = 3 units < 4 -> discount OFF -> 500 + 105 = 605.
    assert inv_y["overage_fee_cents"] == 605
    assert inv_y["total_cents"] == 5605
    assert inv_x["total_cents"] < inv_y["total_cents"], (
        "crossing the discount threshold makes the larger bill one cent cheaper"
    )


def test_invoice_undiscounted_small_overage_literal(api):
    """PRD §3.6: "Below the threshold, no discount applies and each component is
    simply units times its overage fee. The invoice `total_cents` is
    `base_fee_cents` plus `overage_fee_cents`."

    Design: Corner/calculations/invoice_undiscounted_small_overage_literal
    """
    set_clock(CLOCK_SEP_10)
    ctx = setup_subscribed_user(plan_overrides={"name": "Small Plan"},
                                searches=3, doc_views=2, user_email="s@small.com")
    invoice = generate_invoice(ctx["subscription"]["id"])
    assert invoice["overage_search_units"] == 1
    assert invoice["overage_view_units"] == 1
    assert invoice["overage_fee_cents"] == 355, "250 + 105 with the discount off"
    assert invoice["total_cents"] == 5355


def test_cost_recovery_waterfall_remainder_literal(api):
    """PRD §3.6: "With a 5906-cent invoice across matters M-A (four events), M-B
    (three), and M-C (two), the floored shares are 2624, 1968, and 1312 cents
    (summing to 5904), the remainder is 2 cents, and the final allocation reads
    M-A 2625, M-B 1969, M-C 1312."

    Design: Corner/calculations/cost_recovery_waterfall_remainder_literal
    """
    set_clock(CLOCK_SEP_10)
    plan = create_plan(name="Rec Plan", cost_recovery_allowed=True)
    account = create_account(org_name="Rec Firm", cost_recovery_enabled=True)
    subscription = create_subscription(account["id"], plan["id"])
    user = assign_seat(subscription["id"], account["id"], email="r@rec.com", full_name="R")
    uid = user["id"]
    record_usage(uid, "SEARCH", 3, matter_code="M-A")
    record_usage(uid, "SEARCH", 1, matter_code="M-B")
    record_usage(uid, "SEARCH", 1, matter_code="M-C")
    record_usage(uid, "DOC_VIEW", 1, matter_code="M-A")
    record_usage(uid, "DOC_VIEW", 2, matter_code="M-B")
    record_usage(uid, "DOC_VIEW", 1, matter_code="M-C")

    invoice = generate_invoice(subscription["id"])
    assert invoice["total_cents"] == 5906
    assert_cost_recovery_allocation_total(invoice)
    rows = {row["matter_code"]: row for row in invoice["cost_recovery_allocation"]}
    assert set(rows) == {"M-A", "M-B", "M-C"}
    assert rows["M-A"]["event_count"] == 4 and rows["M-A"]["amount_cents"] == 2625
    assert rows["M-B"]["event_count"] == 3 and rows["M-B"]["amount_cents"] == 1969
    assert rows["M-C"]["event_count"] == 2 and rows["M-C"]["amount_cents"] == 1312


def test_invoice_overdue_materializes_on_clock_advance(api):
    """PRD §2.4: "Before the system handles any request that reads or writes an
    invoice, or that reads or writes the subscription behind one, it first
    re-examines every invoice still in `ISSUED` status whose `due_at` is earlier
    than the current logical-clock reading, flips each such invoice to `OVERDUE`,
    and applies the subscription suspension cascade described in §3.6."
    PRD §3.6: "When the logical clock passes an unpaid invoice's `due_at`, the next
    request that touches invoices or subscriptions flips it to `OVERDUE` and
    suspends the owning subscription — if still `ACTIVE` — with `suspension_reason`
    `INVOICE_OVERDUE`."

    Design: Corner/state_machines/invoice_overdue_materializes_on_clock_advance
    """
    ctx = setup_issued_invoice(plan_overrides={"name": "Ovd Plan", "included_searches": 5},
                               searches=1, clock_iso=CLOCK_SEP_10, user_email="o@ovd.com")
    invoice = ctx["invoice"]
    assert invoice["status"] == "ISSUED"
    due_at = invoice["due_at"]
    assert due_at, "an ISSUED invoice must carry due_at (PRD §3.6)"

    # At clock == due_at the invoice is NOT yet overdue: the rule requires
    # due_at strictly earlier than the clock reading.
    advance_clock_days_past(due_at, 0)
    assert get_invoice(invoice["id"])["status"] == "ISSUED"

    advance_clock_days_past(due_at, 1)
    assert get_invoice(invoice["id"])["status"] == "OVERDUE"
    subscription = get_subscription(ctx["subscription"]["id"])
    assert subscription["status"] == "SUSPENDED"
    assert subscription["suspension_reason"] == "INVOICE_OVERDUE"


def test_invoice_period_closed_rejects_late_event_and_regen(api):
    """PRD §3.5: "The event's `occurred_at` must not fall inside the billing window
    of any invoice of the same subscription that is `ISSUED`, `OVERDUE`, or `PAID`;
    such a period is closed and the event is rejected with
    `ERR_INVOICE_PERIOD_CLOSED` (HTTP 409)"
    PRD §3.6: "Generation is refused with `ERR_INVOICE_PERIOD_CLOSED` (HTTP 409)
    when the window overlaps any existing non-`VOID` invoice of the same
    subscription — and for this purpose even a `DRAFT` invoice blocks overlap, in
    contrast to the usage-event rule of §3.5 where only issued-or-later windows
    close."

    Design: Corner/validations/invoice_period_closed_rejects_late_event_and_regen
    """
    # The clock stays at the issuance instant: the new event's occurred_at falls
    # inside the just-ISSUED window no matter what NET_TERMS_DAYS (PRD §3.6,
    # symbolic) the server uses, so the period-closed gate — not the
    # not-active gate — is what can fire.
    ctx = setup_issued_invoice(
        plan_overrides={"name": "Closed Plan", "included_searches": 5},
        searches=1, clock_iso=CLOCK_SEP_10, user_email="c@closed.com",
        period_start="2026-09-01", period_end="2026-12-01",
    )
    late_event = api.create_usage_event(
        usage_event_payload(event_type="SEARCH", practice_area_tag="LITIGATION"),
        make_researcher_headers(ctx["user"]["id"]),
    )
    validate_error(late_event, ApiErrorId.ERR_INVOICE_PERIOD_CLOSED, 409)

    regen = api.generate_invoice(
        invoice_window_payload(ctx["subscription"]["id"],
                               period_start="2026-09-15", period_end="2026-10-15"),
        _BILLING,
    )
    validate_error(regen, ApiErrorId.ERR_INVOICE_PERIOD_CLOSED, 409)


def test_overdue_invoice_materializes_and_suspends(api):
    """PRD §2.4: "Before the system handles any request that reads or writes an
    invoice, or that reads or writes the subscription behind one, it first
    re-examines every invoice still in `ISSUED` status whose `due_at` is earlier
    than the current logical-clock reading, flips each such invoice to `OVERDUE`,
    and applies the subscription suspension cascade described in §3.6."

    Design: Difficulty/transitive_cascade/invoice_void_depth2_auto_resume
    """
    ctx = setup_issued_invoice(plan_overrides={"name": "Void Plan"}, searches=1,
                               clock_iso=CLOCK_SEP_10, user_email="v1@void.com")
    invoice = ctx["invoice"]
    advance_clock_days_past(invoice["due_at"], 1)
    assert get_invoice(invoice["id"])["status"] == "OVERDUE"
    subscription = get_subscription(ctx["subscription"]["id"])
    assert subscription["status"] == "SUSPENDED"
    assert subscription["suspension_reason"] == "INVOICE_OVERDUE"


def test_void_overdue_invoice_auto_resumes_subscription(api):
    """PRD §3.6: "Settlement in either direction (`PAID` or `VOID`) triggers the
    auto-resume evaluation: the subscription returns to `ACTIVE` when its
    suspension reason is `INVOICE_OVERDUE` and no `ISSUED` or `OVERDUE` invoice
    remains on it, clearing `suspension_reason` to null."
    PRD §3.6: "Voiding moves an invoice from `DRAFT`, `ISSUED`, or `OVERDUE` to
    `VOID`; a voided invoice's `total_cents` stops counting toward the
    subscription's outstanding balance and toward any royalty revenue base"

    Design: Difficulty/transitive_cascade/invoice_void_depth2_auto_resume
    """
    ctx = setup_issued_invoice(plan_overrides={"name": "Void Plan"}, searches=1,
                               clock_iso=CLOCK_SEP_10, user_email="v1@void.com")
    invoice = ctx["invoice"]
    advance_clock_days_past(invoice["due_at"], 1)
    assert get_invoice(invoice["id"])["status"] == "OVERDUE"
    assert get_subscription(ctx["subscription"]["id"])["status"] == "SUSPENDED"

    resp = api.transition_invoice(invoice["id"], {"target_status": "VOID"}, _BILLING)
    voided = validate_success(resp, 200)
    assert voided["status"] == "VOID"

    subscription = get_subscription(ctx["subscription"]["id"])
    assert subscription["status"] == "ACTIVE", (
        "voiding the only OVERDUE invoice resumes the subscription with no direct "
        "subscription call"
    )
    assert subscription["suspension_reason"] is None
