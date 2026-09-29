"""Breadth coverage of the kiln run's two-dimensional lifecycle and of the outage
completion branch that decides whether a kiln may be lit again.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_instant_equals
from test_helpers.test_users import ADMIN_HEADERS, ENGINEER_HEADERS, OPERATOR_HEADERS


# ---------------------------------------------------------------------------
# initial_state
# ---------------------------------------------------------------------------
def test_a_new_kiln_run_is_scheduled_and_pending_lab_at_once(api):
    """Both dimensions are present as separate keys on the freshly scheduled run, the energy
    ledger is zeroed, and neither the pile nor the kiln has moved.

    PRD: "The run is born with `process_state` at `SCHEDULED`, `quality_state` at
    `PENDING_LAB` and an empty `fuel_charges` array."

    Design: Corner/state_machines/kiln_run_initial_state_is_scheduled_and_pending_lab
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])

    run = validate_success(
        api.create_kiln_run(
            f.kiln_run_payload(
                env["kiln"]["id"],
                pile["id"],
                env["clinker_silo"]["id"],
                window_start="2026-08-01T00:00:00Z",
                window_end="2026-08-01T12:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )
    assert run["process_state"] == "SCHEDULED"
    assert run["quality_state"] == "PENDING_LAB"
    assert run["fuel_charges"] == []
    assert_amount(run["scheduled_hours"], 12.00, "scheduled_hours")
    assert_amount(run["gross_energy_gj"], 0.00, "gross_energy_gj")
    assert_amount(
        run["provisional_clinker_tonnes"], 0.00, "provisional_clinker_tonnes"
    )
    assert_amount(run["clinker_tonnes"], 0.00, "clinker_tonnes")
    assert_amount(run["tsr_pct"], 0.00, "tsr_pct")
    assert_amount(run["nox_emitted_kg"], 0.00, "nox_emitted_kg")
    assert_amount(run["chlorine_input_kg"], 0.00, "chlorine_input_kg")
    assert run["nox_intensity_breach"] is False
    assert run["free_lime_pct"] is None
    assert run["lit_at"] is None
    assert run["completed_at"] is None
    assert run["abort_reason"] is None
    assert run["version"] == 1

    # Scheduling consumes nothing.
    still_sealed = validate_success(api.get_pile(pile["id"], ENGINEER_HEADERS))
    assert still_sealed["status"] == "SEALED"
    kiln = validate_success(api.get_kiln(env["kiln"]["id"], ENGINEER_HEADERS))
    assert kiln["availability_state"] == "AVAILABLE"
    assert kiln["refractory_hours_since_reline"] == 0


# ---------------------------------------------------------------------------
# side_effect_execution: lighting consumes the bed
# ---------------------------------------------------------------------------
def test_lighting_a_run_consumes_its_pile_and_recomputes_the_active_pile_count(api):
    """One light call writes three rows: the run turns BURNING, the pile turns CONSUMED, and
    the design's active pile count falls to 0 with a version of its own.

    PRD: "Lighting also consumes the feed: the pile moves `SEALED → CONSUMED`, which removes
    it from the design's open-and-sealed set, so the design's `active_pile_count` is
    recomputed and the design's `version` increments."

    Design: Corner/state_machines/lighting_a_run_consumes_its_pile_and_recomputes_active_pile_count
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])
    run = fx.create_scheduled_run(
        api,
        env["kiln"]["id"],
        pile["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )

    before_design = validate_success(api.get_design(design["id"], ENGINEER_HEADERS))
    assert before_design["active_pile_count"] == 1
    assert before_design["version"] == 4

    lit = validate_success(api.light_kiln_run(run["id"], OPERATOR_HEADERS))
    assert lit["process_state"] == "BURNING"
    assert lit["quality_state"] == "PENDING_LAB"
    assert_instant_equals(lit["lit_at"], "2026-08-01T00:00:00Z", "lit_at")
    assert lit["version"] == 2

    consumed = validate_success(api.get_pile(pile["id"], ENGINEER_HEADERS))
    assert consumed["status"] == "CONSUMED"
    assert_amount(consumed["dry_tonnes"], 1000.00, "dry_tonnes")
    assert_amount(consumed["consumed_dry_tonnes"], 0.00, "consumed_dry_tonnes")

    after_design = validate_success(api.get_design(design["id"], ENGINEER_HEADERS))
    assert after_design["active_pile_count"] == 0
    assert after_design["version"] == 5

    validate_error(
        api.light_kiln_run(run["id"], OPERATOR_HEADERS),
        ApiErrorId.ERR_INVALID_RUN_STATE.value,
        409,
    )
    unchanged = validate_success(api.get_kiln_run(run["id"], OPERATOR_HEADERS))
    assert_instant_equals(unchanged["lit_at"], "2026-08-01T00:00:00Z", "lit_at")
    assert unchanged["version"] == 2


# ---------------------------------------------------------------------------
# precondition_enforcement: the window must have elapsed
# ---------------------------------------------------------------------------
def test_a_run_cannot_be_completed_before_its_window_has_elapsed(api):
    """Fuel in the kiln is not enough: with the clock still at the start of a twelve-hour
    window the completion is refused, the charge stands, and no clinker is credited until
    the clock reaches window_end.

    PRD: "Completion requires the run to be `BURNING`, else `ERR_INVALID_RUN_STATE`; requires
    the logical clock to have reached or passed `window_end`, else
    `ERR_RUN_WINDOW_NOT_ELAPSED`; and requires at least one fuel charge to have been
    recorded, so that `gross_energy_gj` is greater than zero — a run with nothing fired is
    refused with `ERR_INVALID_RUN_STATE`."

    Design: Corner/state_machines/run_cannot_be_completed_before_its_window_has_elapsed
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])
    run = fx.create_burning_run(
        api,
        env["kiln"]["id"],
        pile["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    fx.charge(api, run["id"], env["fuels"]["gas"]["id"], 45.00)

    validate_error(
        api.complete_kiln_run(run["id"], OPERATOR_HEADERS),
        ApiErrorId.ERR_RUN_WINDOW_NOT_ELAPSED.value,
        422,
    )

    burning = validate_success(api.get_kiln_run(run["id"], OPERATOR_HEADERS))
    assert burning["process_state"] == "BURNING"
    assert burning["completed_at"] is None
    # PRD 3.5 has each charge recompute "the whole thermal picture of the run", so the burning
    # run already carries its derived clinker figure; completion merely "freezes clinker_tonnes
    # against further change". What has not happened is the physical credit to the silo, which
    # the silo assertions below pin down.
    assert_amount(burning["clinker_tonnes"], 583.78, "clinker_tonnes")
    assert_amount(burning["gross_energy_gj"], 2160.00, "gross_energy_gj")
    assert_amount(burning["nox_emitted_kg"], 216.00, "nox_emitted_kg")

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], OPERATOR_HEADERS))
    assert_amount(silo["tonnes_on_hand"], 0.00, "tonnes_on_hand")
    assert_amount(silo["unreleased_tonnes"], 0.00, "unreleased_tonnes")

    fx.set_clock(api, "2026-08-01T12:00:00Z")
    completed = validate_success(api.complete_kiln_run(run["id"], OPERATOR_HEADERS))
    assert completed["process_state"] == "COMPLETED"
    assert_amount(completed["clinker_tonnes"], 583.78, "clinker_tonnes")


