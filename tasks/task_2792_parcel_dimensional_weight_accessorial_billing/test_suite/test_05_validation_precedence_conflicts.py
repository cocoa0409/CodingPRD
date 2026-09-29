"""Requests that break two or three rules at once, where only one may be reported.

A 999999-cent credit against a settled invoice breaks a lifecycle rule and both
fiscal ceilings; a repeat dispute filed after the ninety-day deadline breaks
both the uniqueness rule and the temporal one. Each pair is also exercised in
the configuration where the lower-ranked rule is the only one broken, so the
ordering is proved rather than assumed.
"""

import pytest

from test_helpers import (
    BILLING_OPS_HEADERS,
    ERR_ADJUSTMENT_EXCEEDS_LINE,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_DUPLICATE_DISPUTE,
    ERR_INVOICE_NOT_ADJUSTABLE,
    RESIDENTIAL_OVERRIDE_540,
    ROUNDING_DECLARED,
    SMALL_DECLARED,
    assert_instant,
    assert_money_equals,
    billing_adjustment_payload,
    delivered_shipment,
    dispute_payload,
    filed_dispute,
    get_success_data,
    issued_invoice,
    line_for_shipment,
    open_invoice,
    refresh_invoice,
    refresh_invoice_line,
    set_clock,
    settled_invoice,
    shipper_with_active_contract,
    validate_error,
)

OVERSIZED_CREDIT_CENTS = -999999


# ---------------------------------------------------------------------------
# Lifecycle state versus the two fiscal ceilings
# ---------------------------------------------------------------------------
@pytest.fixture
def a_settled_and_an_issued_invoice(api):
    """Two 2660 cent invoices for one shipper: one SETTLED, one ISSUED.

    Both lines total 2660 cents, so a 999999 cent credit breaches the line
    ceiling on either of them.
    """
    shipper = shipper_with_active_contract(
        api, account_number="SH-1001", with_ground=False
    )
    parcel_a = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-PA-0021",
        zone=2,
        residential_declared=False,
        **SMALL_DECLARED,
    )
    settled = settled_invoice(
        api,
        issued_invoice(api, open_invoice(api, shipper, [parcel_a.shipment_id])),
        payment_reference="ACH-778",
    )
    settled_line = line_for_shipment(api, settled.invoice_id, parcel_a.shipment_id)

    parcel_b = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-PB-0022",
        zone=2,
        residential_declared=False,
        **SMALL_DECLARED,
    )
    issued = issued_invoice(api, open_invoice(api, shipper, [parcel_b.shipment_id]))
    issued_line = line_for_shipment(api, issued.invoice_id, parcel_b.shipment_id)

    assert_money_equals(settled_line["line_total_cents"], 2660, "settled line total")
    assert_money_equals(issued_line["line_total_cents"], 2660, "issued line total")
    return {
        "shipper": shipper,
        "settled": settled,
        "settled_line": settled_line,
        "issued": issued,
        "issued_line": issued_line,
    }


def _propose_oversized_credit(api, line_id, expected_invoice_version, note):
    """Attempt a 999999 cent credit against one line."""
    return api.create_billing_adjustment(
        billing_adjustment_payload(
            line_id,
            OVERSIZED_CREDIT_CENTS,
            expected_invoice_version,
            reason="MANUAL",
            note=note,
        ),
        BILLING_OPS_HEADERS,
    )


def _adjustments_on_line(api, line_id):
    """Every adjustment row that exists for one line, of any status."""
    return get_success_data(
        api.list_billing_adjustments(
            BILLING_OPS_HEADERS, {"invoice_line_id": line_id, "limit": 100}
        )
    )


def test_a_settled_invoice_refuses_the_credit_on_its_state_before_any_ceiling(
    api, a_settled_and_an_issued_invoice
):
    """PRD §3.8: "Fourth, the invoice behind the line must be `ISSUED` or `ADJUSTED`, else `ERR_INVOICE_NOT_ADJUSTABLE` (HTTP 409) — an `OPEN` invoice is edited in place rather than adjusted, and a `SETTLED` or `VOID` invoice is closed to adjustment entirely."
    PRD §3.8: "Fifth and last come the two fiscal ceilings, which apply only to credits: for a credit, the credit's magnitude must not exceed the target line's current `line_total_cents`, else `ERR_ADJUSTMENT_EXCEEDS_LINE` (HTTP 422); and the invoice's `net_amount_cents` plus the `delta_cents` must be at least 0, so a credit may never push an invoice negative, else `ERR_CREDIT_EXCEEDS_INVOICE_NET` (HTTP 422)."
    PRD §2.10: "Across the whole API, validation follows a fixed global precedence, and the first failing tier decides the response:"

    Design: Difficulty/priority_pair_validation_conflict/settled_invoice_state_check_outranks_the_credit_ceiling_check
    """
    ctx = a_settled_and_an_issued_invoice
    response = _propose_oversized_credit(
        api,
        ctx["settled_line"]["id"],
        ctx["settled"].invoice_version,
        "triple violation probe",
    )
    validate_error(response, ERR_INVOICE_NOT_ADJUSTABLE, 409)


