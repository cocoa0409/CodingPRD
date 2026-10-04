"""Loan case origination: creation gates, underwriting cycle, endorsement."""
import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    assert_timestamp_startswith,
    attach_appraisal,
    create_case,
    create_lender,
    declare_default,
    endorse_case,
    get_case,
    loan_case_payload,
    set_clock,
    setup_approved_lender,
    setup_endorsed_case,
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
    make_reviewer_headers,
    make_servicer_officer_headers,
)


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
def test_loan_case_creation_lands_in_case_number_assigned(api):
    """PRD §3.2: "The new case starts in `CASE_NUMBER_ASSIGNED` with
    `endorsement_integrity` set to `SOUND`."
    PRD §3.3: "The case's `mip_retained_cents` is at all times the sum of `amount_cents`
    over the case's ledger rows whose status is not `CANCELLED`"

    Design: Corner/entities/loan_case_creation_lands_in_case_number_assigned
    """
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Case Origination Co"}
    )
    response = api_client.create_loan_case(
        loan_case_payload(lender["id"], borrower_reference="BRW-001"),
        make_lender_officer_headers(lender["id"]),
    )
    data = validate_success(response, expected_status=201)
    assert data["status"] == "CASE_NUMBER_ASSIGNED"
    assert data["endorsement_integrity"] == "SOUND"
    assert data["mip_cancelled"] is False
    assert data["mip_retained_cents"] == 0


def test_loan_case_creation_rejected_when_lender_not_approved(api):
    """PRD §3.2: "Opening a case against a lender that is not `APPROVED` is rejected
    with `ERR_LENDER_NOT_APPROVED`."

    Design: Corner/entities/loan_case_creation_rejected_when_lender_not_approved
    """
    lender = create_lender(legal_name="Unapproved Co")
    response = api_client.create_loan_case(
        loan_case_payload(lender["id"], borrower_reference="BRW-001"),
        make_lender_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_LENDER_NOT_APPROVED)


