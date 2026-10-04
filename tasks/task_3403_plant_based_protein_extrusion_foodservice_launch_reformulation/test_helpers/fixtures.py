"""Composite setup helpers.

Multi-step preconditions built purely from PRD section 4 endpoints. Every
helper validates its setup calls with get_success_data (lenient on the exact
2xx, loud "Setup step failed" on errors) and returns the server's own
response bodies — never hand-assembled state.

Context-dict conventions: composite fixtures return a dict whose keys are
entity names ("supplier", "lot", "line", "product", "label", "run",
"batch", "program", "forecast", "write_down", "runs", ...); Stage 2 reads
e.g. ctx["batch"]["id"].

Identity threading: all roles are opaque (PRD section 2.1), so shared
TEST_USERS identities are safe everywhere EXCEPT write-down segregation of
duties (PRD section 3.8), where the decider's X-User-ID must differ from the
proposer's. The write-down helpers therefore take explicit user ids and mint
per-call headers through make_demand_planner_headers /
make_finance_controller_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_START_ISO, CHANNEL_FOR_PROGRAM_TYPE
from .factories import (
    DEFAULTS,
    set_clock_payload, create_supplier_payload, supplier_transition_payload,
    create_ingredient_lot_payload, qc_decision_payload,
    create_production_line_payload, line_operational_transition_payload,
    certification_audit_payload, create_product_payload,
    product_lifecycle_payload, create_label_version_payload,
    label_transition_payload, create_production_run_payload,
    run_transition_payload, create_lto_program_payload,
    create_sampling_program_payload, program_lifecycle_payload,
    reserve_batch_payload, create_demand_forecast_payload,
    forecast_transition_payload, create_write_down_payload,
    write_down_decision_payload,
)
from .test_users import (
    TEST_USERS, make_demand_planner_headers, make_finance_controller_headers,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_PM = TEST_USERS["procurement_manager_headers"]
_QM = TEST_USERS["quality_manager_headers"]
_PLANT = TEST_USERS["plant_manager_headers"]
_PROD = TEST_USERS["product_manager_headers"]
_CH = TEST_USERS["channel_manager_headers"]
_DP = TEST_USERS["demand_planner_headers"]


# =============================================================================
# Logical clock
# =============================================================================

def set_clock(to_iso8601=DEFAULT_CLOCK_START_ISO) -> None:
    """Advance the logical clock; also runs the agreement-expiry sweep."""
    get_success_data(api_client.set_clock(set_clock_payload(to_iso8601),
                                          _ADMIN))


# =============================================================================
# Read-back helpers (suppliers and lines have no GET-by-id endpoint; PRD 4)
# =============================================================================

def fetch_supplier(supplier_id) -> dict:
    rows = get_success_data(api_client.list_suppliers(_PM,
                                                      params={"limit": 100}))
    for row in rows:
        if row["id"] == supplier_id:
            return row
    raise AssertionError(f"Setup failed: supplier {supplier_id} not listed")


def fetch_line(line_id) -> dict:
    rows = get_success_data(api_client.list_production_lines(
        _PLANT, params={"limit": 100}))
    for row in rows:
        if row["id"] == line_id:
            return row
    raise AssertionError(f"Setup failed: line {line_id} not listed")


def fetch_product(product_id) -> dict:
    return get_success_data(api_client.get_product(product_id, _PROD))


def fetch_label(label_id) -> dict:
    return get_success_data(api_client.get_label_version(label_id, _PROD))


def fetch_lot(lot_id) -> dict:
    return get_success_data(api_client.get_ingredient_lot(lot_id, _QM))


def fetch_run(run_id) -> dict:
    return get_success_data(api_client.get_production_run(run_id, _PLANT))


def fetch_program(program_id) -> dict:
    return get_success_data(api_client.get_program(program_id, _CH))


def fetch_batch(batch_id) -> dict:
    return get_success_data(api_client.get_finished_goods_batch(batch_id, _CH))


def fetch_forecast(forecast_id) -> dict:
    return get_success_data(api_client.get_demand_forecast(forecast_id, _DP))


def fetch_write_down(write_down_id) -> dict:
    return get_success_data(api_client.get_inventory_write_down(
        write_down_id, TEST_USERS["finance_controller_headers"]))


def current_line_version(line_id) -> int:
    """Re-read the line's OCC token; run creation advances it by one."""
    return fetch_line(line_id)["version"]


