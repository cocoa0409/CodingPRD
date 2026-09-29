"""
Cycles in the two pipelines that re-enter states they have already visited.

A proposal can return to design critique and an implementation can return to
shipped, and in both cases the bookkeeping on the way round the loop is not the
bookkeeping of the first pass through it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_ACCEPTANCE_EVIDENCE_INCOMPLETE,
    ERR_BLOCKED_DEPENDENCY,
)
from test_helpers.assertions import assert_append_only_row, assert_fields
from test_helpers.constants import (
    BLOCKED_REASON_NONE,
    BLOCKED_REASON_UPSTREAM_BREAKING_CHANGE,
    COMPAT_COMPATIBLE,
    COVERAGE_NONE,
    COVERAGE_WEB_ONLY,
    EV_A11Y_AUTOMATED,
    EV_A11Y_MANUAL,
    EV_DOC_PAGE,
    EV_TOKEN_COMPLIANCE,
    IMPL_BLOCKED,
    IMPL_SHIPPED,
    KIND_BREAKING_CHANGE,
    KIND_NEW_COMPONENT,
    PLATFORM_WEB,
    PROPOSAL_CHANGES_REQUESTED,
    PROPOSAL_DESIGN_CRITIQUE,
    PROPOSAL_READY_FOR_ACCEPTANCE,
    STAGE_DESIGN_CRITIQUE,
    STAGE_ENGINEERING_REVIEW,
    VERDICT_APPROVE,
    VERDICT_REQUEST_CHANGES,
)
from test_helpers.factories import (
    accept_payload,
    dependency_repin_payload,
    ship_payload,
)
from test_helpers.fixtures import (
    accept,
    file_clean_evidence,
    file_evidence,
    governance_base,
    make_implementation,
    make_proposal,
    make_release,
    provider_and_consumer,
    read_component,
    read_implementation,
    read_proposal,
    read_team,
    review,
    ship,
    submit,
)
from test_helpers.test_users import (
    CRITIC_USER_ID,
    make_contributing_team_headers,
    make_design_system_lead_headers,
)

ROUND_ONE_EVIDENCE = [EV_A11Y_AUTOMATED, EV_A11Y_MANUAL, EV_DOC_PAGE, EV_TOKEN_COMPLIANCE]


def _proposal_sent_back_for_changes(api):
    """
    A new-component proposal that satisfied its round-one evidence gate in full
    and was then sent back by the design critique reviewer.
    """
    base = governance_base(api, component_name="Split Button", component_slug="split-button")
    proposal = make_proposal(
        api,
        base["team_id"],
        base["component_id"],
        base["token_set_id"],
        title="Introduce the split button",
        proposal_kind=KIND_NEW_COMPONENT,
    )
    submitted = submit(api, proposal["id"], base["team_id"])
    assert submitted["required_evidence_kinds"] == ROUND_ONE_EVIDENCE, (
        "a new-component proposal on a component with no shipped platform requires "
        f"exactly the four base kinds, got {submitted['required_evidence_kinds']}"
    )
    filed = file_evidence(api, proposal["id"], base["team_id"], ROUND_ONE_EVIDENCE)
    assert filed["submitted_evidence_kinds"] == ROUND_ONE_EVIDENCE
    sent_back = review(
        api, proposal["id"], STAGE_DESIGN_CRITIQUE, VERDICT_REQUEST_CHANGES
    )
    base.update({"proposal_id": proposal["id"], "first_verdict": sent_back})
    return base


def test_resubmit_prunes_the_evidence_set_to_the_round_durable_kinds(api):
    """A second round keeps only the documentation and migration evidence.

    PRD: "On a resubmit out of `CHANGES_REQUESTED`, `submitted_evidence_kinds` is reduced to its intersection with the two round-durable kinds, `DOC_PAGE` and `MIGRATION_GUIDE`."

    All four required kinds were filed in round 1, yet round 2 opens holding only
    DOC_PAGE while the requirement set itself is untouched.

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_round_two_prunes_non_durable_evidence
    """
    scenario = _proposal_sent_back_for_changes(api)

    verdict = scenario["first_verdict"]
    assert_append_only_row(verdict, "review record")
    assert_fields(
        verdict,
        {
            "stage": STAGE_DESIGN_CRITIQUE,
            "verdict": VERDICT_REQUEST_CHANGES,
            "revision_round": 1,
            "resulting_proposal_state": PROPOSAL_CHANGES_REQUESTED,
            "reviewer_user_id": CRITIC_USER_ID,
        },
        "review record",
    )
    assert read_proposal(api, scenario["proposal_id"])["state"] == PROPOSAL_CHANGES_REQUESTED

    resubmitted = submit(api, scenario["proposal_id"], scenario["team_id"])
    assert_fields(
        resubmitted,
        {
            "state": PROPOSAL_DESIGN_CRITIQUE,
            "revision_round": 2,
            "submitted_evidence_kinds": [EV_DOC_PAGE],
            "required_evidence_kinds": ROUND_ONE_EVIDENCE,
        },
        "proposal",
    )


def test_round_two_acceptance_fails_the_evidence_gate_round_one_had_satisfied(api):
    """The pruned set no longer covers a requirement that never changed.

    PRD: "This is why a proposal that fully satisfied its evidence gate in round 1 can fail acceptance with `ERR_ACCEPTANCE_EVIDENCE_INCOMPLETE` in round 2 without any requirement having changed."

    Round 2 is walked through both gates with no evidence re-filed, and the
    acceptance is refused on the incomplete set.

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_round_two_prunes_non_durable_evidence
    """
    scenario = _proposal_sent_back_for_changes(api)
    proposal_id = scenario["proposal_id"]

    submit(api, proposal_id, scenario["team_id"])
    review(api, proposal_id, STAGE_DESIGN_CRITIQUE, VERDICT_APPROVE)
    engineering_review = review(
        api, proposal_id, STAGE_ENGINEERING_REVIEW, VERDICT_APPROVE
    )
    # Filing a verdict returns the immutable review record, whose
    # `resulting_proposal_state` is the proposal's state right after the verdict.
    assert_fields(
        engineering_review,
        {
            "resulting_proposal_state": PROPOSAL_READY_FOR_ACCEPTANCE,
            "revision_round": 2,
        },
        "review record",
    )
    assert_fields(
        read_proposal(api, proposal_id),
        {"state": PROPOSAL_READY_FOR_ACCEPTANCE, "revision_round": 2},
        "proposal",
    )

    release = make_release(api, "1.4.0")
    component_version = read_component(api, scenario["component_id"])["version"]
    validate_error(
        api.accept_proposal(
            proposal_id,
            accept_payload(release["id"], component_version),
            make_design_system_lead_headers(),
        ),
        ERR_ACCEPTANCE_EVIDENCE_INCOMPLETE,
    )
    still_ready = read_proposal(api, proposal_id)
    assert_fields(
        still_ready,
        {
            "state": PROPOSAL_READY_FOR_ACCEPTANCE,
            "released_in_release_id": None,
            "accepted_at": None,
            "submitted_evidence_kinds": [EV_DOC_PAGE],
        },
        "proposal",
    )


def _consumer_blocked_by_an_upstream_breaking_change(api):
    """
    A consumer whose only shipped implementation has been blocked by the
    acceptance of a breaking change on the provider it pins.
    """
    base = provider_and_consumer(api, pinned_provider_major=1)
    impl = make_implementation(
        api,
        base["consumer_id"],
        base["team_id"],
        platform=PLATFORM_WEB,
        package_name="@ds/menu-button-web",
        package_version="1.0.0",
    )
    file_clean_evidence(api, impl["id"], base["team_id"])
    shipped = ship(api, impl["id"], base["team_id"], package_version="1.0.0")
    assert shipped["status"] == IMPL_SHIPPED
    assert base["dependency"]["compatibility_state"] == COMPAT_COMPATIBLE

    proposal = make_proposal(
        api,
        base["team_id"],
        base["provider_id"],
        base["token_set_id"],
        title="Rename the icon size prop",
        proposal_kind=KIND_BREAKING_CHANGE,
    )
    submitted = submit(api, proposal["id"], base["team_id"])
    file_evidence(
        api, proposal["id"], base["team_id"], list(submitted["required_evidence_kinds"])
    )
    review(api, proposal["id"], STAGE_DESIGN_CRITIQUE, VERDICT_APPROVE)
    review(api, proposal["id"], STAGE_ENGINEERING_REVIEW, VERDICT_APPROVE)
    release = make_release(api, "1.0.0")
    provider_version = read_component(api, base["provider_id"])["version"]
    accept(api, proposal["id"], release["id"], provider_version)

    base.update({"implementation_id": impl["id"], "release_id": release["id"]})
    return base


def test_a_blocked_implementation_cannot_reship_before_the_edge_is_repinned(api):
    """Re-pinning is the first move of the recovery, not an optional one.

    PRD: "Re-pinning is the mandatory first step of a recovery: until the count reaches 0, the consumer's implementations cannot leave `BLOCKED`."

    The cascade has left the implementation BLOCKED, and a ship attempted while
    the consumer still counts one bad edge is refused on the dependency gate.

    Design: Difficulty/non_linear_state_machine/implementation_ship_block_reship_cycle_via_dependency_repin
    """
    scenario = _consumer_blocked_by_an_upstream_breaking_change(api)

    blocked = read_implementation(api, scenario["implementation_id"])
    assert_fields(
        blocked,
        {
            "status": IMPL_BLOCKED,
            "blocked_reason": BLOCKED_REASON_UPSTREAM_BREAKING_CHANGE,
        },
        "implementation",
    )
    consumer = read_component(api, scenario["consumer_id"])
    assert_fields(
        consumer,
        {
            "blocked_dependency_count": 1,
            "shipped_platform_count": 0,
            "coverage_state": COVERAGE_NONE,
        },
        "consumer",
    )

    validate_error(
        api.ship_implementation(
            scenario["implementation_id"],
            ship_payload(package_version="2.0.0", token_compliance_ratio=0.95),
            make_contributing_team_headers(scenario["team_id"]),
        ),
        ERR_BLOCKED_DEPENDENCY,
    )
    assert read_implementation(api, scenario["implementation_id"])["status"] == IMPL_BLOCKED


def test_repinning_then_reshipping_closes_the_block_cycle(api):
    """The implementation returns to shipped from the blocked position.

    PRD: "Shipping is available from exactly two positions on the implementation's state machine — `PLANNED → SHIPPED` for a first release and `BLOCKED → SHIPPED` for a recovery"

    A fresh pin on the provider's new major clears the edge, and the re-ship
    restores coverage and empties both blocked counters.

    Design: Difficulty/non_linear_state_machine/implementation_ship_block_reship_cycle_via_dependency_repin
    """
    scenario = _consumer_blocked_by_an_upstream_breaking_change(api)

    repinned = validate_success(
        api.update_dependency(
            scenario["dependency_id"],
            dependency_repin_payload(2),
            make_design_system_lead_headers(),
        )
    )
    assert repinned["compatibility_state"] == COMPAT_COMPATIBLE
    assert read_component(api, scenario["consumer_id"])["blocked_dependency_count"] == 0

    reshipped = ship(
        api, scenario["implementation_id"], scenario["team_id"], package_version="2.0.0"
    )
    assert_fields(
        reshipped,
        {
            "status": IMPL_SHIPPED,
            "blocked_reason": BLOCKED_REASON_NONE,
            "package_version": "2.0.0",
        },
        "implementation",
    )
    consumer = read_component(api, scenario["consumer_id"])
    assert_fields(
        consumer,
        {
            "shipped_platform_count": 1,
            "coverage_state": COVERAGE_WEB_ONLY,
            "blocked_dependency_count": 0,
        },
        "consumer",
    )
    assert read_team(api, scenario["team_id"])["blocked_implementation_count"] == 0
