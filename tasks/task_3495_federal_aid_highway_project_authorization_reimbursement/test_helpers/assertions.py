"""Entity assertions and domain invariant checkers (PRD §2.4-§2.6, §2.10, §3).

Two timestamp rendering families are contractual (PRD §2.4):
  * bookkeeping (created_at / updated_at / api_request_timestamp) — ISO 8601
    UTC with EXACTLY three fractional digits, e.g. 2026-09-01T00:00:00.000Z
  * domain clock stamps (comment_period_opened_at, advertised_on_date,
    findings_issued_at, closed_at) — render exactly as the logical clock
    reads at stamping time, e.g. 2026-09-01T00:00:00Z
"""
import re
from typing import Optional

from prd_bench_local_runner.testing import is_valid_uuid

from .constants import (
    ACTIVITY_CODES,
    BASE_FEDERAL_SHARE_BY_CODE,
    FUNDING_PROGRAM_CODES,
    STIP_DURATION_YEARS,
)

_BOOKKEEPING_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_CLOCK_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


# ---------------------------------------------------------------------------
# Timestamp families
# ---------------------------------------------------------------------------
def assert_bookkeeping_timestamp(value: str, field: str = "created_at"):
    """created_at / updated_at must render with exactly 3 fraction digits."""
    assert isinstance(value, str) and _BOOKKEEPING_TS_RE.match(value), (
        f"{field} must be ISO 8601 UTC with exactly three fractional digits, "
        f"got {value!r}"
    )


def assert_clock_timestamp(
    value: str, expected: Optional[str] = None, field: str = "timestamp"
):
    """Domain timestamps render exactly as the logical clock reads; when the
    clock value is known, assert exact string equality."""
    assert isinstance(value, str) and _CLOCK_TS_RE.match(value), (
        f"{field} must be an ISO 8601 UTC clock rendering, got {value!r}"
    )
    if expected is not None:
        assert value == expected, (
            f"{field} must render exactly as the logical clock reads: "
            f"expected {expected!r}, got {value!r}"
        )


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert_bookkeeping_timestamp(data.get("created_at", ""), "created_at")
    assert_bookkeeping_timestamp(data.get("updated_at", ""), "updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def _assert_int_cents(data: dict, field: str, minimum: Optional[int] = None):
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be integer cents, got {value!r}"
    )
    if minimum is not None:
        assert value >= minimum, f"{field} must be >= {minimum}, got {value}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_funding_program(data: dict):
    assert_common_fields(data)
    assert data["code"] in FUNDING_PROGRAM_CODES, f"code: {data.get('code')!r}"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["eligible_activity_codes"], list)
    for code in data["eligible_activity_codes"]:
        assert code in ACTIVITY_CODES, f"ineligible activity code {code!r}"
    assert data["base_federal_share_pct"] == BASE_FEDERAL_SHARE_BY_CODE[data["code"]], (
        f"base_federal_share_pct must be the statutory base for {data['code']}: "
        f"{BASE_FEDERAL_SHARE_BY_CODE[data['code']]}, got {data['base_federal_share_pct']}"
    )


def assert_apportionment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("funding_program_id", "")), "funding_program_id UUID"
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["federal_fiscal_year"], int)
    _assert_int_cents(data, "apportioned_cents", minimum=0)
    _assert_int_cents(data, "obligated_cents")
    _assert_int_cents(data, "available_cents")
    assert_apportionment_invariant(data)


def assert_state_program(data: dict):
    assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert 0 <= data["state_federal_land_pct"] <= 1
    assert isinstance(data["start_federal_fiscal_year"], int)
    assert data["end_federal_fiscal_year"] == (
        data["start_federal_fiscal_year"] + STIP_DURATION_YEARS - 1
    ), (
        f"end_federal_fiscal_year must be start + {STIP_DURATION_YEARS} - 1, got "
        f"{data.get('end_federal_fiscal_year')} for start {data.get('start_federal_fiscal_year')}"
    )
    assert data["status"] in ("PUBLIC_INVOLVEMENT", "SUBMITTED", "APPROVED")
    assert_clock_timestamp(data.get("comment_period_opened_at", ""), field="comment_period_opened_at")
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0
    _assert_int_cents(data, "total_programmed_federal_cents", minimum=0)


