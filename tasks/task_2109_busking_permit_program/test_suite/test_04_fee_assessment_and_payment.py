"""The permit fee assessment, the approval cascade and settling the invoice."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_fee_invoice, assert_permit, assert_permit_number_format,
    assert_same_instant, assert_money_ledger_invariant,
    payment_payload, decision_payload,
    set_clock, create_zone, create_performer, create_application,
    submit_application, review_application, decide_application,
    setup_permit_pending_fee, setup_audition_passed,
    find_permit_for_application, first_permit_invoice, list_permit_invoices,
    read_application, read_permit, pay_invoice,
    make_officer_headers, make_performer_headers,
    OFFICER_ALPHA, OFFICER_BETA,
    CLOCK_START_UTC_ISO,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc /
#          fee_variant_full_season_vs_prorated_on_identical_application_inputs
# ---------------------------------------------------------------------------

def _street_theatre_invoice(email, legal_name, stage_name):
    zone = create_zone()
    ctx = setup_permit_pending_fee(
        zone["id"], act_type="STREET_THEATRE", amplification_requested=False,
        performer_overrides={"legal_name": legal_name, "stage_name": stage_name,
                             "email": email})
    return ctx


def test_initial_invoice_issued_before_the_cutoff_month_is_billed_full_season(api):
    """PRD §3.4: "Step six applies one of two variants to that season total, and
    records which one ran in `fee_variant`. A `RENEWAL` invoice is always
    `FULL_SEASON`. An `INITIAL` invoice is `FULL_SEASON` when the UTC calendar
    month of its `issued_at` is June or earlier, and `PRORATED` when that month
    is July or later. Under `FULL_SEASON` the invoice records
    `coverage_start_month` 1 and `months_covered` 12, and `amount_due_cents` is
    the season total unchanged — the permit is billed for the whole season no
    matter how much of it remains."
    PRD §3.4: "Third, the invoice's creation **writes back** onto the
    application: `assessed_fee_cents` becomes that invoice's
    `amount_due_cents`."

    Design: Difficulty/dual_variant_calc/fee_variant_full_season_vs_prorated_on_identical_application_inputs
    """
    set_clock("2026-03-15T09:00:00Z")
    ctx = _street_theatre_invoice("mira@example.org", "Mira Solt", "Mira")
    invoice = ctx["invoice"]
    assert_fee_invoice(invoice)
    assert invoice["gross_fee_cents"] == 15000
    assert invoice["fee_variant"] == "FULL_SEASON"
    assert invoice["months_covered"] == 12
    assert invoice["coverage_start_month"] == 1
    assert invoice["amount_due_cents"] == 16200, (
        "15000 gross, tier 1 discount 0, admin 1200 gives a season total of "
        f"16200 billed in full, got {invoice['amount_due_cents']}")
    assert read_application(ctx["application"]["id"])["assessed_fee_cents"] == 16200


def test_identical_application_issued_after_the_cutoff_month_is_prorated(api):
    """PRD §3.4: "Under `PRORATED` the invoice records `coverage_start_month` as
    the UTC calendar month of `issued_at` and `months_covered` as 13 minus that
    month, and `amount_due_cents` is the season total multiplied by
    `months_covered`, divided by 12, and rounded half up to whole cents."
    PRD §3.4: "Third, the invoice's creation **writes back** onto the
    application: `assessed_fee_cents` becomes that invoice's
    `amount_due_cents`."

    Design: Difficulty/dual_variant_calc/fee_variant_full_season_vs_prorated_on_identical_application_inputs
    """
    set_clock("2026-08-01T00:00:00Z")
    ctx = _street_theatre_invoice("nell@example.org", "Nell Rourke", "Nell")
    invoice = ctx["invoice"]
    assert invoice["gross_fee_cents"] == 15000, \
        "the act inputs are byte-identical to the March application"
    assert invoice["fee_variant"] == "PRORATED"
    assert invoice["coverage_start_month"] == 8
    assert invoice["months_covered"] == 5, "13 minus the month-8 issue"
    assert invoice["amount_due_cents"] == 6750, (
        "16200 * 5 / 12 rounds half up to 6750, got "
        f"{invoice['amount_due_cents']}")
    assert read_application(ctx["application"]["id"])["assessed_fee_cents"] == 6750


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / fee_tier_and_admin_rate_keyed_on_pre_discount_gross
# ---------------------------------------------------------------------------

def test_tier_three_discount_and_admin_fee_are_both_keyed_on_the_gross(api):
    """PRD §3.4: "Step three computes `discount_cents` as the gross multiplied by
    the tier's discount rate — nothing at all in tier 1, 10 percent in tier 2, 15
    percent in tier 3 — rounded half up to whole cents. Step four computes
    `admin_fee_cents` as the same pre-discount gross multiplied by the tier's
    administration rate — 8 percent in tier 1, 6 percent in tier 2, 5 percent in
    tier 3 — again rounded half up to whole cents. Both the tier selection and
    the administration charge are keyed on the gross figure, never on the
    discounted one; re-tiering on the net total would produce a different and
    incorrect charge. Step five produces the season total: the gross, minus the
    discount, plus the administration fee."
    PRD §3.4: "Step one produces `gross_fee_cents`: the base fee for the act
    classification, plus a flat amplification surcharge of $65.00 when the
    amplification flag is true and nothing when it is false."

    Design: Difficulty/combinatorial_formula/fee_tier_and_admin_rate_keyed_on_pre_discount_gross
    """
    set_clock("2026-03-15T09:00:00Z")
    zone = create_zone()
    ctx = setup_audition_passed(
        zone["id"], act_type="AMPLIFIED_MUSIC", amplification_requested=True,
        scheduled_for="2026-03-20T10:00:00Z", finalize_officer=OFFICER_ALPHA,
        performer_overrides={"legal_name": "Bo Kestrel", "stage_name": "Bo K",
                             "email": "bo@example.org"})
    assert float(ctx["audition"]["panel_score"]) == 7.90
    assert ctx["audition"]["status"] == "PASSED"

    decide_application(ctx["application"]["id"], "APPROVED", "Panel passed",
                       OFFICER_BETA)
    permit = find_permit_for_application(ctx["application"]["id"])
    invoice = first_permit_invoice(permit["id"])

    assert invoice["gross_fee_cents"] == 24500, "18000 base plus the 6500 surcharge"
    assert invoice["discount_cents"] == 3675, "15 percent of the pre-discount 24500"
    assert invoice["admin_fee_cents"] == 1225, "5 percent of the pre-discount 24500"
    assert invoice["amount_due_cents"] == 22050, (
        "24500 - 3675 + 1225; re-tiering on the post-discount 20825 would give "
        f"22075, got {invoice['amount_due_cents']}")
    assert invoice["fee_variant"] == "FULL_SEASON"
    assert permit["amplification_endorsed"] is True


def test_tier_two_admin_fee_is_charged_on_the_pre_discount_gross(api):
    """PRD §3.4: "Step three computes `discount_cents` as the gross multiplied by
    the tier's discount rate — nothing at all in tier 1, 10 percent in tier 2, 15
    percent in tier 3 — rounded half up to whole cents. Step four computes
    `admin_fee_cents` as the same pre-discount gross multiplied by the tier's
    administration rate — 8 percent in tier 1, 6 percent in tier 2, 5 percent in
    tier 3 — again rounded half up to whole cents. Both the tier selection and
    the administration charge are keyed on the gross figure, never on the
    discounted one; re-tiering on the net total would produce a different and
    incorrect charge. Step five produces the season total: the gross, minus the
    discount, plus the administration fee."
    PRD §3.4: "Step two picks a discount tier from that gross figure — the
    pre-discount one. A gross of $150.00 or less is tier 1; a gross above $150.00
    and up to and including $220.00 is tier 2; anything above $220.00 is tier 3."

    Design: Difficulty/combinatorial_formula/fee_tier_and_admin_rate_keyed_on_pre_discount_gross
    """
    set_clock("2026-03-15T09:00:00Z")
    zone = create_zone()
    ctx = setup_audition_passed(
        zone["id"], act_type="ACOUSTIC_MUSIC", amplification_requested=True,
        scheduled_for="2026-03-20T10:00:00Z", finalize_officer=OFFICER_ALPHA,
        performer_overrides={"legal_name": "Ivo Larch", "stage_name": "Ivo L",
                             "email": "ivo@example.org"})
    decide_application(ctx["application"]["id"], "APPROVED", "Panel passed",
                       OFFICER_BETA)
    permit = find_permit_for_application(ctx["application"]["id"])
    invoice = first_permit_invoice(permit["id"])

    assert invoice["gross_fee_cents"] == 18500, "12000 base plus the 6500 surcharge"
    assert invoice["discount_cents"] == 1850, "10 percent of the tier-2 gross 18500"
    assert invoice["admin_fee_cents"] == 1110, (
        "6 percent of the pre-discount 18500; charging it on the post-discount "
        f"16650 would give 999, got {invoice['admin_fee_cents']}")
    assert invoice["amount_due_cents"] == 17760, "18500 - 1850 + 1110"
    assert invoice["fee_variant"] == "FULL_SEASON"


# ---------------------------------------------------------------------------
# Queue B: calculations
# ---------------------------------------------------------------------------

def test_visual_art_invoice_issued_in_month_eight_is_prorated_to_five_months(api):
    """PRD §3.4: "The base fees are $90.00 for `VISUAL_ART`, $120.00 for
    `ACOUSTIC_MUSIC`, $150.00 for `STREET_THEATRE`, $180.00 for
    `AMPLIFIED_MUSIC` and $210.00 for `CIRCUS_SKILL`."
    PRD §3.4: "Under `PRORATED` the invoice records `coverage_start_month` as the
    UTC calendar month of `issued_at` and `months_covered` as 13 minus that
    month, and `amount_due_cents` is the season total multiplied by
    `months_covered`, divided by 12, and rounded half up to whole cents."
    PRD §3.4: "Every invoice is stamped with `issued_at` from the program clock
    and a `due_at` exactly 14 days later, and starts with `amount_paid_cents` 0,
    `refunded_cents` 0 and `paid_at` null."

    Design: Corner/calculations/corner_prorated_fee_for_visual_art_issued_in_month_eight
    """
    zone = create_zone(weekend_noise_bonus_db=0, evening_penalty_db=0)
    ctx = setup_permit_pending_fee(
        zone["id"], act_type="VISUAL_ART", amplification_requested=False,
        performer_overrides={"legal_name": "Fay Orrin", "stage_name": "Fay O",
                             "email": "fay@example.org"})
    invoice = ctx["invoice"]
    assert invoice["gross_fee_cents"] == 9000
    assert invoice["discount_cents"] == 0, "a 9000 gross sits in tier 1"
    assert invoice["admin_fee_cents"] == 720, "8 percent of 9000"
    assert invoice["fee_variant"] == "PRORATED"
    assert invoice["months_covered"] == 5
    assert invoice["amount_due_cents"] == 4050, (
        "9720 season total * 5 / 12 rounds half up to 4050, got "
        f"{invoice['amount_due_cents']}")
    assert invoice["status"] == "PENDING"
    assert invoice["amount_paid_cents"] == 0
    assert invoice["refunded_cents"] == 0
    assert invoice["paid_at"] is None
    assert_same_instant(invoice["due_at"], "2026-08-15T00:00:00Z", "due_at")


def test_gross_of_exactly_fifteen_thousand_stays_in_the_first_discount_tier(api):
    """PRD §3.4: "Both boundaries belong to the lower tier: a gross of exactly
    15000 cents is tier 1 while 15001 is tier 2, and exactly 22000 is tier 2
    while 22001 is tier 3."
    PRD §3.4: "Step three computes `discount_cents` as the gross multiplied by
    the tier's discount rate — nothing at all in tier 1, 10 percent in tier 2, 15
    percent in tier 3 — rounded half up to whole cents. Step four computes
    `admin_fee_cents` as the same pre-discount gross multiplied by the tier's
    administration rate — 8 percent in tier 1, 6 percent in tier 2, 5 percent in
    tier 3 — again rounded half up to whole cents."

    Design: Corner/calculations/corner_fee_tier_one_boundary_at_gross_exactly_fifteen_thousand
    """
    zone = create_zone(weekend_noise_bonus_db=0, evening_penalty_db=0)
    ctx = setup_permit_pending_fee(
        zone["id"], act_type="STREET_THEATRE", amplification_requested=False,
        performer_overrides={"legal_name": "Gil Ashby", "stage_name": "Gil A",
                             "email": "gil@example.org"})
    invoice = ctx["invoice"]
    assert invoice["gross_fee_cents"] == 15000
    assert invoice["discount_cents"] == 0, (
        "the tier-1 ceiling is inclusive; a tier-2 reading would deduct 1500")
    assert invoice["admin_fee_cents"] == 1200, (
        "8 percent of 15000; a tier-2 reading would charge 900")
    assert invoice["amount_due_cents"] == 6750
    assert read_application(ctx["application"]["id"])["assessed_fee_cents"] == 6750


# ---------------------------------------------------------------------------
# Queue B: the approval cascade and payment
# ---------------------------------------------------------------------------

def test_one_decision_request_mints_the_permit_and_its_initial_invoice(api):
    """PRD §3.4: "First, the approval **mints a permit** for the applicant: its
    `application_id` points back at the approved application, its `performer_id`
    at the applicant, its `season_year` is copied from the application's
    `season_year`, its `amplification_endorsed` flag is copied from the
    application's `amplification_requested`, its `lifecycle_status` starts at
    `PENDING_FEE` and its `compliance_status` at `CLEAR`."
    PRD §3.4: "The permit is stamped with a `permit_number` formatted as `BP-`,
    the season year, and a zero-padded four-digit sequence number —
    `BP-2026-0001` for the first permit of the 2026 season."
    PRD §3.4: "Second, the permit's own creation **mints its first invoice**,
    with `invoice_kind` `INITIAL` and `status` `PENDING`. Third, the invoice's
    creation **writes back** onto the application: `assessed_fee_cents` becomes
    that invoice's `amount_due_cents`."

    Design: Corner/cross_cutting_layers/corner_approval_cascade_mints_permit_and_invoice_in_one_request
    """
    zone = create_zone()
    performer = create_performer()
    application = create_application(performer["id"], zone["id"],
                                     requested_act_type="ACOUSTIC_MUSIC")
    submit_application(application["id"], performer["id"])
    review_application(application["id"], OFFICER_ALPHA)

    resp = api.decide_application(
        application["id"],
        decision_payload("APPROVED", "Approved on the papers"),
        make_officer_headers(OFFICER_BETA))
    decided = validate_success(resp, 200)
    assert decided["status"] == "APPROVED"

    permits, meta = validate_paginated(api.list_permits(
        make_officer_headers(), params={"application_id": application["id"]}))
    assert meta["total_count"] == 1
    permit = permits[0]
    assert_permit(permit)
    assert permit["lifecycle_status"] == "PENDING_FEE"
    assert permit["compliance_status"] == "CLEAR"
    assert permit["performer_id"] == performer["id"]
    assert permit["season_year"] == 2026
    assert_permit_number_format(permit, 2026, 1)

    invoices, inv_meta = validate_paginated(api.list_permit_invoices(
        permit["id"], make_officer_headers()))
    assert inv_meta["total_count"] == 1
    invoice = invoices[0]
    assert invoice["invoice_kind"] == "INITIAL"
    assert invoice["status"] == "PENDING"
    assert invoice["amount_due_cents"] == 5400

    assert read_application(application["id"])["assessed_fee_cents"] == 5400


def test_a_short_payment_is_refused_and_leaves_the_permit_unpaid(api):
    """PRD §3.5: "Payment carries a single field, `amount_cents`, and must match
    the invoice's `amount_due_cents` exactly; a short or over payment is refused
    with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/errors/corner_error_payment_amount_mismatch_rejected
    """
    zone = create_zone()
    ctx = setup_permit_pending_fee(zone["id"])
    assert ctx["invoice"]["amount_due_cents"] == 5400

    resp = api.pay_invoice(ctx["invoice"]["id"], payment_payload(5000),
                           make_performer_headers(ctx["performer"]["id"]))
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

    invoice = first_permit_invoice(ctx["permit"]["id"])
    assert invoice["status"] == "PENDING"
    assert invoice["amount_paid_cents"] == 0
    permit = read_permit(ctx["permit"]["id"])
    assert permit["lifecycle_status"] == "PENDING_FEE"
    assert permit["net_fees_paid_cents"] == 0


def test_payment_response_and_the_permit_read_agree_immediately(api):
    """PRD §3.5: "Settling an invoice runs its own two-level cascade. The invoice
    itself becomes `PAID`, its `amount_paid_cents` is set to the tendered
    `amount_cents`, and `paid_at` is stamped from the clock. That payment then
    credits the permit: `net_fees_paid_cents` grows by the amount just paid, and
    the permit's lifecycle axis advances — `PENDING_FEE → ACTIVE` when the
    settled invoice is the `INITIAL` one, with `activated_at` stamped from the
    clock, and `RENEWAL_PENDING → ACTIVE` when it is the `RENEWAL` one."
    PRD §2.5: "The server holds a single logical UTC clock that starts at exactly
    `2026-08-01T00:00:00Z` when the process boots and stays there until it is
    moved explicitly; it must never fall back to the host's real time, not even
    before the first move."

    Design: Corner/consistency_model/corner_payment_response_and_permit_read_agree_immediately
    """
    zone = create_zone()
    ctx = setup_permit_pending_fee(zone["id"])

    resp = api.pay_invoice(ctx["invoice"]["id"], payment_payload(5400),
                           make_performer_headers(ctx["performer"]["id"]))
    invoice = validate_success(resp, 200)
    assert invoice["status"] == "PAID"
    assert invoice["amount_paid_cents"] == 5400

    permit = read_permit(ctx["permit"]["id"])
    assert permit["lifecycle_status"] == "ACTIVE"
    assert permit["net_fees_paid_cents"] == 5400
    assert permit["compliance_status"] == "CLEAR"
    assert_same_instant(permit["activated_at"], CLOCK_START_UTC_ISO, "activated_at")
    assert_money_ledger_invariant(permit, list_permit_invoices(permit["id"]))
