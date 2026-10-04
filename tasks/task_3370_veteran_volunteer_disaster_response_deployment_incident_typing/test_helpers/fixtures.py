"""Composite setup helpers.

Multi-step PRD workflows (vetting, credentialing, call-up, muster, shifts,
triage, training) collapsed into reusable fixtures. Every fixture builds its
preconditions from scratch against an empty database using only PRD-declared
endpoints, and uses the lenient get_success_data validator so setup failures
surface as clear setup errors.

Identity threading: ownership-gated calls (volunteer accepting/declining own
offer, volunteer patching own record/enrollment, partner liaison referrals)
always use make_volunteer_headers / make_partner_liaison_headers with the
real entity id.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import (
    CERT_EXPIRES_AT,
    CERT_ISSUED_AT,
    CHECK_IN_CLOCK,
    CLOCK_START,
)
from .factories import (
    create_certification_payload,
    create_duty_shift_payload,
    create_fob_site_payload,
    create_incident_payload,
    create_operation_payload,
    create_partner_payload,
    create_training_course_payload,
    create_volunteer_payload,
    create_work_order_payload,
    offer_deployment_payload,
)
from .test_users import TEST_USERS, make_volunteer_headers

ADMIN = TEST_USERS["system_admin_headers"]
COMMANDER = TEST_USERS["incident_commander_headers"]
OPS_LEAD = TEST_USERS["operations_lead_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
TRAINING = TEST_USERS["training_director_headers"]


# ---------------------------------------------------------------------------
# Admin epochs
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_START) -> dict:
    """Advance the logical clock (SystemAdmin only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def run_ops_epoch() -> dict:
    """Run one housekeeping epoch (the six sweeps)."""
    return get_success_data(api_client.run_ops(ADMIN))


# ---------------------------------------------------------------------------
# Volunteers and certifications
# ---------------------------------------------------------------------------

def register_volunteer(**overrides) -> dict:
    """Register a volunteer (lands REGISTERED, scores 0, fatigue 0)."""
    payload = create_volunteer_payload(**overrides)
    return get_success_data(api_client.create_volunteer(payload, ADMIN))


def add_certification(volunteer_id: str, kind: str = "CHAINSAW",
                      issued_at: str = CERT_ISSUED_AT,
                      expires_at: str = CERT_EXPIRES_AT) -> dict:
    """Record a certification for a volunteer (lands PENDING_VERIFICATION)."""
    payload = create_certification_payload(kind=kind, issued_at=issued_at, expires_at=expires_at)
    return get_success_data(api_client.create_certification(volunteer_id, payload, TRAINING))


def verify_certification(certification_id: str, officer_id: str = "safety-officer-1") -> dict:
    """Verify a PENDING_VERIFICATION certification as SafetyOfficer."""
    from prd_bench_local_runner.testing import build_user_headers
    headers = build_user_headers(officer_id, "SafetyOfficer")
    return get_success_data(
        api_client.patch_certification(certification_id, {"status": "VERIFIED"}, headers)
    )


def transition_volunteer(volunteer_id: str, readiness_status: str) -> dict:
    """SafetyOfficer-driven readiness transition."""
    return get_success_data(
        api_client.patch_volunteer(volunteer_id, {"readiness_status": readiness_status}, SAFETY)
    )


def make_deployable_volunteer(cert_kinds=("CHAINSAW",), cert_expires: str = CERT_EXPIRES_AT,
                              **volunteer_overrides) -> dict:
    """Register + record/verify one cert per kind + VETTED + DEPLOYABLE.

    Returns the DEPLOYABLE volunteer dict (refetched state included).
    """
    skills = volunteer_overrides.pop("skills", list(cert_kinds))
    volunteer = register_volunteer(skills=skills, **volunteer_overrides)
    for kind in cert_kinds:
        cert = add_certification(volunteer["id"], kind=kind, expires_at=cert_expires)
        verify_certification(cert["id"])
    volunteer = transition_volunteer(volunteer["id"], "VETTED")
    volunteer = transition_volunteer(volunteer["id"], "DEPLOYABLE")
    return volunteer


def get_volunteer(volunteer_id: str) -> dict:
    return get_success_data(api_client.get_volunteer(volunteer_id, SAFETY))


def get_certification(certification_id: str) -> dict:
    return get_success_data(api_client.get_certification(certification_id, SAFETY))


# ---------------------------------------------------------------------------
# Incidents and operations
# ---------------------------------------------------------------------------

def report_incident(**overrides) -> dict:
    """Report an incident (lands REPORTED)."""
    return get_success_data(api_client.create_incident(create_incident_payload(**overrides), COMMANDER))


def transition_incident(incident_id: str, **payload) -> dict:
    return get_success_data(api_client.patch_incident(incident_id, payload, COMMANDER))


def setup_assessed_incident(severity: int = 4, affected_households: int = 120,
                            **overrides) -> dict:
    """Incident driven REPORTED -> ASSESSED."""
    incident = report_incident(**overrides)
    return transition_incident(incident["id"], status="ASSESSED",
                               severity=severity, affected_households=affected_households)


def setup_typed_incident(incident_type: str = "WIND", **overrides) -> dict:
    """Incident driven REPORTED -> ASSESSED -> TYPED."""
    incident = setup_assessed_incident(**overrides)
    return transition_incident(incident["id"], status="TYPED", incident_type=incident_type)


def create_operation(incident_id: str, **overrides) -> dict:
    """Create an operation under a TYPED incident (lands DRAFT, aar NONE)."""
    payload = create_operation_payload(**overrides)
    return get_success_data(api_client.create_operation(incident_id, payload, COMMANDER))


def transition_operation(operation_id: str, role_headers=None, **payload) -> dict:
    return get_success_data(
        api_client.patch_operation(operation_id, payload, role_headers or OPS_LEAD)
    )


def get_operation(operation_id: str) -> dict:
    return get_success_data(api_client.get_operation(operation_id, OPS_LEAD))


def setup_open_operation(incident_id: str = None, **op_overrides):
    """TYPED incident (unless one is supplied) + operation driven DRAFT -> OPEN.

    Returns (incident, operation).
    """
    incident = setup_typed_incident() if incident_id is None else get_incident(incident_id)
    iid = incident["id"] if incident_id is None else incident_id
    operation = create_operation(iid, **op_overrides)
    operation = transition_operation(operation["id"], status="OPEN")
    return incident, operation


def get_incident(incident_id: str) -> dict:
    return get_success_data(api_client.get_incident(incident_id, COMMANDER))


# ---------------------------------------------------------------------------
# Deployments, FOB sites, duty shifts
# ---------------------------------------------------------------------------

def offer_deployment(operation_id: str, volunteer_id: str, **overrides) -> dict:
    """Offer a deployment to a volunteer (lands OFFERED)."""
    payload = offer_deployment_payload(volunteer_id=volunteer_id, **overrides)
    return get_success_data(api_client.offer_deployment(operation_id, payload, OPS_LEAD))


def accept_deployment(deployment_id: str, volunteer_id: str) -> dict:
    """Volunteer accepts own offer (ownership-gated: X-User-ID == volunteer_id)."""
    return get_success_data(
        api_client.patch_deployment(
            deployment_id, {"status": "ACCEPTED"}, make_volunteer_headers(volunteer_id)
        )
    )


def decline_deployment(deployment_id: str, volunteer_id: str) -> dict:
    """Volunteer declines own offer (ownership-gated)."""
    return get_success_data(
        api_client.patch_deployment(
            deployment_id, {"status": "DECLINED"}, make_volunteer_headers(volunteer_id)
        )
    )


def check_in_deployment(deployment_id: str) -> dict:
    """OperationsLead checks an ACCEPTED deployment in (ACCEPTED -> ON_SITE)."""
    return get_success_data(
        api_client.patch_deployment(deployment_id, {"status": "ON_SITE"}, OPS_LEAD)
    )


def demobe_deployment(deployment_id: str) -> dict:
    """OperationsLead demobilizes a deployment (ON_SITE/SAFETY_HOLD -> DEMOBED)."""
    return get_success_data(
        api_client.patch_deployment(deployment_id, {"status": "DEMOBED"}, OPS_LEAD)
    )


def get_deployment(deployment_id: str) -> dict:
    return get_success_data(api_client.get_deployment(deployment_id, OPS_LEAD))


def create_fob_site(operation_id: str, **overrides) -> dict:
    """Establish a forward operating base (bunks_occupied 0, lodging 0)."""
    payload = create_fob_site_payload(**overrides)
    return get_success_data(api_client.create_fob_site(operation_id, payload, OPS_LEAD))


def get_fob_site(operation_id: str, fob_site_id: str) -> dict:
    """Fetch one FOB by scanning the operation's FOB list endpoint."""
    items = validate_success(api_client.list_fob_sites(operation_id, OPS_LEAD))
    data = items if isinstance(items, list) else items.get("data", [])
    for fob in data:
        if fob.get("id") == fob_site_id:
            return fob
    raise AssertionError(f"FobSite {fob_site_id} not found under operation {operation_id}")


def list_operation_fob_sites(operation_id: str) -> list:
    data = validate_success(api_client.list_fob_sites(operation_id, OPS_LEAD))
    return data if isinstance(data, list) else data.get("data", [])


def schedule_duty_shift(operation_id: str, deployment_id: str, kind: str = "OPERATIONS",
                        starts_at: str = "2026-09-10T08:00:00Z",
                        ends_at: str = "2026-09-10T18:00:00Z") -> dict:
    """Schedule a duty shift for an ON_SITE deployment."""
    payload = create_duty_shift_payload(
        deployment_id=deployment_id, kind=kind, starts_at=starts_at, ends_at=ends_at
    )
    return get_success_data(api_client.create_duty_shift(operation_id, payload, OPS_LEAD))


def list_deployment_shifts(deployment_id: str) -> list:
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_duty_shifts(OPS_LEAD, params={"deployment_id": deployment_id})
    data, _meta = validate_paginated(resp)
    return data


def setup_accepted_deployment(cert_kinds=("CHAINSAW",), volunteer_overrides=None,
                              op_overrides=None, offer_overrides=None,
                              with_fob=None) -> dict:
    """Clock pinned -> DEPLOYABLE volunteer -> TYPED incident -> OPEN operation
    (optional FOB) -> OFFERED -> ACCEPTED deployment.

    Returns {"volunteer", "incident", "operation", "deployment", "fob"}.
    """
    set_clock()
    volunteer = make_deployable_volunteer(cert_kinds=cert_kinds, **(volunteer_overrides or {}))
    incident, operation = setup_open_operation(**(op_overrides or {}))
    fob = create_fob_site(operation["id"], **with_fob) if with_fob else None
    deployment = offer_deployment(operation["id"], volunteer["id"], **(offer_overrides or {}))
    deployment = accept_deployment(deployment["id"], volunteer["id"])
    return {
        "volunteer": volunteer,
        "incident": incident,
        "operation": operation,
        "deployment": deployment,
        "fob": fob,
    }


def setup_on_site_deployment(cert_kinds=("CHAINSAW",), volunteer_overrides=None,
                             op_overrides=None, offer_overrides=None,
                             with_fob=None, at_clock: str = CHECK_IN_CLOCK) -> dict:
    """setup_accepted_deployment + clock advance + check-in -> ON_SITE.

    Returns the same bundle with the deployment in ON_SITE.
    """
    bundle = setup_accepted_deployment(
        cert_kinds=cert_kinds, volunteer_overrides=volunteer_overrides,
        op_overrides=op_overrides, offer_overrides=offer_overrides, with_fob=with_fob,
    )
    set_clock(at_clock)
    bundle["deployment"] = check_in_deployment(bundle["deployment"]["id"])
    return bundle


def setup_two_volunteer_operation(v1_cert_kinds=("CHAINSAW",), v2_cert_kinds=("MEDICAL",),
                                  required_capabilities=("CHAINSAW", "MEDICAL"),
                                  hazard_focus: str = "TREE_REMOVAL",
                                  team_size_required: int = 2, with_fob=None,
                                  d1_offer_overrides=None, d2_offer_overrides=None,
                                  at_clock: str = CHECK_IN_CLOCK) -> dict:
    """Two DEPLOYABLE volunteers; TYPED incident; op created -> OPEN; d1 (v1)
    and d2 (v2) offered and accepted; op MUSTERED; clock advanced; d1 checked
    in ON_SITE; op ACTIVE.

    Returns {"v1", "v2", "incident", "operation", "d1", "d2", "fob"}.
    """
    set_clock()
    v1 = make_deployable_volunteer(
        cert_kinds=v1_cert_kinds, full_name="Ada Voss", email="ada@x.org",
        skills=list(v1_cert_kinds),
    )
    v2 = make_deployable_volunteer(
        cert_kinds=v2_cert_kinds, full_name="Bo Karr", email="bo@x.org",
        skills=list(v2_cert_kinds),
    )
    incident, operation = setup_open_operation(
        hazard_focus=hazard_focus,
        team_size_required=team_size_required,
        required_capabilities=list(required_capabilities),
    )
    fob = create_fob_site(operation["id"], **with_fob) if with_fob else None
    d1 = offer_deployment(operation["id"], v1["id"], **(d1_offer_overrides or {}))
    d1 = accept_deployment(d1["id"], v1["id"])
    d2 = offer_deployment(
        operation["id"], v2["id"],
        **{"travel_mode": "TEAM_TRANSPORT", **(d2_offer_overrides or {})},
    )
    d2 = accept_deployment(d2["id"], v2["id"])
    operation = transition_operation(operation["id"], status="MUSTERED")
    set_clock(at_clock)
    d1 = check_in_deployment(d1["id"])
    operation = transition_operation(operation["id"], status="ACTIVE")
    return {
        "v1": v1, "v2": v2, "incident": incident, "operation": operation,
        "d1": d1, "d2": d2, "fob": fob,
    }


def schedule_and_complete_shifts(operation_id: str, deployment_id: str,
                                 shift_specs, ops_clock: str,
                                 kind: str = "OPERATIONS") -> list:
    """Schedule each (starts_at, ends_at) in shift_specs, then advance the
    clock to ops_clock and run one housekeeping epoch so every due shift
    completes and accrues fatigue. Returns the created shift dicts."""
    shifts = [
        schedule_duty_shift(operation_id, deployment_id, kind=kind,
                            starts_at=starts, ends_at=ends)
        for (starts, ends) in shift_specs
    ]
    set_clock(ops_clock)
    run_ops_epoch()
    return shifts


def setup_fatigued_volunteer(cert_kinds=("CHAINSAW",), volunteer_overrides=None,
                             shift_specs=(("2026-09-10T08:00:00Z", "2026-09-10T18:00:00Z"),),
                             ops_clock: str = "2026-09-10T19:00:00Z") -> dict:
    """ON_SITE deployment + completed shifts via ops run -> fatigue accrued.

    Default: one 10h OPERATIONS shift -> fatigue_hours == 10.
    Returns the on-site bundle plus "shifts".
    """
    bundle = setup_on_site_deployment(
        cert_kinds=cert_kinds, volunteer_overrides=volunteer_overrides,
    )
    shifts = schedule_and_complete_shifts(
        bundle["operation"]["id"], bundle["deployment"]["id"], shift_specs, ops_clock,
    )
    bundle["shifts"] = shifts
    bundle["volunteer"] = get_volunteer(bundle["volunteer"]["id"])
    return bundle


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------

def intake_work_order(incident_id: str, headers=None, **overrides) -> dict:
    """Intake a work order (lands INTAKE). Defaults to IntakeCoordinator
    (direct intake); pass liaison headers for a partner referral."""
    payload = create_work_order_payload(**overrides)
    return get_success_data(api_client.create_work_order(incident_id, payload, headers or INTAKE))


def triage_work_order_id(work_order_id: str, expected_version: int) -> dict:
    """OCC-guarded triage (INTAKE -> TRIAGED) carrying the observed version."""
    payload = {"expected_work_order_version": expected_version}
    return get_success_data(api_client.triage_work_order(work_order_id, payload, INTAKE))


def triage_work_order(work_order: dict) -> dict:
    """Triage using the version carried on the given work-order dict."""
    return triage_work_order_id(work_order["id"], work_order["version"])


def transition_work_order(work_order_id: str, role_headers, **payload) -> dict:
    return get_success_data(api_client.patch_work_order(work_order_id, payload, role_headers))


def get_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, INTAKE))


