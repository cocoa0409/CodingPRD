"""Ballot construction: the polymorphic line, the superseding create, the
optimistic-concurrency guard and the lock that freezes the print."""

from test_helpers import (
    ApiErrorId,
    PETITION_DEADLINE,
    TEST_USERS,
    assert_ballot,
    assert_ballot_line,
    build_round_one_ballot,
    create_ballot,
    create_ballot_payload,
    draft_referendum,
    read_ballot,
    read_ballot_line,
    read_candidacy,
    read_election,
    read_office,
    review_referendum,
    set_clock,
    setup_ballot_building_with_pending_review,
    setup_ballot_missing_a_second_office_line,
    setup_single_candidate_election,
    submit_referendum,
    validate_error,
    validate_paginated,
    validate_success,
)

COMMISSIONER = TEST_USERS["commissioner_headers"]


def test_a_referendum_line_that_carries_a_candidacy_is_refused(api):
    """PRD §3.6: "The discriminator governs which references the payload may carry: a
    `CANDIDATE` line supplies both `office_id` and `candidacy_id` and omits
    `referendum_id`, while a `REFERENDUM` line supplies `referendum_id` and omits both
    `office_id` and `candidacy_id`."
    PRD §3.6: "The referenced candidacy must be in `ELIGIBLE` or `RUNOFF_QUALIFIED`, and
    the referenced referendum must be in `APPROVED_FOR_BALLOT`; any shape or state
    violation is `ERR_INVALID_BALLOT_LINE`."

    Design: Corner/entities/ballot_line_referendum_type_with_candidacy_returns_invalid_ballot_line
    """
    scenario = setup_single_candidate_election(
        office_overrides={"eligible_class_years": ["SENIOR"]}
    )
    build_round_one_ballot(scenario, candidacy_indexes=[])
    ballot = scenario["ballot"]
    candidacy = scenario["candidacies"][0]

    validate_error(
        api.create_ballot_line(
            ballot["id"],
            {
                "line_type": "REFERENDUM",
                "office_id": scenario["office"]["id"],
                "candidacy_id": candidacy["id"],
            },
            COMMISSIONER,
        ),
        ApiErrorId.ERR_INVALID_BALLOT_LINE.value,
        400,
    )

    unchanged = read_ballot(ballot["id"])
    assert unchanged["line_count"] == 0
    assert unchanged["active_line_count"] == 0
    _, meta = validate_paginated(
        api.list_ballot_lines(COMMISSIONER, params={"ballot_id": ballot["id"]})
    )
    assert meta["total_count"] == 0, "the malformed line was never drawn"


def test_a_replacement_ballot_voids_the_prior_draft_and_its_lines(api):
    """PRD §3.6: "And a ballot created while the election is already `BALLOT_BUILDING` is a
    legitimate replacement, a `BALLOT_BUILDING → BALLOT_BUILDING` self-loop: the election
    stays in `BALLOT_BUILDING`, the existing `DRAFT` ballot for that round moves
    `DRAFT → VOIDED` together with every one of its lines, and a fresh `DRAFT` ballot takes
    its place."

    Design: Corner/state_machines/ballot_create_supersedes_prior_draft_and_voids_its_lines
    """
    scenario = setup_single_candidate_election(
        office_overrides={"eligible_class_years": ["SENIOR"]}
    )
    build_round_one_ballot(scenario)
    first_ballot = scenario["ballot"]
    first_line = scenario["candidate_lines"][0]

    current_version = read_election(scenario["election"]["id"])["version"]
    replacement = validate_success(
        api.create_ballot(
            create_ballot_payload(scenario["election"]["id"], current_version, 1),
            COMMISSIONER,
        ),
        201,
    )

    assert_ballot(replacement)
    assert read_ballot(first_ballot["id"])["status"] == "VOIDED"
    assert read_ballot_line(first_line["id"])["status"] == "VOIDED"
    assert replacement["status"] == "DRAFT"
    assert replacement["line_count"] == 0
    assert replacement["active_line_count"] == 0
    assert read_election(scenario["election"]["id"])["status"] == "BALLOT_BUILDING"

    _, meta = validate_paginated(
        api.list_ballots(COMMISSIONER, params={"election_id": scenario["election"]["id"]})
    )
    assert meta["total_count"] == 2, "the superseded ballot is kept, not deleted"


