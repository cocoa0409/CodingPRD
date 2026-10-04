"""Difficulty queue: non_linear_state_machine — cycles and parallel dimensions."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    ApiErrorId,
    application_decision_payload,
    read_loan,
    request_servicing_action,
    servicing_action_decision_payload,
    set_clock,
    setup_declined_application,
    setup_loan_with_t1_released,
    validate_error,
    validate_success,
)


def test_application_reconsideration_cycle_bounded(api):
    """PRD §3.2: "A declined applicant may ask for reconsideration, which moves the application from `DECLINED` back to `DECISION_PENDING`."
    PRD §3.2: "The caller must own the application (`ERR_FORBIDDEN_OWNER`), the application must be in `DECLINED` (else `ERR_APPLICATION_NOT_DECLINED`), and `reconsideration_count` must be below the program maximum of 2 — a request when the count has already reached 2 is rejected with `ERR_RECONSIDERATION_LIMIT` (HTTP 409)."
    PRD §3.2: "Each granted reconsideration increments `reconsideration_count` by 1 and clears `decline_reason` to null."
    PRD §3.2: "Once the count reaches 2, `DECLINED` is absorbing: no transition out remains reachable, since reconsideration fails with `ERR_RECONSIDERATION_LIMIT` and a fresh decision fails with `ERR_APPLICATION_NOT_DECISION_PENDING`."
    PRD §3.3: "A `FAIL` moves the application to `DECLINED`, writing `decline_reason` `CREDIT_FAIL` when `score_pass` was false and `DTI_EXCEEDED` otherwise."

    Design: Difficulty/non_linear_state_machine/application_reconsideration_cycle_bounded
    """
    # Setup: homeowner application (requested 2500000) SUBMITTED, then
    # credit-DECLINED with score 639 (< 640).
    ctx = setup_declined_application(requested_amount_cents=2500000,
                                     credit_score=639)
    app_id = ctx["application"]["id"]
    assert ctx["credit_review"]["verdict"] == "FAIL"
    app = validate_success(api.get_application(app_id, ctx["officer_headers"]),
                           EXPECTED_SUCCESS_STATUS["get_application"])
    assert app["status"] == "DECLINED"
    assert app["decline_reason"] == "CREDIT_FAIL"

    # Cycle 1: DECLINED -> DECISION_PENDING, count 1, reason cleared.
    resp = api.request_reconsideration(app_id, ctx["applicant_headers"])
    app = validate_success(resp, EXPECTED_SUCCESS_STATUS["request_reconsideration"])
    assert app["status"] == "DECISION_PENDING"
    assert app["reconsideration_count"] == 1
    assert app["decline_reason"] is None
    resp = api.decide_application(app_id,
                                  application_decision_payload(decision="DECLINED"),
                                  ctx["approver_headers"])
    validate_success(resp, EXPECTED_SUCCESS_STATUS["decide_application"])

    # Cycle 2: DECLINED -> DECISION_PENDING, count 2.
    resp = api.request_reconsideration(app_id, ctx["applicant_headers"])
    app = validate_success(resp, EXPECTED_SUCCESS_STATUS["request_reconsideration"])
    assert app["status"] == "DECISION_PENDING"
    assert app["reconsideration_count"] == 2
    resp = api.decide_application(app_id,
                                  application_decision_payload(decision="DECLINED"),
                                  ctx["approver_headers"])
    validate_success(resp, EXPECTED_SUCCESS_STATUS["decide_application"])

    # The loop is bounded by the counter: the third request is rejected.
    resp = api.request_reconsideration(app_id, ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_RECONSIDERATION_LIMIT)

    # And DECLINED is absorbing: a fresh decision is rejected too.
    resp = api.decide_application(app_id,
                                  application_decision_payload(decision="DECLINED"),
                                  ctx["approver_headers"])
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_DECISION_PENDING)


def test_loan_lifecycle_x_servicing_parallel_dimensions(api):
    """PRD §3.9: "An approval whose `start_date` has already been reached activates immediately within the same request: the action continues to `ACTIVE` and the loan's `servicing_status` flips to `DEFERRED` or `HARDSHIP` according to the action type."
    PRD §3.9: "Activating a `DEFERMENT` also shifts `next_due_date` forward by the length of the accommodation in days — `end_date` minus `start_date` — while a `HARDSHIP` leaves the due date untouched."
    PRD §2.4: "An `APPROVED` servicing action whose `start_date` has been reached (current instant on or after `start_date`) becomes `ACTIVE` and flips the loan's `servicing_status`; an `ACTIVE` action whose `end_date` has been reached (current instant on or after `end_date`) becomes `EXPIRED` and the loan's `servicing_status` returns to `CURRENT`."
    PRD §3.9: "At 15 or more days past due, and provided no late fee has yet been assessed for that due-date cycle, a late fee of 5 percent (0.05) of `monthly_payment_cents`, rounded half-up to integer cents, is added to `late_fee_balance_cents` — at most one fee per due-date cycle."
    PRD §3.9: "Status boundaries are inclusive at every rung: at 30 or more days past due a `CURRENT` loan becomes `DELINQUENT`; at 120 or more a `DELINQUENT` loan becomes `DEFAULT`; at 180 or more a loan in `DEFAULT` is charged off, moving `lifecycle_status` to `CHARGED_OFF`, which is terminal and accepts no further payments (`ERR_LOAN_NOT_ACTIVE`)."

    Design: Difficulty/non_linear_state_machine/loan_lifecycle_x_servicing_parallel_dimensions
    """
    # Setup: homeowner loan approved 20000000, accepted 2026-11-01; stage 1
    # released 2026-11-01 -> next_due_date 2027-12-01 (release + 13 months).
    ctx = setup_loan_with_t1_released()
    loan_id = ctx["loan"]["id"]

    # Trigger 1: DEFERMENT [2026-11-01, 2026-12-02) approved with start_date
    # already reached -> activates immediately within the same request.
    action = request_servicing_action(ctx, action_type="DEFERMENT",
                                      start_date="2026-11-01T00:00:00Z",
                                      end_date="2026-12-02T00:00:00Z")
    resp = api.decide_servicing_action(
        action["id"], servicing_action_decision_payload(decision="APPROVED"),
        ctx["servicing_headers"])
    decided = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["decide_servicing_action"])
    assert decided["status"] == "ACTIVE"

    loan = read_loan(ctx)
    # Parallel dimensions: servicing flips while lifecycle stays ACTIVE.
    assert loan["servicing_status"] == "DEFERRED"
    assert loan["lifecycle_status"] == "ACTIVE"
    # Window length 2026-11-01 -> 2026-12-02 is 31 days: 2027-12-01 + 31 days.
    assert loan["next_due_date"].startswith("2028-01-01T00:00:00")

    # Trigger 2: clock reaches end_date -> the sweep expires the action.
    set_clock("2026-12-02T00:00:00Z", ctx["admin_headers"])
    loan = read_loan(ctx)
    assert loan["servicing_status"] == "CURRENT"
    assert loan["lifecycle_status"] == "ACTIVE"
    actions = validate_success(
        api.list_servicing_actions(loan_id, ctx["servicing_headers"]),
        EXPECTED_SUCCESS_STATUS["list_servicing_actions"])
    assert [a for a in actions if a["id"] == action["id"]][0]["status"] == "EXPIRED"

    # Trigger 3: clock to 2028-01-31 — exactly 30 days past the shifted
    # next_due_date 2028-01-01 (inclusive boundary qualifies as DELINQUENT).
    set_clock("2028-01-31T00:00:00Z", ctx["admin_headers"])
    loan = read_loan(ctx)
    assert loan["days_past_due"] == 30
    assert loan["servicing_status"] == "DELINQUENT"
    # Late fee: round_half_up(0.05 * 88352) = round_half_up(4417.6) = 4418.
    assert loan["late_fee_balance_cents"] == 4418
    # Lifecycle never left ACTIVE through the servicing-status cycle.
    assert loan["lifecycle_status"] == "ACTIVE"
