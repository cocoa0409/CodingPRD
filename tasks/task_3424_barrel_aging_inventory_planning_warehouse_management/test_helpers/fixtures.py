"""Composite setup helpers.

Every fixture builds preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before every test, so each test starts
against an empty database at the default clock). Setup calls use the lenient
get_success_data() so a broken precondition surfaces as "Setup failed".

Logical-clock discipline: fixtures advance the clock only forward and only
to explicit instants. ``create_commissioned_rickhouse`` starts from the
server's startup default (PRD §2.4) unless ``reset_clock=False`` is passed
for composing a second rickhouse inside one test. Helpers that take
``at_clock`` require a value at or after the current logical clock.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DAYS_PER_MONTH,
    DEFAULT_CLOCK_ISO,
    LIMIT_MAX,
    STANDARD_BOTTLING_ISO,
    STANDARD_CONSTRUCTION_LAG_MONTHS,
    STANDARD_FILL_ISO,
    TEST_DEFAULTS,
)
from .factories import (
    add_blend_component_payload,
    create_barrel_payload,
    create_blend_batch_payload,
    create_bonded_report_payload,
    create_expansion_project_payload,
    create_label_payload,
    create_program_payload,
    create_reservation_payload,
    create_assessment_payload,
    rotate_barrel_payload,
    set_clock_payload,
)
from .test_users import (
    DEFAULT_OFFICER_USER_ID,
    DEFAULT_PREPARER_USER_ID,
    TEST_USERS,
    make_bonded_preparer_headers,
    make_compliance_officer_headers,
)
from .types import AssessmentKind

_PLANNER = TEST_USERS["distillery_planner_headers"]
_OPS = TEST_USERS["operations_director_headers"]
_WAREHOUSE = TEST_USERS["warehouse_manager_headers"]
_BLENDER = TEST_USERS["master_blender_headers"]
_PROGRAM = TEST_USERS["program_director_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


# =============================================================================
# Clock and calendar utilities
# =============================================================================

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock; returns the {"current_utc": ...} payload."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), _ADMIN))


def iso_plus_days(iso: str, days: int) -> str:
    """Add ``days`` fixed-length days to an ISO 8601 UTC instant (YYYY...Z)."""
    parsed = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    shifted = parsed + timedelta(days=days)
    return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


def commission_date_for(approved_at_iso: str, construction_lag_months: int) -> str:
    """Earliest commissionable instant: approved_at + lag months of 30 days
    (PRD §3.1 — the clock must have reached approved_at + lag x thirty days)."""
    return iso_plus_days(approved_at_iso, construction_lag_months * DAYS_PER_MONTH)


# =============================================================================
# Tier 1/2: the capacity chain — project -> approve -> commission -> slots
# =============================================================================

def create_commissioned_rickhouse(
    *,
    floors: int = TEST_DEFAULTS["FLOORS"],
    rows_per_floor: int = TEST_DEFAULTS["ROWS_PER_FLOOR"],
    positions_per_row: int = TEST_DEFAULTS["POSITIONS_PER_ROW"],
    construction_lag_months: int = STANDARD_CONSTRUCTION_LAG_MONTHS,
    name: str = TEST_DEFAULTS["PROJECT_NAME"],
    region_code: str = TEST_DEFAULTS["REGION_CODE"],
    planned_annual_distillation_liters: int = TEST_DEFAULTS["PLANNED_ANNUAL_DISTILLATION_LITERS"],
    ready_clock: str = STANDARD_FILL_ISO,
    reset_clock: bool = True,
) -> dict:
    """Full capacity chain ending in an OPERATING rickhouse with its slot grid.

    Chain: clock -> startup default (unless reset_clock=False) -> propose ->
    approve (stamps approved_at) -> clock -> approved_at + lag*30 days ->
    commission (rickhouse PLANNED -> OPERATING, slots materialized) ->
    clock -> ready_clock (unless None). Pass reset_clock=False and
    ready_clock=None to build a second rickhouse later in the same test.

    Returns {"project": <COMMISSIONED project>, "rickhouse": ..., "slots": [...]}.
    Slots come in deterministic (floor_index, row_index, position_index) order.
    """
    if reset_clock:
        set_clock(DEFAULT_CLOCK_ISO)
    payload = create_expansion_project_payload(
        name=name,
        region_code=region_code,
        floors=floors,
        rows_per_floor=rows_per_floor,
        positions_per_row=positions_per_row,
        construction_lag_months=construction_lag_months,
        planned_annual_distillation_liters=planned_annual_distillation_liters,
    )
    project = get_success_data(api_client.create_expansion_project(payload, _PLANNER))
    approved = get_success_data(api_client.approve_expansion_project(project["id"], _OPS))
    commission_iso = commission_date_for(approved["approved_at"], construction_lag_months)
    set_clock(commission_iso)
    project = get_success_data(api_client.commission_expansion_project(project["id"], _OPS))
    rickhouses = get_success_data(
        api_client.list_rickhouses(_ADMIN, params={"expansion_project_id": project["id"]})
    )
    assert len(rickhouses) == 1, f"Setup failed: expected 1 cascaded rickhouse, got {len(rickhouses)}"
    rickhouse = rickhouses[0]
    slots = get_success_data(
        api_client.list_rickhouse_slots(rickhouse["id"], _ADMIN, params={"limit": LIMIT_MAX})
    )
    if ready_clock is not None:
        set_clock(ready_clock)
    return {"project": project, "rickhouse": rickhouse, "slots": slots}


def fill_placed_barrel(slot_id: str, headers: dict = None, **overrides) -> dict:
    """Fill a barrel into a free slot of an OPERATING rickhouse.

    The creation response already shows maturation AGING and custody BONDED
    with one OPEN INITIAL_FILL occupancy (PRD §3.2). Returns the Barrel.
    """
    payload = create_barrel_payload(slot_id, **overrides)
    return get_success_data(api_client.create_barrel(payload, headers or _WAREHOUSE))


def fill_mature_barrel(slot_id: str, headers: dict = None, **overrides) -> dict:
    """Fill a barrel that is MATURE_ELIGIBLE immediately (min_maturation_months
    0: the eligibility clock condition holds at fill time, PRD §3.3)."""
    overrides.setdefault("min_maturation_months", 0)
    return fill_placed_barrel(slot_id, headers=headers, **overrides)


def fill_barrels_on_slots(slot_ids, headers: dict = None, **common_overrides) -> list:
    """Fill one barrel per slot (entries may be slot dicts or id strings)."""
    barrels = []
    for slot in slot_ids:
        slot_id = slot["id"] if isinstance(slot, dict) else slot
        barrels.append(fill_placed_barrel(slot_id, headers=headers, **common_overrides))
    return barrels


def setup_barrel_scenario(*, barrel_overrides: dict = None, **rickhouse_kwargs) -> dict:
    """Commissioned rickhouse plus one barrel on its first slot.
    Returns the rickhouse context with an added "barrel" key."""
    ctx = create_commissioned_rickhouse(**rickhouse_kwargs)
    ctx["barrel"] = fill_placed_barrel(ctx["slots"][0]["id"], **(barrel_overrides or {}))
    return ctx


def setup_mature_barrel_scenario(*, barrel_overrides: dict = None, **rickhouse_kwargs) -> dict:
    """Commissioned rickhouse plus one immediately-MATURE_ELIGIBLE barrel."""
    overrides = {"min_maturation_months": 0}
    overrides.update(barrel_overrides or {})
    return setup_barrel_scenario(barrel_overrides=overrides, **rickhouse_kwargs)


# =============================================================================
# Barrel operations (OCC-aware where the endpoint requires it)
# =============================================================================

def get_barrel_fresh(barrel_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_barrel(barrel_id, headers or _ADMIN))


def rotate_barrel(barrel_id: str, to_slot_id: str, headers: dict = None) -> dict:
    """Rotate with a fresh expected_barrel_version (re-read first, PRD §2.7)."""
    headers = headers or _WAREHOUSE
    barrel = get_success_data(api_client.get_barrel(barrel_id, headers))
    payload = rotate_barrel_payload(to_slot_id, barrel["version"])
    return get_success_data(api_client.rotate_barrel(barrel_id, payload, headers))


def dump_barrel(barrel_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.dump_barrel(barrel_id, headers or _WAREHOUSE))


def withdraw_barrel(barrel_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.withdraw_barrel(barrel_id, headers or _WAREHOUSE))


def record_evaporation_reading(barrel_id: str, measured_volume_liters: float, headers: dict = None, **overrides) -> dict:
    payload = create_assessment_payload(
        AssessmentKind.EVAPORATION_READING.value,
        measured_volume_liters=measured_volume_liters,
        **overrides,
    )
    return get_success_data(api_client.create_barrel_assessment(barrel_id, payload, headers or _WAREHOUSE))


def record_quality_sample(
    barrel_id: str,
    sample_draw_liters: float = TEST_DEFAULTS["SAMPLE_DRAW_LITERS"],
    quality_score: int = None,
    headers: dict = None,
    **overrides,
) -> dict:
    """Record a QUALITY_SAMPLE; quality_score is sent only when not None
    (an omitted score persists as null, PRD §3.3)."""
    if quality_score is not None:
        overrides["quality_score"] = quality_score
    payload = create_assessment_payload(
        AssessmentKind.QUALITY_SAMPLE.value,
        sample_draw_liters=sample_draw_liters,
        **overrides,
    )
    return get_success_data(api_client.create_barrel_assessment(barrel_id, payload, headers or _WAREHOUSE))


# =============================================================================
# Labels and blend batches
# =============================================================================

def create_active_label(headers: dict = None, **overrides) -> dict:
    """Register + activate a label. Returns the ACTIVE label."""
    headers = headers or _BLENDER
    label = get_success_data(api_client.create_label(create_label_payload(**overrides), headers))
    return get_success_data(api_client.activate_label(label["id"], headers))


def create_blend_batch(label_id: str, scheduled_bottling_date: str = STANDARD_BOTTLING_ISO, headers: dict = None) -> dict:
    payload = create_blend_batch_payload(label_id, scheduled_bottling_date)
    return get_success_data(api_client.create_blend_batch(payload, headers or _BLENDER))


def get_blend_batch_fresh(batch_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_blend_batch(batch_id, headers or _ADMIN))


def add_component(batch_id: str, barrel_id: str, drawn_volume_liters: float, headers: dict = None) -> dict:
    """Add a component with a fresh expected_blend_batch_version (PRD §2.7)."""
    headers = headers or _BLENDER
    batch = get_success_data(api_client.get_blend_batch(batch_id, headers))
    payload = add_blend_component_payload(barrel_id, drawn_volume_liters, batch["version"])
    return get_success_data(api_client.add_blend_component(batch_id, payload, headers))


def create_batch_with_component(
    label_id: str,
    barrel_id: str,
    drawn_volume_liters: float,
    scheduled_bottling_date: str = STANDARD_BOTTLING_ISO,
    headers: dict = None,
) -> tuple:
    """PROPOSED batch carrying one component. Returns (batch, component)."""
    batch = create_blend_batch(label_id, scheduled_bottling_date, headers=headers)
    component = add_component(batch["id"], barrel_id, drawn_volume_liters, headers=headers)
    batch = get_blend_batch_fresh(batch["id"], headers=headers)
    return batch, component


def create_validated_batch(
    label_id: str,
    barrel_id: str,
    drawn_volume_liters: float,
    scheduled_bottling_date: str = STANDARD_BOTTLING_ISO,
    headers: dict = None,
) -> dict:
    """Batch walked create -> add component -> validate. Returns VALIDATED batch."""
    headers = headers or _BLENDER
    batch, _component = create_batch_with_component(
        label_id, barrel_id, drawn_volume_liters, scheduled_bottling_date, headers=headers
    )
    return get_success_data(api_client.validate_blend_batch(batch["id"], headers))


def create_committed_batch(
    label_id: str,
    barrel_id: str,
    drawn_volume_liters: float,
    scheduled_bottling_date: str = STANDARD_BOTTLING_ISO,
    headers: dict = None,
) -> dict:
    """Batch walked through commit. Returns the COMMITTED batch (drawn volumes
    already deducted from component barrels, PRD §3.5)."""
    headers = headers or _BLENDER
    batch = create_validated_batch(
        label_id, barrel_id, drawn_volume_liters, scheduled_bottling_date, headers=headers
    )
    return get_success_data(api_client.commit_blend_batch(batch["id"], headers))


# =============================================================================
# Private selection programs and reservations
# =============================================================================

def create_program(headers: dict = None, **overrides) -> dict:
    payload = create_program_payload(**overrides)
    return get_success_data(api_client.create_private_selection_program(payload, headers or _PROGRAM))


def get_program_fresh(program_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_private_selection_program(program_id, headers or _ADMIN))


def get_eligible_barrels(program_id: str, headers: dict = None, params: dict = None) -> list:
    return get_success_data(api_client.list_eligible_barrels(program_id, headers or _ADMIN, params=params))


def create_reservation(program_id: str, barrel_id: str, headers: dict = None) -> dict:
    """Reserve with a fresh expected_program_version (re-read first, PRD §2.7)."""
    headers = headers or _PROGRAM
    program = get_success_data(api_client.get_private_selection_program(program_id, headers))
    payload = create_reservation_payload(barrel_id, program["version"])
    return get_success_data(api_client.create_reservation(program_id, payload, headers))


def consume_reservation(reservation_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.consume_reservation(reservation_id, headers or _PROGRAM))


def release_reservation(reservation_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.release_reservation(reservation_id, headers or _PROGRAM))


def setup_program_with_mature_barrel(
    *,
    barrel_overrides: dict = None,
    program_overrides: dict = None,
    **rickhouse_kwargs,
) -> dict:
    """Commissioned rickhouse + one MATURE_ELIGIBLE barrel + one program.
    Returns the rickhouse context with added "barrel" and "program" keys."""
    ctx = setup_mature_barrel_scenario(barrel_overrides=barrel_overrides, **rickhouse_kwargs)
    ctx["program"] = create_program(**(program_overrides or {}))
    return ctx


# =============================================================================
# Bonded period reports (segregation-of-duties aware)
# =============================================================================

def create_report(period_start: str, period_end: str, preparer_user_id: str = DEFAULT_PREPARER_USER_ID) -> dict:
    """Open a bonded-period report (state OPEN)."""
    headers = make_bonded_preparer_headers(preparer_user_id)
    payload = create_bonded_report_payload(period_start, period_end)
    return get_success_data(api_client.create_bonded_report(payload, headers))


def reconcile_report(report_id: str, at_clock: str = None, preparer_user_id: str = DEFAULT_PREPARER_USER_ID) -> dict:
    """Reconcile an OPEN report. The clock must be at or after period_end
    (PRD §3.7); when at_clock is omitted the clock is advanced to the
    report's period_end. Any explicit at_clock must be >= the current clock."""
    headers = make_bonded_preparer_headers(preparer_user_id)
    if at_clock is None:
        report = get_success_data(api_client.get_bonded_report(report_id, headers))
        at_clock = report["period_end"]
    set_clock(at_clock)
    return get_success_data(api_client.reconcile_bonded_report(report_id, headers))


