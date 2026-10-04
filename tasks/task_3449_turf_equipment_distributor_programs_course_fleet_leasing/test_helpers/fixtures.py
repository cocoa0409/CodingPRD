"""Composite setup helpers.

Each fixture builds preconditions from scratch against an empty database using
only PRD-declared endpoints, threading entity-backed identities through the
per-instance header builders (the acting DistributorManager's X-User-ID is the
owning Distributor's id; the CourseManager's is the course's id; the
IrrigationDealer's is the dealer Distributor's id). Setup calls use the
lenient get_success_data validator so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO
from .factories import (
    certify_technician_payload,
    create_appraisal_payload,
    create_course_payload,
    create_distributor_payload,
    create_irrigation_project_payload,
    create_lease_payload,
    create_model_payload,
    create_part_payload,
    create_parts_order_payload,
    create_technician_payload,
    create_warranty_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_course_manager_headers,
    make_distributor_manager_headers,
    make_irrigation_dealer_headers,
)

ADMIN = TEST_USERS["corporate_admin_headers"]

DEFAULT_CERT_EXPIRES_AT = "2028-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1/2: base entities and hierarchies
# ---------------------------------------------------------------------------
def create_distributor_active(**overrides):
    """Onboard an equipment distributor and walk it ONBOARDING -> ACTIVE.

    The activation gate (PRD §3.1) requires at least one CERT_ACTIVE technician
    and a non-empty territory_codes; the compliance review applies the gate.
    Returns (distributor, technician).
    """
    payload = create_distributor_payload(**overrides)
    distributor = get_success_data(api_client.create_distributor(payload, ADMIN))
    mgr = make_distributor_manager_headers(distributor["id"])
    technician = get_success_data(
        api_client.create_technician(create_technician_payload(), mgr)
    )
    get_success_data(
        api_client.certify_technician(
            technician["id"], certify_technician_payload(), ADMIN
        )
    )
    reviewed = get_success_data(api_client.run_compliance_review(distributor["id"], ADMIN))
    assert reviewed["status"] == "ACTIVE", (
        f"Setup failed: distributor review left status {reviewed['status']!r}, "
        "expected ACTIVE (needs one CERT_ACTIVE technician and non-empty territory_codes)"
    )
    return reviewed, technician


def create_irrigation_dealer(**overrides):
    """Onboard an irrigation-channel distributor (the dealer identity for
    irrigation projects). Returns the distributor."""
    overrides.setdefault("name", "HydroDesign Co")
    overrides.setdefault("territory_codes", ["CA"])
    overrides["channel"] = "IRRIGATION"
    payload = create_distributor_payload(**overrides)
    return get_success_data(api_client.create_distributor(payload, ADMIN))


def create_course_for(distributor, **overrides):
    """Register a golf course assigned to the given distributor."""
    payload = create_course_payload(distributor["id"], **overrides)
    return get_success_data(api_client.create_course(payload, ADMIN))


def create_catalog_model(**overrides):
    return get_success_data(api_client.create_model(create_model_payload(**overrides), ADMIN))


def create_part_for(model, **overrides):
    return get_success_data(
        api_client.create_part(create_part_payload(model["id"], **overrides), ADMIN)
    )


def setup_program(distributor_overrides=None, course_overrides=None, model_overrides=None):
    """ACTIVE distributor + certified technician + assigned course + one model.
    Returns dict(distributor, technician, course, model)."""
    distributor, technician = create_distributor_active(**(distributor_overrides or {}))
    course = create_course_for(distributor, **(course_overrides or {}))
    model = create_catalog_model(**(model_overrides or {}))
    return {
        "distributor": distributor,
        "technician": technician,
        "course": course,
        "model": model,
    }


# ---------------------------------------------------------------------------
# Tier 1: state progression — fleet leases
# ---------------------------------------------------------------------------
def create_lease_for(distributor, course, lines, **overrides):
    """Create a DRAFT lease for the course under the acting distributor."""
    mgr = make_distributor_manager_headers(distributor["id"])
    payload = create_lease_payload(course["id"], lines, **overrides)
    return get_success_data(api_client.create_lease(payload, mgr))


def submit_lease(lease):
    """DRAFT -> SPEC_REVIEW by the owning DistributorManager (OCC-guarded)."""
    mgr = make_distributor_manager_headers(lease["distributor_id"])
    return get_success_data(
        api_client.transition_lease(lease["id"], "SPEC_REVIEW", lease["version"], mgr)
    )


def revert_lease_to_draft(lease):
    """SPEC_REVIEW -> DRAFT by the owning DistributorManager (OCC-guarded)."""
    mgr = make_distributor_manager_headers(lease["distributor_id"])
    return get_success_data(
        api_client.transition_lease(lease["id"], "DRAFT", lease["version"], mgr)
    )


def approve_lease(lease):
    """SPEC_REVIEW -> APPROVED by CorporateAdmin (OCC-guarded)."""
    return get_success_data(
        api_client.transition_lease(lease["id"], "APPROVED", lease["version"], ADMIN)
    )


def activate_lease(lease):
    """APPROVED -> ACTIVE by the owning DistributorManager (OCC-guarded)."""
    mgr = make_distributor_manager_headers(lease["distributor_id"])
    return get_success_data(
        api_client.transition_lease(lease["id"], "ACTIVE", lease["version"], mgr)
    )


def cancel_lease(lease, as_admin=False):
    """DRAFT -> CANCELLED by the owner, or SPEC_REVIEW -> CANCELLED by admin."""
    headers = (
        ADMIN if as_admin else make_distributor_manager_headers(lease["distributor_id"])
    )
    return get_success_data(
        api_client.transition_lease(lease["id"], "CANCELLED", lease["version"], headers)
    )


def walk_lease_to(lease, target_state):
    """Walk a lease through the linear chain DRAFT -> SPEC_REVIEW -> APPROVED
    -> ACTIVE, stopping at target_state. Returns the updated lease."""
    if target_state == "DRAFT":
        return lease
    if lease["status"] == "DRAFT":
        lease = submit_lease(lease)
    if target_state == "SPEC_REVIEW":
        return lease
    if lease["status"] == "SPEC_REVIEW":
        lease = approve_lease(lease)
    if target_state == "APPROVED":
        return lease
    if lease["status"] == "APPROVED":
        lease = activate_lease(lease)
    assert lease["status"] == target_state, (
        f"Setup failed: lease walk ended at {lease['status']!r}, wanted {target_state!r}"
    )
    return lease


# ---------------------------------------------------------------------------
# Tier 2/3: units through delivery and service
# ---------------------------------------------------------------------------
def list_lease_units(lease):
    """Units of the lease in canonical unit_seq order."""
    data = get_success_data(
        api_client.list_units(ADMIN, params={"lease_id": lease["id"]})
    )
    assert isinstance(data, list) and data, "Setup failed: lease has no units"
    return data


def deliver_unit(unit, serial_number):
    """ORDERED -> DELIVERED recorded by the owning lease's distributor."""
    lease = get_success_data(api_client.get_lease(unit["lease_id"], ADMIN))
    mgr = make_distributor_manager_headers(lease["distributor_id"])
    return get_success_data(
        api_client.transition_unit(unit["id"], "DELIVERED", mgr, serial_number=serial_number)
    )


