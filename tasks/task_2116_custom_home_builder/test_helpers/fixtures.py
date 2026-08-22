"""Composite setup helpers for the custom home build workflow.

Every helper builds its preconditions from scratch through the API's own
endpoints, because each test starts against an empty database and a logical
clock that reads exactly 2026-08-01T00:00:00.000Z.  Setup calls go through the
lenient success validator so a broken precondition surfaces as "Setup step
failed" rather than as a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import CLOCK_START, TEST_DEFAULTS
from .factories import (
    create_allowance_item_payload,
    create_change_order_payload,
    create_client_payload,
    create_cost_entry_payload,
    create_defect_ticket_payload,
    create_draw_request_payload,
    create_lender_payload,
    create_photo_document_payload,
    create_project_payload,
    create_schedule_task_payload,
    create_selection_payload,
    create_staff_member_payload,
    create_subcontractor_payload,
    receive_lien_waiver_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_headers,
    make_controller_headers,
    make_estimator_headers,
    make_lender_headers,
    make_project_manager_headers,
    make_subcontractor_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LIST_ALL = {"limit": 100, "offset": 0}


# ==========================================================================
# Tier 0 — single-call helpers
# ==========================================================================
def set_clock(to_iso8601: str = CLOCK_START) -> dict:
    """Reposition the server's logical UTC clock."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_client(**overrides) -> dict:
    return get_success_data(api.create_client(create_client_payload(**overrides), ADMIN))


def create_lender(**overrides) -> dict:
    return get_success_data(api.create_lender(create_lender_payload(**overrides), ADMIN))


def create_staff_member(full_name: str, staff_function: str) -> dict:
    return get_success_data(
        api.create_staff_member(
            create_staff_member_payload(full_name=full_name, staff_function=staff_function),
            ADMIN,
        )
    )


def create_subcontractor(**overrides) -> dict:
    return get_success_data(
        api.create_subcontractor(create_subcontractor_payload(**overrides), ADMIN)
    )


def create_project(client_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_project(create_project_payload(client_id, **overrides), ADMIN)
    )


def create_allowance_item(project_id: str, pm_headers: dict, **overrides) -> dict:
    return get_success_data(
        api.create_allowance_item(
            create_allowance_item_payload(project_id, **overrides), pm_headers
        )
    )


def create_schedule_task(
    project_id: str, subcontractor_id: str, pm_headers: dict, **overrides
) -> dict:
    return get_success_data(
        api.create_schedule_task(
            create_schedule_task_payload(project_id, subcontractor_id, **overrides),
            pm_headers,
        )
    )


def advance_project(project_id: str, action: str, pm_headers: dict) -> dict:
    return get_success_data(
        api.advance_project(project_id, {"action": action}, pm_headers)
    )


# ─── Reads ────────────────────────────────────────────────────────────────
def read_project(project_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api.get_project(project_id, headers))


def read_contract_position(project_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api.get_contract_position(project_id, headers))


def read_allowance_item(allowance_item_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api.get_allowance_item(allowance_item_id, headers))


def read_selection(selection_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api.get_selection(selection_id, headers))


def read_change_order(change_order_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api.get_change_order(change_order_id, headers))


def read_schedule_task(task_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api.get_schedule_task(task_id, headers))


def read_cost_entry(cost_entry_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api.get_cost_entry(cost_entry_id, headers))


def read_draw_request(draw_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api.get_draw_request(draw_id, headers))


def read_lien_waiver(waiver_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api.get_lien_waiver(waiver_id, headers))


def read_defect_ticket(ticket_id: str, headers: dict = ADMIN) -> dict:
    return get_success_data(api.get_defect_ticket(ticket_id, headers))


def list_photo_documents(project_id: str, headers: dict = ADMIN, **params) -> list:
    query = dict(LIST_ALL)
    query.update(params)
    return get_success_data(api.list_photo_documents(project_id, headers, params=query))


def read_photo_document(project_id: str, photo_id: str, headers: dict = ADMIN) -> dict:
    """Photo documents are read back through their project's sub-resource list."""
    rows = list_photo_documents(project_id, headers)
    match = [row for row in rows if row["id"] == photo_id]
    assert match, f"Setup step failed: photo document {photo_id} not present in the list"
    return match[0]


def project_version(project_id: str) -> int:
    return read_project(project_id)["version"]


def allowance_item_version(allowance_item_id: str) -> int:
    return read_allowance_item(allowance_item_id)["version"]


