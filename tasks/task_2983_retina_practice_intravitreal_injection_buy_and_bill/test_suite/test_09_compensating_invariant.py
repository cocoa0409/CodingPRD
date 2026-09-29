"""
Undo paths that must leave the ledgers balanced.

Annulling a documented injection may not resurrect the dose it consumed, and the
recall ladder must close the vial ledger and the money ledger without drift.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_vial_conservation,
    assert_vial_counters,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    COMPLIANCE_USER_ID,
    COMPLIANCE_USER_ID_2,
    compliance_headers,
    specialist_headers,
)


# ==========================================================================
# voiding_a_documented_encounter_conserves_the_lot_vial_count_without_resurrecting_stock
# ==========================================================================


def _voided_after_documentation(depth):
    """Document the first injection and then annul it, returning the void result."""
    documented = depth.enc1_documented
    voided = validate_success(
        depth.api.void_injection_encounter(
            documented["id"],
            f.void_payload(void_reason="Documented against the wrong eye"),
            specialist_headers(depth.cl1["id"]),
        ),
        200,
    )
    return voided


def test_the_injected_vial_is_quarantined_rather_than_returned_to_stock(depth):
    """
    Annulling a documented injection moves the vial out of usable inventory instead
    of back onto the shelf, and the six counters still sum to the five vials booked
    in.

    The PRD refuses to pretend the dose was never given: "Here the vial has already
    been injected, and pretending otherwise would break the conservation invariant of
    §2.9, so the vial is **not** returned to stock: it moves `ADMINISTERED →
    QUARANTINED`, preserving the lot's total while removing the vial from usable
    inventory, and the lot's `vials_administered` and `vials_quarantined` are
    recomputed."  The vial keeps its clinical history — the void "keeps every figure
    it had computed ... the record is annulled, not erased" — and `administered_at`
    was "stamped with the encounter's `encounter_datetime` rather than with the
    clock", so it still reads 2026-08-01T09:00:00Z.

    Design: Difficulty/compensating_invariant/voiding_a_documented_encounter_conserves_the_lot_vial_count_without_resurrecting_stock
    """
    voided = _voided_after_documentation(depth)
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "Documented against the wrong eye"

    vial = depth.read_vial(voided["vial_id"])
    assert vial["status"] == "QUARANTINED"
    assert_instant_equals(vial["administered_at"], depth.ENCOUNTER_AT, "administered_at")

    lot = depth.read_lot(depth.lot_ref["id"])
    assert_vial_counters(
        lot,
        vials_on_hand=4,
        vials_reserved=0,
        vials_administered=0,
        vials_quarantined=1,
        vials_returned=0,
        vials_expired=0,
    )
    assert_vial_conservation(lot, 5)


def test_the_plan_and_the_authorization_are_unwound_to_their_pre_injection_state(depth):
    """
    The plan's schedule and the authorization's consumption are both re-derived from
    the surviving encounters, of which there are none.

    The PRD spells the unwind out: "The plan is then unwound: `injections_administered`
    is decremented, and `last_encounter_id`, `current_interval_days` and
    `next_due_date` are all re-derived from the plan's surviving non-`VOIDED`
    encounters taken in ascending `encounter_datetime` order with ascending
    `created_at` breaking ties — that is, the schedule ends up where it would have
    been had the voided injection never been documented. The plan's own `status` is
    left where it stood. Finally the authorization's `injections_used` is recomputed
    with the same `EXHAUSTED → APPROVED` revival."  A plan with no surviving
    encounters is back at the defaults activation left it with, since a successful
    activation "sets `current_interval_days` to 28 — four weeks, the loading cadence",
    "sets `next_due_date` to the logical clock advanced by those 28 days" — so
    2026-08-29 from the suite's 2026-08-01 clock — and at that point
    "`injections_administered` and `consecutive_quiescent_visits` both start at 0".

    Design: Difficulty/compensating_invariant/voiding_a_documented_encounter_conserves_the_lot_vial_count_without_resurrecting_stock
    """
    _voided_after_documentation(depth)

    plan = depth.read_plan(depth.plan1["id"])
    assert plan["status"] == "LOADING"
    assert plan["injections_administered"] == 0
    assert plan["last_encounter_id"] is None
    assert_instant_equals(plan["next_due_date"], "2026-08-29T00:00:00Z", "next_due_date")
    assert plan["current_interval_days"] == 28
    assert plan["consecutive_quiescent_visits"] == 0

    authorization = depth.read_authorization(depth.pa1["id"])
    assert authorization["injections_used"] == 0
    assert authorization["status"] == "APPROVED"


# ==========================================================================
# recall_return_and_credit_reconciliation_close_the_vial_and_money_ledgers_with_no_drift
# ==========================================================================


def _recall_on_the_injected_lot(depth):
    """Document the injection, then open a Class II recall on the lot that supplied it."""
    depth.enc1_documented
    return depth.recall(
        drug_lot_id=depth.lot_ref["id"],
        recall_class="CLASS_II",
        reason="Manufacturer sterility deviation",
    )


def test_the_frozen_expected_credit_caps_what_the_manufacturer_may_be_credited(
    depth, billing
):
    """
    Shipping the return prices the expected credit once from the returned vials, and
    a payment one cent above that ceiling is refused.

    The PRD freezes the figure at the shipment: "Shipping moves every `QUARANTINED`
    vial of the lot to `RETURNED`, recomputes `vials_returned_count`, and **freezes**
    `credit_expected_cents` at `vials_returned_count` multiplied by the lot's
    `unit_acquisition_cost_cents` — frozen at this instant, so nothing that happens
    later re-prices the expected credit."  Four vials at 132000 cents is 528000.  The
    ceiling then binds: "the figure may not exceed `credit_expected_cents`, and a
    larger one is `ERR_CREDIT_EXCEEDS_EXPECTED` (HTTP 422). A short credit is
    accepted, and the difference is simply a loss the practice absorbs."  Sending
    notifications is what unlocks the shipment, moving the recall "`INITIATED →
    PATIENTS_NOTIFIED` and every `PENDING` notification of that recall to `SENT` with
    `sent_at` set to the logical clock".

    Design: Difficulty/compensating_invariant/recall_return_and_credit_reconciliation_close_the_vial_and_money_ledgers_with_no_drift
    """
    recall = _recall_on_the_injected_lot(depth)
    assert recall["credit_expected_cents"] == 0

    notified = depth.send_notifications(recall["id"])
    assert notified["status"] == "PATIENTS_NOTIFIED"

    sent = depth.recall_notifications(recall["id"])
    assert len(sent) == 1
    assert sent[0]["status"] == "SENT"
    assert sent[0]["channel"] == "EMAIL"
    assert_instant_equals(sent[0]["sent_at"], depth.CLOCK, "sent_at")

    shipped = depth.ship_return(recall["id"], carrier_reference="UPS-1Z-99120")
    assert shipped["status"] == "RETURN_SHIPPED"
    assert shipped["carrier_reference"] == "UPS-1Z-99120"
    assert shipped["vials_returned_count"] == 4
    assert shipped["credit_expected_cents"] == 528000

    validate_error(
        depth.api.reconcile_recall_credit(
            recall["id"], f.reconcile_credit_payload(credit_received_cents=528001), billing
        ),
        ApiErrorId.ERR_CREDIT_EXCEEDS_EXPECTED,
        422,
    )
    assert depth.read_recall(recall["id"])["status"] == "RETURN_SHIPPED"

    reconciled = depth.reconcile_credit(recall["id"], credit_received_cents=528000)
    assert reconciled["status"] == "CREDIT_RECONCILED"
    assert reconciled["credit_received_cents"] == 528000
    assert reconciled["credit_expected_cents"] == 528000


def test_acknowledgement_and_a_second_officer_close_the_recall_with_the_ledger_intact(
    depth,
):
    """
    The exposed patient's acknowledgement satisfies the closure guard, a different
    compliance officer closes the recall, and the lot's vials are all accounted for.

    Acknowledgement is the patient's own act: "The patient acknowledges: this is the
    sole endpoint the `Patient` role may write, `acknowledged_at` is set to the
    logical clock, and the parent recall's `notifications_acknowledged` is
    incremented."  Closure then checks both guards: "Every notification must be
    resolved: `notifications_acknowledged` plus `notifications_unreachable` must equal
    `notifications_required` exactly ... And the closer must not be the initiator: an
    acting `X-User-ID` equal to `initiated_by_user_id` is refused with
    `ERR_RECALL_CLOSER_CONFLICT` (HTTP 403). On success `closure_note` is stored and
    `closed_by_user_id` is stamped from the acting identity."  The injected vial never
    joins the return — only "every `QUARANTINED` vial of the lot" ships — and
    `ADMINISTERED` is terminal, so the counters still sum to the five received.

    Design: Difficulty/compensating_invariant/recall_return_and_credit_reconciliation_close_the_vial_and_money_ledgers_with_no_drift
    """
    recall = _recall_on_the_injected_lot(depth)
    depth.send_notifications(recall["id"])
    depth.ship_return(recall["id"], carrier_reference="UPS-1Z-99120")
    depth.reconcile_credit(recall["id"], credit_received_cents=528000)

    notification = depth.recall_notifications(recall["id"])[0]
    acknowledged = depth.acknowledge(notification["id"], patient_id=depth.pt1["id"])
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert_instant_equals(acknowledged["acknowledged_at"], depth.CLOCK, "acknowledged_at")

    resolved = depth.read_recall(recall["id"])
    assert resolved["notifications_required"] == 1
    assert resolved["notifications_acknowledged"] == 1
    assert resolved["notifications_unreachable"] == 0
    assert resolved["initiated_by_user_id"] == COMPLIANCE_USER_ID

    closed = validate_success(
        depth.api.close_lot_recall(
            recall["id"],
            f.recall_close_payload(closure_note="Patient contacted and stock returned"),
            compliance_headers(COMPLIANCE_USER_ID_2),
        ),
        200,
    )
    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == COMPLIANCE_USER_ID_2
    assert closed["closure_note"] == "Patient contacted and stock returned"

    lot = depth.read_lot(depth.lot_ref["id"])
    assert lot["status"] == "RECALLED"
    assert_vial_counters(
        lot,
        vials_returned=4,
        vials_administered=1,
        vials_on_hand=0,
        vials_reserved=0,
        vials_quarantined=0,
        vials_expired=0,
    )
    assert_vial_conservation(lot, 5)

    encounter = depth.read_encounter(depth.enc1["id"])
    assert encounter["status"] == "DOCUMENTED"
    assert depth.read_plan(depth.plan1["id"])["injections_administered"] == 1
