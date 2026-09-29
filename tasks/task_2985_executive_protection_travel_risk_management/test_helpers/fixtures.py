"""Composite setup helpers and pytest fixtures.

Storage is wiped before every test, so every entity a test needs is built here
through the declared endpoints.  The helpers are layered: registration first,
then the entities that depend on it, then the lifecycle shortcuts that drive a
trip to a named state, and finally the whole-scenario builders.

Two disciplines are baked in because the service demands them.  A protective
detail assignment carries the leg version the client last observed, so every
assignment helper re-reads the leg immediately before it posts.  A vendor
engagement carries the vendor version, so every engagement helper re-reads the
vendor immediately before it posts.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ExecProtectionClient
from .constants import (
    ADVANCE_OUTCOME_COMPLETE,
    CERT_FAR_FUTURE,
    CLOCK_EPOCH,
    COUNTRY_PT,
    DECISION_APPROVE,
    DETAIL_LEAD_AGENT,
    ITEM_ROUTE_SURVEY,
    LEG_ARRIVE_AT,
    LEG_DEPART_AT,
    POLICY_MEDICAL_EVAC,
    RATE_ANALYST_CENTS,
    RATE_DIRECTOR_CENTS,
    RATE_MANAGER_CENTS,
    REVIEW_APPROVE,
    STAFF_ROLE_ANALYST,
    STAFF_ROLE_DIRECTOR,
    STAFF_ROLE_MANAGER,
    SURVEY_COMPLETE,
    TIER_3,
    TRIP_DEPART_AT,
    TRIP_RETURN_AT,
    VERIFY_OUTCOME_VERIFY,
)
from .test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    SYSTEM_OPERATOR_HEADERS,
    make_executive_headers,
    make_protection_manager_headers,
    make_security_analyst_headers,
    make_security_director_headers,
)


class Ctx(dict):
    """A dict whose keys are also readable as attributes."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


# --------------------------------------------------------------- tier 1: clock
def set_clock(api, instant):
    """Move the logical clock to ``instant``; no business entity is touched."""
    return get_success_data(
        api.set_clock(f.clock_payload(instant), SYSTEM_OPERATOR_HEADERS)
    )


# ------------------------------------------------ tier 1: department registry
def register_staff(
    api,
    full_name,
    staff_role,
    hourly_rate_cents,
    certification_expires_at=CERT_FAR_FUTURE,
    headers=None,
):
    return get_success_data(
        api.create_security_staff(
            f.staff_payload(
                full_name=full_name,
                staff_role=staff_role,
                certification_expires_at=certification_expires_at,
                hourly_rate_cents=hourly_rate_cents,
            ),
            headers or SYSTEM_OPERATOR_HEADERS,
        )
    )


def bootstrap_department(api, clock=CLOCK_EPOCH):
    """Set the clock and register the four staff members the suite works with."""
    if clock is not None:
        set_clock(api, clock)
    analyst = register_staff(api, "Ana Analyst", STAFF_ROLE_ANALYST, RATE_ANALYST_CENTS)
    manager = register_staff(api, "Mia Manager", STAFF_ROLE_MANAGER, RATE_MANAGER_CENTS)
    director = register_staff(
        api, "Dan Director", STAFF_ROLE_DIRECTOR, RATE_DIRECTOR_CENTS
    )
    lead = register_staff(api, "Lee Lead", STAFF_ROLE_ANALYST, RATE_ANALYST_CENTS)
    return Ctx(
        analyst_id=analyst["id"],
        mgr_id=manager["id"],
        dir_id=director["id"],
        lead_id=lead["id"],
        analyst=make_security_analyst_headers(analyst["id"]),
        mgr=make_protection_manager_headers(manager["id"]),
        dir=make_security_director_headers(director["id"]),
        officer=COMPLIANCE_OFFICER_HEADERS,
        ops=SYSTEM_OPERATOR_HEADERS,
    )


# --------------------------------------------------------- tier 2: protectees
def register_executive(api, dep, **overrides):
    """Register a protectee and return the created row plus its own headers."""
    row = get_success_data(
        api.create_executive(f.executive_payload(**overrides), dep.mgr)
    )
    return row


def complete_residential_survey(
    api, dep, executive_id, outcome=SURVEY_COMPLETE, component=10.0
):
    return get_success_data(
        api.record_residential_survey(
            executive_id,
            f.residential_survey_payload(
                survey_outcome=outcome, residential_component=component
            ),
            dep.analyst,
        )
    )