# ==========================================================================
# Tier 1 — parties and a job standing in PLANNING / UNDER_CONSTRUCTION
# ==========================================================================
def seed_parties(
    *,
    with_lender: bool = True,
    with_plumbing: bool = False,
    frame_crew_capacity: int = 1,
    frame_waiver_required: bool = True,
    plumbing_waiver_required: bool = True,
    retainage_pct: float = TEST_DEFAULTS["RETAINAGE_PCT"],
    max_cumulative_draw_pct: float = TEST_DEFAULTS["MAX_CUMULATIVE_DRAW_PCT"],
    review_window_days: int = TEST_DEFAULTS["REVIEW_WINDOW_DAYS"],
) -> dict:
    """Register the homeowner, the builder's staff and the trades.

    Two controllers are always registered because the draw segregation-of-duties
    rule needs an approver and a different submitter.
    """
    client = create_client()
    ctx = {
        "admin_headers": ADMIN,
        "client": client,
        "client_headers": make_client_headers(client["id"]),
    }

    if with_lender:
        lender = create_lender(
            retainage_pct=retainage_pct,
            max_cumulative_draw_pct=max_cumulative_draw_pct,
            review_window_days=review_window_days,
        )
        ctx["lender"] = lender
        ctx["lender_headers"] = make_lender_headers(lender["id"])
    else:
        ctx["lender"] = None
        ctx["lender_headers"] = None

    pm = create_staff_member("Pat Morgan", "PROJECT_MANAGER")
    estimator = create_staff_member("Elle Sato", "ESTIMATOR")
    controller_a = create_staff_member("Casey Nolan", "CONTROLLER")
    controller_b = create_staff_member("Robin Vega", "CONTROLLER")
    ctx.update(
        {
            "pm": pm,
            "pm_headers": make_project_manager_headers(pm["id"]),
            "estimator": estimator,
            "estimator_headers": make_estimator_headers(estimator["id"]),
            "controller_a": controller_a,
            "controller_a_headers": make_controller_headers(controller_a["id"]),
            "controller_b": controller_b,
            "controller_b_headers": make_controller_headers(controller_b["id"]),
        }
    )

    sub_frame = create_subcontractor(
        company_name="Ridgeline Framing",
        trade="FRAMING",
        lead_time_days=5,
        crew_capacity=frame_crew_capacity,
        waiver_required=frame_waiver_required,
    )
    ctx["sub_frame"] = sub_frame
    ctx["sub_frame_headers"] = make_subcontractor_headers(sub_frame["id"])

    if with_plumbing:
        sub_plumb = create_subcontractor(
            company_name="Blue Valve Plumbing",
            trade="PLUMBING",
            lead_time_days=10,
            crew_capacity=2,
            waiver_required=plumbing_waiver_required,
        )
        ctx["sub_plumb"] = sub_plumb
        ctx["sub_plumb_headers"] = make_subcontractor_headers(sub_plumb["id"])

    return ctx


