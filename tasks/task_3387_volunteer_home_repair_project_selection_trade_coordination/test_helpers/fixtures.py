"""Composite setup helpers (fixtures) for the volunteer-home-repair domain.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints — the harness restarts the server before every test, so nothing
here may rely on cross-test state. Setup calls use the lenient
get_success_data() validator: a failed precondition raises a clear
"Setup step failed" AssertionError rather than a confusing test assertion.

Identity threading: after creating an entity-backed identity's resource, every
ownership-gated call in the same chain uses make_<role>_headers(entity["id"])
— never the shared TEST_USERS fallback (PRD §2.1).

Clock discipline: the logical clock defaults to 2026-09-01T00:00:00Z.
Composite fixtures pin it explicitly at the start for determinism, then advance
it forward only when a later lifecycle step requires it (visit windows, event
day, warranty window). All default dates live in constants.py and are reachable
under the default clock.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_DEFAULT_ISO,
    DEFAULT_ASSESSMENT_DATE,
    DEFAULT_BUDGET_CENTS,
    DEFAULT_EVENT_DATE,
    DEFAULT_FISCAL_YEAR,
    DEFAULT_FOLLOW_UP_DATE,
    DEFAULT_INCOME_CENTS,
    DEFAULT_MAX_VOLUNTEERS,
    DEFAULT_TRAINING_COMPLETED_ON,
    DEFAULT_VISIT_CLOCK_ISO,
    DEFAULT_VISIT_END,
    DEFAULT_VISIT_START,
    DEFAULT_WAIVER_SIGNED_ON,
)
from .factories import (
    complete_assessment_payload,
    create_application_payload,
    create_assessment_payload,
    create_commitment_payload,
    create_contractor_payload,
    create_event_payload,
    create_funding_cycle_payload,
    create_material_order_payload,
    create_scope_amendment_payload,
    create_selection_run_payload,
    create_sponsor_payload,
    create_volunteer_payload,
    create_warranty_claim_payload,
    create_work_order_payload,
    inspect_work_order_payload,
    schedule_work_order_payload,
    scope_item_payload,
)
from .test_users import (
    TEST_USERS,
    make_homeowner_headers,
    make_trade_partner_headers,
    make_volunteer_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
STAFF = TEST_USERS["affiliate_staff_headers"]
ASSESSOR = TEST_USERS["assessor_headers"]
ANON = TEST_USERS["anonymous_headers"]


# =============================================================================
# Tier 0: clock + thin re-reads
# =============================================================================

def set_clock(to_iso8601=CLOCK_DEFAULT_ISO) -> dict:
    """Drive the logical clock (PlatformAdmin-only). Returns {current_utc}."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def reset_clock() -> dict:
    """Pin the logical clock to its documented default instant."""
    return set_clock(CLOCK_DEFAULT_ISO)


def get_cycle(cycle_id) -> dict:
    return get_success_data(api_client.get_funding_cycle(cycle_id, STAFF))


def get_selection_run(run_id) -> dict:
    return get_success_data(api_client.get_selection_run(run_id, STAFF))


def get_sponsor(sponsor_id) -> dict:
    return get_success_data(api_client.get_sponsor(sponsor_id, STAFF))


def get_commitment(commitment_id) -> dict:
    return get_success_data(api_client.get_commitment(commitment_id, STAFF))


def get_application(application_id) -> dict:
    return get_success_data(api_client.get_application(application_id, STAFF))


def get_assessment(assessment_id) -> dict:
    return get_success_data(api_client.get_assessment(assessment_id, STAFF))


def get_scope_item(scope_item_id) -> dict:
    return get_success_data(api_client.get_scope_item(scope_item_id, STAFF))


def get_project(project_id) -> dict:
    return get_success_data(api_client.get_project(project_id, STAFF))


def get_event(event_id) -> dict:
    return get_success_data(api_client.get_event(event_id, STAFF))


def get_volunteer(volunteer_id) -> dict:
    return get_success_data(api_client.get_volunteer(volunteer_id, STAFF))


def get_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, STAFF))


def get_contractor(contractor_id) -> dict:
    return get_success_data(api_client.get_trade_contractor(contractor_id, STAFF))


