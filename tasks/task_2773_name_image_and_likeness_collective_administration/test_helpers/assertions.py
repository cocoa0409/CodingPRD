"""Domain assertion helpers for the NIL Collective Administration API.

Each helper groups the field checks that the PRD states together, so a failure
message names the rule rather than a bare inequality. Nothing here recomputes a
business figure: expected values are always passed in by the caller.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .api_client import canonicalize_timestamp

# --- Envelope and system fields (PRD s2.2, s2.4) -------------------------


def assert_error_envelope_shape(response) -> Dict[str, Any]:
    """An error body carries exactly the envelope of PRD s2.2."""
    body = response.json()
    assert set(body.keys()) == {"meta", "response_type", "data"}, (
        f"Error envelope must carry exactly meta, response_type and data: {body.keys()}"
    )
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "An error response's meta carries only api_request_id and api_request_timestamp"
    )
    assert set(body["data"].keys()) == {"error_id", "message"}
    return body["data"]


def assert_request_meta(response) -> Dict[str, Any]:
    """``api_request_id`` starts with ``req_`` and the timestamp is ISO 8601 UTC."""
    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_: {meta['api_request_id']}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp must be ISO 8601: {meta['api_request_timestamp']}"
    )
    return meta


def assert_system_fields(data: Dict[str, Any], expect_version: bool = True) -> None:
    """A UUID ``id``, an ISO ``created_at``, and for most entities ``updated_at``/``version``."""
    assert is_valid_uuid(data["id"]), f"id must be a UUID with no prefix: {data['id']}"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601: {data['created_at']}"
    )
    if expect_version:
        assert is_iso8601_timestamp(data["updated_at"]), (
            f"updated_at must be ISO 8601: {data['updated_at']}"
        )
        assert isinstance(data["version"], int) and data["version"] >= 1


def assert_append_only_shape(data: Dict[str, Any]) -> None:
    """A communication record has no ``updated_at`` and no ``version`` (PRD s2.4)."""
    assert is_valid_uuid(data["id"])
    assert "updated_at" not in data, "A communication record carries no updated_at"
    assert "version" not in data, "A communication record carries no version"


def assert_timestamp_equals(actual: Optional[str], expected: Optional[str]) -> None:
    """Compare two instants after canonicalising the sub-second field."""
    if expected is None:
        assert actual is None, f"Expected a null timestamp, got {actual}"
        return
    assert actual is not None, f"Expected {expected}, got null"
    assert canonicalize_timestamp(actual) == canonicalize_timestamp(expected), (
        f"Expected instant {expected}, got {actual}"
    )


# --- Pagination and ordering (PRD s2.3) ---------------------------------


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    assert meta["limit"] == limit, f"meta.limit expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"meta.offset expected {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"meta.total_count counts filter matches before paging: expected {total_count}, "
        f"got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more expected {has_more}, got {meta['has_more']}"
    )


def assert_sequence_no_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    """List order is ascending ``sequence_no`` for every list endpoint (PRD s2.3)."""
    numbers = [row["sequence_no"] for row in rows]
    assert numbers == sorted(numbers), f"Rows must be ordered by ascending sequence_no: {numbers}"


# --- Collective ledger (PRD s2.10) --------------------------------------


def assert_collective_ledger(
    data: Dict[str, Any],
    settled_net_funds_cents: Optional[int] = None,
    committed_unreleased_cents: Optional[int] = None,
    released_total_cents: Optional[int] = None,
    reversed_total_cents: Optional[int] = None,
    funding_posture: Optional[str] = None,
) -> None:
    if settled_net_funds_cents is not None:
        assert data["settled_net_funds_cents"] == settled_net_funds_cents, (
            f"settled_net_funds_cents expected {settled_net_funds_cents}, "
            f"got {data['settled_net_funds_cents']}"
        )
    if committed_unreleased_cents is not None:
        assert data["committed_unreleased_cents"] == committed_unreleased_cents, (
            f"committed_unreleased_cents expected {committed_unreleased_cents}, "
            f"got {data['committed_unreleased_cents']}"
        )
    if released_total_cents is not None:
        assert data["released_total_cents"] == released_total_cents, (
            f"released_total_cents expected {released_total_cents}, "
            f"got {data['released_total_cents']}"
        )
    if reversed_total_cents is not None:
        assert data["reversed_total_cents"] == reversed_total_cents, (
            f"reversed_total_cents expected {reversed_total_cents}, "
            f"got {data['reversed_total_cents']}"
        )
    if funding_posture is not None:
        assert data["funding_posture"] == funding_posture, (
            f"funding_posture expected {funding_posture}, got {data['funding_posture']}"
        )


# --- Contribution money (PRD s3.5, s3.6) --------------------------------


def assert_contribution_money(
    data: Dict[str, Any],
    gross_amount_cents: Optional[int] = None,
    processing_fee_cents: Optional[int] = None,
    net_amount_cents: Optional[int] = None,
    deductible_amount_cents: Optional[int] = None,
    deduction_variant: Optional[str] = None,
    status: Optional[str] = None,
) -> None:
    if gross_amount_cents is not None:
        assert data["gross_amount_cents"] == gross_amount_cents
    if processing_fee_cents is not None:
        assert data["processing_fee_cents"] == processing_fee_cents, (
            f"processing_fee_cents expected {processing_fee_cents}, "
            f"got {data['processing_fee_cents']}"
        )
    if net_amount_cents is not None:
        assert data["net_amount_cents"] == net_amount_cents, (
            f"net_amount_cents expected {net_amount_cents}, got {data['net_amount_cents']}"
        )
    if deductible_amount_cents is not None:
        assert data["deductible_amount_cents"] == deductible_amount_cents, (
            f"deductible_amount_cents expected {deductible_amount_cents}, "
            f"got {data['deductible_amount_cents']}"
        )
    if deduction_variant is not None:
        assert data["deduction_variant"] == deduction_variant
    if status is not None:
        assert data["status"] == status


def assert_donor_ledger(
    data: Dict[str, Any],
    lifetime_settled_cents: Optional[int] = None,
    lifetime_deductible_cents: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    if lifetime_settled_cents is not None:
        assert data["lifetime_settled_cents"] == lifetime_settled_cents, (
            f"lifetime_settled_cents expected {lifetime_settled_cents}, "
            f"got {data['lifetime_settled_cents']}"
        )
    if lifetime_deductible_cents is not None:
        assert data["lifetime_deductible_cents"] == lifetime_deductible_cents, (
            f"lifetime_deductible_cents expected {lifetime_deductible_cents}, "
            f"got {data['lifetime_deductible_cents']}"
        )
    if status is not None:
        assert data["status"] == status


# --- Contract dimensions (PRD s3.8) -------------------------------------


def assert_contract_dimensions(
    data: Dict[str, Any],
    lifecycle_status: Optional[str] = None,
    payment_status: Optional[str] = None,
    disclosure_status: Optional[str] = None,
) -> None:
    """The three independent dimensions carried on the same contract row."""
    if lifecycle_status is not None:
        assert data["lifecycle_status"] == lifecycle_status, (
            f"lifecycle_status expected {lifecycle_status}, got {data['lifecycle_status']}"
        )
    if payment_status is not None:
        assert data["payment_status"] == payment_status, (
            f"payment_status expected {payment_status}, got {data['payment_status']}"
        )
    if disclosure_status is not None:
        assert data["disclosure_status"] == disclosure_status, (
            f"disclosure_status expected {disclosure_status}, got {data['disclosure_status']}"
        )


def assert_contract_money(
    data: Dict[str, Any],
    total_value_cents: Optional[int] = None,
    released_total_cents: Optional[int] = None,
    deliverable_value_total_cents: Optional[int] = None,
    clawback_amount_cents: Optional[int] = None,
    termination_reason: Optional[str] = None,
) -> None:
    if total_value_cents is not None:
        assert data["total_value_cents"] == total_value_cents
    if released_total_cents is not None:
        assert data["released_total_cents"] == released_total_cents, (
            f"released_total_cents expected {released_total_cents}, "
            f"got {data['released_total_cents']}"
        )
    if deliverable_value_total_cents is not None:
        assert data["deliverable_value_total_cents"] == deliverable_value_total_cents, (
            f"deliverable_value_total_cents expected {deliverable_value_total_cents}, "
            f"got {data['deliverable_value_total_cents']}"
        )
    if clawback_amount_cents is not None:
        assert data["clawback_amount_cents"] == clawback_amount_cents, (
            f"clawback_amount_cents expected {clawback_amount_cents}, "
            f"got {data['clawback_amount_cents']}"
        )
    if termination_reason is not None:
        assert data["termination_reason"] == termination_reason


# --- Deliverable scoring (PRD s3.9) -------------------------------------


def assert_deliverable_scoring(
    data: Dict[str, Any],
    status: Optional[str] = None,
    payout_basis: Optional[str] = None,
    payout_eligible_cents: Optional[int] = None,
    late_flag: Optional[bool] = None,
    submission_count: Optional[int] = None,
    evidence_count: Optional[int] = None,
    verified_by_user_id: Optional[str] = None,
) -> None:
    if status is not None:
        assert data["status"] == status, f"status expected {status}, got {data['status']}"
    if payout_basis is not None:
        assert data["payout_basis"] == payout_basis, (
            f"payout_basis expected {payout_basis}, got {data['payout_basis']}"
        )
    if payout_eligible_cents is not None:
        assert data["payout_eligible_cents"] == payout_eligible_cents, (
            f"payout_eligible_cents expected {payout_eligible_cents}, "
            f"got {data['payout_eligible_cents']}"
        )
    if late_flag is not None:
        assert data["late_flag"] is late_flag, (
            f"late_flag expected {late_flag}, got {data['late_flag']}"
        )
    if submission_count is not None:
        assert data["submission_count"] == submission_count, (
            f"submission_count expected {submission_count}, got {data['submission_count']}"
        )
    if evidence_count is not None:
        assert data["evidence_count"] == evidence_count, (
            f"evidence_count expected {evidence_count}, got {data['evidence_count']}"
        )
    if verified_by_user_id is not None:
        assert data["verified_by_user_id"] == verified_by_user_id, (
            f"verified_by_user_id expected {verified_by_user_id}, "
            f"got {data['verified_by_user_id']}"
        )


# --- Payment release and withholding (PRD s3.9) -------------------------


def assert_release_money(
    data: Dict[str, Any],
    status: Optional[str] = None,
    requested_amount_cents: Optional[int] = None,
    withholding_basis: Optional[str] = None,
    withholding_amount_cents: Optional[int] = None,
    net_payable_cents: Optional[int] = None,
    reversal_reason: Optional[str] = None,
    initiated_by_user_id: Optional[str] = None,
) -> None:
    if status is not None:
        assert data["status"] == status, f"release status expected {status}, got {data['status']}"
    if requested_amount_cents is not None:
        assert data["requested_amount_cents"] == requested_amount_cents
    if withholding_basis is not None:
        assert data["withholding_basis"] == withholding_basis, (
            f"withholding_basis expected {withholding_basis}, got {data['withholding_basis']}"
        )
    if withholding_amount_cents is not None:
        assert data["withholding_amount_cents"] == withholding_amount_cents, (
            f"withholding_amount_cents expected {withholding_amount_cents}, "
            f"got {data['withholding_amount_cents']}"
        )
    if net_payable_cents is not None:
        assert data["net_payable_cents"] == net_payable_cents, (
            f"net_payable_cents expected {net_payable_cents}, got {data['net_payable_cents']}"
        )
    if reversal_reason is not None:
        assert data["reversal_reason"] == reversal_reason
    if initiated_by_user_id is not None:
        assert data["initiated_by_user_id"] == initiated_by_user_id


# --- Athlete ledgers (PRD s3.7) -----------------------------------------


def assert_athlete_tax_ledger(
    data: Dict[str, Any],
    tax_year_gross_paid_cents: Optional[int] = None,
    tax_year_withheld_cents: Optional[int] = None,
    tax_form_required: Optional[str] = None,
    annual_committed_value_cents: Optional[int] = None,
    eligibility_status: Optional[str] = None,
) -> None:
    if tax_year_gross_paid_cents is not None:
        assert data["tax_year_gross_paid_cents"] == tax_year_gross_paid_cents, (
            f"tax_year_gross_paid_cents expected {tax_year_gross_paid_cents}, "
            f"got {data['tax_year_gross_paid_cents']}"
        )
    if tax_year_withheld_cents is not None:
        assert data["tax_year_withheld_cents"] == tax_year_withheld_cents, (
            f"tax_year_withheld_cents expected {tax_year_withheld_cents}, "
            f"got {data['tax_year_withheld_cents']}"
        )
    if tax_form_required is not None:
        assert data["tax_form_required"] == tax_form_required, (
            f"tax_form_required expected {tax_form_required}, got {data['tax_form_required']}"
        )
    if annual_committed_value_cents is not None:
        assert data["annual_committed_value_cents"] == annual_committed_value_cents, (
            f"annual_committed_value_cents expected {annual_committed_value_cents}, "
            f"got {data['annual_committed_value_cents']}"
        )
    if eligibility_status is not None:
        assert data["eligibility_status"] == eligibility_status


# --- Small readers used by many tests -----------------------------------


def read_data(response, expected_status: int = 200) -> Dict[str, Any]:
    """``validate_success`` plus the envelope checks of PRD s2.2."""
    data = validate_success(response, expected_status=expected_status)
    assert_request_meta(response)
    return data


def rows_of(response) -> List[Dict[str, Any]]:
    """The ``data`` array of a list response."""
    return response.json()["data"]
