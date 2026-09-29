"""Entity assertions and domain invariant checkers.

Instants are compared through `assert_instant_equals`, which canonicalises the
sub-second component first: the PRD fixes three fractional digits, and a server
that answers `...T15:00:00.000Z` where the expected literal reads
`...T15:00:00Z` is reporting the same instant.
"""

import re
from typing import List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import BASIS_POINTS_WHOLE, INDICATOR_WEIGHTS, THRESHOLDS

_INSTANT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z$")


def canonical_instant(value: str) -> str:
    """Normalise an ISO 8601 UTC instant to millisecond precision for comparison."""
    assert isinstance(value, str), f"Expected an instant string, got {value!r}"
    match = _INSTANT_RE.match(value)
    assert match, f"Not an ISO 8601 UTC instant: {value!r}"
    date_part, time_part, fraction = match.groups()
    millis = (fraction or "").ljust(3, "0")[:3]
    return f"{date_part}T{time_part}.{millis}Z"


def instants_equal(actual: Optional[str], expected: Optional[str]) -> bool:
    if actual is None or expected is None:
        return actual == expected
    return canonical_instant(actual) == canonical_instant(expected)


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant"):
    if expected is None:
        assert actual is None, f"Expected {label} to be null, got {actual!r}"
        return
    assert actual is not None, f"Expected {label} {expected}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


# ─── Audit-field shapes ───────────────────────────────


def assert_common_audit_fields(data: dict, entity: str = "resource"):
    """`id`, `created_at`, `updated_at` and `version` on a mutable resource."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_immutable_event_fields(data: dict, entity: str = "event record"):
    """An immutable event record carries only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, (
        f"{entity} is written once and never changed: it has no updated_at field"
    )
    assert "version" not in data, (
        f"{entity} is written once and never changed: it has no version field"
    )


# ─── Per-entity assertions ────────────────────────────


def assert_shelter_program(data: dict):
    assert_common_audit_fields(data, "ShelterProgram")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["program_type"] in ("EMERGENCY_SHELTER", "TRANSITIONAL_LIVING")
    assert isinstance(data["licensed_bed_capacity"], int) and data["licensed_bed_capacity"] >= 1
    assert isinstance(data["min_age_years"], int) and 0 <= data["min_age_years"] <= 24
    assert isinstance(data["max_age_years"], int)
    assert data["min_age_years"] <= data["max_age_years"] <= 24
    assert isinstance(data["max_stay_nights"], int) and data["max_stay_nights"] >= 1
    assert isinstance(data["max_placement_days"], int) and data["max_placement_days"] >= 1
    for rate in ("savings_match_rate_bp", "required_savings_rate_bp"):
        assert isinstance(data[rate], int) and 0 <= data[rate] <= BASIS_POINTS_WHOLE, (
            f"{rate} must be a basis-point integer between 0 and 10000, got {data[rate]!r}"
        )
    for counter in ("occupied_beds", "waitlisted_count", "overdue_notification_count",
                    "utilization_bp"):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"ShelterProgram.{counter} must be a non-negative integer, got {data[counter]!r}"
        )
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")


def assert_youth(data: dict):
    assert_common_audit_fields(data, "Youth")
    for name in ("legal_first_name", "legal_last_name"):
        assert isinstance(data[name], str) and 1 <= len(data[name]) <= 80
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["date_of_birth"]), (
        f"date_of_birth is a calendar date with no time component, got {data['date_of_birth']!r}"
    )
    assert isinstance(data["age_years"], int) and data["age_years"] >= 0
    assert isinstance(data["unaccompanied"], bool)
    assert data["status"] in (
        "PROSPECT", "ENGAGED", "SHELTERED", "TLP_ENROLLED",
        "REUNIFIED_PENDING", "REUNIFIED", "EXITED",
    )
    assert data["risk_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["trafficking_risk_score"], int)
    assert 0 <= data["trafficking_risk_score"] <= THRESHOLDS["RISK_SCORE_CAP"]
    assert data["trafficking_risk_tier"] in ("LOW", "ELEVATED", "CRITICAL")
    assert_risk_tier_matches_score(data["trafficking_risk_score"], data["trafficking_risk_tier"])
    for counter in ("engagement_contact_count", "basic_needs_provision_count",
                    "cumulative_shelter_nights", "lifetime_savings_deposited_cents"):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"Youth.{counter} must be a non-negative integer, got {data[counter]!r}"
        )
    assert isinstance(data["governance_vote_eligible"], bool)


