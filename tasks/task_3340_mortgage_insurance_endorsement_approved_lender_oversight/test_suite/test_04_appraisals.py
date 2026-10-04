"""Appraisals: delivery, decision, expiry sweep, transfer rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    appraisal_payload,
    attach_appraisal,
    create_case,
    endorse_case,
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
    make_lender_officer_headers,
    make_reviewer_headers,
)


def test_appraisal_creation_computes_expiry_date(api):
    """PRD §3.2: "The system computes `expiry_date` as exactly 120 days after
    `effective_date`, and the appraisal lands in `DELIVERED`."
    PRD §3.2: "the list defaults to empty for a compliant property."

    Design: Corner/entities/appraisal_creation_computes_expiry_date
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "Appraisal Co"})
    case = create_case(lender["id"], borrower_reference="AP-1")
    response = api_client.create_appraisal(
        case["id"],
        appraisal_payload(appraised_value_cents=31_250_000, effective_date="2026-01-01"),
        make_lender_officer_headers(lender["id"]),
    )
    data = validate_success(response, expected_status=201)
    assert data["status"] == "DELIVERED"
    # 2026-01-01 plus 120 days is 2026-05-01.
    assert data["expiry_date"] == "2026-05-01"
    assert data["mps_deficiency_codes"] == []


def test_appraisal_reject_is_terminal(api):
    """PRD §3.2: "accepts or rejects the appraisal — again via a `decision` of `ACCEPT`
    or `REJECT` with an optional `note` — moving it to `ACCEPTED` or `REJECTED`."
    PRD §2.7: "State legality: the target resource is in a state that permits the
    transition (`ERR_INVALID_STATE`, `ERR_CASE_BLOCKED`, `ERR_ALREADY_TERMINAL`)."

    Design: Corner/state_machines/appraisal_reject_is_terminal
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "Appr Reject Co"})
    case = create_case(lender["id"], borrower_reference="AR-1")
    appraisal = attach_appraisal(case["id"], lender["id"], accept=False)
    api_client.decide_appraisal(
        appraisal["id"], {"decision": "REJECT"}, make_reviewer_headers("rev-1")
    )
    response = api_client.decide_appraisal(
        appraisal["id"], {"decision": "ACCEPT"}, make_reviewer_headers("rev-1")
    )
    assert response.status_code == 409
    validate_error_is_one_of(
        response, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE]
    )


def test_appraisal_expiry_sweep_on_clock_advance(api):
    """PRD §2.4: "Advancing the clock fires two time-based sweeps: every `ACCEPTED`
    appraisal whose `expiry_date` is at or before the new logical date becomes
    `EXPIRED`, and every `OPEN` repair escrow whose `end_date` is strictly before the
    new logical date becomes `EXPIRED`."

    Design: Corner/state_machines/appraisal_expiry_sweep_on_clock_advance
    """
    # Start the logical clock early so the sweep-triggering advance moves forward.
    set_clock("2026-01-15T00:00:00Z")
    lender = setup_approved_lender(lender_overrides={"legal_name": "Appr Expire Co"})
    case = create_case(lender["id"], borrower_reference="AE-1")
    appraisal = attach_appraisal(
        case["id"], lender["id"], effective_date="2026-01-01"
    )
    # Advance the clock to exactly the expiry date (2026-05-01): the half-open window
    # excludes it, so the sweep expires the appraisal.
    set_clock("2026-05-01T00:00:00Z")
    data, _meta = validate_paginated(
        api_client.list_appraisals(case["id"], make_admin_headers())
    )
    by_id = {a["id"]: a for a in data}
    assert by_id[appraisal["id"]]["status"] == "EXPIRED"


def test_appraisal_transfer_moves_attachment_and_records_origin(api):
    """PRD §3.2: "A successful transfer records the original case in
    `transferred_from_case_id`, moves the `loan_case_id` attachment to the target, and
    marks the appraisal `TRANSFERRED`."

    Design: Corner/state_machines/appraisal_transfer_moves_attachment_and_records_origin
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "Transfer Co"})
    case_1 = create_case(lender["id"], borrower_reference="T-1")
    case_2 = create_case(
        lender["id"], borrower_reference="T-2",
        base_loan_amount_cents=28_000_000, appraised_value_cents=30_000_000,
    )
    appraisal = attach_appraisal(case_1["id"], lender["id"])
    response = api_client.transfer_appraisal(
        appraisal["id"],
        {"to_loan_case_id": case_2["id"]},
        make_lender_officer_headers(lender["id"]),
    )
    data = validate_success(response)
    assert data["status"] == "TRANSFERRED"
    assert data["loan_case_id"] == case_2["id"]
    assert data["transferred_from_case_id"] == case_1["id"]