def get_work_order(work_order_id) -> dict:
    return get_success_data(api_client.get_trade_work_order(work_order_id, STAFF))


def get_material_order(order_id) -> dict:
    return get_success_data(api_client.get_material_order(order_id, STAFF))


def get_warranty_claim(claim_id) -> dict:
    return get_success_data(api_client.get_warranty_claim(claim_id, STAFF))


def list_scope_items_for_assessment(assessment_id) -> list:
    return get_success_data(
        api_client.list_scope_items(STAFF, params={"assessment_id": assessment_id})
    )


def list_projects_for_application(application_id) -> list:
    return get_success_data(
        api_client.list_projects(STAFF, params={"application_id": application_id})
    )


def get_project_for_application(application_id) -> dict:
    """The selection-run apply creates exactly one project per application."""
    projects = list_projects_for_application(application_id)
    assert projects, f"Setup failed: no project found for application {application_id}"
    return projects[0]


# =============================================================================
# Tier 1: single-entity state progression
# =============================================================================

def create_cycle(
    total_budget_cents=DEFAULT_BUDGET_CENTS,
    priority_mode="STANDARD",
    name=None,
    fiscal_year=DEFAULT_FISCAL_YEAR,
) -> dict:
    """Create a funding cycle (status OPEN, ledgers zeroed)."""
    overrides = {
        "fiscal_year": fiscal_year,
        "total_budget_cents": total_budget_cents,
        "priority_mode": priority_mode,
    }
    if name is not None:
        overrides["name"] = name
    payload = create_funding_cycle_payload(**overrides)
    return get_success_data(api_client.create_funding_cycle(payload, ADMIN))


def open_selection(cycle_id) -> dict:
    """Drive a cycle OPEN -> SELECTION_OPEN. Returns the updated cycle."""
    return get_success_data(
        api_client.patch_funding_cycle(cycle_id, {"status": "SELECTION_OPEN"}, ADMIN)
    )


def seal_cycle(cycle_id) -> dict:
    """Drive a cycle SELECTION_OPEN -> SEALED. Returns the updated cycle."""
    return get_success_data(
        api_client.patch_funding_cycle(cycle_id, {"status": "SEALED"}, ADMIN)
    )


def create_application(cycle_id, **overrides) -> dict:
    """Submit an application as the Anonymous public caller (status SUBMITTED)."""
    payload = create_application_payload(cycle_id, **overrides)
    return get_success_data(api_client.create_application(payload, ANON))


def patch_application_status(application_id, status, decision_reason=None) -> dict:
    """Staff-driven application transition."""
    payload = {"status": status}
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    return get_success_data(api_client.patch_application(application_id, payload, STAFF))


def create_verified_application(cycle_id, **overrides) -> dict:
    """Application walked SUBMITTED -> UNDER_VERIFICATION -> VERIFIED.

    The returned dict is the VERIFIED PATCH response data, so it carries the
    freshly computed priority_score and is_older_adult.
    """
    app = create_application(cycle_id, **overrides)
    patch_application_status(app["id"], "UNDER_VERIFICATION")
    return patch_application_status(app["id"], "VERIFIED")


def create_assessment(application_id, scheduled_on=DEFAULT_ASSESSMENT_DATE) -> dict:
    """Schedule an assessment (staff); flips the application to ASSESSING."""
    payload = create_assessment_payload(application_id, scheduled_on=scheduled_on)
    return get_success_data(api_client.create_assessment(payload, STAFF))


def complete_assessment(
    assessment_id,
    scope_items=None,
    safety_hazard_max_severity=0,
    accessibility_needs_count=0,
    critical_systems_notes=None,
) -> dict:
    """Record findings + proposed scope (Assessor). Returns COMPLETED assessment."""
    payload = complete_assessment_payload(
        scope_items=scope_items,
        safety_hazard_max_severity=safety_hazard_max_severity,
        accessibility_needs_count=accessibility_needs_count,
        critical_systems_notes=critical_systems_notes,
    )
    return get_success_data(api_client.complete_assessment(assessment_id, payload, ASSESSOR))


