"""The three executions, the title swap and the reversal that undoes it."""

from test_helpers import (
    assert_renewal_decision,
    assert_subscription,
    decide_payload,
    diagnose_and_resolve,
    execute_decision,
    read_commitment,
    read_member,
    read_subscription,
    report_off_campus_incidents,
    setup_decided_decision,
    setup_executed_restructure,
    setup_restructure_ready,
    validate_error,
    validate_paginated,
    validate_success,
)


def _read_decision(api, headers, subscription_id, decision_id):
    """One renewal decision of a subscription, read back through its listing."""
    rows, _ = validate_paginated(
        api.list_renewal_decisions(subscription_id, headers))
    matching = [row for row in rows if row["id"] == decision_id]
    assert len(matching) == 1, "the decision under test is on the subscription"
    return matching[0]


def test_renew_execution_applies_the_inflation_cap_and_rolls_the_term(api, admin):
    """The capped offer becomes the price and the term moves on by a year.

    PRD: "The decision advances `DECIDED_RENEW → EXECUTED` and the subscription's
    contract axis takes a self-loop from `ACTIVE` back to `ACTIVE` while its books
    roll forward: `negotiated_price_cents` is replaced by the decision's
    `offer_price_cents`; `term_start` becomes the previous `term_end` plus one day
    and `term_end` becomes the previous `term_end` plus one year, with
    `notice_deadline_date` recomputed from the new `term_end` and the product's
    `cancellation_notice_days`; both `sla_credit_cents` and `degrade_count` are
    reset to 0, because the credit has just been consumed by the offer; and
    `renewal_term_count` is incremented by 1."

    PRD: "Cap the increase: `capped_increase_pct` is the smaller of the decision's
    `vendor_requested_increase_pct` and the product's `inflation_cap_pct`."

    Design: Corner/calculations/renew_execution_applies_the_inflation_cap_and_rolls_the_term
    """
    scenario = setup_decided_decision("RENEW", vendor_requested_increase_pct=12.00,
                                      decide_overrides={"accept_capped_offer": True})
    subscription_id = scenario["subscription"]["id"]
    decision = scenario["decision"]
    assert float(decision["capped_increase_pct"]) == 5.00
    assert decision["cost_per_use_band"] == "NO_USE", "no usage was ever filed"
    assert decision["cost_per_use_cents"] is None
    assert decision["loyalty_credit_cents"] == 0
    assert decision["sla_credit_applied_cents"] == 0
    assert decision["offer_price_cents"] == 9450000, "9,000,000 escalated by five percent"

    response = api.execute_renewal(decision["id"], admin)
    data = validate_success(response)

    assert_renewal_decision(data)
    assert data["status"] == "EXECUTED"

    subscription = read_subscription(subscription_id)
    assert_subscription(subscription)
    assert subscription["negotiated_price_cents"] == 9450000
    assert subscription["term_start"] == "2028-01-01", "the day after the old term_end"
    assert subscription["term_end"] == "2028-12-31"
    assert subscription["notice_deadline_date"] == "2028-10-02", (
        "the new term_end less the ninety days of notice"
    )
    assert subscription["renewal_term_count"] == 1
    assert subscription["sla_credit_cents"] == 0
    assert subscription["degrade_count"] == 0
    assert subscription["contract_status"] == "ACTIVE", "the contract axis self-loops"

    assert read_commitment(scenario["commitment"]["id"])["tier_price_cents"] == 4500000
    assert read_member(scenario["member"]["id"])["annual_committed_cents"] == 4500000