def put_unit_in_service(unit, course):
    """DELIVERED -> IN_SERVICE by the CourseManager of the lease's course."""
    cm = make_course_manager_headers(course["id"])
    return get_success_data(api_client.transition_unit(unit["id"], "IN_SERVICE", cm))


def request_unit_return(unit, course):
    """IN_SERVICE -> RETURN_REQUESTED by the lease course's CourseManager."""
    cm = make_course_manager_headers(course["id"])
    return get_success_data(
        api_client.transition_unit(unit["id"], "RETURN_REQUESTED", cm)
    )


def record_unit_return(unit, hours_used=300, condition_grade="B"):
    """RETURN_REQUESTED -> RETURNED recorded by the owning distributor."""
    lease = get_success_data(api_client.get_lease(unit["lease_id"], ADMIN))
    mgr = make_distributor_manager_headers(lease["distributor_id"])
    return get_success_data(
        api_client.transition_unit(
            unit["id"], "RETURNED", mgr,
            hours_used=hours_used, condition_grade=condition_grade,
        )
    )


def remarket_list_unit(unit):
    """RETURNED -> REMARKET_LISTED; runs remarketing pricing (PRD §3.7)."""
    lease = get_success_data(api_client.get_lease(unit["lease_id"], ADMIN))
    mgr = make_distributor_manager_headers(lease["distributor_id"])
    return get_success_data(api_client.transition_unit(unit["id"], "REMARKET_LISTED", mgr))


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_lease_scenario(lease_overrides=None, **program_kwargs):
    """Program (distributor/course/model) + a DRAFT lease over one model unit.
    Returns dict with the program plus 'lease'."""
    ctx = setup_program(**program_kwargs)
    lease = create_lease_for(
        ctx["distributor"],
        ctx["course"],
        [{"model_id": ctx["model"]["id"], "qty": 1}],
        **(lease_overrides or {}),
    )
    ctx["lease"] = lease
    return ctx


