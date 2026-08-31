"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import DEBT_TIERS, SEVERITY_POINTS

ENGAGEMENT_STATUSES = [
    "SCOPING", "READINESS", "OBSERVATION", "FIELDWORK", "REPORTING", "ISSUED", "ABANDONED",
]
GAP_POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]


def assert_common_fields(data: dict, entity_name: str = "row") -> None:
    """Every mutable row carries a bare-UUID id, ISO 8601 timestamps and a version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601 UTC with three fractional digits"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601 UTC with three fractional digits"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1"
    )


def assert_engagement(data: dict) -> None:
    assert_common_fields(data, "Engagement")
    assert isinstance(data["client_name"], str) and 1 <= len(data["client_name"]) <= 200
    assert data["report_type"] in ["SOC_1_TYPE_2", "SOC_2_TYPE_2"]
    assert data["status"] in ENGAGEMENT_STATUSES
    assert data["gap_posture"] in GAP_POSTURES
    assert isinstance(data["required_criteria_categories"], list)
    assert len(data["required_criteria_categories"]) >= 1
    assert isinstance(data["max_distribution_recipients"], int)
    assert data["max_distribution_recipients"] >= 1
    assert isinstance(data["base_debt_points"], int)
    assert isinstance(data["open_exception_count"], int)
    assert isinstance(data["criteria_in_scope_count"], int)
    assert isinstance(data["observation_period_days"], int)
    assert isinstance(data["calendar_epoch"], int)
    assert isinstance(data["boundary_locked"], bool)


def assert_system_description(data: dict) -> None:
    assert_common_fields(data, "SystemDescription")
    assert data["status"] in ["DRAFT", "IN_REVIEW", "APPROVED", "SUPERSEDED", "WITHDRAWN"]
    assert isinstance(data["version_label"], str) and 1 <= len(data["version_label"]) <= 40
    assert isinstance(data["boundary_narrative"], str)
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0
    assert isinstance(data["boundary_locked"], bool)
    assert isinstance(data["in_scope_component_count"], int)
    assert isinstance(data["carved_out_component_count"], int)


def assert_boundary_component(data: dict) -> None:
    assert_common_fields(data, "BoundaryComponent")
    assert data["component_type"] in [
        "INFRASTRUCTURE", "SOFTWARE", "PEOPLE", "PROCEDURES", "DATA",
    ]
    assert data["scope_status"] in ["IN_SCOPE", "CARVED_OUT", "EXCLUDED"]
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120


def assert_trust_criterion(data: dict) -> None:
    """Catalog rows carry only id and created_at - never updated_at, never version."""
    assert is_valid_uuid(data.get("id", "")), "TrustCriterion.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "TrustCriterion.created_at must be ISO 8601 UTC with three fractional digits"
    )
    assert "updated_at" not in data, "TrustCriterion must not expose updated_at"
    assert "version" not in data, "TrustCriterion must not expose version"
    assert data["category"] in [
        "SECURITY", "AVAILABILITY", "CONFIDENTIALITY", "PROCESSING_INTEGRITY", "PRIVACY",
    ]
    assert isinstance(data["min_primary_controls"], int) and data["min_primary_controls"] >= 1
    assert isinstance(data["applies_to_report_types"], list)
    assert len(data["applies_to_report_types"]) >= 1


def assert_control(data: dict) -> None:
    assert_common_fields(data, "Control")
    assert data["frequency"] in ["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "ANNUAL", "ADHOC"]
    assert data["automation"] in ["MANUAL", "AUTOMATED"]
    assert data["risk_rating"] in ["LOW", "MODERATE", "HIGH"]
    assert data["design_status"] in [
        "DESIGN_DRAFT", "DESIGN_MAPPED", "DESIGN_APPROVED",
        "DESIGN_DEFICIENT", "DESIGN_CARVED_OUT",
    ]
    assert data["operating_status"] in [
        "NOT_TESTED", "IN_OBSERVATION", "TESTED_EFFECTIVE",
        "TESTED_EXCEPTION", "TESTED_INEFFECTIVE",
    ]
    assert isinstance(data["in_scope"], bool)
    assert isinstance(data["population_size"], int) and data["population_size"] >= 0
    for counter in (
        "primary_mapping_count", "active_mapping_count", "evidence_scheduled_count",
        "evidence_accepted_count", "evidence_missed_count", "tested_item_count",
        "open_gap_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"Control.{counter} must be a non-negative integer"
        )


def assert_criteria_mapping(data: dict) -> None:
    assert_common_fields(data, "CriteriaMapping")
    assert data["mapping_type"] in ["PRIMARY", "SECONDARY"]
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_evidence_request(data: dict) -> None:
    assert_common_fields(data, "EvidenceRequest")
    assert data["status"] in [
        "SCHEDULED", "SUBMITTED", "ACCEPTED", "REJECTED", "MISSED", "WAIVED",
    ]
    assert isinstance(data["period_index"], int) and data["period_index"] >= 0
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert is_iso8601_timestamp(data["due_date"])
    assert isinstance(data["rejection_round"], int) and data["rejection_round"] >= 0
    assert isinstance(data["late"], bool)


def assert_gap(data: dict) -> None:
    assert_common_fields(data, "Gap")
    assert data["source"] in [
        "READINESS_ASSESSMENT", "EXCEPTION_CASCADE", "EVIDENCE_MISS",
        "COVERAGE_LOSS", "MANUAL",
    ]
    assert data["severity"] in ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    assert data["status"] in [
        "OPEN", "PLANNED", "REMEDIATED", "VERIFIED", "REOPENED", "WITHDRAWN",
    ]
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert isinstance(data["debt_points"], int) and data["debt_points"] >= 0


def assert_gap_debt_points_match_status(data: dict) -> None:
    """debt_points carries the severity's point value only in the non-settled states."""
    if data["status"] in ("OPEN", "PLANNED", "REOPENED"):
        assert data["debt_points"] == SEVERITY_POINTS[data["severity"]], (
            f"A {data['status']} {data['severity']} gap must carry "
            f"{SEVERITY_POINTS[data['severity']]} debt_points, got {data['debt_points']}"
        )
    else:
        assert data["debt_points"] == 0, (
            f"A {data['status']} gap must carry 0 debt_points, got {data['debt_points']}"
        )


