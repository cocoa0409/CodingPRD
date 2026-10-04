"""Repair escrows: windows, disbursement, freezes, expiry."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_case,
    create_escrow,
    list_escrows,
    set_clock,
    setup_approved_lender,
    submit_case,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.test_users import (
    make_admin_headers,
    make_approver_headers,
    make_lender_officer_headers,
    make_servicer_officer_headers,
)


def _setup_case(api, legal_name="Escrow Co", borrower_reference="ESC-1"):
    lender = setup_approved_lender(lender_overrides={"legal_name": legal_name})
    case = create_case(lender["id"], borrower_reference=borrower_reference)
    return lender, case


def test_escrow_creation_lands_open_with_remaining_equal_to_amount(api):
    """PRD §3.4: "The new escrow opens in `OPEN` status with `remaining_amount_cents`
    equal to the full `amount_cents` and `disbursed_amount_cents` at 0."

    Design: Corner/entities/escrow_creation_lands_open_with_remaining_equal_to_amount
    """
    lender, case = _setup_case(api)
    response = api_client.create_repair_escrow(
        case["id"],
        {"amount_cents": 500_000, "start_date": "2026-01-01", "end_date": "2026-06-30"},
        make_lender_officer_headers(lender["id"]),
    )
    data = validate_success(response)
    assert data["status"] == "OPEN"
    assert data["remaining_amount_cents"] == 500_000
    assert data["disbursed_amount_cents"] == 0
    assert data.get("freeze_origin") is None


def test_escrow_creation_start_after_end_rejected(api):
    """PRD §3.4: "A `start_date` after `end_date` is malformed and rejected with
    `ERR_VALIDATION`."

    Design: Corner/entities/escrow_creation_start_after_end_rejected
    """
    lender, case = _setup_case(api, legal_name="Escrow Window Co", borrower_reference="ESC-2")
    response = api_client.create_repair_escrow(
        case["id"],
        {"amount_cents": 500_000, "start_date": "2026-07-01", "end_date": "2026-06-30"},
        make_lender_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_escrow_disburse_sets_remaining_and_status(api):
    """PRD §3.4: "On success the escrow moves to `DISBURSED`, the released amount is
    recorded in `disbursed_amount_cents`, and `remaining_amount_cents` becomes the
    original amount minus the disbursed amount."

    Design: Corner/state_machines/escrow_disburse_sets_remaining_and_status
    """
    set_clock("2026-01-15T00:00:00Z")
    lender, case = _setup_case(api, legal_name="Disburse Co", borrower_reference="DIS-1")
    escrow = create_escrow(
        case["id"], lender["id"],
        amount_cents=500_000, start_date="2026-01-01", end_date="2026-06-30",
    )
    response = api_client.disburse_escrow(
        escrow["id"],
        {"disbursed_amount_cents": 200_000},
        make_servicer_officer_headers(lender["id"]),
    )
    data = validate_success(response)
    assert data["status"] == "DISBURSED"
    assert data["disbursed_amount_cents"] == 200_000
    assert data["remaining_amount_cents"] == 300_000


def test_escrow_disburse_amount_exceeding_escrow_rejected(api):
    """PRD §3.4: "Disbursement requires the current logical date to be on or before the
    escrow's `end_date` — afterwards the request is rejected with `ERR_ESCROW_EXPIRED`
    — and the amount must not exceed the escrow's `amount_cents` (`ERR_VALIDATION`)."

    Design: Corner/state_machines/escrow_disburse_amount_exceeding_escrow_rejected
    """
    set_clock("2026-01-15T00:00:00Z")
    lender, case = _setup_case(api, legal_name="Overdisburse Co", borrower_reference="DIS-2")
    escrow = create_escrow(
        case["id"], lender["id"],
        amount_cents=500_000, start_date="2026-01-01", end_date="2026-06-30",
    )
    response = api_client.disburse_escrow(
        escrow["id"],
        {"disbursed_amount_cents": 500_001},
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)
    escrows = list_escrows(case["id"])
    assert escrows[0]["status"] == "OPEN"


def test_escrow_expiry_sweep_on_clock_advance(api):
    """PRD §2.4: "Advancing the clock fires two time-based sweeps: every `ACCEPTED`
    appraisal whose `expiry_date` is at or before the new logical date becomes
    `EXPIRED`, and every `OPEN` repair escrow whose `end_date` is strictly before the
    new logical date becomes `EXPIRED`."

    Design: Corner/state_machines/escrow_expiry_sweep_on_clock_advance
    """
    set_clock("2026-01-15T00:00:00Z")
    lender, case = _setup_case(api, legal_name="Escrow Expire Co", borrower_reference="EE-1")
    escrow = create_escrow(
        case["id"], lender["id"],
        amount_cents=500_000, start_date="2026-01-01", end_date="2026-06-30",
    )
    # Advance past end_date (2026-06-30): the sweep expires the OPEN escrow.
    set_clock("2026-07-01T00:00:00Z")
    data, _meta = validate_paginated(
        api_client.list_repair_escrows(case["id"], make_admin_headers())
    )
    by_id = {e["id"]: e for e in data}
    assert by_id[escrow["id"]]["status"] == "EXPIRED"


def test_touching_escrow_windows_rejected(api):
    """PRD §3.4: "The escrow window is a closed interval from `start_date` through
    `end_date` inclusive, and the platform rejects any new escrow whose closed window
    intersects another `OPEN` or `FROZEN` escrow of the same case — intersection
    includes merely touching endpoints, so a new escrow whose `start_date` equals an
    existing escrow's `end_date` overlaps — with `ERR_ESCROW_WINDOW_OVERLAP`."

    Design: Corner/validations/touching_escrow_windows_rejected
    """
    lender, case = _setup_case(api, legal_name="Touch Co", borrower_reference="TCH-1")
    create_escrow(
        case["id"], lender["id"],
        amount_cents=500_000, start_date="2026-01-01", end_date="2026-06-30",
    )
    response = api_client.create_repair_escrow(
        case["id"],
        {"amount_cents": 300_000, "start_date": "2026-06-30", "end_date": "2026-09-30"},
        make_lender_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ESCROW_WINDOW_OVERLAP)


def test_error_escrow_frozen_disburse_rejected(api):
    """PRD §3.4: "Attempting to disburse an escrow that has been frozen is rejected
    with `ERR_ESCROW_FROZEN`."
    PRD §3.6: "every `OPEN` repair escrow of each newly blocked case is frozen with
    `freeze_origin` set to `SUSPENSION`."

    Design: Corner/errors/error_escrow_frozen_disburse_rejected
    """
    set_clock("2026-01-15T00:00:00Z")
    lender, case = _setup_case(api, legal_name="Frozen Co", borrower_reference="FRZ-1")
    escrow = create_escrow(
        case["id"], lender["id"],
        amount_cents=500_000, start_date="2026-01-01", end_date="2026-06-30",
    )
    submit_case(case["id"], lender["id"])
    api_client.lender_status_change(
        lender["id"], {"action": "SUSPEND"}, make_approver_headers("app-1")
    )
    response = api_client.disburse_escrow(
        escrow["id"],
        {"disbursed_amount_cents": 100_000},
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ESCROW_FROZEN)
    escrows = list_escrows(case["id"])
    assert escrows[0]["freeze_origin"] == "SUSPENSION"


def test_error_escrow_expired_disburse_rejected(api):
    """PRD §3.4: "Disbursement requires the current logical date to be on or before the
    escrow's `end_date` — afterwards the request is rejected with `ERR_ESCROW_EXPIRED`"

    Design: Corner/errors/error_escrow_expired_disburse_rejected
    """
    # At the 2026-09-01 startup clock the window [2026-01-01, 2026-06-30] is already
    # past; the clock never advances, so no sweep fires and the escrow stays OPEN —
    # only the temporal disbursement gate can fire.
    lender, case = _setup_case(api, legal_name="Late Disburse Co", borrower_reference="LD-1")
    escrow = create_escrow(
        case["id"], lender["id"],
        amount_cents=500_000, start_date="2026-01-01", end_date="2026-06-30",
    )
    response = api_client.disburse_escrow(
        escrow["id"],
        {"disbursed_amount_cents": 100_000},
        make_servicer_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ESCROW_EXPIRED)


def test_disburse_on_terminal_disbursed_rejected(api):
    """PRD §3.4: "On success the escrow moves to `DISBURSED`, the released amount is
    recorded in `disbursed_amount_cents`"
    PRD §2.7: "State legality: the target resource is in a state that permits the
    transition (`ERR_INVALID_STATE`, `ERR_CASE_BLOCKED`, `ERR_ALREADY_TERMINAL`)."

    Design: Corner/errors/disburse_on_terminal_disbursed_rejected
    """
    set_clock("2026-01-15T00:00:00Z")
    lender, case = _setup_case(api, legal_name="Twice Disburse Co", borrower_reference="TD-1")
    escrow = create_escrow(
        case["id"], lender["id"],
        amount_cents=500_000, start_date="2026-01-01", end_date="2026-06-30",
    )
    api_client.disburse_escrow(
        escrow["id"],
        {"disbursed_amount_cents": 200_000},
        make_servicer_officer_headers(lender["id"]),
    )
    response = api_client.disburse_escrow(
        escrow["id"],
        {"disbursed_amount_cents": 100_000},
        make_servicer_officer_headers(lender["id"]),
    )
    assert response.status_code == 409
    validate_error_is_one_of(
        response, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE]
    )