def test_renew_execution_needs_no_archival_check(api, admin):
    """The archival and deadline gates are scoped to cancellations only.

    PRD: "**Verified archival deposit before cancellation** —
    `ERR_ARCHIVAL_DEPOSIT_UNVERIFIED` (409), when executing a decision whose
    `resolved_action` is `CANCEL`."

    PRD: "**Cancellation notice deadline** — `ERR_NOTICE_DEADLINE_PASSED` (409),
    when executing a decision whose `resolved_action` is `CANCEL`."

    Design: Corner/validations/renew_execution_needs_no_archival_check
    """
    scenario = setup_decided_decision("RENEW")
    subscription_id = scenario["subscription"]["id"]
    assert scenario["decision"]["offer_price_cents"] == 9000000, "no increase was asked"

    _, meta = validate_paginated(api.list_archival_checks(subscription_id, admin))
    assert meta["total_count"] == 0, "nothing was ever deposited or attested"

    response = api.execute_renewal(scenario["decision"]["id"], admin)
    data = validate_success(response)

    assert data["status"] == "EXECUTED"
    assert data["resolved_action"] == "RENEW"

    subscription = read_subscription(subscription_id)
    assert subscription["negotiated_price_cents"] == 9000000
    assert subscription["term_start"] == "2028-01-01"
    assert subscription["term_end"] == "2028-12-31"
    assert subscription["notice_deadline_date"] == "2028-10-02"
    assert subscription["renewal_term_count"] == 1
    assert subscription["contract_status"] == "ACTIVE"


def test_restructure_decide_with_an_overlapping_title_swap_is_rejected(api, admin):
    """A title that leaves and arrives at once is not a swap.

    PRD: "**The restructure branch** additionally requires a well-formed title
    swap: `titles_out` and `titles_in` must both be non-empty, neither may contain a
    duplicate identifier within itself, and the two may not share any identifier
    with each other; and `delta_price_cents` must be present on the request,
    carrying the price adjustment the publisher attached to the swap."

    PRD: "Any of those failing is `ERR_TITLE_SWAP_INVALID` (422)."

    Design: Corner/validations/restructure_decide_with_an_overlapping_title_swap_is_rejected
    """
    scenario = setup_restructure_ready(titles_out=["T-0001", "T-0002"],
                                       titles_in=["T-0002"], decide_now=False)
    subscription_id = scenario["subscription"]["id"]
    decision_id = scenario["decision"]["id"]
    assert scenario["decision"]["status"] == "VOTING"

    response = api.decide_renewal(
        decision_id, decide_payload("RESTRUCTURE", delta_price_cents=250000), admin)
    validate_error(response, "ERR_TITLE_SWAP_INVALID", 422)

    stored = _read_decision(api, admin, subscription_id, decision_id)
    assert stored["status"] == "VOTING", "the fork never ran"
    assert stored["resolved_action"] is None
    assert stored["delta_price_cents"] is None, "no price adjustment was recorded"
    assert stored["quorum_met"] is True, "only the swap rule blocked the decision"

    assert read_subscription(subscription_id)["entitled_title_count"] == 400


def test_restructure_execution_below_the_title_floor_is_rejected(api, admin):
    """A swap that would empty the package is refused at execution time.

    PRD: "The swap must also leave the consortium with something: the resulting
    `entitled_title_count` must be at least 1 title, otherwise
    `ERR_TITLE_COUNT_FLOOR_BREACHED` (409)."

    PRD: "the subscription's `entitled_title_count` becomes its current value less
    the number of identifiers in `titles_out` plus the number of identifiers in
    `titles_in`"

    Design: Corner/validations/restructure_execution_below_the_title_floor_is_rejected
    """
    scenario = setup_restructure_ready(titles_out=["T-0001", "T-0002", "T-0003"],
                                       titles_in=["T-9001"], delta_price_cents=0,
                                       product_overrides={"title_count": 2})
    subscription_id = scenario["subscription"]["id"]
    decision_id = scenario["decision"]["id"]
    assert scenario["subscription"]["entitled_title_count"] == 2
    assert scenario["decision"]["status"] == "DECIDED_RESTRUCTURE", (
        "the swap lists themselves are well formed"
    )

    response = api.execute_renewal(decision_id, admin)
    validate_error(response, "ERR_TITLE_COUNT_FLOOR_BREACHED", 409)

    stored = _read_decision(api, admin, subscription_id, decision_id)
    assert stored["status"] == "DECIDED_RESTRUCTURE", "the execution moved nothing"

    subscription = read_subscription(subscription_id)
    assert subscription["entitled_title_count"] == 2, (
        "2 - 3 + 1 would have been 0 titles, below the floor of one"
    )
    assert subscription["negotiated_price_cents"] == 9000000
    assert read_commitment(scenario["commitment"]["id"])["tier_price_cents"] == 4500000


