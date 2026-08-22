"""Renewal, revocation, refunds and the money ledger."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_money_ledger_invariant, assert_fee_invoice,
    renew_payload, revoke_payload,
    set_clock, create_zone, create_pitch, run_epoch_advance,
    setup_permit_pending_fee, setup_active_permit,
    setup_district_pitch_and_active_permit,
    book_session, read_permit, read_booking, read_performer,
    list_permit_invoices, first_permit_invoice,
    revoke_permit, renew_permit, pay_invoice, uphold_new_complaint,
    make_officer_headers, make_performer_headers,
    OFFICER_ALPHA, OFFICER_BETA,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant /
#          full_refund_on_revocation_restores_net_fees_paid_to_zero
# ---------------------------------------------------------------------------

def test_full_refund_on_revocation_restores_net_fees_paid_to_zero(api):
    """PRD §3.5: "Under `FULL_REFUND` the refund is the invoice's entire
    `amount_paid_cents`, so a payment and its compensating refund leave
    `net_fees_paid_cents` at exactly its pre-payment value."
    PRD §3.5: "Revoking an `ACTIVE` or `RENEWAL_PENDING` permit runs the full
    four-level cascade: the lifecycle axis becomes `REVOKED`; that revocation
    refunds every `PAID` invoice on the permit, processed in `created_at`
    ascending order, writing each refund into the invoice's `refunded_cents`,
    moving that invoice to `REFUNDED` and subtracting the refunded amount from
    the permit's `net_fees_paid_cents`, while any invoice still `PENDING` or
    `PAST_DUE` becomes `VOID` and contributes nothing; the revocation also
    cancels every session on that permit whose `status` is `RESERVED` or
    `RELOCATED` and whose `start_at` is still in the future into
    `CANCELLED_BY_REVOCATION`; and each such cancellation in turn credits the
    permit's `season_minutes_used` back by that session's `duration_minutes`."

    Design: Difficulty/compensating_invariant/full_refund_on_revocation_restores_net_fees_paid_to_zero
    """
    zone = create_zone()
    ctx = setup_active_permit(zone["id"])
    permit_id = ctx["permit"]["id"]
    invoice = first_permit_invoice(permit_id)
    assert invoice["amount_due_cents"] == 5400
    assert invoice["amount_paid_cents"] == 5400
    assert invoice["months_covered"] == 5
    assert invoice["coverage_start_month"] == 8
    assert read_permit(permit_id)["net_fees_paid_cents"] == 5400

    set_clock("2026-08-05T00:00:00Z")
    revoked = revoke_permit(permit_id, "Permit surrendered by the holder",
                            refund_mode="FULL_REFUND")
    assert revoked["lifecycle_status"] == "REVOKED"

    invoice = first_permit_invoice(permit_id)
    assert invoice["refunded_cents"] == 5400, (
        "FULL_REFUND returns the entire amount_paid_cents, got "
        f"{invoice['refunded_cents']}")
    assert invoice["status"] == "REFUNDED"
    assert read_permit(permit_id)["net_fees_paid_cents"] == 0


def test_money_ledger_shows_no_drift_after_the_compensating_refund(api):
    """PRD §2.9: "The **money ledger** invariant: a permit's
    `net_fees_paid_cents` always equals the sum of `amount_paid_cents` over all
    of that permit's invoices minus the sum of their `refunded_cents`, evaluated
    over every invoice of the permit in `created_at` ascending order regardless
    of status — invoices that are pending, past due or void simply contribute
    zero on both sides. A payment and a compensating full refund must therefore
    leave `net_fees_paid_cents` at exactly its pre-payment value, with no
    drift."

    Design: Difficulty/compensating_invariant/full_refund_on_revocation_restores_net_fees_paid_to_zero
    """
    zone = create_zone()
    ctx = setup_active_permit(zone["id"])
    permit_id = ctx["permit"]["id"]

    set_clock("2026-08-05T00:00:00Z")
    revoke_permit(permit_id, "Permit surrendered by the holder",
                  refund_mode="FULL_REFUND")

    permit = read_permit(permit_id)
    invoices = list_permit_invoices(permit_id)
    assert len(invoices) == 1
    assert invoices[0]["amount_paid_cents"] == 5400, \
        "the forward payment is not erased by the compensating refund"
    assert invoices[0]["refunded_cents"] == 5400
    assert_money_ledger_invariant(permit, invoices)
    assert permit["net_fees_paid_cents"] == 0


# ---------------------------------------------------------------------------
# Queue B: revocation variants
# ---------------------------------------------------------------------------

def test_prorated_refund_returns_only_the_unused_months(api):
    """PRD §3.5: "How much comes back depends on `refund_mode`, which is
    `PRORATED_REFUND` when omitted. Under `FULL_REFUND` the refund is the
    invoice's entire `amount_paid_cents`, so a payment and its compensating
    refund leave `net_fees_paid_cents` at exactly its pre-payment value. Under
    `PRORATED_REFUND` only the whole calendar months after the revocation month
    come back: count the elapsed months as the UTC calendar month of the clock
    minus the invoice's `coverage_start_month`, plus one; take the unused months
    as the invoice's `months_covered` minus those elapsed months, or zero when
    that difference is negative; then the refund is the invoice's
    `amount_paid_cents` multiplied by the unused months, divided by
    `months_covered`, rounded half up to whole cents."

    Design: Corner/calculations/corner_prorated_refund_returns_only_the_unused_months
    """
    zone = create_zone()
    ctx = setup_active_permit(zone["id"])
    permit_id = ctx["permit"]["id"]
    invoice = first_permit_invoice(permit_id)
    assert invoice["coverage_start_month"] == 8
    assert invoice["months_covered"] == 5

    set_clock("2026-10-15T00:00:00Z")
    revoked = revoke_permit(permit_id, "Repeated unattended equipment")
    assert revoked["lifecycle_status"] == "REVOKED"

    invoice = first_permit_invoice(permit_id)
    assert invoice["refunded_cents"] == 2160, (
        "elapsed 10 - 8 + 1 = 3 leaves 2 unused of 5 months, so 5400 * 2 / 5 "
        f"rounds half up to 2160, got {invoice['refunded_cents']}")
    assert invoice["status"] == "REFUNDED"
    assert invoice["amount_paid_cents"] == 5400
    assert read_permit(permit_id)["net_fees_paid_cents"] == 3240


def test_revoking_a_never_paid_permit_voids_its_pending_invoice(api):
    """PRD §3.5: "Revoking a permit that never paid — one still in
    `PENDING_FEE` — simply voids every invoice on it that is `PENDING` or
    `PAST_DUE` and moves the lifecycle axis to `REVOKED`; there is nothing to
    refund and no booking to cancel."

    Design: Corner/state_machines/corner_revoke_from_pending_fee_voids_the_unpaid_invoice
    """
    zone = create_zone()
    ctx = setup_permit_pending_fee(zone["id"])
    permit_id = ctx["permit"]["id"]

    revoked = revoke_permit(permit_id, "Fraudulent ID detected")
    assert revoked["lifecycle_status"] == "REVOKED"

    invoice = first_permit_invoice(permit_id)
    assert invoice["status"] == "VOID"
    assert invoice["refunded_cents"] == 0
    assert invoice["amount_paid_cents"] == 0

    permit = read_permit(permit_id)
    assert permit["net_fees_paid_cents"] == 0
    assert_money_ledger_invariant(permit, list_permit_invoices(permit_id))


# ---------------------------------------------------------------------------
# Queue B: the renewal cycle
# ---------------------------------------------------------------------------

def test_renewal_payment_rolls_the_season_and_resets_the_counters(api):
    """PRD §3.5: "A renewal that clears all of that moves the permit `ACTIVE →
    RENEWAL_PENDING`, records the requested year in `next_season_year`, and
    mints a second invoice with `invoice_kind` `RENEWAL`. That invoice is always
    billed as a whole season: `fee_variant` `FULL_SEASON`, `months_covered` 12,
    `coverage_start_month` 1, `status` `PENDING`."
    PRD §3.5: "Paying a renewal invoice does considerably more than paying an
    initial one, because it rolls the season over. The permit's `season_year`
    becomes its `next_season_year` and `next_season_year` is cleared back to
    null; `season_minutes_used`, `closure_credit_minutes` and
    `noise_violation_count` are all reset to 0; and the holder's
    `premium_wins_this_season` is reset to 0 so the rotation priority bands
    start fresh."
    PRD §3.9: "Step four completes work already done: every session whose
    `status` is `RESERVED` or `RELOCATED` and whose `end_at` is at or before the
    clock moves to `COMPLETED`, and the permit's `season_minutes_used` is
    deliberately unchanged, because completed sessions still count against the
    season allowance."

    Design: Corner/state_machines/corner_renewal_payment_rolls_the_season_and_resets_ledgers
    """
    ctx = setup_district_pitch_and_active_permit()
    permit_id = ctx["permit"]["id"]
    performer_id = ctx["performer"]["id"]
    booking = book_session(permit_id, ctx["pitch"]["id"],
                           "2026-08-25T10:00:00Z", "2026-08-25T11:30:00Z",
                           performer_id)
    assert read_permit(permit_id)["season_minutes_used"] == 90

    set_clock("2026-11-01T00:00:00Z")
    run_epoch_advance()
    assert read_booking(booking["id"])["status"] == "COMPLETED"
    assert read_permit(permit_id)["season_minutes_used"] == 90

    renewed = renew_permit(permit_id, performer_id, 2027)
    assert renewed["lifecycle_status"] == "RENEWAL_PENDING"
    assert renewed["next_season_year"] == 2027

    renewal_invoices = list_permit_invoices(permit_id, invoice_kind="RENEWAL")
    assert len(renewal_invoices) == 1
    renewal = renewal_invoices[0]
    assert_fee_invoice(renewal)
    assert renewal["invoice_kind"] == "RENEWAL"
    assert renewal["fee_variant"] == "FULL_SEASON"
    assert renewal["months_covered"] == 12
    assert renewal["coverage_start_month"] == 1
    assert renewal["amount_due_cents"] == 12960, (
        "an ACOUSTIC_MUSIC renewal is billed 12000 gross plus 960 admin as a "
        f"whole season, got {renewal['amount_due_cents']}")

    pay_invoice(renewal, performer_id)

    permit = read_permit(permit_id)
    assert permit["lifecycle_status"] == "ACTIVE"
    assert permit["season_year"] == 2027
    assert permit["next_season_year"] is None
    assert permit["season_minutes_used"] == 0
    assert permit["noise_violation_count"] == 0
    assert permit["closure_credit_minutes"] == 0
    assert permit["net_fees_paid_cents"] == 18360
    assert read_performer(performer_id)["premium_wins_this_season"] == 0


def test_renewal_outside_the_window_is_refused(api):
    """PRD §3.5: "The clock must sit inside the renewal window for the permit's
    current season, which opens on 1 November of that year at `00:00:00Z` and
    closes at `23:59:59Z` on 31 December of that year — **both bounds
    inclusive**, so a renewal filed at exactly `2026-11-01T00:00:00Z` is
    admitted and one filed at exactly `2026-12-31T23:59:59Z` is still admitted.
    Outside that window the request is refused with
    `ERR_RENEWAL_WINDOW_CLOSED`."

    Design: Corner/errors/corner_error_renewal_window_closed_in_august
    """
    zone = create_zone()
    ctx = setup_active_permit(zone["id"])
    permit_id = ctx["permit"]["id"]

    resp = api.renew_permit(permit_id, renew_payload(2027),
                            make_performer_headers(ctx["performer"]["id"]))
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)

    permit = read_permit(permit_id)
    assert permit["lifecycle_status"] == "ACTIVE"
    assert permit["next_season_year"] is None
    assert len(list_permit_invoices(permit_id)) == 1, \
        "the refused renewal mints no RENEWAL invoice"


def test_renewal_conduct_gate_refuses_a_career_score_of_seventy_six(api):
    """PRD §3.5: "And the holder must clear the conduct gate — a
    `renewal_conduct_score` of at least 80, judged on the career-weighted figure
    and never on the live one, refused with `ERR_RENEWAL_CONDUCT_INSUFFICIENT`
    when it falls short."
    PRD §3.8: "Out of `TRIAGED` the full severity charge applies: 5 points for
    `MINOR`, 12 for `MODERATE`, 25 for `MAJOR`."
    PRD §3.8: "The `standing` is derived from the live score alone: `GOOD` when
    `conduct_score` is 80 or more, `WATCH` when it is at least 60 but below 80,
    and `BARRED` when it is below 60."

    Design: Corner/errors/corner_error_renewal_conduct_insufficient_at_seventy_six
    """
    zone = create_zone()
    ctx = setup_active_permit(zone["id"])
    permit_id = ctx["permit"]["id"]
    performer_id = ctx["performer"]["id"]

    uphold_new_complaint(permit_id, "MODERATE", "DIRECT", resident="resident-1",
                         category="NOISE", description="Backing track too loud")
    uphold_new_complaint(permit_id, "MODERATE", "DIRECT", resident="resident-2",
                         category="OBSTRUCTION",
                         description="Pitch spilled onto the pavement")

    performer = read_performer(performer_id)
    assert performer["conduct_score"] == 76, "two MODERATE charges of 12 from 100"
    assert performer["renewal_conduct_score"] == 76
    assert performer["standing"] == "WATCH"
    assert read_permit(permit_id)["compliance_status"] == "CLEAR"

    set_clock("2026-11-01T00:00:00Z")
    resp = api.renew_permit(permit_id, renew_payload(2027),
                            make_performer_headers(performer_id))
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_RENEWAL_CONDUCT_INSUFFICIENT)
    assert read_permit(permit_id)["lifecycle_status"] == "ACTIVE"


def test_past_due_renewal_invoice_lapses_the_permit_and_blocks_a_second_renewal(api):
    """PRD §3.9: "Step two sweeps money: every invoice still `PENDING` whose
    `due_at` is strictly before the clock moves `PENDING → PAST_DUE`, which
    immediately blocks that permit from new bookings and new lottery entries.
    When the invoice swept this way is a `RENEWAL` invoice, its permit lapses
    back out of the renewal cycle: it moves `RENEWAL_PENDING → ACTIVE` and its
    `next_season_year` is cleared to null, while its `season_year`,
    `season_minutes_used` and compliance axis are all left untouched. The
    past-due invoice is **not** voided — it goes on blocking bookings and
    entries, and it goes on blocking a second renewal attempt with
    `ERR_OUTSTANDING_INVOICE`."
    PRD §3.5: "The permit must carry no unsettled money at all: any invoice on it
    that is `PENDING` or `PAST_DUE` refuses the renewal with
    `ERR_OUTSTANDING_INVOICE`."

    Design: Corner/errors/corner_error_outstanding_invoice_blocks_a_second_renewal
    """
    zone = create_zone()
    ctx = setup_active_permit(zone["id"])
    permit_id = ctx["permit"]["id"]
    performer_id = ctx["performer"]["id"]

    set_clock("2026-11-01T00:00:00Z")
    renew_permit(permit_id, performer_id, 2027)
    renewal = list_permit_invoices(permit_id, invoice_kind="RENEWAL")[0]

    set_clock("2026-11-20T00:00:00Z")
    run_epoch_advance()

    swept = [i for i in list_permit_invoices(permit_id)
             if i["id"] == renewal["id"]][0]
    assert swept["status"] == "PAST_DUE"
    assert swept["amount_due_cents"] == 12960

    permit = read_permit(permit_id)
    assert permit["lifecycle_status"] == "ACTIVE", \
        "a swept RENEWAL invoice lapses the permit back out of the renewal cycle"
    assert permit["next_season_year"] is None

    resp = api.renew_permit(permit_id, renew_payload(2027),
                            make_performer_headers(performer_id))
    assert resp.status_code == 402, f"Expected 402, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_INVOICE)