def assert_audit_sample(data: dict) -> None:
    assert_common_fields(data, "AuditSample")
    assert data["status"] in [
        "DRAWN", "TESTING", "CONCLUDED_CLEAN", "CONCLUDED_EXCEPTIONS", "VOIDED",
    ]
    assert isinstance(data["population_size_snapshot"], int)
    assert isinstance(data["sample_size"], int) and data["sample_size"] >= 0
    assert isinstance(data["allowed_deviations"], int) and data["allowed_deviations"] >= 0
    assert isinstance(data["zero_population"], bool)
    assert data["items_recorded"] == data["items_passed"] + data["items_failed"], (
        "items_recorded must equal items_passed + items_failed"
    )
    assert data["items_not_provided"] <= data["items_failed"], (
        "items_not_provided is a subset of items_failed"
    )
    assert data["items_recorded"] <= data["sample_size"], (
        "items_recorded may never exceed sample_size"
    )


def assert_audit_exception(data: dict) -> None:
    assert_common_fields(data, "AuditException")
    assert data["disposition"] in ["UNEVALUATED", "ISOLATED", "PERVASIVE", "VOIDED"]
    assert data["severity_assigned"] in [None, "MODERATE", "CRITICAL"]
    assert isinstance(data["item_ordinal"], int) and data["item_ordinal"] >= 0
    assert isinstance(data["pervasive_recommended"], bool)