def scope_assessment(assessment_id) -> dict:
    """Drive COMPLETED -> SCOPED (staff); the application advances to ASSESSED."""
    return get_success_data(
        api_client.patch_assessment(assessment_id, {"status": "SCOPED"}, STAFF)
    )


def create_scoped_application(
    cycle_id,
    scope_items=None,
    safety_hazard_max_severity=0,
    accessibility_needs_count=0,
    scheduled_on=DEFAULT_ASSESSMENT_DATE,
    **application_overrides,
) -> dict:
    """Verified application + completed + scoped assessment.

    Returns {"application", "assessment", "scope_items"}; the application is
    re-read after scoping so it carries status ASSESSED and the recomputed
    priority_score.
    """
    app = create_verified_application(cycle_id, **application_overrides)
    asm = create_assessment(app["id"], scheduled_on=scheduled_on)
    asm = complete_assessment(
        asm["id"],
        scope_items=scope_items,
        safety_hazard_max_severity=safety_hazard_max_severity,
        accessibility_needs_count=accessibility_needs_count,
    )
    asm = scope_assessment(asm["id"])
    items = list_scope_items_for_assessment(asm["id"])
    return {
        "application": get_application(app["id"]),
        "assessment": asm,
        "scope_items": items,
    }


def create_candidate(cycle_id, scope_items=None, **kwargs) -> dict:
    """Scoped application nominated to CANDIDATE. Same return shape as
    create_scoped_application, with the application re-read as CANDIDATE."""
    ctx = create_scoped_application(cycle_id, scope_items=scope_items, **kwargs)
    ctx["application"] = patch_application_status(ctx["application"]["id"], "CANDIDATE")
    return ctx


def create_application_in_state(cycle_id, target_state, **overrides) -> dict:
    """Walk an application to a non-system state for state-machine probes.

    Reachable targets: SUBMITTED, UNDER_VERIFICATION, VERIFIED, ASSESSING,
    ASSESSED, CANDIDATE, DEFERRED, REJECTED, WITHDRAWN. (SELECTED / FULFILLED
    are system-driven via the selection run / project completion; use
    setup_selected_project / setup_completed_project for those.)
    """
    if target_state == "SUBMITTED":
        return create_application(cycle_id, **overrides)
    if target_state == "UNDER_VERIFICATION":
        app = create_application(cycle_id, **overrides)
        return patch_application_status(app["id"], "UNDER_VERIFICATION")
    if target_state == "VERIFIED":
        return create_verified_application(cycle_id, **overrides)
    if target_state == "REJECTED":
        app = create_application(cycle_id, **overrides)
        patch_application_status(app["id"], "UNDER_VERIFICATION")
        return patch_application_status(app["id"], "REJECTED", decision_reason="ineligible")
    if target_state in ("ASSESSING", "ASSESSED"):
        app = create_verified_application(cycle_id, **overrides)
        asm = create_assessment(app["id"])
        if target_state == "ASSESSING":
            return get_application(app["id"])
        complete_assessment(asm["id"])
        scope_assessment(asm["id"])
        return get_application(app["id"])
    if target_state == "CANDIDATE":
        return create_candidate(cycle_id, **overrides)["application"]
    if target_state == "DEFERRED":
        ctx = create_candidate(cycle_id, **overrides)
        return patch_application_status(
            ctx["application"]["id"], "DEFERRED", decision_reason="waitlist"
        )
    if target_state == "WITHDRAWN":
        app = create_application(cycle_id, **overrides)
        return patch_application_status(app["id"], "WITHDRAWN")
    raise ValueError(f"create_application_in_state: unreachable target {target_state}")


# =============================================================================
# Tier 2/3: selection runs and selected projects
# =============================================================================

def create_selection_run(cycle_id) -> dict:
    """Create + compute a selection run; reads the cycle's current version for
    the OCC guard. Returns the COMPUTED run."""
    cycle = get_cycle(cycle_id)
    payload = create_selection_run_payload(cycle["version"])
    return get_success_data(api_client.create_selection_run(cycle_id, payload, STAFF))