def setup_job(
    *,
    with_lender: bool = True,
    with_plumbing: bool = False,
    contract_type: str = "FIXED_PRICE",
    base_contract_amount: float = TEST_DEFAULTS["BASE_CONTRACT_AMOUNT"],
    builder_fee_pct=None,
    gmp_cap=None,
    address: str = "18 Kestrel Ridge",
    allowance_category: str = "FLOORING",
    allowance_amount: float = TEST_DEFAULTS["ALLOWANCE_AMOUNT"],
    selection_deadline: str = TEST_DEFAULTS["SELECTION_DEADLINE"],
    create_allowance: bool = True,
    create_task: bool = True,
    task_overrides=None,
    start_construction: bool = True,
    frame_crew_capacity: int = 1,
    frame_waiver_required: bool = True,
    plumbing_waiver_required: bool = True,
    retainage_pct: float = TEST_DEFAULTS["RETAINAGE_PCT"],
    max_cumulative_draw_pct: float = TEST_DEFAULTS["MAX_CUMULATIVE_DRAW_PCT"],
    review_window_days: int = TEST_DEFAULTS["REVIEW_WINDOW_DAYS"],
) -> dict:
    """Stand a job up: parties, project, one allowance line, one framing task.

    With `start_construction` true the project is walked to
    UNDER_CONSTRUCTION, which is the state most of this API's operations
    require.  Returns a context dict carrying every entity and every role's
    headers, threaded from the real row ids.
    """
    ctx = seed_parties(
        with_lender=with_lender,
        with_plumbing=with_plumbing,
        frame_crew_capacity=frame_crew_capacity,
        frame_waiver_required=frame_waiver_required,
        plumbing_waiver_required=plumbing_waiver_required,
        retainage_pct=retainage_pct,
        max_cumulative_draw_pct=max_cumulative_draw_pct,
        review_window_days=review_window_days,
    )

    project_overrides = {
        "address": address,
        "contract_type": contract_type,
        "base_contract_amount": base_contract_amount,
    }
    if with_lender:
        project_overrides["lender_id"] = ctx["lender"]["id"]
    if builder_fee_pct is not None:
        project_overrides["builder_fee_pct"] = builder_fee_pct
    if gmp_cap is not None:
        project_overrides["gmp_cap"] = gmp_cap

    project = create_project(ctx["client"]["id"], **project_overrides)
    ctx["project"] = project

    if create_allowance:
        ctx["allowance_item"] = create_allowance_item(
            project["id"],
            ctx["pm_headers"],
            category=allowance_category,
            allowance_amount=allowance_amount,
            selection_deadline=selection_deadline,
        )
    else:
        ctx["allowance_item"] = None

    if create_task:
        ctx["task_frame"] = create_schedule_task(
            project["id"],
            ctx["sub_frame"]["id"],
            ctx["pm_headers"],
            **(task_overrides or {}),
        )
    else:
        ctx["task_frame"] = None

    if start_construction:
        ctx["project"] = advance_project(project["id"], "START_CONSTRUCTION", ctx["pm_headers"])

    return ctx


# ==========================================================================
# Tier 2 — the allowance book: propose, accept, lock, reconcile
# ==========================================================================
def propose_selection(ctx: dict, allowance_item_id=None, **overrides) -> dict:
    """Homeowner proposes a selection, carrying the line's current version."""
    item_id = allowance_item_id or ctx["allowance_item"]["id"]
    version = overrides.pop(
        "expected_allowance_item_version", allowance_item_version(item_id)
    )
    return get_success_data(
        api.create_selection(
            create_selection_payload(item_id, version, **overrides), ctx["client_headers"]
        )
    )


def decide_selection(ctx: dict, selection_id: str, decision: str = "APPROVE") -> dict:
    return get_success_data(
        api.decide_selection(selection_id, {"decision": decision}, ctx["pm_headers"])
    )


def settle_allowance_item(ctx: dict, allowance_item_id: str, action: str) -> dict:
    return get_success_data(
        api.settle_allowance_item(
            allowance_item_id, {"action": action}, ctx["controller_a_headers"]
        )
    )


def setup_selected_allowance(ctx: dict, allowance_item_id=None, **selection_overrides) -> dict:
    """Propose a selection and have the project manager accept it."""
    item_id = allowance_item_id or ctx["allowance_item"]["id"]
    selection = propose_selection(ctx, item_id, **selection_overrides)
    decide_selection(ctx, selection["id"], "APPROVE")
    ctx["selection"] = selection
    return selection


def setup_locked_allowance(ctx: dict, allowance_item_id=None, **selection_overrides) -> dict:
    """Walk an allowance line OPEN -> SELECTED -> LOCKED."""
    item_id = allowance_item_id or ctx["allowance_item"]["id"]
    setup_selected_allowance(ctx, item_id, **selection_overrides)
    locked = settle_allowance_item(ctx, item_id, "LOCK")
    if ctx.get("allowance_item") and item_id == ctx["allowance_item"]["id"]:
        ctx["allowance_item"] = locked
    return locked


def setup_job_with_material_driven_task(
    *,
    allowance_amount: float = 25000.00,
    cabinet_start: str = "2026-09-01T00:00:00.000Z",
    cabinet_finish: str = "2026-10-15T00:00:00.000Z",
    **job_kwargs,
) -> dict:
    """A job whose cabinet activity waits on a CABINETRY allowance line.

    The cabinet task names the allowance line through `driving_allowance_item_id`,
    so its release is gated on the line's buy-out and on the material readiness
    date the lock computes.
    """
    ctx = setup_job(
        start_construction=False,
        allowance_category="CABINETRY",
        allowance_amount=allowance_amount,
        **job_kwargs,
    )
    sub_cabinet = create_subcontractor(
        company_name="Northwood Cabinets",
        trade="FINISH_CARPENTRY",
        lead_time_days=12,
        crew_capacity=2,
        waiver_required=True,
    )
    ctx["sub_cabinet"] = sub_cabinet
    ctx["sub_cabinet_headers"] = make_subcontractor_headers(sub_cabinet["id"])
    ctx["task_cabinet"] = create_schedule_task(
        ctx["project"]["id"],
        sub_cabinet["id"],
        ctx["pm_headers"],
        task_name="Cabinet install",
        planned_start=cabinet_start,
        planned_finish=cabinet_finish,
        driving_allowance_item_id=ctx["allowance_item"]["id"],
    )
    ctx["project"] = advance_project(
        ctx["project"]["id"], "START_CONSTRUCTION", ctx["pm_headers"]
    )
    return ctx


