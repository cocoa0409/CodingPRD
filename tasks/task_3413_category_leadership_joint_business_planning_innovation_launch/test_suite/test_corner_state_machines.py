"""Corner queue — lifecycle state machines: invalid transitions, mover mapping,
terminal lockdowns, and state-coupled side effects.

Each test translates one corner-design `state_machines` instance and cites the
PRD sentence that pins the asserted rule.
"""
from test_helpers import (
    ApiErrorId,
    create_accepted_analysis,
    create_activate_payload,
    create_analysis_decide_payload,
    create_deduction_resolve_payload,
    create_forecast_commit_payload,
    create_launch_with_phases,
    create_launched_launch,
    create_negotiate_payload,
    create_penciled_event,
    create_phase_patch_payload,
    create_plan_decide_payload,
    create_proposed_shelf_rec,
    create_published_forecast,
    create_verify_payload,
    drive_plan_to_exhaustion,
    file_deduction,
    setup_accepted_plan,
    setup_activated_plan,
    setup_proposed_plan,
    validate_error,
    validate_success,
)


def test_plan_negotiate_from_accepted_returns_invalid_state(api, manufacturer_planner_headers):
    """PRD §3.1: "While the plan is `PROPOSED`, the `RetailerBuyer` of the plan's own retailer may counter: the call carries a new `growth_target_pct`, and on success the plan's `growth_target_pct` is replaced by the proposed value, `negotiation_round` climbs by 1, and the plan's `version` increments as the plan moves `PROPOSED → COUNTERED`."
    PRD §2.9: "State fit: the target entity sits in a from-state that the requested transition permits, else `ERR_INVALID_STATE` (HTTP 409)."

    Negotiation is defined only from PROPOSED/COUNTERED; against an ACCEPTED
    plan the counter fails ERR_INVALID_STATE and the plan is left untouched.

    Design: Corner/state_machines/plan_negotiate_from_accepted_returns_invalid_state
    """
    scenario = setup_accepted_plan()
    plan_id = scenario["plan"]["id"]

    validate_error(
        api.negotiate_plan(plan_id, create_negotiate_payload(9), scenario["buyer_headers"]),
        ApiErrorId.ERR_INVALID_STATE,
    )

    plan = validate_success(api.get_plan(plan_id, manufacturer_planner_headers), 200)
    assert plan["status"] == "ACCEPTED", f"plan must remain ACCEPTED, got {plan['status']}"
    assert plan["negotiation_round"] == 1, (
        f"a rejected counter must not move the round, got {plan['negotiation_round']}"
    )


def test_plan_decide_wrong_actor_returns_not_your_move(api, manufacturer_planner_headers):
    """PRD §3.1: "From `PROPOSED`, only the plan's own `RetailerBuyer` may decide: a `decision` of `ACCEPT` moves the plan `PROPOSED → ACCEPTED`, while `REJECT` moves it to the terminal `REJECTED`."
    PRD §2.9: "Mover mapping: negotiation and decision calls honor whose move it is — from `PROPOSED` only the `RetailerBuyer` may move, from `COUNTERED` only the `ManufacturerPlanner` — else `ERR_NOT_YOUR_MOVE` (HTTP 403)."

    From PROPOSED the move belongs to the retailer; a ManufacturerPlanner
    decide fails ERR_NOT_YOUR_MOVE (403) and the plan stays PROPOSED.

    Design: Corner/state_machines/plan_decide_wrong_actor_returns_not_your_move
    """
    scenario = setup_proposed_plan()
    plan_id = scenario["plan"]["id"]

    validate_error(
        api.decide_plan(plan_id, create_plan_decide_payload("ACCEPT"), manufacturer_planner_headers),
        ApiErrorId.ERR_NOT_YOUR_MOVE,
    )

    plan = validate_success(api.get_plan(plan_id, manufacturer_planner_headers), 200)
    assert plan["status"] == "PROPOSED", f"plan must remain PROPOSED, got {plan['status']}"