def apply_run(run_id) -> dict:
    """Apply a COMPUTED run. Returns {applied_count, project_ids,
    deferred_application_ids}."""
    return get_success_data(api_client.apply_selection_run(run_id, STAFF))


def run_selection(cycle_id) -> dict:
    """Create a run against the current cycle version and apply it."""
    run = create_selection_run(cycle_id)
    return {"run": run, "apply": apply_run(run["id"])}


def setup_selected_project(
    budget_cents=DEFAULT_BUDGET_CENTS,
    priority_mode="STANDARD",
    scope_items=None,
    safety_hazard_max_severity=0,
    accessibility_needs_count=0,
    application_overrides=None,
    cycle_id=None,
) -> dict:
    """The full selection chain on a fresh (or supplied) cycle:

    clock pinned -> cycle -> application verified -> assessment completed +
    scoped -> CANDIDATE -> SELECTION_OPEN -> run -> apply -> project.

    scope_items is a list of scope-item payload dicts (see factories
    scope_item_payload / trade_scope_item_payload); the default is a single
    volunteer-performable GENERAL item estimated 100000..100000 (envelope
    115000 under the 15% tier).

    Returns {"cycle", "application", "assessment", "scope_items", "run",
    "apply", "project"} with cycle/application/project re-read post-apply.
    """
    reset_clock()
    if cycle_id is None:
        cycle_id = create_cycle(budget_cents, priority_mode=priority_mode)["id"]
    ctx = create_candidate(
        cycle_id,
        scope_items=scope_items,
        safety_hazard_max_severity=safety_hazard_max_severity,
        accessibility_needs_count=accessibility_needs_count,
        **(application_overrides or {}),
    )
    open_selection(cycle_id)
    sel = run_selection(cycle_id)
    project = get_project_for_application(ctx["application"]["id"])
    ctx.update(
        {
            "cycle": get_cycle(cycle_id),
            "run": sel["run"],
            "apply": sel["apply"],
            "project": project,
        }
    )
    ctx["application"] = get_application(ctx["application"]["id"])
    return ctx


def amend_scope(project_id, add_items=None, drop_item_ids=None, restore_item_ids=None) -> dict:
    """OCC-guarded scope amendment; reads the project's current version.
    Returns the updated project."""
    project = get_project(project_id)
    payload = create_scope_amendment_payload(
        project["version"],
        add_items=add_items,
        drop_item_ids=drop_item_ids,
        restore_item_ids=restore_item_ids,
    )
    return get_success_data(api_client.create_scope_amendment(project_id, payload, STAFF))


# =============================================================================
# Tier 2/3: sponsors and commitments
# =============================================================================

def create_sponsor(**overrides) -> dict:
    return get_success_data(api_client.create_sponsor(create_sponsor_payload(**overrides), ADMIN))


def create_commitment(sponsor_id, cycle_id, amount_cents, receive=False, **overrides) -> dict:
    """Pledge a commitment (staff); receive=True additionally marks it RECEIVED,
    which stamps received_at from the logical clock and raises the pool."""
    payload = create_commitment_payload(sponsor_id, cycle_id, amount_cents, **overrides)
    commitment = get_success_data(api_client.create_commitment(payload, STAFF))
    if receive:
        commitment = get_success_data(
            api_client.patch_commitment(commitment["id"], {"status": "RECEIVED"}, STAFF)
        )
    return commitment


def setup_cycle_with_commitments(budget_cents, amounts=(), receive=True) -> dict:
    """A cycle plus one sponsor carrying one commitment per amount.

    Returns {"cycle", "sponsor", "commitments"}. With receive=True every
    commitment is RECEIVED at the current clock (advance the clock between
    calls in the test itself when received_at ordering matters).
    """
    cycle = create_cycle(budget_cents)
    sponsor = create_sponsor()
    commitments = [
        create_commitment(sponsor["id"], cycle["id"], amount, receive=receive)
        for amount in amounts
    ]
    return {"cycle": cycle, "sponsor": sponsor, "commitments": commitments}


# =============================================================================
# Tier 2/3: trade contractors and work orders
# =============================================================================

