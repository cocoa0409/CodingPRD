"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared
operations, because the server restarts with an empty database before
each individual test.

Five tiers:
  1. State progression     — walk an entity to a non-initial state
  2. Entity hierarchy      — region / pathway / district / school / member
  3. Lifecycle shortcuts   — create -> confirm -> activate, verify chains
  4. Accumulation          — drive counters and derived values to a target
  5. Terminal state        — reach a lifecycle end state
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import build_user_headers, get_success_data

from .api_client import api_client
from .constants import OPERATORS, TEST_DEFAULTS as D
from .factories import (
    create_applicant_payload,
    create_application_payload,
    create_certification_pathway_payload,
    create_partner_district_payload,
    create_partner_school_payload,
    create_placement_payload,
    create_region_payload,
)

# ─── Header aliases ───────────────────────────────────
ADMIN = build_user_headers("test-admin-1", "PlatformAdmin")
SELECTION_MANAGER = build_user_headers(OPERATORS["REVIEWER"], "SelectionManager")
REVIEWER = build_user_headers(OPERATORS["REVIEWER"], "SelectionManager")
REVIEWER_2 = build_user_headers(OPERATORS["REVIEWER_2"], "SelectionManager")
DECIDER = build_user_headers(OPERATORS["DECIDER"], "SelectionManager")
DECIDER_2 = build_user_headers(OPERATORS["DECIDER_2"], "SelectionManager")
PLACEMENT_COORDINATOR = build_user_headers("test-pc-1", "PlacementCoordinator")
INSTITUTE_DIRECTOR = build_user_headers("test-id-1", "InstituteDirector")
COMPLETER = build_user_headers(OPERATORS["COMPLETER"], "CertificationOfficer")
VERIFIER = build_user_headers(OPERATORS["VERIFIER"], "CertificationOfficer")
CERTIFICATION_OFFICER = COMPLETER
COACH = build_user_headers(OPERATORS["COACH"], "Coach")

MILESTONE_ORDER = ["COURSEWORK", "PRACTICUM", "ORIENTATION", "EXAM"]


def applicant_headers(applicant_id: str) -> dict:
    """Ownership-carrying headers for the Applicant role."""
    return build_user_headers(applicant_id, "Applicant")


def _ok(response, label: str) -> dict:
    """Setup step: accept any 2xx and return the data payload."""
    try:
        return get_success_data(response)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {label}: {exc}") from exc


# ═══ Tier 1: state progression ═══════════════════════

def create_region(**overrides) -> dict:
    return _ok(
        api_client.create_region(create_region_payload(**overrides), ADMIN),
        "POST /corps/regions",
    )


def create_pathway(region_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_certification_pathway(
            create_certification_pathway_payload(region_id, **overrides), ADMIN
        ),
        "POST /corps/certification-pathways",
    )


def create_district(region_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_partner_district(
            create_partner_district_payload(region_id, **overrides), ADMIN
        ),
        "POST /corps/partner-districts",
    )


def create_school(district: dict, **overrides) -> dict:
    """Create a school under a district, consuming the district's live version."""
    return _ok(
        api_client.create_partner_school(
            create_partner_school_payload(district["id"], district["version"], **overrides),
            ADMIN,
        ),
        "POST /corps/partner-schools",
    )


def get_district(district_id: str, projection: Optional[str] = None) -> dict:
    return _ok(
        api_client.get_partner_district(district_id, ADMIN, projection=projection),
        "GET /corps/partner-districts/{id}",
    )


def activate_district(district_id: str) -> dict:
    return _ok(
        api_client.set_partner_district_status(district_id, "ACTIVE", ADMIN),
        "POST /corps/partner-districts/{id}/status",
    )


def suspend_district(district_id: str) -> dict:
    return _ok(
        api_client.set_partner_district_status(district_id, "SUSPENDED", ADMIN),
        "POST /corps/partner-districts/{id}/status",
    )


def create_applicant(**overrides) -> dict:
    return _ok(
        api_client.create_applicant(create_applicant_payload(**overrides), SELECTION_MANAGER),
        "POST /corps/applicants",
    )


def create_application(applicant_id: str, region_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_application(
            create_application_payload(applicant_id, region_id, **overrides), SELECTION_MANAGER
        ),
        "POST /corps/applications",
    )


