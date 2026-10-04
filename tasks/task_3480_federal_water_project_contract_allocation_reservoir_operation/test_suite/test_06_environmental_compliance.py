"""Environmental constraints, compliance incidents, and the storage ledger.

Covers the half-open pulse-window overlap rule, the conditional-field shape
validation on constraint registration, the execute-anyway violation that
opens an incident and flips the reservoir onto COMPLIANCE_HOLD (gating the
next release), the parallel evolution of a delivery order's fulfillment and
compliance dimensions, the inflow-credit / execute-debit storage ledger, and
the constraint-registration role restriction - PRD §2.1, §2.10, §3.5 and
§3.6.
"""

from test_helpers import (
    ApiErrorId,
    ENVIRONMENTAL_OFFICER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    assert_instant,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

ENV = ENVIRONMENTAL_OFFICER_HEADERS


def test_delivery_parallel_axes_independent(api):
    """A delivery order created under a compliance hold starts FLAGGED; a
    partial delivery advances fulfillment while compliance stays FLAGGED, and
    resolving the incident clears compliance while fulfillment stays
    PARTIALLY_DELIVERED - the two dimensions evolve independently.

    PRD §3.6: "A created order starts with `delivered_af` at zero and
    `fulfillment_status` `CONFIRMED`; its `compliance_status` starts
    `FLAGGED` when the reservoir's `compliance_posture` is `COMPLIANCE_HOLD`
    at that moment, and `CLEARED` otherwise."
    PRD §3.6: "Recording never touches `compliance_status`, and a `FLAGGED`
    order can be recorded against exactly as a `CLEARED` one can: fulfillment
    and compliance are parallel dimensions that evolve independently."
    PRD §3.5: "When a resolution leaves no `OPEN` incidents on the reservoir,
    the reservoir's `compliance_posture` returns to `NORMAL`, and every
    delivery order whose `compliance_status` was `FLAGGED` returns to
    `CLEARED` with its fulfillment state untouched."

    Design: Difficulty/non_linear_state_machine/delivery_parallel_axes_independent
    """
    outcome = fixtures.setup_flagged_delivery(api, ordered_af=100, side="sr")
    world, order, incident = outcome["world"], outcome["order"], outcome["incident"]

    assert order["compliance_status"] == "FLAGGED", "created while the hold stands"
    assert order["fulfillment_status"] == "CONFIRMED"

    order = fixtures.record_delivery(api, order["id"], 40)
    assert order["fulfillment_status"] == "PARTIALLY_DELIVERED"
    assert order["compliance_status"] == "FLAGGED", "recording must not touch compliance"

    fixtures.resolve_incident(api, incident["id"], "FLOW_RESTORED")

    order = fixtures.get_delivery_order(api, order["id"])
    assert order["compliance_status"] == "CLEARED", "last-open resolution clears the flag"
    assert order["fulfillment_status"] == "PARTIALLY_DELIVERED", (
        "the compliance flip must not touch fulfillment"
    )
    assert order["delivered_af"] == 40

    reservoir = fixtures.get_reservoir(api, world["reservoir"]["id"])
    assert reservoir["compliance_posture"] == "NORMAL"


def test_violation_propagates_compliance_hold(api):
    """An executed release that violates a MIN_FLOW constraint still executes;
    the opened incident flips the reservoir to COMPLIANCE_HOLD, which gates
    the next release creation with 409 ERR_COMPLIANCE_HOLD.

    PRD §3.5: "for each constraint whose enforcement window contains the
    execution instant and which the release violates — a rate below its
    `required_min_cfs`, or above its `max_release_cfs` — the release still
    executes, and a compliance incident is opened recording the reservoir,
    the violated `constraint_id`, the offending `release_order_id`, and a
    `deficit_cfs` equal to `required_min_cfs` minus `release_cfs` for
    `MIN_FLOW` and `PULSE_FLOW` constraints, or `release_cfs` minus
    `max_release_cfs` for `MAX_RELEASE` constraints. Opening any incident
    sets the reservoir's `compliance_posture` to `COMPLIANCE_HOLD` and
    recomputes `open_incident_count`."
    PRD §3.5: "Creation is refused outright while the reservoir's
    `compliance_posture` is `COMPLIANCE_HOLD`, surfacing
    `ERR_COMPLIANCE_HOLD`."

    Design: Difficulty/transitive_cascade/violation_propagates_compliance_hold
    """
    outcome = fixtures.setup_compliance_violation(api)
    world, release, constraint, incident = (
        outcome["world"], outcome["release"], outcome["constraint"], outcome["incident"],
    )
    reservoir_id = world["reservoir"]["id"]

    assert release["status"] == "EXECUTED", "the violating release executes anyway"
    assert incident["status"] == "OPEN"
    assert incident["constraint_id"] == constraint["id"]
    assert incident["release_order_id"] == release["id"]
    assert incident["deficit_cfs"] == 100, "500 required - 400 released"

    incidents, meta = fixtures.list_incidents(api, reservoir_id=reservoir_id)
    assert meta["total_count"] == 1, "exactly one incident is opened"

    reservoir = world["reservoir"]  # refreshed by the fixture after the cascade
    assert reservoir["compliance_posture"] == "COMPLIANCE_HOLD"
    assert reservoir["open_incident_count"] == 1
    # The volume debit still applied: 3,000,000 - round(400*5*1.9835) = 2,996,033.
    assert reservoir["current_storage_af"] == 2_996_033

    validate_error(
        api.create_release_order(
            reservoir_id,
            factories.release_order_payload(
                purpose="POWER", release_cfs=900, duration_days=1,
                scheduled_start="2027-02-10T00:00:00Z",
            ),
            fixtures.RECLAMATION_OPERATOR_HEADERS,
        ),
        ApiErrorId.ERR_COMPLIANCE_HOLD,
    )


def test_pulse_window_adjacency_vs_overlap(api):
    """Half-open pulse windows: one starting exactly at another's end is
    adjacency and is accepted; any positive intersection is rejected 409
    ERR_PULSE_WINDOW_OVERLAP.

    PRD §3.5: "One structural rule applies at registration: a new
    `PULSE_FLOW` window that overlaps an existing `PULSE_FLOW` window on the
    same reservoir is rejected with `ERR_PULSE_WINDOW_OVERLAP`. Overlap means
    strict interval intersection — the existing window starts strictly before
    the new window ends, and the new window starts strictly before the
    existing window ends — so two pulse windows where one starts exactly when
    the other ends are merely adjacent and are allowed."

    Design: Difficulty/resource_temporal_overlap/pulse_window_adjacency_vs_overlap
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]

    first = fixtures.create_constraint(
        api, reservoir_id,
        factories.pulse_flow_constraint_payload(
            3_000, enforce_start="2027-01-10T00:00:00Z", enforce_end="2027-01-20T00:00:00Z",
        ),
    )
    assert first["requirement_type"] == "PULSE_FLOW"

    adjacent = validate_success(
        api.create_environmental_constraint(
            reservoir_id,
            factories.pulse_flow_constraint_payload(
                3_500, enforce_start="2027-01-20T00:00:00Z", enforce_end="2027-02-01T00:00:00Z",
            ),
            ENV,
        ),
        201,
    )
    assert adjacent["id"], "the window starting exactly at the first's end is merely adjacent"

    validate_error(
        api.create_environmental_constraint(
            reservoir_id,
            factories.pulse_flow_constraint_payload(
                4_000, species="STURGEON",
                enforce_start="2027-01-15T00:00:00Z", enforce_end="2027-01-25T00:00:00Z",
            ),
            ENV,
        ),
        ApiErrorId.ERR_PULSE_WINDOW_OVERLAP,
    )

    pulses, meta = validate_paginated(
        api.list_environmental_constraints(reservoir_id, fixtures.READ_HEADERS, {"requirement_type": "PULSE_FLOW"})
    )
    assert meta["total_count"] == 2 and len(pulses) == 2


def test_inflow_observation_credits_and_execute_debits_storage(api):
    """The storage ledger applies in event order: 3,000,000 initial plus a
    50,000 af measured inflow at creation minus the 19,835 af executed
    volume gives 3,030,165.

    PRD §2.10: "The reservoir's `current_storage_af` is a pure function of
    its ledger: the `initial_storage_af` plus every measured-inflow
    observation's `value` (credited at the moment the observation is created)
    minus the `volume_af` of every executed release (debited at the moment of
    execution), applied in event order on the logical clock, across all water
    years."

    Design: Corner/calculations/inflow_observation_credits_and_execute_debits_storage
    """
    world = fixtures.setup_open_year(api, reservoir_profile="big", inflow=50_000)
    reservoir_id = world["reservoir"]["id"]

    release = fixtures.schedule_and_execute_release(
        api, world, 1_000, 10, "2027-02-01T00:00:00Z", "2027-02-03T00:00:00Z"
    )
    assert release["status"] == "EXECUTED"
    assert_instant(release["executed_at"], "2027-02-03T00:00:00Z", "release.executed_at")

    reservoir = fixtures.get_reservoir(api, reservoir_id)
    assert reservoir["current_storage_af"] == 3_030_165, (
        "3,000,000 + 50,000 inflow - 19,835 executed volume"
    )


def test_constraint_min_flow_with_max_release_field_returns_invalid_request(api):
    """Constraint fields are conditional on requirement_type: a MIN_FLOW
    constraint carrying max_release_cfs is malformed - 400
    ERR_INVALID_REQUEST, and no row persists.

    PRD §3.5: "For `MIN_FLOW` and `PULSE_FLOW` constraints a
    `required_min_cfs` must be supplied and `max_release_cfs` must not be;
    for `MAX_RELEASE` the converse holds — `max_release_cfs` is required and
    `required_min_cfs` forbidden. Supplying the wrong field for the type
    fails shape validation with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/constraint_min_flow_with_max_release_field_returns_invalid_request
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]

    validate_error(
        api.create_environmental_constraint(
            reservoir_id,
            factories.constraint_payload(
                species="SMELT", requirement_type="MIN_FLOW",
                required_min_cfs=500, max_release_cfs=300,
            ),
            ENV,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    constraints, meta = validate_paginated(
        api.list_environmental_constraints(reservoir_id, fixtures.READ_HEADERS)
    )
    assert meta["total_count"] == 0 and constraints == []


def test_finance_officer_cannot_create_environmental_constraint_returns_forbidden(api):
    """Constraint registration is exclusive to EnvironmentalOfficer -
    segregation of operations from finance: a FinanceOfficer is rejected 403
    ERR_FORBIDDEN.

    PRD §2.1: "A request whose role is authenticated but not listed among the
    roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §2.1: "`EnvironmentalOfficer` (the endangered-species compliance
    desk, which registers constraints and resolves incidents but must not run
    releases)"

    Design: Corner/rbac/finance_officer_cannot_create_environmental_constraint_returns_forbidden
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]

    validate_error(
        api.create_environmental_constraint(
            reservoir_id, factories.min_flow_constraint_payload(500), FINANCE_OFFICER_HEADERS
        ),
        ApiErrorId.ERR_FORBIDDEN,
    )

    constraints, meta = validate_paginated(
        api.list_environmental_constraints(reservoir_id, fixtures.READ_HEADERS)
    )
    assert meta["total_count"] == 0 and constraints == []
