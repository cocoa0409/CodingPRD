"""Cyclic and multi-dimensional state graphs: the bounded proposal revision
loop, and the lease's two independent status dimensions."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents_equals,
    assert_fields,
    assert_lease_state,
    assert_null,
    assert_pct_equals,
    assert_status,
)
from test_helpers.test_users import specialist_headers


def _proposal_after_two_revision_rounds(api):
    """A proposal that has traversed SUBMITTED -> UNDER_REVIEW ->
    REVISION_REQUESTED -> SUBMITTED twice and is UNDER_REVIEW again."""
    ctx = X.setup_issued_prospectus(api)
    proposal = X.submit_proposal(api, ctx["prospectus_id"], ctx["offeror_id"])
    ctx["proposal_id"] = proposal["id"]
    X.begin_review(api, proposal["id"])

    rounds = (
        {
            "offered_franchise_fee_pct": 5.25,
            "proposed_capital_investment_cents": 31000000,
            "proposed_annual_guarantee_cents": 6000000,
        },
        {
            "offered_franchise_fee_pct": 5.50,
            "proposed_capital_investment_cents": 32000000,
            "proposed_annual_guarantee_cents": 6500000,
        },
    )
    for revision in rounds:
        validate_success(api.request_revision(proposal["id"], specialist_headers()))
        validate_success(
            api.resubmit_proposal(
                proposal["id"],
                F.resubmit_proposal_payload(**revision),
                ctx["offeror_headers"],
            )
        )
        X.begin_review(api, proposal["id"])
    return ctx


def test_third_revision_request_is_refused_at_the_revision_limit(api):
    """PRD §3.3: "Three conditions guard that move, in order: the proposal's `evaluation_count` must still be 0, because once any panelist has filed a score sheet the bid is frozen and the attempt fails with `ERR_EVALUATION_ALREADY_STARTED`; the prospectus must still be `ISSUED`, since a revision is pointless once the window has closed; and `revision_round` must be strictly below two, else `ERR_REVISION_LIMIT_REACHED` — an offeror gets two bites and no more."
    PRD §3.3: "The full cycle is therefore `SUBMITTED → UNDER_REVIEW → REVISION_REQUESTED → SUBMITTED`, traversable at most twice."

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_reenters_submitted_then_blocks_third_round
    """
    ctx = _proposal_after_two_revision_rounds(api)

    response = api.request_revision(ctx["proposal_id"], specialist_headers())
    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value, 409)

    proposal = get_success_data(api.get_proposal(ctx["proposal_id"], specialist_headers()))
    assert_status(proposal, "UNDER_REVIEW")
    assert proposal["revision_round"] == 2, proposal["revision_round"]


def test_resubmission_overwrites_exactly_the_three_commercial_figures(api):
    """PRD §3.3: "The offeror closes the loop by resubmitting, moving `REVISION_REQUESTED → SUBMITTED` and overwriting exactly three fields from the request body: `offered_franchise_fee_pct`, `proposed_capital_investment_cents` and `proposed_annual_guarantee_cents`."
    PRD §3.3: "On success `revision_round` rises by one and the proposal's `version` advances by one."

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_reenters_submitted_then_blocks_third_round
    """
    ctx = _proposal_after_two_revision_rounds(api)

    proposal = get_success_data(api.get_proposal(ctx["proposal_id"], specialist_headers()))
    assert_pct_equals(
        proposal["offered_franchise_fee_pct"], "5.50", "offered_franchise_fee_pct"
    )
    assert_cents_equals(
        proposal["proposed_capital_investment_cents"],
        32000000,
        "proposed_capital_investment_cents",
    )
    assert_cents_equals(
        proposal["proposed_annual_guarantee_cents"],
        6500000,
        "proposed_annual_guarantee_cents",
    )
    assert proposal["evaluation_count"] == 0, proposal["evaluation_count"]
    assert proposal["revision_round"] == 2, proposal["revision_round"]


def _lease_cured_once(api):
    """An ACTIVE lease whose single notice has already been cured, so its
    compliance dimension has walked COMPLIANT -> DEFICIENT -> COMPLIANT."""
    ctx = X.setup_active_lease(api)
    action = X.issue_compliance_action(
        api,
        ctx["lease_id"],
        action_type="OPERATING_STANDARD",
        deficiency_note="Lodge rates posted above the approved schedule.",
        cure_deadline="2027-03-04T00:00:00Z",
    )
    X.accept_cure(
        api, action["id"], cure_note="Corrected rate schedule filed and verified."
    )
    ctx["first_action_id"] = action["id"]
    return ctx


def test_second_unrelated_notice_re_enters_the_deficient_compliance_state(api):
    """PRD §3.9: "The action is created in `NOTICE_ISSUED` with `origin` set to `AGENCY_ISSUED` — the value that distinguishes an officer's notice from the `SYSTEM_ISSUED` notices the audit cascade of §3.8 mints — and the lease's `compliance_status` moves `COMPLIANT → DEFICIENT` with its `version` advancing by one."
    PRD §2.10: "Neither dimension is ever read as a precondition for a transition of the other, and they advance on entirely different triggers, so a lease may legitimately be `HOLDOVER` and `DEFICIENT` at the same time, or `ACTIVE` and `DEFAULT`."

    Design: Difficulty/non_linear_state_machine/lease_compliance_dimension_reenters_deficient_while_contract_stays_active
    """
    ctx = _lease_cured_once(api)

    response = api.create_compliance_action(
        F.compliance_action_payload(
            ctx["lease_id"],
            action_type="INSURANCE_LAPSE",
            deficiency_note="Certificate of insurance renewal not on file.",
            cure_deadline="2027-03-20T00:00:00Z",
        ),
        X.exec_officer_headers(),
    )
    validate_success(response, 201)
    action = get_success_data(response)

    assert_status(action, "NOTICE_ISSUED")
    assert_fields(action, {"origin": "AGENCY_ISSUED", "action_type": "INSURANCE_LAPSE"})
    assert_null(action, "reconciliation_id")

    lease = X.read_lease(api, ctx["lease_id"])
    assert_lease_state(lease, contract_status="ACTIVE", compliance_status="DEFICIENT")
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 0, "outstanding_fee_balance_cents"
    )


def test_cured_notice_stays_closed_when_the_lease_falls_deficient_again(api):
    """PRD §3.9: "When the officer accepts a cure, moving the action `NOTICE_ISSUED → CURE_ACCEPTED` and persisting a `cure_note`, the lease returns `DEFICIENT → COMPLIANT` only if no other compliance action on that lease is still in `NOTICE_ISSUED`; if one is, the action closes but the lease stays deficient and its `version` does not move."
    PRD §3.9: "The two status dimensions of §2.10 remain independent right up to the point of default."

    Design: Difficulty/non_linear_state_machine/lease_compliance_dimension_reenters_deficient_while_contract_stays_active
    """
    ctx = _lease_cured_once(api)
    cured = get_success_data(
        api.get_compliance_action(ctx["first_action_id"], X.award_officer_headers())
    )
    assert_status(cured, "CURE_ACCEPTED")
    assert cured["cure_note"] == "Corrected rate schedule filed and verified."
    assert_lease_state(
        X.read_lease(api, ctx["lease_id"]), contract_status="ACTIVE",
        compliance_status="COMPLIANT",
    )

    X.issue_compliance_action(
        api,
        ctx["lease_id"],
        action_type="INSURANCE_LAPSE",
        deficiency_note="Certificate of insurance renewal not on file.",
        cure_deadline="2027-03-20T00:00:00Z",
    )

    still_cured = get_success_data(
        api.get_compliance_action(ctx["first_action_id"], X.award_officer_headers())
    )
    assert_status(still_cured, "CURE_ACCEPTED")
    assert_lease_state(
        X.read_lease(api, ctx["lease_id"]), contract_status="ACTIVE",
        compliance_status="DEFICIENT",
    )
