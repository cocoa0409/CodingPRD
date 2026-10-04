"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

VALID_UNIVERSITY_STATUSES = ["ONBOARDING", "ACTIVE", "SUSPENDED", "OFFBOARDED"]
VALID_STUDENT_STATUSES = ["ENROLLED", "ALUMNUS", "WITHDRAWN"]
VALID_WORK_AUTHORIZATIONS = [
    "US_CITIZEN", "PERMANENT_RESIDENT", "VISA_OPT_CPT", "SPONSORSHIP_REQUIRED",
]
VALID_PROFILE_VISIBILITIES = [
    "PUBLIC_TO_APPROVED_EMPLOYERS", "UNIVERSITY_ONLY", "HIDDEN",
]
VALID_OUTCOME_STATUSES = ["UNREPORTED", "EMPLOYED", "GRAD_SCHOOL", "SEEKING", "OTHER"]
VALID_EMPLOYER_STATUSES = [
    "PENDING", "DOMAIN_VERIFIED", "APPROVED", "UNDER_REVIEW", "REJECTED",
]
VALID_TRUST_TIERS = ["LOW_RISK", "STANDARD", "ELEVATED", "HIGH_RISK"]
VALID_APPROVAL_STATUSES = ["PENDING", "APPROVED", "BLOCKED", "REVOKED", "SUPERSEDED"]
# EXPIRED is the read-time projection of a stored PUBLISHED posting (PRD §2.10).
VALID_POSTING_STATUSES = [
    "DRAFT", "SUBMITTED", "PUBLISHED", "PAUSED", "CLOSED", "EXPIRED",
]
VALID_POSITION_TYPES = ["FULL_TIME", "INTERNSHIP", "COOP"]
VALID_DOCUMENT_TYPES = ["RESUME", "COVER_LETTER", "TRANSCRIPT", "PORTFOLIO"]
VALID_EVENT_STATUSES = ["DRAFT", "OPEN", "LOCKED", "COMPLETED", "CANCELLED"]
VALID_SESSION_MODES = ["VIRTUAL", "IN_PERSON"]
VALID_SESSION_STATUSES = ["SCHEDULED", "CANCELLED"]
VALID_SIGNUP_STATUSES = [
    "REGISTERED", "WAITLISTED", "CANCELLED", "ATTENDED", "NO_SHOW",
]
VALID_APPLICATION_STATUSES = [
    "SUBMITTED", "UNDER_REVIEW", "INTERVIEWING", "OFFER_EXTENDED",
    "ACCEPTED", "DECLINED", "REJECTED", "WITHDRAWN", "AUTO_WITHDRAWN",
]
VALID_INTERVIEW_STATUSES = ["SCHEDULED", "CANCELLED"]
VALID_DOCUMENT_STATUSES = ["COMPLETE", "INCOMPLETE"]

# Statuses counted toward a posting's active_application_count (PRD §3.4).
ACTIVE_APPLICATION_STATUSES = [
    "SUBMITTED", "UNDER_REVIEW", "INTERVIEWING", "OFFER_EXTENDED",
]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_university(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["primary_domain"], str) and len(data["primary_domain"]) > 0
    assert data["status"] in VALID_UNIVERSITY_STATUSES
    assert isinstance(data["employer_daily_message_cap"], int)
    assert data["employer_daily_message_cap"] >= 0
    assert isinstance(data["enrolled_student_count"], int)
    assert data["enrolled_student_count"] >= 0
    assert isinstance(data["approved_employer_count"], int)
    assert data["approved_employer_count"] >= 0


def assert_student(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("university_id", "")), "university_id must be a UUID"
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["major"], str) and len(data["major"]) > 0
    assert isinstance(data["graduation_year"], int)
    assert data["work_authorization"] in VALID_WORK_AUTHORIZATIONS
    assert data["profile_visibility"] in VALID_PROFILE_VISIBILITIES
    assert data["status"] in VALID_STUDENT_STATUSES
    assert data["outcome_status"] in VALID_OUTCOME_STATUSES
    assert data["outcome_employer_name"] is None or isinstance(data["outcome_employer_name"], str)
    assert data["outcome_recorded_at"] is None or is_iso8601_timestamp(data["outcome_recorded_at"])


def assert_employer(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["website_domain"], str) and len(data["website_domain"]) > 0
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert data["status"] in VALID_EMPLOYER_STATUSES
    assert data["domain_verification_token"] is None or isinstance(
        data["domain_verification_token"], str
    )
    assert isinstance(data["fraud_risk_score"], int)
    assert 0 <= data["fraud_risk_score"] <= 100
    assert data["trust_tier"] in VALID_TRUST_TIERS
    assert isinstance(data["screen_count"], int) and data["screen_count"] >= 0
    assert data["last_trust_decision_at"] is None or is_iso8601_timestamp(
        data["last_trust_decision_at"]
    )


