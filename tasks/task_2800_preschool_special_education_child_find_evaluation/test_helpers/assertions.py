"""Reusable assertions: envelope shape, common fields, per-entity shape, invariants.

Timestamp comparisons always go through :func:`same_instant` / :func:`assert_instant`
so that a difference in sub-second rendering width can never fake a failure.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import date_part, utc


# --------------------------------------------------------------- timestamp shape
def same_instant(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO 8601 strings denote the same instant, whatever their width."""
    if left is None or right is None:
        return left is None and right is None
    return utc(left) == utc(right)


def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    assert same_instant(actual, expected), f"{label}: expected {expected!r}, got {actual!r}"


def assert_timestamp(value: Any, label: str = "timestamp") -> None:
    """A server-rendered ISO 8601 UTC timestamp."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not an ISO 8601 timestamp: {value!r}"
    # Parsing must succeed regardless of how many fractional digits were rendered.
    utc(value)


def assert_calendar_date(value: Any, label: str = "date") -> None:
    """A plain ``YYYY-MM-DD`` calendar date."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{label} must be a plain calendar date, got {value!r}"
    )
    int(value[0:4]), int(value[5:7]), int(value[8:10])


def assert_date_equals(actual: Any, expected: str, label: str = "date") -> None:
    assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"


# ------------------------------------------------------------------ common fields
def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every persisted resource carries ``id``, ``created_at``, ``updated_at``, ``version``."""
    assert "id" in entity, "entity is missing id"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert not str(entity["id"]).startswith(("child_", "prov_", "id_")), (
        f"id must carry no type prefix: {entity['id']!r}"
    )
    assert_timestamp(entity.get("created_at"), "created_at")
    assert_timestamp(entity.get("updated_at"), "updated_at")
    version = entity.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"version must be an integer, got {version!r}"
    )
    assert version >= 1, f"version must begin at 1, got {version}"
    if expected_version is not None:
        assert version == expected_version, (
            f"version: expected {expected_version}, got {version}"
        )


def assert_version_incremented(before: Dict[str, Any], after: Dict[str, Any], by: int = 1) -> None:
    """A mutation advances ``version`` by exactly ``by``."""
    assert after["version"] == before["version"] + by, (
        f"version: expected {before['version']} + {by}, got {after['version']}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert after["version"] == before["version"], (
        f"version must be unchanged at {before['version']}, got {after['version']}"
    )


def assert_fields_absent(entity: Dict[str, Any], *names: str) -> None:
    """Each named field is either missing or null."""
    for name in names:
        assert entity.get(name) is None, f"{name} must be absent, got {entity.get(name)!r}"


def assert_fields_present(entity: Dict[str, Any], *names: str) -> None:
    for name in names:
        assert name in entity, f"{name} must be present in the response"


def assert_subset(entity: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Every key of ``expected`` matches the entity."""
    for key, value in expected.items():
        assert entity.get(key) == value, (
            f"{key}: expected {value!r}, got {entity.get(key)!r}"
        )


def assert_number(value: Any, label: str = "value") -> None:
    """A JSON number, not a numeric string."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {value!r} ({type(value).__name__})"
    )


def assert_int(value: Any, label: str = "value") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be a JSON integer, got {value!r} ({type(value).__name__})"
    )


# -------------------------------------------------------------------- pagination
def assert_page_meta(
    meta: Dict[str, Any],
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_total: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    """The four pagination fields a list endpoint must carry."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"list meta is missing {field}"
    assert_int(meta["limit"], "meta.limit")
    assert_int(meta["offset"], "meta.offset")
    assert_int(meta["total_count"], "meta.total_count")
    assert isinstance(meta["has_more"], bool), "meta.has_more must be a boolean"
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            f"meta.limit: expected {expected_limit}, got {meta['limit']}"
        )
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"meta.offset: expected {expected_offset}, got {meta['offset']}"
        )
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"meta.total_count: expected {expected_total}, got {meta['total_count']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"meta.has_more: expected {expected_has_more}, got {meta['has_more']}"
        )


def assert_ordered_by_created_at(rows: List[Dict[str, Any]]) -> None:
    """List results are ordered by ``created_at`` ascending."""
    instants = [utc(row["created_at"]) for row in rows]
    assert instants == sorted(instants), "rows are not ordered by created_at ascending"


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_contains_id(rows: Iterable[Dict[str, Any]], row_id: str) -> None:
    listed = ids_of(rows)
    assert row_id in listed, f"{row_id} is missing from the listing {listed}"


def assert_excludes_id(rows: Iterable[Dict[str, Any]], row_id: str) -> None:
    listed = ids_of(rows)
    assert row_id not in listed, f"{row_id} must not appear in the listing {listed}"