def current_product_version(product_id) -> int:
    """Re-read the product's OCC token; label approval advances it by one."""
    return fetch_product(product_id)["version"]


# =============================================================================
# Tier 1: Supplier qualification / agreement progression
# =============================================================================

def create_bare_supplier(**overrides) -> dict:
    """Register a supplier: qualification PENDING_AUDIT, agreement DRAFT."""
    return get_success_data(api_client.create_supplier(
        create_supplier_payload(**overrides), _PM))


def qualify_supplier(supplier_id, audit_score=None) -> dict:
    """PENDING_AUDIT -> QUALIFIED (default score clears both audit gates)."""
    score = DEFAULTS["QUALIFY_AUDIT_SCORE"] if audit_score is None \
        else audit_score
    return get_success_data(api_client.transition_supplier(
        supplier_id,
        supplier_transition_payload("QUALIFICATION", "QUALIFIED",
                                    audit_score=score),
        _PM))


def suspend_supplier(supplier_id) -> dict:
    """QUALIFIED -> SUSPENDED (no score requirement)."""
    return get_success_data(api_client.transition_supplier(
        supplier_id,
        supplier_transition_payload("QUALIFICATION", "SUSPENDED"),
        _PM))


def disqualify_supplier(supplier_id) -> dict:
    """QUALIFIED|SUSPENDED -> DISQUALIFIED (cascades agreement and lots)."""
    return get_success_data(api_client.transition_supplier(
        supplier_id,
        supplier_transition_payload("QUALIFICATION", "DISQUALIFIED"),
        _PM))


def activate_agreement(supplier_id) -> dict:
    """Agreement DRAFT -> ACTIVE (requires qualification QUALIFIED)."""
    return get_success_data(api_client.transition_supplier(
        supplier_id,
        supplier_transition_payload("AGREEMENT", "ACTIVE"),
        _PM))


def terminate_agreement(supplier_id) -> dict:
    """Agreement DRAFT|ACTIVE -> TERMINATED (rejects quarantined lots)."""
    return get_success_data(api_client.transition_supplier(
        supplier_id,
        supplier_transition_payload("AGREEMENT", "TERMINATED"),
        _PM))


def create_qualified_supplier(**overrides) -> dict:
    """Supplier qualified but agreement still DRAFT."""
    supplier = create_bare_supplier(**overrides)
    return qualify_supplier(supplier["id"])


def create_qualified_active_supplier(**overrides) -> dict:
    """Supplier QUALIFIED with agreement ACTIVE — the receivable state."""
    supplier = create_qualified_supplier(**overrides)
    return activate_agreement(supplier["id"])


def setup_expired_agreement_supplier(
        agreement_end_date="2026-09-10T00:00:00Z",
        advance_clock_to="2026-09-15T00:00:00Z",
        lot_overrides=None, **supplier_overrides) -> dict:
    """Supplier with an ACTIVE agreement that the clock sweep then expires,
    leaving one lot behind in QUARANTINE (the sweep never rejects lots).

    Returns ctx with 'supplier' (post-sweep) and 'lot'.
    """
    set_clock()
    supplier = create_qualified_active_supplier(
        agreement_end_date=agreement_end_date, **supplier_overrides)
    lot = create_received_lot(supplier["id"], **(lot_overrides or {}))
    set_clock(advance_clock_to)
    return {"supplier": fetch_supplier(supplier["id"]), "lot": lot}


# =============================================================================
# Tier 1: Ingredient lots
# =============================================================================

def create_received_lot(supplier_id, **overrides) -> dict:
    """Receive a lot into QUARANTINE (requires agreement ACTIVE)."""
    return get_success_data(api_client.create_ingredient_lot(
        create_ingredient_lot_payload(supplier_id, **overrides), _PM))


