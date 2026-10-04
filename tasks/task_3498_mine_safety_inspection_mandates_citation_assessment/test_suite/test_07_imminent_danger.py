"""Imminent-danger orders (PRD §3.5, §2.9): the halt-and-suspend cascade, the
closed-interval occupation of a mine, the fixed lifecycle, termination
reversal, and segregation of duties on abatement verification.

Clock note: all readings are >= the startup reading 2026-09-01T00:00:00Z
(PRD §2.4); the order lifecycle here runs 2026-09-01 .. 2026-09-05 with
terminated_at exactly 2026-09-05T15:00:00Z.
"""
from test_helpers import (
    ApiErrorId,
    abate_citation_flow,
    confirm_ido_withdrawal_flow,
    confirm_withdrawal_payload,
    create_ido_payload,
    in_progress_inspection,
    issue_citation,
    issue_ido,
    make_inspector_headers,
    refresh_citation,
    refresh_ido,
    refresh_inspection,
    refresh_mine,
    set_clock,
    setup_inspector,
    setup_registry,
    setup_terminated_ido,
    terminate_ido_flow,
    validate_created,
    validate_error,
    verify_citation_abatement_payload,
    verify_ido_abatement_flow,
    verify_ido_abatement_payload,
)


def test_ido_issuance_halts_mine_then_suspends_inspections(api):
    """PRD §2.9: "The moment an order is created at a mine, the mine's
    `production_status` becomes `HALTED`, the mine's `version` increments, and
    every inspection currently `IN_PROGRESS` at that mine transitions to
    `SUSPENDED`, each such inspection's `version` incrementing."
    PRD §3.5: "The order is born in `ISSUED` status with `issued_at` from the
    clock and `issued_by_inspector_id` set to the acting inspector"

    Design: Difficulty/transitive_cascade/ido_issuance_halts_mine_then_suspends_inspections
    """
    set_clock("2026-09-06T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    inspection = in_progress_inspection(
        mine, i1, kind="SPOT",
        planned_start_at="2026-09-06T08:00:00Z",
        planned_end_at="2026-09-06T17:00:00Z",
    )
    mine_before = refresh_mine(mine["id"])

    set_clock("2026-09-06T10:00:00Z")
    resp = api.create_imminent_danger_order(
        create_ido_payload(
            mine["id"],
            inspection_id=inspection["id"],
            hazard_description="methane accumulation beyond 2 percent",
        ),
        make_inspector_headers(i1["id"]),
    )
    order = validate_created(resp)
    assert order["status"] == "ISSUED"
    assert order["issued_at"] == "2026-09-06T10:00:00Z"
    assert order["issued_by_inspector_id"] == i1["id"]
    assert order["inspection_id"] == inspection["id"]

    mine_after = refresh_mine(mine["id"])
    assert mine_after["production_status"] == "HALTED"
    assert mine_after["version"] == mine_before["version"] + 1, (
        "the halt mutates the mine exactly once"
    )

    suspended = refresh_inspection(inspection["id"])
    assert suspended["status"] == "SUSPENDED", (
        "the halt cascade — not the POST directly — suspends the inspection"
    )

    # SUSPENDED has no completion transition.
    resp = api.complete_inspection(inspection["id"], make_inspector_headers(i1["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_ido_closed_interval_rejects_termination_instant_reuse(api):
    """PRD §3.5: "moreover, a new order's `issued_at` must be strictly later
    than the `terminated_at` of any previously terminated order at the mine,
    since a terminated order occupies its interval up to and including its
    termination instant. Either violation is rejected with
    `ERR_IDO_ACTIVE_EXISTS`."

    Design: Difficulty/resource_temporal_overlap/ido_closed_interval_rejects_termination_instant_reuse
    """
    set_clock("2026-09-01T09:00:00Z")
    _operator, mine, i1 = setup_registry()
    verifier = setup_inspector()
    i1h = make_inspector_headers(i1["id"])

    set_clock("2026-09-01T10:00:00Z")
    order = issue_ido(mine, i1, hazard_description="roof sag over the belt line")
    set_clock("2026-09-01T11:00:00Z")
    order = confirm_ido_withdrawal_flow(order, i1, miners_withdrawn_count=12)
    set_clock("2026-09-03T09:00:00Z")
    order = verify_ido_abatement_flow(order, verifier)
    set_clock("2026-09-05T15:00:00Z")
    order = terminate_ido_flow(order)
    assert order["status"] == "TERMINATED"
    assert order["terminated_at"] == "2026-09-05T15:00:00Z"

    # Closed interval: the shared instant is still occupied.
    resp = api.create_imminent_danger_order(
        create_ido_payload(mine["id"], hazard_description="second hazard, same instant"),
        i1h,
    )
    validate_error(resp, ApiErrorId.ERR_IDO_ACTIVE_EXISTS)

    # One second strictly later: the interval is free again.
    set_clock("2026-09-05T15:00:01Z")
    resp = api.create_imminent_danger_order(
        create_ido_payload(mine["id"], hazard_description="second hazard, one second later"),
        i1h,
    )
    order2 = validate_created(resp)
    assert order2["status"] == "ISSUED"
    assert order2["issued_at"] == "2026-09-05T15:00:01Z"
    assert refresh_mine(mine["id"])["production_status"] == "HALTED"


def test_ido_terminated_locks_further_transitions(api):
    """PRD §3.5: "Termination is a `DistrictManager` act that moves the order
    from `ABATEMENT_VERIFIED` to `TERMINATED` and stamps `terminated_at`."
    PRD §3.5: "`TERMINATED` is terminal."
    PRD §2.5 tier 7: "The entity is in a state that permits the transition,
    including the operating-mine requirement, the uncontested-citation
    requirement, and the potential-POV prerequisite; violations yield
    `ERR_INVALID_STATE`, `ERR_MINE_NOT_ACTIVE`, `ERR_CITATION_NOT_CONTESTABLE`,
    or `ERR_POV_NOTICE_REQUIRES_POTENTIAL` (HTTP 409)."

    Design: Corner/state_machines/ido_terminated_locks_further_transitions
    """
    set_clock("2026-09-02T09:00:00Z")
    bundle = setup_terminated_ido()
    order = bundle["order"]
    assert order["status"] == "TERMINATED"

    resp = api.confirm_ido_withdrawal(
        order["id"],
        confirm_withdrawal_payload(12),
        make_inspector_headers(bundle["issuer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert refresh_ido(order["id"])["status"] == "TERMINATED"


def test_ido_termination_resumes_mine_and_inspection(api):
    """PRD §2.9: "The cascade reverses only when the last non-terminated order
    at the mine is terminated: the mine's `production_status` returns to
    `NORMAL` with another version increment, and every `SUSPENDED` inspection
    at the mine resumes to `IN_PROGRESS`."

    Design: Corner/state_machines/ido_termination_resumes_mine_and_inspection
    """
    set_clock("2026-09-01T08:00:00Z")
    _operator, mine, i1 = setup_registry()
    verifier = setup_inspector()
    inspection = in_progress_inspection(mine, i1, kind="SPOT")

    set_clock("2026-09-01T10:00:00Z")
    order = issue_ido(
        mine, i1, hazard_description="methane pocket", inspection_id=inspection["id"]
    )
    assert refresh_mine(mine["id"])["production_status"] == "HALTED"
    assert refresh_inspection(inspection["id"])["status"] == "SUSPENDED"

    set_clock("2026-09-01T11:00:00Z")
    order = confirm_ido_withdrawal_flow(order, i1, miners_withdrawn_count=12)
    set_clock("2026-09-03T09:00:00Z")
    order = verify_ido_abatement_flow(order, verifier)

    set_clock("2026-09-05T15:00:00Z")
    order = terminate_ido_flow(order)
    assert order["status"] == "TERMINATED"
    assert order["terminated_at"] == "2026-09-05T15:00:00Z"
    assert refresh_mine(mine["id"])["production_status"] == "NORMAL"
    assert refresh_inspection(inspection["id"])["status"] == "IN_PROGRESS", (
        "the resume cascade restores the suspended inspection"
    )


def test_sod_verifier_must_differ_from_issuer(api):
    """PRD §2.9: "For both citations and imminent-danger orders, the inspector
    who verifies abatement must differ from the inspector who issued the
    instrument; a verification attempted by the issuing inspector is rejected
    with `ERR_SOD_VERIFY_SELF`."

    Design: Corner/rbac/sod_verifier_must_differ_from_issuer
    """
    set_clock("2026-09-10T08:00:00Z")
    operator, mine, i1 = setup_registry()
    inspection = in_progress_inspection(mine, i1, kind="SPOT")
    i1h = make_inspector_headers(i1["id"])

    set_clock("2026-09-10T09:00:00Z")
    citation = issue_citation(inspection, mine, i1)
    set_clock("2026-09-11T09:00:00Z")
    citation = abate_citation_flow(citation, operator)
    assert citation["abatement_status"] == "ABATED"

    order = issue_ido(
        mine, i1, hazard_description="methane pocket", inspection_id=inspection["id"]
    )
    order = confirm_ido_withdrawal_flow(order, i1, miners_withdrawn_count=8)
    assert order["status"] == "WITHDRAWAL_CONFIRMED"

    # The issuing inspector cannot verify either instrument.
    resp = api.verify_citation_abatement(
        citation["id"], verify_citation_abatement_payload(), i1h
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VERIFY_SELF)
    resp = api.verify_ido_abatement(
        order["id"], verify_ido_abatement_payload(), i1h
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VERIFY_SELF)

    assert refresh_citation(citation["id"])["abatement_status"] == "ABATED"
    assert refresh_ido(order["id"])["status"] == "WITHDRAWAL_CONFIRMED"
