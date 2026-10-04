"""The charged-count conservation invariant on a repeated report for the same cell.

Reporting the same order twice on the same billing cell must leave the cell's chargeable
transaction count at one, which the correction row achieves by recording the superseded
count rather than by landing a second charge.
"""
from test_helpers import (
    set_clock,
    create_clinic,
    create_pharmacy,
    add_endpoint,
    certify_participant,
    create_patient,
    setup_signed_prescription,
    route_prescription,
    latest_attempt,
    report_acknowledged,
    reload_attempt,
    reload_prescription,
    post_fee_entry,
    reload_fee_entry,
)


def _one_reported_cell():
    """A CERTIFIED clinic and pharmacy, one order already routed and acknowledged once, and a
    posted fee entry for the resulting sending cell."""
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    for level, sla in (("ELIGIBLE_A", 15), ("ELIGIBLE_B", 30)):
        add_endpoint(
            pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level=level,
            sla_response_minutes=sla, message_standard="NCPDP_SCRIPT_2022011",
        )
    pharmacy = certify_participant(pharmacy["id"])

    patient = create_patient()
    prescription, _ = setup_signed_prescription(clinic["id"], pharmacy["id"], patient["id"])
    route_prescription(prescription["id"], clinic["id"])
    first_attempt = latest_attempt(prescription["id"])
    report_acknowledged(first_attempt["id"])

    cell_entry = post_fee_entry(clinic["id"], transaction_type="NEW_RX", direction="SENT")
    return {
        "clinic": clinic, "pharmacy": pharmacy, "patient": patient,
        "prescription": prescription, "first_attempt": first_attempt, "cell_entry": cell_entry,
    }


def test_a_second_report_on_the_same_cell_carries_a_correction_rather_than_a_second_count(api):
    """PRD §3.7: "When the same cell already holds a non-`IN_PROGRESS` attempt for this
    prescription, so that the new report would double-count, a second row is created alongside
    it: an `entry_type` of `CORRECTION` with `status` `PARTIAL`, carrying `previous_count`
    equal to the cell's chargeable count before this report and `new_count` equal to that count
    plus one."
    PRD §3.7: "The correction row's identifier is returned as the attempt's
    `correction_entry_id`, and it is null on a report that superseded nothing."

    Design: Difficulty/compensating_invariant/attempt_report_correction_preserves_chargeable_transaction_count
    """
    ctx = _one_reported_cell()
    prescription = ctx["prescription"]
    clinic = ctx["clinic"]

    before = reload_fee_entry(ctx["cell_entry"]["id"])
    assert before["transaction_count"] == 1
    assert before["period_net_total_cents"] == before["fee_cents"]

    route_prescription(prescription["id"], clinic["id"])
    second_attempt = latest_attempt(prescription["id"])
    reported = report_acknowledged(second_attempt["id"])

    correction_id = reported["correction_entry_id"]
    assert correction_id is not None

    correction = reload_fee_entry(correction_id)
    assert correction["entry_type"] == "CORRECTION"
    assert correction["previous_count"] == 1
    assert correction["new_count"] == 2
    assert correction["fee_cents"] == 0
    assert before["fee_cents"] == 0


def test_two_attempts_really_exist_while_the_cell_count_stays_conserved(api):
    """PRD §3.7: "The net of the pair is a single count rather than two."
    PRD §3.7: "Reporting an attempt acknowledged creates a `TransactionFeeEntry` for the
    sending cell — the tuple of the prescription's `prescriber_id`, the `month_key`, the
    `transaction_type`, and a `direction` of `SENT` — with `status` `PARTIAL`,
    `transaction_count` of 1, `fee_tier` `FREE`, and `fee_cents` of 0."

    Design: Difficulty/compensating_invariant/attempt_report_correction_preserves_chargeable_transaction_count
    """
    ctx = _one_reported_cell()
    prescription = ctx["prescription"]
    clinic = ctx["clinic"]

    assert ctx["cell_entry"]["transaction_count"] == 1
    assert ctx["cell_entry"]["fee_tier"] == "FREE"
    assert ctx["cell_entry"]["fee_cents"] == 0

    route_prescription(prescription["id"], clinic["id"])
    second_attempt = latest_attempt(prescription["id"])
    report_acknowledged(second_attempt["id"])

    refreshed_prescription = reload_prescription(prescription["id"])
    assert refreshed_prescription["routing_attempt_count"] == 2, (
        "two attempts really were made, which is why the count must be conserved at the "
        "billing cell rather than at the attempt table"
    )

    after = reload_fee_entry(ctx["cell_entry"]["id"])
    assert after["period_net_total_cents"] == 0, (
        "both the accrual and the correction carry fee_cents of zero, so the money side is "
        "untouched"
    )
    first = reload_attempt(ctx["first_attempt"]["id"])
    assert first["outcome"] == "ACKNOWLEDGED"