def test_plan_expired_rejects_further_decide_returns_already_terminal(api, manufacturer_planner_headers):
    """PRD §3.1: "The exchange is capped at a round budget of 6: when a negotiation move is attempted while the plan's `negotiation_round` has already reached 6, the request is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP 409), and in the very same failed request the plan auto-transitions to `EXPIRED` with its `version` incremented — the exhaustion error and the expiration are inseparable, whether the plan was sitting `PROPOSED` or `COUNTERED`."
    PRD §2.10: "A plan in `REJECTED` or `EXPIRED`, an event in `CANCELLED`, an analysis in `ACCEPTED` or `RETURNED`, a shelf recommendation in `REJECTED`, `VERIFIED`, `STALLED`, or `WITHDRAWN`, a launch in `REVIEWED` or `DELISTED`, a deduction in `SETTLED`, `REJECTED`, or `WRITTEN_OFF`, and a review in `FINALIZED` all refuse every further transition with `ERR_ALREADY_TERMINAL`."

    The move that spends the last negotiation round fails
    ERR_NEGOTIATION_ROUNDS_EXHAUSTED and expires the plan in the same breath;
    a decide attempted afterwards fails ERR_ALREADY_TERMINAL (terminal
    lockdown is checked before mover mapping).

    Design: Corner/state_machines/plan_expired_rejects_further_negotiate_returns_already_terminal
    """
    scenario = setup_proposed_plan()
    plan_id = scenario["plan"]["id"]

    exhausted = drive_plan_to_exhaustion(plan_id, scenario["retailer"]["id"])
    validate_error(exhausted, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED)

    validate_error(
        api.decide_plan(plan_id, create_plan_decide_payload("ACCEPT"), scenario["buyer_headers"]),
        ApiErrorId.ERR_ALREADY_TERMINAL,
    )

    plan = validate_success(api.get_plan(plan_id, manufacturer_planner_headers), 200)
    assert plan["status"] == "EXPIRED", f"plan must remain EXPIRED, got {plan['status']}"


def test_analysis_decide_twice_returns_already_terminal(api):
    """PRD §3.3: "The `RetailerBuyer` of the plan's retailer decides it: a `decision` of `ACCEPT` moves it `SUBMITTED → ACCEPTED`, a `decision` of `RETURN` moves it `SUBMITTED → RETURNED`, and either way the record's `version` increments. Both outcomes are terminal; `RETURNED` in particular closes the record for good — a reworked analysis enters the system as a brand-new submission rather than a resurrection."
    PRD §2.10: "A plan in `REJECTED` or `EXPIRED`, an event in `CANCELLED`, an analysis in `ACCEPTED` or `RETURNED`, a shelf recommendation in `REJECTED`, `VERIFIED`, `STALLED`, or `WITHDRAWN`, a launch in `REVIEWED` or `DELISTED`, a deduction in `SETTLED`, `REJECTED`, or `WRITTEN_OFF`, and a review in `FINALIZED` all refuse every further transition with `ERR_ALREADY_TERMINAL`."

    An ACCEPTED analysis is terminal; a second decide on it fails
    ERR_ALREADY_TERMINAL.

    Design: Corner/state_machines/analysis_decide_twice_returns_already_terminal
    """
    scenario = setup_proposed_plan()
    analysis = create_accepted_analysis(scenario["plan"]["id"], scenario["retailer"]["id"])

    validate_error(
        api.decide_category_analysis(
            analysis["id"],
            create_analysis_decide_payload("RETURN"),
            scenario["buyer_headers"],
        ),
        ApiErrorId.ERR_ALREADY_TERMINAL,
    )


