"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data, entity_name):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a prefix-less UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1"
    )


def assert_organization(data):
    _assert_common_fields(data, "GranteeOrganization")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["ein"], str) and data["ein"]
    assert data["org_type"] in [
        "NONPROFIT",
        "PUBLIC_AGENCY",
        "INSTITUTION_OF_HIGHER_ED",
        "TRIBAL",
    ]
    assert data["status"] in ["ACTIVE", "DEBARRED"]


def assert_competition(data):
    _assert_common_fields(data, "GrantCompetition")
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["fiscal_year"], int)
    assert data["status"] in ["OPEN", "CLOSED", "AWARDS_FINALIZED"]


def assert_application(data):
    _assert_common_fields(data, "GrantApplication")
    assert isinstance(data["competition_id"], str)
    assert isinstance(data["organization_id"], str)
    assert isinstance(data["federal_share_requested_cents"], int)
    assert data["federal_share_requested_cents"] > 0
    assert isinstance(data["total_term_minutes"], int)
    assert data["status"] in [
        "DRAFT",
        "UNDER_REVIEW",
        "CLARIFICATION_REQUESTED",
        "AWARDED",
        "REJECTED",
    ]


def assert_award(data):
    _assert_common_fields(data, "GrantAward")
    assert isinstance(data["application_id"], str)
    assert isinstance(data["organization_id"], str)
    assert isinstance(data["federal_share_awarded_cents"], int)
    assert isinstance(data["awarded_slot_count"], int) and data["awarded_slot_count"] >= 1
    assert isinstance(data["allowable_match_cents"], int) and data["allowable_match_cents"] >= 0
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]


def assert_slot(data):
    _assert_common_fields(data, "PositionSlot")
    assert isinstance(data["award_id"], str)
    assert data["term_category"] in [
        "FULL_TIME",
        "HALF_TIME",
        "REDUCED_HALF_TIME",
        "QUARTER_TIME",
        "MINIMUM_TIME",
        "ABBREVIATED_TIME",
    ]
    assert isinstance(data["slot_index"], int) and data["slot_index"] >= 1
    assert isinstance(data["fill_count"], int) and data["fill_count"] >= 0
    assert data["status"] in ["OPEN", "RESERVED", "FILLED", "VACATED", "RETIRED"]


def assert_member(data):
    _assert_common_fields(data, "Member")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str)
    assert data["citizenship_status"] in [
        "US_CITIZEN",
        "US_NATIONAL",
        "LAWFUL_PERMANENT_RESIDENT",
    ]
    assert data["status"] in ["ACTIVE", "DEBARRED"]
    assert isinstance(data["for_cause_release_count"], int)
    assert data["for_cause_release_count"] >= 0


def assert_check(data):
    _assert_common_fields(data, "CriminalHistoryCheck")
    assert isinstance(data["member_id"], str)
    assert isinstance(data["check_seq"], int) and data["check_seq"] >= 1
    for field in ("nsopr_status", "state_status", "fbi_status"):
        assert data[field] in ["PENDING", "CLEAR", "FLAGGED"]
    assert data["adjudication"] in ["PENDING", "CLEARED", "FLAGGED"]


def assert_enrollment(data):
    _assert_common_fields(data, "MemberEnrollment")
    assert isinstance(data["member_id"], str)
    assert isinstance(data["award_id"], str)
    assert isinstance(data["term_minutes"], int) and data["term_minutes"] > 0
    assert isinstance(data["certified_minutes"], int) and data["certified_minutes"] >= 0
    assert isinstance(data["fundraising_certified_minutes"], int)
    assert isinstance(data["allowance_paid_cents"], int) and data["allowance_paid_cents"] >= 0
    assert data["suspension_origin"] in ["NONE", "MANUAL", "AWARD_CASCADE"]
    assert data["status"] in [
        "PENDING_CHECKS",
        "ACTIVE",
        "SUSPENDED",
        "EXITED_SUCCESSFUL",
        "EXITED_COMPELLING",
        "RELEASED_FOR_CAUSE",
        "CANCELLED",
    ]