def assert_outreach_contact(data: dict):
    assert_immutable_event_fields(data, "OutreachContact")
    assert data["engagement_stage"] in (
        "FIRST_CONTACT", "RAPPORT_BUILDING", "SERVICE_OFFER", "TRUST_ESTABLISHED"
    )
    for field, codes in (
        ("basic_needs_provided", ("FOOD", "HYGIENE_KIT", "CLOTHING", "TRANSIT_PASS",
                                  "MEDICAL_REFERRAL")),
        ("indicator_flags", tuple(INDICATOR_WEIGHTS)),
    ):
        values = data[field]
        assert isinstance(values, list), f"OutreachContact.{field} must be a list"
        assert len(values) == len(set(values)), f"OutreachContact.{field} must be free of duplicates"
        for value in values:
            assert value in codes, f"{value!r} is outside the declared code set for {field}"
    assert is_iso8601_timestamp(data["contacted_at"])


def assert_safety_screening(data: dict):
    assert_common_audit_fields(data, "SafetyScreening")
    assert data["status"] in ("SUBMITTED", "CLEARED", "ESCALATED")
    codes = data["indicator_codes"]
    assert isinstance(codes, list) and len(codes) == len(set(codes))
    for code in codes:
        assert code in INDICATOR_WEIGHTS, f"{code!r} is outside the declared indicator code set"
    assert isinstance(data["score"], int) and 0 <= data["score"] <= THRESHOLDS["RISK_SCORE_CAP"]
    assert data["tier"] in ("LOW", "ELEVATED", "CRITICAL")
    assert_risk_tier_matches_score(data["score"], data["tier"])
    assert data["specialized_response_code"] in (
        "NONE", "ADVOCATE_ASSIGNED", "LAW_ENFORCEMENT_LIAISON", "EMERGENCY_RELOCATION"
    )
    assert is_iso8601_timestamp(data["screened_at"])


def assert_admission(data: dict):
    assert_common_audit_fields(data, "Admission")
    assert data["status"] in (
        "PENDING_SCREENING", "WAITLISTED", "ACTIVE", "EXTENDED",
        "DISCHARGE_SCHEDULED", "DISCHARGED", "DENIED",
    )
    assert is_iso8601_timestamp(data["requested_at"])
    assert is_iso8601_timestamp(data["planned_discharge_at"])
    for nullable_instant in ("admitted_at", "discharged_at"):
        value = data[nullable_instant]
        assert value is None or is_iso8601_timestamp(value), (
            f"Admission.{nullable_instant} must be null or an ISO 8601 instant, got {value!r}"
        )
    for nights in ("projected_billable_nights", "final_billable_nights"):
        value = data[nights]
        assert value is None or (isinstance(value, int) and value >= 0), (
            f"Admission.{nights} must be null or a whole number of nights, got {value!r}"
        )
    assert isinstance(data["extension_count"], int) and 0 <= data["extension_count"] <= 2
    assert isinstance(data["capacity_blocked"], bool)
    assert isinstance(data["priority_score"], int)
    assert 0 <= data["priority_score"] <= THRESHOLDS["PRIORITY_SCORE_CAP"]
    assert data["exit_destination"] is None or data["exit_destination"] in (
        "FAMILY_REUNIFIED", "TRANSITIONAL_LIVING", "INDEPENDENT_HOUSING",
        "OTHER_SHELTER", "UNKNOWN",
    )
    assert data["outcome_positive"] is None or isinstance(data["outcome_positive"], bool)


def assert_guardian_notification(data: dict):
    assert_common_audit_fields(data, "GuardianNotification")
    assert data["status"] in (
        "PENDING", "ATTEMPTED", "OVERDUE", "CONTACTED", "WAIVED", "LAW_ENFORCEMENT_REPORTED"
    )
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert is_iso8601_timestamp(data["due_at"])
    for nullable_instant in ("last_attempt_at", "resolved_at"):
        value = data[nullable_instant]
        assert value is None or is_iso8601_timestamp(value), (
            f"GuardianNotification.{nullable_instant} must be null or an instant, got {value!r}"
        )