def test_shelf_recommendation_superseded_on_new_create(api, category_advisor_headers):
    """PRD §3.4: "The OCC rule exists because of what a successful create does to the incumbent: the plan's currently `PROPOSED` recommendation, if one exists, is auto-superseded to `WITHDRAWN` with its own `version` incremented, and the plan's `version` itself increments by 1, so the next advisor must read afresh before recommending again."

    Creating a second recommendation against the same plan auto-WITHDRAWNs
    the incumbent PROPOSED one; the newcomer is born PROPOSED.

    Design: Corner/state_machines/shelf_superseded_on_new_create
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    create_accepted_analysis(plan_id, scenario["retailer"]["id"])
    first = create_proposed_shelf_rec(plan_id, title="Reset A", space_change_pct=5)

    second = create_proposed_shelf_rec(plan_id, title="Reset B", space_change_pct=-10)

    recs = validate_success(
        api.list_shelf_recommendations(plan_id, category_advisor_headers), 200
    )
    by_id = {rec["id"]: rec for rec in recs}
    assert by_id[first["id"]]["status"] == "WITHDRAWN", (
        f"the incumbent must be auto-superseded to WITHDRAWN, got {by_id[first['id']]['status']}"
    )
    assert by_id[second["id"]]["status"] == "PROPOSED", (
        f"the newcomer must be born PROPOSED, got {by_id[second['id']]['status']}"
    )


def test_shelf_verify_from_proposed_returns_invalid_state(api, category_advisor_headers):
    """PRD §3.4: "Verification is the `CategoryAdvisor`'s audit, and its three checks fire in a fixed order. First, the recommendation must actually be `IMPLEMENTING` — verifying anything else fails with `ERR_INVALID_STATE`."

    Verifying a recommendation the retailer has not yet accepted fails the
    first ordered check with ERR_INVALID_STATE; the rec stays PROPOSED.

    Design: Corner/state_machines/shelf_verify_from_proposed_returns_invalid_state
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    create_accepted_analysis(plan_id, scenario["retailer"]["id"])
    rec = create_proposed_shelf_rec(plan_id)

    validate_error(
        api.verify_shelf_recommendation(rec["id"], create_verify_payload(100), category_advisor_headers),
        ApiErrorId.ERR_INVALID_STATE,
    )

    recs = validate_success(
        api.list_shelf_recommendations(plan_id, category_advisor_headers), 200
    )
    by_id = {item["id"]: item for item in recs}
    assert by_id[rec["id"]]["status"] == "PROPOSED", (
        f"a failed verification must not move the rec, got {by_id[rec['id']]['status']}"
    )


def test_launch_launch_twice_returns_invalid_state(api, manufacturer_planner_headers):
    """PRD §3.5: "A successful execution moves the launch `PLANNING → LAUNCHED`, stamps `launched_at` from the logical clock, and increments the launch's `version`."
    PRD §2.9: "State fit: the target entity sits in a from-state that the requested transition permits, else `ERR_INVALID_STATE` (HTTP 409)."

    The launch transition is defined only from PLANNING (LAUNCHED is not a
    terminal state — §2.10 names REVIEWED/DELISTED — so state fit, not
    terminality, fires): a second launch call fails ERR_INVALID_STATE.

    Design: Corner/state_machines/launch_launch_twice_returns_invalid_state
    """
    scenario = setup_activated_plan()
    launch, _phases = create_launched_launch(scenario["plan"]["id"])
    assert launch["status"] == "LAUNCHED"

    validate_error(
        api.execute_launch(launch["id"], manufacturer_planner_headers),
        ApiErrorId.ERR_INVALID_STATE,
    )


def test_phase_patch_after_gate_passed_returns_phase_locked(api, manufacturer_planner_headers):
    """PRD §3.5: "A patch is only lawful while the phase is `PENDING` or `GATE_FAILED` and the launch is still `PLANNING`; anything else is refused with `ERR_PHASE_LOCKED` (HTTP 409)."

    A GATE_PASSED phase is locked: a further PATCH fails ERR_PHASE_LOCKED and
    the stored inputs are unchanged.

    Design: Corner/state_machines/phase_patch_after_gate_passed_returns_phase_locked
    """
    scenario = setup_activated_plan()
    launch, phases = create_launch_with_phases(
        scenario["plan"]["id"], launch_date="2027-03-01T00:00:00Z"
    )
    phase_one = phases[0]
    validate_success(
        api.patch_launch_phase(
            launch["id"],
            phase_one["id"],
            create_phase_patch_payload(distribution_target_pct=10, capacity_cases=100),
            manufacturer_planner_headers,
        ),
        200,
    )
    passed = validate_success(
        api.evaluate_launch_phase(launch["id"], phase_one["id"], manufacturer_planner_headers), 200
    )
    assert passed["status"] == "GATE_PASSED", (
        f"Setup failed: phase 1 must pass its gate, got {passed['status']}"
    )

    validate_error(
        api.patch_launch_phase(
            launch["id"],
            phase_one["id"],
            {"distribution_target_pct": 20},
            manufacturer_planner_headers,
        ),
        ApiErrorId.ERR_PHASE_LOCKED,
    )

    current = validate_success(
        api.list_launch_phases(launch["id"], manufacturer_planner_headers), 200
    )
    phase_one_now = next(p for p in current if p["phase_index"] == 1)
    assert phase_one_now["status"] == "GATE_PASSED"
    assert phase_one_now["distribution_target_pct"] == 10, (
        f"a locked phase must keep its stored inputs, got {phase_one_now['distribution_target_pct']}"
    )