def review(application_id: str, verified_gpa: float, headers: Optional[dict] = None) -> dict:
    return _ok(
        api_client.review_application(application_id, verified_gpa, headers or REVIEWER),
        "POST /corps/applications/{id}/review",
    )


def decide(application_id: str, decision: str, headers: Optional[dict] = None, **kwargs) -> dict:
    return _ok(
        api_client.decide_application(application_id, decision, headers or DECIDER, **kwargs),
        "POST /corps/applications/{id}/decision",
    )


def extend_offer(application_id: str) -> dict:
    return _ok(
        api_client.extend_offer(application_id, SELECTION_MANAGER),
        "POST /corps/applications/{id}/offer",
    )


def accept_offer(application_id: str, applicant_id: str) -> dict:
    return _ok(
        api_client.respond_to_offer(application_id, True, applicant_headers(applicant_id)),
        "POST /corps/applications/{id}/offer/respond",
    )


def set_clock(to_iso8601: str) -> None:
    _ok(api_client.set_current_utc(to_iso8601, ADMIN), "POST /corps/_clock/set_current_utc")


# ═══ Tier 2: entity hierarchy ════════════════════════

def setup_region_pathway_district_school(
    region_overrides: Optional[dict] = None,
    pathway_overrides: Optional[dict] = None,
    district_overrides: Optional[dict] = None,
    school_overrides: Optional[dict] = None,
    activate: bool = True,
) -> Dict[str, dict]:
    """Region + pathway + district (+ school), district optionally ACTIVE.

    Returns keys: region, pathway, district, school.
    """
    region = create_region(**(region_overrides or {}))
    pathway = create_pathway(region["id"], **(pathway_overrides or {}))
    district = create_district(region["id"], **(district_overrides or {}))
    school = create_school(district, **(school_overrides or {}))
    if activate:
        district = activate_district(district["id"])
    return {"region": region, "pathway": pathway, "district": district, "school": school}


def setup_selection_pipeline(
    region_overrides: Optional[dict] = None,
    applicant_overrides: Optional[dict] = None,
    application_overrides: Optional[dict] = None,
    verified_gpa: Optional[float] = None,
    review_operator: Optional[dict] = None,
    decide_operator: Optional[dict] = None,
    decision: str = "SELECT",
) -> Dict[str, dict]:
    """Region + applicant + application, optionally reviewed and decided."""
    region = create_region(**(region_overrides or {}))
    applicant = create_applicant(**(applicant_overrides or {}))
    application = create_application(applicant["id"], region["id"], **(application_overrides or {}))
    if verified_gpa is not None:
        application = review(application["id"], verified_gpa, review_operator)
    if decision is not None and verified_gpa is not None:
        application = decide(application["id"], decision, decide_operator)
    return {"region": region, "applicant": applicant, "application": application}


def setup_offered_application(
    region_overrides: Optional[dict] = None,
    pathway_overrides: Optional[dict] = None,
    district_overrides: Optional[dict] = None,
    school_overrides: Optional[dict] = None,
    applicant_overrides: Optional[dict] = None,
    application_overrides: Optional[dict] = None,
    verified_gpa: float = 4.0,
    offer_extended: bool = True,
) -> Dict[str, object]:
    """Everything needed to accept an offer: district ACTIVE, application offered."""
    infra = setup_region_pathway_district_school(
        region_overrides=region_overrides,
        pathway_overrides=pathway_overrides,
        district_overrides=district_overrides,
        school_overrides=school_overrides,
    )
    applicant = create_applicant(**(applicant_overrides or {}))
    application = create_application(
        applicant["id"], infra["region"]["id"], **(application_overrides or {})
    )
    application = review(application["id"], verified_gpa)
    application = decide(application["id"], "SELECT")
    if offer_extended:
        application = extend_offer(application["id"])
    return {
        **infra,
        "applicant": applicant,
        "application": application,
        "applicant_headers": applicant_headers(applicant["id"]),
    }