def create_contractor(**overrides) -> dict:
    """Register an ACTIVE contractor (PlatformAdmin), strike_count 0."""
    return get_success_data(
        api_client.create_trade_contractor(create_contractor_payload(**overrides), ADMIN)
    )


def create_work_order(project_id, contractor_id, scope_item_ids, **overrides) -> dict:
    """Commission a work order (staff); born QUOTE_REQUESTED."""
    payload = create_work_order_payload(project_id, contractor_id, scope_item_ids, **overrides)
    return get_success_data(api_client.create_trade_work_order(payload, STAFF))


def quote_work_order(work_order_id, contractor_id, quote_cents) -> dict:
    """QUOTE_REQUESTED -> QUOTED by the owning TradePartner."""
    return get_success_data(
        api_client.patch_trade_work_order(
            work_order_id,
            {"status": "QUOTED", "quote_cents": quote_cents},
            make_trade_partner_headers(contractor_id),
        )
    )


def approve_work_order(work_order_id, permit_number=None) -> dict:
    """QUOTED -> APPROVED (staff); supply permit_number when any covered item
    requires a permit."""
    payload = {"status": "APPROVED"}
    if permit_number is not None:
        payload["permit_number"] = permit_number
    return get_success_data(api_client.patch_trade_work_order(work_order_id, payload, STAFF))


def schedule_work_order(
    work_order_id, visit_start=DEFAULT_VISIT_START, visit_end=DEFAULT_VISIT_END
) -> dict:
    """APPROVED -> SCHEDULED (staff) with a half-open visit window."""
    payload = schedule_work_order_payload(visit_start, visit_end)
    return get_success_data(
        api_client.schedule_trade_work_order(work_order_id, payload, STAFF)
    )


def inspect_work_order(work_order_id, outcome="PASSED", notes=None) -> dict:
    """PENDING_INSPECTION -> INSPECTED (PASSED) or INSPECTION_FAILED (FAILED)."""
    payload = inspect_work_order_payload(outcome, notes=notes)
    return get_success_data(api_client.inspect_trade_work_order(work_order_id, payload, STAFF))


def invoice_work_order(work_order_id, contractor_id, invoice_cents) -> dict:
    """INSPECTED -> INVOICED by the owning TradePartner."""
    return get_success_data(
        api_client.patch_trade_work_order(
            work_order_id,
            {"status": "INVOICED", "invoice_cents": invoice_cents},
            make_trade_partner_headers(contractor_id),
        )
    )


def pay_work_order(work_order_id) -> dict:
    """INVOICED -> PAID (staff); moves the invoice from reserved to spent."""
    return get_success_data(
        api_client.patch_trade_work_order(work_order_id, {"status": "PAID"}, STAFF)
    )