def test_the_same_oversized_credit_reaches_the_line_ceiling_on_an_issued_invoice(
    api, a_settled_and_an_issued_invoice
):
    """PRD §3.8: "for a credit, the credit's magnitude must not exceed the target line's current `line_total_cents`, else `ERR_ADJUSTMENT_EXCEEDS_LINE` (HTTP 422)"
    PRD §3.8: "Five checks guard a proposal, and they are evaluated in this order."

    Design: Difficulty/priority_pair_validation_conflict/settled_invoice_state_check_outranks_the_credit_ceiling_check
    """
    ctx = a_settled_and_an_issued_invoice
    response = _propose_oversized_credit(
        api, ctx["issued_line"]["id"], ctx["issued"].invoice_version, "ceiling probe"
    )
    validate_error(response, ERR_ADJUSTMENT_EXCEEDS_LINE, 422)


def test_neither_rejected_proposal_leaves_a_row_or_moves_an_invoice(
    api, a_settled_and_an_issued_invoice
):
    """PRD §3.8: "A proposal is created by `BillingOps` at `status` `PROPOSED` with `created_by_user_id` set to the proposing operator's `X-User-ID`, `applied_by_user_id` null, and `applied_at` null."
    PRD §2.5: "`version` (integer): a counter that starts at 1 on creation and increments by exactly 1 on every mutation of the record, including mutations the server performs on its own initiative as a cascade from some other request."
    PRD §3.7: "A settled invoice is terminal: it admits no further adjustment and no further dispute."

    Design: Difficulty/priority_pair_validation_conflict/settled_invoice_state_check_outranks_the_credit_ceiling_check
    """
    ctx = a_settled_and_an_issued_invoice
    issued_version_before = ctx["issued"].invoice_version

    validate_error(
        _propose_oversized_credit(
            api,
            ctx["settled_line"]["id"],
            ctx["settled"].invoice_version,
            "triple violation probe",
        ),
        ERR_INVOICE_NOT_ADJUSTABLE,
        409,
    )
    validate_error(
        _propose_oversized_credit(
            api, ctx["issued_line"]["id"], issued_version_before, "ceiling probe"
        ),
        ERR_ADJUSTMENT_EXCEEDS_LINE,
        422,
    )

    settled = refresh_invoice(api, ctx["settled"].invoice_id)
    assert settled["status"] == "SETTLED"
    assert_money_equals(settled["adjustment_total_cents"], 0, "adjustment_total_cents")
    assert_money_equals(settled["net_amount_cents"], 2660, "net_amount_cents")
    assert settled["pending_adjustment_count"] == 0

    issued = refresh_invoice(api, ctx["issued"].invoice_id)
    assert issued["status"] == "ISSUED"
    assert_money_equals(issued["adjustment_total_cents"], 0, "adjustment_total_cents")
    assert issued["pending_adjustment_count"] == 0
    assert issued["version"] == issued_version_before, (
        "a rejected proposal must not bump the invoice version, expected "
        f"{issued_version_before}, got {issued['version']}"
    )

    assert _adjustments_on_line(api, ctx["settled_line"]["id"]) == []
    assert _adjustments_on_line(api, ctx["issued_line"]["id"]) == []


# ---------------------------------------------------------------------------
# The dispute window versus the duplicate-dispute rule
# ---------------------------------------------------------------------------
ISSUE_CLOCK_UTC = "2026-08-05T00:00:00Z"
DISPUTE_DEADLINE_UTC = "2026-11-03T00:00:00Z"
AFTER_DEADLINE_UTC = "2026-11-04T00:00:01Z"


@pytest.fixture
def line_with_one_open_dispute(api):
    """A 7760 cent residential line under one SUBMITTED accessorial dispute.

    The invoice is issued at 2026-08-05T00:00:00Z, which puts its ninety-day
    dispute deadline at 2026-11-03T00:00:00Z.
    """
    shipper = shipper_with_active_contract(
        api,
        account_number="SH-1001",
        contract_kwargs={"accessorial_rate_overrides": dict(RESIDENTIAL_OVERRIDE_540)},
        with_ground=False,
    )
    parcel = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-PW-0031",
        zone=2,
        residential_declared=True,
        **ROUNDING_DECLARED,
    )
    set_clock(api, ISSUE_CLOCK_UTC)
    invoice = issued_invoice(api, open_invoice(api, shipper, [parcel.shipment_id]))
    line = line_for_shipment(api, invoice.invoice_id, parcel.shipment_id)
    dispute = filed_dispute(
        api,
        invoice,
        line["id"],
        claim_type="ACCESSORIAL",
        disputed_codes=["RESIDENTIAL"],
        claimed_reason="Commercial dock delivery",
    )
    return {
        "shipper": shipper,
        "invoice": invoice,
        "line": line,
        "dispute": dispute,
    }


