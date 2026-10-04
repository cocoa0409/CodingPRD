"""Compensating invariants: instrument lives restored by a cancellation, and the IDN
committed-procedure pool restored exactly by a transfer reversal."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_case,
    create_transfer_payload,
    get_success_data,
    setup_commissioned_system,
    setup_idn_pair,
    validate_success,
)


def test_booking_a_case_debits_the_accessory_set_by_its_approved_load(api):
    """PRD §2.10: "The remaining lives are the configuration's `max_instrument_lives` minus
    the sum of the approved loads of every procedure case on the agreement's systems whose
    `case_status` is `SCHEDULED` or `COMPLETED`."

    Design: Difficulty/compensating_invariant/instrument_lives_conserved_after_case_cancellation
    """
    ctx = setup_commissioned_system(config_overrides={"max_instrument_lives": 3})
    assert ctx.system["instrument_lives_remaining"] == 3

    create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                case_started_at="2026-09-10T08:00:00Z", duration_minutes=90,
                instrument_load=2)

    after = get_success_data(api_client.get_robot_system(
        ctx.system["id"], TEST_USERS["service_engineer_headers"]))
    assert after["instrument_lives_remaining"] == 1, (
        "the approved load of 2 is debited from the accessory set"
    )


def test_cancelling_the_case_credits_the_exact_loan_back(api):
    """PRD §2.10: "Cancelling a case releases its load back to the accumulator."
    PRD §2.10: "The accumulator is floored at 0 and never goes negative."

    Design: Difficulty/compensating_invariant/instrument_lives_conserved_after_case_cancellation
    """
    ctx = setup_commissioned_system(config_overrides={"max_instrument_lives": 3})
    booked = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                         case_started_at="2026-09-10T08:00:00Z", duration_minutes=90,
                         instrument_load=2)

    cancelled = validate_success(api_client.cancel_procedure_case(
        booked["id"], {"expected_case_version": booked["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)
    assert cancelled["case_status"] == "CANCELLED"

    restored = get_success_data(api_client.get_robot_system(
        ctx.system["id"], TEST_USERS["service_engineer_headers"]))
    assert restored["instrument_lives_remaining"] == 3, (
        "the accumulator returns to its pre-booking value with zero drift"
    )


def _idn_snapshot(ctx):
    source = get_success_data(api_client.get_consumption_ledger(
        ctx.src_ledger["id"], TEST_USERS["idn_coordinator_headers"]))
    destination = get_success_data(api_client.get_consumption_ledger(
        ctx.dst_ledger["id"], TEST_USERS["idn_coordinator_headers"]))
    return source, destination


def test_a_committed_transfer_moves_units_out_of_the_source_ledger(api):
    """PRD §3.8: "On creation the source ledger's supplied units are increased by the
    transferred units and the destination ledger's consumed units are increased by the same
    amount, both ledgers' remaining credit is recomputed, the pool subscription is
    recomputed, and both ledger versions increment."

    Design: Difficulty/compensating_invariant/idn_procedure_unit_pool_conserved_after_transfer_reversal
    """
    ctx = setup_idn_pair(idn_group_code="IDN-BOREAL", commitment=30, region_code="EAST")
    validate_success(api_client.create_transfer(
        create_transfer_payload(ctx.source["id"], ctx.destination["id"], procedure_units=6,
                                transfer_window_start_utc="2026-09-01T00:00:00Z",
                                transfer_window_end_utc="2026-09-15T00:00:00Z"),
        TEST_USERS["idn_coordinator_headers"]), 201)

    source, destination = _idn_snapshot(ctx)
    assert source["supplied_procedure_units"] == 6
    assert source["remaining_credit_units"] == 24, "the source's credit is debited by 6 of 30"
    assert destination["consumed_procedure_units"] == 6
    assert destination["remaining_credit_units"] == 24


def test_reversing_the_transfer_restores_both_ledgers_exactly(api):
    """PRD §3.8: "a reversal moves the transaction to `REVERSED`, subtracts the transferred
    units back out of the source ledger's supplied figure and the destination ledger's
    consumed figure, recomputes both ledgers' remaining credit and the pool subscription, and
    increments the transaction's version and both ledger versions."

    Design: Difficulty/compensating_invariant/idn_procedure_unit_pool_conserved_after_transfer_reversal
    """
    ctx = setup_idn_pair(idn_group_code="IDN-BOREAL", commitment=30, region_code="EAST")
    before_source, before_destination = _idn_snapshot(ctx)
    transfer = validate_success(api_client.create_transfer(
        create_transfer_payload(ctx.source["id"], ctx.destination["id"], procedure_units=6,
                                transfer_window_start_utc="2026-09-01T00:00:00Z",
                                transfer_window_end_utc="2026-09-15T00:00:00Z"),
        TEST_USERS["idn_coordinator_headers"]), 201)

    reversed_txn = validate_success(api_client.reverse_transfer(
        transfer["id"], {"reversal_reason": "Destination site closed its service line."},
        TEST_USERS["idn_coordinator_headers"]), 200)

    assert reversed_txn["transaction_status"] == "REVERSED"
    after_source, after_destination = _idn_snapshot(ctx)
    assert after_source["remaining_credit_units"] == before_source["remaining_credit_units"]
    assert after_source["supplied_procedure_units"] == before_source["supplied_procedure_units"]
    assert after_destination["remaining_credit_units"] == before_destination["remaining_credit_units"]
    assert after_destination["consumed_procedure_units"] == before_destination["consumed_procedure_units"]

    total_before = (before_source["remaining_credit_units"] + before_source["supplied_procedure_units"]
                    + before_destination["remaining_credit_units"]
                    + before_destination["consumed_procedure_units"])
    total_after = (after_source["remaining_credit_units"] + after_source["supplied_procedure_units"]
                   + after_destination["remaining_credit_units"]
                   + after_destination["consumed_procedure_units"])
    assert total_after == total_before, (
        "the conserved pool quantity is identical before the transfer and after the reversal"
    )