def test_endorsement_without_accepted_appraisal(api):
    """PRD §3.2: "Endorsing a case requires the lender to be `APPROVED` and requires an
    appraisal attached to the case in `ACCEPTED` status; without one the decision is
    rejected with `ERR_APPRAISAL_NOT_ACCEPTED`."

    Design: Corner/validations/endorsement_without_accepted_appraisal
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "No Appraisal Co"})
    case = create_case(lender["id"], borrower_reference="NA-1")
    # Appraisal is DELIVERED but never decided.
    attach_appraisal(case["id"], lender["id"], accept=False)
    submit_case(case["id"], lender["id"])
    response = api_client.endorsement_review(
        case["id"], {"decision": "ENDORSE"}, make_reviewer_headers("rev-1")
    )
    validate_error(response, ApiErrorId.ERR_APPRAISAL_NOT_ACCEPTED)


def test_endorsement_with_expired_appraisal(api):
    """PRD §3.2: "The appraisal must also be inside its validity window: endorsement is
    rejected with `ERR_APPRAISAL_EXPIRED` when the current logical date has reached the
    appraisal's `expiry_date`, because the window is the half-open interval from
    `effective_date` up to but not including `expiry_date`."

    Design: Corner/validations/endorsement_with_expired_appraisal
    """
    # The clock is set BEFORE the appraisal is accepted and never advances after, so
    # no expiry sweep fires: the appraisal stays ACCEPTED but is past its expiry_date
    # (2026-01-01 + 120 days = 2026-05-01) at endorsement time.
    set_clock("2026-06-01T00:00:00Z")
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Expired Appraisal Co"}
    )
    case = create_case(lender["id"], borrower_reference="EXP-1")
    attach_appraisal(case["id"], lender["id"], effective_date="2026-01-01")
    submit_case(case["id"], lender["id"])
    response = api_client.endorsement_review(
        case["id"], {"decision": "ENDORSE"}, make_reviewer_headers("rev-1")
    )
    validate_error(response, ApiErrorId.ERR_APPRAISAL_EXPIRED)


def test_transfer_to_case_with_live_appraisal_rejected(api):
    """PRD §3.2: "And the target case must not already hold an appraisal in `DELIVERED`
    or `ACCEPTED` status (`ERR_CASE_ALREADY_HAS_APPRAISAL`)."

    Design: Corner/validations/transfer_to_case_with_live_appraisal_rejected
    """
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Double Appraisal Co"}
    )
    case_1 = create_case(lender["id"], borrower_reference="DA-1")
    case_2 = create_case(
        lender["id"], borrower_reference="DA-2",
        base_loan_amount_cents=28_000_000, appraised_value_cents=30_000_000,
    )
    appraisal = attach_appraisal(case_1["id"], lender["id"])
    # Target case holds a DELIVERED appraisal.
    attach_appraisal(
        case_2["id"], lender["id"], accept=False, appraised_value_cents=30_000_000
    )
    response = api_client.transfer_appraisal(
        appraisal["id"],
        {"to_loan_case_id": case_2["id"]},
        make_lender_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CASE_ALREADY_HAS_APPRAISAL)


def test_error_transfer_window_closed_at_expiry(api):
    """PRD §3.2: "The transfer must occur strictly before `expiry_date` — at or after
    expiry it is rejected with `ERR_TRANSFER_WINDOW_CLOSED`."

    Design: Corner/errors/error_transfer_window_closed_at_expiry
    """
    # At the 2026-09-01 logical clock an appraisal effective 2026-05-04 expires exactly
    # 2026-09-01 (120 days later); no clock advance follows the acceptance, so the
    # appraisal remains ACCEPTED but is at its expiry instant.
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Transfer Closed Co"}
    )
    case_1 = create_case(lender["id"], borrower_reference="TC-1")
    case_2 = create_case(
        lender["id"], borrower_reference="TC-2",
        base_loan_amount_cents=28_000_000, appraised_value_cents=30_000_000,
    )
    appraisal = attach_appraisal(
        case_1["id"], lender["id"], effective_date="2026-05-04"
    )
    response = api_client.transfer_appraisal(
        appraisal["id"],
        {"to_loan_case_id": case_2["id"]},
        make_lender_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TRANSFER_WINDOW_CLOSED)


def test_error_transfer_cross_lender_forbidden(api):
    """PRD §3.2: "The target case must belong to the same lender
    (`ERR_FORBIDDEN_OWNERSHIP`)."

    Design: Corner/errors/error_transfer_cross_lender_forbidden
    """
    lender_a = setup_approved_lender(lender_overrides={"legal_name": "XOwner A"})
    lender_b = setup_approved_lender(lender_overrides={"legal_name": "XOwner B"})
    case_a = create_case(lender_a["id"], borrower_reference="XA-1")
    case_b = create_case(
        lender_b["id"], borrower_reference="XB-1",
        base_loan_amount_cents=28_000_000, appraised_value_cents=30_000_000,
    )
    appraisal = attach_appraisal(case_a["id"], lender_a["id"])
    response = api_client.transfer_appraisal(
        appraisal["id"],
        {"to_loan_case_id": case_b["id"]},
        make_lender_officer_headers(lender_a["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


def test_appraisals_list_reverse_reachable_from_case(api):
    """PRD §4: "| GET | /mi/loan-cases/{loanCaseId}/appraisals | List appraisals
    attached to the case | PlatformAdmin, LenderOfficer, ServicerOfficer, FhaReviewer,
    FhaApprover, ClaimsExaminer |"
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/appraisals_list_reverse_reachable_from_case
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "Appr List Co"})
    case_1 = create_case(lender["id"], borrower_reference="AL-1")
    case_2 = create_case(
        lender["id"], borrower_reference="AL-2",
        base_loan_amount_cents=28_000_000, appraised_value_cents=30_000_000,
    )
    appraisal_1 = attach_appraisal(case_1["id"], lender["id"], accept=False)
    attach_appraisal(
        case_2["id"], lender["id"], accept=False, appraised_value_cents=30_000_000
    )
    data, meta = validate_paginated(
        api_client.list_appraisals(case_1["id"], make_admin_headers())
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == appraisal_1["id"]


def test_lender_officer_cannot_decide_appraisal(api):
    """PRD §2.1: "A request whose role is recognized but not permitted for the endpoint
    — or, on the lender lifecycle endpoint, not permitted for the requested action — is
    rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | /mi/appraisals/{appraisalId}/decide | Accept or reject a
    delivered appraisal | FhaReviewer |"

    Design: Corner/rbac/lender_officer_cannot_decide_appraisal
    """
    lender = setup_approved_lender(lender_overrides={"legal_name": "RBAC Appraisal Co"})
    case = create_case(lender["id"], borrower_reference="RA-1")
    appraisal = attach_appraisal(case["id"], lender["id"], accept=False)
    response = api_client.decide_appraisal(
        appraisal["id"],
        {"decision": "ACCEPT"},
        make_lender_officer_headers(lender["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