def setup_triaged_work_order(incident_id: str = None, **wo_overrides) -> dict:
    """Work order driven INTAKE -> TRIAGED. If no incident id is given, an
    ASSESSED incident is created first. Returns {"incident", "work_order"}."""
    incident = setup_assessed_incident() if incident_id is None else get_incident(incident_id)
    iid = incident["id"] if incident_id is None else incident_id
    work_order = intake_work_order(iid, **wo_overrides)
    work_order = triage_work_order(work_order)
    return {"incident": incident, "work_order": work_order}


def setup_in_progress_work_order() -> dict:
    """Two-volunteer ACTIVE operation + a TREE_REMOVAL work order driven
    INTAKE -> TRIAGED -> SCHEDULED -> IN_PROGRESS.

    Returns the two-volunteer bundle plus "wo1".
    """
    bundle = setup_two_volunteer_operation()
    work_order = intake_work_order(
        bundle["incident"]["id"], requester_name="Elderly Homeowner",
        hazard_kind="TREE_REMOVAL", vulnerable_resident=True,
    )
    work_order = triage_work_order(work_order)
    work_order = transition_work_order(
        work_order["id"], INTAKE, status="SCHEDULED", operation_id=bundle["operation"]["id"],
    )
    work_order = transition_work_order(work_order["id"], OPS_LEAD, status="IN_PROGRESS")
    bundle["wo1"] = work_order
    return bundle


