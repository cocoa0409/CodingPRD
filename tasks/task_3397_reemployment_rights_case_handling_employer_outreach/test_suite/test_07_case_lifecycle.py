"""Case lifecycle: the negotiation loop, ombudsman closure, member reopen
within the 60-day window, terminal-state lockdown, and withdrawal replay."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_instant,
    case_state_payload,
    create_assigned_case,
    create_case,
    make_ombudsman_headers,
    make_service_member_headers,
    open_round,
    read_case,
    resolve_case_informally,
    respond_as_employer,
    set_clock,
    setup_basic_world,
    transition_case,
    triage_case,
    assign_case,
    validate_error,
    validate_success,
)


def test_mediation_loop_decline_returns_case_to_in_mediation_twice(api: ApiClient, coordinator_headers: dict):
    """PRD §3.4: "A `COUNTERED` or `DECLINED` round — or one that expires, whether discovered lazily on a read of the case's rounds or on a response attempt — likewise returns the case from `AWAITING_RESPONSE` to `IN_MEDIATION`, decrementing `open_round_count` by 1, and the ombudsman may then open the next round."

    Design: Difficulty/non_linear_state_machine/case_reopen_cycle_and_mediation_loop
    """
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])

    round_one = open_round(api, case["id"], world["ombudsman"]["id"], proposal_text="Reinstate with back pay.")
    assert read_case(api, case["id"])["status"] == "AWAITING_RESPONSE"
    respond_as_employer(api, round_one["id"], world["employer"]["id"], "DECLINE")
    assert read_case(api, case["id"])["status"] == "IN_MEDIATION", "first loop edge"

    round_two = open_round(api, case["id"], world["ombudsman"]["id"], proposal_text="Reinstate without back pay.")
    assert read_case(api, case["id"])["status"] == "AWAITING_RESPONSE"
    respond_as_employer(api, round_two["id"], world["employer"]["id"], "DECLINE")
    assert read_case(api, case["id"])["status"] == "IN_MEDIATION", "second loop edge"

    rounds = {r["id"]: r for r in validate_success(api.list_case_rounds(case["id"], coordinator_headers))}
    assert rounds[round_one["id"]]["status"] == "DECLINED"
    assert rounds[round_two["id"]]["status"] == "DECLINED"


def test_close_unresolved_then_member_reopen_reenters_triage_unassigned(api: ApiClient):
    """PRD §3.7: "The assigned ombudsman, giving up on a stalled matter, may instead close it from `IN_MEDIATION` or `AWAITING_RESPONSE` into `CLOSED_UNRESOLVED` — stamping `closed_at`, releasing the caseload, clearing the assignment, and mooting any open rounds with audit notes when closing from `AWAITING_RESPONSE`."
    PRD §3.7: "The member may reopen a `CLOSED_UNRESOLVED` case back into `TRIAGE` — the case re-enters triage unassigned — provided the logical clock is no later than 60 days after `closed_at`; reopening exactly 60 days after closure is inside the window, and a later attempt fails with `ERR_REOPEN_WINDOW_PASSED` (HTTP 422). A successful reopen clears `closed_at`."

    Design: Difficulty/non_linear_state_machine/case_reopen_cycle_and_mediation_loop
    """
    world = setup_basic_world(api)
    ombudsman_headers = make_ombudsman_headers(world["ombudsman"]["id"])
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    round_one = open_round(api, case["id"], world["ombudsman"]["id"], proposal_text="Reinstate with back pay.")
    respond_as_employer(api, round_one["id"], world["employer"]["id"], "DECLINE")

    closed = transition_case(api, case["id"], "CLOSED_UNRESOLVED", ombudsman_headers,
                             reason="Mediation exhausted informally")
    assert closed["status"] == "CLOSED_UNRESOLVED"
    assert closed["assigned_ombudsman_id"] is None, "closure clears the assignment"
    assert_instant(closed["closed_at"], "2026-09-01T00:00:00Z", "closed_at")

    set_clock(api, "2026-10-01T00:00:00Z")
    reopened = transition_case(api, case["id"], "TRIAGE", make_service_member_headers(world["member"]["id"]))
    assert reopened["status"] == "TRIAGE", "30 days after closure is inside the 60-day reopen window"
    assert reopened["assigned_ombudsman_id"] is None
    assert reopened["open_round_count"] == 0
    assert reopened["closed_at"] is None, "a successful reopen clears closed_at"


def test_resolved_case_rejects_all_further_transitions(api: ApiClient, coordinator_headers: dict):
    """PRD §3.7: "`RESOLVED_INFORMAL`, `REFERRED`, and `CLOSED_WITHDRAWN` are terminal: no transition leaves them."
    PRD §2.7: "Sixth, state gates: the target entity must be in a state from which the requested transition exists, and cross-entity state gates apply, failing with `ERR_INVALID_STATE`, `ERR_ROUND_NOT_OPEN`, or `ERR_OMBUDSMAN_NOT_CERTIFIED`."

    Design: Corner/state_machines/resolved_case_rejects_all_further_transitions
    """
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    resolved = resolve_case_informally(api, case["id"], world["ombudsman"]["id"],
                                       employer_id=world["employer"]["id"])
    assert resolved["case"]["status"] == "RESOLVED_INFORMAL"

    by_coordinator = api.transition_case(case["id"], case_state_payload("TRIAGE"), coordinator_headers)
    validate_error(by_coordinator, ApiErrorId.ERR_INVALID_STATE)

    by_member = api.transition_case(
        case["id"], case_state_payload("CLOSED_WITHDRAWN"), make_service_member_headers(world["member"]["id"])
    )
    validate_error(by_member, ApiErrorId.ERR_INVALID_STATE)

    assert read_case(api, case["id"])["status"] == "RESOLVED_INFORMAL"


def test_withdraw_twice_returns_invalid_state(api: ApiClient):
    """PRD §3.7: "The member may abandon the case at almost any point. Withdrawal moves the case from `INTAKE`, `TRIAGE`, `ASSIGNED`, `IN_MEDIATION`, `AWAITING_RESPONSE`, or `ESCALATION_PENDING` into `CLOSED_WITHDRAWN` and always stamps `closed_at`."
    PRD §3.7: "`RESOLVED_INFORMAL`, `REFERRED`, and `CLOSED_WITHDRAWN` are terminal: no transition leaves them."

    Design: Corner/state_machines/withdraw_twice_returns_invalid_state
    """
    world = setup_basic_world(api)
    case = create_case(api, world["member"]["id"], world["employer"]["id"])
    member_headers = make_service_member_headers(world["member"]["id"])

    withdrawn = transition_case(api, case["id"], "CLOSED_WITHDRAWN", member_headers)
    assert withdrawn["status"] == "CLOSED_WITHDRAWN"
    first_closed_at = withdrawn["closed_at"]
    assert first_closed_at is not None

    replay = api.transition_case(case["id"], case_state_payload("CLOSED_WITHDRAWN"), member_headers)
    validate_error(replay, ApiErrorId.ERR_INVALID_STATE)

    after = read_case(api, case["id"])
    assert after["status"] == "CLOSED_WITHDRAWN"
    assert after["closed_at"] == first_closed_at, "the rejected replay changes nothing"


def test_direct_resolve_via_state_endpoint_returns_invalid_state(api: ApiClient, coordinator_headers: dict):
    """PRD §3.4: "When the predicate holds, acceptance moves the round to `ACCEPTED` with `responded_at` stamped and resolves the case `AWAITING_RESPONSE → RESOLVED_INFORMAL`"
    PRD §2.7: "Sixth, state gates: the target entity must be in a state from which the requested transition exists, and cross-entity state gates apply, failing with `ERR_INVALID_STATE`, `ERR_ROUND_NOT_OPEN`, or `ERR_OMBUDSMAN_NOT_CERTIFIED`."

    Design: Corner/state_machines/direct_resolve_via_state_endpoint_returns_invalid_state
    """
    world = setup_basic_world(api)
    case = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    open_round(api, case["id"], world["ombudsman"]["id"])
    assert read_case(api, case["id"])["status"] == "AWAITING_RESPONSE"

    response = api.transition_case(case["id"], case_state_payload("RESOLVED_INFORMAL"), coordinator_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert read_case(api, case["id"])["status"] == "AWAITING_RESPONSE"


def test_reopen_window_exactly_60_days(api: ApiClient):
    """PRD §3.7: "The member may reopen a `CLOSED_UNRESOLVED` case back into `TRIAGE` — the case re-enters triage unassigned — provided the logical clock is no later than 60 days after `closed_at`; reopening exactly 60 days after closure is inside the window, and a later attempt fails with `ERR_REOPEN_WINDOW_PASSED` (HTTP 422)."

    Design: Corner/validations/reopen_window_exactly_60_days
    """
    world = setup_basic_world(api)
    member_headers = make_service_member_headers(world["member"]["id"])
    ombudsman_headers = make_ombudsman_headers(world["ombudsman"]["id"])

    case_a = create_assigned_case(api, world["employer"], world["member"], world["ombudsman"])
    open_round(api, case_a["id"], world["ombudsman"]["id"])
    closed_a = transition_case(api, case_a["id"], "CLOSED_UNRESOLVED", ombudsman_headers)
    assert_instant(closed_a["closed_at"], "2026-09-01T00:00:00Z", "case A closed_at")

    case_c = create_case(api, world["member"]["id"], world["employer"]["id"],
                         issue_type="PENSION", description="Case for late reopen")
    case_c = triage_case(api, case_c["id"])
    case_c = assign_case(api, case_c["id"], world["ombudsman"]["id"], case_c["version"])
    open_round(api, case_c["id"], world["ombudsman"]["id"], proposal_text="Offer C.")
    transition_case(api, case_c["id"], "CLOSED_UNRESOLVED", ombudsman_headers)

    set_clock(api, "2026-10-31T00:00:00Z")
    reopened = api.transition_case(case_a["id"], case_state_payload("TRIAGE"), member_headers)
    assert validate_success(reopened)["status"] == "TRIAGE", \
        "reopening at exactly closed_at + 60 days is inside the window"

    set_clock(api, "2026-10-31T00:00:01Z")
    late = api.transition_case(case_c["id"], case_state_payload("TRIAGE"), member_headers)
    validate_error(late, ApiErrorId.ERR_REOPEN_WINDOW_PASSED)
    assert late.status_code == 422
    assert read_case(api, case_c["id"])["status"] == "CLOSED_UNRESOLVED"
