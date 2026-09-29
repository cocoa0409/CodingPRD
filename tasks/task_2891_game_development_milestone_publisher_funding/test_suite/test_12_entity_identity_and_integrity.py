"""Server-minted identity and computed fields, the immutable review payload, and the
body foreign keys a creation endpoint has to resolve."""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_DEPENDENCY,
    ERR_INVALID_REQUEST,
    ERR_MILESTONE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_absent,
    assert_fields_equal,
    assert_instant_format,
    assert_ledger,
    assert_pct_equals,
)
from test_helpers.constants import UNKNOWN_MILESTONE_ID
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_1,
    DEFAULT_CRITERIA_2,
    add_milestone,
    agreement_version,
    draft_agreement,
    read_milestone,
    setup_registry,
    setup_single_alpha,
    submit_build,
)
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ALPHA_PASSING = {
    "feature_completeness_pct": 75.00,
    "crash_free_sessions_pct": 96.00,
    "content_completeness_pct": 60.00,
    "known_blocker_count": 5,
}


def test_the_build_gate_state_and_readiness_score_are_server_computed(api):
    """PRD §3.4: "Every build that passes also records a `readiness_score`, a single
    weighted figure for reviewers to skim: `feature_completeness_pct` weighted at 0.45,
    plus `crash_free_sessions_pct` weighted at 0.35, plus `content_completeness_pct`
    weighted at 0.20, with the total of those three weighted terms rounded half up to
    two decimal places." PRD §2.4 supplies the instant from the logical clock.

    Design: Corner/entities/corner_build_gate_state_and_readiness_score_are_server_computed
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=0,
                                 acceptance_criteria=DEFAULT_CRITERIA_2,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg

    build = validate_success(
        api.create_build(
            f.build_payload(scenario.m1["id"], 7, 92.00, 96.50, 61.00, 3,
                            release_notes="Alpha candidate"),
            reg.dev,
        ),
        201,
    )
    assert build["gate_state"] == "PASSED"
    assert_pct_equals(build["readiness_score"], 87.38, "readiness_score")
    assert build["submitted_at"] == "2026-08-01T00:00:00.000Z"

    assert_fields_equal(
        read_milestone(reg, scenario.m1["id"]),
        {"latest_build_number": 7, "status": "UNDER_REVIEW"},
        "milestone",
    )


def test_the_agreement_version_increments_once_per_mutation(api):
    """PRD §2.4: "Every resource the API persists carries an `id`: a server-minted UUID
    string with no type prefix, never supplied by the client" and "`version`, an integer
    that starts at 1 on creation and increments by one on each mutation".

    Design: Corner/entities/corner_system_fields_are_minted_and_version_increments_per_mutation
    """
    reg = setup_registry(api, studio_name="Ledgerline Studio",
                        studio_email="dev@ledgerline.example", studio_country="NL",
                        with_reviewer=False)
    agreement = draft_agreement(reg, "Ledgerline", 2000000,
                                live_ops_quarterly_funding_cents=100000)
    add_milestone(reg, agreement["id"], 1, "Alpha", "ALPHA", 2000000, 0,
                  DEFAULT_CRITERIA_1)

    assert agreement["version"] == 1
    assert is_valid_uuid(agreement["id"]) and len(agreement["id"]) == 36
    assert_instant_format(agreement["created_at"], "created_at")

    # PRD §2.8 pins the increment as "by one, exactly once per request", so each
    # mutation is measured against the version observed immediately before it.
    before_activate = agreement_version(reg, agreement["id"])
    activated = validate_success(api.activate_agreement(agreement["id"], reg.finance))
    assert_fields_equal(
        activated,
        {"version": before_activate + 1, "status": "ACTIVE"},
        "agreement",
    )

    suspended = validate_success(
        api.suspend_agreement(agreement["id"], reg.finance, {"reason": "Cash-flow review"})
    )
    assert_fields_equal(
        suspended,
        {"version": activated["version"] + 1, "status": "SUSPENDED"},
        "agreement",
    )

    assert activated["created_at"] == agreement["created_at"]
    assert suspended["created_at"] == agreement["created_at"]
    assert suspended["updated_at"] >= activated["updated_at"]


def test_an_unknown_gate_profile_value_is_refused(api):
    """PRD §3.3 fixes the three profiles as `ALPHA`, `BETA` and `GOLD`, and PRD §2.10
    rule 6 refuses a structurally invalid body with `ERR_INVALID_REQUEST`.

    Design: Corner/entities/corner_unknown_gate_profile_enum_value_is_rejected
    """
    reg = setup_registry(api, with_reviewer=False)
    agreement = draft_agreement(reg, "Aurora Drift", 3600000,
                                live_ops_quarterly_funding_cents=100000)

    response = api.create_milestone(
        f.milestone_payload(agreement["id"], 1, "Silver Build", "SILVER", 3600000, 0,
                            DEFAULT_CRITERIA_1),
        reg.dev,
    )
    validate_error(response, ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_milestones(reg.finance, {"agreement_id": agreement["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_the_review_payload_carries_neither_version_nor_updated_at(api):
    """PRD §2.4: "`PublisherReview` is the single exception: a review is immutable from
    the instant it is written, so it exposes only `id` and `created_at` — it has neither
    `updated_at` nor `version`, and clients must not expect either field on a review
    payload."

    Design: Corner/entities/corner_publisher_review_is_immutable_and_carries_no_version_field
    """
    scenario = setup_single_alpha(api, title="Stillwater", advance_total_cents=3600000,
                                 contractor_budget_cents=0,
                                 acceptance_criteria=DEFAULT_CRITERIA_2,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg
    build = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING)
    created = validate_success(
        api.create_review(f.rejected_review_payload(build["id"], end_hour=13), reg.reviewer),
        201,
    )

    review = validate_success(api.get_review(created["id"], reg.reviewer))
    assert "id" in review and "created_at" in review
    assert_absent(review, "version", "review")
    assert_absent(review, "updated_at", "review")
    assert_fields_equal(
        review,
        {"reviewer_user_id": reg.reviewer_id, "verdict": "REJECTED",
         "decided_at": "2026-08-01T00:00:00.000Z", "cure_deadline_at": None},
        "review",
    )


def test_an_unknown_milestone_id_on_an_engagement_reports_the_parent(api):
    """PRD §2.10 rule 19: "Every foreign key in the request body resolves, left to
    right, on every creation endpoint that carries one — the parent-specific not-found
    error listed in §2.9." It precedes the state and budget rules of §3.8.

    Design: Corner/entities/corner_engagement_with_unknown_milestone_id_returns_milestone_not_found
    """
    scenario = setup_single_alpha(api, title="Aurora Solo", advance_total_cents=3600000,
                                 contractor_budget_cents=100000,
                                 acceptance_criteria=DEFAULT_CRITERIA_1,
                                 live_ops_quarterly_funding_cents=100000)
    reg = scenario.reg

    response = api.create_engagement(
        f.engagement_payload(UNKNOWN_MILESTONE_ID, "ART-QUILL", 900000,
                             "2026-08-10", "2026-09-10", "Concept art"),
        reg.dev,
    )
    validate_error(response, ERR_MILESTONE_NOT_FOUND, 404)

    rows, meta = validate_paginated(
        api.list_engagements(reg.dev, {"milestone_id": scenario.m1["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_a_predecessor_from_another_agreement_is_not_a_valid_dependency(api):
    """PRD §3.2: "A supplied `depends_on_milestone_id` must name a milestone of the same
    agreement, must not name the milestone being created, and must name a milestone whose
    `sequence_index` is strictly smaller than the one being submitted; a predecessor from
    another agreement, a self-reference, or a predecessor at or after this milestone's own
    position is `ERR_INVALID_DEPENDENCY`."

    Design: Corner/entities/corner_flat_topology_cross_reference_dependency_must_stay_inside_one_agreement
    """
    reg = setup_registry(api, with_reviewer=False)
    agreement_a = draft_agreement(reg, "Aurora Drift", 3600000,
                                  live_ops_quarterly_funding_cents=100000)
    milestone_a = add_milestone(reg, agreement_a["id"], 1, "Alpha A", "ALPHA",
                                3600000, 0, DEFAULT_CRITERIA_1)
    agreement_b = draft_agreement(reg, "Side Project", 1000000, 2000, "2028-01-31",
                                  live_ops_quarterly_funding_cents=100000)

    response = api.create_milestone(
        f.milestone_payload(agreement_b["id"], 1, "Alpha B", "ALPHA", 1000000, 0,
                            DEFAULT_CRITERIA_1, milestone_a["id"]),
        reg.dev,
    )
    validate_error(response, ERR_INVALID_DEPENDENCY, 422)

    rows, meta = validate_paginated(
        api.list_milestones(reg.finance, {"agreement_id": agreement_b["id"]})
    )
    assert rows == [] and meta["total_count"] == 0
    assert_ledger(
        validate_success(api.get_agreement(agreement_b["id"], reg.finance)),
        committed_cents=0,
    )