def test_ballot_creation_with_a_stale_election_version_is_refused(api):
    """PRD §2.8: "A ballot-creation request (`POST /ballots`) must carry
    `expected_election_version` matching the target election's current `version`. If the
    election's version has advanced since the client last read it, the create is rejected
    with `ERR_STALE_ELECTION_VERSION` and HTTP 412."
    PRD §2.8: "The guard matters because creating a ballot for a round that already has a
    `DRAFT` ballot voids that draft along with every line on it; without the guard, a
    client working from an out-of-date view would silently discard ballot construction it
    never saw."

    Design: Corner/cross_cutting_complexity_layers/ballot_create_with_stale_election_version_returns_412
    """
    scenario = setup_single_candidate_election(
        office_overrides={"eligible_class_years": ["SENIOR"]}
    )
    set_clock(PETITION_DEADLINE)
    stale_version = read_election(scenario["election"]["id"])["version"]
    first_ballot = create_ballot(scenario["election"]["id"], 1, stale_version)

    validate_error(
        api.create_ballot(
            create_ballot_payload(scenario["election"]["id"], stale_version, 1),
            COMMISSIONER,
        ),
        ApiErrorId.ERR_STALE_ELECTION_VERSION.value,
        412,
    )

    assert read_ballot(first_ballot["id"])["status"] == "DRAFT", (
        "the stale create must not void the draft it never saw"
    )
    _, meta = validate_paginated(
        api.list_ballots(COMMISSIONER, params={"election_id": scenario["election"]["id"]})
    )
    assert meta["total_count"] == 1
    assert read_election(scenario["election"]["id"])["version"] == stale_version + 1


def test_ballot_lines_are_reachable_through_both_arms_of_the_reference(api):
    """PRD §2.3: "Ballot lines filter on `ballot_id`, `office_id`, `candidacy_id`,
    `referendum_id`, `line_type` and `status`."
    PRD §3.6: "A new line enters in `status` `ACTIVE` and receives a 1-based `position`
    assigned in ascending `created_at` order — numbered within the pairing of ballot and
    office for candidate lines, and within the ballot as a whole for referendum lines — and
    both `line_count` and `active_line_count` on the parent ballot are incremented."

    Design: Corner/endpoints/ballot_line_filtered_list_reaches_lines_by_candidacy_and_by_referendum
    """
    scenario = setup_single_candidate_election(
        office_overrides={"eligible_class_years": ["SENIOR"]}
    )
    candidacy = scenario["candidacies"][0]
    drafter = scenario["candidate_students"][0]
    referendum = draft_referendum(scenario["election"]["id"], drafter)
    submit_referendum(referendum, drafter)
    review_referendum(referendum, "APPROVE")

    build_round_one_ballot(scenario, referendum_ids=[referendum["id"]])
    candidate_line = scenario["candidate_lines"][0]
    referendum_line = scenario["referendum_lines"][0]

    by_candidacy, candidacy_meta = validate_paginated(
        api.list_ballot_lines(COMMISSIONER, params={"candidacy_id": candidacy["id"]})
    )
    assert candidacy_meta["total_count"] == 1
    assert by_candidacy[0]["id"] == candidate_line["id"]
    assert_ballot_line(by_candidacy[0])
    assert by_candidacy[0]["line_type"] == "CANDIDATE"
    assert by_candidacy[0]["position"] == 1
    assert by_candidacy[0]["office_id"] == scenario["office"]["id"]
    assert by_candidacy[0]["referendum_id"] is None

    by_referendum, referendum_meta = validate_paginated(
        api.list_ballot_lines(COMMISSIONER, params={"referendum_id": referendum["id"]})
    )
    assert referendum_meta["total_count"] == 1
    assert by_referendum[0]["id"] == referendum_line["id"]
    assert by_referendum[0]["line_type"] == "REFERENDUM"
    assert by_referendum[0]["candidacy_id"] is None
    assert by_referendum[0]["office_id"] is None

    _, ballot_meta = validate_paginated(
        api.list_ballot_lines(COMMISSIONER, params={"ballot_id": scenario["ballot"]["id"]})
    )
    assert ballot_meta["total_count"] == 2

    ballot = read_ballot(scenario["ballot"]["id"])
    assert ballot["line_count"] == 2
    assert ballot["active_line_count"] == 2


def test_locking_a_ballot_with_an_uncontested_seat_is_refused(api):
    """PRD §3.6: "The transition `DRAFT → LOCKED` requires the election to be in
    `BALLOT_BUILDING` and requires every office of that election to carry at least one
    `ACTIVE` line of type `CANDIDATE` on the ballot being locked; an office with none
    blocks the lock with `ERR_OFFICE_HAS_NO_CANDIDATE`."

    Design: Difficulty/boundary_precision_check/office_with_zero_active_lines_blocks_ballot_lock
    """
    scenario = setup_ballot_missing_a_second_office_line()

    validate_error(
        api.lock_ballot(scenario["ballot"]["id"], COMMISSIONER),
        ApiErrorId.ERR_OFFICE_HAS_NO_CANDIDATE.value,
        409,
    )


