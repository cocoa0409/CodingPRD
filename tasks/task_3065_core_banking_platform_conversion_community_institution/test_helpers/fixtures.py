"""Composite setup helpers.

Most interesting claims require the system to be in a state that takes many
API calls to reach (project + active product + GL + mapped account + a passed
mock run + a planned/scheduled/GO cutover plan + go-live). These fixtures
encapsulate those chains so tests can focus on assertions.

Every helper builds its preconditions from scratch using only public
endpoints; the harness restarts the server (empty database) before each
test. All helpers use get_success_data() internally so setup failures
surface as clear "Setup failed" assertion errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_project_payload, create_product_type_payload, create_gl_account_payload,
    create_account_payload, create_mock_run_payload,
    create_ancillary_system_payload, create_training_session_payload,
    create_staff_payload, create_enrollment_payload, create_comm_payload,
    create_defect_payload, create_service_credit_payload, plan_cutover_payload,
    create_task_payload,
)
from .test_users import TEST_USERS

PM = TEST_USERS["pm_headers"]
CE = TEST_USERS["ce_headers"]
OPS = TEST_USERS["ops_headers"]
TRAINER = TEST_USERS["trainer_headers"]
CO = TEST_USERS["co_headers"]
VTL = TEST_USERS["vtl_headers"]
FC = TEST_USERS["fc_headers"]

# Standard cutover-weekend geometry used across the happy paths (PRD §3.6/§3.7).
CUTOVER_DATE = "2026-09-20"
FILE_FREEZE_START = "2026-09-19T18:00:00Z"
GO_NO_GO = "2026-09-19T20:00:00Z"
REOPEN_TARGET = "2026-09-21T06:00:00Z"
TASK1_START = "2026-09-19T19:00:00Z"
TASK1_END = "2026-09-19T21:00:00Z"
CLOCK_AFTER_CHECKPOINT = "2026-09-19T20:30:00Z"
GO_LIVE_CLOCK = "2026-09-20T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: atomic builders
# ---------------------------------------------------------------------------

def set_clock(current_utc):
    """Advance the logical clock; returns the clock response data."""
    return get_success_data(api_client.set_clock(current_utc, PM))


def create_project(**overrides):
    return get_success_data(
        api_client.create_project(create_project_payload(**overrides), PM), 201
    )


def create_product(project_id, active=True, **overrides):
    pt = get_success_data(
        api_client.create_product_type(
            create_product_type_payload(project_id, **overrides), CE
        ),
        201,
    )
    if active:
        pt = get_success_data(api_client.activate_product_type(pt["id"], CE))
    return pt


def create_gl(project_id, **overrides):
    return get_success_data(
        api_client.create_gl_account(create_gl_account_payload(project_id, **overrides), CE),
        201,
    )


def create_account(project_id, product_type_id, **overrides):
    return get_success_data(
        api_client.create_account(
            create_account_payload(project_id, product_type_id, **overrides), CE
        ),
        201,
    )


def current_project_version(project_id):
    return get_success_data(api_client.get_project(project_id, CE))["version"]


def map_account(account_id, gl_id, project_id):
    """Map an account using a freshly read project version (OCC)."""
    pv = current_project_version(project_id)
    return get_success_data(
        api_client.map_account(
            account_id,
            {"gl_account_id": gl_id, "expected_project_version": pv},
            CE,
        )
    )


def advance_project(project_id):
    return get_success_data(api_client.advance_project(project_id, PM))


def advance_to_mock_conversion(project_id):
    """DISCOVERY -> CONFIGURATION -> MOCK_CONVERSION."""
    advance_project(project_id)
    return advance_project(project_id)


def start_mock_run(project_id, run_label="MOCK-1"):
    return get_success_data(
        api_client.create_mock_run(
            create_mock_run_payload(project_id, run_label=run_label), CE
        ),
        201,
    )


def finalize_run(run_id, clock=None):
    if clock is not None:
        set_clock(clock)
    return get_success_data(api_client.finalize_mock_run(run_id, CE))


def flag_and_clear(account_id, note="x", resolution_note="y"):
    """MAPPED -> EXCEPTION -> CLEARED round trip."""
    get_success_data(api_client.flag_exception(account_id, {"note": note}, CE))
    return get_success_data(
        api_client.clear_exception(account_id, {"resolution_note": resolution_note}, CE)
    )


def create_ancillary_system(project_id, **overrides):
    return get_success_data(
        api_client.create_ancillary_system(
            create_ancillary_system_payload(project_id, **overrides), OPS
        ),
        201,
    )


def verify_ancillary_system(system_id):
    """PENDING -> INTEGRATING -> VERIFIED."""
    get_success_data(api_client.start_integration(system_id, OPS))
    return get_success_data(api_client.verify_integration(system_id, OPS))


def create_session(project_id, **overrides):
    return get_success_data(
        api_client.create_training_session(
            create_training_session_payload(project_id, **overrides), TRAINER
        ),
        201,
    )


def create_staff(project_id, **overrides):
    return get_success_data(
        api_client.create_staff(create_staff_payload(project_id, **overrides), TRAINER),
        201,
    )


def enroll(session_id, employee_id):
    return get_success_data(
        api_client.create_enrollment(
            create_enrollment_payload(session_id, employee_id), TRAINER
        ),
        201,
    )


def create_comm(project_id, account_id, **overrides):
    return get_success_data(
        api_client.create_comm(create_comm_payload(project_id, account_id, **overrides), CO),
        201,
    )


def schedule_comm(comm_id, project_id):
    """Schedule a comm using a freshly read project version (OCC)."""
    pv = get_success_data(api_client.get_project(project_id, CO))["version"]
    return get_success_data(
        api_client.schedule_comm(comm_id, {"expected_project_version": pv}, CO)
    )


def create_defect(project_id, headers=None, **overrides):
    return get_success_data(
        api_client.create_defect(
            create_defect_payload(project_id, **overrides), headers or OPS
        ),
        201,
    )


def create_claim(project_id, month, defect_ids, headers=None):
    return get_success_data(
        api_client.create_service_credit(
            create_service_credit_payload(project_id, month, defect_ids),
            headers or FC,
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Tier 2: project assembly
# ---------------------------------------------------------------------------

def setup_project_with_active_product(product_overrides=None, **project_overrides):
    """Project in DISCOVERY + one ACTIVE DEPOSIT product + one GL account."""
    project = create_project(**project_overrides)
    pt = create_product(project["id"], **(product_overrides or {}))
    gl = create_gl(project["id"])
    return {"project": project, "product": pt, "gl": gl}


def setup_project_with_mapped_account(product_overrides=None, account_overrides=None,
                                      **project_overrides):
    """Project in DISCOVERY with one ACTIVE product, one GL, one MAPPED account."""
    ctx = setup_project_with_active_product(product_overrides, **project_overrides)
    acct = create_account(
        ctx["project"]["id"], ctx["product"]["id"], **(account_overrides or {})
    )
    acct = map_account(acct["id"], ctx["gl"]["id"], ctx["project"]["id"])
    ctx["account"] = acct
    return ctx


def setup_mock_conversion_project(product_overrides=None, account_overrides=None,
                                  clear_account=False, **project_overrides):
    """Project advanced to MOCK_CONVERSION with one MAPPED (or CLEARED) account."""
    ctx = setup_project_with_mapped_account(
        product_overrides, account_overrides, **project_overrides
    )
    advance_to_mock_conversion(ctx["project"]["id"])
    if clear_account:
        ctx["account"] = flag_and_clear(ctx["account"]["id"])
    return ctx


def setup_project_with_passed_run(clear_account=False, finalize_clock=None,
                                  product_overrides=None, account_overrides=None,
                                  **project_overrides):
    """MOCK_CONVERSION project whose first run finalizes PASSED.

    One MAPPED account, no EXCEPTION accounts -> balanced 1, exceptions 0.
    If clear_account is True the account is cycled MAPPED -> EXCEPTION ->
    CLEARED after the finalize (a PASSED run flips CLEARED back to MAPPED, so
    the cycle is applied after finalize when the caller needs CLEARED).
    """
    ctx = setup_mock_conversion_project(
        product_overrides, account_overrides, **project_overrides
    )
    run = start_mock_run(ctx["project"]["id"])
    ctx["run"] = finalize_run(run["id"], clock=finalize_clock)
    if clear_account:
        ctx["account"] = flag_and_clear(ctx["account"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: cutover planning and execution
# ---------------------------------------------------------------------------

def plan_cutover(project_id, **overrides):
    payload = plan_cutover_payload(**overrides)
    return get_success_data(api_client.plan_cutover(project_id, payload, PM))


def add_task(plan_id, **overrides):
    return get_success_data(
        api_client.create_task(create_task_payload(plan_id, **overrides), PM), 201
    )


def setup_cutover_planned_project(clear_account=False, finalize_clock=None,
                                  verify_system=True,
                                  product_overrides=None, account_overrides=None,
                                  **plan_overrides):
    """Project in CUTOVER_PLANNED with a DRAFT plan and one PASSED baseline run.

    Also registers one ancillary system (VERIFIED when verify_system) so the
    go-live gate can be satisfied downstream.
    """
    ctx = setup_project_with_passed_run(
        clear_account=clear_account, finalize_clock=finalize_clock,
        product_overrides=product_overrides, account_overrides=account_overrides,
    )
    sys_row = create_ancillary_system(ctx["project"]["id"])
    if verify_system:
        sys_row = verify_ancillary_system(sys_row["id"])
    ctx["system"] = sys_row
    plan = plan_cutover(ctx["project"]["id"], **plan_overrides)
    ctx["plan"] = plan
    return ctx


def setup_plan_scheduled(clear_account=False, finalize_clock=None,
                         tasks=None, **plan_overrides):
    """CUTOVER_PLANNED project with a SCHEDULED plan (one task by default)."""
    ctx = setup_cutover_planned_project(
        clear_account=clear_account, finalize_clock=finalize_clock, **plan_overrides
    )
    if tasks is None:
        tasks = [{}]
    ctx["tasks"] = [add_task(ctx["plan"]["id"], **t) for t in tasks]
    ctx["plan"] = get_success_data(api_client.schedule_plan(ctx["plan"]["id"], PM))
    return ctx


def setup_plan_go(clear_account=False, finalize_clock=None,
                  checkpoint_clock=CLOCK_AFTER_CHECKPOINT, tasks=None,
                  **plan_overrides):
    """CUTOVER_PLANNED project with the plan declared GO."""
    ctx = setup_plan_scheduled(
        clear_account=clear_account, finalize_clock=finalize_clock,
        tasks=tasks, **plan_overrides,
    )
    if checkpoint_clock is not None:
        set_clock(checkpoint_clock)
    ctx["plan"] = get_success_data(api_client.declare_go(ctx["plan"]["id"], PM))
    return ctx


def execute_task(task_id, owner_role="CONVERSION_ENGINEER", start_clock=None,
                 complete_clock=None):
    """PENDING -> RUNNING -> COMPLETE for one task."""
    headers = CE if owner_role == "CONVERSION_ENGINEER" else OPS
    if start_clock is not None:
        set_clock(start_clock)
    get_success_data(api_client.start_task(task_id, headers))
    if complete_clock is not None:
        set_clock(complete_clock)
    return get_success_data(api_client.complete_task(task_id, headers))


def setup_go_project_with_completed_task(clear_account=False, finalize_clock=None,
                                         **plan_overrides):
    """Plan GO with its single task COMPLETE — go-live gate fully satisfiable."""
    ctx = setup_plan_go(
        clear_account=clear_account, finalize_clock=finalize_clock, **plan_overrides
    )
    task = ctx["tasks"][0]
    ctx["tasks"][0] = execute_task(task["id"], owner_role=task["owner_role"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: full lifecycle — LIVE project
# ---------------------------------------------------------------------------

def setup_live_project(clear_account=False, finalize_clock=None,
                       go_live_clock=GO_LIVE_CLOCK, **plan_overrides):
    """Full happy path through project go-live (LIVE).

    With clear_account=False the single account is MAPPED pre-live and becomes
    EXCEPTION ('uncleared at go-live'); with clear_account=True it is CLEARED
    pre-live and becomes CONVERTED.
    """
    ctx = setup_go_project_with_completed_task(
        clear_account=clear_account, finalize_clock=finalize_clock, **plan_overrides
    )
    if go_live_clock is not None:
        set_clock(go_live_clock)
    ctx["project"] = get_success_data(api_client.go_live(ctx["project"]["id"], PM))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: post-live defect / service-credit assembly
# ---------------------------------------------------------------------------

def setup_live_project_with_defect(severity="SEV1", defect_clock="2026-09-21T00:00:00Z",
                                   reporter_headers=None, **defect_overrides):
    """LIVE project + one defect reported at defect_clock."""
    ctx = setup_live_project()
    set_clock(defect_clock)
    ctx["defect"] = create_defect(
        ctx["project"]["id"], headers=reporter_headers or OPS,
        severity=severity, **defect_overrides,
    )
    return ctx


def resolve_defect_at(defect_id, clock):
    set_clock(clock)
    return get_success_data(api_client.resolve_defect(defect_id, VTL))


def setup_live_project_with_eligible_defect(
    severity="SEV1",
    defect_clock="2026-09-21T00:00:00Z",
    resolve_clock="2026-09-24T00:00:00Z",
    **defect_overrides,
):
    """LIVE project + one defect resolved past its SLA (credit_eligible True).

    Defaults: SEV1 opened 2026-09-21T00:00Z (sla 2026-09-22T00:00Z), resolved
    2026-09-24T00:00Z -> breach 48h.
    """
    ctx = setup_live_project_with_defect(
        severity=severity, defect_clock=defect_clock, **defect_overrides
    )
    ctx["defect"] = resolve_defect_at(ctx["defect"]["id"], resolve_clock)
    return ctx


def setup_live_project_with_open_claim(month="2026-09", claim_headers=None, **kwargs):
    """LIVE project + eligible defect + OPEN service credit claim over it."""
    ctx = setup_live_project_with_eligible_defect(**kwargs)
    ctx["claim"] = create_claim(
        ctx["project"]["id"], month, [ctx["defect"]["id"]],
        headers=claim_headers or FC,
    )
    return ctx