def release_lot(lot_id,
                invoiced_unit_cost_cents=DEFAULTS["INVOICED_UNIT_COST_CENTS"],
                actual_freight_cents_per_kg=DEFAULTS[
                    "ACTUAL_FREIGHT_CENTS_PER_KG"]) -> dict:
    """QC release: stamps final_unit_cost_cents and adds to delivered kg."""
    return get_success_data(api_client.qc_decision(
        lot_id,
        qc_decision_payload("RELEASED",
                            invoiced_unit_cost_cents=invoiced_unit_cost_cents,
                            actual_freight_cents_per_kg=
                            actual_freight_cents_per_kg),
        _QM))


def reject_lot(lot_id) -> dict:
    """QC reject: no commercial inputs required."""
    return get_success_data(api_client.qc_decision(
        lot_id, qc_decision_payload("REJECTED"), _QM))


def create_released_lot(supplier_id,
                        invoiced_unit_cost_cents=
                        DEFAULTS["INVOICED_UNIT_COST_CENTS"],
                        actual_freight_cents_per_kg=
                        DEFAULTS["ACTUAL_FREIGHT_CENTS_PER_KG"],
                        **lot_overrides) -> dict:
    """Receive + QC-release a lot. Returns the released lot."""
    lot = create_received_lot(supplier_id, **lot_overrides)
    return release_lot(lot["id"], invoiced_unit_cost_cents,
                       actual_freight_cents_per_kg)


# =============================================================================
# Tier 1: Production lines
# =============================================================================

def create_owned_line(**overrides) -> dict:
    """OWNED line: certification CERTIFIED and operational IDLE at creation."""
    return get_success_data(api_client.create_production_line(
        create_production_line_payload(site_type="OWNED", **overrides),
        _PLANT))


def create_coman_line(coman_partner_name=DEFAULTS["COMAN_PARTNER_NAME"],
                      monthly_reserved_capacity_kg=
                      DEFAULTS["MONTHLY_RESERVED_CAPACITY_KG"],
                      **overrides) -> dict:
    """CO_MAN line: certification PENDING until an equivalence audit passes."""
    return get_success_data(api_client.create_production_line(
        create_production_line_payload(
            site_type="CO_MAN",
            coman_partner_name=coman_partner_name,
            monthly_reserved_capacity_kg=monthly_reserved_capacity_kg,
            **overrides),
        _PLANT))


def post_certification_audit(line_id, texture_score=DEFAULTS["TEXTURE_SCORE"],
                             moisture_variance_pct=
                             DEFAULTS["AUDIT_MOISTURE_VARIANCE_PCT"]) -> dict:
    """Record a co-man equivalence audit; pass/fail derives from thresholds."""
    return get_success_data(api_client.create_certification_audit(
        line_id,
        certification_audit_payload(texture_score=texture_score,
                                    moisture_variance_pct=
                                    moisture_variance_pct),
        _QM))


def certify_coman_line(line_id, **audit_scores) -> dict:
    """Drive a CO_MAN line to CERTIFIED with a passing audit."""
    return post_certification_audit(line_id, **audit_scores)


def move_line_operational(line_id, target_status) -> dict:
    """Move the line's operational dimension (IDLE/SETUP/RUNNING/CLEANING/
    DOWN graph)."""
    return get_success_data(api_client.line_operational_transition(
        line_id, line_operational_transition_payload(target_status), _PLANT))


def reset_line_to_idle(line_id) -> dict:
    """Return the line to IDLE. After a run completes or aborts mid-flight the
    line sits in CLEANING, and CLEANING -> IDLE is the legal edge back; a
    dedicated run start requires the line exactly IDLE."""
    line = fetch_line(line_id)
    if line["operational_status"] == "IDLE":
        return line
    return move_line_operational(line_id, "IDLE")


# =============================================================================
# Tier 1: Products and label versions (OCC-aware)
# =============================================================================

def create_bare_product(**overrides) -> dict:
    """Create a product generation in DEVELOPMENT."""
    return get_success_data(api_client.create_product(
        create_product_payload(**overrides), _PROD))


def create_draft_label(product_id, **overrides) -> dict:
    """Draft a label version (starts DRAFT)."""
    return get_success_data(api_client.create_label_version(
        product_id, create_label_version_payload(**overrides), _PROD))


