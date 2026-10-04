"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


CHARTER_STATUSES = ["APPLICANT", "UNDER_ASSESSMENT", "PROVISIONAL", "CHARTERED", "PROBATION", "REVOKED"]
POSTURES = ["CLEAR", "WATCH", "RESTRICTED", "FROZEN"]
ASSESSMENT_STATUSES = ["DRAFT", "SUBMITTED", "SCORED", "ADJUDICATED", "WITHDRAWN"]
RATINGS = ["STRONG", "ADEQUATE", "MARGINAL", "DEFICIENT"]
COUNSELOR_STATUSES = ["ACTIVE", "SUSPENDED", "SEPARATED"]
COURSE_STATUSES = ["SCHEDULED", "IN_SESSION", "CONCLUDED", "CANCELLED"]
ENROLLMENT_STATUSES = ["REGISTERED", "COMPLETED", "FAILED", "WITHDRAWN"]
CERTIFICATION_STATUSES = ["CANDIDATE", "CERTIFIED", "LAPSED", "EXPIRED", "REVOKED"]
CYCLE_STATUSES = ["OPEN", "FORMULA_LOCKED", "COMPETITIVE_REVIEW", "AWARDED", "CLOSED"]
APPLICATION_STATUSES = ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "AWARDED", "DECLINED", "WITHDRAWN"]
AWARD_STATUSES = ["DISBURSING", "ACTIVE", "SUSPENDED", "RECONCILED", "CLOSED", "TERMINATED"]
DISBURSEMENT_STATUSES = ["PENDING", "POSTED", "VOIDED"]
FILE_STATUSES = ["OPEN", "COUNSELING", "OUTCOME_RECORDED", "CLOSED"]
OUTCOME_CODES = [
    "PURCHASED_HOME", "MORTGAGE_READY", "RENTAL_STABILIZED",
    "FORECLOSURE_AVERTED", "BUDGET_PLAN_ADOPTED", "NO_OUTCOME",
]
FILE_REVIEW_STATUSES = ["OPEN", "PASSED", "FAILED", "REMEDIATED"]
REPORT_STATUSES = ["SUBMITTED", "ACCEPTED", "FLAGGED", "AUDITED"]
AUDIT_STATUSES = ["OPEN", "FINDINGS_ISSUED", "RESOLVED", "ESCALATED"]
PERFORMANCE_REVIEW_STATUSES = ["OPEN", "SCORED", "SATISFACTORY", "CORRECTIVE_ACTION", "ESCALATED", "CLOSED"]
PROGRAM_AREAS = [
    "HOMEOWNERSHIP", "RENTAL", "COMMUNITY_DEVELOPMENT",
    "FINANCIAL_CAPABILITY", "FORECLOSURE_PREVENTION",
]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["ein"], str) and len(data["ein"]) == 9 and data["ein"].isdigit()
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["charter_status"] in CHARTER_STATUSES
    assert data["compliance_posture"] in POSTURES
    assert isinstance(data["service_regions"], list) and 1 <= len(data["service_regions"]) <= 50
    assert isinstance(data["open_finding_count"], int)
    assert isinstance(data["failed_review_flag"], bool)


def assert_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["assessment_status"] in ASSESSMENT_STATUSES
    if data.get("provisional_rating") is not None:
        assert data["provisional_rating"] in RATINGS
    if data.get("final_rating") is not None:
        assert data["final_rating"] in RATINGS


def assert_counselor(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["counselor_status"] in COUNSELOR_STATUSES
    assert isinstance(data["ce_credits_accumulated"], int)


def assert_course(data: dict):
    _assert_common(data)
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert data["program_area"] in PROGRAM_AREAS
    assert isinstance(data["capacity"], int) and 1 <= data["capacity"] <= 500
    assert data["course_status"] in COURSE_STATUSES
    assert isinstance(data["seats_taken"], int) and data["seats_taken"] >= 0


def assert_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("course_id", ""))
    assert is_valid_uuid(data.get("counselor_id", ""))
    assert data["enrollment_status"] in ENROLLMENT_STATUSES
    if data.get("score") is not None:
        assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    assert data.get("pass_threshold") == 70


def assert_certification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("counselor_id", ""))
    assert data["program_area"] in PROGRAM_AREAS
    assert data["certification_status"] in CERTIFICATION_STATUSES
    assert isinstance(data["continuing_requirement_met"], bool)


def assert_grant_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["fiscal_year"], int) and 2000 <= data["fiscal_year"] <= 2100
    assert isinstance(data["formula_pool_cents"], int) and data["formula_pool_cents"] >= 0
    assert isinstance(data["competitive_pool_cents"], int) and data["competitive_pool_cents"] >= 0
    assert data["cycle_status"] in CYCLE_STATUSES
    assert isinstance(data["formula_committed_cents"], int)
    assert isinstance(data["competitive_committed_cents"], int)


def assert_grant_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["program_area"] in PROGRAM_AREAS
    assert data["application_status"] in APPLICATION_STATUSES
    if data.get("review_score") is not None:
        assert isinstance(data["review_score"], int) and 0 <= data["review_score"] <= 100


def assert_grant_award(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["formula_component_cents"], int)
    assert isinstance(data["competitive_component_cents"], int)
    assert isinstance(data["required_match_cents"], int)
    assert isinstance(data["verified_match_cents"], int)
    assert data["award_status"] in AWARD_STATUSES
    assert isinstance(data["disbursed_cents"], int) and data["disbursed_cents"] >= 0


def assert_disbursement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("award_id", ""))
    assert isinstance(data["tranche_index"], int) and data["tranche_index"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["disbursement_status"] in DISBURSEMENT_STATUSES


def assert_client_file(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("counselor_id", ""))
    assert data["program_area"] in PROGRAM_AREAS
    assert isinstance(data["household_size"], int) and 1 <= data["household_size"] <= 20
    assert data["file_status"] in FILE_STATUSES
    if data.get("outcome_code") is not None:
        assert data["outcome_code"] in OUTCOME_CODES


def assert_file_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_file_id", ""))
    assert data["review_status"] in FILE_REVIEW_STATUSES
    assert isinstance(data["deficiency_codes"], list)


def assert_expenditure_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("award_id", ""))
    assert data["report_status"] in REPORT_STATUSES
    assert isinstance(data["reported_spent_cents"], int) and data["reported_spent_cents"] >= 0
    assert isinstance(data["cumulative_spent_cents"], int)


def assert_compliance_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("award_id", ""))
    assert data["audit_status"] in AUDIT_STATUSES
    assert isinstance(data["disallowance_cents"], int) and data["disallowance_cents"] >= 0


def assert_performance_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["review_period"], str) and data["review_period"]
    assert data["review_status"] in PERFORMANCE_REVIEW_STATUSES
    if data.get("review_score") is not None:
        assert isinstance(data["review_score"], int) and 0 <= data["review_score"] <= 100


def assert_award_invariants(data: dict):
    """Award ledger invariants that hold after any operation."""
    assert data["disbursed_cents"] >= 0, "disbursed_cents never negative"
    total = data["formula_component_cents"] + data["competitive_component_cents"]
    assert data["disbursed_cents"] <= total, "disbursed must never exceed award total"