def assert_reunification_case(data: dict):
    assert_common_audit_fields(data, "ReunificationCase")
    assert data["status"] in (
        "OPENED", "MEDIATION_SCHEDULED", "MEDIATION_HELD", "HOME_ASSESSMENT",
        "APPROVED", "DECLINED", "AFTERCARE", "CLOSED", "SUPERSEDED",
    )
    assert isinstance(data["guardian_household_label"], str)
    assert 1 <= len(data["guardian_household_label"]) <= 120
    assert is_iso8601_timestamp(data["opened_at"])
    assert isinstance(data["mediation_round"], int) and data["mediation_round"] >= 0
    assert data["max_mediation_rounds"] == THRESHOLDS["MAX_MEDIATION_ROUNDS"], (
        f"max_mediation_rounds is fixed by the server at 3, got {data['max_mediation_rounds']!r}"
    )
    assert data["safety_assessment_result"] is None or data["safety_assessment_result"] in (
        "SAFE", "CONDITIONAL", "UNSAFE"
    )
    assert isinstance(data["aftercare_contacts_completed"], int)
    assert 0 <= data["aftercare_contacts_completed"] <= THRESHOLDS["REQUIRED_AFTERCARE_CONTACTS"]
    for nullable_instant in ("aftercare_plan_due_at", "closed_at"):
        value = data[nullable_instant]
        assert value is None or is_iso8601_timestamp(value), (
            f"ReunificationCase.{nullable_instant} must be null or an instant, got {value!r}"
        )


def assert_mediation_session(data: dict):
    assert_common_audit_fields(data, "MediationSession")
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert canonical_instant(data["scheduled_end_at"]) > canonical_instant(
        data["scheduled_start_at"]
    ), "scheduled_end_at must be strictly after scheduled_start_at"
    assert data["outcome"] is None or data["outcome"] in (
        "PROGRESS", "IMPASSE", "GUARDIAN_NO_SHOW", "AGREEMENT"
    )
    assert data["held_at"] is None or is_iso8601_timestamp(data["held_at"])


def assert_tlp_placement(data: dict):
    assert_common_audit_fields(data, "TlpPlacement")
    assert data["tenancy_status"] in ("PLACED", "NOTICE_GIVEN", "EXITED")
    assert data["compliance_status"] in ("IN_COMPLIANCE", "SAVINGS_DEFICIENT", "PROBATION")
    assert is_iso8601_timestamp(data["placed_at"])
    assert data["exited_at"] is None or is_iso8601_timestamp(data["exited_at"])
    assert data["exit_reason"] is None or data["exit_reason"] in (
        "DURATION_LIMIT", "INDEPENDENT_HOUSING", "REUNIFIED", "NONCOMPLIANCE", "YOUTH_INITIATED"
    )
    for cents in ("documented_monthly_income_cents", "required_savings_cents",
                  "savings_balance_cents"):
        assert isinstance(data[cents], int), (
            f"TlpPlacement.{cents} must be an integer count of cents, got {data[cents]!r}"
        )
    assert data["documented_monthly_income_cents"] >= 0
    assert data["required_savings_cents"] >= 0
    assert isinstance(data["match_awarded_cents"], int)
    assert 0 <= data["match_awarded_cents"] <= THRESHOLDS["MATCH_CAP_CENTS"], (
        "match_awarded_cents is held at a floor of zero and capped at 50000 cents"
    )
    assert isinstance(data["consecutive_probation_reviews"], int)
    assert data["consecutive_probation_reviews"] >= 0
    assert isinstance(data["life_skills_credit_hours"], int)
    assert data["life_skills_credit_hours"] >= 0
    for days in ("base_allowance_days", "earned_bonus_days", "allowance_days", "days_elapsed"):
        assert isinstance(data[days], int) and data[days] >= 0, (
            f"TlpPlacement.{days} must be a whole number of days, got {data[days]!r}"
        )
    assert data["allowance_days"] == data["base_allowance_days"] + data["earned_bonus_days"], (
        "allowance_days is base_allowance_days plus earned_bonus_days"
    )
    assert isinstance(data["consumed_ratio_bp"], int) and data["consumed_ratio_bp"] >= 0