def setup_two_project_schedule() -> dict:
    """Two jobs in PLANNING whose schedules overlap in time but not in ownership.

    Project 2 carries a plumbing activity over 2026-09-05..2026-09-20; project 1
    carries a framing activity over 2026-09-01..2026-10-15 worked by a crew whose
    capacity is 1.  A new project-1 task that both names the project-2 activity as
    its predecessor and collides with the framing crew therefore breaches two
    rules at once.
    """
    ctx = seed_parties(with_lender=False, with_plumbing=True)
    project_1 = create_project(
        ctx["client"]["id"], address="18 Kestrel Ridge", base_contract_amount=900000.00
    )
    project_2 = create_project(
        ctx["client"]["id"], address="24 Kestrel Ridge", base_contract_amount=700000.00
    )
    ctx["project_1"] = project_1
    ctx["project_2"] = project_2
    ctx["task_a"] = create_schedule_task(
        project_2["id"],
        ctx["sub_plumb"]["id"],
        ctx["pm_headers"],
        task_name="P2 rough plumbing",
        planned_start="2026-09-05T00:00:00.000Z",
        planned_finish="2026-09-20T00:00:00.000Z",
    )
    ctx["task_b"] = create_schedule_task(
        project_1["id"],
        ctx["sub_frame"]["id"],
        ctx["pm_headers"],
        task_name="P1 frame shell",
        planned_start="2026-09-01T00:00:00.000Z",
        planned_finish="2026-10-15T00:00:00.000Z",
    )
    return ctx


def setup_exclusive_use_slab() -> dict:
    """A job whose concrete crew has already taken the whole jobsite for a slab pour.

    The pouring crew's capacity is 3, so the crew-capacity rule can never fire
    here and only the jobsite exclusive-use rule is in play.
    """
    ctx = setup_job(
        with_lender=False, create_task=False, create_allowance=False, start_construction=False
    )
    sub_concrete = create_subcontractor(
        company_name="Granite Flatwork",
        trade="CONCRETE",
        lead_time_days=2,
        crew_capacity=3,
        waiver_required=False,
    )
    ctx["sub_concrete"] = sub_concrete
    ctx["sub_concrete_headers"] = make_subcontractor_headers(sub_concrete["id"])
    ctx["task_slab"] = create_schedule_task(
        ctx["project"]["id"],
        sub_concrete["id"],
        ctx["pm_headers"],
        task_name="Slab pour",
        planned_start="2026-09-01T00:00:00.000Z",
        planned_finish="2026-09-10T00:00:00.000Z",
        exclusive_use=True,
    )
    return ctx


