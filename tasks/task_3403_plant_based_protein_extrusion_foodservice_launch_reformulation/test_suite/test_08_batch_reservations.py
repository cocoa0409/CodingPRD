"""Finished-goods batch reservations: FEFO rotation, one-program-per-batch,
quantity bounds, product match, expiry lockout, and the case-accounting
invariant across reserve and program-terminate release (PRD sections 3.6,
3.7)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_error, validate_success,
    reserve_batch_payload,
    create_active_product_with_label,
    setup_completed_batch, setup_two_batches_staggered_expiry,
    setup_lto_program, reserve_batch_cases, terminate_program,
    set_clock, fetch_batch,
    assert_batch_case_accounting,
)

_CH = TEST_USERS["channel_manager_headers"]


def test_reserves_conserve_case_accounting(api):
    """PRD section 3.7: "Case accounting is invariant throughout a batch's
    life: `quantity_cases` always equals `available_cases` plus
    `reserved_cases` plus `written_off_cases`." Reserving 4 then 6 of a
    10-case batch tracks 10 == 6+4+0 then 10 == 0+10+0 (the bound "the
    requested quantity may not exceed `available_cases`" is inclusive).

    Design: Difficulty/compensating_invariant/ci_batch_reserve_terminate_release
    """
    ctx = setup_completed_batch(channel="FOODSERVICE", actual_quantity_kg=100,
                                product_overrides={
                                    "product_code": "PROD-CI-1"})
    program = setup_lto_program(ctx["product"]["id"], program_code="PROG-CI-1",
                                partner_code="CHAIN-CI", committed_cases=5)
    batch = reserve_batch_cases(ctx["batch"]["id"], program["id"], 4)
    assert batch["available_cases"] == 6
    assert batch["reserved_cases"] == 4
    assert batch["written_off_cases"] == 0
    assert_batch_case_accounting(batch)
    batch = reserve_batch_cases(ctx["batch"]["id"], program["id"], 6)
    assert batch["available_cases"] == 0
    assert batch["reserved_cases"] == 10
    assert_batch_case_accounting(batch)


def test_program_termination_releases_reservations(api):
    """PRD section 3.6: "termination performs a compensating release of
    inventory, returning every batch reserved to the program to availability
    — each such batch's reserved cases flow back into `available_cases`, its
    `reserved_cases` is zeroed, and its `reserved_for_program_id` is
    cleared." Forward reserve plus compensating release conserve the total:
    10 == 10+0+0 afterwards, and the batch derives AVAILABLE again.

    Design: Difficulty/compensating_invariant/ci_batch_reserve_terminate_release
    """
    ctx = setup_completed_batch(channel="FOODSERVICE", actual_quantity_kg=100,
                                product_overrides={
                                    "product_code": "PROD-CI-1"})
    program = setup_lto_program(ctx["product"]["id"], program_code="PROG-CI-1",
                                partner_code="CHAIN-CI", committed_cases=5)
    reserve_batch_cases(ctx["batch"]["id"], program["id"], 4)
    reserve_batch_cases(ctx["batch"]["id"], program["id"], 6)
    terminate_program(program["id"])
    batch = fetch_batch(ctx["batch"]["id"])
    assert batch["available_cases"] == 10
    assert batch["reserved_cases"] == 0
    assert batch["written_off_cases"] == 0
    assert batch["reserved_for_program_id"] is None
    assert batch["derived_status"] == "AVAILABLE"
    assert_batch_case_accounting(batch)


def test_fefo_violation_then_earliest_first(api):
    """PRD section 3.7: "first-expired-first-out forbids skipping a
    same-product, same-channel batch that has a strictly earlier
    `expiry_date` and still has cases available (`ERR_FEFO_VIOLATION`)".
    Reserving the later-expiring batch B2 (expiry 2026-10-18) while B1
    (2026-10-16) still has cases is a 409; once B1 is fully reserved, B2
    reserves cleanly.

    Design: Corner/validations/cn_val_fefo_violation_then_earliest_first
    """
    ctx = setup_two_batches_staggered_expiry()
    program = setup_lto_program(ctx["product"]["id"], program_code="PROG-K-32",
                                partner_code="CHAIN-K32", committed_cases=10)
    b1, b2 = ctx["batch"], ctx["batch2"]
    resp = api.reserve_batch(b2["id"], reserve_batch_payload(program["id"], 5),
                             _CH)
    validate_error(resp, ApiErrorId.ERR_FEFO_VIOLATION)
    reserve_batch_cases(b1["id"], program["id"], 10)
    b2_after = reserve_batch_cases(b2["id"], program["id"], 5)
    assert b2_after["reserved_cases"] == 5
    assert b2_after["reserved_for_program_id"] == program["id"]


def test_batch_reserved_to_other_program_refused(api):
    """PRD section 3.7: "a batch already holding a reservation for a
    different program refuses with `ERR_BATCH_ALREADY_RESERVED`" — once
    PROG-K-A holds 4 cases, reserving to PROG-K-B fails even though
    availability remains.

    Design: Corner/validations/cn_val_batch_already_reserved_other_program
    """
    ctx = setup_completed_batch(channel="FOODSERVICE", actual_quantity_kg=100)
    prog_a = setup_lto_program(ctx["product"]["id"], program_code="PROG-K-A",
                               partner_code="CHAIN-KA", committed_cases=10)
    prog_b = setup_lto_program(ctx["product"]["id"], program_code="PROG-K-B",
                               partner_code="CHAIN-KB", committed_cases=10)
    reserve_batch_cases(ctx["batch"]["id"], prog_a["id"], 4)
    resp = api.reserve_batch(ctx["batch"]["id"],
                             reserve_batch_payload(prog_b["id"], 2), _CH)
    validate_error(resp, ApiErrorId.ERR_BATCH_ALREADY_RESERVED)
    batch = fetch_batch(ctx["batch"]["id"])
    assert batch["reserved_cases"] == 4
    assert batch["reserved_for_program_id"] == prog_a["id"]


def test_reserve_beyond_available_cases_refused(api):
    """PRD section 3.7: "the requested quantity may not exceed
    `available_cases` (`ERR_INSUFFICIENT_AVAILABLE_CASES`)" — 11 of a 10-case
    batch fails.

    Design: Corner/validations/cn_val_insufficient_available_cases
    """
    ctx = setup_completed_batch(channel="FOODSERVICE", actual_quantity_kg=100)
    program = setup_lto_program(ctx["product"]["id"], program_code="PROG-K-33",
                                partner_code="CHAIN-K33", committed_cases=10)
    resp = api.reserve_batch(ctx["batch"]["id"],
                             reserve_batch_payload(program["id"], 11), _CH)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE_CASES)


def test_reserve_into_other_products_program_refused(api):
    """PRD section 3.7: "the program's product must equal the batch's
    (`ERR_PRODUCT_MISMATCH`)" — a batch of product A cannot reserve into
    product B's program.

    Design: Corner/validations/cn_val_reserve_product_mismatch
    """
    ctx = setup_completed_batch(channel="FOODSERVICE", actual_quantity_kg=100)
    product_b, _label_b = create_active_product_with_label(
        {"product_code": "PROD-K-42B"})
    program = setup_lto_program(product_b["id"], program_code="PROG-K-42",
                                partner_code="CHAIN-K42", committed_cases=10)
    resp = api.reserve_batch(ctx["batch"]["id"],
                             reserve_batch_payload(program["id"], 2), _CH)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_MISMATCH)


def test_expired_batch_reads_expired_and_refuses_reserve(api):
    """PRD section 3.7: "`EXPIRED` when the current logical clock has reached
    or passed `expiry_date`" and "The batch must be in a reservable state —
    `EXPIRED`, `WRITTEN_OFF`, and `DEPLETED` batches refuse with
    `ERR_INVALID_STATE`". PRD section 2.4: derived classifications are
    "computed at read time ... no sweep ever writes it", so expiry moves no
    quantity.

    Design: Corner/validations/cn_val_batch_expired_blocks_reserve
    """
    ctx = setup_completed_batch(channel="FOODSERVICE", actual_quantity_kg=100)
    program = setup_lto_program(ctx["product"]["id"], program_code="PROG-K-36",
                                partner_code="CHAIN-K36", committed_cases=10)
    set_clock("2027-06-01T00:00:00Z")
    batch = fetch_batch(ctx["batch"]["id"])
    assert batch["derived_status"] == "EXPIRED"
    assert batch["available_cases"] == 10
    resp = api.reserve_batch(batch["id"],
                             reserve_batch_payload(program["id"], 1), _CH)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