def test_loan_case_creation_invalid_refinance_reference_rejected(api):
    """PRD §2.7: "Existence: every id in the path and body references an existing
    resource (`ERR_NOT_FOUND`)."
    PRD §3.2: "the officer supplies `refinance_of_case_id`, which must reference an
    `ENDORSED` case of the same lender; otherwise it is omitted."

    Design: Corner/entities/loan_case_creation_invalid_refinance_reference_rejected
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "Refi Ref Co"})
    response = api_client.create_loan_case(
        loan_case_payload(
            lender["id"],
            borrower_reference="BRW-002",
            refinance_of_case_id=UNKNOWN_UUID,
        ),
        make_lender_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_loan_case_list_filter_by_lender_id(api):
    """PRD §3.2: "Cases can be listed filtered by `lender_id` or by
    `refinance_of_case_id`."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/loan_case_list_filter_by_lender_id
    """
    lender_a = setup_approved_lender(lender_overrides={"legal_name": "List Filter A"})
    lender_b = setup_approved_lender(lender_overrides={"legal_name": "List Filter B"})
    case_a = create_case(lender_a["id"], borrower_reference="A-1")
    create_case(lender_b["id"], borrower_reference="B-1")
    data, meta = validate_paginated(
        api_client.list_loan_cases(
            make_admin_headers(), params={"lender_id": lender_a["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert data[0]["id"] == case_a["id"]


# ---------------------------------------------------------------------------
# Underwriting cycle
# ---------------------------------------------------------------------------
def _setup_submitted_case(api, **case_overrides):
    lender = setup_approved_lender()
    case = create_case(lender["id"], **case_overrides)
    submit_case(case["id"], lender["id"])
    return lender, case


def test_loan_case_flag_deficient_records_codes(api):
    """PRD §3.2: "Alternatively, the reviewer flags the case deficient: the request
    must carry a non-empty `deficiency_codes` list (an empty list is rejected with
    `ERR_VALIDATION`), the codes are recorded on the case, and the case moves to
    `DEFICIENT`."

    Design: Corner/state_machines/loan_case_flag_deficient_records_codes
    """
    lender, case = _setup_submitted_case(api, borrower_reference="DEF-1")
    response = api_client.endorsement_review(
        case["id"],
        {"decision": "FLAG_DEFICIENT", "deficiency_codes": ["INCOME_DOC_STALE"]},
        make_reviewer_headers("rev-1"),
    )
    data = validate_success(response)
    assert data["status"] == "DEFICIENT"
    assert data["deficiency_codes"] == ["INCOME_DOC_STALE"]


def test_loan_case_deficiency_cure_cycle_resubmits(api):
    """PRD §3.2: "Submitting the underwriting package moves a case from
    `CASE_NUMBER_ASSIGNED` to `UNDERWRITE_SUBMITTED`, and the same submission also
    cures a deficiency, moving a case from `DEFICIENT` back to `UNDERWRITE_SUBMITTED`
    — the deficiency cure cycle may repeat."

    Design: Corner/state_machines/loan_case_deficiency_cure_cycle_resubmits
    """
    lender, case = _setup_submitted_case(api, borrower_reference="CURE-1")
    api_client.endorsement_review(
        case["id"],
        {"decision": "FLAG_DEFICIENT", "deficiency_codes": ["APPRAISAL_GAP"]},
        make_reviewer_headers("rev-1"),
    )
    response = api_client.submit_underwriting(
        case["id"], make_lender_officer_headers(lender["id"])
    )
    data = validate_success(response)
    assert data["status"] == "UNDERWRITE_SUBMITTED"


def test_flag_deficient_with_empty_codes_rejected(api):
    """PRD §3.2: "the request must carry a non-empty `deficiency_codes` list (an empty
    list is rejected with `ERR_VALIDATION`)"

    Design: Corner/state_machines/flag_deficient_with_empty_codes_rejected
    """
    lender, case = _setup_submitted_case(api, borrower_reference="EMP-1")
    response = api_client.endorsement_review(
        case["id"],
        {"decision": "FLAG_DEFICIENT", "deficiency_codes": []},
        make_reviewer_headers("rev-1"),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)


# ---------------------------------------------------------------------------
# Default and void transitions
# ---------------------------------------------------------------------------
def test_declare_default_stamps_default_date_from_clock(api):
    """PRD §3.8: "A `ServicerOfficer` declares an endorsed case in default, moving it
    from `ENDORSED` to `IN_DEFAULT` and stamping `default_date` from the logical
    clock."
    PRD §2.4: "Several timestamps elsewhere in the system — `endorsement_date`,
    `default_date`, `closed_at`, `evaluated_at` — are stamped from this same logical
    clock at the moment the triggering action completes."

    Design: Corner/state_machines/declare_default_stamps_default_date_from_clock
    """
    set_clock("2026-03-01T00:00:00Z")
    lender, case = setup_endorsed_case(
        case_overrides={"borrower_reference": "DFT-1"},
        appraisal_overrides={"effective_date": "2026-01-01"},
    )
    response = api_client.declare_default(
        case["id"], make_servicer_officer_headers(lender["id"])
    )
    data = validate_success(response)
    assert data["status"] == "IN_DEFAULT"
    assert_timestamp_startswith(data["default_date"], "2026-03-01T00:00:00", "default_date")


def test_declare_default_from_underwrite_submitted_rejected(api):
    """PRD §3.8: "A `ServicerOfficer` declares an endorsed case in default, moving it
    from `ENDORSED` to `IN_DEFAULT`"
    PRD §2.7: "State legality: the target resource is in a state that permits the
    transition (`ERR_INVALID_STATE`, `ERR_CASE_BLOCKED`, `ERR_ALREADY_TERMINAL`)."

    Design: Corner/state_machines/declare_default_from_underwrite_submitted_rejected
    """
    lender, case = _setup_submitted_case(api, borrower_reference="DFT-2")
    response = api_client.declare_default(
        case["id"], make_servicer_officer_headers(lender["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)


def test_void_endorsement_moves_case_to_voided(api):
    """PRD §3.2: "Voiding moves the case from `ENDORSED` to `VOIDED`, subtracts the
    `base_loan_amount_cents` from the lender's `endorsed_volume_cents`, recomputes the
    net worth requirement, and cancels every premium ledger entry of the case of type
    `ANNUAL` still in `BILLED` status, after which `mip_retained_cents` is recomputed."

    Design: Corner/state_machines/void_endorsement_moves_case_to_voided
    """
    lender, case = setup_endorsed_case(case_overrides={"borrower_reference": "VOID-1"})
    response = api_client.void_endorsement(
        case["id"], {"reason": "duplicate endorsement"}, make_approver_headers("app-1")
    )
    data = validate_success(response)
    assert data["status"] == "VOIDED"


def test_voided_case_is_terminal_lockdown(api):
    """PRD §2.7: "State legality: the target resource is in a state that permits the
    transition (`ERR_INVALID_STATE`, `ERR_CASE_BLOCKED`, `ERR_ALREADY_TERMINAL`)."

    Design: Corner/state_machines/voided_case_is_terminal_lockdown
    """
    lender, case = setup_endorsed_case(case_overrides={"borrower_reference": "VOID-2"})
    api_client.void_endorsement(
        case["id"], {"reason": "duplicate endorsement"}, make_approver_headers("app-1")
    )
    response = api_client.declare_default(
        case["id"], make_servicer_officer_headers(lender["id"])
    )
    assert response.status_code == 409
    validate_error_is_one_of(
        response, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE]
    )


# ---------------------------------------------------------------------------
# Difficulty: loan case deficiency cure cycle
# ---------------------------------------------------------------------------
def _setup_deficient_case(api):
    """Approved lender; case (base 20,000,000 / appraised 24,000,000) submitted then
    flagged DEFICIENT with codes [INCOME_MISCALC]."""
    lender = setup_approved_lender()
    case = create_case(
        lender["id"],
        borrower_reference="CYCLE-1",
        base_loan_amount_cents=20_000_000,
        appraised_value_cents=24_000_000,
    )
    attach_appraisal(
        case["id"], lender["id"],
        appraised_value_cents=24_000_000, effective_date="2026-08-15",
    )
    submit_case(case["id"], lender["id"])
    return lender, case


def test_deficiency_cure_cycle_round_trip(api):
    """PRD §3.2: "the same submission also cures a deficiency, moving a case from
    `DEFICIENT` back to `UNDERWRITE_SUBMITTED` — the deficiency cure cycle may repeat."

    Design: Difficulty/non_linear_state_machine/loan_case_deficiency_cure_cycle
    """
    lender, case = _setup_deficient_case(api)
    deficient = validate_success(
        api_client.endorsement_review(
            case["id"],
            {"decision": "FLAG_DEFICIENT", "deficiency_codes": ["INCOME_MISCALC"]},
            make_reviewer_headers("rev-1"),
        )
    )
    assert deficient["status"] == "DEFICIENT"
    resubmitted = validate_success(
        api_client.submit_underwriting(
            case["id"], make_lender_officer_headers(lender["id"])
        )
    )
    assert resubmitted["status"] == "UNDERWRITE_SUBMITTED"


def test_endorsement_reachable_after_deficiency_cycle(api):
    """PRD §3.2: "On a successful endorsement the system stamps `endorsement_date` from
    the logical clock, records the reviewer in `endorsement_reviewer_id`, computes
    `ltv_bps` as the base loan amount divided by the appraised value and multiplied by
    ten thousand, rounded half-up to an integer, derives `mip_vintage` as `PRE_CUTOFF`
    when the endorsement date is before `2024-01-01T00:00:00Z` and `POST_CUTOFF`
    otherwise"

    Design: Difficulty/non_linear_state_machine/loan_case_deficiency_cure_cycle
    """
    lender, case = _setup_deficient_case(api)
    api_client.endorsement_review(
        case["id"],
        {"decision": "FLAG_DEFICIENT", "deficiency_codes": ["INCOME_MISCALC"]},
        make_reviewer_headers("rev-1"),
    )
    submit_case(case["id"], lender["id"])
    endorsed = validate_success(
        api_client.endorsement_review(
            case["id"], {"decision": "ENDORSE"}, make_reviewer_headers("rev-1")
        )
    )
    assert endorsed["status"] == "ENDORSED"
    # round_half_up(20,000,000 / 24,000,000 * 10,000) == 8,333.
    assert endorsed["ltv_bps"] == 8333
    # Endorsed at the 2026-09-01 logical clock: at/after the 2024-01-01 cutover.
    assert endorsed["mip_vintage"] == "POST_CUTOFF"


# ---------------------------------------------------------------------------
# Difficulty: cross-entity gate — endorsement/create gated by lender approval
# ---------------------------------------------------------------------------
def test_case_create_gated_by_lender_approval(api):
    """PRD §3.2: "Opening a case against a lender that is not `APPROVED` is rejected
    with `ERR_LENDER_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/endorsement_gated_by_lender_approval
    """
    lender = create_lender(legal_name="Never Approved Lending")
    response = api_client.create_loan_case(
        loan_case_payload(lender["id"], borrower_reference="BOR-X"),
        make_lender_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_LENDER_NOT_APPROVED)
    data, meta = validate_paginated(
        api_client.list_loan_cases(
            make_admin_headers(), params={"lender_id": lender["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_endorsement_gated_when_lender_suspended(api):
    """PRD §3.2: "A case that has been driven into `BLOCKED` by a lender suspension
    cannot be endorsed at all — the review is rejected with `ERR_CASE_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/endorsement_gated_by_lender_approval
    """
    lender = setup_approved_lender()
    case = create_case(lender["id"], borrower_reference="BOR-S")
    attach_appraisal(case["id"], lender["id"])
    submit_case(case["id"], lender["id"])
    api_client.lender_status_change(
        lender["id"], {"action": "SUSPEND"}, make_approver_headers("appr-beta")
    )
    assert get_case(case["id"])["status"] == "BLOCKED"
    response = api_client.endorsement_review(
        case["id"], {"decision": "ENDORSE"}, make_reviewer_headers("rev-1")
    )
    validate_error(response, ApiErrorId.ERR_CASE_BLOCKED)
