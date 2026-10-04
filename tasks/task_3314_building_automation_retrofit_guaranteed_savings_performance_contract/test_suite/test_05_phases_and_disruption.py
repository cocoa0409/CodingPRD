"""Work phase windows, disruption budgets, and measure installation gates."""
from test_helpers import (
    ApiErrorId,
    construction_contract,
    create_disruption_payload,
    create_phase_payload,
    eng_headers,
    executed_contract,
    make_actor_ids,
    own_headers,
    reset_clock,
    set_clock,
    validate_error,
    validate_success,
)


def test_phase_window_overlap_half_open_semantics(api):
    """PRD §3.4: "Windows are half-open: one window ending exactly when
    another begins does not overlap, and is allowed; any true overlap is
    rejected with `ERR_PHASE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/phase_window_overlap_half_open_semantics
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f = executed_contract(eng_id, owner_id)
    cid = contract["id"]
    phase_a = validate_success(
        api.create_phase(cid, create_phase_payload(phase_label="A"), eng_headers(eng_id)),
        201,
    )
    validate_success(api.mobilize_phase(cid, phase_a["id"], eng_headers(eng_id)))
    phase_b = validate_success(
        api.create_phase(cid, create_phase_payload(
            phase_label="Overlap B", window_start="2026-09-10T00:00:00Z",
            window_end="2026-09-15T00:00:00Z", disruption_budget_hours=10),
                         eng_headers(eng_id)),
        201,
    )
    phase_c = validate_success(
        api.create_phase(cid, create_phase_payload(
            phase_label="Adjacent C", window_start="2026-09-20T00:00:00Z",
            window_end="2026-09-25T00:00:00Z", disruption_budget_hours=10),
                         eng_headers(eng_id)),
        201,
    )
    response = api.mobilize_phase(cid, phase_b["id"], eng_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_PHASE_WINDOW_OVERLAP.value, 409)
    mobilized = validate_success(
        api.mobilize_phase(cid, phase_c["id"], eng_headers(eng_id))
    )
    assert mobilized["status"] == "MOBILIZED"


def test_phase_window_overlap_rechecks_against_in_progress_phases(api):
    """PRD §3.4: "provided its window does not overlap any other `MOBILIZED`
    or `IN_PROGRESS` phase window of the same contract."

    Design: Difficulty/resource_temporal_overlap/phase_window_overlap_half_open_semantics
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f = executed_contract(eng_id, owner_id)
    cid = contract["id"]
    phase_a = validate_success(
        api.create_phase(cid, create_phase_payload(phase_label="A"), eng_headers(eng_id)),
        201,
    )
    validate_success(api.mobilize_phase(cid, phase_a["id"], eng_headers(eng_id)))
    # The clock (2026-09-01) has reached the default window_start, so the
    # mobilized phase can move to IN_PROGRESS while the contract is still
    # EXECUTED — mobilize remains available for the overlap re-check below.
    phase_a = validate_success(api.start_phase(cid, phase_a["id"], eng_headers(eng_id)))
    assert phase_a["status"] == "IN_PROGRESS"
    phase_b = validate_success(
        api.create_phase(cid, create_phase_payload(
            phase_label="Overlap", window_start="2026-09-05T00:00:00Z",
            window_end="2026-09-30T00:00:00Z", disruption_budget_hours=10),
                         eng_headers(eng_id)),
        201,
    )
    response = api.mobilize_phase(cid, phase_b["id"], eng_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_PHASE_WINDOW_OVERLAP.value, 409)