def _file_repeat_dispute(api, ctx, reason):
    """Attempt a second ACCESSORIAL dispute on the already-disputed line."""
    return api.create_dispute(
        dispute_payload(
            ctx["line"]["id"],
            claim_type="ACCESSORIAL",
            claimed_reason=reason,
            disputed_codes=["RESIDENTIAL"],
        ),
        ctx["shipper"].shipper_headers,
    )


def test_a_second_dispute_inside_the_window_is_refused_only_as_a_duplicate(
    api, line_with_one_open_dispute
):
    """PRD §3.9: "No other dispute on the same `invoice_line_id` may be sitting at `SUBMITTED`, `UNDER_REVIEW`, `EVIDENCE_REQUESTED`, or `UPHELD`, else `ERR_DUPLICATE_DISPUTE` (HTTP 409) — note that a previously `DENIED` dispute does not block a fresh filing."
    PRD §3.7: "Issue stamps `issued_at` from the logical clock and derives `dispute_deadline_utc` as that instant advanced by the ninety-day dispute window."

    Design: Difficulty/priority_pair_validation_conflict/dispute_window_closure_outranks_the_duplicate_dispute_rule
    """
    ctx = line_with_one_open_dispute
    invoice = refresh_invoice(api, ctx["invoice"].invoice_id)
    assert_instant(invoice["issued_at"], ISSUE_CLOCK_UTC, "issued_at")
    assert_instant(
        invoice["dispute_deadline_utc"], DISPUTE_DEADLINE_UTC, "dispute_deadline_utc"
    )

    validate_error(
        _file_repeat_dispute(api, ctx, "Second bite while the window is open"),
        ERR_DUPLICATE_DISPUTE,
        409,
    )


def test_after_the_deadline_the_closed_window_outranks_the_duplicate_rule(
    api, line_with_one_open_dispute
):
    """PRD §3.9: "The logical clock must be at or before the invoice's `dispute_deadline_utc`, which sits ninety days after `issued_at`; equality is still inside the window, and a later clock yields `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 422)."
    PRD §3.9: "Five guards apply to a filing, in this order."
    PRD §2.10: "7. **Temporal validity**: period orderings, contract overlap, window overlap, and the dispute and claim filing windows."
    PRD §2.10: "8. **Referential and business constraints**: duplicate dispute and claim guards, contract and rate-row resolution, sweep candidacy, evidence rounds, and guarantee eligibility."

    Design: Difficulty/priority_pair_validation_conflict/dispute_window_closure_outranks_the_duplicate_dispute_rule
    """
    ctx = line_with_one_open_dispute
    set_clock(api, AFTER_DEADLINE_UTC)

    validate_error(
        _file_repeat_dispute(api, ctx, "Second bite after the window closed"),
        ERR_DISPUTE_WINDOW_CLOSED,
        422,
    )


def test_both_rejected_filings_leave_the_original_dispute_and_its_line_untouched(
    api, line_with_one_open_dispute
):
    """PRD §3.9: "A new dispute opens at `status` `SUBMITTED` with `shipper_user_id` stamped from the filer's `X-User-ID`, `round_count` at 0, `required_item_type` null, `accepted_evidence_count` at 0, `granted_credit_cents` at 0, and `resolved_at` null."
    PRD §2.9: "An invoice line is a **frozen quotation** the moment its invoice leaves the `OPEN` state."

    Design: Difficulty/priority_pair_validation_conflict/dispute_window_closure_outranks_the_duplicate_dispute_rule
    """
    ctx = line_with_one_open_dispute
    validate_error(
        _file_repeat_dispute(api, ctx, "Second bite while the window is open"),
        ERR_DUPLICATE_DISPUTE,
        409,
    )
    set_clock(api, AFTER_DEADLINE_UTC)
    validate_error(
        _file_repeat_dispute(api, ctx, "Second bite after the window closed"),
        ERR_DISPUTE_WINDOW_CLOSED,
        422,
    )

    original = get_success_data(
        api.get_dispute(ctx["dispute"].dispute_id, BILLING_OPS_HEADERS)
    )
    assert original["status"] == "SUBMITTED"
    assert original["round_count"] == 0
    assert original["accepted_evidence_count"] == 0

    rows = get_success_data(
        api.list_disputes(
            BILLING_OPS_HEADERS, {"invoice_line_id": ctx["line"]["id"], "limit": 100}
        )
    )
    assert len(rows) == 1, (
        f"no partial dispute may be persisted by a rejection, found {len(rows)} rows"
    )
    assert rows[0]["id"] == ctx["dispute"].dispute_id

    line = refresh_invoice_line(api, ctx["line"]["id"])
    assert_money_equals(line["line_total_cents"], 7760, "line_total_cents")
    assert refresh_invoice(api, ctx["invoice"].invoice_id)["status"] == "ISSUED"