def submit_label(label_id) -> dict:
    """DRAFT -> SUBMITTED (claim gates run here)."""
    return get_success_data(api_client.label_version_transition(
        label_id, label_transition_payload("SUBMITTED"), _PROD))


def return_label_to_draft(label_id) -> dict:
    """SUBMITTED -> DRAFT (return for revision)."""
    return get_success_data(api_client.label_version_transition(
        label_id, label_transition_payload("DRAFT"), _PROD))


def approve_label(label_id, product_id) -> dict:
    """SUBMITTED -> APPROVED. Re-reads the product's version immediately
    before approving so the OCC token is fresh, then bumps product.version."""
    version = current_product_version(product_id)
    return get_success_data(api_client.label_version_transition(
        label_id,
        label_transition_payload("APPROVED", expected_product_version=version),
        _PROD))


def transition_product(product_id, target_state) -> dict:
    """Drive the product lifecycle one declared step."""
    return get_success_data(api_client.product_lifecycle_transition(
        product_id, product_lifecycle_payload(target_state), _PROD))


def create_product_with_approved_label(product_overrides=None,
                                       label_overrides=None):
    """Product (DEVELOPMENT) with one label taken DRAFT -> SUBMITTED ->
    APPROVED. Returns (product, label), both freshly read."""
    product = create_bare_product(**(product_overrides or {}))
    label = create_draft_label(product["id"], **(label_overrides or {}))
    submit_label(label["id"])
    label = approve_label(label["id"], product["id"])
    return fetch_product(product["id"]), label


def create_pilot_product_with_label(product_overrides=None,
                                    label_overrides=None):
    """Product in PILOT with an APPROVED label. Returns (product, label)."""
    product, label = create_product_with_approved_label(product_overrides,
                                                        label_overrides)
    product = transition_product(product["id"], "PILOT")
    return product, label


def create_active_product_with_label(product_overrides=None,
                                     label_overrides=None):
    """Product in ACTIVE with an APPROVED label (activation computes the
    price-parity trio). Returns (product, label)."""
    product, label = create_pilot_product_with_label(product_overrides,
                                                     label_overrides)
    product = transition_product(product["id"], "ACTIVE")
    return product, label


# =============================================================================
# Tier 2: Canonical production scenario
# =============================================================================

def setup_production_scenario(supplier_overrides=None, lot_overrides=None,
                              line_overrides=None, product_overrides=None,
                              label_overrides=None,
                              invoiced_unit_cost_cents=
                              DEFAULTS["INVOICED_UNIT_COST_CENTS"],
                              actual_freight_cents_per_kg=
                              DEFAULTS["ACTUAL_FREIGHT_CENTS_PER_KG"],
                              set_clock_first=True) -> dict:
    """The canonical chain: clock pinned to the PRD default, one supplier
    QUALIFIED with agreement ACTIVE, one lot RELEASED (default 500 kg at
    final 535 cents/kg), one OWNED CERTIFIED line, and one product ACTIVE
    with an APPROVED label.

    Returns ctx with 'supplier', 'lot', 'line', 'product', 'label'.
    """
    if set_clock_first:
        set_clock()
    supplier = create_qualified_active_supplier(**(supplier_overrides or {}))
    lot = create_released_lot(
        supplier["id"],
        invoiced_unit_cost_cents=invoiced_unit_cost_cents,
        actual_freight_cents_per_kg=actual_freight_cents_per_kg,
        **(lot_overrides or {}))
    line = create_owned_line(**(line_overrides or {}))
    product, label = create_active_product_with_label(product_overrides,
                                                      label_overrides)
    return {"supplier": supplier, "lot": lot, "line": line,
            "product": product, "label": label}


# =============================================================================
# Tier 3: Production run lifecycle
# =============================================================================

def schedule_run(ctx, channel=DEFAULTS["CHANNEL"],
                 planned_quantity_kg=DEFAULTS["PLANNED_QUANTITY_KG"],
                 scheduled_start=DEFAULTS["SCHEDULED_START"],
                 scheduled_end=DEFAULTS["SCHEDULED_END"],
                 program_id=None) -> dict:
    """Create a run against the scenario's line/product/label, re-reading the
    line version so the OCC token is always fresh. Lands in SCHEDULED."""
    payload = create_production_run_payload(
        production_line_id=ctx["line"]["id"],
        product_id=ctx["product"]["id"],
        label_version_id=ctx["label"]["id"],
        expected_line_version=current_line_version(ctx["line"]["id"]),
        program_id=program_id,
        channel=channel,
        planned_quantity_kg=planned_quantity_kg,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end)
    return get_success_data(api_client.create_production_run(payload, _PLANT))