def setup_identical_ledger_pair(
    *,
    base_contract_amount: float = TEST_DEFAULTS["BASE_CONTRACT_AMOUNT"],
    gmp_cap: float = 1000000.00,
    builder_fee_pct: float = TEST_DEFAULTS["BUILDER_FEE_PCT"],
    cost_amount: float = 45000.30,
) -> dict:
    """Two jobs carrying byte-identical ledger inputs on different bases.

    One project is written fixed price and the other cost plus; both carry the
    same base contract amount, the same guaranteed maximum price, no change
    orders, no allowance variance and one approved cost entry of the same value.
    """
    ctx = seed_parties(with_lender=True)
    pair = {}
    for key, contract_type, address, task_window in (
        (
            "fixed_price",
            "FIXED_PRICE",
            "18 Kestrel Ridge",
            ("2026-09-01T00:00:00.000Z", "2026-10-15T00:00:00.000Z"),
        ),
        (
            "cost_plus",
            "COST_PLUS",
            "22 Kestrel Ridge",
            ("2026-10-15T00:00:00.000Z", "2026-11-30T00:00:00.000Z"),
        ),
    ):
        project_overrides = {
            "address": address,
            "contract_type": contract_type,
            "base_contract_amount": base_contract_amount,
            "gmp_cap": gmp_cap,
            "lender_id": ctx["lender"]["id"],
        }
        if contract_type == "COST_PLUS":
            project_overrides["builder_fee_pct"] = builder_fee_pct
        project = create_project(ctx["client"]["id"], **project_overrides)
        create_allowance_item(project["id"], ctx["pm_headers"])
        create_schedule_task(
            project["id"],
            ctx["sub_frame"]["id"],
            ctx["pm_headers"],
            task_name=f"Frame shell {key}",
            planned_start=task_window[0],
            planned_finish=task_window[1],
        )
        project = advance_project(project["id"], "START_CONSTRUCTION", ctx["pm_headers"])

        entry = get_success_data(
            api.create_cost_entry(
                create_cost_entry_payload(
                    project["id"],
                    amount=cost_amount,
                    incurred_at="2026-08-10T00:00:00.000Z",
                    subcontractor_id=ctx["sub_frame"]["id"],
                ),
                ctx["pm_headers"],
            )
        )
        get_success_data(
            api.review_cost_entry(
                entry["id"], {"decision": "APPROVE"}, ctx["controller_a_headers"]
            )
        )
        pair[f"{key}_project"] = project
        pair[f"{key}_cost_entry"] = entry

    ctx.update(pair)
    return ctx


# ==========================================================================
# Tier 3 — change orders: draft, price, submit, decide
# ==========================================================================
def create_change_order(ctx: dict, **overrides) -> dict:
    return get_success_data(
        api.create_change_order(
            create_change_order_payload(ctx["project"]["id"], **overrides),
            ctx["pm_headers"],
        )
    )


def price_change_order(ctx: dict, change_order_id: str, priced_by: str = "estimator", **payload) -> dict:
    headers = ctx["estimator_headers"] if priced_by == "estimator" else ctx["pm_headers"]
    return get_success_data(api.price_change_order(change_order_id, payload, headers))


def submit_change_order(ctx: dict, change_order_id: str) -> dict:
    return get_success_data(api.submit_change_order(change_order_id, ctx["pm_headers"]))


def decide_change_order(ctx: dict, change_order_id: str, decision: str, **payload) -> dict:
    body = {"decision": decision}
    body.update(payload)
    return get_success_data(
        api.decide_change_order(change_order_id, body, ctx["client_headers"])
    )


def setup_priced_change_order(ctx: dict, priced_by: str = "estimator", **overrides) -> dict:
    change_order = create_change_order(ctx, **overrides)
    return price_change_order(ctx, change_order["id"], priced_by=priced_by)


def setup_submitted_change_order(ctx: dict, **overrides) -> dict:
    priced = setup_priced_change_order(ctx, **overrides)
    return submit_change_order(ctx, priced["id"])


def setup_approved_change_order(ctx: dict, **overrides) -> dict:
    submitted = setup_submitted_change_order(ctx, **overrides)
    return decide_change_order(ctx, submitted["id"], "APPROVE")


def run_revision_round(ctx: dict, change_order_id: str, note: str, direct_cost: float) -> dict:
    """Client sends the change order back, the estimator reprices, the PM resubmits."""
    decide_change_order(ctx, change_order_id, "REQUEST_REVISION", revision_note=note)
    price_change_order(ctx, change_order_id, direct_cost=direct_cost)
    return submit_change_order(ctx, change_order_id)


# ==========================================================================
# Tier 4 — the schedule: release, start, complete
# ==========================================================================
def release_task(ctx: dict, task_id: str) -> dict:
    return get_success_data(api.release_schedule_task(task_id, ctx["pm_headers"]))


def progress_task(ctx: dict, task_id: str, action: str, sub_headers: dict) -> dict:
    return get_success_data(
        api.progress_schedule_task(task_id, {"action": action}, sub_headers)
    )


def run_task_to_completion(
    ctx: dict, task_id: str, sub_headers: dict, finish_clock: str
) -> dict:
    """Release, start, move the clock to `finish_clock`, then complete."""
    release_task(ctx, task_id)
    progress_task(ctx, task_id, "START", sub_headers)
    set_clock(finish_clock)
    return progress_task(ctx, task_id, "COMPLETE", sub_headers)