def test_revert_restructure_on_a_renew_execution_is_rejected(api, admin):
    """Reverting keys on the resolved action, not merely on the EXECUTED status.

    PRD: "Reverting requires the decision to be `EXECUTED` with `resolved_action` of
    `RESTRUCTURE` and the subscription's `contract_status` to be `ACTIVE`; attempting
    to revert a decision whose resolved action was anything else is
    `ERR_RENEWAL_INVALID_STATE` (409)."

    Design: Corner/endpoints/revert_restructure_on_a_renew_execution_is_rejected
    """
    scenario = setup_decided_decision("RENEW")
    subscription_id = scenario["subscription"]["id"]
    executed = execute_decision(scenario["decision"]["id"])
    assert executed["status"] == "EXECUTED"
    assert executed["resolved_action"] == "RENEW"

    response = api.revert_restructure(executed["id"], admin)
    validate_error(response, "ERR_RENEWAL_INVALID_STATE", 409)

    stored = _read_decision(api, admin, subscription_id, executed["id"])
    assert stored["status"] == "EXECUTED", "the refusal did not move the decision"
    assert stored["resolved_action"] == "RENEW"

    subscription = read_subscription(subscription_id)
    assert subscription["term_start"] == "2028-01-01", "the term roll was not undone"
    assert subscription["term_end"] == "2028-12-31"
    assert subscription["negotiated_price_cents"] == 9000000
    assert subscription["renewal_term_count"] == 1


def test_restructure_execution_rewrites_the_title_list_and_the_price(api, admin):
    """The swap moves three titles out, one in, and adds the publisher's delta.

    PRD: "The decision advances `DECIDED_RESTRUCTURE → EXECUTED`; the subscription's
    `entitled_title_count` becomes its current value less the number of identifiers
    in `titles_out` plus the number of identifiers in `titles_in`; its
    `negotiated_price_cents` has `delta_price_cents` added to it; and every
    `CONFIRMED` commitment is re-priced by the settled variant with each member's
    `annual_committed_cents` adjusted by its own price delta."

    PRD: "Read as a standing definition, `entitled_title_count` equals the product's
    `title_count` less the total size of `titles_out` plus the total size of
    `titles_in` across every decision on the subscription that is `EXECUTED` with a
    `resolved_action` of `RESTRUCTURE`."

    Design: Difficulty/non_linear_state_machine/restructure_branch_execution_omits_the_renew_branch_side_effects
    """
    scenario = setup_restructure_ready()
    subscription_id = scenario["subscription"]["id"]
    assert scenario["subscription"]["entitled_title_count"] == 400
    assert scenario["decision"]["status"] == "DECIDED_RESTRUCTURE"
    assert scenario["decision"]["delta_price_cents"] == 250000

    response = api.execute_renewal(scenario["decision"]["id"], admin)
    data = validate_success(response)

    assert_renewal_decision(data)
    assert data["status"] == "EXECUTED"
    assert data["resolved_action"] == "RESTRUCTURE"

    subscription = read_subscription(subscription_id)
    assert_subscription(subscription)
    assert subscription["entitled_title_count"] == 398, "400 less three out plus one in"
    assert subscription["negotiated_price_cents"] == 9250000, (
        "the delta of 250,000 was added to the running price"
    )
    assert read_commitment(scenario["commitment"]["id"])["tier_price_cents"] == 4500000, (
        "the sole participant is still alone in the discount schedule"
    )
    assert read_member(scenario["member"]["id"])["annual_committed_cents"] == 4500000