def start_run(run_id) -> dict:
    """SCHEDULED -> IN_PROGRESS (PlantManager); moves the line to RUNNING."""
    return get_success_data(api_client.production_run_transition(
        run_id, run_transition_payload("IN_PROGRESS"), _PLANT))


def complete_run(run_id,
                 actual_quantity_kg=DEFAULTS["ACTUAL_QUANTITY_KG"]) -> dict:
    """IN_PROGRESS -> COMPLETED: FIFO lot consumption, batch creation,
    program delivery cascade, line to CLEANING."""
    return get_success_data(api_client.production_run_transition(
        run_id,
        run_transition_payload("COMPLETED",
                               actual_quantity_kg=actual_quantity_kg),
        _PLANT))


def abort_run(run_id) -> dict:
    """SCHEDULED|IN_PROGRESS -> ABORTED (releases reserved line capacity)."""
    return get_success_data(api_client.production_run_transition(
        run_id, run_transition_payload("ABORTED"), _PLANT))


def release_run(run_id) -> dict:
    """COMPLETED -> RELEASED (QualityManager disposition)."""
    return get_success_data(api_client.production_run_transition(
        run_id, run_transition_payload("RELEASED"), _QM))


def recall_run(run_id) -> dict:
    """COMPLETED -> RECALLED; raises recall_flag on every batch of the run."""
    return get_success_data(api_client.production_run_transition(
        run_id, run_transition_payload("RECALLED"), _QM))


def get_run_batch(run_id) -> dict:
    """The single batch a completed run produced."""
    rows = get_success_data(api_client.list_finished_goods_batches(
        _PLANT, params={"production_run_id": run_id}))
    assert len(rows) == 1, (
        f"Setup failed: expected exactly one batch for run {run_id}, "
        f"got {len(rows)}")
    return rows[0]


def setup_run_in_progress(channel=DEFAULTS["CHANNEL"],
                          planned_quantity_kg=
                          DEFAULTS["PLANNED_QUANTITY_KG"],
                          scheduled_start=DEFAULTS["SCHEDULED_START"],
                          scheduled_end=DEFAULTS["SCHEDULED_END"],
                          program_id=None, **scenario_kwargs) -> dict:
    """Canonical scenario + a run taken to IN_PROGRESS. Adds 'run' to ctx."""
    ctx = setup_production_scenario(**scenario_kwargs)
    run = schedule_run(ctx, channel=channel,
                       planned_quantity_kg=planned_quantity_kg,
                       scheduled_start=scheduled_start,
                       scheduled_end=scheduled_end, program_id=program_id)
    ctx["run"] = start_run(run["id"])
    return ctx


def setup_completed_batch(channel=DEFAULTS["CHANNEL"],
                          actual_quantity_kg=DEFAULTS["ACTUAL_QUANTITY_KG"],
                          planned_quantity_kg=None,
                          scheduled_start=DEFAULTS["SCHEDULED_START"],
                          scheduled_end=DEFAULTS["SCHEDULED_END"],
                          program_id=None, **scenario_kwargs) -> dict:
    """Canonical scenario + a run completed, producing exactly one batch.
    Adds 'run' and 'batch' to ctx."""
    ctx = setup_run_in_progress(
        channel=channel,
        planned_quantity_kg=(planned_quantity_kg
                             if planned_quantity_kg is not None
                             else actual_quantity_kg),
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
        program_id=program_id, **scenario_kwargs)
    ctx["run"] = complete_run(ctx["run"]["id"], actual_quantity_kg)
    ctx["batch"] = get_run_batch(ctx["run"]["id"])
    return ctx