def setup_lease_in_state(target_state, lease_overrides=None, **program_kwargs):
    """Lease scenario walked to the requested state (DRAFT/SPEC_REVIEW/
    APPROVED/ACTIVE). For APPROVED/ACTIVE the lease start_date must be
    reachable at the default clock — pass lease_overrides accordingly."""
    ctx = setup_lease_scenario(lease_overrides=lease_overrides, **program_kwargs)
    ctx["lease"] = walk_lease_to(ctx["lease"], target_state)
    return ctx


def setup_active_lease_with_in_service_unit(serial_number="SN-A1", **program_kwargs):
    """The canonical serviceable setup: ACTIVE lease (start 2026-09-01, the
    default clock date) with its single unit DELIVERED then IN_SERVICE.
    Returns dict(distributor, technician, course, model, lease, unit)."""
    lease_overrides = {"cycle_months": 36, "start_date": "2026-09-01"}
    ctx = setup_lease_in_state("ACTIVE", lease_overrides=lease_overrides, **program_kwargs)
    unit = list_lease_units(ctx["lease"])[0]
    unit = deliver_unit(unit, serial_number)
    unit = put_unit_in_service(unit, ctx["course"])
    ctx["unit"] = unit
    return ctx


def setup_turned_over_lease(unit_count=1, clock_to="2026-10-02T00:00:00Z",
                            serial_prefix="SN-T", **program_kwargs):
    """A cycle-1 lease started 2026-09-01, fully in service; the clock is then
    advanced past end_date and the season rollover moves the lease to
    TURNOVER_IN_PROGRESS and sweeps every IN_SERVICE unit to RETURN_REQUESTED
    (PRD §3.6). Returns ctx with 'units' list."""
    ctx = setup_program(**program_kwargs)
    lease = create_lease_for(
        ctx["distributor"], ctx["course"],
        [{"model_id": ctx["model"]["id"], "qty": unit_count}],
        cycle_months=1, start_date="2026-09-01",
    )
    lease = walk_lease_to(lease, "ACTIVE")
    units = []
    for i, u in enumerate(list_lease_units(lease), start=1):
        u = deliver_unit(u, f"{serial_prefix}{i}")
        u = put_unit_in_service(u, ctx["course"])
        units.append(u)
    advance_clock(clock_to)
    run_rollover()
    lease = get_success_data(api_client.get_lease(lease["id"], ADMIN))
    assert lease["status"] == "TURNOVER_IN_PROGRESS", (
        f"Setup failed: lease is {lease['status']!r} after rollover, "
        "expected TURNOVER_IN_PROGRESS"
    )
    ctx["lease"] = lease
    ctx["units"] = [
        get_success_data(api_client.get_unit(u["id"], ADMIN)) for u in units
    ]
    return ctx


def setup_remarketed_unit(hours_used=800, condition_grade="B",
                          serial_number="SN-U1", **program_kwargs):
    """Turnover plus the physical return and remarket listing: the unit ends
    REMARKET_LISTED with asking/floor prices set. Returns ctx with 'unit'."""
    ctx = setup_turned_over_lease(unit_count=1, **program_kwargs)
    unit = record_unit_return(
        ctx["units"][0], hours_used=hours_used, condition_grade=condition_grade
    )
    unit = remarket_list_unit(unit)
    ctx["unit"] = unit
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: appraisals
# ---------------------------------------------------------------------------
def create_appraisal_for(lease, model, distributor=None, **overrides):
    """Create a VALUED trade-in appraisal against a DRAFT/SPEC_REVIEW lease."""
    distributor = distributor or get_success_data(
        api_client.get_distributor(lease["distributor_id"], ADMIN)
    )
    mgr = make_distributor_manager_headers(distributor["id"])
    payload = create_appraisal_payload(lease["id"], model["id"], **overrides)
    return get_success_data(api_client.create_appraisal(payload, mgr))