def setup_member_scenario(
    region_overrides: Optional[dict] = None,
    pathway_overrides: Optional[dict] = None,
    district_overrides: Optional[dict] = None,
    school_overrides: Optional[dict] = None,
    applicant_overrides: Optional[dict] = None,
    application_overrides: Optional[dict] = None,
    verified_gpa: float = 4.0,
) -> Dict[str, object]:
    """Full scenario through offer acceptance.

    Returns region, pathway, district, school, applicant, application,
    member_id and member (the synthesized CorpsMember).
    """
    offered = setup_offered_application(
        region_overrides=region_overrides,
        pathway_overrides=pathway_overrides,
        district_overrides=district_overrides,
        school_overrides=school_overrides,
        applicant_overrides=applicant_overrides,
        application_overrides=application_overrides,
        verified_gpa=verified_gpa,
    )
    accepted = accept_offer(offered["application"]["id"], offered["applicant"]["id"])
    member_id = accepted["created_corps_member_id"]
    return {
        **offered,
        "application": accepted,
        "member_id": member_id,
        "member": get_member(member_id),
    }


def get_member(member_id: str) -> dict:
    return _ok(
        api_client.get_corps_member(member_id, PLACEMENT_COORDINATOR),
        "GET /corps/corps-members/{id}",
    )


def list_milestones(member_id: str) -> List[dict]:
    data = _ok(
        api_client.list_member_milestones(member_id, CERTIFICATION_OFFICER),
        "GET /corps/corps-members/{id}/certification-milestones",
    )
    return data if isinstance(data, list) else []


def get_milestone(milestone_id: str) -> dict:
    return _ok(
        api_client.get_certification_milestone(milestone_id, CERTIFICATION_OFFICER),
        "GET /corps/certification-milestones/{id}",
    )


# Alias: the read endpoint is named for the resource it returns.
get_certification_milestone = get_milestone


def list_placements(member_id: str) -> List[dict]:
    data = _ok(
        api_client.list_member_placements(member_id, PLACEMENT_COORDINATOR),
        "GET /corps/corps-members/{id}/placements",
    )
    return data if isinstance(data, list) else []


def milestones_by_type(member_id: str) -> Dict[str, dict]:
    return {m["milestone_type"]: m for m in list_milestones(member_id)}


# ═══ Tier 3: lifecycle shortcuts ═════════════════════

def record_practice_hours(member_id: str, delta: int) -> dict:
    return _ok(
        api_client.record_practice_hours(member_id, delta, INSTITUTE_DIRECTOR),
        "POST /corps/corps-members/{id}/institute/practice-hours",
    )


def complete_institute(member_id: str) -> dict:
    return _ok(
        api_client.complete_institute(member_id, INSTITUTE_DIRECTOR),
        "POST /corps/corps-members/{id}/institute/complete",
    )


def start_milestone(milestone_id: str) -> dict:
    return _ok(
        api_client.start_certification_milestone(milestone_id, CERTIFICATION_OFFICER),
        "POST /corps/certification-milestones/{id}/start",
    )


def complete_milestone(milestone_id: str, headers: Optional[dict] = None) -> dict:
    return _ok(
        api_client.complete_certification_milestone(milestone_id, headers or COMPLETER),
        "POST /corps/certification-milestones/{id}/complete",
    )


def verify_milestone(milestone_id: str, outcome: str = "VERIFY", headers: Optional[dict] = None) -> dict:
    return _ok(
        api_client.verify_certification_milestone(milestone_id, outcome, headers or VERIFIER),
        "POST /corps/certification-milestones/{id}/verify",
    )


def complete_and_verify_milestone(milestone_id: str) -> dict:
    """PENDING|IN_PROGRESS -> COMPLETED -> VERIFIED with two distinct officers."""
    start_milestone(milestone_id)
    complete_milestone(milestone_id, COMPLETER)
    return verify_milestone(milestone_id, "VERIFY", VERIFIER)


def advance_milestone(milestone_id: str, target: str) -> dict:
    """Walk one milestone to the requested combined state."""
    if target == "IN_PROGRESS":
        return start_milestone(milestone_id)
    if target == "COMPLETED":
        start_milestone(milestone_id)
        return complete_milestone(milestone_id, COMPLETER)
    if target == "VERIFIED":
        return complete_and_verify_milestone(milestone_id)
    if target == "REJECTED":
        start_milestone(milestone_id)
        complete_milestone(milestone_id, COMPLETER)
        return verify_milestone(milestone_id, "REJECT", VERIFIER)
    raise ValueError(f"unsupported milestone target state: {target}")


