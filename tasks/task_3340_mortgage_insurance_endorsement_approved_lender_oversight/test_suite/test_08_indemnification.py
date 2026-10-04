"""Indemnification agreements: drafting, execution, recoveries, payment gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    draft_agreement,
    execute_agreement,
    exhaust_waterfall,
    file_claim,
    setup_case_with_confirmed_tier1_defect,
    setup_case_with_executed_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.test_users import (
    make_admin_headers,
    make_examiner_headers,
    make_lender_officer_headers,
)


def test_indemnification_agreements_list_reverse_reachable_from_case(api):
    """PRD §3.7: "A drafted agreement starts in `DRAFT` with `recovered_total_cents` at
    0 and the drafter recorded in `created_by_user_id`."
    PRD §4: "| GET | /mi/loan-cases/{loanCaseId}/indemnification-agreements | List
    indemnification agreements of the case | PlatformAdmin, LenderOfficer,
    ServicerOfficer, FhaReviewer, FhaApprover, ClaimsExaminer |"

    Design: Corner/endpoints/indemnification_agreements_list_reverse_reachable_from_case
    """
    lender, case, _review, _defect = setup_case_with_confirmed_tier1_defect()
    agreement = draft_agreement(case["id"], coverage_cap_cents=1_000_000)
    data, meta = validate_paginated(
        api_client.list_indemnification_agreements(case["id"], make_admin_headers())
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == agreement["id"]
    assert data[0]["status"] == "DRAFT"
    assert data[0]["recovered_total_cents"] == 0


def test_execute_indemnification_by_non_owner_forbidden(api):
    """PRD §3.7: "Execution belongs to the `LenderOfficer` of the lender that owns the
    case; an officer of any other lender is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/errors/execute_indemnification_by_non_owner_forbidden
    """
    _lender, case, _review, _defect = setup_case_with_confirmed_tier1_defect()
    agreement = draft_agreement(case["id"], coverage_cap_cents=1_000_000)
    response = api_client.execute_indemnification(
        agreement["id"], make_lender_officer_headers(UNKNOWN_UUID)
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    data, _meta = validate_paginated(
        api_client.list_indemnification_agreements(case["id"], make_admin_headers())
    )
    assert data[0]["status"] == "DRAFT"


def test_record_recovery_satisfies_at_cap(api):
    """PRD §3.7: "Recoveries are recorded by a `ClaimsExaminer` against an executed
    agreement, each carrying a `recovery_amount_cents`. The amount is added to
    `recovered_total_cents`, and the moment the cumulative recovered total reaches or
    exceeds the `coverage_cap_cents` the agreement moves from `EXECUTED` to
    `SATISFIED`, its terminal state."

    Design: Corner/errors/record_recovery_satisfies_at_cap
    """
    _lender, _case, agreement = setup_case_with_executed_agreement()
    first = validate_success(
        api_client.record_recovery(
            agreement["id"], {"recovery_amount_cents": 600_000},
            make_examiner_headers("cx-1"),
        )
    )
    assert first["status"] == "EXECUTED"
    assert first["recovered_total_cents"] == 600_000
    # Reaching the cap exactly satisfies the agreement.
    second = validate_success(
        api_client.record_recovery(
            agreement["id"], {"recovery_amount_cents": 400_000},
            make_examiner_headers("cx-1"),
        )
    )
    assert second["status"] == "SATISFIED"
    assert second["recovered_total_cents"] == 1_000_000


def test_error_indemnification_blocks_payment(api):
    """PRD §3.7: "Thereafter a claims examiner cannot pay any claim on that case while
    an `EXECUTED` or `SATISFIED` agreement covers it — the payment decision is rejected
    with `ERR_INDEMNIFICATION_BLOCKS_PAYMENT`."

    Design: Corner/errors/error_indemnification_blocks_payment
    """
    # Agreement executed before any claim is filed.
    lender, case, _agreement = setup_case_with_executed_agreement()
    exhaust_waterfall(case["id"], lender["id"])
    claim = file_claim(case["id"], lender["id"])
    response = api_client.decide_claim(
        claim["id"], {"decision": "PAY"}, make_examiner_headers("cx-1")
    )
    validate_error(response, ApiErrorId.ERR_INDEMNIFICATION_BLOCKS_PAYMENT)
    data, _meta = validate_paginated(
        api_client.list_claims(case["id"], make_admin_headers())
    )
    assert data[0]["status"] == "UNDER_REVIEW"