def setup_recalled_batch(channel=DEFAULTS["CHANNEL"],
                         actual_quantity_kg=DEFAULTS["ACTUAL_QUANTITY_KG"],
                         **scenario_kwargs) -> dict:
    """Completed run then RECALLED — batch.recall_flag is true, so RECALL
    write-downs are legal. Adds 'run' and 'batch' (refreshed) to ctx."""
    ctx = setup_completed_batch(channel=channel,
                                actual_quantity_kg=actual_quantity_kg,
                                **scenario_kwargs)
    ctx["run"] = recall_run(ctx["run"]["id"])
    ctx["batch"] = fetch_batch(ctx["batch"]["id"])
    return ctx


# =============================================================================
# Tier 3: Growth programs
# =============================================================================

def create_lto_program(product_id, program_code=DEFAULTS["PROGRAM_CODE"],
                       partner_code=DEFAULTS["PARTNER_CODE"],
                       committed_cases=DEFAULTS["COMMITTED_CASES"],
                       window_start=DEFAULTS["PROGRAM_WINDOW_START"],
                       window_end=DEFAULTS["PROGRAM_WINDOW_END"],
                       dedicated_run_required=
                       DEFAULTS["DEDICATED_RUN_REQUIRED"]) -> dict:
    """Create a FOODSERVICE_LTO program (starts PROPOSED)."""
    return get_success_data(api_client.create_program(
        create_lto_program_payload(
            product_id, program_code=program_code, partner_code=partner_code,
            committed_cases=committed_cases, window_start=window_start,
            window_end=window_end,
            dedicated_run_required=dedicated_run_required),
        _CH))


def create_sampling_program(product_id, program_code=DEFAULTS["PROGRAM_CODE"],
                            budget_cents=DEFAULTS["BUDGET_CENTS"],
                            coupons_issued=DEFAULTS["COUPONS_ISSUED"],
                            window_start=DEFAULTS["PROGRAM_WINDOW_START"],
                            window_end=DEFAULTS["PROGRAM_WINDOW_END"]) -> dict:
    """Create a SAMPLING_DEMO program (starts PROPOSED)."""
    return get_success_data(api_client.create_program(
        create_sampling_program_payload(
            product_id, program_code=program_code, budget_cents=budget_cents,
            coupons_issued=coupons_issued, window_start=window_start,
            window_end=window_end),
        _CH))


def program_transition(program_id, target_status,
                       final_coupons_redeemed=None) -> dict:
    """Drive the program lifecycle one step."""
    return get_success_data(api_client.program_lifecycle(
        program_id,
        program_lifecycle_payload(target_status,
                                  final_coupons_redeemed=
                                  final_coupons_redeemed),
        _CH))


def activate_program(program_id) -> dict:
    """PROPOSED -> ACTIVE (product producibility + LTO partner gap rule)."""
    return program_transition(program_id, "ACTIVE")


def open_program_window(program_id) -> dict:
    """ACTIVE -> IN_WINDOW (the clock must sit inside the window)."""
    return program_transition(program_id, "IN_WINDOW")


def evaluate_program(program_id, final_coupons_redeemed=None) -> dict:
    """IN_WINDOW -> EVALUATING (sampling must report final_coupons_redeemed)."""
    return program_transition(program_id, "EVALUATING",
                              final_coupons_redeemed=final_coupons_redeemed)


def terminate_program(program_id) -> dict:
    """Any non-terminal state -> TERMINATED; releases batch reservations."""
    return program_transition(program_id, "TERMINATED")


def setup_lto_program(product_id, **kwargs) -> dict:
    """LTO program in ACTIVE (the state that accepts dedicated runs)."""
    program = create_lto_program(product_id, **kwargs)
    return activate_program(program["id"])


def setup_lto_program_in_window(product_id, **kwargs) -> dict:
    """LTO program in IN_WINDOW (default window contains the default clock)."""
    program = setup_lto_program(product_id, **kwargs)
    return open_program_window(program["id"])


def setup_sampling_program_in_window(product_id, **kwargs) -> dict:
    """SAMPLING_DEMO program in IN_WINDOW."""
    program = create_sampling_program(product_id, **kwargs)
    activate_program(program["id"])
    return open_program_window(program["id"])


# =============================================================================
# Tier 4: Dedicated-run delivery accumulation (attainment targeting)
# =============================================================================