def file_report(report_id: str, preparer_user_id: str = DEFAULT_PREPARER_USER_ID) -> dict:
    headers = make_bonded_preparer_headers(preparer_user_id)
    return get_success_data(api_client.file_bonded_report(report_id, headers))


def accept_report(report_id: str, officer_user_id: str = DEFAULT_OFFICER_USER_ID) -> dict:
    """Accept a FILED report. The default officer id differs from the default
    filer id, satisfying segregation of duties (PRD §3.7)."""
    headers = make_compliance_officer_headers(officer_user_id)
    return get_success_data(api_client.accept_bonded_report(report_id, headers))


def reject_report(report_id: str, officer_user_id: str = DEFAULT_OFFICER_USER_ID) -> dict:
    headers = make_compliance_officer_headers(officer_user_id)
    return get_success_data(api_client.reject_bonded_report(report_id, headers))


def amend_report(report_id: str, preparer_user_id: str = DEFAULT_PREPARER_USER_ID) -> dict:
    headers = make_bonded_preparer_headers(preparer_user_id)
    return get_success_data(api_client.amend_bonded_report(report_id, headers))


def create_reconciled_report(
    period_start: str,
    period_end: str,
    at_clock: str = None,
    preparer_user_id: str = DEFAULT_PREPARER_USER_ID,
) -> dict:
    """OPEN report created, clock advanced, reconciled. Returns RECONCILED report."""
    report = create_report(period_start, period_end, preparer_user_id=preparer_user_id)
    return reconcile_report(report["id"], at_clock=at_clock, preparer_user_id=preparer_user_id)


def create_filed_report(
    period_start: str,
    period_end: str,
    at_clock: str = None,
    preparer_user_id: str = DEFAULT_PREPARER_USER_ID,
) -> dict:
    """Reconcile + file. Returns the FILED report (a FILED or ACCEPTED report
    covering the current clock is the withdrawal compliance gate, PRD §3.4)."""
    report = create_reconciled_report(period_start, period_end, at_clock=at_clock, preparer_user_id=preparer_user_id)
    return file_report(report["id"], preparer_user_id=preparer_user_id)


def create_accepted_report(
    period_start: str,
    period_end: str,
    at_clock: str = None,
    preparer_user_id: str = DEFAULT_PREPARER_USER_ID,
    officer_user_id: str = DEFAULT_OFFICER_USER_ID,
) -> dict:
    """Full compliance loop through ACCEPTED (the terminal report state)."""
    report = create_filed_report(period_start, period_end, at_clock=at_clock, preparer_user_id=preparer_user_id)
    return accept_report(report["id"], officer_user_id=officer_user_id)