def assert_employer_approval(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("employer_id", "")), "employer_id must be a UUID"
    assert is_valid_uuid(data.get("university_id", "")), "university_id must be a UUID"
    assert data["status"] in VALID_APPROVAL_STATUSES
    assert data["decision_reason"] is None or isinstance(data["decision_reason"], str)
    assert data["decided_at"] is None or is_iso8601_timestamp(data["decided_at"])
    assert data["trust_tier_at_decision"] is None or (
        data["trust_tier_at_decision"] in VALID_TRUST_TIERS
    )
    assert data["supersedes_approval_id"] is None or is_valid_uuid(
        data["supersedes_approval_id"]
    )


def assert_job_posting(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("employer_id", "")), "employer_id must be a UUID"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["position_type"] in VALID_POSITION_TYPES
    assert isinstance(data["required_majors"], list)
    assert isinstance(data["min_graduation_year"], int)
    assert isinstance(data["max_graduation_year"], int)
    assert data["min_graduation_year"] <= data["max_graduation_year"]
    assert isinstance(data["accepted_work_authorizations"], list)
    assert isinstance(data["required_documents"], list)
    assert is_iso8601_timestamp(data["application_deadline"])
    assert data["status"] in VALID_POSTING_STATUSES
    assert isinstance(data["blocked_university_ids"], list)
    assert isinstance(data["active_application_count"], int)
    assert data["active_application_count"] >= 0


def assert_career_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("university_id", "")), "university_id must be a UUID"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in VALID_EVENT_STATUSES
    assert data["last_session_added_at"] is None or is_iso8601_timestamp(
        data["last_session_added_at"]
    )


def assert_event_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("career_event_id", "")), "career_event_id must be a UUID"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["mode"] in VALID_SESSION_MODES
    assert data["room_id"] is None or isinstance(data["room_id"], str)
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert is_iso8601_timestamp(data["signup_deadline"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["occupied_seats"], int) and data["occupied_seats"] >= 0
    assert data["status"] in VALID_SESSION_STATUSES


def assert_event_signup(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_session_id", "")), "event_session_id must be a UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a UUID"
    assert data["status"] in VALID_SIGNUP_STATUSES
    assert data["registered_at"] is None or is_iso8601_timestamp(data["registered_at"])
    assert isinstance(data["promoted_from_waitlist"], bool)


def assert_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a UUID"
    assert is_valid_uuid(data.get("job_posting_id", "")), "job_posting_id must be a UUID"
    assert data["status"] in VALID_APPLICATION_STATUSES
    assert isinstance(data["submitted_documents"], list)
    for doc in data["submitted_documents"]:
        assert doc["doc_type"] in VALID_DOCUMENT_TYPES
        assert isinstance(doc["file_uri"], str) and len(doc["file_uri"]) > 0
    assert data["documents_status"] in VALID_DOCUMENT_STATUSES
    assert is_iso8601_timestamp(data["submitted_at"])
    assert data["decided_at"] is None or is_iso8601_timestamp(data["decided_at"])


def assert_interview(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert isinstance(data["interviewer_email"], str) and "@" in data["interviewer_email"]
    assert data["mode"] in VALID_SESSION_MODES
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in VALID_INTERVIEW_STATUSES


def assert_outreach_message(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("employer_id", "")), "employer_id must be a UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a UUID"
    assert is_valid_uuid(data.get("university_id", "")), "university_id must be a UUID"
    assert isinstance(data["body"], str)
    assert isinstance(data["sent_day"], str) and len(data["sent_day"]) == 10


def assert_outcome_report(data: dict):
    """Shape of the computed first-destination report (PRD §3.9)."""
    assert isinstance(data["alumni_count"], int) and data["alumni_count"] >= 0
    assert isinstance(data["respondents_count"], int) and data["respondents_count"] >= 0
    assert isinstance(data["placed_count"], int) and data["placed_count"] >= 0
    assert data["respondents_count"] <= data["alumni_count"]
    assert data["placed_count"] <= data["respondents_count"]
    assert data["placement_rate_cohort"] is None or isinstance(
        data["placement_rate_cohort"], (int, float)
    )
    assert data["placement_rate_respondent"] is None or isinstance(
        data["placement_rate_respondent"], (int, float)
    )
    assert isinstance(data["per_major"], list)