# ---------------------------------------------------------------------------
# terminal_state_lockdown: ABORTED closes the process dimension
# ---------------------------------------------------------------------------
def test_an_aborted_run_refuses_completion_even_once_the_window_has_passed(api):
    """ABORTED is terminal on the process dimension, so once the clock has passed window_end
    — which would have satisfied the elapsed-window gate — completion and further fuel
    charges are both refused on state alone.

    PRD: "On every transition endpoint: the subject's current state is a legal originating
    state for the requested transition, else that entity's own invalid-state error (409) —
    `ERR_INVALID_DESIGN_STATE`, `ERR_INVALID_PILE_STATE`, `ERR_INVALID_BURN_TEST_STATE`,
    `ERR_INVALID_RUN_STATE`, `ERR_INVALID_OUTAGE_STATE`, `ERR_INVALID_BATCH_STATE`,
    `ERR_INVALID_CERTIFICATE_STATE` or `ERR_INVALID_ORDER_STATE`."

    Design: Corner/state_machines/aborted_run_is_terminal_and_a_later_complete_is_rejected
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])
    run = fx.create_burning_run(
        api,
        env["kiln"]["id"],
        pile["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    fx.charge(api, run["id"], env["fuels"]["gas"]["id"], 45.00)

    aborted = validate_success(
        api.abort_kiln_run(
            run["id"], {"abort_reason": "kiln trip on the main drive"}, OPERATOR_HEADERS
        )
    )
    assert aborted["process_state"] == "ABORTED"
    assert aborted["abort_reason"] == "kiln trip on the main drive"
    assert_amount(aborted["nox_emitted_kg"], 0.00, "nox_emitted_kg")
    assert_amount(aborted["clinker_tonnes"], 0.00, "clinker_tonnes")

    fx.set_clock(api, "2026-08-01T12:00:00Z")

    validate_error(
        api.complete_kiln_run(run["id"], OPERATOR_HEADERS),
        ApiErrorId.ERR_INVALID_RUN_STATE.value,
        409,
    )
    validate_error(
        api.charge_fuel(
            run["id"],
            f.fuel_charge_payload(env["fuels"]["gas"]["id"], 10.00),
            OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_INVALID_RUN_STATE.value,
        409,
    )

    terminal = validate_success(api.get_kiln_run(run["id"], OPERATOR_HEADERS))
    assert terminal["process_state"] == "ABORTED"
    assert terminal["completed_at"] is None
    assert len(terminal["fuel_charges"]) == 1

    # The raw meal is physically gone and is not given back.
    consumed = validate_success(api.get_pile(pile["id"], ENGINEER_HEADERS))
    assert consumed["status"] == "CONSUMED"


# ---------------------------------------------------------------------------
# side_effect_execution: the refractory branch of outage completion
# ---------------------------------------------------------------------------
def _reline_due_kiln_with_outage(api):
    """A kiln whose reline is due after one twelve-hour burn, plus an IN_PROGRESS
    refractory outage on it."""
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(api, env["plant_id"], design["id"], env["materials"])
    kiln = fx.create_kiln(api, env["plant_id"], code="K2", reline_due_hours=10)
    run = fx.create_burning_run(
        api,
        kiln["id"],
        pile["id"],
        env["clinker_silo"]["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    fx.charge(api, run["id"], env["fuels"]["gas"]["id"], 45.00)
    fx.set_clock(api, "2026-08-01T12:00:00Z")
    fx.data_of(api.complete_kiln_run(run["id"], OPERATOR_HEADERS))

    worn = fx.data_of(api.get_kiln(kiln["id"], ENGINEER_HEADERS))
    assert worn["refractory_hours_since_reline"] == 12
    assert worn["availability_state"] == "RELINE_DUE"

    outage = validate_success(
        api.create_outage(
            f.outage_payload(
                kiln["id"],
                "2026-10-01T00:00:00Z",
                "2026-10-03T00:00:00Z",
                scope="REFRACTORY",
            ),
            ENGINEER_HEADERS,
        ),
        201,
    )
    assert outage["status"] == "PLANNED"
    approved = validate_success(api.approve_outage(outage["id"], ADMIN_HEADERS))
    assert approved["status"] == "APPROVED"

    fx.set_clock(api, "2026-10-01T00:00:00Z")
    started = validate_success(api.start_outage(outage["id"], ENGINEER_HEADERS))
    assert started["status"] == "IN_PROGRESS"
    return kiln, outage


def test_an_outage_completed_without_a_reline_leaves_the_kiln_reline_due(api):
    """The hour meter is untouched by a completion that replaced no refractory, so a kiln
    that had already passed its reline threshold comes out of the outage still RELINE_DUE.

    PRD: "When `refractory_replaced` is false, the accumulated hours are left completely
    untouched, so a kiln that had already reached or passed `reline_due_hours` returns to
    `RELINE_DUE` rather than `AVAILABLE` and still cannot be lit."

    Design: Corner/state_machines/outage_completed_without_refractory_replacement_leaves_the_kiln_reline_due
    """
    kiln, outage = _reline_due_kiln_with_outage(api)

    completed = validate_success(
        api.complete_outage(outage["id"], {"refractory_replaced": False}, ENGINEER_HEADERS)
    )
    assert completed["status"] == "COMPLETED"
    assert completed["refractory_replaced"] is False
    assert_instant_equals(
        completed["completed_at"], "2026-10-01T00:00:00Z", "completed_at"
    )

    still_due = validate_success(api.get_kiln(kiln["id"], ENGINEER_HEADERS))
    assert still_due["refractory_hours_since_reline"] == 12
    assert still_due["availability_state"] == "RELINE_DUE"


def test_an_outage_completed_with_a_reline_returns_the_kiln_to_service(api):
    """The other branch of the same transition zeroes the hour meter and hands the kiln back
    as AVAILABLE.

    PRD: "When `refractory_replaced` is true, the kiln's `refractory_hours_since_reline` is
    reset to 0 and its `availability_state` becomes `AVAILABLE`."

    Design: Corner/state_machines/outage_completed_without_refractory_replacement_leaves_the_kiln_reline_due
    """
    kiln, outage = _reline_due_kiln_with_outage(api)

    completed = validate_success(
        api.complete_outage(outage["id"], {"refractory_replaced": True}, ENGINEER_HEADERS)
    )
    assert completed["status"] == "COMPLETED"
    assert completed["refractory_replaced"] is True

    relined = validate_success(api.get_kiln(kiln["id"], ENGINEER_HEADERS))
    assert relined["refractory_hours_since_reline"] == 0
    assert relined["availability_state"] == "AVAILABLE"