def test_disruption_occurs_at_window_end_instant_rejected(api):
    """PRD §3.4: "the `occurred_at` must fall inside the phase window — at or
    after `window_start` and strictly before `window_end` — else
    `ERR_DISRUPTION_OUTSIDE_WINDOW` (HTTP 422)"

    Design: Difficulty/resource_temporal_overlap/disruption_occurs_at_window_end_instant_rejected
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, phase = construction_contract(
        eng_id, owner_id, start_phase=True
    )
    cid, pid = contract["id"], phase["id"]
    start_edge = validate_success(
        api.create_disruption(cid, pid, create_disruption_payload(
            occurred_at="2026-09-01T00:00:00Z", hours=2, cause="start-edge"),
                              eng_headers(eng_id)),
        201,
    )
    assert start_edge.get("id")
    response = api.create_disruption(cid, pid, create_disruption_payload(
        occurred_at="2026-09-20T00:00:00Z", hours=2, cause="end-edge"),
                                     eng_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_DISRUPTION_OUTSIDE_WINDOW.value, 422)
    phase = validate_success(api.get_phase(cid, pid, eng_headers(eng_id)))
    assert phase["consumed_disruption_hours"] == 2


def test_disruption_outside_window_before_start_rejected(api):
    """PRD §3.4: "the `occurred_at` must fall inside the phase window — at or
    after `window_start` and strictly before `window_end` — else
    `ERR_DISRUPTION_OUTSIDE_WINDOW` (HTTP 422)"

    Design: Difficulty/resource_temporal_overlap/disruption_occurs_at_window_end_instant_rejected
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, phase = construction_contract(
        eng_id, owner_id, start_phase=True
    )
    cid, pid = contract["id"], phase["id"]
    response = api.create_disruption(cid, pid, create_disruption_payload(
        occurred_at="2026-08-31T23:00:00Z", hours=2, cause="too early"),
                                     eng_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_DISRUPTION_OUTSIDE_WINDOW.value, 422)
    phase = validate_success(api.get_phase(cid, pid, eng_headers(eng_id)))
    assert phase["consumed_disruption_hours"] == 0


def test_disruption_budget_consumption_at_exact_limit(api):
    """PRD §3.4: "the log must not push the phase over budget — if the
    phase's `consumed_disruption_hours` plus the new `hours` would exceed
    `disruption_budget_hours`, the log is rejected with
    `ERR_DISRUPTION_BUDGET_EXCEEDED` (HTTP 422). An accepted log adds its
    `hours` to `consumed_disruption_hours`."

    Design: Difficulty/boundary_precision_check/disruption_budget_consumption_at_exact_limit
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, phase = construction_contract(
        eng_id, owner_id, start_phase=True,
        phase_overrides={"disruption_budget_hours": 8},
    )
    cid, pid = contract["id"], phase["id"]
    validate_success(
        api.create_disruption(cid, pid, create_disruption_payload(
            occurred_at="2026-09-02T10:00:00Z", hours=3, cause="roof crane"),
                              eng_headers(eng_id)),
        201,
    )
    validate_success(
        api.create_disruption(cid, pid, create_disruption_payload(
            occurred_at="2026-09-03T10:00:00Z", hours=5, cause="AHU swap"),
                              eng_headers(eng_id)),
        201,
    )
    phase = validate_success(api.get_phase(cid, pid, eng_headers(eng_id)))
    assert phase["consumed_disruption_hours"] == 8
    response = api.create_disruption(cid, pid, create_disruption_payload(
        occurred_at="2026-09-04T10:00:00Z", hours=1, cause="fire alarm tie-in"),
                                     eng_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_DISRUPTION_BUDGET_EXCEEDED.value, 422)
    phase = validate_success(api.get_phase(cid, pid, eng_headers(eng_id)))
    assert phase["consumed_disruption_hours"] == 8


def test_disruption_budget_allows_consumed_equal_to_budget(api):
    """PRD §3.4: "if the phase's `consumed_disruption_hours` plus the new
    `hours` would exceed `disruption_budget_hours`, the log is rejected with
    `ERR_DISRUPTION_BUDGET_EXCEEDED` (HTTP 422)"

    Design: Difficulty/boundary_precision_check/disruption_budget_consumption_at_exact_limit
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, phase = construction_contract(
        eng_id, owner_id, start_phase=True,
        phase_overrides={"disruption_budget_hours": 8},
    )
    cid, pid = contract["id"], phase["id"]
    # Exactly at budget: 8 == 8 does not exceed, so it is accepted.
    validate_success(
        api.create_disruption(cid, pid, create_disruption_payload(
            occurred_at="2026-09-02T10:00:00Z", hours=8, cause="full-day outage"),
                              eng_headers(eng_id)),
        201,
    )
    phase = validate_success(api.get_phase(cid, pid, eng_headers(eng_id)))
    assert phase["consumed_disruption_hours"] == 8