# ---------------------------------------------------------------------------
# Partner agencies
# ---------------------------------------------------------------------------

def register_partner(**overrides) -> dict:
    """Register a partner agency (SystemAdmin)."""
    return get_success_data(api_client.create_partner(create_partner_payload(**overrides), ADMIN))


# ---------------------------------------------------------------------------
# Training pipeline
# ---------------------------------------------------------------------------

def register_instructor(**overrides) -> dict:
    """Register an instructor-certified volunteer (no certs required)."""
    overrides.setdefault("full_name", "Inez Struct")
    overrides.setdefault("email", "inez@x.org")
    overrides["instructor_certified"] = True
    return register_volunteer(**overrides)


def create_course(instructor_id: str, **overrides) -> dict:
    """Create a training course (seats_taken 0)."""
    payload = create_training_course_payload(lead_instructor_volunteer_id=instructor_id, **overrides)
    return get_success_data(api_client.create_training_course(payload, TRAINING))


def enroll_volunteer(course_id: str, volunteer_id: str) -> dict:
    """Enroll a volunteer; lands ENROLLED when a seat is free else WAITLISTED."""
    return get_success_data(
        api_client.create_enrollment(course_id, {"volunteer_id": volunteer_id}, TRAINING)
    )


def get_course(course_id: str) -> dict:
    return get_success_data(api_client.get_training_course(course_id, TRAINING))