def create_matched_placement(member_id: str, school_id: str, **overrides) -> dict:
    """Create a Placement, consuming the member's current version (OCC guard)."""
    member = get_member(member_id)
    payload = create_placement_payload(
        member_id, school_id, member["version"], **overrides
    )
    return _ok(
        api_client.create_placement(payload, PLACEMENT_COORDINATOR),
        "POST /corps/placements",
    )


def confirm_placement(placement_id: str) -> dict:
    return _ok(
        api_client.confirm_placement(placement_id, PLACEMENT_COORDINATOR),
        "POST /corps/placements/{id}/confirm",
    )


def activate_placement(placement_id: str) -> dict:
    return _ok(
        api_client.activate_placement(placement_id, PLACEMENT_COORDINATOR),
        "POST /corps/placements/{id}/activate",
    )


def create_confirmed_placement(member_id: str, school_id: str, **overrides) -> dict:
    placement = create_matched_placement(member_id, school_id, **overrides)
    return confirm_placement(placement["id"])


def create_active_placement(member_id: str, school_id: str, **overrides) -> dict:
    """Requires the member's institute to be COMPLETED and readiness >= 60.0."""
    placement = create_matched_placement(member_id, school_id, **overrides)
    placement = confirm_placement(placement["id"])
    return activate_placement(placement["id"])


def setup_member_with_institute_completed(**scenario_overrides) -> Dict[str, object]:
    """Member scenario + 240 practice hours + COMPLETED institute.

    Readiness is 30.00 and no milestone is verified, so employment
    eligibility stays false until verified hours reach the pathway floor.
    """
    scenario = setup_member_scenario(**scenario_overrides)
    record_practice_hours(scenario["member_id"], 240)
    complete_institute(scenario["member_id"])
    scenario["member"] = get_member(scenario["member_id"])
    return scenario


# ═══ Tier 4: accumulation / threshold targeting ══════

def _synthesize_member(
    infra: Dict[str, dict],
    applicant_overrides: Optional[dict] = None,
    application_overrides: Optional[dict] = None,
    verified_gpa: float = 4.0,
) -> Dict[str, object]:
    """Run one applicant through the selection pipeline to a CorpsMember."""
    applicant = create_applicant(**(applicant_overrides or {}))
    application = create_application(
        applicant["id"], infra["region"]["id"], **(application_overrides or {})
    )
    application = review(application["id"], verified_gpa, REVIEWER)
    application = decide(application["id"], "SELECT", DECIDER)
    application = extend_offer(application["id"])
    accepted = accept_offer(application["id"], applicant["id"])
    member_id = accepted["created_corps_member_id"]
    return {
        "applicant": applicant,
        "application": accepted,
        "member_id": member_id,
        "member": get_member(member_id),
    }


def setup_two_members(
    region_overrides: Optional[dict] = None,
    pathway_overrides: Optional[dict] = None,
    district_overrides: Optional[dict] = None,
    school_overrides: Optional[dict] = None,
) -> Dict[str, object]:
    """One region/district/school carrying two independently synthesized members."""
    infra = setup_region_pathway_district_school(
        region_overrides=region_overrides,
        pathway_overrides=pathway_overrides,
        district_overrides=district_overrides,
        school_overrides=school_overrides,
    )
    first = _synthesize_member(
        infra,
        applicant_overrides={"full_name": "Ada Rivera", "email": "ada@x.edu"},
        application_overrides={"subject_area": "MATH"},
    )
    second = _synthesize_member(
        infra,
        applicant_overrides={"full_name": "Bo Chen", "email": "bo@x.edu"},
        application_overrides={"subject_area": "SCIENCE"},
    )
    return {
        **infra,
        "member1_id": first["member_id"],
        "member1": first["member"],
        "applicant1": first["applicant"],
        "application1": first["application"],
        "member2_id": second["member_id"],
        "member2": second["member"],
        "applicant2": second["applicant"],
        "application2": second["application"],
    }