def test_state_vs_business_safety_on_disruption_log(api):
    """PRD §2.6: "then whether the target entity's current state even permits
    the requested transition, and only then the business rules"
    PRD §3.4: "While a phase is in progress, the engineer logs occupant
    disruptions against it"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_disruption_log
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f = executed_contract(eng_id, owner_id)
    cid = contract["id"]
    phase = validate_success(
        api.create_phase(cid, create_phase_payload(
            phase_label="Small Window", disruption_budget_hours=4),
                         eng_headers(eng_id)),
        201,
    )
    # PLANNED phase + over-budget payload: the state gate fires first.
    response = api.create_disruption(cid, phase["id"], create_disruption_payload(
        occurred_at="2026-09-10T10:00:00Z", hours=10, cause="crane lift"),
                                     eng_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_PHASE_NOT_IN_PROGRESS.value, 409)
    phase = validate_success(api.get_phase(cid, phase["id"], eng_headers(eng_id)))
    assert phase["consumed_disruption_hours"] == 0


def test_disruption_on_planned_phase_rejected_with_state_error(api):
    """PRD §3.4: "While a phase is in progress, the engineer logs occupant
    disruptions against it with an `occurred_at` instant, a whole-number
    `hours` greater than zero, and a free-text `cause`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_disruption_log
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f = executed_contract(eng_id, owner_id)
    cid = contract["id"]
    phase = validate_success(
        api.create_phase(cid, create_phase_payload(disruption_budget_hours=40),
                         eng_headers(eng_id)),
        201,
    )
    # Within budget and inside the window, but the phase is PLANNED.
    response = api.create_disruption(cid, phase["id"], create_disruption_payload(
        occurred_at="2026-09-10T10:00:00Z", hours=2, cause="staging"),
                                     eng_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_PHASE_NOT_IN_PROGRESS.value, 409)


def test_work_phase_suspend_resume_loop_with_window_guards(api):
    """PRD §3.4: "An owner may instead suspend an in-progress phase, moving
    it to `SUSPENDED`, and the engineer may later start it again: resuming
    from `SUSPENDED` (`ERR_PHASE_NOT_RESUMABLE` if it is not suspended)
    requires the logical clock to still be before `window_end`, else
    `ERR_PHASE_WINDOW_CLOSED`."

    Design: Difficulty/non_linear_state_machine/work_phase_suspend_resume_loop_with_window_guards
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, phase = construction_contract(
        eng_id, owner_id, start_phase=True
    )
    cid, pid = contract["id"], phase["id"]
    suspended = validate_success(api.suspend_phase(cid, pid, own_headers(owner_id)))
    assert suspended["status"] == "SUSPENDED"
    resumed = validate_success(api.start_phase(cid, pid, eng_headers(eng_id)))
    assert resumed["status"] == "IN_PROGRESS"
    suspended = validate_success(api.suspend_phase(cid, pid, own_headers(owner_id)))
    assert suspended["status"] == "SUSPENDED"
    set_clock("2026-09-21T00:00:00Z")  # past window_end 2026-09-20
    response = api.start_phase(cid, pid, eng_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_PHASE_WINDOW_CLOSED.value, 409)
    phase = validate_success(api.get_phase(cid, pid, eng_headers(eng_id)))
    assert phase["status"] == "SUSPENDED"


def test_phase_resume_cycle_is_repeatable_before_window_end(api):
    """PRD §3.4: "An owner may instead suspend an in-progress phase, moving
    it to `SUSPENDED`, and the engineer may later start it again"

    Design: Difficulty/non_linear_state_machine/work_phase_suspend_resume_loop_with_window_guards
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, phase = construction_contract(
        eng_id, owner_id, start_phase=True
    )
    cid, pid = contract["id"], phase["id"]
    for _ in range(2):
        suspended = validate_success(api.suspend_phase(cid, pid, own_headers(owner_id)))
        assert suspended["status"] == "SUSPENDED"
        resumed = validate_success(api.start_phase(cid, pid, eng_headers(eng_id)))
        assert resumed["status"] == "IN_PROGRESS"