def accept_appraisal(appraisal, course):
    """VALUED -> ACCEPTED by the CourseManager of the lease's course."""
    cm = make_course_manager_headers(course["id"])
    return get_success_data(api_client.transition_appraisal(appraisal["id"], "ACCEPTED", cm))


def dispute_appraisal(appraisal, course):
    """VALUED -> DISPUTED by the CourseManager of the lease's course."""
    cm = make_course_manager_headers(course["id"])
    return get_success_data(api_client.transition_appraisal(appraisal["id"], "DISPUTED", cm))


def revalue_appraisal(appraisal, lease, **overrides):
    """DISPUTED -> VALUED by the owning DistributorManager; optional override
    inputs (hours / condition_grade / policy) are applied before revaluation."""
    mgr = make_distributor_manager_headers(lease["distributor_id"])
    return get_success_data(
        api_client.transition_appraisal(appraisal["id"], "VALUED", mgr, **overrides)
    )


def void_appraisal(appraisal, lease):
    """DISPUTED -> VOIDED by the owning DistributorManager."""
    mgr = make_distributor_manager_headers(lease["distributor_id"])
    return get_success_data(api_client.transition_appraisal(appraisal["id"], "VOIDED", mgr))


# ---------------------------------------------------------------------------
# Tier 3: parts orders through the pipeline
# ---------------------------------------------------------------------------
def create_order_for(distributor, lines, **overrides):
    """Create a DRAFT parts order for the acting distributor."""
    mgr = make_distributor_manager_headers(distributor["id"])
    payload = create_parts_order_payload(lines, **overrides)
    return get_success_data(api_client.create_parts_order(payload, mgr))


def submit_order(order):
    mgr = make_distributor_manager_headers(order["distributor_id"])
    return get_success_data(api_client.transition_parts_order(order["id"], "SUBMITTED", mgr))


def allocate_order(order):
    return get_success_data(api_client.transition_parts_order(order["id"], "ALLOCATED", ADMIN))


def ship_order(order):
    return get_success_data(api_client.transition_parts_order(order["id"], "SHIPPED", ADMIN))


def receive_order(order, received_lines):
    mgr = make_distributor_manager_headers(order["distributor_id"])
    return get_success_data(
        api_client.transition_parts_order(
            order["id"], "RECEIVED", mgr, received_lines=received_lines
        )
    )


def cancel_order(order, as_admin=False):
    headers = (
        ADMIN if as_admin else make_distributor_manager_headers(order["distributor_id"])
    )
    return get_success_data(api_client.transition_parts_order(order["id"], "CANCELLED", headers))


def create_and_receive_order(distributor, part, qty_ordered, qty_received):
    """Full pipeline DRAFT -> SUBMITTED -> ALLOCATED -> SHIPPED -> RECEIVED.
    Returns the RECEIVED order (the raw material for compliance reviews)."""
    order = create_order_for(distributor, [{"part_id": part["id"], "qty": qty_ordered}])
    order = submit_order(order)
    order = allocate_order(order)
    order = ship_order(order)
    return receive_order(order, [{"part_id": part["id"], "qty": qty_received}])


# ---------------------------------------------------------------------------
# Tier 3: warranty claims through adjudication
# ---------------------------------------------------------------------------
def create_claim_for(unit, technician, distributor, **overrides):
    """File a SUBMITTED warranty claim for an IN_SERVICE unit."""
    mgr = make_distributor_manager_headers(distributor["id"])
    payload = create_warranty_claim_payload(unit["id"], technician["id"], **overrides)
    return get_success_data(api_client.create_warranty_claim(payload, mgr))


def setup_submitted_claim(**program_kwargs):
    """Serviceable setup + one SUBMITTED claim. Returns ctx with 'claim'."""
    ctx = setup_active_lease_with_in_service_unit(**program_kwargs)
    ctx["claim"] = create_claim_for(ctx["unit"], ctx["technician"], ctx["distributor"])
    return ctx


def claim_to_under_review(claim):
    return get_success_data(
        api_client.transition_warranty_claim(claim["id"], "UNDER_REVIEW", claim["version"], ADMIN)
    )


def claim_to_approved(claim):
    """UNDER_REVIEW -> APPROVED (adjudication on full claimed hours)."""
    return get_success_data(
        api_client.transition_warranty_claim(claim["id"], "APPROVED", claim["version"], ADMIN)
    )