def add_exposure_signal(api, dep, executive_id, signal_type, severity, observed_at):
    return get_success_data(
        api.create_exposure_signal(
            executive_id,
            f.exposure_signal_payload(signal_type, severity, observed_at),
            dep.analyst,
        )
    )


# ------------------------------------------------ tier 2: advisories and cover
def publish_rating(
    api,
    dep,
    country_code=COUNTRY_PT,
    crime_index=10.0,
    political_instability_index=8.0,
    medical_infrastructure_index=90.0,
    natural_hazard_index=12.0,
):
    return get_success_data(
        api.create_destination_rating(
            f.destination_rating_payload(
                country_code=country_code,
                crime_index=crime_index,
                political_instability_index=political_instability_index,
                medical_infrastructure_index=medical_infrastructure_index,
                natural_hazard_index=natural_hazard_index,
            ),
            dep.analyst,
        )
    )


def create_policy(api, dep, executive_id, headers=None, **overrides):
    return get_success_data(
        api.create_insurance_policy(
            f.insurance_policy_payload(executive_id, **overrides),
            headers or dep.officer,
        )
    )


def verify_policy(api, dep, policy_id, note="binder on file"):
    return get_success_data(
        api.verify_insurance_policy(
            policy_id,
            f.policy_verify_payload(
                outcome=VERIFY_OUTCOME_VERIFY, verification_note=note
            ),
            dep.officer,
        )
    )


def create_verified_policy(api, dep, executive_id, **overrides):
    """Create a policy and carry it through verification in two phases."""
    policy = create_policy(api, dep, executive_id, **overrides)
    return verify_policy(api, dep, policy["id"])


# ------------------------------------------------------- tier 3: assessments
def draft_assessment(api, dep, executive_id, threat_monitoring_score=20.0):
    return get_success_data(
        api.create_risk_assessment(
            f.risk_assessment_payload(
                executive_id, dep.analyst_id, threat_monitoring_score
            ),
            dep.analyst,
        )
    )


def submit_assessment(api, dep, assessment_id):
    return get_success_data(api.submit_risk_assessment(assessment_id, dep.analyst))


def review_assessment(api, dep, assessment_id, outcome=REVIEW_APPROVE, notes=None):
    payload = f.assessment_review_payload(outcome)
    if notes is not None:
        payload["review_notes"] = notes
    return get_success_data(
        api.review_risk_assessment(assessment_id, payload, dep.dir)
    )


def approved_assessment(api, dep, executive_id, threat_monitoring_score=20.0):
    """Draft, submit and approve one assessment, returning the approved row."""
    assessment = draft_assessment(api, dep, executive_id, threat_monitoring_score)
    submit_assessment(api, dep, assessment["id"])
    return review_assessment(api, dep, assessment["id"], REVIEW_APPROVE, "cleared")


# ------------------------------------------------------------- tier 3: trips
def create_trip(
    api, dep, executive_id, risk_assessment_id, insurance_policy_id=None, **overrides
):
    payload = f.trip_payload(
        executive_id, dep.mgr_id, risk_assessment_id, **overrides
    )
    if insurance_policy_id is not None:
        payload["insurance_policy_id"] = insurance_policy_id
    return get_success_data(api.create_trip(payload, dep.mgr))


def add_leg(
    api,
    dep,
    trip_id,
    sequence_no=1,
    destination_country_code=COUNTRY_PT,
    arrive_at=LEG_ARRIVE_AT,
    depart_at=LEG_DEPART_AT,
):
    return get_success_data(
        api.create_trip_leg(
            trip_id,
            f.trip_leg_payload(
                sequence_no=sequence_no,
                destination_country_code=destination_country_code,
                arrive_at=arrive_at,
                depart_at=depart_at,
            ),
            dep.mgr,
        )
    )


def read_leg(api, dep, leg_id, headers=None):
    return get_success_data(api.get_trip_leg(leg_id, headers or dep.mgr))


def leg_version(api, dep, leg_id):
    """Re-observe a leg's version, which every assignment create must carry."""
    return read_leg(api, dep, leg_id)["version"]


