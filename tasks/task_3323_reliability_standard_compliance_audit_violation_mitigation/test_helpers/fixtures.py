"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints, because the server restarts (empty database) before every test.
Fixtures use get_success_data (lenient) so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_appeal_payload,
    create_engagement_payload,
    create_evidence_payload,
    create_milestone_payload,
    create_mitigation_plan_payload,
    create_registration_payload,
    create_self_log_entry_payload,
    create_self_report_payload,
    create_violation_payload,
)
from .test_users import (
    TEST_USERS,
    make_auditor_headers,
    make_cip_manager_headers,
    make_officer_headers,
)

RC = TEST_USERS["registration_coordinator_headers"]
AUD = TEST_USERS["auditor_headers"]
RER = TEST_USERS["regional_reviewer_headers"]
FED = TEST_USERS["federal_reviewer_headers"]

MILESTONE_DUE = "2026-10-01T00:00:00Z"


def set_clock(iso="2026-09-01T00:00:00Z"):
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, RER))


def advance_clock(seconds):
    return get_success_data(api_client.advance_clock({"seconds": seconds}, RER))


def create_entity(functions=("GO",), legal_name="Test Entity Co", enrollment=None):
    payload = create_registration_payload(
        legal_name=legal_name, registration_functions=list(functions)
    )
    if enrollment is not None:
        payload["enrollment_self_logging"] = enrollment
    return get_success_data(api_client.create_registration(payload, RC))


def create_engagement_for(entity, standard_ids=("STD-GO-001",), engagement_type="AUDIT",
                          period_start="2026-01-01T00:00:00Z",
                          period_end="2026-01-31T00:00:00Z"):
    # Accept either an entity dict or a bare entity_id string; fetch the
    # entity over the API in the latter case (per fixtures.py docstring on
    # create_violation).
    if not isinstance(entity, dict):
        entity = get_success_data(api_client.get_registration(entity, AUD))
    payload = create_engagement_payload(
        entity["id"],
        engagement_type=engagement_type,
        standard_ids=list(standard_ids),
        period_start=period_start,
        period_end=period_end,
    )
    return get_success_data(api_client.create_engagement(payload, AUD))


def create_started_engagement(entity, **kwargs):
    eng = create_engagement_for(entity, **kwargs)
    eng = get_success_data(api_client.start_engagement(eng["id"], AUD))
    return eng


def create_completed_engagement(entity, evidence_windows=None, accept=True, **kwargs):
    """Started engagement, optionally with evidence submitted/accepted, then completed."""
    eng = create_started_engagement(entity, **kwargs)
    if evidence_windows:
        for (std_id, start, end) in evidence_windows:
            art = get_success_data(api_client.create_evidence(
                create_evidence_payload(
                    eng["id"], standard_id=std_id,
                    coverage_start=start, coverage_end=end,
                ),
                make_officer_headers(entity["id"]),
            ))
            if accept:
                get_success_data(api_client.accept_evidence(art["id"], AUD))
    eng = get_success_data(api_client.complete_engagement(eng["id"], AUD))
    return eng


def create_violation(entity, **overrides):
    """Create a violation with PRD-satisfying source integrity.

    PRD §3.4: AUDIT/SPOT_CHECK sources require a source_engagement_id naming a
    COMPLETED engagement of the matching type; SELF_REPORT sources require a
    source_self_report_id naming a CONFIRMED self-report. When the caller does
    not supply source references, this fixture builds the required source
    object first so the request is PRD-legal.

    Accepts either an entity dict or a bare entity_id string; in the latter
    case the entity is fetched over the API so the engagement/self-report
    source can be built for the right entity.
    """
    entity_id = entity["id"] if isinstance(entity, dict) else entity
    source_type = overrides.get("source_type", "SPOT_CHECK")
    if source_type in ("AUDIT", "SPOT_CHECK") and "source_engagement_id" not in overrides:
        std_id = overrides.get("standard_id", "STD-GO-001")
        # Build the PRD-required COMPLETED engagement of the matching type. No
        # evidence is submitted, so coverage_fraction stays 0.0 — below the 0.8
        # threshold of PRD §3.4, so the gap-aggravation step (factor x1.25)
        # DOES apply to violations priced against this engagement.
        eng = create_completed_engagement(
            entity_id, engagement_type=source_type, standard_ids=[std_id]
        )
        overrides["source_engagement_id"] = eng["id"]
    elif source_type == "SELF_REPORT" and "source_self_report_id" not in overrides:
        std_id = overrides.get("standard_id", "STD-GO-001")
        sr = get_success_data(api_client.create_self_report(
            create_self_report_payload(entity_id, standard_id=std_id),
            make_officer_headers(entity_id),
        ))
        get_success_data(api_client.triage_self_report(sr["id"], AUD))
        sr = get_success_data(api_client.confirm_self_report(sr["id"], AUD))
        overrides["source_self_report_id"] = sr["id"]
    payload = create_violation_payload(entity_id, **overrides)
    return get_success_data(api_client.create_violation(payload, AUD))


def create_open_violation(entity, **overrides):
    """Create a violation; returns (violation, observed_version)."""
    v = create_violation(entity, **overrides)
    return v, v["version"]