def assert_hour_entry(data):
    _assert_common_fields(data, "ServiceHourEntry")
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["service_date"], str)
    assert isinstance(data["minutes"], int) and 1 <= data["minutes"] <= 48000
    assert data["activity_code"] in [
        "DIRECT_SERVICE",
        "CAPACITY_BUILDING",
        "TRAINING",
        "FUNDRAISING",
        "PROSELYTIZING",
        "PARTISAN_LOBBYING",
    ]
    assert data["status"] in ["PENDING", "CERTIFIED", "REJECTED"]


def assert_payment(data):
    """LivingAllowancePayment is immutable: it carries only id and created_at
    of the common field set; updated_at and version are absent (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "payment.id must be a prefix-less UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "payment must NOT carry updated_at"
    assert "version" not in data, "payment must NOT carry version"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1


def assert_education_award(data):
    _assert_common_fields(data, "EducationAward")
    assert isinstance(data["member_id"], str)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["issued_amount_cents"], int) and data["issued_amount_cents"] > 0
    assert isinstance(data["remaining_balance_cents"], int)
    assert 0 <= data["remaining_balance_cents"] <= data["issued_amount_cents"]
    assert data["status"] in ["ISSUED", "PARTIALLY_USED", "EXHAUSTED", "EXPIRED"]


def assert_award_use(data):
    _assert_common_fields(data, "EducationAwardUse")
    assert isinstance(data["education_award_id"], str)
    assert data["use_type"] in ["TUITION", "QUALIFIED_LOAN"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ["PENDING_APPROVAL", "APPROVED", "DENIED", "RESCINDED"]


def assert_visit(data):
    _assert_common_fields(data, "ComplianceVisit")
    assert isinstance(data["award_id"], str)
    assert data["visit_type"] in ["SITE_VISIT", "FILE_REVIEW"]
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["created_by_officer_id"], str)
    assert data["status"] in ["SCHEDULED", "CONDUCTED", "CLOSED"]


def assert_finding(data):
    _assert_common_fields(data, "Finding")
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["award_id"], str)
    assert data["severity"] in ["LOW", "HIGH"]
    assert data["status"] in [
        "OPEN",
        "ACTION_ASSIGNED",
        "EVIDENCE_SUBMITTED",
        "RESOLVED",
        "ESCALATED",
    ]


def assert_grievance(data):
    _assert_common_fields(data, "Grievance")
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["description"], str) and data["description"]
    assert data["status"] in ["FILED", "ESCALATED", "RESOLVED"]


def assert_measure(data):
    _assert_common_fields(data, "PerformanceMeasure")
    assert isinstance(data["award_id"], str)
    assert data["measure_code"] in ["MSY_OUTPUT", "BENEFICIARY_OUTCOME", "COMMUNITY_OUTCOME"]
    assert isinstance(data["target_value"], int) and data["target_value"] > 0
    assert data["status"] in ["OPEN", "SUBMITTED", "ACCEPTED", "RETURNED"]


def assert_slot_conservation(slots, awarded_slot_count):
    """The award's capacity ledger: slots are never created or destroyed after
    minting — every slot sits in exactly one status and their total is the
    awarded slot count (PRD §3.3)."""
    assert len(slots) == awarded_slot_count, (
        f"slot count {len(slots)} != awarded_slot_count {awarded_slot_count}"
    )
    counts = {"OPEN": 0, "RESERVED": 0, "FILLED": 0, "VACATED": 0, "RETIRED": 0}
    for slot in slots:
        counts[slot["status"]] += 1
    assert (
        counts["OPEN"] + counts["RESERVED"] + counts["FILLED"] + counts["VACATED"]
        + counts["RETIRED"]
        == awarded_slot_count
    )
    return counts
