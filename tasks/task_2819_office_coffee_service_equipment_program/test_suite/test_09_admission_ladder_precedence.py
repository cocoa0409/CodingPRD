"""Two admission-ladder pairs: the visit-state gate above the delivered-units
gate, and the credit-target gate above the credit ceiling.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_par_level, assert_service_visit
from test_helpers.fixtures import (
    ANCHOR_MONDAY,
    CATALOG_SPEC_COFFEE_ONLY,
    assemble_invoice_for,
    complete_stop,
    issue_invoice,
    lines_by_type,
    list_invoice_lines,
    par_line_for,
    read_account,
    read_invoice,
    read_invoice_line,
    read_visit,
    schedule_stop_with_lines,
    set_clock,
    setup_planned_site,
)
from test_helpers.test_users import TEST_USERS, make_route_technician_headers

BS = TEST_USERS["billing_specialist_headers"]

COMPLETION_INSTANT = "2026-08-03T09:30:00Z"


def _completed_coffee_stop():
    """One break room served twenty units of green-linked coffee, reported."""
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    visit = schedule_stop_with_lines(base, {"COFFEE": 20})
    base["visit"] = complete_stop(
        base, visit, {"COFFEE": 20}, complete_at=COMPLETION_INSTANT
    )
    return base


def test_a_second_completion_answers_with_the_state_gate_not_the_overflow():
    """Reporting an already-reported stop with an impossible quantity surfaces the
    visit-state conflict, and the shelf ledger is left exactly as it was.

    "Four gates precede the arithmetic, in this order: the technician must own the
    visit's route (`ERR_ACTOR_NOT_ON_ROUTE`); the site's service posture must be
    `ACTIVE` or `ESCALATED`, so a suspended site refuses completion with
    `ERR_SITE_NOT_SERVICEABLE` even for a visit that is otherwise perfectly
    schedulable; the visit must be `SCHEDULED`, otherwise `ERR_VISIT_STATE_INVALID`;
    and the window must have opened, meaning the current instant is at or after
    `window_start` — an earlier attempt is rejected with
    `ERR_VISIT_NOT_YET_STARTED` (HTTP 422). Only then are the delivered quantities
    validated."

    Design: Difficulty/priority_pair_validation_conflict/visit_state_conflict_beats_delivered_units_overflow
    """
    base = _completed_coffee_stop()
    visit = base["visit"]
    coffee_id = base["products"]["COFFEE"]["id"]
    assert_service_visit(visit)
    assert visit["visit_status"] == "COMPLETED"
    assert visit["completed_at"] == COMPLETION_INSTANT

    refused = api_client.complete_visit(
        visit["id"],
        f.complete_visit_payload([f.delivered_line(coffee_id, 999)]),
        make_route_technician_headers(base["route"]["id"]),
    )
    error = validate_error(refused, "ERR_VISIT_STATE_INVALID", 409)
    assert error["error_id"] != "ERR_DELIVERED_EXCEEDS_REQUESTED"

    after = read_visit(visit["id"])
    assert after["visit_status"] == "COMPLETED"
    assert after["completed_at"] == COMPLETION_INSTANT
    reported = [line for line in after["lines"] if line["product_id"] == coffee_id]
    assert len(reported) == 1
    assert reported[0]["delivered_units"] == 20, "the refused report stamped nothing"
    assert reported[0]["requested_units"] == 20
    assert reported[0]["resulting_on_hand_units"] == 20

    par_line = par_line_for(base["site"]["id"], coffee_id)
    assert_par_level(par_line)
    assert par_line["cumulative_delivered_units"] == 20
    assert par_line["cumulative_consumed_units"] == 0
    assert par_line["on_hand_units"] == 20


def test_the_overflow_gate_does_fire_once_the_visit_is_still_schedulable():
    """On a stop that has not been reported yet the same impossible quantity is
    the overflow rejection, an unstocked product is rejected the same way, and the
    honest report then completes.

    "Only products already present on the visit's `lines` array may be reported,
    each reported quantity must be at least 0 and must not exceed that line's
    `requested_units`, and any violation of either — including naming a product
    absent from the visit's lines — is rejected with
    `ERR_DELIVERED_EXCEEDS_REQUESTED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/visit_state_conflict_beats_delivered_units_overflow
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    visit = schedule_stop_with_lines(base, {"COFFEE": 20})
    coffee_id = base["products"]["COFFEE"]["id"]
    headers = make_route_technician_headers(base["route"]["id"])
    set_clock(COMPLETION_INSTANT)

    over = api_client.complete_visit(
        visit["id"],
        f.complete_visit_payload([f.delivered_line(coffee_id, 999)]),
        headers,
    )
    error = validate_error(over, "ERR_DELIVERED_EXCEEDS_REQUESTED", 422)
    assert error["error_id"] != "ERR_VISIT_STATE_INVALID"
    assert read_visit(visit["id"])["visit_status"] == "SCHEDULED"

    # One unit over the request is still over the request.
    validate_error(
        api_client.complete_visit(
            visit["id"],
            f.complete_visit_payload([f.delivered_line(coffee_id, 21)]),
            headers,
        ),
        "ERR_DELIVERED_EXCEEDS_REQUESTED",
        422,
    )

    untouched = par_line_for(base["site"]["id"], coffee_id)
    assert untouched["cumulative_delivered_units"] == 0
    assert untouched["on_hand_units"] == 0
    assert untouched["last_service_at"] == ANCHOR_MONDAY

    completed = validate_success(
        api_client.complete_visit(
            visit["id"],
            f.complete_visit_payload([f.delivered_line(coffee_id, 20)]),
            headers,
        ),
        200,
    )
    assert completed["visit_status"] == "COMPLETED"
    assert completed["completed_at"] == COMPLETION_INSTANT
    assert completed["shortfall_flag"] is False
    assert par_line_for(base["site"]["id"], coffee_id)["on_hand_units"] == 20


FIRST_PERIOD = ("2026-08-01T00:00:00Z", "2026-08-15T23:59:59Z")
SECOND_PERIOD = ("2026-08-16T00:00:00Z", "2026-08-31T23:59:59Z")
INVOICE_TOTAL_CENTS = 11500


def _two_issued_invoices():
    """Two closed fortnights, each carrying one coffee delivery and its flat
    freight charge, both issued against the same consolidated programme."""
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_ONLY
    )
    first_stop = schedule_stop_with_lines(base, {"COFFEE": 20})
    complete_stop(base, first_stop, {"COFFEE": 20})
    second_stop = schedule_stop_with_lines(
        base,
        {"COFFEE": 20},
        window_start="2026-08-17T09:00:00Z",
        window_end="2026-08-17T09:45:00Z",
    )
    complete_stop(base, second_stop, {"COFFEE": 20})

    set_clock("2026-09-01T00:00:00Z")
    account_id = base["account"]["id"]
    base["invoice_1"] = issue_invoice(
        assemble_invoice_for(account_id, *FIRST_PERIOD)["id"]
    )
    base["invoice_2"] = issue_invoice(
        assemble_invoice_for(account_id, *SECOND_PERIOD)["id"]
    )
    for key in ("invoice_1", "invoice_2"):
        invoice = base[key]
        assert invoice["invoice_status"] == "ISSUED"
        assert invoice["total_cents"] == INVOICE_TOTAL_CENTS
        assert invoice["line_count"] == 2
    base["line_1"] = lines_by_type(base["invoice_1"]["id"])["PRODUCT"][0]
    base["line_2"] = lines_by_type(base["invoice_2"]["id"])["PRODUCT"][0]
    assert base["line_1"]["amount_cents"] == 9000
    assert base["line_2"]["amount_cents"] == 9000
    assert read_account(account_id)["receivable_balance_cents"] == 2 * (
        INVOICE_TOTAL_CENTS
    )
    return base


def test_a_foreign_credit_target_answers_before_the_credit_ceiling():
    """A credit aimed at another invoice's line and carrying an absurd amount
    answers with the target mismatch, and neither invoice nor the receivable moves.

    "The target line must belong to **this** invoice and must not itself be a
    `CREDIT` line; a violation of either yields `ERR_CREDIT_TARGET_MISMATCH` (HTTP
    422). The credit amount must be above 0, and the cumulative credited amount
    across the invoice must not exceed the invoice's pre-credit `total_cents`; a
    violation of either yields `ERR_CREDIT_EXCEEDS_INVOICE_TOTAL` (HTTP 422)."

    "When a single request could fail several checks, the outcome is not a matter
    of implementation taste. Checks are evaluated in a fixed global order, and the
    **first** failing check determines the response."

    Design: Difficulty/priority_pair_validation_conflict/credit_target_mismatch_beats_credit_amount_overflow
    """
    base = _two_issued_invoices()

    refused = api_client.credit_invoice(
        base["invoice_2"]["id"],
        f.credit_invoice_payload(
            base["line_1"]["id"], 99999999, "Duplicate delivery reported by customer"
        ),
        BS,
    )
    error = validate_error(refused, "ERR_CREDIT_TARGET_MISMATCH", 422)
    assert error["error_id"] != "ERR_CREDIT_EXCEEDS_INVOICE_TOTAL"

    second = read_invoice(base["invoice_2"]["id"])
    assert second["invoice_status"] == "ISSUED"
    assert second["total_cents"] == INVOICE_TOTAL_CENTS
    assert second["line_count"] == 2
    first = read_invoice(base["invoice_1"]["id"])
    assert first["total_cents"] == INVOICE_TOTAL_CENTS
    assert first["line_count"] == 2
    assert read_invoice_line(base["line_1"]["id"])["credits_applied_cents"] == 0
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == 23000


def test_the_ceiling_gate_does_fire_once_the_target_is_the_right_invoice():
    """Aimed at its own invoice's line the same absurd amount is the ceiling
    rejection; a legitimate partial credit then lands, a credit line is itself an
    invalid target, and the cumulative ceiling is enforced to the cent.

    "A successful credit appends a new invoice line whose `line_type` is `CREDIT`,
    whose `amount_cents` is the **negation** of the requested amount, whose
    `target_line_id` points at the credited line, and whose `credit_reason` carries
    the supplied reason. The target line's `credits_applied_cents` increases by the
    requested amount."

    "The invoice then moves to `PARTIALLY_CREDITED` when the cumulative credits
    after this one are strictly less than the pre-credit total, and to
    `FULLY_CREDITED` when they exactly equal it, at which point the invoice's total
    is 0 and the invoice is terminal."

    Design: Difficulty/priority_pair_validation_conflict/credit_target_mismatch_beats_credit_amount_overflow
    """
    base = _two_issued_invoices()
    invoice_id = base["invoice_2"]["id"]
    own_line_id = base["line_2"]["id"]

    over = api_client.credit_invoice(
        invoice_id,
        f.credit_invoice_payload(own_line_id, 99999999, "Duplicate delivery"),
        BS,
    )
    error = validate_error(over, "ERR_CREDIT_EXCEEDS_INVOICE_TOTAL", 422)
    assert error["error_id"] != "ERR_CREDIT_TARGET_MISMATCH"
    assert read_invoice(invoice_id)["line_count"] == 2
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == 23000

    partial = validate_success(
        api_client.credit_invoice(
            invoice_id,
            f.credit_invoice_payload(own_line_id, 4000, "Short-poured urn"),
            BS,
        ),
        201,
    )
    assert partial["line_type"] == "CREDIT"
    assert partial["amount_cents"] == -4000
    assert partial["target_line_id"] == own_line_id

    credited = read_invoice(invoice_id)
    assert credited["invoice_status"] == "PARTIALLY_CREDITED"
    assert credited["total_cents"] == INVOICE_TOTAL_CENTS - 4000
    assert credited["line_count"] == 3
    assert read_invoice_line(own_line_id)["credits_applied_cents"] == 4000
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == 19000

    # A credit line may not itself be credited.
    validate_error(
        api_client.credit_invoice(
            invoice_id,
            f.credit_invoice_payload(partial["id"], 100, "Credit the credit"),
            BS,
        ),
        "ERR_CREDIT_TARGET_MISMATCH",
        422,
    )

    # The ceiling is the invoice's pre-credit total, cumulatively.
    validate_error(
        api_client.credit_invoice(
            invoice_id,
            f.credit_invoice_payload(own_line_id, 7501, "One cent too far"),
            BS,
        ),
        "ERR_CREDIT_EXCEEDS_INVOICE_TOTAL",
        422,
    )

    final = validate_success(
        api_client.credit_invoice(
            invoice_id,
            f.credit_invoice_payload(own_line_id, 7500, "Remainder written back"),
            BS,
        ),
        201,
    )
    assert final["amount_cents"] == -7500
    settled = read_invoice(invoice_id)
    assert settled["invoice_status"] == "FULLY_CREDITED"
    assert settled["total_cents"] == 0
    assert settled["line_count"] == 4
    assert read_invoice_line(own_line_id)["credits_applied_cents"] == (
        INVOICE_TOTAL_CENTS
    )
    assert len(list_invoice_lines(invoice_id)) == 4
    assert read_account(base["account"]["id"])["receivable_balance_cents"] == (
        INVOICE_TOTAL_CENTS
    )
    assert read_invoice(base["invoice_1"]["id"])["invoice_status"] == "ISSUED"