def test_restructure_execution_leaves_the_term_and_the_offer_alone(api, admin):
    """None of the renew branch's bookkeeping fires on the restructure branch.

    PRD: "Execution then carries out whatever was decided, and the three executions
    are as different from one another as the branches were."

    PRD: "**Executing a restructuring** requires the decision to be in
    `DECIDED_RESTRUCTURE`, the subscription's `contract_status` to be `ACTIVE`, and
    its `access_status` to be exactly `CONFIGURED` — a package whose access is
    degraded or suspended is in no condition to have its title list rewritten, and an
    attempt yields `ERR_SUBSCRIPTION_ACCESS_INVALID_STATE` (409)."

    Design: Difficulty/non_linear_state_machine/restructure_branch_execution_omits_the_renew_branch_side_effects
    """
    scenario = setup_restructure_ready()
    subscription_id = scenario["subscription"]["id"]
    decision = validate_success(
        api.execute_renewal(scenario["decision"]["id"], admin))
    assert decision["offer_price_cents"] == 9000000, (
        "the offer was computed when the vote opened and asked for no increase"
    )

    subscription = read_subscription(subscription_id)
    assert subscription["renewal_term_count"] == 0, "no renewal term was consumed"
    assert subscription["term_start"] == "2027-01-01", "the term did not roll forward"
    assert subscription["term_end"] == "2027-12-31"
    assert subscription["notice_deadline_date"] == "2027-10-02", (
        "the deadline is still derived from the original term_end"
    )
    assert subscription["contract_status"] == "ACTIVE"
    assert subscription["access_status"] == "CONFIGURED", (
        "the precondition the branch demanded is unchanged by the execution"
    )
    assert subscription["negotiated_price_cents"] == 9250000
    assert subscription["negotiated_price_cents"] != decision["offer_price_cents"], (
        "the restructure branch spends the delta and ignores the renewal offer"
    )


def _restructure_ready_but_degraded():
    """A DECIDED_RESTRUCTURE decision whose subscription has fallen to DEGRADED."""
    scenario = setup_restructure_ready()
    scenario["incidents"] = report_off_campus_incidents(
        scenario["subscription"]["id"], scenario["member"]["id"], 6)
    return scenario


def test_restructure_execution_is_refused_while_the_access_axis_is_degraded(api, admin):
    """A contract axis in perfect order is not enough when access has fallen away.

    PRD: "When a recomputation triggered by an incident report or a reopen leaves the
    score **strictly below** 60 while the subscription's `access_status` is
    `CONFIGURED`, the axis advances `CONFIGURED → DEGRADED`."

    PRD: "a package whose access is degraded or suspended is in no condition to have
    its title list rewritten, and an attempt yields
    `ERR_SUBSCRIPTION_ACCESS_INVALID_STATE` (409)"

    Design: Difficulty/cross_entity_state_dependency/restructure_execution_rejected_while_the_access_axis_is_degraded
    """
    scenario = _restructure_ready_but_degraded()
    subscription_id = scenario["subscription"]["id"]
    decision_id = scenario["decision"]["id"]

    degraded = read_subscription(subscription_id)
    assert degraded["access_health_score"] == 52, "six off-campus denials cost 48 points"
    assert degraded["access_status"] == "DEGRADED"
    assert degraded["degrade_count"] == 1
    assert degraded["sla_credit_cents"] == 180000
    assert degraded["contract_status"] == "ACTIVE", "the contract axis is in order"

    response = api.execute_renewal(decision_id, admin)
    validate_error(response, "ERR_SUBSCRIPTION_ACCESS_INVALID_STATE", 409)

    stored = _read_decision(api, admin, subscription_id, decision_id)
    assert stored["status"] == "DECIDED_RESTRUCTURE", "the decision did not advance"

    unchanged = read_subscription(subscription_id)
    assert unchanged["entitled_title_count"] == 400, "no title left the package"
    assert unchanged["negotiated_price_cents"] == 9000000, "no delta was applied"
    assert unchanged["contract_status"] == "ACTIVE"


def test_restoring_the_access_axis_lets_the_same_restructuring_through(api, admin):
    """Resolving two incidents lifts the score back to CONFIGURED and unblocks execution.

    PRD: "When a recomputation triggered by a resolution leaves the score **greater
    than or equal to** 60 while the axis is `DEGRADED`, it advances `DEGRADED →
    CONFIGURED`; a recomputed score of exactly 60 restores `CONFIGURED`."

    PRD: "Each incident whose `status` is exactly `RESOLVED` gives back 5 points of
    recovery."

    Design: Difficulty/cross_entity_state_dependency/restructure_execution_rejected_while_the_access_axis_is_degraded
    """
    scenario = _restructure_ready_but_degraded()
    subscription_id = scenario["subscription"]["id"]
    decision_id = scenario["decision"]["id"]
    validate_error(api.execute_renewal(decision_id, admin),
                   "ERR_SUBSCRIPTION_ACCESS_INVALID_STATE", 409)

    diagnose_and_resolve(scenario["incidents"][0]["id"])
    diagnose_and_resolve(scenario["incidents"][1]["id"])
    restored = read_subscription(subscription_id)
    assert restored["access_health_score"] == 62, "two recoveries give back 5 points each"
    assert restored["access_status"] == "CONFIGURED"
    assert restored["degrade_count"] == 1, "the recovery does not undo the degrade event"

    data = validate_success(api.execute_renewal(decision_id, admin))
    assert data["status"] == "EXECUTED"
    assert data["resolved_action"] == "RESTRUCTURE"

    subscription = read_subscription(subscription_id)
    assert subscription["entitled_title_count"] == 398
    assert subscription["negotiated_price_cents"] == 9250000
    assert subscription["sla_credit_cents"] == 180000, (
        "the restructure execution does not consume the SLA credit"
    )