def drive_work_order_to(
    work_order_id,
    contractor_id,
    target_status,
    quote_cents=100_000,
    invoice_cents=None,
    permit_number=None,
    visit_start=DEFAULT_VISIT_START,
    visit_end=DEFAULT_VISIT_END,
    inspection_outcome="PASSED",
    advance_clock=True,
) -> dict:
    """Walk a QUOTE_REQUESTED work order forward to a target status.

    Reachable targets: QUOTED, APPROVED, SCHEDULED, IN_PROGRESS,
    PENDING_INSPECTION, INSPECTED, INSPECTION_FAILED, INVOICED, PAID.
    The IN_PROGRESS step needs the clock date on/after the visit_start date;
    with advance_clock=True the fixture drives the clock to the visit window's
    start instant first. INVOICED/PAID route through a PASSED inspection;
    INSPECTION_FAILED routes through a FAILED one.
    """
    linear = ["QUOTED", "APPROVED", "SCHEDULED", "IN_PROGRESS", "PENDING_INSPECTION"]
    if target_status in linear:
        steps = linear[: linear.index(target_status) + 1]
    elif target_status in ("INSPECTED", "INSPECTION_FAILED"):
        steps = linear + [target_status]
    elif target_status in ("INVOICED", "PAID"):
        steps = linear + ["INSPECTED", "INVOICED"]
        if target_status == "PAID":
            steps.append("PAID")
    else:
        raise ValueError(f"drive_work_order_to: unreachable target {target_status}")

    wo = None
    for step in steps:
        if step == "QUOTED":
            wo = quote_work_order(work_order_id, contractor_id, quote_cents)
        elif step == "APPROVED":
            wo = approve_work_order(work_order_id, permit_number=permit_number)
        elif step == "SCHEDULED":
            wo = schedule_work_order(work_order_id, visit_start, visit_end)
        elif step == "IN_PROGRESS":
            if advance_clock:
                set_clock(DEFAULT_VISIT_CLOCK_ISO)
            wo = get_success_data(
                api_client.patch_trade_work_order(
                    work_order_id, {"status": "IN_PROGRESS"}, STAFF
                )
            )
        elif step == "PENDING_INSPECTION":
            wo = get_success_data(
                api_client.patch_trade_work_order(
                    work_order_id, {"status": "PENDING_INSPECTION"}, STAFF
                )
            )
        elif step in ("INSPECTED", "INSPECTION_FAILED"):
            outcome = "PASSED" if step == "INSPECTED" else inspection_outcome
            if step == "INSPECTION_FAILED":
                outcome = "FAILED"
            wo = inspect_work_order(work_order_id, outcome=outcome)
        elif step == "INVOICED":
            wo = invoice_work_order(
                work_order_id,
                contractor_id,
                invoice_cents if invoice_cents is not None else quote_cents,
            )
        elif step == "PAID":
            wo = pay_work_order(work_order_id)
    return wo if wo is not None else get_work_order(work_order_id)


def setup_project_with_work_order(
    trade="ELECTRICAL",
    item_est=(50_000, 50_000),
    requires_permit=False,
    wo_target_status="QUOTE_REQUESTED",
    quote_cents=50_000,
    include_volunteer_item=False,
    budget_cents=DEFAULT_BUDGET_CENTS,
    contractor_overrides=None,
    **wo_kwargs,
) -> dict:
    """Selected project whose licensed-trade scope item is covered by a work
    order already driven to wo_target_status.

    Returns the selected-project context plus "contractor", "work_order", and
    "trade_item" (the covered ScopeItem dict).
    """
    trade_item_spec = scope_item_payload(
        category="CRITICAL_SYSTEMS",
        required_trade=trade,
        volunteer_performable=False,
        requires_permit=requires_permit,
        est_low_cents=item_est[0],
        est_high_cents=item_est[1],
        description="licensed work",
    )
    specs = [trade_item_spec]
    if include_volunteer_item:
        specs.append(scope_item_payload(description="volunteer work"))
    ctx = setup_selected_project(budget_cents=budget_cents, scope_items=specs)
    contractor = create_contractor(trade=trade, **(contractor_overrides or {}))
    trade_item = next(
        item for item in ctx["scope_items"] if item["volunteer_performable"] is False
    )
    wo = create_work_order(ctx["project"]["id"], contractor["id"], [trade_item["id"]])
    if wo_target_status != "QUOTE_REQUESTED":
        wo = drive_work_order_to(
            wo["id"],
            contractor["id"],
            wo_target_status,
            quote_cents=quote_cents,
            permit_number="PERMIT-1" if requires_permit else None,
            **wo_kwargs,
        )
    ctx.update({"contractor": contractor, "work_order": wo, "trade_item": trade_item})
    ctx["project"] = get_project(ctx["project"]["id"])
    return ctx


# =============================================================================
# Tier 2/3: volunteers, events, enrollments
# =============================================================================

def create_volunteer(**overrides) -> dict:
    """Open registration (Anonymous): REGISTERED, waiver/training null."""
    return get_success_data(api_client.create_volunteer(create_volunteer_payload(**overrides), ANON))


def sign_waiver(volunteer_id, on=DEFAULT_WAIVER_SIGNED_ON) -> dict:
    """Volunteer sets its own waiver date (entity-backed self write)."""
    return get_success_data(
        api_client.patch_volunteer(
            volunteer_id, {"waiver_signed_on": on}, make_volunteer_headers(volunteer_id)
        )
    )