def assign_detail(
    api,
    dep,
    leg_id,
    staff_id,
    role_on_detail=DETAIL_LEAD_AGENT,
    starts_at=LEG_ARRIVE_AT,
    ends_at=LEG_DEPART_AT,
):
    """Create one assignment, refreshing the leg version immediately beforehand."""
    version = leg_version(api, dep, leg_id)
    return get_success_data(
        api.create_detail_assignment(
            f.detail_assignment_payload(
                leg_id,
                staff_id,
                version,
                role_on_detail=role_on_detail,
                starts_at=starts_at,
                ends_at=ends_at,
            ),
            dep.mgr,
        )
    )


def release_assignment(api, dep, assignment_id, actual_ends_at):
    return get_success_data(
        api.release_detail_assignment(
            assignment_id, f.release_payload(actual_ends_at), dep.mgr
        )
    )


def record_advance(
    api, dep, leg_id, item_type=ITEM_ROUTE_SURVEY,
    outcome=ADVANCE_OUTCOME_COMPLETE, headers=None, note="route walked",
):
    payload = f.advance_progress_payload(item_type=item_type, outcome=outcome)
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api.record_advance_progress(leg_id, payload, headers or dep.mgr)
    )


def complete_required_advance_work(api, dep, leg_id, headers=None):
    """Record every currently required advance item on one leg as complete."""
    leg = read_leg(api, dep, leg_id)
    for item in leg["required_advance_items"]:
        record_advance(api, dep, leg_id, item, headers=headers)
    return read_leg(api, dep, leg_id)


def submit_trip(api, dep, trip_id):
    return get_success_data(api.submit_trip_for_approval(trip_id, dep.mgr))


def ack_briefing(api, executive_id, trip_id):
    return get_success_data(
        api.acknowledge_briefing(trip_id, make_executive_headers(executive_id))
    )


def decide_trip(api, dep, trip_id, decision=DECISION_APPROVE, headers=None, **extra):
    payload = f.trip_decision_payload(decision, **extra)
    return get_success_data(api.decide_trip(trip_id, payload, headers or dep.dir))


def approve_trip(api, dep, trip_id, executive_id):
    """Submit, acknowledge the briefing and take the director's approval."""
    submit_trip(api, dep, trip_id)
    ack_briefing(api, executive_id, trip_id)
    return decide_trip(api, dep, trip_id, DECISION_APPROVE)


def read_trip(api, dep, trip_id, headers=None):
    return get_success_data(api.get_trip(trip_id, headers or dep.mgr))


def read_executive(api, dep, executive_id, headers=None):
    return get_success_data(api.get_executive(executive_id, headers or dep.mgr))


def read_staff(api, dep, staff_id, headers=None):
    return get_success_data(api.get_security_staff(staff_id, headers or dep.mgr))


def close_trip(api, dep, trip_id):
    return get_success_data(api.close_trip(trip_id, dep.mgr))


# ----------------------------------------------------------- tier 3: vendors
def register_vendor(api, dep, headers=None, **overrides):
    return get_success_data(
        api.create_vendor(f.vendor_payload(**overrides), headers or dep.mgr)
    )


def read_vendor(api, dep, vendor_id, headers=None):
    return get_success_data(api.get_vendor(vendor_id, headers or dep.mgr))


def vendor_version(api, dep, vendor_id):
    """Re-observe a vendor's version, which every engagement create must carry."""
    return read_vendor(api, dep, vendor_id)["version"]


def engage_vendor(
    api, dep, vendor_id, leg_id, engagement_purpose, starts_at, ends_at, headers=None
):
    """Engage a vendor, refreshing the vendor version immediately beforehand."""
    version = vendor_version(api, dep, vendor_id)
    return get_success_data(
        api.create_vendor_engagement(
            f.vendor_engagement_payload(
                vendor_id,
                leg_id,
                engagement_purpose,
                starts_at,
                ends_at,
                version,
            ),
            headers or dep.mgr,
        )
    )


def complete_engagement(api, dep, engagement_id, headers=None):
    return get_success_data(
        api.complete_vendor_engagement(engagement_id, headers or dep.mgr)
    )


def suspend_vendor(api, dep, vendor_id, reason="licence lapsed in country"):
    return get_success_data(
        api.suspend_vendor(vendor_id, f.vendor_suspend_payload(reason), dep.dir)
    )


# --------------------------------------------------------- tier 3: incidents
def report_incident(api, dep, trip_id, headers=None, **overrides):
    return get_success_data(
        api.report_incident(
            trip_id, f.incident_payload(**overrides), headers or dep.mgr
        )
    )


