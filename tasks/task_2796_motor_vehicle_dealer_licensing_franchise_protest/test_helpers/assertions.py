"""Entity assertions and domain invariant checkers."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

DEALER_LICENSE_STATUSES = [
    "PROSPECTIVE", "LICENSED", "SUSPENDED", "EXPIRED", "REVOKED", "CANCELLED",
]
DEALER_FRANCHISE_STATUSES = ["NONE", "FRANCHISED", "TERMINATION_PENDING", "TERMINATED"]
SUSPENSION_REASONS = ["NONE", "DISCIPLINARY_POINTS", "RESTITUTION_DELINQUENT"]
APPLICATION_STATUSES = [
    "DRAFT", "SUBMITTED", "DEFICIENT", "APPROVED", "DENIED", "VOID_SPONSOR_CANCELLED",
]
SALESPERSON_LICENSE_STATUSES = [
    "PENDING", "LICENSED", "RENEWAL_PENDING", "DENIED", "SUSPENDED_BY_SPONSOR", "EXPIRED",
]
DISCIPLINE_STATUSES = ["CLEAR", "PROBATION", "SUSPENDED_DISCIPLINARY", "REINSTATED"]
FILING_STATUSES = [
    "DRAFT", "NOTICE_SERVED", "PROTEST_PENDING", "PROTEST_RESOLVED", "EFFECTIVE", "BARRED",
]
PROTEST_STATUSES = [
    "FILED", "SCHEDULED", "HEARD", "SUSTAINED", "DENIED", "APPEALED", "FINAL",
    "WITHDRAWN", "DISMISSED",
]
DISPUTE_STATUSES = ["FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "DISMISSED_MOOT"]
COMPLAINT_STATUSES = [
    "RECEIVED", "UNDER_INVESTIGATION", "SANCTIONED", "CLOSED_SATISFIED",
    "CLOSED_UNSUBSTANTIATED",
]
DEFICIENCY_CODES = [
    "FACILITY_TOO_SMALL", "DISPLAY_SPACES_INSUFFICIENT", "SERVICE_BAYS_INSUFFICIENT",
    "BOND_INSUFFICIENT", "INSURANCE_INSUFFICIENT", "ZONING_NOT_APPROVED",
]


def assert_record_identity(data: dict) -> None:
    """Every persisted record carries a server-minted UUID `id` with no type
    prefix and an ISO 8601 UTC `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert not str(data.get("id", "")).startswith(("dlr", "mfr", "id_")), \
        "id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"


def assert_versioned_record(data: dict) -> None:
    """Records other than the two evidence logs also carry `updated_at` and an
    integer `version`."""
    assert_record_identity(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"


def assert_append_only_record(data: dict) -> None:
    """A market study and an evidence submission expose only `id` and
    `created_at`: both `updated_at` and `version` are absent entirely."""
    assert_record_identity(data)
    assert "updated_at" not in data, "an append-only evidence row must not carry updated_at"
    assert "version" not in data, "an append-only evidence row must not carry version"


def assert_manufacturer(data: dict) -> None:
    assert_versioned_record(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["line_make"].isupper() and 2 <= len(data["line_make"]) <= 20
    assert len(data["home_office_state"]) == 2 and data["home_office_state"].isupper()
    assert 1000 <= data["posted_warranty_labor_rate_cents"] <= 100000
    assert data["state_registration_status"] in ["REGISTERED", "LAPSED"]
    assert isinstance(data["open_dispute_count"], int) and data["open_dispute_count"] >= 0
    assert isinstance(data["active_filing_count"], int) and data["active_filing_count"] >= 0


def assert_hearing_room(data: dict) -> None:
    assert_versioned_record(data)
    assert 2 <= len(data["room_code"]) <= 12
    assert 10 <= data["seating_capacity"] <= 400
    assert 1 <= data["max_hearings_per_day"] <= 4
    assert 0 <= data["buffer_minutes"] <= 240
    assert isinstance(data["booked_hearing_count"], int) and data["booked_hearing_count"] >= 0


def assert_dealer(data: dict) -> None:
    assert_versioned_record(data)
    assert data["dealer_type"] in ["NEW_MOTOR_VEHICLE", "USED_ONLY"]
    assert data["county_tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    assert -500 <= data["site_x_km"] <= 500
    assert -500 <= data["site_y_km"] <= 500
    assert data["license_status"] in DEALER_LICENSE_STATUSES
    assert data["franchise_status"] in DEALER_FRANCHISE_STATUSES
    assert data["suspension_reason"] in SUSPENSION_REASONS
    if data["license_status"] != "SUSPENDED":
        assert data["suspension_reason"] == "NONE", \
            "suspension_reason is NONE whenever license_status is not SUSPENDED"
    assert data["disciplinary_points"] >= 0
    assert data["restitution_outstanding_cents"] >= 0
    assert data["licensed_salesperson_count"] >= 0


def assert_license_application(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["dealer_id"])
    assert data["application_type"] in ["INITIAL", "RENEWAL", "CHANGE_OF_OWNERSHIP", "RELOCATION"]
    assert data["status"] in APPLICATION_STATUSES
    assert 0 <= data["facility_sqft"] <= 500000
    assert 0 <= data["display_spaces"] <= 2000
    assert 0 <= data["service_bays"] <= 200
    assert data["bond_amount_cents"] >= 0
    assert data["insurance_liability_cents"] >= 0
    assert data["zoning_certificate_status"] in ["APPROVED", "CONDITIONAL", "PENDING", "DENIED"]
    assert 0 <= data["line_make_count"] <= 12
    assert isinstance(data["deficiency_codes"], list)
    for code in data["deficiency_codes"]:
        assert code in DEFICIENCY_CODES, f"unknown deficiency code {code!r}"
    assert data["deficiency_count"] == len(data["deficiency_codes"]), \
        "deficiency_count is the number of entries in deficiency_codes"
    assert data["deficiency_codes"] == sorted(data["deficiency_codes"]), \
        "deficiency_codes must be sorted in ascending lexicographic order"
    assert 0 <= data["resubmission_count"] <= 2


def assert_salesperson(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["sponsoring_dealer_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["disclosed_prior_discipline"], bool)
    assert data["license_status"] in SALESPERSON_LICENSE_STATUSES
    assert data["discipline_status"] in DISCIPLINE_STATUSES
    assert data["disciplinary_points"] >= 0
    assert data["renewal_count"] >= 0


def assert_franchise_filing(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["manufacturer_id"])
    assert data["filing_type"] in ["TERMINATION", "RELOCATION", "ADDITIONAL_POINT"]
    assert data["status"] in FILING_STATUSES
    assert isinstance(data["proposed_effective_on"], str)
    assert 0 <= data["amendment_count"] <= 2
    assert data["active_protest_count"] >= 0


def assert_protest(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["franchise_filing_id"])
    assert is_valid_uuid(data["protestant_dealer_id"])
    assert data["grounds_code"] in [
        "INADEQUATE_REPRESENTATION", "NO_GOOD_CAUSE_FOR_TERMINATION", "MARKET_ENCROACHMENT",
    ]
    assert data["status"] in PROTEST_STATUSES
    assert data["accepted_evidence_pages"] >= 0
    assert data["late_evidence_count"] >= 0
    assert data["good_cause_threshold"] in [40.00, 60.00]


def assert_market_study(data: dict) -> None:
    assert_append_only_record(data)
    assert data["submitted_by_party"] in ["PROTESTANT", "MANUFACTURER"]
    assert data["basis"] in ["STATEWIDE_AVERAGE", "COMPARABLE_MARKET"]
    assert data["total_market_registrations"] >= 0
    assert data["line_make_registrations"] >= 0
    assert data["line_make_registrations"] <= data["total_market_registrations"], \
        "line_make_registrations may not exceed total_market_registrations"
    assert data["permanency_investment_cents"] >= 0
    assert 0 <= data["consumer_access_drive_minutes"] <= 600
    assert -50.00 <= data["market_growth_pct"] <= 100.00
    assert data["shortfall_pts"] >= 0.00, "a negative shortfall is raised to 0.00"
    assert isinstance(data["is_probative"], bool)


def assert_evidence_submission(data: dict) -> None:
    assert_append_only_record(data)
    assert data["submitting_party"] in ["PROTESTANT", "MANUFACTURER"]
    assert 1 <= len(data["exhibit_label"]) <= 20
    assert 1 <= data["page_count"] <= 5000
    assert data["acceptance_status"] in ["ACCEPTED", "LATE_ACCEPTED"]
    assert is_iso8601_timestamp(data["received_at"])
    assert isinstance(data["is_late"], bool)
    assert data["is_late"] == (data["acceptance_status"] == "LATE_ACCEPTED"), \
        "is_late records exactly the late-accepted outcome"


def assert_warranty_rate_dispute(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["dealer_id"])
    assert is_valid_uuid(data["manufacturer_id"])
    assert data["status"] in DISPUTE_STATUSES
    assert 1 <= len(data["repair_order_lines"]) <= 100
    assert data["qualifying_line_count"] >= 5, \
        "a stored dispute always carries at least 5 qualifying lines"
    assert data["declared_rate_cents"] > 0
    assert isinstance(data["excluded_line_indexes"], list)


def assert_consumer_complaint(data: dict) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["dealer_id"])
    assert data["allegation_code"] in [
        "ODOMETER_MISREPRESENTATION", "FAILURE_TO_TRANSFER_TITLE", "ADVERTISING_VIOLATION",
        "DEPOSIT_RETENTION", "UNLICENSED_SALESPERSON",
    ]
    assert data["status"] in COMPLAINT_STATUSES
    assert data["alleged_loss_cents"] >= 0
    assert data["points_assessed"] in [0, 3, 6, 9]
    assert data["restitution_paid_cents"] >= 0


SLOT_HOLDING_PROTEST_STATUSES = [
    "SCHEDULED", "HEARD", "SUSTAINED", "DENIED", "APPEALED", "FINAL",
]


def assert_restitution_ledger_conserved(complaint: dict) -> None:
    """The ordered restitution equals the amount already paid plus the
    complaint's remaining contribution to its dealership's balance."""
    ordered = complaint["restitution_ordered_cents"]
    paid = complaint["restitution_paid_cents"]
    assert ordered is not None, "a sanctioned complaint carries an ordered amount"
    assert paid <= ordered, (
        f"restitution_paid_cents {paid} may never exceed "
        f"restitution_ordered_cents {ordered}"
    )


def assert_dealer_ledger_matches(dealer: dict, complaints: list) -> None:
    """A dealership's restitution_outstanding_cents is the sum, over its
    complaints still in SANCTIONED, of the remaining balance on each."""
    expected = sum(
        c["restitution_ordered_cents"] - c["restitution_paid_cents"]
        for c in complaints
        if c["status"] == "SANCTIONED"
    )
    assert dealer["restitution_outstanding_cents"] == expected, (
        f"Expected restitution_outstanding_cents {expected}, got "
        f"{dealer['restitution_outstanding_cents']}"
    )


def assert_room_slot_ledger(room: dict, protests: list) -> None:
    """A room's booked_hearing_count is exactly the number of protests that
    both name that room and hold a slot in it."""
    expected = sum(
        1 for p in protests
        if p.get("hearing_room_id") == room["id"]
        and p.get("hearing_start_at") is not None
        and p["status"] in SLOT_HOLDING_PROTEST_STATUSES
    )
    assert room["booked_hearing_count"] == expected, (
        f"Expected booked_hearing_count {expected}, got {room['booked_hearing_count']}"
    )


def assert_docket_released(protest: dict) -> None:
    """A protest that gave up its room holds none of the four docket fields."""
    for field in ("hearing_room_id", "hearing_start_at", "hearing_end_at",
                  "hearing_session_count"):
        assert protest[field] is None, f"{field} must be cleared, got {protest[field]!r}"


def assert_assessment_split_resums(protest: dict) -> None:
    """protestant_share_cents and manufacturer_share_cents always re-sum to
    assessment_total_cents exactly with no rounding drift."""
    total = protest["assessment_total_cents"]
    protestant = protest["protestant_share_cents"]
    manufacturer = protest["manufacturer_share_cents"]
    assert None not in (total, protestant, manufacturer), \
        "a decided protest carries the assessment and both shares"
    assert protestant + manufacturer == total, (
        f"{protestant} + {manufacturer} != {total}"
    )


def assert_two_decimals(value, label="value") -> None:
    """Percentages and coordinate distances are carried to exactly two decimals."""
    assert value is not None, f"{label} must be present"
    assert round(float(value), 2) == float(value), \
        f"{label} must carry at most two decimal places, got {value!r}"


def assert_list_meta(meta: dict, total_count: int, limit: int = 10, offset: int = 0) -> None:
    """The meta block of a list response carries limit, offset, total_count and
    has_more (true when rows remain beyond the current window)."""
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["limit"] == limit
    assert meta["offset"] == offset
    assert meta["has_more"] == (offset + limit < total_count), (
        f"has_more should be {offset + limit < total_count}, got {meta['has_more']}"
    )


def assert_created_at_ascending(rows: list) -> None:
    """List results are ordered by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ascending order: {stamps}"


def parse_instant(value):
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z and any width of
    fractional seconds, so an instant may be compared by value rather than by
    the exact spelling the server chose."""
    assert value is not None, "expected an instant, got None"
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_same_instant(actual, expected) -> None:
    """Two ISO 8601 UTC instants denote the same moment."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"Expected the instant {expected}, got {actual}"
    )