def assert_public_comment(data: dict):
    """PublicComment is the single exception to common fields: it carries
    only id and created_at — updated_at and version are ABSENT (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert_bookkeeping_timestamp(data.get("created_at", ""), "created_at")
    assert "updated_at" not in data, "PublicComment must not carry updated_at"
    assert "version" not in data, "PublicComment must not carry version"
    assert is_valid_uuid(data.get("stip_id", "")), "stip_id UUID"
    assert isinstance(data["author_name"], str) and data["author_name"]
    assert isinstance(data["comment_text"], str)


def assert_project(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("stip_id", "")), "stip_id UUID"
    assert is_valid_uuid(data.get("funding_program_id", "")), "funding_program_id UUID"
    assert isinstance(data["route_name"], str) and data["route_name"]
    assert isinstance(data["description"], str)
    assert data["activity_code"] in ACTIVITY_CODES
    assert isinstance(data["is_interstate_system"], bool)
    assert 0 <= data["dbe_goal_pct"] <= 1
    _assert_int_cents(data, "total_estimated_cost_cents", minimum=1)
    assert isinstance(data["provisional_federal_share_pct"], (int, float))
    _assert_int_cents(data, "provisional_federal_estimate_cents", minimum=0)
    assert data["determined_federal_share_pct"] is None or isinstance(
        data["determined_federal_share_pct"], (int, float)
    )
    assert data["status"] in (
        "NOMINATED", "ELIGIBLE", "INELIGIBLE", "AUTHORIZED", "BIDDING",
        "BIDS_OPENED", "UNDER_CONSTRUCTION", "COMPLETE", "CLOSED_OUT",
    )
    assert data["advertised_on_date"] is None or isinstance(
        data["advertised_on_date"], str
    )
    if data["advertised_on_date"] is not None:
        assert_clock_timestamp(data["advertised_on_date"], field="advertised_on_date")
    assert data["awarded_bid_id"] is None or isinstance(data["awarded_bid_id"], str)


def assert_clearance(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id UUID"
    assert data["kind"] in ("ENVIRONMENTAL", "RIGHT_OF_WAY")
    if data["kind"] == "ENVIRONMENTAL":
        assert data["nepa_class"] in ("CE", "EA", "EIS"), (
            f"ENVIRONMENTAL clearance needs nepa_class, got {data.get('nepa_class')!r}"
        )
    else:
        assert data["nepa_class"] is None, (
            f"RIGHT_OF_WAY clearance must have null nepa_class, got {data.get('nepa_class')!r}"
        )
    assert data["status"] in ("SUBMITTED", "CLEARED", "REJECTED")
    assert data["row_cert_level"] is None or data["row_cert_level"] in (
        "LEVEL_1_FULL", "LEVEL_2_CONDITIONAL",
    )
    assert data["decided_by_user_id"] is None or isinstance(
        data["decided_by_user_id"], str
    )


def assert_authorization(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id UUID"
    assert isinstance(data["agreement_number"], str) and data["agreement_number"]
    _assert_int_cents(data, "initial_obligated_cents", minimum=1)
    assert is_valid_uuid(data.get("apportionment_id", "")), "apportionment_id UUID"
    assert isinstance(data["federal_share_pct"], (int, float))
    assert 0 <= data["federal_share_pct"] <= 1
    _assert_int_cents(data, "obligated_cents", minimum=0)
    _assert_int_cents(data, "reimbursed_cents", minimum=0)
    _assert_int_cents(data, "repaid_cents", minimum=0)
    _assert_int_cents(data, "cumulative_change_order_federal_cents", minimum=0)
    assert data["status"] in ("OBLIGATED", "FULLY_DRAWN", "CLOSED")
    assert data["closed_at"] is None or isinstance(data["closed_at"], str)
    if data["closed_at"] is not None:
        assert_clock_timestamp(data["closed_at"], field="closed_at")


def assert_bid(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id UUID"
    assert isinstance(data["contractor_name"], str) and data["contractor_name"]
    _assert_int_cents(data, "bid_amount_cents", minimum=1)
    assert isinstance(data["is_responsive"], bool)
    assert isinstance(data["submission_seq"], int) and data["submission_seq"] >= 0
    assert data["status"] in ("SUBMITTED", "AWARDED", "NOT_AWARDED")


def assert_voucher(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("authorization_id", "")), "authorization_id UUID"
    assert isinstance(data["period_start_date"], str)
    assert isinstance(data["period_end_date"], str)
    assert isinstance(data["line_items"], list) and len(data["line_items"]) >= 1
    for item in data["line_items"]:
        assert isinstance(item["description"], str)
        _assert_int_cents(item, "eligible_amount_cents", minimum=1)
    assert isinstance(data["documentation_complete"], bool)
    assert isinstance(data["is_final"], bool)
    assert data["status"] in ("DRAFT", "UNDER_REVIEW", "APPROVED", "REJECTED")
    _assert_int_cents(data, "claimed_amount_cents", minimum=1)
    assert data["eligible_amount_cents"] is None or isinstance(
        data["eligible_amount_cents"], int
    )
    assert data["federal_reimbursable_cents"] is None or isinstance(
        data["federal_reimbursable_cents"], int
    )
    assert data["ineligible_line_indexes"] is None or isinstance(
        data["ineligible_line_indexes"], list
    )
    assert data["decided_by_user_id"] is None or isinstance(
        data["decided_by_user_id"], str
    )
    assert isinstance(data["resubmission_count"], int) and data["resubmission_count"] >= 0


def assert_change_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("authorization_id", "")), "authorization_id UUID"
    assert isinstance(data["description"], str)
    _assert_int_cents(data, "delta_cost_cents", minimum=1)
    assert isinstance(data["requested_by_user_id"], str)
    assert data["state_concurred_by_user_id"] is None or isinstance(
        data["state_concurred_by_user_id"], str
    )
    assert data["federal_participation_cents"] is None or isinstance(
        data["federal_participation_cents"], int
    )
    assert data["status"] in (
        "REQUESTED", "STATE_CONCURRED", "FEDERAL_APPROVED", "FEDERAL_REJECTED",
    )


def assert_audit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id UUID"
    assert isinstance(data["auditor_user_id"], str)
    assert data["status"] in ("INITIATED", "FINDINGS_ISSUED", "FINAL", "CLOSED")
    assert data["findings_text"] is None or isinstance(data["findings_text"], str)
    assert data["ineligible_amount_cents"] is None or (
        isinstance(data["ineligible_amount_cents"], int)
        and data["ineligible_amount_cents"] >= 0
    )
    assert data["findings_issued_at"] is None or isinstance(
        data["findings_issued_at"], str
    )
    if data["findings_issued_at"] is not None:
        assert_clock_timestamp(data["findings_issued_at"], field="findings_issued_at")
    assert data["final_eligible_federal_share_cents"] is None or isinstance(
        data["final_eligible_federal_share_cents"], int
    )
    assert data["repayment_due_cents"] is None or isinstance(
        data["repayment_due_cents"], int
    )
    _assert_int_cents(data, "repaid_cents", minimum=0)
    assert data["closed_at"] is None or isinstance(data["closed_at"], str)
    if data["closed_at"] is not None:
        assert_clock_timestamp(data["closed_at"], field="closed_at")


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_apportionment_invariant(data: dict):
    """I-APPORTION (PRD §2.10): available == apportioned - obligated always."""
    assert data["available_cents"] == data["apportioned_cents"] - data["obligated_cents"], (
        f"available_cents {data['available_cents']} != apportioned "
        f"{data['apportioned_cents']} - obligated {data['obligated_cents']}"
    )


def assert_closeout_net_share_invariant(authorization: dict, audit: dict):
    """I-NETSHARE (PRD §2.10): at closeout, reimbursed - repaid equals the
    audit's final_eligible_federal_share_cents."""
    net = authorization["reimbursed_cents"] - authorization["repaid_cents"]
    assert net == audit["final_eligible_federal_share_cents"], (
        f"net federal outlay {net} != final_eligible_federal_share_cents "
        f"{audit['final_eligible_federal_share_cents']}"
    )


def assert_version_bumped(before: dict, after: dict, increment: int = 1):
    """Every mutation, cascaded ones included, increments version by 1 and
    refreshes updated_at (PRD §2.5)."""
    assert after["version"] == before["version"] + increment, (
        f"version must increment by {increment}: {before['version']} -> {after['version']}"
    )
