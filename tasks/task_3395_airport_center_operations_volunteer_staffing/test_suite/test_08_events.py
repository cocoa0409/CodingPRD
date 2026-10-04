"""Event lifecycle: kind-forked initial states, the tour security gate,
the optimistic staffing gate, event-calendar overlap, and the operations
checkpoint's event sweep."""
from test_helpers import (
    ApiClient,
    ApiErrorId,
    TEST_USERS,
    activate_agreement,
    approve_event_security,
    assign_volunteer,
    cancel_event,
    confirm_assignment,
    confirm_event,
    create_center,
    create_center_with_active_agreement,
    create_cleared_volunteer,
    create_event,
    create_shift,
    create_tour_event,
    draft_agreement,
    get_assignment,
    get_center,
    run_ops,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
MGR = TEST_USERS["manager_headers"]


def test_event_tour_branch_vs_deploy(api: ApiClient):
    """PRD §3.7: "Creation forks the lifecycle by kind: a tour stop begins in `SECURITY_REVIEW`, while deployment and homecoming events begin in `PLANNED`."
    PRD §3.7: "Deployment and homecoming events confirm from `PLANNED`; tours confirm from `SECURITY_APPROVED`; confirming from the wrong branch state is `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/event_tour_branch_vs_deploy
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Zeta Center",
            "airport_code": "ORD",
            "occupancy_cap": 60,
            "required_daily_confirmed_assignments": 2,
        },
        agreement_overrides={
            "facility_space_sqft": 1500,
            "access_terms": "escort-required",
            "security_level": 3,
        },
    )
    dep_resp = api.create_event(
        center["id"],
        {
            "kind": "DEPLOYMENT",
            "name": "Unit 9 Departure",
            "start_at": "2026-09-10T08:00:00Z",
            "end_at": "2026-09-10T10:00:00Z",
            "min_volunteers": 0,
        },
        MGR,
    )
    deployment = validate_success(dep_resp, 201)
    assert deployment["status"] == "PLANNED", (
        f"a DEPLOYMENT event begins in PLANNED, got {deployment['status']!r}"
    )

    tour_resp = api.create_event(
        center["id"],
        {
            "kind": "ENTERTAINMENT_TOUR",
            "name": "Fall Tour Stop",
            "start_at": "2026-09-12T14:00:00Z",
            "end_at": "2026-09-12T16:00:00Z",
            "min_volunteers": 0,
            "required_security_level": 3,
            "talent_agreement_signed": True,
        },
        MGR,
    )
    tour = validate_success(tour_resp, 201)
    assert tour["status"] == "SECURITY_REVIEW", (
        f"an ENTERTAINMENT_TOUR begins in SECURITY_REVIEW, got {tour['status']!r}"
    )

    early = api.confirm_event(tour["id"], MGR)
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)

    approved = approve_event_security(tour["id"])
    assert approved["status"] == "SECURITY_APPROVED"

    confirmed = confirm_event(tour["id"])
    assert confirmed["status"] == "CONFIRMED", (
        "after the security detour the branches rejoin at CONFIRMED, got "
        f"{confirmed['status']!r}"
    )


def test_event_confirm_after_cancel_rejected(api: ApiClient):
    """PRD §3.7: "Deployment and homecoming events confirm from `PLANNED`; tours confirm from `SECURITY_APPROVED`; confirming from the wrong branch state is `ERR_INVALID_STATE`."
    PRD §3.7: "A `CenterManager` may cancel any non-terminal event — `PLANNED`, `SECURITY_REVIEW`, `SECURITY_APPROVED`, or `CONFIRMED` — moving it to `CANCELLED`. The operations checkpoint resolves the rest: a `CONFIRMED` event whose `end_at` has passed becomes `EXECUTED`, while an event still in `PLANNED`, `SECURITY_REVIEW`, or `SECURITY_APPROVED` once its `start_at` has arrived is swept to `CANCELLED`. `EXECUTED` and `CANCELLED` are terminal."

    Design: Corner/state_machines/event_confirm_after_cancel_rejected
    """
    set_clock()
    center = create_center(
        name="Omega Center",
        airport_code="COS",
        occupancy_cap=25,
        required_daily_confirmed_assignments=1,
    )
    event = create_event(
        center["id"],
        kind="DEPLOYMENT",
        name="Unit 5 Departure",
        start_at="2026-09-10T08:00:00Z",
        end_at="2026-09-10T10:00:00Z",
        min_volunteers=0,
    )
    cancel_event(event["id"])

    resp = api.confirm_event(event["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    rows, _meta = validate_paginated(api.list_events(center["id"], MGR))
    assert rows[0]["id"] == event["id"]
    assert rows[0]["status"] == "CANCELLED", (
        "CANCELLED is terminal: the rejected confirm changes nothing"
    )


def test_event_overlap_half_open(api: ApiClient):
    """PRD §3.7: "Creation also enforces the center's event calendar: a new event whose window overlaps — half-open, with adjacency permitted — any non-`CANCELLED` event at the same center is rejected with `ERR_EVENT_OVERLAP`."

    Design: Corner/calculations/event_overlap_half_open
    """
    set_clock()
    center = create_center(
        name="Teth Center",
        airport_code="EUG",
        occupancy_cap=25,
        required_daily_confirmed_assignments=1,
    )
    create_event(
        center["id"],
        kind="DEPLOYMENT",
        name="Ev A",
        start_at="2026-09-10T10:00:00Z",
        end_at="2026-09-10T12:00:00Z",
        min_volunteers=0,
    )

    adjacent = api.create_event(
        center["id"],
        {
            "kind": "HOMECOMING",
            "name": "Ev B",
            "start_at": "2026-09-10T12:00:00Z",
            "end_at": "2026-09-10T14:00:00Z",
            "min_volunteers": 0,
        },
        MGR,
    )
    ev_b = validate_success(adjacent, 201)
    assert ev_b["status"] == "PLANNED", (
        "12:00 == 12:00 adjacency is permitted under half-open windows"
    )

    straddle = api.create_event(
        center["id"],
        {
            "kind": "DEPLOYMENT",
            "name": "Ev C",
            "start_at": "2026-09-10T11:00:00Z",
            "end_at": "2026-09-10T13:00:00Z",
            "min_volunteers": 0,
        },
        MGR,
    )
    validate_error(straddle, ApiErrorId.ERR_EVENT_OVERLAP)


def test_tour_approve_without_active_agreement_rejected(api: ApiClient):
    """PRD §3.7: "Security approval requires the event to be an `ENTERTAINMENT_TOUR` sitting in `SECURITY_REVIEW` — anything else is `ERR_INVALID_STATE` — the host center to hold an `ACTIVE` site agreement (`ERR_AGREEMENT_NOT_ACTIVE`), that agreement's `security_level` to be at least the event's `required_security_level` (`ERR_SECURITY_LEVEL_INSUFFICIENT`), and `talent_agreement_signed` to be true (`ERR_TALENT_AGREEMENT_UNSIGNED`). Passing moves the event to `SECURITY_APPROVED`."

    Design: Corner/errors/tour_approve_without_active_agreement_rejected
    """
    set_clock()
    center = create_center(
        name="Bet2 Center",
        airport_code="HVN",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    # No site agreement exists on this center at all.
    event = create_tour_event(
        center["id"],
        name="Tour X",
        required_security_level=1,
        talent_agreement_signed=True,
    )
    assert event["status"] == "SECURITY_REVIEW"

    resp = api.approve_event_security(event["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    rows, _meta = validate_paginated(api.list_events(center["id"], MGR))
    assert rows[0]["status"] == "SECURITY_REVIEW", (
        "the rejected approval leaves the tour in SECURITY_REVIEW"
    )


def test_tour_approve_unsigned_talent_rejected(api: ApiClient):
    """PRD §3.7: "Security approval requires the event to be an `ENTERTAINMENT_TOUR` sitting in `SECURITY_REVIEW` — anything else is `ERR_INVALID_STATE` — the host center to hold an `ACTIVE` site agreement (`ERR_AGREEMENT_NOT_ACTIVE`), that agreement's `security_level` to be at least the event's `required_security_level` (`ERR_SECURITY_LEVEL_INSUFFICIENT`), and `talent_agreement_signed` to be true (`ERR_TALENT_AGREEMENT_UNSIGNED`). Passing moves the event to `SECURITY_APPROVED`."

    Design: Corner/errors/tour_approve_unsigned_talent_rejected
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Gimel2 Center",
            "airport_code": "OGS",
            "occupancy_cap": 10,
            "required_daily_confirmed_assignments": 1,
        },
        agreement_overrides={"security_level": 3, "access_terms": "escort"},
    )
    # Agreement level 3 >= required 2, so the talent precondition is the
    # one that fires.
    event = create_tour_event(
        center["id"],
        name="Tour Y",
        required_security_level=2,
        talent_agreement_signed=False,
    )
    resp = api.approve_event_security(event["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_TALENT_AGREEMENT_UNSIGNED)


def test_event_confirm_staffing_shortfall(api: ApiClient):
    """PRD §3.7: "The gate is the optimistic staffing variant: pledged staffing is the count of `CONFIRMED` assignments plus 0.5 times the count of `ASSIGNED` assignments, taken over the host center's shifts whose windows overlap the event window half-open. When pledged staffing is at least `min_volunteers` the event becomes `CONFIRMED`; otherwise confirmation is rejected with `ERR_STAFFING_SHORTFALL` and the event stays in its branch state."

    Design: Corner/errors/event_confirm_staffing_shortfall
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "He2 Center",
            "airport_code": "PIA",
            "occupancy_cap": 10,
            "required_daily_confirmed_assignments": 1,
        }
    )
    # No shifts exist, so pledged staffing over the event window is 0.
    event = create_event(
        center["id"],
        kind="DEPLOYMENT",
        name="Unit 77 Departure",
        start_at="2026-09-10T10:00:00Z",
        end_at="2026-09-10T12:00:00Z",
        min_volunteers=2,
    )
    resp = api.confirm_event(event["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_STAFFING_SHORTFALL)

    rows, _meta = validate_paginated(api.list_events(center["id"], MGR))
    assert rows[0]["status"] == "PLANNED", (
        "a shortfall rejection leaves the event in its branch state (PLANNED)"
    )


def test_event_auto_sweep_run_ops(api: ApiClient):
    """PRD §3.7: "The operations checkpoint resolves the rest: a `CONFIRMED` event whose `end_at` has passed becomes `EXECUTED`, while an event still in `PLANNED`, `SECURITY_REVIEW`, or `SECURITY_APPROVED` once its `start_at` has arrived is swept to `CANCELLED`."

    Design: Corner/complexity_layers/event_auto_sweep_run_ops
    """
    set_clock()
    center = create_center(
        name="Ayin2 Center",
        airport_code="ATW",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    ev1 = create_event(
        center["id"],
        kind="DEPLOYMENT",
        name="Ev One",
        start_at="2026-09-10T10:00:00Z",
        end_at="2026-09-10T12:00:00Z",
        min_volunteers=0,
    )
    confirm_event(ev1["id"])
    ev2 = create_event(
        center["id"],
        kind="DEPLOYMENT",
        name="Ev Two",
        start_at="2026-09-10T14:00:00Z",
        end_at="2026-09-10T16:00:00Z",
        min_volunteers=0,
    )

    set_clock("2026-09-10T17:00:00Z")
    run_ops(center["id"])

    rows, _meta = validate_paginated(api.list_events(center["id"], MGR))
    by_id = {row["id"]: row for row in rows}
    assert by_id[ev1["id"]]["status"] == "EXECUTED", (
        "the CONFIRMED event past its end (12:00 <= 17:00) is EXECUTED, got "
        f"{by_id[ev1['id']]['status']!r}"
    )
    assert by_id[ev2["id"]]["status"] == "CANCELLED", (
        "the never-confirmed event whose start (14:00) has arrived is swept "
        f"to CANCELLED, got {by_id[ev2['id']]['status']!r}"
    )


def test_agreement_security_gates_tour_approval(api: ApiClient):
    """PRD §3.7: "Security approval requires the event to be an `ENTERTAINMENT_TOUR` sitting in `SECURITY_REVIEW` — anything else is `ERR_INVALID_STATE` — the host center to hold an `ACTIVE` site agreement (`ERR_AGREEMENT_NOT_ACTIVE`), that agreement's `security_level` to be at least the event's `required_security_level` (`ERR_SECURITY_LEVEL_INSUFFICIENT`), and `talent_agreement_signed` to be true (`ERR_TALENT_AGREEMENT_UNSIGNED`). Passing moves the event to `SECURITY_APPROVED`."
    PRD §3.1: "On success, any other `ACTIVE` agreement of the same center cascades to `TERMINATED`, the center's `active_agreement_id` is set to the newly activated agreement, posture is recomputed against current coverage, and the center's `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/agreement_security_gates_tour_approval
    """
    set_clock()
    center = create_center(
        name="Xi Center",
        airport_code="Ramstein",
        occupancy_cap=80,
        required_daily_confirmed_assignments=2,
    )
    a1 = draft_agreement(
        center["id"], security_level=2, access_terms="escort-required"
    )
    activate_agreement(a1["id"], center["version"])
    event = create_tour_event(
        center["id"],
        name="USO Tour Stop",
        required_security_level=3,
        talent_agreement_signed=True,
    )

    denied = api.approve_event_security(event["id"], ADMIN)
    validate_error(denied, ApiErrorId.ERR_SECURITY_LEVEL_INSUFFICIENT)

    # Supersede with a level-3 agreement (the level-2 one is TERMINATED).
    a2 = draft_agreement(
        center["id"], security_level=3, access_terms="escort-required-plus"
    )
    fresh = get_center(center["id"])
    activate_agreement(a2["id"], fresh["version"])

    ok = api.approve_event_security(event["id"], ADMIN)
    approved = validate_success(ok, 200)
    assert approved["status"] == "SECURITY_APPROVED", (
        "with the ACTIVE agreement at level 3 >= required 3 and talent "
        "signed, approval passes"
    )

    rows, _meta = validate_paginated(api.list_site_agreements(center["id"], ADMIN))
    by_id = {row["id"]: row for row in rows}
    assert by_id[a1["id"]]["status"] == "TERMINATED", (
        "the superseded level-2 agreement cascades to TERMINATED"
    )
    assert by_id[a2["id"]]["status"] == "ACTIVE"


def test_coverage_confirmed_vs_optimistic_variants(api: ApiClient):
    """PRD §2.6: "The derivation uses the confirmed-only coverage variant: `coverage_ratio` is the number of `CONFIRMED` shift assignments whose shift's `start_at` falls on the current clock date, divided by the center's `required_daily_confirmed_assignments`; assignments in `ASSIGNED`, `CANCELLED`, `NO_SHOW`, or `COMPLETED` never count toward it."
    PRD §2.6: "If the center has no `ACTIVE` site agreement, posture is `CLOSED`. Otherwise, when `coverage_ratio` is at least 0.75 the posture is `OPEN`, and below that threshold it is `RESTRICTED`."
    PRD §3.7: "The gate is the optimistic staffing variant: pledged staffing is the count of `CONFIRMED` assignments plus 0.5 times the count of `ASSIGNED` assignments, taken over the host center's shifts whose windows overlap the event window half-open. When pledged staffing is at least `min_volunteers` the event becomes `CONFIRMED`; otherwise confirmation is rejected with `ERR_STAFFING_SHORTFALL` and the event stays in its branch state."

    Design: Difficulty/dual_variant_calc/coverage_confirmed_vs_optimistic_variants
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Alpha Center",
            "airport_code": "LAX",
            "occupancy_cap": 50,
            "required_daily_confirmed_assignments": 4,
        },
        agreement_overrides={
            "facility_space_sqft": 1200,
            "access_terms": "badge-24x7",
            "security_level": 3,
        },
    )
    v1 = create_cleared_volunteer(center["id"], full_name="V One")
    v2 = create_cleared_volunteer(center["id"], full_name="V Two")
    shift = create_shift(
        center["id"],
        start_at="2026-09-01T08:00:00Z",
        end_at="2026-09-01T12:00:00Z",
        role_required="DESK",
        capacity=3,
    )
    a1 = assign_volunteer(shift["id"], v1["id"])
    confirm_assignment(a1["id"], v1["id"])
    # v2 stays ASSIGNED: invisible to the confirmed-only variant but counted
    # at half weight by the optimistic variant.
    a2 = assign_volunteer(shift["id"], v2["id"])

    event = create_event(
        center["id"],
        kind="DEPLOYMENT",
        name="Unit 42 Departure",
        start_at="2026-09-01T09:00:00Z",
        end_at="2026-09-01T11:00:00Z",
        unit_name="42nd",
        min_volunteers=1,
    )

    snapshot = get_center(center["id"])
    assert snapshot["coverage_ratio"] == 0.25, (
        f"confirmed-only variant: 1 CONFIRMED / 4 required = 0.25, got "
        f"{snapshot['coverage_ratio']}"
    )
    assert snapshot["posture"] == "RESTRICTED", (
        f"0.25 < 0.75 under the confirmed-only variant: RESTRICTED, got "
        f"{snapshot['posture']!r}"
    )
    assert get_assignment(a2["id"])["status"] == "ASSIGNED"

    confirmed = confirm_event(event["id"])
    assert confirmed["status"] == "CONFIRMED", (
        "optimistic variant over the overlapping shift: 1 CONFIRMED + "
        "0.5 * 1 ASSIGNED = 1.5 >= min_volunteers 1, so the event confirms"
    )
