"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict, label: str = "resource"):
    """PRD section 2.4: every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')}"
    )


def assert_three_fractional_digits(value: str, label: str = "timestamp"):
    """PRD section 2.4: timestamps carry exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{label} must be UTC and end with Z, got {value!r}"
    assert "." in value, f"{label} must carry fractional seconds, got {value!r}"
    fraction = value.split(".")[-1][:-1]
    assert len(fraction) == 3 and fraction.isdigit(), (
        f"{label} must carry exactly three fractional digits, got {value!r}"
    )


def assert_land_manager(data: dict):
    assert_common_fields(data, "LandManager")
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert isinstance(data["permit_required"], bool)
    assert isinstance(data["permit_lead_days"], int) and data["permit_lead_days"] >= 0
    assert isinstance(data["max_party_size"], int) and data["max_party_size"] >= 1
    assert 0.0 <= float(data["wet_threshold_index"]) <= 1.0
    assert isinstance(data["requires_engineering_review"], bool)
    assert isinstance(data["requires_certified_sawyer"], bool)
    assert isinstance(data["policy_version"], int)
    assert isinstance(data["adopted_segment_count"], int)


def assert_volunteer(data: dict):
    assert_common_fields(data, "VolunteerProfile")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["certifications"], list)
    assert data["skill_class"] in [
        "GENERAL",
        "SKILLED_TRAIL",
        "CERTIFIED_SAWYER",
        "PROFESSIONAL",
    ]
    assert_hour_invariant(data)
    assert isinstance(data["active_registration_count"], int)
    assert data["active_registration_count"] >= 0


def assert_hour_invariant(volunteer: dict):
    """PRD section 2.9 hour invariant, checked with zero drift."""
    lifetime = round(float(volunteer["lifetime_credited_hours"]), 2)
    partitioned = round(
        float(volunteer["pending_hours"])
        + float(volunteer["verified_hours"])
        + float(volunteer["certified_hours"]),
        2,
    )
    assert lifetime == partitioned, (
        "hour invariant broken: lifetime_credited_hours "
        f"{lifetime} != pending+verified+certified {partitioned}"
    )
    for bucket in (
        "lifetime_credited_hours",
        "pending_hours",
        "verified_hours",
        "certified_hours",
    ):
        assert_quarter_hour(float(volunteer[bucket]), bucket)


def assert_quarter_hour(value: float, label: str = "hours"):
    """PRD section 2.9: volunteer hours are always a multiple of 0.25."""
    assert abs(round(value * 4) - value * 4) < 1e-6, (
        f"{label} must be a multiple of 0.25, got {value}"
    )


def assert_trail_segment(data: dict):
    assert_common_fields(data, "TrailSegment")
    assert is_valid_uuid(data["land_manager_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert float(data["length_miles"]) > 0
    assert data["surface_class"] in ["NATIVE_SOIL", "GRAVEL", "BOARDWALK", "ROCK"]
    assert data["traffic_class"] in ["LIGHT", "MODERATE", "HEAVY"]
    assert data["posture"] in [
        "OPEN",
        "HAZARD_RESTRICTED",
        "WET_RESTRICTED",
        "SEASONAL_CLOSED",
        "INCIDENT_CLOSED",
    ]
    assert data["adoption_status"] in ["UNADOPTED", "ADOPTED"]
    assert 0 <= int(data["hazard_index"]) <= 100
    assert int(data["escalated_hazard_count"]) >= 0
    assert int(data["open_severe_incident_count"]) >= 0


def assert_adoption_agreement(data: dict):
    assert_common_fields(data, "AdoptionAgreement")
    assert is_valid_uuid(data["trail_segment_id"])
    assert is_valid_uuid(data["crew_leader_volunteer_id"])
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "RETURNED",
        "APPROVED",
        "ACTIVE",
        "SUSPENDED",
        "TERMINATED",
    ]
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_work_plan(data: dict):
    assert_common_fields(data, "WorkPlan")
    assert is_valid_uuid(data["adoption_agreement_id"])
    assert isinstance(data["season_year"], int)
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "REVISION_REQUESTED",
        "APPROVED",
        "CLOSED",
    ]
    assert data["budget_posture"] in [
        "HEALTHY",
        "TIGHT",
        "EXHAUSTED",
        "OVER_COMMITTED",
    ]
    assert_budget_invariant(data)


def assert_budget_invariant(plan: dict):
    """PRD section 2.9 budget invariant, checked with zero drift."""
    approved = int(plan["approved_budget_cents"])
    total = (
        int(plan["committed_cents"])
        + int(plan["spent_cents"])
        + int(plan["available_cents"])
    )
    assert approved == total, (
        "budget invariant broken: approved_budget_cents "
        f"{approved} != committed+spent+available {total}"
    )