def setup_substantial_completion(
    ctx=None, *, finish_clock: str = "2026-10-20T00:00:00.000Z", **job_kwargs
) -> dict:
    """Walk a single-task job all the way to SUBSTANTIAL_COMPLETION."""
    ctx = ctx or setup_job(**job_kwargs)
    run_task_to_completion(
        ctx, ctx["task_frame"]["id"], ctx["sub_frame_headers"], finish_clock
    )
    ctx["project"] = advance_project(
        ctx["project"]["id"], "DECLARE_SUBSTANTIAL_COMPLETION", ctx["pm_headers"]
    )
    return ctx


def setup_accepted_home(
    ctx=None, *, acknowledged_open_cosmetic_count: int = 0, **kwargs
) -> dict:
    """Walk a job to FINAL_ACCEPTED through the homeowner's walkthrough."""
    ctx = ctx or setup_substantial_completion(**kwargs)
    ctx["project"] = get_success_data(
        api.final_walkthrough(
            ctx["project"]["id"],
            {"acknowledged_open_cosmetic_count": acknowledged_open_cosmetic_count},
            ctx["client_headers"],
        )
    )
    return ctx


def setup_build_with_completed_plumbing_task() -> dict:
    """A finished house whose plumbing trade finished long before acceptance.

    Framing runs 2026-09-01..2026-10-15 and actually finishes 2026-10-20;
    rough plumbing runs 2026-10-16..2026-11-30 and actually finishes
    2027-01-15; substantial completion is declared 2027-03-01 and the
    homeowner accepts the home the same instant.
    """
    ctx = setup_job(with_plumbing=True)
    ctx["task_plumb"] = create_schedule_task(
        ctx["project"]["id"],
        ctx["sub_plumb"]["id"],
        ctx["pm_headers"],
        task_name="Rough plumbing",
        planned_start="2026-10-16T00:00:00.000Z",
        planned_finish="2026-11-30T00:00:00.000Z",
    )
    run_task_to_completion(
        ctx,
        ctx["task_frame"]["id"],
        ctx["sub_frame_headers"],
        "2026-10-20T00:00:00.000Z",
    )
    run_task_to_completion(
        ctx,
        ctx["task_plumb"]["id"],
        ctx["sub_plumb_headers"],
        "2027-01-15T00:00:00.000Z",
    )
    set_clock("2027-03-01T00:00:00.000Z")
    ctx["project"] = advance_project(
        ctx["project"]["id"], "DECLARE_SUBSTANTIAL_COMPLETION", ctx["pm_headers"]
    )
    ctx["project"] = get_success_data(
        api.final_walkthrough(
            ctx["project"]["id"],
            {"acknowledged_open_cosmetic_count": 0},
            ctx["client_headers"],
        )
    )
    return ctx


# ==========================================================================
# Tier 5 — cost capture, draws and lien waivers
# ==========================================================================
def post_cost_entry(ctx: dict, *, owner_direct: bool = False, **overrides) -> dict:
    """Post a cost against the job; it lands in PENDING.

    Unless `owner_direct` is set the line is charged to the framing trade, which
    is what gives the draw machinery a lien-waiver counterparty.
    """
    if not owner_direct:
        overrides.setdefault("subcontractor_id", ctx["sub_frame"]["id"])
    return get_success_data(
        api.create_cost_entry(
            create_cost_entry_payload(ctx["project"]["id"], **overrides), ctx["pm_headers"]
        )
    )


def review_cost_entry(ctx: dict, cost_entry_id: str, decision: str, approver: str = "a") -> dict:
    headers = ctx[f"controller_{approver}_headers"]
    return get_success_data(
        api.review_cost_entry(cost_entry_id, {"decision": decision}, headers)
    )


def post_and_approve_cost_entry(ctx: dict, *, approver: str = "a", **overrides) -> dict:
    entry = post_cost_entry(ctx, **overrides)
    return review_cost_entry(ctx, entry["id"], "APPROVE", approver=approver)


def post_and_approve_cost_entries(ctx: dict, lines, *, approver: str = "a") -> list:
    """Post and approve a list of {amount, incurred_at, ...} cost lines."""
    entries = []
    for line in lines:
        entries.append(post_and_approve_cost_entry(ctx, approver=approver, **line))
    ctx["cost_entries"] = entries
    return entries