def get_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, TRAINING))


def drop_enrollment(enrollment_id: str, volunteer_id: str = None) -> dict:
    """Drop an enrollment: as the enrolled volunteer when volunteer_id is
    given (ownership-gated), otherwise as the TrainingDirector."""
    headers = make_volunteer_headers(volunteer_id) if volunteer_id else TRAINING
    return get_success_data(api_client.patch_enrollment(enrollment_id, {"status": "DROPPED"}, headers))


def setup_course_with_volunteers(capacity: int = 2, num_students: int = 3,
                                 stagger_clock: bool = False, **course_overrides) -> dict:
    """Instructor + course + num_students registered volunteers enrolled in
    order. When stagger_clock is true the logical clock advances one second
    between enrollments so created_at is strictly increasing (waitlist
    promotion order is created_at ASC).

    Returns {"instructor", "course", "volunteers", "enrollments"}.
    """
    set_clock()
    instructor = register_instructor()
    course = create_course(instructor["id"], capacity=capacity, **course_overrides)
    names = ["Enrol One", "Enrol Two", "Enrol Three", "Enrol Four", "Enrol Five"]
    volunteers, enrollments = [], []
    for idx in range(num_students):
        if stagger_clock and idx > 0:
            set_clock(f"2026-09-01T00:00:0{idx}Z")
        volunteer = register_volunteer(
            full_name=names[idx], email=f"e{idx + 1}@x.org", skills=["DEBRIS"],
            availability_windows=[],
        )
        volunteers.append(volunteer)
        enrollments.append(enroll_volunteer(course["id"], volunteer["id"]))
    return {
        "instructor": instructor,
        "course": course,
        "volunteers": volunteers,
        "enrollments": enrollments,
    }


# ---------------------------------------------------------------------------
# Wellness checks
# ---------------------------------------------------------------------------

def list_deployment_wellness_checks(deployment_id: str) -> list:
    from prd_bench_local_runner.testing import validate_paginated
    resp = api_client.list_wellness_checks(deployment_id, SAFETY)
    data, _meta = validate_paginated(resp)
    return data