def assert_condition_report(data: dict):
    assert_common_fields(data, "ConditionReport")
    assert is_valid_uuid(data["trail_segment_id"])
    assert is_valid_uuid(data["reported_by_volunteer_id"])
    assert data["hazard_type"] in [
        "BLOWDOWN",
        "TREAD_EROSION",
        "DRAINAGE_FAILURE",
        "BRIDGE_DAMAGE",
        "SIGNAGE_MISSING",
        "BRUSH_ENCROACHMENT",
    ]
    assert data["severity_class"] in ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    assert data["status"] in [
        "SUBMITTED",
        "TRIAGED",
        "SCHEDULED",
        "DEFERRED",
        "ESCALATED",
        "RESOLVED",
        "VOIDED",
    ]
    assert 0 <= int(data["priority_score"]) <= 100


def assert_work_permit(data: dict):
    assert_common_fields(data, "WorkPermit")
    assert is_valid_uuid(data["work_plan_id"])
    assert is_valid_uuid(data["trail_segment_id"])
    assert is_valid_uuid(data["land_manager_id"])
    assert data["status"] in [
        "REQUESTED",
        "ISSUED",
        "DENIED",
        "CONSUMED",
        "EXPIRED",
        "REVOKED",
    ]
    assert isinstance(data["requested_work_types"], list)
    assert data["requested_work_types"], "requested_work_types must be non-empty"
    assert int(data["consumed_party_count"]) >= 0


def assert_work_party(data: dict):
    assert_common_fields(data, "WorkParty")
    assert is_valid_uuid(data["work_plan_id"])
    assert is_valid_uuid(data["trail_segment_id"])
    assert data["schedule_status"] in [
        "PLANNED",
        "CONFIRMED",
        "IN_PROGRESS",
        "COMPLETED",
        "SUSPENDED",
        "CANCELLED",
    ]
    assert data["readiness_status"] in ["PENDING", "BRIEFED", "CLEARED", "BLOCKED"]
    assert data["block_reason"] in [
        None,
        "PERMIT_REVOKED",
        "PERMIT_EXPIRED",
        "SEGMENT_CLOSED",
        "AGREEMENT_SUSPENDED",
    ]
    assert int(data["max_participants"]) >= 1
    assert int(data["registered_count"]) >= 0
    assert int(data["checked_in_count"]) >= 0
    assert int(data["first_aid_capable_count"]) >= 0
    assert int(data["linked_report_count"]) >= 0


def assert_volunteer_shift(data: dict):
    assert_common_fields(data, "VolunteerShift")
    assert is_valid_uuid(data["work_party_id"])
    assert is_valid_uuid(data["volunteer_id"])
    assert data["status"] in [
        "REGISTERED",
        "CHECKED_IN",
        "CHECKED_OUT",
        "HOURS_VERIFIED",
        "HOURS_DISPUTED",
        "HOURS_CERTIFIED",
        "WITHDRAWN",
        "NO_SHOW",
    ]
    assert data["role_on_crew"] in [
        "CREW_MEMBER",
        "SAWYER",
        "FIRST_AIDER",
        "CREW_LEADER",
    ]
    assert_quarter_hour(float(data["credited_hours"]), "credited_hours")


def assert_material_order(data: dict):
    assert_common_fields(data, "MaterialOrder")
    assert is_valid_uuid(data["work_plan_id"])
    assert data["category"] in ["BRIDGE", "SIGNAGE", "TOOLS", "DRAINAGE", "SURFACING"]
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "DELIVERED",
        "CANCELLED",
    ]
    assert isinstance(data["lines"], list) and data["lines"]
    assert_pricing_chain(data)


def assert_pricing_chain(order: dict):
    """PRD section 3.8: the six pricing steps must be internally consistent."""
    subtotal = int(order["line_subtotal_cents"])
    discount = int(order["discount_cents"])
    discounted = int(order["discounted_subtotal_cents"])
    freight = int(order["freight_cents"])
    surcharge = int(order["bridge_surcharge_cents"])
    total = int(order["total_cents"])
    assert discounted == subtotal - discount, (
        f"discounted_subtotal_cents {discounted} must equal "
        f"line_subtotal_cents {subtotal} less discount_cents {discount}"
    )
    assert total == discounted + freight + surcharge, (
        f"total_cents {total} must equal discounted_subtotal_cents {discounted} "
        f"plus freight_cents {freight} plus bridge_surcharge_cents {surcharge}"
    )


def assert_incident(data: dict):
    assert_common_fields(data, "IncidentReport")
    assert is_valid_uuid(data["work_party_id"])
    assert is_valid_uuid(data["trail_segment_id"])
    assert data["severity_class"] in ["MINOR", "MODERATE", "SEVERE"]
    assert data["status"] in ["OPEN", "UNDER_REVIEW", "CLOSED"]
    assert isinstance(data["first_aid_rendered"], bool)
    assert isinstance(data["reported_by_user_id"], str) and data["reported_by_user_id"]


def assert_money_usd(value, label: str = "usd"):
    """PRD section 2.9: grant-match figures are US dollars to two decimal places."""
    as_float = float(value)
    assert abs(round(as_float, 2) - as_float) < 1e-9, (
        f"{label} must carry at most two decimal places, got {value}"
    )