def complete_dedicated_run(ctx, program, planned_quantity_kg,
                           actual_quantity_kg, scheduled_start,
                           scheduled_end) -> tuple:
    """Schedule -> start -> complete one dedicated run for the program, in the
    program's channel. Resets the line to IDLE first (a dedicated start needs
    the line exactly IDLE; a prior completion leaves it CLEANING). Returns
    (run, batch)."""
    reset_line_to_idle(ctx["line"]["id"])
    run = schedule_run(
        ctx, channel=CHANNEL_FOR_PROGRAM_TYPE[program["program_type"]],
        planned_quantity_kg=planned_quantity_kg,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
        program_id=program["id"])
    start_run(run["id"])
    run = complete_run(run["id"], actual_quantity_kg)
    return run, get_run_batch(run["id"])


def setup_lto_program_with_deliveries(committed_cases, run_kg_list,
                                      partner_code=DEFAULTS["PARTNER_CODE"],
                                      program_code=DEFAULTS["PROGRAM_CODE"],
                                      window_start=
                                      DEFAULTS["PROGRAM_WINDOW_START"],
                                      window_end=DEFAULTS["PROGRAM_WINDOW_END"],
                                      **scenario_kwargs) -> dict:
    """Canonical scenario plus a FOODSERVICE_LTO program driven to IN_WINDOW
    with one completed dedicated run per entry of run_kg_list (each run's
    planned and actual kilograms equal the entry; windows are spread across
    consecutive days inside the program window).

    Example: setup_lto_program_with_deliveries(20, [100, 75]) delivers
    floor(100/10) + floor(75/10) = 17 cases for attainment 85.00.

    Returns ctx with 'program' (refreshed) and 'runs' = [(run, batch), ...].
    """
    ctx = setup_production_scenario(**scenario_kwargs)
    program = setup_lto_program_in_window(
        ctx["product"]["id"], program_code=program_code,
        partner_code=partner_code, committed_cases=committed_cases,
        window_start=window_start, window_end=window_end)
    runs = []
    for index, kg in enumerate(run_kg_list):
        day = 5 + index
        runs.append(complete_dedicated_run(
            ctx, program, planned_quantity_kg=kg, actual_quantity_kg=kg,
            scheduled_start=f"2026-09-{day:02d}T08:00:00Z",
            scheduled_end=f"2026-09-{day:02d}T12:00:00Z"))
    ctx["program"] = fetch_program(program["id"])
    ctx["runs"] = runs
    return ctx


def setup_two_batches_staggered_expiry(**scenario_kwargs) -> dict:
    """Two non-dedicated FOODSERVICE batches of the same product: the first
    produced at the default clock, the second produced two days later after a
    clock advance, so the first has the strictly earlier expiry_date (FEFO
    order). Adds 'batch2'/'run2' to ctx."""
    ctx = setup_completed_batch(channel="FOODSERVICE", actual_quantity_kg=100,
                                **scenario_kwargs)
    set_clock("2026-09-03T00:00:00Z")
    reset_line_to_idle(ctx["line"]["id"])
    run2 = schedule_run(ctx, channel="FOODSERVICE", planned_quantity_kg=100,
                        scheduled_start="2026-09-06T08:00:00Z",
                        scheduled_end="2026-09-06T12:00:00Z")
    start_run(run2["id"])
    ctx["run2"] = complete_run(run2["id"], 100)
    ctx["batch2"] = get_run_batch(ctx["run2"]["id"])
    return ctx


# =============================================================================
# Tier 3: Batch reservation
# =============================================================================

def reserve_batch_cases(batch_id, program_id, quantity_cases) -> dict:
    """Reserve cases of an available batch to a program (ChannelManager)."""
    return get_success_data(api_client.reserve_batch(
        batch_id, reserve_batch_payload(program_id, quantity_cases), _CH))


# =============================================================================
# Tier 3: Demand forecasts
# =============================================================================

def create_forecast(product_id, channel=DEFAULTS["CHANNEL"],
                    week_start=DEFAULTS["WEEK_START"],
                    forecast_cases=DEFAULTS["FORECAST_CASES"]) -> dict:
    """Create a weekly forecast (starts PROVISIONAL)."""
    return get_success_data(api_client.create_demand_forecast(
        create_demand_forecast_payload(
            product_id, channel=channel, week_start=week_start,
            forecast_cases=forecast_cases),
        _DP))


