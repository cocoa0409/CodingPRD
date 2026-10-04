"""Entity assertions and domain invariant checkers.

``assert_<entity>`` validates the shape of one resource: the four
system-managed fields every resource carries, plus the fields the contract
declares for that resource. The ``assert_<entity>_invariants`` helpers check
relationships that must hold after any operation.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import instant_matches
from .constants import MAX_REMEDIATION_ATTEMPTS
from .types import LIVE_FINDING_STATUSES


def _present(data: dict, field: str, owner: str):
    assert field in data, f"{owner} response is missing '{field}'"


def assert_common_fields(data: dict, owner: str = "resource"):
    """Every resource in this API carries id, created_at, updated_at and version."""
    _present(data, "id", owner)
    assert is_valid_uuid(data["id"]), f"{owner}.id must be a UUID, got {data['id']!r}"
    _present(data, "created_at", owner)
    assert is_iso8601_timestamp(data["created_at"]), (
        f"{owner}.created_at must be an ISO 8601 UTC timestamp, got {data['created_at']!r}"
    )
    _present(data, "updated_at", owner)
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"{owner}.updated_at must be an ISO 8601 UTC timestamp, got {data['updated_at']!r}"
    )
    _present(data, "version", owner)
    assert isinstance(data["version"], int) and not isinstance(data["version"], bool), (
        f"{owner}.version must be an integer, got {data['version']!r}"
    )


def _assert_enum(data: dict, field: str, allowed, owner: str):
    _present(data, field, owner)
    assert data[field] in allowed, (
        f"{owner}.{field} must be one of {sorted(allowed)}, got {data[field]!r}"
    )


# ── Per-entity shape assertions ────────────────────────────────────────────

def assert_client(data: dict):
    assert_common_fields(data, "Client")
    _assert_enum(data, "status", {"PROSPECT", "ACTIVE", "SUSPENDED", "TERMINATED"}, "Client")
    _assert_enum(
        data, "aggregate_independence_status", {"CLEAR", "RESTRICTED", "FROZEN"}, "Client"
    )
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["naf_approved_fee_cents"], int)
    assert isinstance(data["naf_annual_cap_cents"], int)
    assert isinstance(data["open_finding_count"], int)
    assert isinstance(data["is_public_interest_entity"], bool)


def assert_engagement(data: dict):
    assert_common_fields(data, "Engagement")
    _assert_enum(
        data, "status", {"DRAFT", "ACCEPTANCE_PENDING", "ACTIVE", "SUSPENDED", "CLOSED"}, "Engagement"
    )
    _assert_enum(data, "independence_status", {"CLEAR", "RESTRICTED", "FROZEN"}, "Engagement")
    _assert_enum(data, "risk_tier", {"LOW", "MODERATE", "HIGH", "SIGNIFICANT"}, "Engagement")
    assert isinstance(data["assigned_workload_points"], int)
    assert isinstance(data["quality_review_required"], bool)
    assert isinstance(data["is_multinational"], bool)
    assert data["lead_partner_id"] is None or is_valid_uuid(data["lead_partner_id"])
    assert data["concurring_partner_id"] is None or is_valid_uuid(data["concurring_partner_id"])


def assert_acceptance(data: dict):
    assert_common_fields(data, "ClientAcceptance")
    _assert_enum(
        data,
        "status",
        {"DRAFT", "SUBMITTED", "APPROVED", "CONDITIONAL", "REJECTED", "WITHDRAWN"},
        "ClientAcceptance",
    )
    assert isinstance(data["industry_expertise_confirmed"], bool)
    assert isinstance(data["integrity_score"], (int, float))
    assert isinstance(data["risk_score"], (int, float))
    assert isinstance(data["combined_risk_score"], (int, float))
    assert data["decided_at"] is None or is_iso8601_timestamp(data["decided_at"])


def assert_integrity_assessment(data: dict):
    assert_common_fields(data, "IntegrityAssessment")
    _assert_enum(
        data,
        "source_type",
        {"REGULATORY_ACTION", "LITIGATION", "MEDIA_ADVERSE", "PRIOR_AUDIT_FINDING", "CREDIT_EVENT"},
        "IntegrityAssessment",
    )
    _assert_enum(data, "severity", {"LOW", "MEDIUM", "HIGH", "CRITICAL"}, "IntegrityAssessment")
    assert isinstance(data["score_impact"], int) and 0 <= data["score_impact"] <= 40
    assert isinstance(data["resolved"], bool)
    assert is_iso8601_timestamp(data["assessed_on"])


def assert_professional(data: dict):
    assert_common_fields(data, "Professional")
    _assert_enum(data, "grade", {"PARTNER", "DIRECTOR", "SENIOR_MANAGER", "MANAGER"}, "Professional")
    _assert_enum(
        data,
        "rotation_role_class",
        {"LEAD_PARTNER", "CONCURRING_PARTNER", "EQ_REVIEWER", "NONE"},
        "Professional",
    )
    _assert_enum(data, "availability", {"AVAILABLE", "IN_TIME_OFF", "OVERLOADED"}, "Professional")
    assert isinstance(data["active_workload_points"], int)
    assert isinstance(data["max_workload_points"], int)
    assert isinstance(data["rotation_exposure_months"], int)


def assert_assignment(data: dict):
    assert_common_fields(data, "EngagementRoleAssignment")
    _assert_enum(
        data,
        "role",
        {"LEAD_PARTNER", "CONCURRING_PARTNER", "EQ_REVIEWER", "ENGAGEMENT_MANAGER"},
        "EngagementRoleAssignment",
    )
    _assert_enum(data, "status", {"ACTIVE", "ENDED"}, "EngagementRoleAssignment")
    _assert_enum(
        data,
        "rotation_status",
        {"ON_SERVICE", "ROTATION_DUE", "IN_TIME_OFF", "ELIGIBLE"},
        "EngagementRoleAssignment",
    )
    assert isinstance(data["consecutive_service_months"], int)
    assert isinstance(data["workload_points"], int)
    assert is_iso8601_timestamp(data["started_on"])
    assert is_iso8601_timestamp(data["scheduled_end_on"])
    assert data["ended_on"] is None or is_iso8601_timestamp(data["ended_on"])
    assert data["eligible_return_on"] is None or is_iso8601_timestamp(data["eligible_return_on"])


def assert_finding(data: dict):
    assert_common_fields(data, "IndependenceFinding")
    _assert_enum(
        data, "status", {"OPEN", "REMEDIATION", "RE_TEST", "CLOSED", "REOPENED"}, "IndependenceFinding"
    )
    _assert_enum(
        data, "severity", {"LOW", "MEDIUM", "HIGH", "CRITICAL"}, "IndependenceFinding"
    )
    _assert_enum(
        data,
        "finding_type",
        {
            "FINANCIAL_INTEREST",
            "EMPLOYMENT_RELATIONSHIP",
            "PROHIBITED_SERVICE",
            "AFFILIATE_OBLIGATION",
            "WORKLOAD_LIMIT",
        },
        "IndependenceFinding",
    )
    _assert_enum(
        data,
        "origin",
        {
            "DECLARATION",
            "FINANCIAL_INTEREST",
            "EMPLOYMENT_RELATIONSHIP",
            "PROHIBITED_SERVICE",
            "AFFILIATE_BREACH",
            "WORKLOAD_LIMIT",
            "INSPECTION",
        },
        "IndependenceFinding",
    )
    assert isinstance(data["remediation_attempts"], int)
    assert data["closed_on"] is None or is_iso8601_timestamp(data["closed_on"])


def assert_threat(data: dict):
    assert_common_fields(data, "IndependenceThreat")
    _assert_enum(data, "threat_type", {"FINANCIAL_INTEREST", "EMPLOYMENT_RELATIONSHIP"}, "IndependenceThreat")
    _assert_enum(
        data,
        "status",
        {"DECLARED", "IN_COOLING_OFF", "MITIGATED", "DIVESTED", "CLEARED"},
        "IndependenceThreat",
    )
    assert isinstance(data["is_material"], bool)
    assert isinstance(data["value_cents"], int)
    assert is_iso8601_timestamp(data["effective_on"])
    assert data["cooling_off_end_on"] is None or is_iso8601_timestamp(data["cooling_off_end_on"])


def assert_service(data: dict):
    assert_common_fields(data, "NonAuditService")
    _assert_enum(
        data,
        "status",
        {"DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "REVOKED"},
        "NonAuditService",
    )
    _assert_enum(
        data,
        "service_category",
        {
            "BOOKKEEPING",
            "INTERNAL_AUDIT_OUTSOURCING",
            "VALUATION",
            "TAX_PREPARATION",
            "TAX_ADVISORY",
            "IT_SYSTEMS_DESIGN",
            "ACTUARIAL",
            "MANAGEMENT_FUNCTION",
            "LEGAL",
            "OTHER",
        },
        "NonAuditService",
    )
    assert isinstance(data["is_prohibited_for_pie"], bool)
    assert isinstance(data["fee_cents"], int)
    assert data["approved_fee_cents"] is None or isinstance(data["approved_fee_cents"], int)
    assert data["approved_on"] is None or is_iso8601_timestamp(data["approved_on"])


def assert_affiliate(data: dict):
    assert_common_fields(data, "Affiliate")
    _assert_enum(data, "network_tier", {"MEMBER_FIRM", "CORRESPONDENT", "ALLIANCE"}, "Affiliate")
    _assert_enum(data, "status", {"ACTIVE", "SUSPENDED"}, "Affiliate")
    assert isinstance(data["open_breach_count"], int)


def assert_attestation(data: dict):
    assert_common_fields(data, "AffiliateAttestation")
    _assert_enum(
        data, "attestation_status", {"PENDING", "ATTESTED", "BREACHED", "WAIVED"}, "AffiliateAttestation"
    )
    assert isinstance(data["breach_count"], int)
    assert data["attested_on"] is None or is_iso8601_timestamp(data["attested_on"])


def assert_review(data: dict):
    assert_common_fields(data, "QualityReview")
    _assert_enum(
        data,
        "status",
        {"SCHEDULED", "IN_PROGRESS", "PASSED", "DEFICIENT", "REMEDIATED"},
        "QualityReview",
    )
    _assert_enum(
        data,
        "review_type",
        {"ENGAGEMENT_QUALITY_REVIEW", "INSPECTION_READINESS", "REGULATORY_INSPECTION"},
        "QualityReview",
    )
    assert isinstance(data["deficiency_count"], int)
    assert data["response_due_on"] is None or is_iso8601_timestamp(data["response_due_on"])
    assert is_iso8601_timestamp(data["received_on"])
    assert is_iso8601_timestamp(data["due_on"])


def assert_independence_summary(data: dict):
    for field in (
        "engagement_id",
        "independence_status",
        "critical_open_count",
        "high_open_count",
        "prohibited_service_count",
        "breached_attestation_count",
        "material_interest_count",
        "network_risk_points",
    ):
        assert field in data, f"independence summary is missing '{field}'"
    _assert_enum(data, "independence_status", {"CLEAR", "RESTRICTED", "FROZEN"}, "summary")
    for field in (
        "critical_open_count",
        "high_open_count",
        "prohibited_service_count",
        "breached_attestation_count",
        "material_interest_count",
        "network_risk_points",
    ):
        assert isinstance(data[field], int), f"summary.{field} must be an integer"


# ── Domain invariants ──────────────────────────────────────────────────────

def assert_client_invariants(data: dict):
    """Roll-ups a client must satisfy after any operation."""
    assert data["open_finding_count"] >= 0
    assert data["naf_approved_fee_cents"] >= 0
    assert data["naf_approved_fee_cents"] <= data["naf_annual_cap_cents"], (
        "the approved fee pool must never exceed the annual ceiling"
    )


def assert_engagement_invariants(data: dict):
    """Cross-axis invariants on one engagement row."""
    assert data["status"] != "FROZEN", "the lifecycle axis never takes the posture value FROZEN"
    assert data["independence_status"] != "SUSPENDED", (
        "the posture axis never takes the lifecycle value SUSPENDED"
    )
    assert data["assigned_workload_points"] >= 0
    assert 0 <= float(data["combined_risk_score"]) <= 100, "the combined score is clamped to 0..100"


def assert_acceptance_invariants(data: dict):
    assert 0 <= float(data["integrity_score"]) <= 100
    assert 0 <= float(data["combined_risk_score"]) <= 100


def assert_assignment_invariants(data: dict):
    if data["status"] == "ACTIVE":
        assert data["ended_on"] is None, "an ACTIVE assignment carries no ended_on"
        assert data["eligible_return_on"] is None, (
            "an assignment that is still ACTIVE has a null eligible_return_on"
        )
    else:
        assert data["ended_on"] is not None, "an ENDED assignment carries an ended_on"
        assert data["eligible_return_on"] is not None, (
            "an ENDED assignment carries the date it becomes eligible again"
        )


def assert_professional_invariants(data: dict):
    assert data["active_workload_points"] >= 0
    assert data["rotation_exposure_months"] >= 0
    if data["availability"] == "OVERLOADED":
        assert data["active_workload_points"] > data["max_workload_points"]


def assert_finding_invariants(data: dict):
    if data["status"] == "CLOSED":
        assert data["closed_on"] is not None, "a CLOSED finding carries a closed_on"
    assert data["remediation_attempts"] <= MAX_REMEDIATION_ATTEMPTS or data["status"] in (
        "REOPENED",
        "CLOSED",
    ), "attempts never exceed the budget while the finding can still re-enter remediation"


def assert_service_invariants(data: dict):
    if data["status"] == "APPROVED":
        assert data["approved_fee_cents"] is not None
        assert data["approved_fee_cents"] % 100 == 0, (
            "an approved fee is a whole-dollar amount"
        )
        assert data["approved_on"] is not None
    else:
        assert data["approved_fee_cents"] is None
        assert data["approved_on"] is None


def assert_threat_invariants(data: dict):
    if data["threat_type"] == "EMPLOYMENT_RELATIONSHIP":
        assert data["is_material"] is False, "an employment relationship is never material"
        assert data["instrument_type"] is None
    else:
        assert data["relationship_type"] is None
        assert data["cooling_off_end_on"] is not None


def assert_attestation_invariants(data: dict):
    if data["attestation_status"] == "PENDING":
        assert data["attested_on"] is None
    else:
        assert data["attested_on"] is not None


def assert_review_invariants(data: dict):
    if data["review_type"] != "REGULATORY_INSPECTION":
        assert data["response_due_on"] is None, (
            "only a regulatory inspection carries a response deadline"
        )


def assert_live_finding_status(status: str) -> bool:
    """True when the finding status keeps the engagement's posture elevated."""
    return status in LIVE_FINDING_STATUSES


def assert_same_instant(actual, expected: str, message: str = ""):
    assert instant_matches(actual, expected), (
        message or f"expected the instant {expected}, got {actual!r}"
    )