def test_reverting_a_restructuring_restores_the_title_count_and_the_price(api, admin):
    """The reversal is the exact compensating action of the execution it undoes.

    PRD: "The reversal is the exact compensating action of the execution:
    `entitled_title_count` gains back the number of identifiers in `titles_out` and
    loses the number in `titles_in`, `negotiated_price_cents` has
    `delta_price_cents` subtracted from it, every `CONFIRMED` commitment is
    re-priced by the settled variant with member ledgers adjusted by the deltas, and
    the decision advances `EXECUTED → REVERTED`."

    PRD: "The conserved quantity is the entitled title count: after a revert, it must
    equal exactly what it was before the execution."

    Design: Difficulty/compensating_invariant/reverting_a_restructure_restores_the_title_count_and_the_price
    """
    scenario = setup_executed_restructure()
    subscription_id = scenario["subscription"]["id"]
    assert scenario["decision"]["status"] == "EXECUTED"
    assert scenario["subscription"]["entitled_title_count"] == 398
    assert scenario["subscription"]["negotiated_price_cents"] == 9250000

    response = api.revert_restructure(scenario["decision"]["id"], admin)
    data = validate_success(response)

    assert_renewal_decision(data)
    assert data["status"] == "REVERTED"
    assert data["resolved_action"] == "RESTRUCTURE", "the resolved action is not erased"
    assert data["delta_price_cents"] == 250000

    subscription = read_subscription(subscription_id)
    assert_subscription(subscription)
    assert subscription["entitled_title_count"] == 400, (
        "the three titles came back and the one that arrived left again"
    )
    assert subscription["negotiated_price_cents"] == 9000000, "the delta was subtracted"


def test_a_reverted_restructuring_cannot_be_reverted_a_second_time(api, admin):
    """REVERTED is terminal, so the compensation cannot be applied twice.

    PRD: "`EXECUTED`, `REVERTED` and `SUPERSEDED` are the decision's terminal
    states."

    PRD: "Reverting requires the decision to be `EXECUTED` with `resolved_action` of
    `RESTRUCTURE` and the subscription's `contract_status` to be `ACTIVE`; attempting
    to revert a decision whose resolved action was anything else is
    `ERR_RENEWAL_INVALID_STATE` (409)."

    Design: Difficulty/compensating_invariant/reverting_a_restructure_restores_the_title_count_and_the_price
    """
    scenario = setup_executed_restructure()
    subscription_id = scenario["subscription"]["id"]
    decision_id = scenario["decision"]["id"]
    reverted = validate_success(api.revert_restructure(decision_id, admin))
    assert reverted["status"] == "REVERTED"

    commitment = read_commitment(scenario["commitment"]["id"])
    assert commitment["status"] == "CONFIRMED", "the participant is still on the package"
    assert commitment["tier_price_cents"] == 4500000
    assert read_member(scenario["member"]["id"])["annual_committed_cents"] == 4500000

    subscription = read_subscription(subscription_id)
    assert subscription["renewal_term_count"] == 0, "no term was ever consumed"
    assert subscription["term_end"] == "2027-12-31"
    assert subscription["contract_status"] == "ACTIVE"

    response = api.revert_restructure(decision_id, admin)
    validate_error(response, "ERR_RENEWAL_INVALID_STATE", 409)

    stored = _read_decision(api, admin, subscription_id, decision_id)
    assert stored["status"] == "REVERTED", "the second attempt moved nothing"
    assert read_subscription(subscription_id)["entitled_title_count"] == 400, (
        "the compensating action was not applied a second time"
    )
    assert read_subscription(subscription_id)["negotiated_price_cents"] == 9000000