def assert_savings_ledger_entry(data: dict):
    assert_immutable_event_fields(data, "SavingsLedgerEntry")
    assert data["entry_type"] in ("DEPOSIT", "WITHDRAWAL", "REVERSAL")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1, (
        "amount_cents is always a positive magnitude of at least 1"
    )
    for derived in ("signed_amount_cents", "match_component_cents", "balance_after_cents"):
        assert isinstance(data[derived], int), (
            f"SavingsLedgerEntry.{derived} must be an integer count of cents, got {data[derived]!r}"
        )
    if data["entry_type"] == "DEPOSIT":
        assert data["signed_amount_cents"] == data["amount_cents"]
    else:
        assert data["signed_amount_cents"] == -data["amount_cents"], (
            "signed_amount_cents is the negation of amount_cents for a withdrawal and a reversal"
        )
    if data["entry_type"] == "WITHDRAWAL":
        assert data["match_component_cents"] == 0, (
            "match_component_cents is 0 for a withdrawal"
        )
    assert is_iso8601_timestamp(data["posted_at"])


def assert_life_skills_completion(data: dict):
    assert_immutable_event_fields(data, "LifeSkillsCompletion")
    assert data["module_code"] in (
        "BUDGETING", "TENANCY", "EMPLOYMENT_READINESS", "HEALTH_LITERACY",
        "CONFLICT_RESOLUTION", "CIVIC_ENGAGEMENT",
    )
    assert isinstance(data["credit_hours"], int)
    assert (
        THRESHOLDS["LIFE_SKILLS_HOURS_MIN"] <= data["credit_hours"]
        <= THRESHOLDS["LIFE_SKILLS_HOURS_MAX"]
    ), "credit_hours must be between 1 and 40 inclusive"
    assert is_iso8601_timestamp(data["completed_at"])


def assert_education_enrollment(data: dict):
    assert_common_audit_fields(data, "EducationEnrollment")
    assert isinstance(data["school_name"], str) and 1 <= len(data["school_name"]) <= 120
    assert data["enrollment_type"] in (
        "PUBLIC_K12", "GED_PROGRAM", "POSTSECONDARY", "VOCATIONAL"
    )
    assert data["status"] in ("IMMEDIATE_ENROLLMENT", "VERIFIED")
    assert is_iso8601_timestamp(data["enrolled_at"])
    assert data["verified_at"] is None or is_iso8601_timestamp(data["verified_at"])
    assert isinstance(data["records_waived"], bool)


def assert_governance_proposal(data: dict):
    assert_common_audit_fields(data, "GovernanceProposal")
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 160
    assert data["category"] in (
        "HOUSE_RULES", "PROGRAMMING", "GRIEVANCE_PROCESS", "FOOD_SERVICE"
    )
    assert data["status"] in ("OPEN_FOR_VOTE", "ADOPTED", "REJECTED")
    assert is_iso8601_timestamp(data["voting_closes_at"])
    for counter in ("support_vote_count", "oppose_vote_count", "eligible_electorate_size",
                    "support_ratio_bp"):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"GovernanceProposal.{counter} must be a non-negative integer, got {data[counter]!r}"
        )
    assert data["adopted_at"] is None or is_iso8601_timestamp(data["adopted_at"])


def assert_governance_vote(data: dict):
    assert_common_audit_fields(data, "GovernanceVote")
    assert data["stance"] in ("SUPPORT", "OPPOSE")
    assert data["status"] in ("COUNTED", "RETRACTED")
    assert is_iso8601_timestamp(data["cast_at"])
    assert data["retracted_at"] is None or is_iso8601_timestamp(data["retracted_at"])


# ─── Domain invariant checkers ────────────────────────


def assert_risk_tier_matches_score(score: int, tier: str):
    """The tier is `CRITICAL` at a score of 60 or more, `ELEVATED` at 30 or more,
    and `LOW` below 30."""
    if score >= THRESHOLDS["TIER_CRITICAL_SCORE"]:
        expected = "CRITICAL"
    elif score >= THRESHOLDS["TIER_ELEVATED_SCORE"]:
        expected = "ELEVATED"
    else:
        expected = "LOW"
    assert tier == expected, f"A score of {score} tiers as {expected}, got {tier}"


def expected_utilization_bp(occupied_beds: int, licensed_bed_capacity: int) -> int:
    """Occupied beds multiplied by 10000, divided by licensed capacity, floored."""
    return (occupied_beds * BASIS_POINTS_WHOLE) // licensed_bed_capacity