def lock_forecast(forecast_id) -> dict:
    """PROVISIONAL -> LOCKED."""
    return get_success_data(api_client.demand_forecast_transition(
        forecast_id, forecast_transition_payload("LOCKED"), _DP))


def actualize_forecast(forecast_id, actual_cases) -> dict:
    """LOCKED -> ACTUALIZED; computes variance_pct and is_miss."""
    return get_success_data(api_client.demand_forecast_transition(
        forecast_id,
        forecast_transition_payload("ACTUALIZED", actual_cases=actual_cases),
        _DP))


def create_locked_forecast(product_id, **kwargs) -> dict:
    forecast = create_forecast(product_id, **kwargs)
    return lock_forecast(forecast["id"])


def create_actualized_forecast(product_id, actual_cases, **kwargs) -> dict:
    """Forecast taken PROVISIONAL -> LOCKED -> ACTUALIZED with the given
    actual demand."""
    forecast = create_locked_forecast(product_id, **kwargs)
    return actualize_forecast(forecast["id"], actual_cases)


# =============================================================================
# Tier 5: Inventory write-downs (segregation-of-duties aware)
# =============================================================================

def propose_write_down(batch_id, quantity_cases=
                       DEFAULTS["WRITE_DOWN_QUANTITY_CASES"],
                       reason=DEFAULTS["WRITE_DOWN_REASON"],
                       demand_forecast_id=None,
                       proposer_user_id="planner-1") -> dict:
    """DemandPlanner proposes a write-down; the proposer's X-User-ID lands on
    proposed_by_user_id. Returns the PROPOSED write-down."""
    return get_success_data(api_client.create_inventory_write_down(
        create_write_down_payload(batch_id, quantity_cases, reason,
                                  demand_forecast_id=demand_forecast_id),
        make_demand_planner_headers(proposer_user_id)))


def decide_write_down(write_down_id, decision,
                      decider_user_id="fin-1") -> dict:
    """FinanceController decides. Segregation of duties: decider_user_id must
    differ from the write-down's proposed_by_user_id — the default 'fin-1'
    satisfies this against the default proposer 'planner-1'."""
    return get_success_data(api_client.decide_write_down(
        write_down_id, write_down_decision_payload(decision),
        make_finance_controller_headers(decider_user_id)))


def post_write_down(write_down_id, decider_user_id="fin-1") -> dict:
    """PROPOSED -> POSTED (computes the NRV-based final amount)."""
    return decide_write_down(write_down_id, "POSTED", decider_user_id)


def reject_write_down(write_down_id, decider_user_id="fin-1") -> dict:
    """PROPOSED -> REJECTED (batch untouched)."""
    return decide_write_down(write_down_id, "REJECTED", decider_user_id)


def setup_proposed_recall_write_down(quantity_cases=1,
                                     proposer_user_id="planner-1",
                                     **scenario_kwargs) -> dict:
    """Recalled-batch scenario plus a RECALL write-down left in PROPOSED.
    Adds 'write_down' to ctx."""
    ctx = setup_recalled_batch(**scenario_kwargs)
    ctx["write_down"] = propose_write_down(
        ctx["batch"]["id"], quantity_cases=quantity_cases, reason="RECALL",
        proposer_user_id=proposer_user_id)
    return ctx


def setup_posted_recall_write_down(quantity_cases=2,
                                   proposer_user_id="planner-1",
                                   decider_user_id="fin-1",
                                   **scenario_kwargs) -> dict:
    """A RECALL write-down taken PROPOSED -> POSTED by a different identity
    than its proposer. Adds 'write_down' and refreshed 'batch' to ctx."""
    ctx = setup_proposed_recall_write_down(
        quantity_cases=quantity_cases, proposer_user_id=proposer_user_id,
        **scenario_kwargs)
    ctx["write_down"] = post_write_down(ctx["write_down"]["id"],
                                        decider_user_id)
    ctx["batch"] = fetch_batch(ctx["batch"]["id"])
    return ctx
