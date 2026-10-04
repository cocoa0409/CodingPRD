"""Entity assertions and PRD-pinned computation helpers.

`assert_<entity>(data)` checks the wire shape of one record: identity,
timestamps, version, and the presence/type of every field the PRD says a
read returns. `assert_common_fields` is the shared base.

The `expected_*` helpers recompute PRD formulas in exact arithmetic so tests
can pin money figures without reimplementing the rounding rules inline. Both
use integer-exact `Fraction` math: the PRD rounds half up to whole cents at
pinned points, and binary floats (e.g. 2499 * 0.8) would misround.
"""

from fractions import Fraction
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    COURIER_SURCHARGE_RATE,
    MEMBER_DISCOUNT_PCT,
    PROVISIONAL_FLAT_RATE,
    TIER1_CAP_CENTS,
    TIER1_RATE,
    TIER2_RATE,
    TIER2_WIDTH_CENTS,
    TIER3_RATE,
)
from .types import (
    ActivityType,
    AssignmentStatus,
    CertificationLevel,
    CoverageType,
    DayOfWeek,
    DisposalMethod,
    ExhibitionStatus,
    ExpenditureStatus,
    FundStatus,
    FundType,
    LoanStatus,
    MemberStatus,
    ObjectStatus,
    PassStatus,
    ProgramStatus,
    ReportKind,
    ReportStatus,
    ResearchStatus,
    ReservationStatus,
    ReviewKind,
    ReviewStatus,
    TicketStatus,
)


def _enum_values(enum_cls) -> List[str]:
    return [member.value for member in enum_cls]


def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.5: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_iso_date(value: Any, field: str) -> None:
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} must be an ISO calendar date (YYYY-MM-DD), got {value!r}"
    )


def _assert_optional_str(data: Dict[str, Any], field: str) -> None:
    assert field in data, f"{field} must be present (null allowed), missing"
    assert data[field] is None or isinstance(data[field], str), (
        f"{field} must be a string or null, got {data[field]!r}"
    )


def _assert_cents(data: Dict[str, Any], field: str, minimum: int = 0) -> None:
    assert isinstance(data.get(field), int) and not isinstance(data[field], bool), (
        f"{field} must be an integer number of cents, got {data.get(field)!r}"
    )
    assert data[field] >= minimum, f"{field} must be >= {minimum}, got {data[field]}"


# ── Per-entity record assertions ─────────────────────────────────────────────
def assert_museum(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("museum_code"), str) and data["museum_code"], "museum_code required"
    assert isinstance(data.get("display_name"), str) and data["display_name"], "display_name required"
    assert isinstance(data.get("requires_timed_pass"), bool), "requires_timed_pass must be bool"
    _assert_cents(data, "quarter_hour_pass_quota", minimum=1)
    _assert_cents(data, "daily_pass_quota", minimum=1)
    _assert_cents(data, "screening_rate_per_quarter_hour", minimum=1)
    assert data["daily_pass_quota"] >= data["quarter_hour_pass_quota"], (
        "daily_pass_quota must be at least quarter_hour_pass_quota"
    )
    closed = data.get("closed_dates")
    assert isinstance(closed, list) and all(isinstance(d, str) for d in closed), (
        f"closed_dates must be a list of ISO date strings, got {closed!r}"
    )
    if "screening_backlog_minutes" in data and data["screening_backlog_minutes"] is not None:
        assert isinstance(data["screening_backlog_minutes"], int), (
            "screening_backlog_minutes, when present, is a whole-minute integer"
        )


def assert_timed_entry_pass(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("museum_id", "")), "museum_id must be a UUID"
    assert isinstance(data.get("visitor_name"), str) and data["visitor_name"], "visitor_name required"
    _assert_optional_str(data, "holder_member_id")
    _assert_iso_date(data.get("visit_date"), "visit_date")
    assert isinstance(data.get("entry_quarter_hour"), int) and 0 <= data["entry_quarter_hour"] <= 29, (
        f"entry_quarter_hour must be an integer slot 0..29, got {data.get('entry_quarter_hour')!r}"
    )
    assert data.get("status") in _enum_values(PassStatus), f"bad pass status {data.get('status')!r}"
    assert "admitted_slot" in data, "admitted_slot must be present (null until ADMITTED)"
    assert data["admitted_slot"] is None or isinstance(data["admitted_slot"], int), (
        "admitted_slot must be an integer slot or null"
    )
    assert isinstance(data.get("created_by_user_id"), str) and data["created_by_user_id"], (
        "created_by_user_id records the creator's X-User-ID"
    )