def claim_to_partial_approved(claim, approved_labor_hours):
    return get_success_data(
        api_client.transition_warranty_claim(
            claim["id"], "PARTIAL_APPROVED", claim["version"], ADMIN,
            approved_labor_hours=approved_labor_hours,
        )
    )


def claim_to_denied(claim):
    return get_success_data(
        api_client.transition_warranty_claim(claim["id"], "DENIED", claim["version"], ADMIN)
    )


def claim_to_disputed(claim):
    """DENIED or PARTIAL_APPROVED -> DISPUTED by the owning distributor."""
    mgr = make_distributor_manager_headers(claim["distributor_id"])
    return get_success_data(
        api_client.transition_warranty_claim(claim["id"], "DISPUTED", claim["version"], mgr)
    )


def claim_to_paid(claim):
    return get_success_data(
        api_client.transition_warranty_claim(claim["id"], "PAID", claim["version"], ADMIN)
    )


def setup_approved_claim(**program_kwargs):
    """SUBMITTED claim walked SUBMITTED -> UNDER_REVIEW -> APPROVED."""
    ctx = setup_submitted_claim(**program_kwargs)
    ctx["claim"] = claim_to_under_review(ctx["claim"])
    ctx["claim"] = claim_to_approved(ctx["claim"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: irrigation projects
# ---------------------------------------------------------------------------
def create_controller_model(**overrides):
    overrides.setdefault("model_code", "TMC-424E")
    overrides.setdefault("category", "IRRIGATION_CONTROLLER")
    overrides.setdefault("tier", "STANDARD")
    overrides.setdefault("list_price_cents", 180000)
    overrides.setdefault(
        "eligible_turf_types", ["BENTGRASS", "BERMUDA", "POA_ANNUA", "MIXED"]
    )
    overrides.setdefault("parts_support_years", 12)
    return create_catalog_model(**overrides)


def setup_irrigation_project(course_overrides=None, project_overrides=None,
                             dealer_overrides=None):
    """Irrigation dealer + course (assigned to a separate equipment
    distributor for territory validity) + controller model + project in BRIEF.
    Returns dict(dealer, distributor, course, controller, project)."""
    dealer = create_irrigation_dealer(**(dealer_overrides or {}))
    distributor = get_success_data(
        api_client.create_distributor(create_distributor_payload(), ADMIN)
    )
    course = create_course_for(distributor, **(course_overrides or {}))
    controller = create_controller_model()
    dealer_headers = make_irrigation_dealer_headers(dealer["id"])
    project = get_success_data(
        api_client.create_irrigation_project(
            create_irrigation_project_payload(course["id"], **(project_overrides or {})),
            dealer_headers,
        )
    )
    return {
        "dealer": dealer,
        "distributor": distributor,
        "course": course,
        "controller": controller,
        "project": project,
    }


def submit_design(project, controller, window_start="2027-04-01", window_end="2027-05-01"):
    """BRIEF -> DESIGN_SUBMITTED by the owning dealer; pins the controller and
    the half-open install window and runs the design spec (PRD §3.9)."""
    dealer_headers = make_irrigation_dealer_headers(project["dealer_id"])
    return get_success_data(
        api_client.transition_irrigation_project(
            project["id"], "DESIGN_SUBMITTED", dealer_headers,
            controller_model_id=controller["id"],
            install_window_start=window_start,
            install_window_end=window_end,
        )
    )


def approve_design(project, course):
    """DESIGN_SUBMITTED -> APPROVED by the project course's CourseManager."""
    cm = make_course_manager_headers(course["id"])
    return get_success_data(
        api_client.transition_irrigation_project(project["id"], "APPROVED", cm)
    )


# ---------------------------------------------------------------------------
# Logical clock and season rollover (PRD §2.5)
# ---------------------------------------------------------------------------
def advance_clock(to_iso8601):
    """Set the logical clock; the instant must be reachable from the fixed
    startup default 2026-09-01T00:00:00Z (never set it backwards across data)."""
    return get_success_data(api_client.set_current_utc(to_iso8601, ADMIN))


def run_rollover():
    """Run the ops checkpoint: billing, turnover, cert expiry, reservation
    expiry, one remarketing decay step, model aging."""
    return get_success_data(api_client.run_season_rollover(ADMIN))