def test_measure_install_gated_by_work_phase_and_contract_states(api):
    """PRD §3.4: "An engineer installs an `INCLUDED` measure
    (`ERR_MEASURE_NOT_INCLUDED` otherwise) only while the contract is in
    `CONSTRUCTION` (`ERR_CONTRACT_NOT_IN_CONSTRUCTION`) and only while at
    least one `IN_PROGRESS` phase of the contract has a window containing the
    logical clock — if no active phase window covers the current instant, the
    install is rejected with `ERR_NO_ACTIVE_PHASE_WINDOW`."

    Design: Difficulty/cross_entity_state_dependency/measure_install_gated_by_work_phase_and_contract_states
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    # Phase MOBILIZED but never started: no IN_PROGRESS window covers the clock.
    contract, _b, bundle, measures, _f, phase = construction_contract(
        eng_id, owner_id, start_phase=False
    )
    cid, bid, mid = contract["id"], bundle["id"], measures[0]["id"]
    response = api.install_measure(cid, bid, mid, eng_headers(eng_id))
    validate_error(response, ApiErrorId.ERR_NO_ACTIVE_PHASE_WINDOW.value, 409)
    measure = validate_success(api.get_measure(cid, bid, mid, eng_headers(eng_id)))
    assert measure["status"] == "INCLUDED"
    validate_success(api.start_phase(cid, phase["id"], eng_headers(eng_id)))
    installed = validate_success(
        api.install_measure(cid, bid, mid, eng_headers(eng_id))
    )
    assert installed["status"] == "INSTALLED"


def test_measure_install_requires_in_progress_phase_window(api):
    """PRD §3.4: "Installation moves the measure to `INSTALLED`."
    PRD §3.4: "only while at least one `IN_PROGRESS` phase of the contract
    has a window containing the logical clock"

    Design: Difficulty/cross_entity_state_dependency/measure_install_gated_by_work_phase_and_contract_states
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, bundle, measures, _f, phase = construction_contract(
        eng_id, owner_id, start_phase=True
    )
    cid, bid, mid = contract["id"], bundle["id"], measures[0]["id"]
    installed = validate_success(
        api.install_measure(cid, bid, mid, eng_headers(eng_id))
    )
    assert installed["status"] == "INSTALLED"


def test_logical_clock_default_is_fixed_instant(api):
    """PRD §2.5: "The logical clock starts at exactly `2026-09-01T00:00:00Z`
    before any call has set it, and it never falls back to wall-clock time."
    PRD §3.4: "Starting a phase moves it from `MOBILIZED` to `IN_PROGRESS`
    and requires the logical clock to have reached `window_start`"

    Design: Corner/complexity_layers/logical_clock_default_is_fixed_instant
    """
    # No clock call anywhere in this test: the documented default applies.
    eng_id, owner_id = make_actor_ids()
    contract, _b, _bd, _m, _f, phase = construction_contract(
        eng_id, owner_id, start_phase=False
    )
    cid, pid = contract["id"], phase["id"]
    started = validate_success(api.start_phase(cid, pid, eng_headers(eng_id)))
    assert started["status"] == "IN_PROGRESS"


def test_measure_verify_from_included_rejected(api):
    """PRD §3.4: "An `OwnerRep` then verifies an installed measure
    (`ERR_MEASURE_NOT_INSTALLED` otherwise), moving it to `VERIFIED`"

    Design: Corner/state_machines/measure_verify_from_included_rejected
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    contract, _b, bundle, measures, _f, _ph = construction_contract(
        eng_id, owner_id, start_phase=False
    )
    cid, bid, mid = contract["id"], bundle["id"], measures[0]["id"]
    response = api.verify_measure(cid, bid, mid, own_headers(owner_id))
    validate_error(response, ApiErrorId.ERR_MEASURE_NOT_INSTALLED.value, 409)
    measure = validate_success(api.get_measure(cid, bid, mid, eng_headers(eng_id)))
    assert measure["status"] == "INCLUDED"


def test_bundle_auto_completes_when_last_measure_verified(api):
    """PRD §3.4: "when the verifying measure leaves a bundle with no
    remaining non-`EXCLUDED` measure unverified, that bundle automatically
    completes, moving from `ACTIVE` to `COMPLETE`."

    Design: Corner/state_machines/bundle_auto_completes_when_last_measure_verified
    """
    reset_clock()
    eng_id, owner_id = make_actor_ids()
    measures_spec = [
        {"measure_type": "LIGHTING", "installed_cost_cents": 600000,
         "annual_savings_cents": 300000},
        {"measure_type": "WATER", "installed_cost_cents": 100000,
         "annual_savings_cents": 50000},
    ]
    from test_helpers import create_measure_payload
    contract, _b, bundle, measures, _f, phase = construction_contract(
        eng_id, owner_id, start_phase=True,
        measures=[create_measure_payload(**m) for m in measures_spec],
    )
    cid, bid = contract["id"], bundle["id"]
    validate_success(
        api.install_measure(cid, bid, measures[0]["id"], eng_headers(eng_id))
    )
    validate_success(
        api.verify_measure(cid, bid, measures[0]["id"], own_headers(owner_id))
    )
    validate_success(
        api.install_measure(cid, bid, measures[1]["id"], eng_headers(eng_id))
    )
    verified = validate_success(
        api.verify_measure(cid, bid, measures[1]["id"], own_headers(owner_id))
    )
    assert verified["status"] == "VERIFIED"
    bundle = validate_success(api.get_bundle(cid, bid, eng_headers(eng_id)))
    assert bundle["status"] == "COMPLETE"