def setup_member_with_verified_hours(
    verified_types=("COURSEWORK",),
    practice_hours: int = 240,
    complete_institute_flag: bool = False,
    **scenario_overrides,
) -> Dict[str, object]:
    """Member whose named milestone types are COMPLETED and VERIFIED.

    Also records `practice_hours` practice-teaching hours first, so the
    milestone completion edges see an IN_TRAINING or COMPLETED institute.
    """
    scenario = setup_member_scenario(**scenario_overrides)
    member_id = scenario["member_id"]
    if practice_hours:
        record_practice_hours(member_id, practice_hours)
    if complete_institute_flag:
        complete_institute(member_id)
    milestones = milestones_by_type(member_id)
    for milestone_type in verified_types:
        complete_and_verify_milestone(milestones[milestone_type]["id"])
    scenario["milestones"] = milestones_by_type(member_id)
    scenario["verified_types"] = list(verified_types)
    scenario["member"] = get_member(member_id)
    return scenario


def setup_member_ready_for_activation(**scenario_overrides) -> Dict[str, object]:
    """Member with a COMPLETED institute and readiness 64.00.

    Verified COURSEWORK (60 of 240 required hours) plus 240 practice hours
    gives certified 0.25, practice 1.0 and coursework 1.0, so the subtotal is
    62.50 and the QUALIFIED credit lifts readiness to 64.00.
    """
    scenario = setup_member_with_verified_hours(
        verified_types=("COURSEWORK",),
        practice_hours=240,
        complete_institute_flag=True,
        **scenario_overrides,
    )
    return scenario


def setup_member_ready_to_activate_with_placement(**scenario_overrides) -> Dict[str, object]:
    """Ready-for-activation member plus a CONFIRMED placement at the school."""
    scenario = setup_member_ready_for_activation(**scenario_overrides)
    placement = create_confirmed_placement(scenario["member_id"], scenario["school"]["id"])
    scenario["placement"] = placement
    return scenario


def setup_member_at_deadline_boundary(**scenario_overrides) -> Dict[str, object]:
    """Member whose milestones are all due 2026-11-01 (term start minus 30 days)."""
    return setup_member_scenario(**scenario_overrides)


# ═══ Tier 5: terminal / late-lifecycle states ════════

def setup_member_with_active_placement(**scenario_overrides) -> Dict[str, object]:
    """Member with a COMPLETED institute, readiness 64.00 and an ACTIVE placement."""
    scenario = setup_member_ready_for_activation(**scenario_overrides)
    placement = create_active_placement(scenario["member_id"], scenario["school"]["id"])
    scenario["placement"] = placement
    scenario["district"] = get_district(scenario["district"]["id"])
    return scenario


def setup_exited_member(**scenario_overrides) -> Dict[str, object]:
    """Member walked to the terminal EXITED service state."""
    scenario = setup_member_scenario(**scenario_overrides)
    _ok(
        api_client.exit_corps_member(
            scenario["member_id"], "resigned before the term began", PLACEMENT_COORDINATOR
        ),
        "POST /corps/corps-members/{id}/exit",
    )
    scenario["member"] = get_member(scenario["member_id"])
    return scenario


def setup_member_with_full_verified_hours(**scenario_overrides) -> Dict[str, object]:
    """Member whose COURSEWORK and PRACTICUM milestones are COMPLETED and VERIFIED.

    certification_hours_verified is 180, which is exactly the pathway's
    combined practice (120) plus coursework (60) requirement.
    """
    return setup_member_with_verified_hours(
        verified_types=("COURSEWORK", "PRACTICUM"),
        practice_hours=240,
        complete_institute_flag=True,
        **scenario_overrides,
    )


def setup_member_with_fully_verified_schedule(**scenario_overrides) -> Dict[str, object]:
    """Every hour-bearing milestone COMPLETED and VERIFIED (240 of 240 hours)."""
    return setup_member_with_verified_hours(
        verified_types=("COURSEWORK", "PRACTICUM", "ORIENTATION"),
        practice_hours=240,
        complete_institute_flag=True,
        **scenario_overrides,
    )


def setup_member_for_eligibility_flip(**scenario_overrides) -> Dict[str, object]:
    """Member with a COMPLETED institute, COURSEWORK verified (60 hours) and a
    CONFIRMED placement, so employment_eligible is false only because the
    verified-hour floor of 180 has not been reached."""
    scenario = setup_member_with_verified_hours(
        verified_types=("COURSEWORK",),
        practice_hours=240,
        complete_institute_flag=True,
        **scenario_overrides,
    )
    placement = create_confirmed_placement(scenario["member_id"], scenario["school"]["id"])
    scenario["placement"] = placement
    return scenario
