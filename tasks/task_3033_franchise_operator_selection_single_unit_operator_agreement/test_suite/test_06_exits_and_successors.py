"""Exit notice period and the successor proposal revision loop."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_active_operator, setup_open_exit, set_clock, make_operator_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
FC = TEST_USERS["field_consultant_headers"]
SC = TEST_USERS["selection_committee_headers"]


def test_exit_notice_shorter_than_min_days_rejected(api):
    """PRD §3.11: "Notice must be genuine: `effective_on` must be at least
    thirty days after the notice date, and a shorter runway is refused with
    `ERR_NOTICE_TOO_SHORT`."

    Design: Corner/validations/exit_notice_shorter_than_min_days_rejected
    """
    set_clock()
    ctx = setup_active_operator()
    operator_id = ctx["operator"]["id"]
    # After the pipeline the logical clock sits at 2026-09-07; 2026-09-20 is
    # only thirteen days of notice — fewer than thirty.
    resp = api.create_exit(
        operator_id,
        {"reason": "VOLUNTARY", "effective_on": "2026-09-20T00:00:00Z"},
        make_operator_headers(operator_id),
    )
    validate_error(resp, ApiErrorId.ERR_NOTICE_TOO_SHORT)
    operator = get_success_data(api.get_operator(operator_id, ADMIN))
    assert operator["operator_status"] == "ACTIVE"


def _setup_exit_with_proposed_successor(api):
    """ACTIVE operator with an OPEN exit case and a proposed successor who is a
    SELECTED candidate of the same market. Returns (ctx, exit_case, successor_candidate)."""
    ctx = setup_active_operator()
    exit_case = setup_open_exit(ctx, reason="VOLUNTARY",
                                effective_on="2026-10-07T00:00:00Z")
    # The exiting operator's own candidate is SELECTED with an approved
    # application targeting the restaurant's market, so it is eligible to be
    # proposed as successor.
    successor_candidate = ctx["candidate"]
    resp = api.propose_successor(
        ctx["operator"]["id"], exit_case["id"],
        {"successor_candidate_id": successor_candidate["id"]}, FC,
    )
    exit_case = validate_success(resp)
    assert exit_case["exit_status"] == "SUCCESSOR_PENDING"
    return ctx, exit_case, successor_candidate


def test_reject_successor_returns_exit_to_open_and_clears_successor(api):
    """PRD §3.11: "The committee then rules: approval moves the case to
    `SUCCESSOR_APPROVED`, while rejection returns it to `OPEN` and clears the
    `successor_candidate_id`, restarting the successor search."

    Design: Difficulty/non_linear_state_machine/exit_case_successor_revision_loop
    """
    set_clock()
    ctx, exit_case, _ = _setup_exit_with_proposed_successor(api)
    resp = api.reject_successor(ctx["operator"]["id"], exit_case["id"], SC)
    reopened = validate_success(resp)
    assert reopened["exit_status"] == "OPEN"
    assert reopened["successor_candidate_id"] is None


def test_repropose_successor_after_rejection_succeeds(api):
    """PRD §3.11: "rejection returns it to `OPEN` and clears the
    `successor_candidate_id`, restarting the successor search."
    PRD §3.11: "A valid proposal moves the case to `SUCCESSOR_PENDING`."

    Design: Difficulty/non_linear_state_machine/exit_case_successor_revision_loop
    """
    set_clock()
    ctx, exit_case, successor_candidate = _setup_exit_with_proposed_successor(api)
    validate_success(api.reject_successor(ctx["operator"]["id"], exit_case["id"], SC))
    resp = api.propose_successor(
        ctx["operator"]["id"], exit_case["id"],
        {"successor_candidate_id": successor_candidate["id"]}, FC,
    )
    again = validate_success(resp)
    assert again["exit_status"] == "SUCCESSOR_PENDING"
    assert again["successor_candidate_id"] == successor_candidate["id"]
