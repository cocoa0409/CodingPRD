"""Training plans: review state gates, the post-decision lock, and the plan
revision budget."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId, factories, fixtures, make_employer_rep_headers


def test_review_plan_on_draft_rejected(api):
    """PRD §3.5: "The plan must be `PLAN_SUBMITTED`, otherwise
    `ERR_PLAN_NOT_SUBMITTED`."

    Design: Corner/state_machines/review_plan_on_draft_rejected
    """
    ns = fixtures.setup_match(api, advance_to="proposed")
    resp = api.review_plan(
        ns.match["id"],
        factories.review_plan_payload("APPROVE"),
        fixtures.make_installation_authority_headers("auth-1"),
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_SUBMITTED)
    after = fixtures.get_match(api, ns.match["id"])
    assert after["match_status"] == "PROPOSED"
    assert after["plan_status"] == "PLAN_DRAFT"


def test_plan_locked_after_installation_decision(api):
    """PRD §3.5: "The match must still be `PROPOSED`, else `ERR_MATCH_NOT_PROPOSED`:
    the plan locks once the installation decides."
    PRD §3.5: "Approval requires the match to be `PROPOSED`
    (`ERR_MATCH_NOT_PROPOSED`), the plan to be `PLAN_APPROVED`
    (`ERR_PLAN_NOT_APPROVED`) — a cross-dimension gate on the same row, tying the
    two parallel state machines together — the employer to be `AUTHORIZED`
    (`ERR_EMPLOYER_NOT_AUTHORIZED`), and the member to still be `ACTIVE_DUTY`
    (`ERR_MEMBER_NOT_ON_ACTIVE_DUTY`)."

    Design: Corner/state_machines/plan_locked_after_installation_decision
    """
    ns = fixtures.setup_match(api, advance_to="installation_approved")

    late_plan = api.submit_plan(
        ns.match["id"],
        factories.submit_plan_payload(
            [{"objective_code": "O9", "description": "Late change", "weight_hours": 5}]
        ),
        make_employer_rep_headers(ns.employer["id"]),
    )
    validate_error(late_plan, ApiErrorId.ERR_MATCH_NOT_PROPOSED)

    second_decision = api.installation_decision(
        ns.match["id"],
        factories.installation_decision_payload("DENY", "changed my mind"),
        fixtures.make_installation_authority_headers("auth-1"),
    )
    validate_error(second_decision, ApiErrorId.ERR_MATCH_NOT_PROPOSED)


def test_max_plan_revisions(api):
    """PRD §3.5: "RETURN moves it to `PLAN_RETURNED` and increments
    `plan_revision_count` by 1. Resubmission out of `PLAN_RETURNED` repeats the full
    submission validation and is allowed only while `plan_revision_count` remains
    below the revision budget of `MAX_PLAN_REVISIONS`, which is 3; a fourth attempt
    is rejected with `ERR_MAX_PLAN_REVISIONS_REACHED`."

    Design: Corner/validations/max_plan_revisions
    """
    ns = fixtures.setup_match(api, advance_to="proposed")
    match_id, employer_id = ns.match["id"], ns.employer["id"]

    for round_no in (1, 2, 3):
        fixtures.submit_plan(
            api, match_id, employer_id,
            [{"objective_code": "O1", "description": f"v{round_no}", "weight_hours": 10}],
        )
        returned = fixtures.review_plan(api, match_id, "RETURN", feedback="add detail")
        assert returned["plan_revision_count"] == round_no
        assert returned["plan_status"] == "PLAN_RETURNED"

    fourth = api.submit_plan(
        match_id,
        factories.submit_plan_payload([{"objective_code": "O1", "description": "v4", "weight_hours": 10}]),
        make_employer_rep_headers(employer_id),
    )
    validate_error(fourth, ApiErrorId.ERR_MAX_PLAN_REVISIONS_REACHED)


def test_approval_requires_approved_plan(api):
    """PRD §3.5: "Approval requires the match to be `PROPOSED`
    (`ERR_MATCH_NOT_PROPOSED`), the plan to be `PLAN_APPROVED`
    (`ERR_PLAN_NOT_APPROVED`) — a cross-dimension gate on the same row, tying the
    two parallel state machines together — the employer to be `AUTHORIZED`
    (`ERR_EMPLOYER_NOT_AUTHORIZED`), and the member to still be `ACTIVE_DUTY`
    (`ERR_MEMBER_NOT_ON_ACTIVE_DUTY`)."
    PRD §3.5: "Denial requires only `PROPOSED` and an `AUTHORIZED` employer — an
    installation may deny a training-free proposal, so `PLAN_APPROVED` is not
    required — but the `reason` is mandatory on DENY, its absence yielding
    `ERR_VALIDATION`."

    Design: Corner/validations/approval_requires_approved_plan
    """
    ns = fixtures.setup_match(api, advance_to="plan_submitted")

    blocked = api.installation_decision(
        ns.match["id"],
        factories.installation_decision_payload("APPROVE"),
        fixtures.make_installation_authority_headers("auth-1"),
    )
    validate_error(blocked, ApiErrorId.ERR_PLAN_NOT_APPROVED)
    assert fixtures.get_match(api, ns.match["id"])["match_status"] == "PROPOSED"

    denied = fixtures.installation_decision(
        api, ns.match["id"], "DENY", reason="installation quota exhausted"
    )
    assert denied["match_status"] == "INSTALLATION_DENIED", "the plan gate guards approval only"
    assert fixtures.get_opening(api, ns.opening["id"])["filled_count"] == 0, "denial releases the slot"