def record_training(volunteer_id, on=DEFAULT_TRAINING_COMPLETED_ON) -> dict:
    """AffiliateStaff records the safety-training date."""
    return get_success_data(
        api_client.patch_volunteer(
            volunteer_id, {"safety_training_completed_on": on}, STAFF
        )
    )


def create_eligible_volunteer(
    team_leader_eligible=False,
    waiver_on=DEFAULT_WAIVER_SIGNED_ON,
    trained_on=DEFAULT_TRAINING_COMPLETED_ON,
    **overrides,
) -> dict:
    """A REGISTERED volunteer with waiver signed and in-window training, so
    is_eligible is true. Returns the re-read volunteer."""
    volunteer = create_volunteer(team_leader_eligible=team_leader_eligible, **overrides)
    sign_waiver(volunteer["id"], waiver_on)
    record_training(volunteer["id"], trained_on)
    return get_volunteer(volunteer["id"])


def create_event(
    project_id,
    event_date=DEFAULT_EVENT_DATE,
    max_volunteers=DEFAULT_MAX_VOLUNTEERS,
    name=None,
) -> dict:
    """Create an event (staff); born DRAFT."""
    overrides = {"event_date": event_date, "max_volunteers": max_volunteers}
    if name is not None:
        overrides["name"] = name
    payload = create_event_payload(project_id, **overrides)
    return get_success_data(api_client.create_event(payload, STAFF))


def publish_event(event_id) -> dict:
    return get_success_data(api_client.patch_event(event_id, {"status": "PUBLISHED"}, STAFF))


def create_published_event(project_id, **kwargs) -> dict:
    """Event walked DRAFT -> PUBLISHED (enrollment open)."""
    return publish_event(create_event(project_id, **kwargs)["id"])


def enroll_volunteer(event_id, volunteer_id, is_team_leader=False) -> dict:
    """Volunteer enrolls itself (entity-backed self enrollment)."""
    payload = {"event_id": event_id, "volunteer_id": volunteer_id}
    if is_team_leader:
        payload["is_team_leader"] = True
    return get_success_data(
        api_client.create_enrollment(payload, make_volunteer_headers(volunteer_id))
    )


def setup_event_with_team_leader(
    project_id,
    event_date=DEFAULT_EVENT_DATE,
    max_volunteers=DEFAULT_MAX_VOLUNTEERS,
) -> dict:
    """PUBLISHED event carrying one active team-leader enrollment.

    Returns {"event", "leader", "leader_enrollment"} with the event re-read
    after enrollment (open_slots reflects the consumed seat).
    """
    event = create_published_event(
        project_id, event_date=event_date, max_volunteers=max_volunteers
    )
    leader = create_eligible_volunteer(team_leader_eligible=True)
    enrollment = enroll_volunteer(event["id"], leader["id"], is_team_leader=True)
    return {
        "event": get_event(event["id"]),
        "leader": leader,
        "leader_enrollment": enrollment,
    }


def setup_locked_event(project_id, event_date=DEFAULT_EVENT_DATE, max_volunteers=DEFAULT_MAX_VOLUNTEERS) -> dict:
    """Event with a team leader, driven PUBLISHED -> LOCKED. Requires the host
    project's readiness_posture to be READY (volunteer-only projects qualify).
    Also fires the host project's READY -> EVENT_SCHEDULED promotion."""
    ctx = setup_event_with_team_leader(project_id, event_date, max_volunteers)
    ctx["event"] = get_success_data(
        api_client.patch_event(ctx["event"]["id"], {"status": "LOCKED"}, STAFF)
    )
    return ctx


def setup_executed_event(project_id, event_date=DEFAULT_EVENT_DATE, max_volunteers=DEFAULT_MAX_VOLUNTEERS) -> dict:
    """LOCKED event executed on its event date: the clock is driven to the
    event day, the team leader checks in, and the event is EXECUTED —
    finalizing attendance, completing volunteer-performable scope items, and
    advancing the host project EVENT_SCHEDULED -> IN_BUILD."""
    ctx = setup_locked_event(project_id, event_date, max_volunteers)
    set_clock(f"{event_date}T07:00:00Z")
    get_success_data(
        api_client.patch_enrollment(
            ctx["leader_enrollment"]["id"],
            {"status": "CHECKED_IN"},
            make_volunteer_headers(ctx["leader"]["id"]),
        )
    )
    ctx["event"] = get_success_data(
        api_client.patch_event(ctx["event"]["id"], {"status": "EXECUTED"}, STAFF)
    )
    return ctx


