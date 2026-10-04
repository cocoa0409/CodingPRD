"""Write-down decisions: provisional-vs-NRV dual valuation, terminal
lockdown, state-beats-segregation ordering, segregation of duties, and the
role boundary on the decision endpoint (PRD sections 2.8, 3.8)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_error, validate_success,
    write_down_decision_payload,
    make_demand_planner_headers, make_finance_controller_headers,
    setup_recalled_batch, setup_proposed_recall_write_down,
    setup_posted_recall_write_down,
    propose_write_down, post_write_down, reject_write_down,
    decide_write_down,
    fetch_batch, fetch_write_down,
    assert_write_down_amounts,
)


def test_writedown_provisional_values_full_cost(api):
    """PRD section 3.8: "A valid proposal lands in `PROPOSED` ... and is
    valued provisionally at full cost: `provisional_amount_cents` is the
    quantity multiplied by the batch's `unit_cost_cents_per_case`" — 4 cases
    at 4250 cents per case is 17000 — and "`final_amount_cents` stays null
    until the write-down is posted".

    Design: Difficulty/dual_variant_calc/dvc_writedown_provisional_vs_nrv_final
    """
    ctx = setup_recalled_batch(invoiced_unit_cost_cents=465,
                               product_overrides={
                                   "product_code": "PROD-WD-1"})
    assert ctx["batch"]["unit_cost_cents_per_case"] == 4250
    wd = propose_write_down(ctx["batch"]["id"], quantity_cases=4,
                            reason="RECALL", proposer_user_id="planner-1")
    assert wd["status"] == "PROPOSED"
    assert wd["provisional_amount_cents"] == 17000
    assert wd["final_amount_cents"] is None
    assert_write_down_amounts(wd, ctx["batch"])


def test_writedown_posting_values_nrv_unrecoverable_portion(api):
    """PRD section 3.8: "Posting (`PROPOSED` → `POSTED`) computes
    `final_amount_cents` as the quantity multiplied by the unrecoverable
    portion of unit cost — the batch's `unit_cost_cents_per_case` minus the
    channel's net realizable value per case, floored at zero per case: ...
    1500 cents for `RETAIL_FROZEN`" — 4 x max(0, 4250 - 1500) = 11000,
    differing from the 17000 provisional — "and consumes the cases: the
    batch's `available_cases` drops by the quantity, its `written_off_cases`
    rises by the same amount".

    Design: Difficulty/dual_variant_calc/dvc_writedown_provisional_vs_nrv_final
    """
    ctx = setup_recalled_batch(invoiced_unit_cost_cents=465,
                               product_overrides={
                                   "product_code": "PROD-WD-1"})
    wd = propose_write_down(ctx["batch"]["id"], quantity_cases=4,
                            reason="RECALL", proposer_user_id="planner-1")
    wd = post_write_down(wd["id"], "fin-1")
    assert wd["status"] == "POSTED"
    assert wd["provisional_amount_cents"] == 17000
    assert wd["final_amount_cents"] == 11000
    assert wd["provisional_amount_cents"] != wd["final_amount_cents"]
    batch = fetch_batch(ctx["batch"]["id"])
    assert batch["available_cases"] == 6
    assert batch["written_off_cases"] == 4


def test_decision_on_posted_writedown_reports_state_not_segregation(api):
    """PRD section 2.8: "Validations run in a fixed cascade and the first
    failing check determines the error response" — "5. **State legality.**"
    runs ahead of "6. **Compliance gates.** ... segregation of duties on
    write-down decisions (`ERR_SEGREGATION_OF_DUTIES`)". PRD section 3.8:
    "only a `PROPOSED` write-down can be decided (`ERR_INVALID_STATE`)". A
    decision on an already-POSTED write-down therefore reports
    ERR_INVALID_STATE even when the caller IS the original proposer.

    Design: Difficulty/priority_pair_validation_conflict/pvc_state_beats_segregation_on_decision
    """
    ctx = setup_posted_recall_write_down(
        quantity_cases=2, proposer_user_id="planner-1",
        decider_user_id="fin-1", invoiced_unit_cost_cents=465,
        product_overrides={"product_code": "PROD-PV-1"})
    resp = api.decide_write_down(
        ctx["write_down"]["id"], write_down_decision_payload("REJECTED"),
        make_finance_controller_headers("planner-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert fetch_write_down(ctx["write_down"]["id"])["status"] == "POSTED"


def test_decision_on_terminal_writedown_fails_for_any_decider(api):
    """PRD section 3.8: "only a `PROPOSED` write-down can be decided
    (`ERR_INVALID_STATE`)" — a POSTED write-down is terminal (PRD section 2.8
    tier 5: "terminal states reject every further transition"), so the same
    decision fails identically for a decider whose identity does NOT violate
    segregation of duties.

    Design: Difficulty/priority_pair_validation_conflict/pvc_state_beats_segregation_on_decision
    """
    ctx = setup_posted_recall_write_down(
        quantity_cases=2, proposer_user_id="planner-1",
        decider_user_id="fin-1", invoiced_unit_cost_cents=465,
        product_overrides={"product_code": "PROD-PV-1"})
    resp = api.decide_write_down(
        ctx["write_down"]["id"], write_down_decision_payload("REJECTED"),
        make_finance_controller_headers("fin-2"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert fetch_write_down(ctx["write_down"]["id"])["status"] == "POSTED"


def test_rejected_writedown_is_terminal(api):
    """PRD section 3.8: "only a `PROPOSED` write-down can be decided
    (`ERR_INVALID_STATE`)" and "Rejection (`PROPOSED` → `REJECTED`) leaves
    the batch untouched" — a REJECTED write-down refuses a later POSTED
    decision, keeps a null `final_amount_cents`, and consumed no cases.

    Design: Corner/state_machines/cn_sm_writedown_rejected_is_terminal
    """
    ctx = setup_proposed_recall_write_down(quantity_cases=1)
    reject_write_down(ctx["write_down"]["id"], "fin-1")
    resp = api.decide_write_down(
        ctx["write_down"]["id"], write_down_decision_payload("POSTED"),
        make_finance_controller_headers("fin-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    wd = fetch_write_down(ctx["write_down"]["id"])
    assert wd["status"] == "REJECTED"
    assert wd["final_amount_cents"] is None
    assert fetch_batch(ctx["batch"]["id"])["available_cases"] == 10


def test_decider_must_not_be_the_proposer(api):
    """PRD section 3.8: "segregation of duties rejects any decision whose
    `X-User-ID` equals the write-down's `proposed_by_user_id` with
    `ERR_SEGREGATION_OF_DUTIES` (403)" — the check is on the user identity,
    not the role: a FinanceController carrying the proposer's id is refused.

    Design: Corner/validations/cn_val_writedown_segregation_of_duties
    """
    ctx = setup_proposed_recall_write_down(quantity_cases=1,
                                           proposer_user_id="planner-1")
    resp = api.decide_write_down(
        ctx["write_down"]["id"], write_down_decision_payload("POSTED"),
        make_finance_controller_headers("planner-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert fetch_write_down(ctx["write_down"]["id"])["status"] == "PROPOSED"


def test_demand_planner_cannot_decide_writedown(api):
    """PRD section 4: the write-down decision endpoint admits only
    `FinanceController`. PRD section 2.1: "when the presented role is not
    among the roles an endpoint admits, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)" — a DemandPlanner never reaches the
    segregation check at all.

    Design: Corner/rbac/cn_rbac_demandplanner_cannot_decide_writedown
    """
    ctx = setup_proposed_recall_write_down(quantity_cases=1,
                                           proposer_user_id="planner-1")
    resp = api.decide_write_down(
        ctx["write_down"]["id"], write_down_decision_payload("POSTED"),
        make_demand_planner_headers("planner-9"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert fetch_write_down(ctx["write_down"]["id"])["status"] == "PROPOSED"