def test_phase_evaluate_out_of_order_fails_gate(api, manufacturer_planner_headers):
    """PRD §3.5: "A phase passes its gate — moving `PENDING → GATE_PASSED` — exactly when the launch is still `PLANNING`, every lower-indexed phase of the launch has already passed (a condition vacuously true for the first phase), its `distribution_target_pct` is greater than 0, and its `capacity_cases` is greater than 0."
    PRD §3.5: "If the launch is still `PLANNING` but any of the gate's own conditions fails — a lower-indexed phase not yet passed, a zero distribution target, or zero capacity — the phase moves `PENDING → GATE_FAILED` instead: the evaluation itself always succeeds as a call; it is the gate that fails."
    PRD §3.5: "A successful patch applies the field updates, returns a `GATE_FAILED` phase to `PENDING` (a `PENDING` phase simply stays `PENDING`), recomputes the launch's `budget_remaining_cents` as the total budget minus the sum of phase spends, refreshes both distribution projections, and increments the phase's `version`."

    Evaluating phase 2 while phase 1 is still PENDING is a successful call
    whose outcome is GATE_FAILED; once phase 1 has passed and phase 2 is
    patched back to PENDING, re-evaluation passes — proving the sequencing
    precondition.

    Design: Corner/state_machines/phase_evaluate_out_of_order_fails_gate
    """
    scenario = setup_activated_plan()
    launch, phases = create_launch_with_phases(
        scenario["plan"]["id"], launch_date="2027-03-01T00:00:00Z"
    )
    phase_one, phase_two = phases[0], phases[1]
    validate_success(
        api.patch_launch_phase(
            launch["id"],
            phase_one["id"],
            create_phase_patch_payload(distribution_target_pct=10, capacity_cases=100),
            manufacturer_planner_headers,
        ),
        200,
    )
    validate_success(
        api.patch_launch_phase(
            launch["id"],
            phase_two["id"],
            create_phase_patch_payload(distribution_target_pct=20, capacity_cases=200),
            manufacturer_planner_headers,
        ),
        200,
    )

    out_of_order = validate_success(
        api.evaluate_launch_phase(launch["id"], phase_two["id"], manufacturer_planner_headers), 200
    )
    assert out_of_order["status"] == "GATE_FAILED", (
        f"phase 2 with phase 1 unpassed must fail its gate (not error), got {out_of_order['status']}"
    )

    first_pass = validate_success(
        api.evaluate_launch_phase(launch["id"], phase_one["id"], manufacturer_planner_headers), 200
    )
    assert first_pass["status"] == "GATE_PASSED"

    revised = validate_success(
        api.patch_launch_phase(
            launch["id"],
            phase_two["id"],
            create_phase_patch_payload(distribution_target_pct=20),
            manufacturer_planner_headers,
        ),
        200,
    )
    assert revised["status"] == "PENDING", (
        f"patching a GATE_FAILED phase must return it to PENDING, got {revised['status']}"
    )

    re_evaluated = validate_success(
        api.evaluate_launch_phase(launch["id"], phase_two["id"], manufacturer_planner_headers), 200
    )
    assert re_evaluated["status"] == "GATE_PASSED", (
        f"phase 2 must pass once phase 1 has passed, got {re_evaluated['status']}"
    )