def create_plan_for_violation(entity, violation, description="Mitigation plan"):
    """Submit a mitigation plan against an OPEN violation (OCC version read fresh)."""
    v = get_success_data(api_client.get_violation(violation["id"], AUD))
    payload = create_mitigation_plan_payload(v["version"], description=description)
    plan = get_success_data(
        api_client.create_mitigation_plan(v["id"], payload, make_officer_headers(entity["id"]))
    )
    return plan


def create_approved_plan_with_milestone(entity, violation, milestone_due=MILESTONE_DUE):
    """Plan submitted + approved + one milestone added (PENDING). Returns (plan, milestone)."""
    plan = create_plan_for_violation(entity, violation)
    plan = get_success_data(api_client.approve_plan(plan["id"], AUD))
    milestone = get_success_data(api_client.create_milestone(
        plan["id"],
        create_milestone_payload(title="m", due_date=milestone_due),
        make_officer_headers(entity["id"]),
    ))
    return plan, milestone


def close_violation_via_mitigation(entity, violation, milestone_due=MILESTONE_DUE):
    """Full mitigation lifecycle to CLOSED. Returns (violation, plan)."""
    plan, milestone = create_approved_plan_with_milestone(entity, violation, milestone_due)
    get_success_data(api_client.complete_milestone(milestone["id"], make_officer_headers(entity["id"])))
    get_success_data(api_client.complete_mitigation(violation["id"], make_officer_headers(entity["id"])))
    get_success_data(api_client.verify_plan(plan["id"], AUD))
    v = get_success_data(api_client.get_violation(violation["id"], AUD))
    return v, plan


def create_violation_mitigation_complete(entity, **overrides):
    """OPEN violation taken through to MITIGATION_COMPLETE (plan APPROVED, milestones done,
    complete-mitigation called) but NOT yet verified. Returns (violation, plan)."""
    v = create_violation(entity, **overrides)
    plan, milestone = create_approved_plan_with_milestone(entity, v)
    get_success_data(api_client.complete_milestone(milestone["id"], make_officer_headers(entity["id"])))
    get_success_data(api_client.complete_mitigation(v["id"], make_officer_headers(entity["id"])))
    return v, plan


def create_closed_violation_via_appeal_grant(entity, **overrides):
    """Create a violation and close it by filing + regionally granting an appeal."""
    v = create_violation(entity, **overrides)
    appeal = get_success_data(api_client.create_appeal(
        v["id"], create_appeal_payload(v["version"]), make_officer_headers(entity["id"])
    ))
    get_success_data(api_client.grant_appeal(appeal["id"], RER))
    v = get_success_data(api_client.get_violation(v["id"], AUD))
    return v


def create_appealed_violation(entity, **overrides):
    """Create a violation and file an appeal against it. Returns (violation, appeal)."""
    v = create_violation(entity, **overrides)
    appeal = get_success_data(api_client.create_appeal(
        v["id"], create_appeal_payload(v["version"]), make_officer_headers(entity["id"])
    ))
    return v, appeal


def create_confirmed_penalty(entity, violation=None, **violation_overrides):
    """Violation + issued + confirmed penalty. Returns (violation, penalty).

    PRD §3.8/§2.1 segregation of duties: the auditor who created the
    violation (AUD, "test-auditor-1") may not confirm its penalty, so the
    confirm call runs under a second auditor identity.
    """
    if violation is None:
        violation = create_violation(entity, **violation_overrides)
    pen = get_success_data(api_client.create_penalty({"violation_id": violation["id"]}, AUD))
    pen = get_success_data(api_client.confirm_penalty(pen["id"], make_auditor_headers("test-auditor-2")))
    return violation, pen


def create_restricted_entity(functions=("GO",), legal_name="Restricted Co"):
    """Entity with a confirmed penalty, then clock advanced 31 days past issuance
    so the penalty is past due and the entity is RESTRICTED."""
    set_clock()
    entity = create_entity(functions=functions, legal_name=legal_name)
    violation, pen = create_confirmed_penalty(entity)
    advance_clock(2678400)  # 31 days
    return entity, violation, pen


def create_enrolled_entity(functions=("GO",), legal_name="Enrolled Co"):
    return create_entity(functions=functions, legal_name=legal_name, enrollment=True)


def create_period_with_entries(entity, count=1, start_review=True, std_ids=None):
    """Open a review period, attach `count` self-log entries to it, optionally
    start review. Returns (period, [entries])."""
    period = get_success_data(api_client.create_review_period(AUD))
    entries = []
    std_ids = list(std_ids) if std_ids else ["STD-GO-001", "STD-GO-002"]
    for i in range(count):
        payload = create_self_log_entry_payload(
            entity["id"],
            standard_id=std_ids[i % len(std_ids)],
            exception_note=f"exception {i}",
            period_id=period["id"],
        )
        entries.append(get_success_data(
            api_client.create_self_log_entry(payload, make_officer_headers(entity["id"]))
        ))
    if start_review:
        period = get_success_data(api_client.start_review_period(period["id"], AUD))
    return period, entries