# =============================================================================
# Tier 4/5: terminal-state and warranty setups
# =============================================================================

def setup_completed_project(event_date=DEFAULT_EVENT_DATE, **project_kwargs) -> dict:
    """A volunteer-only selected project driven to COMPLETED:

    selection -> published/locked/executed event (volunteer scope items
    complete) -> PATCH status=COMPLETED. completed_on is stamped from the
    clock (the event date) and the remaining reserve is released to the cycle.
    Returns the selected-project context plus the event context, with the
    project re-read as COMPLETED and the application re-read as FULFILLED.
    """
    ctx = setup_selected_project(**project_kwargs)
    ctx.update(setup_executed_event(ctx["project"]["id"], event_date=event_date))
    ctx["project"] = get_success_data(
        api_client.patch_project(ctx["project"]["id"], {"status": "COMPLETED"}, STAFF)
    )
    ctx["application"] = get_application(ctx["application"]["id"])
    ctx["cycle"] = get_cycle(ctx["cycle"]["id"])
    return ctx


def setup_warranty_active_project(follow_up_date=DEFAULT_FOLLOW_UP_DATE, **project_kwargs) -> dict:
    """A COMPLETED project whose 30-day follow-up visit is recorded, opening
    WARRANTY_ACTIVE. follow_up_date defaults to 2026-11-10, on/after the
    default 2026-10-10 completion."""
    ctx = setup_completed_project(**project_kwargs)
    ctx["project"] = get_success_data(
        api_client.patch_project(
            ctx["project"]["id"], {"follow_up_completed_on": follow_up_date}, STAFF
        )
    )
    return ctx


def cancel_project(project_id, cancellation_reason="STAFF_DECISION") -> dict:
    """Staff cancellation from PLANNING/READY/EVENT_SCHEDULED with the full
    cascade. Returns the CANCELLED project."""
    return get_success_data(
        api_client.patch_project(
            project_id,
            {"status": "CANCELLED", "cancellation_reason": cancellation_reason},
            STAFF,
        )
    )


# =============================================================================
# Tier 2: material orders and warranty claims
# =============================================================================

def create_material_order(project_id, lines=None, **overrides) -> dict:
    """Place a material order (staff); born ORDERED with computed totals."""
    payload = create_material_order_payload(project_id, lines=lines, **overrides)
    return get_success_data(api_client.create_material_order(payload, STAFF))


def stage_material_order(order_id) -> dict:
    return get_success_data(api_client.patch_material_order(order_id, {"status": "STAGED"}, STAFF))


def deliver_material_order(order_id) -> dict:
    """ORDERED -> STAGED -> DELIVERED; delivery raises the cycle's spent_cents."""
    stage_material_order(order_id)
    return get_success_data(
        api_client.patch_material_order(order_id, {"status": "DELIVERED"}, STAFF)
    )


def create_warranty_claim(
    project_id, application_id, claim_amount_cents=5_000, description=None
) -> dict:
    """File a claim as the owning Homeowner (X-User-ID == application id)."""
    overrides = {"claim_amount_cents": claim_amount_cents}
    if description is not None:
        overrides["description"] = description
    payload = create_warranty_claim_payload(project_id, **overrides)
    return get_success_data(
        api_client.create_warranty_claim(payload, make_homeowner_headers(application_id))
    )


def approve_warranty_claim(claim_id, payout_cents) -> dict:
    return get_success_data(
        api_client.patch_warranty_claim(
            claim_id, {"status": "APPROVED", "payout_cents": payout_cents}, STAFF
        )
    )


def resolve_warranty_claim(claim_id, resolution_note=None) -> dict:
    payload = {"status": "RESOLVED"}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return get_success_data(api_client.patch_warranty_claim(claim_id, payload, STAFF))