def assert_member(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"], "full_name required"
    assert isinstance(data.get("email"), str) and "@" in data["email"], "email required"
    assert isinstance(data.get("membership_term_months"), int) and data["membership_term_months"] >= 1, (
        "membership_term_months must be an integer >= 1"
    )
    _assert_iso_date(data.get("expires_on"), "expires_on")
    assert data.get("member_status") in _enum_values(MemberStatus), (
        f"bad member_status {data.get('member_status')!r}"
    )


def assert_special_exhibition(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("museum_id", "")), "museum_id must be a UUID"
    assert is_valid_uuid(data.get("revenue_fund_id", "")), "revenue_fund_id must be a UUID"
    assert isinstance(data.get("title"), str) and data["title"], "title required"
    _assert_cents(data, "fee_cents", minimum=0)
    _assert_cents(data, "daily_ticket_quota", minimum=1)
    assert is_iso8601_timestamp(data.get("member_presale_opens_at", "")), (
        "member_presale_opens_at must be an ISO 8601 UTC datetime"
    )
    assert is_iso8601_timestamp(data.get("public_sale_opens_at", "")), (
        "public_sale_opens_at must be an ISO 8601 UTC datetime"
    )
    assert data.get("status") in _enum_values(ExhibitionStatus), (
        f"bad exhibition status {data.get('status')!r}"
    )


def assert_exhibition_ticket(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("exhibition_id", "")), "exhibition_id must be a UUID"
    _assert_optional_str(data, "member_id")
    assert isinstance(data.get("buyer_name"), str) and data["buyer_name"], "buyer_name required"
    _assert_iso_date(data.get("visit_date"), "visit_date")
    _assert_cents(data, "price_paid_cents", minimum=0)
    assert data.get("status") in _enum_values(TicketStatus), f"bad ticket status {data.get('status')!r}"


def assert_education_program(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("museum_id", "")), "museum_id must be a UUID"
    assert isinstance(data.get("title"), str) and data["title"], "title required"
    assert isinstance(data.get("gallery_code"), str) and data["gallery_code"], "gallery_code required"
    assert data.get("day_of_week") in _enum_values(DayOfWeek), f"bad day_of_week {data.get('day_of_week')!r}"
    assert isinstance(data.get("start_minute"), int) and 0 <= data["start_minute"] <= 1439
    assert isinstance(data.get("end_minute"), int) and 0 <= data["end_minute"] <= 1439
    assert data["end_minute"] > data["start_minute"], "end_minute strictly after start_minute"
    _assert_cents(data, "student_capacity", minimum=1)
    _assert_cents(data, "docent_ratio", minimum=1)
    _assert_cents(data, "max_group_size", minimum=1)
    assert data.get("required_docent_certification") in _enum_values(CertificationLevel), (
        f"bad required_docent_certification {data.get('required_docent_certification')!r}"
    )
    assert data.get("status") in _enum_values(ProgramStatus), f"bad program status {data.get('status')!r}"


def assert_docent(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"], "full_name required"
    assert data.get("certification_level") in _enum_values(CertificationLevel), (
        f"bad certification_level {data.get('certification_level')!r}"
    )
    assert isinstance(data.get("active"), bool), "active must be bool"


def assert_docent_assignment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert is_valid_uuid(data.get("docent_id", "")), "docent_id must be a UUID"
    _assert_iso_date(data.get("service_date"), "service_date")
    assert data.get("status") in _enum_values(AssignmentStatus), (
        f"bad assignment status {data.get('status')!r}"
    )


def assert_school_group_reservation(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("museum_id", "")), "museum_id must be a UUID"
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data.get("school_name"), str) and data["school_name"], "school_name required"
    assert isinstance(data.get("headcount"), int) and data["headcount"] >= 1, "headcount must be >= 1"
    _assert_iso_date(data.get("visit_date"), "visit_date")
    # The stored state is always CONFIRMED or WAITLISTED at creation; CANCELLED
    # is reachable afterwards. REQUESTED never persists (PRD §3.3).
    assert data.get("status") in _enum_values(ReservationStatus), (
        f"bad reservation status {data.get('status')!r}"
    )
    assert isinstance(data.get("created_by_user_id"), str) and data["created_by_user_id"], (
        "created_by_user_id records the organizer's X-User-ID"
    )


def assert_collection_object(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("accession_number"), str) and data["accession_number"], (
        "accession_number required"
    )
    assert isinstance(data.get("title"), str) and data["title"], "title required"
    _assert_cents(data, "declared_value_cents", minimum=0)
    assert isinstance(data.get("is_cultural_property"), bool), "is_cultural_property must be bool"
    assert data.get("status") in _enum_values(ObjectStatus), f"bad object status {data.get('status')!r}"


def assert_loan_agreement(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("object_id", "")), "object_id must be a UUID"
    assert isinstance(data.get("borrower_institution"), str) and data["borrower_institution"], (
        "borrower_institution required"
    )
    _assert_iso_date(data.get("loan_start_date"), "loan_start_date")
    _assert_iso_date(data.get("loan_end_date"), "loan_end_date")
    assert data["loan_end_date"] > data["loan_start_date"], "loan_end_date strictly after start"
    _assert_cents(data, "declared_value_cents", minimum=0)
    assert data.get("coverage_type") in _enum_values(CoverageType), (
        f"bad coverage_type {data.get('coverage_type')!r}"
    )
    assert isinstance(data.get("courier_required"), bool), "courier_required must be bool"
    assert data.get("status") in _enum_values(LoanStatus), f"bad loan status {data.get('status')!r}"
    assert isinstance(data.get("negotiated_round"), int) and data["negotiated_round"] >= 1, (
        "negotiated_round starts at 1 and increments on every counter"
    )
    _assert_cents(data, "premium_cents", minimum=0)


def assert_condition_report(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_id", "")), "loan_id must be a UUID"
    assert data.get("report_kind") in _enum_values(ReportKind), f"bad report_kind {data.get('report_kind')!r}"
    assert isinstance(data.get("condition_summary"), str), "condition_summary required"
    assert isinstance(data.get("damage_noted"), bool), "damage_noted must be bool"
    assert data.get("status") in _enum_values(ReportStatus), f"bad report status {data.get('status')!r}"


def assert_collection_review(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data.get("review_kind") in _enum_values(ReviewKind), f"bad review_kind {data.get('review_kind')!r}"
    _assert_optional_str(data, "object_id")
    _assert_optional_str(data, "fund_id")
    _assert_optional_str(data, "proposed_object_title")
    assert "estimated_cost_cents" in data and (
        data["estimated_cost_cents"] is None or isinstance(data["estimated_cost_cents"], int)
    ), "estimated_cost_cents must be an integer number of cents or null"
    assert "disposal_method" in data and (
        data["disposal_method"] is None or data["disposal_method"] in _enum_values(DisposalMethod)
    ), f"bad disposal_method {data.get('disposal_method')!r}"
    assert isinstance(data.get("cultural_property_review_completed"), bool), (
        "cultural_property_review_completed must be bool"
    )
    assert data.get("status") in _enum_values(ReviewStatus), f"bad review status {data.get('status')!r}"
    _assert_optional_str(data, "submitted_by_user_id")
    _assert_optional_str(data, "decided_by_user_id")


def assert_fund_account(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("fund_code"), str) and data["fund_code"], "fund_code required"
    assert data.get("fund_type") in _enum_values(FundType), f"bad fund_type {data.get('fund_type')!r}"
    _assert_cents(data, "appropriation_cents", minimum=0)
    assert data.get("status") in _enum_values(FundStatus), f"bad fund status {data.get('status')!r}"
    _assert_cents(data, "receipts_cents")
    _assert_cents(data, "settled_available_cents")
    _assert_cents(data, "committed_available_cents")
    assert_fund_invariants(data)


def assert_expenditure(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("fund_id", "")), "fund_id must be a UUID"
    _assert_optional_str(data, "review_id")
    _assert_cents(data, "amount_cents", minimum=1)
    assert data.get("activity_type") in _enum_values(ActivityType), (
        f"bad activity_type {data.get('activity_type')!r}"
    )
    assert isinstance(data.get("memo"), str), "memo required"
    assert data.get("status") in _enum_values(ExpenditureStatus), (
        f"bad expenditure status {data.get('status')!r}"
    )


def assert_research_access_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("object_id", "")), "object_id must be a UUID"
    assert isinstance(data.get("scholar_name"), str) and data["scholar_name"], "scholar_name required"
    assert isinstance(data.get("research_topic"), str), "research_topic required"
    _assert_iso_date(data.get("visit_start_date"), "visit_start_date")
    _assert_iso_date(data.get("visit_end_date"), "visit_end_date")
    assert data["visit_end_date"] >= data["visit_start_date"], (
        "visit_end_date on or after visit_start_date (closed interval)"
    )
    assert data.get("status") in _enum_values(ResearchStatus), (
        f"bad research request status {data.get('status')!r}"
    )
    assert isinstance(data.get("created_by_user_id"), str) and data["created_by_user_id"], (
        "created_by_user_id records the scholar's X-User-ID"
    )


# ── Domain invariants ────────────────────────────────────────────────────────
def assert_fund_invariants(data: Dict[str, Any]) -> None:
    """PRD §2.7: committed = settled minus approved-unexecuted acquisition
    commitments, so committed never exceeds settled; both are integer cents."""
    settled = data.get("settled_available_cents")
    committed = data.get("committed_available_cents")
    if isinstance(settled, int) and isinstance(committed, int):
        assert committed <= settled, (
            f"committed_available_cents ({committed}) must not exceed "
            f"settled_available_cents ({settled})"
        )


def assert_created_at_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    """PRD §2.3: list results are always sorted by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"list not sorted by created_at ascending: {stamps!r}"


# ── PRD-pinned money computations (exact arithmetic) ─────────────────────────
def _as_rate(value: float) -> Fraction:
    """Convert a PRD decimal rate to an exact Fraction via its decimal string."""
    return Fraction(str(value))


def round_half_up(value: Fraction) -> int:
    """Round a non-negative exact value half up to whole cents (PRD §2.7)."""
    assert value >= 0, "money rounding helper expects non-negative values"
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def expected_final_premium_cents(
    declared_value_cents: int,
    coverage_type: str,
    courier_required: bool,
) -> int:
    """PRD §3.4 FINAL premium, in the pinned order that must not be reordered:

    1. tiered base in exact arithmetic (0.6% to 100,000,000; 0.35% on the next
       400,000,000; 0.15% above),
    2. base rounded half up to whole cents — exactly once, here,
    3. courier surcharge of 12% of the ROUNDED base, itself rounded half up,
    4. premium = rounded base + rounded surcharge.

    INDEMNITY coverage always prices at 0 (federal indemnity replaces
    commercial insurance).
    """
    if coverage_type == CoverageType.INDEMNITY.value:
        return 0
    tier1 = Fraction(min(declared_value_cents, TIER1_CAP_CENTS)) * _as_rate(TIER1_RATE)
    tier2 = (
        Fraction(min(max(0, declared_value_cents - TIER1_CAP_CENTS), TIER2_WIDTH_CENTS))
        * _as_rate(TIER2_RATE)
    )
    tier3 = (
        Fraction(max(0, declared_value_cents - TIER1_CAP_CENTS - TIER2_WIDTH_CENTS))
        * _as_rate(TIER3_RATE)
    )
    base_cents = round_half_up(tier1 + tier2 + tier3)
    surcharge = (
        round_half_up(Fraction(base_cents) * _as_rate(COURIER_SURCHARGE_RATE))
        if courier_required
        else 0
    )
    return base_cents + surcharge


def expected_provisional_premium_cents(declared_value_cents: int) -> int:
    """PRD §3.4 PROVISIONAL quote: flat 0.8% of declared value, no tiering, no
    courier surcharge. A documented estimate; never persisted."""
    return round_half_up(Fraction(declared_value_cents) * _as_rate(PROVISIONAL_FLAT_RATE))


def expected_member_price_cents(fee_cents: int, member_active: bool) -> int:
    """PRD §3.2: an ACTIVE member pays fee_cents reduced by twenty percent,
    rounded half up to whole cents per single ticket; anyone else pays full."""
    if not member_active:
        return fee_cents
    return round_half_up(Fraction(fee_cents) * (1 - _as_rate(MEMBER_DISCOUNT_PCT)))


def docents_required_for(headcount: int, docent_ratio: int) -> int:
    """PRD §3.3: docents required are headcount / docent_ratio rounded up."""
    return -(-headcount // docent_ratio)