def open_draw(ctx: dict, *, controller: str = "b", expected_project_version=None, **overrides) -> dict:
    headers = ctx[f"controller_{controller}_headers"]
    version = (
        expected_project_version
        if expected_project_version is not None
        else project_version(ctx["project"]["id"])
    )
    return get_success_data(
        api.create_draw_request(
            create_draw_request_payload(ctx["project"]["id"], version, **overrides), headers
        )
    )


def submit_draw(ctx: dict, draw_id: str, *, controller: str = "b") -> dict:
    return get_success_data(
        api.submit_draw_request(draw_id, ctx[f"controller_{controller}_headers"])
    )


def lender_decide_draw(ctx: dict, draw_id: str, decision: str, condition_note=None) -> dict:
    payload = {"decision": decision}
    if condition_note is not None:
        payload["condition_note"] = condition_note
    return get_success_data(api.lender_decision(draw_id, payload, ctx["lender_headers"]))


def void_draw(ctx: dict, draw_id: str, void_reason: str, *, controller: str = "b") -> dict:
    return get_success_data(
        api.void_draw_request(
            draw_id, {"void_reason": void_reason}, ctx[f"controller_{controller}_headers"]
        )
    )


def list_lien_waivers(draw_id: str, subcontractor_id=None) -> list:
    params = dict(LIST_ALL)
    params["draw_request_id"] = draw_id
    if subcontractor_id:
        params["subcontractor_id"] = subcontractor_id
    return get_success_data(api.list_lien_waivers(ADMIN, params=params))


def only_lien_waiver(draw_id: str, subcontractor_id=None) -> dict:
    rows = list_lien_waivers(draw_id, subcontractor_id)
    assert rows, f"Setup step failed: draw {draw_id} generated no lien waiver rows"
    return rows[0]


def receive_waiver(ctx: dict, waiver_id: str, sub_headers: dict, **overrides) -> dict:
    return get_success_data(
        api.receive_lien_waiver(waiver_id, receive_lien_waiver_payload(**overrides), sub_headers)
    )


def review_waiver(ctx: dict, waiver_id: str, decision: str, *, controller: str = "a") -> dict:
    return get_success_data(
        api.review_lien_waiver(
            waiver_id, {"decision": decision}, ctx[f"controller_{controller}_headers"]
        )
    )


def setup_submitted_draw(
    ctx=None,
    *,
    lines=None,
    period_start: str = TEST_DEFAULTS["PERIOD_START"],
    period_end: str = TEST_DEFAULTS["PERIOD_END"],
    approver: str = "a",
    submitter: str = "b",
    **job_kwargs,
) -> dict:
    """Approve a set of cost lines, open a draw and submit it to the lender.

    Returns the context, with `cost_entries` and `draw` filled in.
    """
    ctx = ctx or setup_job(**job_kwargs)
    lines = lines if lines is not None else [{"amount": 10000.10, "incurred_at": "2026-08-10T00:00:00.000Z"}]
    post_and_approve_cost_entries(ctx, lines, approver=approver)
    draw = open_draw(ctx, controller=submitter, period_start=period_start, period_end=period_end)
    ctx["draw"] = submit_draw(ctx, draw["id"], controller=submitter)
    return ctx


def setup_returned_draw_now_over_the_cap(
    *,
    base_contract_amount: float = 50000.00,
    first_lines=None,
    extra_line=None,
) -> dict:
    """A returned draw whose period has since collected more cost than the lender allows.

    The draw is submitted inside the lender's ceiling and returned; an extra
    approved cost line then pushes the period's eligible total past the ceiling,
    so a resubmission breaches both the draw's state and the cumulative cap.
    """
    first_lines = first_lines or [
        {"amount": 10000.10, "incurred_at": "2026-08-10T00:00:00.000Z"},
        {"amount": 15000.10, "incurred_at": "2026-08-15T00:00:00.000Z"},
    ]
    extra_line = extra_line or {"amount": 20000.10, "incurred_at": "2026-08-20T00:00:00.000Z"}

    ctx = setup_submitted_draw(
        lines=first_lines,
        base_contract_amount=base_contract_amount,
        address="9 Alder Court",
        allowance_category="LIGHTING",
        allowance_amount=4000.00,
        frame_waiver_required=False,
    )
    ctx["draw"] = lender_decide_draw(
        ctx, ctx["draw"]["id"], "RETURN", condition_note="Rebill with corrected cost codes"
    )
    ctx["late_cost_entry"] = post_and_approve_cost_entry(ctx, **extra_line)
    return ctx


