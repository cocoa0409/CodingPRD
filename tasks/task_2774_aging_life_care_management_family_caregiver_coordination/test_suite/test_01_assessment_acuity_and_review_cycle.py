"""The two acuity methods, the supervisory revision lap, and the assessment
status a care plan may be authored from.
"""
from test_helpers import (
    api_client,
    accept_assessment,
    create_care_plan_payload,
    get_success_data,
    open_assessment,
    read_assessment,
    read_client,
    register_care_manager,
    register_client,
    register_supervisor,
    request_assessment_revision,
    return_assessment_to_draft,
    set_logical_clock,
    submit_assessment,
    uniform_domain_scores,
    validate_error,
    validate_paginated,
    make_care_manager_headers,
    PRACTICE_ADMIN,
)


def _register_practice(clock, client_overrides):
    """Clock, one care manager, one supervisor and one client."""
    set_logical_clock(clock)
    care_manager = register_care_manager(full_name="Dana Whitfield", hourly_rate_cents=22_500)
    supervisor = register_supervisor(full_name="Iris Ferreira", hourly_rate_cents=30_000)
    client = register_client(**client_overrides)
    return care_manager, supervisor, client


def test_01_submission_stamps_the_unweighted_screening_acuity_only():
    """Submitting a draft stamps `screening_acuity` as the unweighted mean of the
    six domain scores scaled to 0-100, and leaves `comprehensive_acuity` null.

    PRD: "The **screening** figure, stamped when the assessment is submitted, is the unweighted arithmetic mean of the six domain values — every domain counting equally — scaled to the 0-to-100 range: add `adl`, `cognition`, `medical_complexity`, `social_support`, `safety` and `finances`, divide the sum by 6, multiply by 20, and round the result half up to a whole number."

    Design: Difficulty/dual_variant_calc/assessment_screening_versus_comprehensive_acuity_divergence
    """
    care_manager, _supervisor, client = _register_practice(
        "2026-08-02T09:00:00Z",
        {"full_name": "Harriet Vandermolen", "residence_setting": "ASSISTED_LIVING"},
    )
    assessment = open_assessment(
        client["id"],
        care_manager["id"],
        scores={
            "adl": 4,
            "cognition": 5,
            "medical_complexity": 3,
            "social_support": 2,
            "safety": 4,
            "finances": 1,
        },
    )
    assert assessment["screening_acuity"] is None
    assert assessment["comprehensive_acuity"] is None

    submitted = submit_assessment(assessment["id"], care_manager["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["screening_acuity"] == 63
    assert submitted["comprehensive_acuity"] is None

    # The client's own acuity roll-up admits accepted assessments only.
    assert read_client(client["id"])["acuity_score"] == 0


def test_02_acceptance_stamps_the_priority_weighted_comprehensive_acuity():
    """Acceptance stamps `comprehensive_acuity` from the safety/cognition-heavy
    weighting, which on identical domain scores exceeds the screening figure by
    a full fourteen points.

    PRD: "The **comprehensive** figure, stamped when the assessment is accepted, is a priority-weighted sum instead: multiply `safety` by 0.30, `cognition` by 0.25, `adl` by 0.20, `medical_complexity` by 0.15, `social_support` by 0.05 and `finances` by 0.05, add those six products together, multiply the sum by 20, and round half up to a whole number."

    Design: Difficulty/dual_variant_calc/assessment_screening_versus_comprehensive_acuity_divergence
    """
    care_manager, supervisor, client = _register_practice(
        "2026-08-02T09:00:00Z",
        {"full_name": "Harriet Vandermolen", "residence_setting": "ASSISTED_LIVING"},
    )
    assessment = open_assessment(
        client["id"],
        care_manager["id"],
        scores={
            "adl": 4,
            "cognition": 5,
            "medical_complexity": 3,
            "social_support": 2,
            "safety": 4,
            "finances": 1,
        },
    )
    submit_assessment(assessment["id"], care_manager["id"])
    accepted = accept_assessment(assessment["id"], supervisor["id"])

    assert accepted["status"] == "ACCEPTED"
    assert accepted["screening_acuity"] == 63
    assert accepted["comprehensive_acuity"] == 77
    assert accepted["comprehensive_acuity"] - accepted["screening_acuity"] == 14
    assert accepted["reviewed_by_care_manager_id"] == supervisor["id"]
    assert accepted["accepted_at"] is not None


def test_03_acceptance_rolls_the_comprehensive_figure_up_onto_the_client():
    """The client's `acuity_score` becomes the accepted assessment's
    `comprehensive_acuity`, and 77 crosses the elevated threshold.

    PRD: "The candidate set is that client's assessments whose `status` is `ACCEPTED`; candidates are ranked by `accepted_at` descending, ties are broken by `created_at` ascending — never by `id` — and the client's `acuity_score` is the `comprehensive_acuity` of the top-ranked candidate."

    Design: Difficulty/dual_variant_calc/assessment_screening_versus_comprehensive_acuity_divergence
    """
    care_manager, supervisor, client = _register_practice(
        "2026-08-02T09:00:00Z",
        {"full_name": "Harriet Vandermolen", "residence_setting": "ASSISTED_LIVING"},
    )
    assessment = open_assessment(
        client["id"],
        care_manager["id"],
        scores={
            "adl": 4,
            "cognition": 5,
            "medical_complexity": 3,
            "social_support": 2,
            "safety": 4,
            "finances": 1,
        },
    )
    submit_assessment(assessment["id"], care_manager["id"])
    accept_assessment(assessment["id"], supervisor["id"])

    refreshed = read_client(client["id"])
    assert refreshed["acuity_score"] == 77
    assert refreshed["risk_posture"] == "ELEVATED"
    assert refreshed["status"] == "ASSESSMENT_IN_PROGRESS"


def _submitted_assessment_for_revision():
    """A SUBMITTED assessment scored 4/5/3/2/4/1, ready for supervisory review."""
    care_manager, supervisor, client = _register_practice(
        "2026-08-03T10:00:00Z",
        {"full_name": "Harriet Vandermolen", "residence_setting": "ASSISTED_LIVING"},
    )
    assessment = open_assessment(
        client["id"],
        care_manager["id"],
        scores={
            "adl": 4,
            "cognition": 5,
            "medical_complexity": 3,
            "social_support": 2,
            "safety": 4,
            "finances": 1,
        },
    )
    submitted = submit_assessment(assessment["id"], care_manager["id"])
    return care_manager, supervisor, client, submitted


def test_04_requesting_revision_writes_no_acuity_and_leaves_the_client_alone():
    """The revision fork records the reviewing supervisor but writes no
    comprehensive figure and does not touch the client at all.

    PRD: "`SUBMITTED → REVISION_REQUESTED` is the deliberately narrow branch: it records `reviewed_by_care_manager_id` and increases the assessment's `version` by 1, and it writes no acuity value at all, leaves `comprehensive_acuity` null, and touches neither the client's `acuity_score` nor its `risk_posture` nor its `version`."

    Design: Difficulty/non_linear_state_machine/assessment_revision_round_cycle_reenters_draft
    """
    _cm, supervisor, client, submitted = _submitted_assessment_for_revision()
    assert submitted["screening_acuity"] == 63
    assert submitted["revision_round"] == 0
    client_before = read_client(client["id"])

    returned = request_assessment_revision(
        submitted["id"],
        supervisor["id"],
        review_note="Please corroborate the safety score with a home visit.",
    )
    assert returned["status"] == "REVISION_REQUESTED"
    assert returned["reviewed_by_care_manager_id"] == supervisor["id"]
    assert returned["comprehensive_acuity"] is None
    assert returned["screening_acuity"] == 63
    assert returned["revision_round"] == 0

    client_after = read_client(client["id"])
    assert client_after["acuity_score"] == 0
    assert client_after["risk_posture"] == client_before["risk_posture"]
    assert client_after["version"] == client_before["version"]


def test_05_return_to_draft_advances_the_revision_round_and_clears_screening():
    """Taking a revision-requested assessment back to `DRAFT` counts the lap and
    discards the screening figure stamped on the previous submission.

    PRD: "That transition increases `revision_round` by 1, resets `screening_acuity` to null, and increases the assessment's `version` by 1."

    Design: Difficulty/non_linear_state_machine/assessment_revision_round_cycle_reenters_draft
    """
    care_manager, supervisor, _client, submitted = _submitted_assessment_for_revision()
    request_assessment_revision(
        submitted["id"],
        supervisor["id"],
        review_note="Please corroborate the safety score with a home visit.",
    )

    redrafted = return_assessment_to_draft(submitted["id"], care_manager["id"])
    assert redrafted["status"] == "DRAFT"
    assert redrafted["revision_round"] == 1
    assert redrafted["screening_acuity"] is None
    assert redrafted["comprehensive_acuity"] is None
    assert redrafted["version"] > submitted["version"]


def test_06_second_submission_restamps_screening_from_the_rescored_domains():
    """After the author rescores every domain to 5 on the redrafted assessment,
    the second submission stamps the screening figure afresh at 100.

    PRD: "The author submits the draft, moving `DRAFT → SUBMITTED`; this requires that the acting user is the author and that the client is not `DISCHARGED`, and it stamps `screening_acuity` and increases the assessment's `version`."

    Design: Difficulty/non_linear_state_machine/assessment_revision_round_cycle_reenters_draft
    """
    care_manager, supervisor, client, submitted = _submitted_assessment_for_revision()
    request_assessment_revision(
        submitted["id"],
        supervisor["id"],
        review_note="Please corroborate the safety score with a home visit.",
    )
    return_assessment_to_draft(submitted["id"], care_manager["id"])

    edited = get_success_data(
        api_client.update_assessment(
            submitted["id"],
            {"domain_scores": uniform_domain_scores(5)},
            make_care_manager_headers(care_manager["id"]),
        )
    )
    assert edited["status"] == "DRAFT"
    assert edited["domain_scores"]["safety"] == 5

    resubmitted = submit_assessment(submitted["id"], care_manager["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["screening_acuity"] == 100
    assert resubmitted["comprehensive_acuity"] is None
    assert resubmitted["revision_round"] == 1
    assert read_client(client["id"])["acuity_score"] == 0


def _accepted_client_acuity(clock, full_name, scores):
    """Accept one assessment carrying `scores` and answer (assessment, client)."""
    care_manager, supervisor, client = _register_practice(
        clock, {"full_name": full_name, "residence_setting": "PRIVATE_HOME"}
    )
    assessment = open_assessment(client["id"], care_manager["id"], scores=scores)
    submitted = submit_assessment(assessment["id"], care_manager["id"])
    accepted = accept_assessment(assessment["id"], supervisor["id"])
    return submitted, accepted, read_client(client["id"])


def test_07_a_comprehensive_acuity_of_exactly_seventy_is_elevated():
    """A weighted score landing exactly on the threshold elevates the posture;
    the boundary is inclusive.

    PRD: "Otherwise the posture is `ELEVATED` if any one of four conditions holds: the client's `acuity_score` is at least 70 — a score of exactly 70 qualifies; or the client's `capacity_status` is `ADJUDICATED_INCAPACITATED`; or the client has at least one service authorization whose `coi_status` is `PENDING_DISCLOSURE` or `DISCLOSED`, meaning an undischarged conflict-of-interest obligation is outstanding; or the client has at least one care plan in `ACTIVE` status whose `coverage_gap_flag` is true, meaning an activated plan is standing with nobody authorized to deliver it."

    Design: Difficulty/boundary_precision_check/comprehensive_acuity_exactly_seventy_is_elevated
    """
    submitted, accepted, client = _accepted_client_acuity(
        "2026-08-04T09:00:00Z",
        "Gwendolyn Achterberg",
        {
            "adl": 4,
            "cognition": 4,
            "medical_complexity": 4,
            "social_support": 2,
            "safety": 3,
            "finances": 2,
        },
    )
    assert submitted["screening_acuity"] == 63
    assert accepted["comprehensive_acuity"] == 70
    assert client["acuity_score"] == 70
    assert client["risk_posture"] == "ELEVATED"


def test_08_a_comprehensive_acuity_of_sixty_nine_stays_routine():
    """One point of social support below the threshold keeps the same client
    profile at `ROUTINE`, which is what makes 70 a boundary rather than a bias.

    PRD: "Failing all of those, the posture is `ROUTINE`."

    Design: Difficulty/boundary_precision_check/comprehensive_acuity_exactly_seventy_is_elevated
    """
    submitted, accepted, client = _accepted_client_acuity(
        "2026-08-04T09:00:00Z",
        "Hollis Achterberg",
        {
            "adl": 4,
            "cognition": 4,
            "medical_complexity": 4,
            "social_support": 1,
            "safety": 3,
            "finances": 2,
        },
    )
    assert submitted["screening_acuity"] == 60
    assert accepted["comprehensive_acuity"] == 69
    assert client["acuity_score"] == 69
    assert client["risk_posture"] == "ROUTINE"


def test_09_a_care_plan_may_not_be_authored_from_a_submitted_assessment():
    """A plan authored while its source assessment is still awaiting supervisory
    acceptance is refused, and no plan row is left behind.

    PRD: "The source assessment must be `ACCEPTED` — a plan authored from a draft, submitted, revision-requested or withdrawn assessment is rejected with `ERR_ASSESSMENT_NOT_ACCEPTED` — and both the source assessment and any named predecessor plan must belong to the same client as `client_id`, failing which the request is rejected with `ERR_ENTITY_RELATIONSHIP_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/care_plan_creation_requires_accepted_assessment_state
    """
    care_manager, _supervisor, client = _register_practice(
        "2026-08-14T09:00:00Z",
        {"full_name": "Jonah Delacroix-Mbeki", "residence_setting": "SKILLED_NURSING"},
    )
    assessment = open_assessment(
        client["id"], care_manager["id"], scores=uniform_domain_scores(3)
    )
    submitted = submit_assessment(assessment["id"], care_manager["id"])
    assert submitted["status"] == "SUBMITTED"

    observed_client = read_client(client["id"])
    response = api_client.create_care_plan(
        create_care_plan_payload(
            client["id"],
            assessment["id"],
            observed_client["version"],
            goals=["Stabilise nursing-home transition and family communication"],
        ),
        make_care_manager_headers(care_manager["id"]),
    )
    validate_error(response, "ERR_ASSESSMENT_NOT_ACCEPTED", 409)

    listing = api_client.list_care_plans(PRACTICE_ADMIN, {"client_id": client["id"]})
    plans, meta = validate_paginated(listing)
    assert plans == []
    assert meta["total_count"] == 0


def test_10_the_same_care_plan_is_accepted_once_the_assessment_is_accepted():
    """After acceptance the identical authoring request succeeds, pins the
    assessment version it was written from, and opens with its coverage gap set.

    PRD: "Crucially, the plan also captures `pinned_assessment_version`: the value of the source assessment's `version` at the instant the plan was created."

    Design: Difficulty/cross_entity_state_dependency/care_plan_creation_requires_accepted_assessment_state
    """
    care_manager, supervisor, client = _register_practice(
        "2026-08-14T09:00:00Z",
        {"full_name": "Jonah Delacroix-Mbeki", "residence_setting": "SKILLED_NURSING"},
    )
    assessment = open_assessment(
        client["id"], care_manager["id"], scores=uniform_domain_scores(3)
    )
    submit_assessment(assessment["id"], care_manager["id"])
    accepted = accept_assessment(assessment["id"], supervisor["id"])
    assert accepted["comprehensive_acuity"] == 60

    observed_client = read_client(client["id"])
    response = api_client.create_care_plan(
        create_care_plan_payload(
            client["id"],
            assessment["id"],
            observed_client["version"],
            goals=["Stabilise nursing-home transition and family communication"],
        ),
        make_care_manager_headers(care_manager["id"]),
    )
    plan = get_success_data(response, 201)
    assert plan["status"] == "DRAFT"
    assert plan["pinned_assessment_version"] == read_assessment(assessment["id"])["version"]
    assert plan["coverage_gap_flag"] is True
    assert plan["activated_at"] is None
    assert plan["approved_by_contact_id"] is None
    assert plan["rejection_rounds"] == 0
    assert read_client(client["id"])["risk_posture"] == "ROUTINE"