def assert_all_have(rows: Iterable[Dict[str, Any]], field: str, value: Any) -> None:
    for row in rows:
        assert row.get(field) == value, (
            f"row {row.get('id')} has {field}={row.get(field)!r}, expected {value!r}"
        )


# ----------------------------------------------------------------- entity shapes
def assert_child(child: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(child, expected_version)
    for field in (
        "first_name",
        "last_name",
        "guardian_full_name",
        "district_of_residence",
        "primary_language_code",
        "status",
    ):
        assert isinstance(child.get(field), str), f"child.{field} must be a string"
    assert_calendar_date(child.get("date_of_birth"), "child.date_of_birth")
    assert_calendar_date(child.get("third_birthday"), "child.third_birthday")
    assert_calendar_date(
        child.get("kindergarten_eligibility_date"), "child.kindergarten_eligibility_date"
    )
    assert isinstance(child.get("interpreter_required"), bool), (
        "child.interpreter_required must be a boolean"
    )
    assert isinstance(child.get("part_c_enrolled"), bool), (
        "child.part_c_enrolled must be a boolean"
    )


def assert_community_site(site: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(site, expected_version)
    assert isinstance(site.get("name"), str), "site.name must be a string"
    assert isinstance(site.get("region_code"), str), "site.region_code must be a string"
    assert_int(site.get("licensed_capacity"), "site.licensed_capacity")
    assert_int(site.get("iep_seat_capacity"), "site.iep_seat_capacity")
    assert_int(site.get("reserved_iep_seat_count"), "site.reserved_iep_seat_count")
    assert isinstance(site.get("languages_supported"), list), (
        "site.languages_supported must be a list"
    )
    assert isinstance(site.get("screening_host_approved"), bool), (
        "site.screening_host_approved must be a boolean"
    )
    assert isinstance(site.get("status"), str), "site.status must be a string"


def assert_provider(provider: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(provider, expected_version)
    assert isinstance(provider.get("full_name"), str), "provider.full_name must be a string"
    assert isinstance(provider.get("discipline"), str), "provider.discipline must be a string"
    assert isinstance(provider.get("languages"), list), "provider.languages must be a list"
    assert isinstance(provider.get("home_region_code"), str), (
        "provider.home_region_code must be a string"
    )
    assert isinstance(provider.get("status"), str), "provider.status must be a string"
    for field in (
        "max_weekly_service_minutes",
        "direct_weekly_service_minutes",
        "travel_overhead_minutes",
        "assigned_weekly_service_minutes",
        "max_evaluation_caseload",
        "active_evaluation_count",
        "max_weekly_interpreter_assignments",
        "assigned_interpreter_assignment_count",
    ):
        assert_int(provider.get(field), f"provider.{field}")
    assert isinstance(provider.get("service_capacity_posture"), str), (
        "provider.service_capacity_posture must be a string"
    )
    assert isinstance(provider.get("evaluation_intake_posture"), str), (
        "provider.evaluation_intake_posture must be a string"
    )
    assert isinstance(provider.get("is_evaluation_chair_eligible"), bool), (
        "provider.is_evaluation_chair_eligible must be a boolean"
    )


def assert_screening_event(event: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(event, expected_version)
    assert is_valid_uuid(event.get("site_id", "")), "event.site_id must be a UUID"
    assert isinstance(event.get("event_label"), str), "event.event_label must be a string"
    assert_timestamp(event.get("window_start_utc"), "event.window_start_utc")
    assert_timestamp(event.get("window_end_utc"), "event.window_end_utc")
    for field in (
        "slot_length_minutes",
        "slot_capacity",
        "effective_slot_capacity",
        "booked_slot_count",
    ):
        assert_int(event.get(field), f"event.{field}")
    assert isinstance(event.get("interpreter_languages"), list), (
        "event.interpreter_languages must be a list"
    )
    assert isinstance(event.get("status"), str), "event.status must be a string"


def assert_screening_slot(slot: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(slot, expected_version)
    assert is_valid_uuid(slot.get("screening_event_id", "")), (
        "slot.screening_event_id must be a UUID"
    )
    assert is_valid_uuid(slot.get("child_id", "")), "slot.child_id must be a UUID"
    assert_timestamp(slot.get("slot_start_utc"), "slot.slot_start_utc")
    assert_timestamp(slot.get("slot_end_utc"), "slot.slot_end_utc")
    assert isinstance(slot.get("requested_language_code"), str), (
        "slot.requested_language_code must be a string"
    )
    assert isinstance(slot.get("status"), str), "slot.status must be a string"


def assert_referral(referral: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(referral, expected_version)
    assert is_valid_uuid(referral.get("child_id", "")), "referral.child_id must be a UUID"
    assert isinstance(referral.get("source"), str), "referral.source must be a string"
    assert_timestamp(referral.get("received_at"), "referral.received_at")
    assert_int(referral.get("age_months_at_referral"), "referral.age_months_at_referral")
    assert isinstance(referral.get("eligibility_pathway"), str), (
        "referral.eligibility_pathway must be a string"
    )
    assert isinstance(referral.get("intake_status"), str), (
        "referral.intake_status must be a string"
    )
    assert isinstance(referral.get("consent_status"), str), (
        "referral.consent_status must be a string"
    )


def assert_consent_record(record: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(record, expected_version)
    assert is_valid_uuid(record.get("referral_id", "")), "consent.referral_id must be a UUID"
    assert isinstance(record.get("kind"), str), "consent.kind must be a string"
    assert_timestamp(record.get("requested_at"), "consent.requested_at")
    assert isinstance(record.get("decision"), str), "consent.decision must be a string"
    assert isinstance(record.get("notice_language_code"), str), (
        "consent.notice_language_code must be a string"
    )
    assert isinstance(record.get("notice_delivery_method"), str), (
        "consent.notice_delivery_method must be a string"
    )


def assert_evaluation_case(case: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(case, expected_version)
    assert is_valid_uuid(case.get("referral_id", "")), "case.referral_id must be a UUID"
    assert is_valid_uuid(case.get("child_id", "")), "case.child_id must be a UUID"
    assert is_valid_uuid(case.get("chair_provider_id", "")), (
        "case.chair_provider_id must be a UUID"
    )
    for field in (
        "required_domain_count",
        "completed_domain_count",
        "qualifying_domain_count",
        "recommended_weekly_minutes",
        "revision_round",
    ):
        assert_int(case.get(field), f"case.{field}")
    assert isinstance(case.get("composite_eligibility_recommendation"), str), (
        "case.composite_eligibility_recommendation must be a string"
    )
    assert_calendar_date(case.get("due_date"), "case.due_date")
    assert isinstance(case.get("timeline_compliance"), str), (
        "case.timeline_compliance must be a string"
    )
    assert isinstance(case.get("status"), str), "case.status must be a string"
    if case.get("max_weighted_percent_delay") is not None:
        assert_number(case["max_weighted_percent_delay"], "case.max_weighted_percent_delay")


def assert_domain_assessment(
    assessment: Dict[str, Any], expected_version: Optional[int] = None
) -> None:
    assert_common_fields(assessment, expected_version)
    assert is_valid_uuid(assessment.get("evaluation_case_id", "")), (
        "assessment.evaluation_case_id must be a UUID"
    )
    assert is_valid_uuid(assessment.get("evaluator_provider_id", "")), (
        "assessment.evaluator_provider_id must be a UUID"
    )
    assert isinstance(assessment.get("domain"), str), "assessment.domain must be a string"
    assert isinstance(assessment.get("method"), str), "assessment.method must be a string"
    assert_timestamp(assessment.get("window_start_utc"), "assessment.window_start_utc")
    assert_timestamp(assessment.get("window_end_utc"), "assessment.window_end_utc")
    assert_int(assessment.get("chronological_age_months"), "assessment.chronological_age_months")
    assert isinstance(assessment.get("qualifies_delay"), bool), (
        "assessment.qualifies_delay must be a boolean"
    )
    assert isinstance(assessment.get("status"), str), "assessment.status must be a string"
    for field in ("percent_delay", "weighted_percent_delay", "standard_score"):
        if assessment.get(field) is not None:
            assert_number(assessment[field], f"assessment.{field}")


def assert_service_plan(plan: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(plan, expected_version)
    assert is_valid_uuid(plan.get("evaluation_case_id", "")), (
        "plan.evaluation_case_id must be a UUID"
    )
    assert is_valid_uuid(plan.get("child_id", "")), "plan.child_id must be a UUID"
    assert isinstance(plan.get("eligibility_decision"), str), (
        "plan.eligibility_decision must be a string"
    )
    assert_int(plan.get("recommended_weekly_minutes"), "plan.recommended_weekly_minutes")
    assert_int(plan.get("assigned_weekly_minutes"), "plan.assigned_weekly_minutes")
    assert isinstance(plan.get("determined_by_user_id"), str), (
        "plan.determined_by_user_id must be a string"
    )
    assert isinstance(plan.get("kindergarten_transition_status"), str), (
        "plan.kindergarten_transition_status must be a string"
    )
    assert isinstance(plan.get("status"), str), "plan.status must be a string"


def assert_service_line(line: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    assert_common_fields(line, expected_version)
    assert is_valid_uuid(line.get("service_plan_id", "")), "line.service_plan_id must be a UUID"
    assert isinstance(line.get("discipline"), str), "line.discipline must be a string"
    assert_int(line.get("weekly_minutes"), "line.weekly_minutes")
    assert isinstance(line.get("delivery_model"), str), "line.delivery_model must be a string"
    assert isinstance(line.get("status"), str), "line.status must be a string"


# ---------------------------------------------------------------------- invariants
def assert_provider_minute_ledger(
    provider: Dict[str, Any],
    expected_direct: int,
    expected_travel: int,
    expected_assigned: int,
    expected_posture: Optional[str] = None,
) -> None:
    """The three minute figures and, optionally, the posture derived from them."""
    assert provider["direct_weekly_service_minutes"] == expected_direct, (
        "direct_weekly_service_minutes: expected "
        f"{expected_direct}, got {provider['direct_weekly_service_minutes']}"
    )
    assert provider["travel_overhead_minutes"] == expected_travel, (
        "travel_overhead_minutes: expected "
        f"{expected_travel}, got {provider['travel_overhead_minutes']}"
    )
    assert provider["assigned_weekly_service_minutes"] == expected_assigned, (
        "assigned_weekly_service_minutes: expected "
        f"{expected_assigned}, got {provider['assigned_weekly_service_minutes']}"
    )
    if expected_posture is not None:
        assert provider["service_capacity_posture"] == expected_posture, (
            "service_capacity_posture: expected "
            f"{expected_posture}, got {provider['service_capacity_posture']}"
        )


def minute_ledger(provider: Dict[str, Any]) -> Dict[str, Any]:
    """The provider figures that must be restored exactly when a line is released."""
    return {
        "direct_weekly_service_minutes": provider["direct_weekly_service_minutes"],
        "travel_overhead_minutes": provider["travel_overhead_minutes"],
        "assigned_weekly_service_minutes": provider["assigned_weekly_service_minutes"],
        "service_capacity_posture": provider["service_capacity_posture"],
    }


def assert_ledger_restored(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """Releasing a provider restores its minute figures with no residue."""
    assert minute_ledger(before) == minute_ledger(after), (
        f"minute ledger not restored: before {minute_ledger(before)}, after {minute_ledger(after)}"
    )


def assert_composite_profile(
    case: Dict[str, Any],
    completed_domain_count: int,
    qualifying_domain_count: int,
    max_weighted_percent_delay: Optional[float],
    recommendation: str,
    recommended_weekly_minutes: int,
) -> None:
    assert case["completed_domain_count"] == completed_domain_count, (
        f"completed_domain_count: expected {completed_domain_count}, "
        f"got {case['completed_domain_count']}"
    )
    assert case["qualifying_domain_count"] == qualifying_domain_count, (
        f"qualifying_domain_count: expected {qualifying_domain_count}, "
        f"got {case['qualifying_domain_count']}"
    )
    assert case["max_weighted_percent_delay"] == max_weighted_percent_delay, (
        f"max_weighted_percent_delay: expected {max_weighted_percent_delay}, "
        f"got {case['max_weighted_percent_delay']}"
    )
    assert case["composite_eligibility_recommendation"] == recommendation, (
        f"composite_eligibility_recommendation: expected {recommendation}, "
        f"got {case['composite_eligibility_recommendation']}"
    )
    assert case["recommended_weekly_minutes"] == recommended_weekly_minutes, (
        f"recommended_weekly_minutes: expected {recommended_weekly_minutes}, "
        f"got {case['recommended_weekly_minutes']}"
    )


def assert_delay_figures(
    assessment: Dict[str, Any],
    percent_delay: Optional[float],
    weighted_percent_delay: Optional[float],
    qualifies_delay: bool,
) -> None:
    assert assessment["percent_delay"] == percent_delay, (
        f"percent_delay: expected {percent_delay}, got {assessment['percent_delay']}"
    )
    assert assessment["weighted_percent_delay"] == weighted_percent_delay, (
        f"weighted_percent_delay: expected {weighted_percent_delay}, "
        f"got {assessment['weighted_percent_delay']}"
    )
    assert assessment["qualifies_delay"] is qualifies_delay, (
        f"qualifies_delay: expected {qualifies_delay}, got {assessment['qualifies_delay']}"
    )


def assert_clock_date(entity_field: Optional[str], expected_instant: str, label: str) -> None:
    """A date field stamped from the logical clock's current date."""
    assert entity_field == date_part(expected_instant), (
        f"{label}: expected {date_part(expected_instant)!r}, got {entity_field!r}"
    )