def test_the_refused_lock_leaves_the_ballot_and_its_seats_untouched(api):
    """PRD §3.6: "The lock stamps `locked_at` from the logical clock — the instant that
    certification will later treat as the snapshot of record — and it promotes everything
    the ballot references."
    PRD §3.6: "Every referenced candidacy in `ELIGIBLE` moves `ELIGIBLE → ON_BALLOT` on a
    round-1 ballot, every referenced candidacy in `RUNOFF_QUALIFIED` moves
    `RUNOFF_QUALIFIED → ON_BALLOT` on a round-2 ballot, each such promotion carries the
    office `OPEN → CONTESTED`, and every referenced referendum moves its `drafting_status`
    `APPROVED_FOR_BALLOT → ON_BALLOT`, which is terminal on that axis."

    Design: Difficulty/boundary_precision_check/office_with_zero_active_lines_blocks_ballot_lock
    """
    scenario = setup_ballot_missing_a_second_office_line()

    validate_error(
        api.lock_ballot(scenario["ballot"]["id"], COMMISSIONER),
        ApiErrorId.ERR_OFFICE_HAS_NO_CANDIDATE.value,
        409,
    )

    ballot = read_ballot(scenario["ballot"]["id"])
    assert ballot["status"] == "DRAFT", f"the refused lock leaves DRAFT, got {ballot['status']}"
    assert ballot["locked_at"] is None, "no snapshot instant is stamped"
    assert ballot["active_line_count"] == 1
    assert read_candidacy(scenario["candidacy"]["id"])["status"] == "ELIGIBLE", (
        "no promotion happens when the lock is refused"
    )
    assert read_office(scenario["treasurer_office"]["id"])["status"] == "OPEN"


def test_approving_a_petition_after_the_phase_moved_on_is_refused(api):
    """PRD §3.2: "Approval by an `ElectionCommissioner` advances the candidacy
    `UNDER_REVIEW → ELIGIBLE`. Three conditions apply: the election is `PETITIONING`, the
    logical clock is at or before `petition_deadline` — note that approval tolerates the
    deadline instant itself, while submission does not — and the candidacy's
    `petition_signature_valid_count` has reached the office's `required_signature_count`,
    compared as "at least", with a shortfall reported as `ERR_INSUFFICIENT_SIGNATURES`."
    PRD §2.5: "The owning election is in the phase the operation requires —
    `ERR_ELECTION_PHASE_INVALID` (409). This guards twelve operations: candidacy filing,
    petition submission, petition approval, petition return, petition-signature creation,
    signature adjudication, referendum drafting, referendum submission, referendum review,
    ballot-line creation, ballot lock, and officer activation."

    Design: Difficulty/cross_entity_state_dependency/petition_approval_rejected_once_election_left_petitioning
    """
    scenario = setup_ballot_building_with_pending_review()

    response = api.approve_candidacy(scenario["pending_candidacy"]["id"], COMMISSIONER)

    validate_error(response, ApiErrorId.ERR_ELECTION_PHASE_INVALID.value, 409)
    assert response.json()["data"]["error_id"] != (
        ApiErrorId.ERR_INSUFFICIENT_SIGNATURES.value
    ), "the seat requires no signatures, so only the phase gate can refuse this"


def test_the_phase_refusal_leaves_both_candidacies_where_they_stood(api):
    """PRD §2.5: "Rules are evaluated in ascending priority and the **first** failing rule
    decides the response; later rules are never reached."
    PRD §3.6: "A round-1 ballot created out of `PETITIONING` moves the election
    `PETITIONING → BALLOT_BUILDING` and requires the logical clock to have reached
    `petition_deadline`."

    Design: Difficulty/cross_entity_state_dependency/petition_approval_rejected_once_election_left_petitioning
    """
    scenario = setup_ballot_building_with_pending_review()

    validate_error(
        api.approve_candidacy(scenario["pending_candidacy"]["id"], COMMISSIONER),
        ApiErrorId.ERR_ELECTION_PHASE_INVALID.value,
        409,
    )

    assert read_candidacy(scenario["pending_candidacy"]["id"])["status"] == "UNDER_REVIEW"
    assert read_candidacy(scenario["approved_candidacy"]["id"])["status"] == "ELIGIBLE", (
        "the candidacy approved before the phase change keeps its posture"
    )
    assert read_election(scenario["election"]["id"])["status"] == "BALLOT_BUILDING"