def setup_conditionally_approved_draw(ctx=None, *, condition_note="Subject to waivers", **kwargs) -> dict:
    """Submit a draw and have the lender conditionally approve it."""
    ctx = ctx or setup_submitted_draw(**kwargs)
    ctx["draw"] = lender_decide_draw(
        ctx, ctx["draw"]["id"], "CONDITIONALLY_APPROVE", condition_note=condition_note
    )
    return ctx


def setup_two_trade_draw_conditionally_approved() -> dict:
    """A conditionally approved draw that still owes two trades their releases.

    The framing trade carries one 10000.10 invoice and the plumbing trade two,
    of 15000.10 and 20000.10, so the submission demands two lien waivers.
    """
    ctx = setup_job(with_plumbing=True)
    lines = [
        {
            "amount": 10000.10,
            "incurred_at": "2026-08-10T00:00:00.000Z",
            "cost_code": "06-100",
            "subcontractor_id": ctx["sub_frame"]["id"],
        },
        {
            "amount": 15000.10,
            "incurred_at": "2026-08-15T00:00:00.000Z",
            "cost_code": "15-100",
            "subcontractor_id": ctx["sub_plumb"]["id"],
        },
        {
            "amount": 20000.10,
            "incurred_at": "2026-08-20T00:00:00.000Z",
            "cost_code": "15-110",
            "subcontractor_id": ctx["sub_plumb"]["id"],
        },
    ]
    ctx = setup_submitted_draw(ctx, lines=lines)
    ctx = setup_conditionally_approved_draw(ctx)
    ctx["waiver_frame"] = only_lien_waiver(ctx["draw"]["id"], ctx["sub_frame"]["id"])
    ctx["waiver_plumb"] = only_lien_waiver(ctx["draw"]["id"], ctx["sub_plumb"]["id"])
    return ctx


def setup_single_trade_draw_awaiting_verification(
    *, amount_covered: float = 45000.30, waiver_type: str = "CONDITIONAL_PROGRESS"
) -> dict:
    """A conditionally approved draw whose single release has been signed and returned."""
    ctx = setup_submitted_draw(
        lines=[
            {"amount": 10000.10, "incurred_at": "2026-08-10T00:00:00.000Z", "cost_code": "06-100"},
            {"amount": 15000.10, "incurred_at": "2026-08-15T00:00:00.000Z", "cost_code": "06-110"},
            {"amount": 20000.10, "incurred_at": "2026-08-20T00:00:00.000Z", "cost_code": "06-120"},
        ]
    )
    ctx = setup_conditionally_approved_draw(ctx)
    waiver = only_lien_waiver(ctx["draw"]["id"])
    ctx["waiver"] = receive_waiver(
        ctx,
        waiver["id"],
        ctx["sub_frame_headers"],
        waiver_type=waiver_type,
        amount_covered=amount_covered,
        signed_document_ref="waiver-frame-001",
    )
    return ctx


# ==========================================================================
# Tier 6 — punch list, warranty callbacks and photo documentation
# ==========================================================================
def file_defect_ticket(ctx: dict, *, as_role: str = "pm", **overrides) -> dict:
    headers = ctx["client_headers"] if as_role == "client" else ctx["pm_headers"]
    return get_success_data(
        api.create_defect_ticket(
            create_defect_ticket_payload(ctx["project"]["id"], **overrides), headers
        )
    )


def triage_defect_ticket(ctx: dict, ticket_id: str, decision: str, **payload) -> dict:
    body = {"decision": decision}
    body.update(payload)
    return get_success_data(api.triage_defect_ticket(ticket_id, body, ctx["pm_headers"]))


def submit_defect_for_review(ctx: dict, ticket_id: str, sub_headers: dict, **payload) -> dict:
    return get_success_data(api.submit_defect_for_review(ticket_id, payload, sub_headers))


def client_review_defect(ctx: dict, ticket_id: str, decision: str) -> dict:
    return get_success_data(
        api.client_review_defect(ticket_id, {"decision": decision}, ctx["client_headers"])
    )


def upload_photo_document(ctx: dict, **overrides) -> dict:
    return get_success_data(
        api.create_photo_document(
            ctx["project"]["id"], create_photo_document_payload(**overrides), ctx["pm_headers"]
        )
    )


def publish_photo_document(ctx: dict, photo_id: str) -> dict:
    return get_success_data(api.publish_photo_document(photo_id, ctx["pm_headers"]))