def expected_posture(occupied_beds: int, licensed_bed_capacity: int,
                     overdue_notification_count: int) -> str:
    """The three posture clauses, evaluated from the top down."""
    utilization = expected_utilization_bp(occupied_beds, licensed_bed_capacity)
    if (occupied_beds >= licensed_bed_capacity
            or overdue_notification_count >= THRESHOLDS["FROZEN_OVERDUE_COUNT"]):
        return "FROZEN"
    if (utilization >= THRESHOLDS["RESTRICTED_UTILIZATION_BP"]
            or overdue_notification_count == THRESHOLDS["RESTRICTED_OVERDUE_COUNT"]):
        return "RESTRICTED"
    return "OPEN"


def assert_program_counters(program: dict):
    """`utilization_bp` and `posture` must agree with the program's own counters."""
    utilization = expected_utilization_bp(
        program["occupied_beds"], program["licensed_bed_capacity"]
    )
    assert program["utilization_bp"] == utilization, (
        f"utilization_bp should be {utilization} for {program['occupied_beds']} of "
        f"{program['licensed_bed_capacity']} beds, got {program['utilization_bp']}"
    )
    posture = expected_posture(
        program["occupied_beds"],
        program["licensed_bed_capacity"],
        program["overdue_notification_count"],
    )
    assert program["posture"] == posture, (
        f"posture should be {posture} at occupied_beds={program['occupied_beds']}, "
        f"capacity={program['licensed_bed_capacity']}, "
        f"overdue={program['overdue_notification_count']}, got {program['posture']}"
    )
    assert program["occupied_beds"] <= program["licensed_bed_capacity"], (
        "the licensed bed capacity is a hard federal ceiling and is never exceeded"
    )


def assert_savings_identity(placement: dict, entries: List[dict]):
    """`savings_balance_cents` is the sum of `signed_amount_cents` over every entry
    plus the capped `match_awarded_cents`."""
    signed_total = sum(entry["signed_amount_cents"] for entry in entries)
    match_total = sum(entry["match_component_cents"] for entry in entries)
    capped_match = min(max(match_total, 0), THRESHOLDS["MATCH_CAP_CENTS"])
    assert placement["match_awarded_cents"] == capped_match, (
        f"match_awarded_cents should be {capped_match} (per-entry matches summed, "
        f"floored at zero and capped at 50000), got {placement['match_awarded_cents']}"
    )
    expected_balance = signed_total + capped_match
    assert placement["savings_balance_cents"] == expected_balance, (
        f"savings_balance_cents should be {expected_balance} "
        f"({signed_total} signed + {capped_match} match), "
        f"got {placement['savings_balance_cents']}"
    )


def assert_census_counts(data: dict, **expected):
    """The census epoch answers with a count of the work it did in seven integers."""
    keys = (
        "overdue_marked", "admissions_denied", "admissions_promoted", "placements_noticed",
        "placements_exited", "cases_closed", "postures_recomputed",
    )
    for key in keys:
        assert key in data, f"The census response must report {key}"
        assert isinstance(data[key], int), f"census.{key} must be an integer, got {data[key]!r}"
    for key, value in expected.items():
        assert data[key] == value, f"Expected census.{key} == {value}, got {data[key]}"


def assert_compliance_report(data: dict):
    """The federal report answers with sixteen figures."""
    integer_figures = (
        "discharged_count", "billable_nights_total", "average_stay_nights_bp",
        "over_limit_admission_count", "positive_outcome_count", "positive_outcome_rate_bp",
        "waived_notification_count", "runaway_report_count", "licensed_bed_capacity",
        "occupied_beds", "waitlisted_count", "utilization_bp", "overdue_notification_count",
    )
    for figure in integer_figures:
        assert figure in data, f"The compliance report must report {figure}"
        assert isinstance(data[figure], int), (
            f"report.{figure} must be an integer, got {data[figure]!r}"
        )
    assert isinstance(data["bed_capacity_compliant"], bool)
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert data["bed_capacity_compliant"] == (
        data["occupied_beds"] <= data["licensed_bed_capacity"]
    ), "bed_capacity_compliant is true exactly when occupied_beds is at or below capacity"


def assert_clock_response(data: dict, current_utc: str, previous_utc: str):
    """The clock endpoint answers with the new value and the value it replaced."""
    assert_instant_equals(data["current_utc"], current_utc, "current_utc")
    assert_instant_equals(data["previous_utc"], previous_utc, "previous_utc")