def test_forecast_commit_on_superseded_returns_not_published(api):
    """PRD §3.7: "The commit requires the forecast to be both `PUBLISHED` and `UNCOMMITTED`; attempting it against a superseded or already-committed forecast fails with `ERR_FORECAST_NOT_PUBLISHED` (HTTP 409)."
    PRD §3.7: "when a planner publishes a new forecast for a plan and `week_start` that already has a `PUBLISHED` forecast, the incumbent auto-transitions to `SUPERSEDED` with its `version` incremented — yet its `commit_status` is preserved untouched, so a committed week stays committed even after a fresher baseline replaces it."

    A fresh forecast for the same week supersedes the incumbent; committing
    volume against the SUPERSEDED forecast fails ERR_FORECAST_NOT_PUBLISHED.

    Design: Corner/state_machines/forecast_commit_on_superseded_returns_not_published
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    first = create_published_forecast(plan_id, week_start="2027-03-01T00:00:00Z", baseline_cases=1000)
    create_published_forecast(plan_id, week_start="2027-03-01T00:00:00Z", baseline_cases=1200)

    validate_error(
        api.commit_forecast(
            first["id"], create_forecast_commit_payload(1100), scenario["buyer_headers"]
        ),
        ApiErrorId.ERR_FORECAST_NOT_PUBLISHED,
    )


def test_deduction_reject_from_received_returns_invalid_state(api, finance_analyst_headers):
    """PRD §3.6: "`REJECT` — lawful only from `DISPUTED` — moves the claim to `REJECTED` with no fund movement at all."
    PRD §3.6: "Every resolution increments the deduction's `version`; an action attempted from a state that does not permit it fails with `ERR_INVALID_STATE`, and the terminal trio of `SETTLED`, `REJECTED`, and `WRITTEN_OFF` refuses everything with `ERR_ALREADY_TERMINAL`."

    Rejecting a claim that was never disputed fails ERR_INVALID_STATE; the
    deduction remains RECEIVED.

    Design: Corner/state_machines/deduction_reject_from_received_returns_invalid_state
    """
    scenario = setup_activated_plan()
    fund_id = scenario["fund"]["id"]
    deduction = file_deduction(
        fund_id, scenario["retailer"]["id"], "CL-1", bucket="EDLP", amount_cents=2500
    )
    assert deduction["status"] == "RECEIVED"

    validate_error(
        api.resolve_deduction(
            deduction["id"], create_deduction_resolve_payload("REJECT"), finance_analyst_headers
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )

    deductions = validate_success(api.list_deductions(fund_id, finance_analyst_headers), 200)
    by_id = {item["id"]: item for item in deductions}
    assert by_id[deduction["id"]]["status"] == "RECEIVED", (
        f"a state-fit rejection must not move the claim, got {by_id[deduction['id']]['status']}"
    )


def test_event_cancel_twice_returns_already_terminal(api, manufacturer_planner_headers):
    """PRD §3.2: "Lock-then-cancel is thus the compensating pair that keeps the fund's reservation invariant exact, and `CANCELLED` is terminal."
    PRD §2.10: "A plan in `REJECTED` or `EXPIRED`, an event in `CANCELLED`, an analysis in `ACCEPTED` or `RETURNED`, a shelf recommendation in `REJECTED`, `VERIFIED`, `STALLED`, or `WITHDRAWN`, a launch in `REVIEWED` or `DELISTED`, a deduction in `SETTLED`, `REJECTED`, or `WRITTEN_OFF`, and a review in `FINALIZED` all refuse every further transition with `ERR_ALREADY_TERMINAL`."

    A CANCELLED event is terminal: a second cancel fails ERR_ALREADY_TERMINAL.

    Design: Corner/state_machines/event_cancel_twice_returns_already_terminal
    """
    scenario = setup_activated_plan()
    event = create_penciled_event(scenario["plan"]["id"])
    cancelled = validate_success(api.cancel_event(event["id"], manufacturer_planner_headers), 200)
    assert cancelled["status"] == "CANCELLED"

    validate_error(
        api.cancel_event(event["id"], manufacturer_planner_headers),
        ApiErrorId.ERR_ALREADY_TERMINAL,
    )


def test_suspended_retailer_blocks_activation(api, manufacturer_planner_headers):
    """PRD §3.1: "Activation also demands that the plan's retailer still be `ACTIVE`; attempting it against a `SUSPENDED` retailer fails with `ERR_INVALID_STATE`."
    PRD §2.11: "Each activated plan owns exactly one trade fund, created at the moment of activation with every computed balance at zero."

    An ACCEPTED plan whose retailer is SUSPENDED cannot activate: the call
    fails ERR_INVALID_STATE and, the activation having failed, no trade fund
    is materialized for the plan.

    Design: Corner/state_machines/suspended_retailer_blocks_activation
    """
    scenario = setup_accepted_plan(retailer_overrides={"status": "SUSPENDED"})
    plan_id = scenario["plan"]["id"]
    assert scenario["retailer"]["status"] == "SUSPENDED"

    validate_error(
        api.activate_plan(plan_id, create_activate_payload(), manufacturer_planner_headers),
        ApiErrorId.ERR_INVALID_STATE,
    )

    funds = validate_success(
        api.list_funds(manufacturer_planner_headers, params={"plan_id": plan_id}), 200
    )
    assert funds == [], f"no fund may exist for a plan that never activated, got {funds!r}"