def triage_incident(api, dep, incident_id, response_track, headers=None):
    return get_success_data(
        api.triage_incident(
            incident_id, f.triage_payload(response_track), headers or dep.mgr
        )
    )


def resolve_incident(api, dep, incident_id, headers=None, **overrides):
    return get_success_data(
        api.resolve_incident(
            incident_id, headers or dep.mgr, f.resolve_payload(**overrides)
        )
    )


def close_incident(api, dep, incident_id):
    return get_success_data(api.close_incident(incident_id, dep.dir))


# ------------------------------------------------- tier 4: whole-world builders
def bootstrap_world(
    api,
    clock=CLOCK_EPOCH,
    country_code=COUNTRY_PT,
    rating=None,
    executive=None,
    survey_outcome=SURVEY_COMPLETE,
    survey_component=10.0,
    threat_monitoring_score=20.0,
    policy_type=POLICY_MEDICAL_EVAC,
    coverage_cents=500_000_000,
    policy_overrides=None,
):
    """Registry, protectee, survey, advisory, verified cover and approved intel.

    This is the common ground every trip scenario stands on: a `LOW` `PT`
    advisory, a `TIER_3` protectee whose residential survey is complete, a
    verified medical-evacuation policy and one approved risk assessment.
    """
    dep = bootstrap_department(api, clock=clock)
    exec_row = register_executive(api, dep, **(executive or {}))
    complete_residential_survey(
        api, dep, exec_row["id"], survey_outcome, survey_component
    )
    rating_row = publish_rating(
        api, dep, country_code=country_code, **(rating or {})
    )
    policy = create_verified_policy(
        api,
        dep,
        exec_row["id"],
        policy_type=policy_type,
        coverage_cents=coverage_cents,
        **(policy_overrides or {}),
    )
    assessment = approved_assessment(
        api, dep, exec_row["id"], threat_monitoring_score
    )
    return Ctx(
        dep=dep,
        exec_row=exec_row,
        exec_id=exec_row["id"],
        exec_headers=make_executive_headers(exec_row["id"]),
        rating=rating_row,
        policy=policy,
        policy_id=policy["id"],
        assessment=assessment,
        ra_id=assessment["id"],
    )


def trip_world(
    api,
    world=None,
    trip=None,
    leg=None,
    with_lead_agent=True,
    with_route_survey=True,
    attach_policy=True,
    **bootstrap_kwargs,
):
    """A draft trip with one leg, its lead agent and its route survey.

    The lead agent spans the whole leg window, so the leg is covered, and the
    single `LOW` advance item is recorded, so the leg is advance-complete: the
    trip is one submission away from review.
    """
    w = world or bootstrap_world(api, **bootstrap_kwargs)
    dep = w.dep
    trip_row = create_trip(
        api,
        dep,
        w.exec_id,
        w.ra_id,
        insurance_policy_id=w.policy_id if attach_policy else None,
        **(trip or {}),
    )
    leg_row = add_leg(api, dep, trip_row["id"], **(leg or {}))
    w.trip = trip_row
    w.trip_id = trip_row["id"]
    w.leg = leg_row
    w.leg_id = leg_row["id"]
    if with_lead_agent:
        w.lead_assignment = assign_detail(
            api,
            dep,
            leg_row["id"],
            dep.lead_id,
            DETAIL_LEAD_AGENT,
            leg_row["arrive_at"],
            leg_row["depart_at"],
        )
    if with_route_survey:
        record_advance(api, dep, leg_row["id"], ITEM_ROUTE_SURVEY)
    return w


def approved_trip_world(api, **kwargs):
    """A trip carried all the way to approved and ready."""
    w = trip_world(api, **kwargs)
    submit_trip(api, w.dep, w.trip_id)
    ack_briefing(api, w.exec_id, w.trip_id)
    w.trip = decide_trip(api, w.dep, w.trip_id, DECISION_APPROVE)
    return w


# --------------------------------------------------------------- fixtures
@pytest.fixture
def api():
    """The API client for one isolated server."""
    return ExecProtectionClient()


@pytest.fixture
def dep(api):
    """The clock at its epoch and the four staff members registered."""
    return bootstrap_department(api)


@pytest.fixture
def world(api):
    """The common ground: protectee, advisory, verified cover, approved intel."""
    return bootstrap_world(api)
