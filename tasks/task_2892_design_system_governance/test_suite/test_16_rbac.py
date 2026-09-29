"""
Authority as a set of disjoint capabilities rather than a ladder.

None of the writing roles contains another, the two reviewer roles are peers,
and the segregation rule keys on the operator rather than on the hat the
operator happens to be wearing.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_REVIEW_STAGE_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_page_meta,
)
from test_helpers.constants import (
    KIND_ENHANCEMENT,
    MATURITY_BETA,
    MATURITY_EXPERIMENTAL,
    PROPOSAL_DESIGN_CRITIQUE,
    PROPOSAL_ENGINEERING_REVIEW,
    PROPOSAL_READY_FOR_ACCEPTANCE,
    STAGE_DESIGN_CRITIQUE,
    STAGE_ENGINEERING_REVIEW,
    VERDICT_APPROVE,
    VERDICT_BLOCK,
)
from test_helpers.factories import (
    leaf_token_payload,
    promote_payload,
    review_payload,
)
from test_helpers.fixtures import (
    governance_base,
    make_proposal,
    make_release,
    read_component,
    read_proposal,
    read_token_set,
    submit,
)
from test_helpers.test_users import (
    CRITIC_TWO_USER_ID,
    CRITIC_USER_ID,
    DUAL_ROLE_USER_ID,
    ENGINEER_USER_ID,
    make_contributing_team_headers,
    make_design_critique_reviewer_headers,
    make_design_system_lead_headers,
    make_engineering_reviewer_headers,
    make_system_admin_headers,
)


def _proposal_at_the_design_critique_gate(api, **base_overrides):
    """
    A submitted enhancement proposal waiting on its first reviewer.

    The proposal declares `touches_public_api` false, which is the ordinary
    enhancement shape and keeps the evidence requirement to the base set.
    """
    base = governance_base(
        api,
        team_slug="design-guild",
        component_name="Badge",
        component_slug="badge",
        **base_overrides,
    )
    proposal = make_proposal(
        api,
        base["team_id"],
        base["component_id"],
        base["token_set_id"],
        title="Badge density scale",
        proposal_kind=KIND_ENHANCEMENT,
        touches_public_api=False,
    )
    submitted = submit(api, proposal["id"], base["team_id"])
    assert submitted["state"] == PROPOSAL_DESIGN_CRITIQUE
    base.update({"proposal_id": proposal["id"], "submitted": submitted})
    return base


def test_each_roles_exclusive_operations_are_closed_to_the_other_roles(api):
    """Denial runs in every direction, because no role contains another.

    PRD: "If `X-User-Role` is not one of those five strings, or is a valid role that does not appear in the called endpoint's authorised-role list in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD: "`X-User-Role` is one of the five declared roles **and** appears in the called endpoint's authorised-role list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

    A contributing team cannot promote maturity, an administrator cannot mint a
    token, and a lead cannot publish a release; all three refusals leave their
    targets exactly as they were.

    Design: Corner/rbac/each_roles_exclusive_operations_are_closed_to_the_other_roles
    """
    base = governance_base(
        api, team_slug="design-guild", component_name="Badge", component_slug="badge"
    )
    component_id = base["component_id"]
    set_id = base["token_set_id"]
    release = make_release(api, "1.4.0")

    validate_error(
        api.promote_maturity(
            component_id,
            promote_payload(MATURITY_BETA),
            make_contributing_team_headers(base["team_id"]),
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_token(
            leaf_token_payload(set_id, "color.surface", "#FFFFFF", 1),
            make_system_admin_headers(),
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.publish_release(release["id"], make_design_system_lead_headers()),
        ERR_UNAUTHORIZED,
        403,
    )

    assert read_component(api, component_id)["maturity_level"] == MATURITY_EXPERIMENTAL
    assert_fields(
        read_token_set(api, set_id), {"version": 1, "token_count": 0}, "token set"
    )
    _, carried_meta = validate_paginated(
        api.list_proposals(
            make_design_system_lead_headers(),
            params={"released_in_release_id": release["id"]},
        )
    )
    assert_page_meta(carried_meta, total_count=0, has_more=False)


def test_the_two_reviewer_roles_own_disjoint_stages_and_neither_outranks_the_other(api):
    """Sharing one endpoint is not sharing authority over its gates.

    PRD: "The `stage` in the payload must match the gate implied by the proposal's current `state` and the acting role must be that gate's reviewer role, otherwise `ERR_REVIEW_STAGE_MISMATCH`."

    PRD: "The review's `stage` matches the gate implied by the proposal's current `state` — `DESIGN_CRITIQUE` only from `DESIGN_CRITIQUE`, `ENGINEERING_REVIEW` only from `ENGINEERING_REVIEW` — the acting role is the reviewer role for that stage, and a `BLOCK` verdict is accepted only at the `ENGINEERING_REVIEW` stage. Otherwise `ERR_REVIEW_STAGE_MISMATCH` (409). Applies to `POST /design-system/contribution-proposals/{id}/reviews`."

    The critique reviewer is refused at the engineering gate even though the
    proposal really is sitting there, which is what distinguishes a role rule
    from a state rule.

    Design: Corner/rbac/reviewer_roles_are_peers_with_disjoint_stage_authority
    """
    scenario = _proposal_at_the_design_critique_gate(api)
    proposal_id = scenario["proposal_id"]

    critique = validate_success(
        api.create_review(
            proposal_id,
            review_payload(
                STAGE_DESIGN_CRITIQUE, VERDICT_APPROVE, "density scale reads well"
            ),
            make_design_critique_reviewer_headers(CRITIC_USER_ID),
        ),
        201,
    )
    assert critique["resulting_proposal_state"] == PROPOSAL_ENGINEERING_REVIEW

    validate_error(
        api.create_review(
            proposal_id,
            review_payload(
                STAGE_ENGINEERING_REVIEW, VERDICT_APPROVE, "looks buildable to me"
            ),
            make_design_critique_reviewer_headers(CRITIC_TWO_USER_ID),
        ),
        ERR_REVIEW_STAGE_MISMATCH,
        409,
    )
    validate_error(
        api.create_review(
            proposal_id,
            review_payload(
                STAGE_DESIGN_CRITIQUE, VERDICT_APPROVE, "the visuals seem fine"
            ),
            make_engineering_reviewer_headers(ENGINEER_USER_ID),
        ),
        ERR_REVIEW_STAGE_MISMATCH,
        409,
    )

    seen_by_engineer = validate_success(
        api.get_proposal(proposal_id, make_engineering_reviewer_headers())
    )
    assert seen_by_engineer["state"] == PROPOSAL_ENGINEERING_REVIEW

    rows, meta = validate_paginated(
        api.list_reviews(
            proposal_id,
            make_design_critique_reviewer_headers(),
            params={"limit": 100, "offset": 0},
        )
    )
    assert_page_meta(meta, total_count=1, has_more=False)
    assert_fields(
        rows[0],
        {"stage": STAGE_DESIGN_CRITIQUE, "verdict": VERDICT_APPROVE},
        "the only recorded verdict",
    )


def test_one_operator_cannot_hold_both_review_gates_on_one_proposal(api):
    """The block keys on the operator's id, not on the role it presents.

    PRD: "Segregation of duties: the reviewer's `X-User-ID` differs from the user id already recorded for the *other* review stage on that proposal — `design_critique_reviewer_user_id` when filing `ENGINEERING_REVIEW`, `engineering_reviewer_user_id` when filing `DESIGN_CRITIQUE`. Otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies to `POST /design-system/contribution-proposals/{id}/reviews`, and the same code guards the accepting lead's identity on `POST /design-system/contribution-proposals/{id}/accept`."

    PRD: "Segregation of duties applies at both gates, as specified in §2.1: the engineering verdict's `X-User-ID` must differ from the recorded `design_critique_reviewer_user_id`, and the design-critique verdict's `X-User-ID` must differ from the recorded `engineering_reviewer_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

    The second attempt names the correct gate with the correct role, so nothing
    but the operator's identity is left to refuse it — and a different operator
    at that same gate is admitted.

    Design: Corner/rbac/one_user_id_cannot_hold_both_review_gates_on_one_proposal
    """
    scenario = _proposal_at_the_design_critique_gate(api)
    proposal_id = scenario["proposal_id"]

    critique = validate_success(
        api.create_review(
            proposal_id,
            review_payload(
                STAGE_DESIGN_CRITIQUE, VERDICT_APPROVE, "approved at critique by dual-1"
            ),
            make_design_critique_reviewer_headers(DUAL_ROLE_USER_ID),
        ),
        201,
    )
    assert critique["resulting_proposal_state"] == PROPOSAL_ENGINEERING_REVIEW
    assert_fields(
        read_proposal(api, proposal_id),
        {
            "design_critique_reviewer_user_id": DUAL_ROLE_USER_ID,
            "engineering_reviewer_user_id": None,
        },
        "proposal at the engineering gate",
    )

    validate_error(
        api.create_review(
            proposal_id,
            review_payload(
                STAGE_ENGINEERING_REVIEW, VERDICT_APPROVE, "same person, second hat"
            ),
            make_engineering_reviewer_headers(DUAL_ROLE_USER_ID),
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert_fields(
        read_proposal(api, proposal_id),
        {
            "state": PROPOSAL_ENGINEERING_REVIEW,
            "engineering_reviewer_user_id": None,
        },
        "proposal after the refused verdict",
    )

    independent = validate_success(
        api.create_review(
            proposal_id,
            review_payload(
                STAGE_ENGINEERING_REVIEW,
                VERDICT_APPROVE,
                "independent engineering review",
            ),
            make_engineering_reviewer_headers(ENGINEER_USER_ID),
        ),
        201,
    )
    assert independent["resulting_proposal_state"] == PROPOSAL_READY_FOR_ACCEPTANCE

    _, meta = validate_paginated(
        api.list_reviews(proposal_id, make_design_system_lead_headers())
    )
    assert_page_meta(meta, total_count=2, has_more=False)


def test_the_engineering_gate_cannot_be_reached_or_revisited_out_of_order(api):
    """The chain admits one verdict at a time and never re-opens a closed gate.

    PRD: "The review's `stage` matches the gate implied by the proposal's current `state` — `DESIGN_CRITIQUE` only from `DESIGN_CRITIQUE`, `ENGINEERING_REVIEW` only from `ENGINEERING_REVIEW` — the acting role is the reviewer role for that stage, and a `BLOCK` verdict is accepted only at the `ENGINEERING_REVIEW` stage. Otherwise `ERR_REVIEW_STAGE_MISMATCH` (409). Applies to `POST /design-system/contribution-proposals/{id}/reviews`."

    PRD: "`BLOCK` is available only at the engineering gate; a `BLOCK` offered at the design-critique gate is `ERR_REVIEW_STAGE_MISMATCH`."

    Jumping ahead, blocking at the wrong gate and replaying a gate the chain has
    already left all answer with the one identifier.

    Design: Corner/rbac/the_engineering_gate_cannot_be_reached_or_revisited_out_of_order
    """
    scenario = _proposal_at_the_design_critique_gate(api)
    proposal_id = scenario["proposal_id"]

    validate_error(
        api.create_review(
            proposal_id,
            review_payload(
                STAGE_ENGINEERING_REVIEW, VERDICT_APPROVE, "jumping the queue"
            ),
            make_engineering_reviewer_headers(ENGINEER_USER_ID),
        ),
        ERR_REVIEW_STAGE_MISMATCH,
        409,
    )
    validate_error(
        api.create_review(
            proposal_id,
            review_payload(
                STAGE_DESIGN_CRITIQUE, VERDICT_BLOCK, "blocking at the wrong gate"
            ),
            make_design_critique_reviewer_headers(CRITIC_USER_ID),
        ),
        ERR_REVIEW_STAGE_MISMATCH,
        409,
    )

    accepted = validate_success(
        api.create_review(
            proposal_id,
            review_payload(
                STAGE_DESIGN_CRITIQUE, VERDICT_APPROVE, "critique approved"
            ),
            make_design_critique_reviewer_headers(CRITIC_USER_ID),
        ),
        201,
    )
    assert accepted["resulting_proposal_state"] == PROPOSAL_ENGINEERING_REVIEW

    validate_error(
        api.create_review(
            proposal_id,
            review_payload(
                STAGE_DESIGN_CRITIQUE, VERDICT_APPROVE, "re-approving a closed gate"
            ),
            make_design_critique_reviewer_headers(CRITIC_USER_ID),
        ),
        ERR_REVIEW_STAGE_MISMATCH,
        409,
    )

    rows, meta = validate_paginated(
        api.list_reviews(proposal_id, make_design_system_lead_headers())
    )
    assert_page_meta(meta, total_count=1, has_more=False)
    assert rows[0]["id"] == accepted["id"]
    assert read_proposal(api, proposal_id)["state"] == PROPOSAL_ENGINEERING_REVIEW
