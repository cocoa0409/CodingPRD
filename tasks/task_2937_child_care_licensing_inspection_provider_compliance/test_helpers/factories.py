"""Payload factories — one per creatable resource.

Each factory returns a complete, PRD-valid request body that callers override
with keyword arguments.  Optional fields are omitted unless a caller supplies
them, so the "omitted optionals take their declared defaults" rules stay
testable.  Numeric fields are emitted as JSON numbers, never as strings, and
instants are emitted as full ISO 8601 UTC instants rather than calendar dates
wherever the PRD asks for an instant.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CODE_BACKGROUND,
    CODE_FACILITY,
    CODE_NUTRITION,
    CODE_RATIO,
    CODE_RECORDS,
    CODE_SUPERVISION_PLAN,
    CODE_SUPERVISION,
)


def _drop_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


# ─── §3.1 Checklist catalog ────────────────────────────────────────────
def checklist_item_payload(
    code: str = CODE_SUPERVISION,
    title: str = "Direct supervision of children at all times",
    category: str = "SUPERVISION",
    default_severity: str = "CRITICAL",
    age_groups_applicable: Optional[List[str]] = None,
    infant_sensitive: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "code": code,
            "title": title,
            "category": category,
            "default_severity": default_severity,
            "age_groups_applicable": age_groups_applicable
            or ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"],
            "infant_sensitive": infant_sensitive,
        }
    )
    payload.update(overrides)
    return payload


#: The catalog rows every cascade in the PRD can reach by code, plus one extra
#: sanitation row that the point-arithmetic recipes cite alongside SU-101.
CATALOG_SEED: List[Dict[str, Any]] = [
    {
        "code": CODE_SUPERVISION,
        "title": "Direct supervision of children at all times",
        "category": "SUPERVISION",
        "default_severity": "CRITICAL",
        "age_groups_applicable": ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"],
        "infant_sensitive": True,
    },
    {
        "code": CODE_SUPERVISION_PLAN,
        "title": "Written supervision plan on file",
        "category": "SUPERVISION",
        "default_severity": "CRITICAL",
        "age_groups_applicable": ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"],
        "infant_sensitive": False,
    },
    {
        "code": CODE_RATIO,
        "title": "Staff-to-child ratio maintained in every room",
        "category": "RATIO",
        "default_severity": "SERIOUS",
        "age_groups_applicable": ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"],
        "infant_sensitive": False,
    },
    {
        "code": CODE_BACKGROUND,
        "title": "Background clearance on file for every adult",
        "category": "BACKGROUND_CHECK",
        "default_severity": "CRITICAL",
        "age_groups_applicable": ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"],
        "infant_sensitive": False,
    },
    {
        "code": CODE_FACILITY,
        "title": "Indoor and outdoor play areas free of hazards",
        "category": "FACILITY",
        "default_severity": "MODERATE",
        "age_groups_applicable": ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"],
        "infant_sensitive": False,
    },
    {
        "code": CODE_NUTRITION,
        "title": "Meals meet the published nutrition plan",
        "category": "NUTRITION",
        "default_severity": "MINOR",
        "age_groups_applicable": ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"],
        "infant_sensitive": False,
    },
    {
        "code": CODE_RECORDS,
        "title": "Records and mandated reports complete and timely",
        "category": "RECORDS",
        "default_severity": "MINOR",
        "age_groups_applicable": ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"],
        "infant_sensitive": False,
    },
]


# ─── §3.1 Inspector roll ───────────────────────────────────────────────
def inspector_payload(
    full_name: str = "Ivy Cole",
    county_code: str = "CTY-01",
    certified_age_groups: Optional[List[str]] = None,
    max_daily_visits: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "full_name": full_name,
            "county_code": county_code,
            "certified_age_groups": certified_age_groups
            or ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"],
            "max_daily_visits": max_daily_visits,
        }
    )
    payload.update(overrides)
    return payload


# ─── §3.2 Provider application ─────────────────────────────────────────
def provider_payload(
    legal_name: str = "Bright Start Center",
    county_code: str = "CTY-01",
    site_address: str = "12 Elm St",
    program_type: str = "CENTER",
    requested_capacity: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "legal_name": legal_name,
        "county_code": county_code,
        "site_address": site_address,
        "program_type": program_type,
        "requested_capacity": requested_capacity,
    }
    payload.update(overrides)
    return payload


# ─── §3.2 Staff members ────────────────────────────────────────────────
def staff_member_payload(
    provider_id: str,
    full_name: str = "Dana Reed",
    member_type: str = "DIRECTOR",
    date_of_birth: str = "1985-04-02",
    qualified_age_groups: Optional[List[str]] = None,
    role_title: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "provider_id": provider_id,
            "full_name": full_name,
            "member_type": member_type,
            "date_of_birth": date_of_birth,
            "qualified_age_groups": qualified_age_groups
            if qualified_age_groups is not None
            else ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"],
            "role_title": role_title,
        }
    )
    payload.update(overrides)
    return payload


# ─── §3.3 Background checks ────────────────────────────────────────────
def background_check_payload(
    staff_member_id: str, check_type: str = "FBI_FINGERPRINT", **overrides: Any
) -> Dict[str, Any]:
    payload = {"staff_member_id": staff_member_id, "check_type": check_type}
    payload.update(overrides)
    return payload


# ─── §3.2 Age-group rosters ────────────────────────────────────────────
def roster_payload(
    provider_id: str,
    age_group: str = "INFANT",
    requested_group_size: int = 8,
    enrolled_count: Optional[int] = None,
    staff_assigned_count: Optional[int] = None,
    lead_staff_member_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "provider_id": provider_id,
            "age_group": age_group,
            "requested_group_size": requested_group_size,
            "enrolled_count": enrolled_count,
            "staff_assigned_count": staff_assigned_count,
            "lead_staff_member_id": lead_staff_member_id,
        }
    )
    payload.update(overrides)
    return payload


# ─── §3.4 Inspections ──────────────────────────────────────────────────
def inspection_payload(
    provider_id: str,
    inspector_id: str,
    inspection_type: str = "INITIAL",
    scheduled_for: str = "2026-08-05T09:00:00Z",
    target_age_groups: Optional[List[str]] = None,
    duration_minutes: Optional[int] = None,
    complaint_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "provider_id": provider_id,
            "inspector_id": inspector_id,
            "inspection_type": inspection_type,
            "scheduled_for": scheduled_for,
            "target_age_groups": target_age_groups or ["INFANT"],
            "duration_minutes": duration_minutes,
            "complaint_id": complaint_id,
        }
    )
    payload.update(overrides)
    return payload


# ─── §3.5 Violations ───────────────────────────────────────────────────
def violation_payload(
    inspection_id: str,
    checklist_item_id: str,
    primary_age_group: str = "PRESCHOOL",
    narrative: str = "Room left without a supervising adult for several minutes.",
    severity_override: Optional[str] = None,
    repeat_of_violation_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "inspection_id": inspection_id,
            "checklist_item_id": checklist_item_id,
            "primary_age_group": primary_age_group,
            "narrative": narrative,
            "severity_override": severity_override,
            "repeat_of_violation_id": repeat_of_violation_id,
        }
    )
    payload.update(overrides)
    return payload


# ─── §3.7 Complaints ───────────────────────────────────────────────────
def complaint_payload(
    provider_id: str,
    intake_channel: str = "PHONE",
    allegation_category: str = "SUPERVISION",
    affected_age_group: str = "PRESCHOOL",
    narrative: str = "Caller reports a classroom left unattended at nap time.",
    alleged_serious_harm: Optional[bool] = None,
    complainant_name: Optional[str] = None,
    anonymous: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "provider_id": provider_id,
            "intake_channel": intake_channel,
            "allegation_category": allegation_category,
            "affected_age_group": affected_age_group,
            "narrative": narrative,
            "alleged_serious_harm": alleged_serious_harm,
            "complainant_name": complainant_name,
            "anonymous": anonymous,
        }
    )
    payload.update(overrides)
    return payload


# ─── §3.6 Corrective action plans ──────────────────────────────────────
def cap_payload(
    inspection_id: str,
    violation_ids: List[str],
    expected_inspection_version: int,
    narrative: str = "Retraining scheduled and supervision rota rewritten.",
    proposed_completion_date: str = "2026-08-20",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "inspection_id": inspection_id,
        "violation_ids": violation_ids,
        "narrative": narrative,
        "proposed_completion_date": proposed_completion_date,
        "expected_inspection_version": expected_inspection_version,
    }
    payload.update(overrides)
    return payload


def cap_resubmit_payload(
    violation_ids: List[str],
    narrative: str = "Revised plan with a named responsible manager.",
    proposed_completion_date: str = "2026-08-25",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "violation_ids": violation_ids,
        "narrative": narrative,
        "proposed_completion_date": proposed_completion_date,
    }
    payload.update(overrides)
    return payload


# ─── §3.8 Enforcement actions ──────────────────────────────────────────
def enforcement_action_payload(
    provider_id: str,
    requested_action_type: str = "WARNING",
    source_inspection_id: Optional[str] = None,
    rationale: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "provider_id": provider_id,
            "requested_action_type": requested_action_type,
            "source_inspection_id": source_inspection_id,
            "rationale": rationale,
        }
    )
    payload.update(overrides)
    return payload


# ─── §3.9 Licence amendments ───────────────────────────────────────────
def amendment_payload(
    provider_id: str,
    amendment_type: str,
    expected_provider_version: int,
    requested_capacity: Optional[int] = None,
    new_site_address: Optional[str] = None,
    new_age_group: Optional[str] = None,
    new_group_size: Optional[int] = None,
    new_director_staff_member_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "provider_id": provider_id,
            "amendment_type": amendment_type,
            "expected_provider_version": expected_provider_version,
            "requested_capacity": requested_capacity,
            "new_site_address": new_site_address,
            "new_age_group": new_age_group,
            "new_group_size": new_group_size,
            "new_director_staff_member_id": new_director_staff_member_id,
        }
    )
    payload.update(overrides)
    return payload


# ─── §3.7 Serious incident reports ─────────────────────────────────────
def incident_report_payload(
    provider_id: str,
    incident_type: str = "SERIOUS_INJURY",
    occurred_at: str = "2026-08-05T00:00:00Z",
    affected_child_age_group: str = "TODDLER",
    narrative: str = "Child required stitches after a fall in the play yard.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "provider_id": provider_id,
        "incident_type": incident_type,
        "occurred_at": occurred_at,
        "affected_child_age_group": affected_child_age_group,
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


# ─── §3.9 Public report postings ───────────────────────────────────────
def posting_payload(
    inspection_id: str,
    consumer_summary: str = "Annual visit completed; findings summarised for families.",
    redaction_complete: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _drop_none(
        {
            "inspection_id": inspection_id,
            "consumer_summary": consumer_summary,
            "redaction_complete": redaction_complete,
        }
    )
    payload.update(overrides)
    return payload