def assert_subservice_organization(data: dict) -> None:
    assert_common_fields(data, "SubserviceOrganization")
    assert data["method"] in ["CARVE_OUT", "INCLUSIVE"]
    assert isinstance(data["csoc_articulated"], bool)
    assert isinstance(data["inclusive_control_count"], int)


def assert_cuec(data: dict) -> None:
    assert_common_fields(data, "CUEC")
    assert data["articulation_status"] in ["DRAFT", "ARTICULATED", "RETIRED"]
    assert isinstance(data["statement"], str) and 1 <= len(data["statement"]) <= 1000
    assert isinstance(data["deflection_topic"], str) and 1 <= len(data["deflection_topic"]) <= 60


def assert_report_distribution(data: dict) -> None:
    assert_common_fields(data, "ReportDistribution")
    assert data["status"] in [
        "REQUESTED", "NDA_PENDING", "APPROVED", "DELIVERED", "REVOKED", "DENIED",
    ]


def assert_bridge_letter(data: dict) -> None:
    assert_common_fields(data, "BridgeLetter")
    assert data["status"] in ["DRAFT", "ISSUED", "EXPIRED", "SUPERSEDED"]
    assert isinstance(data["coverage_days"], int) and data["coverage_days"] >= 1


def assert_customer_questionnaire(data: dict) -> None:
    assert_common_fields(data, "CustomerQuestionnaire")
    assert data["status"] in [
        "RECEIVED", "DEFLECTED", "PARTIALLY_DEFLECTED", "MANUAL_RESPONSE", "CLOSED",
    ]
    assert data["item_count"] == (
        data["criteria_item_count"] + data["post_period_item_count"] + data["cuec_item_count"]
    ), "item_count must be the sum of the three bucket inputs"


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def expected_gap_debt_points(base_debt_points: int) -> float:
    """Reproduce the three-step debt computation: base, tier from the base, then total."""
    if base_debt_points <= DEBT_TIERS["TIER_1_MAX_BASE"]:
        rate = DEBT_TIERS["TIER_1_RATE"]
    elif base_debt_points <= DEBT_TIERS["TIER_2_MAX_BASE"]:
        rate = DEBT_TIERS["TIER_2_RATE"]
    else:
        rate = DEBT_TIERS["TIER_3_RATE"]
    surcharge = round(base_debt_points * rate + 1e-9, 2)
    return round(base_debt_points + surcharge + 1e-9, 2)


def assert_debt_decomposition(summary: dict) -> None:
    """base + surcharge == total, with the tier read off the pre-surcharge base."""
    base = summary["base_debt_points"]
    assert isinstance(base, int), "base_debt_points must be an integer"
    assert round(summary["base_debt_points"] + summary["surcharge_points"], 2) == round(
        summary["gap_debt_points"], 2
    ), "gap_debt_points must equal base_debt_points plus surcharge_points"
    assert summary["gap_debt_points"] == expected_gap_debt_points(base), (
        f"gap_debt_points for base {base} must be {expected_gap_debt_points(base)}, "
        f"got {summary['gap_debt_points']}"
    )


def assert_two_decimal_places(value, label: str = "value") -> None:
    assert isinstance(value, (int, float)), f"{label} must be numeric"
    assert round(float(value), 2) == float(value), f"{label} must carry two decimal places"


def assert_four_decimal_places(value, label: str = "value") -> None:
    assert isinstance(value, (int, float)), f"{label} must be numeric"
    assert round(float(value), 4) == float(value), f"{label} must carry four decimal places"


def assert_coverage_ordering(summary: dict) -> None:
    """On identical data the attestation view can never exceed the readiness view."""
    assert summary["covered_criteria_count_attestation"] <= summary[
        "covered_criteria_count_readiness"
    ], "attestation coverage may never exceed readiness coverage"
    assert summary["criteria_coverage_pct_attestation"] <= summary[
        "criteria_coverage_pct_readiness"
    ], "attestation coverage percentage may never exceed the readiness percentage"
