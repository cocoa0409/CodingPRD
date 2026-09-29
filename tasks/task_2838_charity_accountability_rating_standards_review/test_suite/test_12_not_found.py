"""Path-identifier and body-foreign-key resolution, and what a 404 must leave untouched."""
from test_helpers import (
    NON_EXISTENT_UUID,
    assert_score,
    assign_panel_payload,
    create_filing_record_payload,
    create_governance_profile_payload,
    create_organization,
    dimension_by_name,
    dispose_public_comment_payload,
    dimension_overrides_payload,
    make_analyst_headers,
    organization_version,
    read_cycle,
    read_dimension_scores,
    read_organization,
    setup_scored_cycle,
    triage_complaint_payload,
    validate_error,
    validate_filing_payload,
    validate_paginated,
    waive_standard_payload,
)


def test_a_governance_profile_naming_an_unknown_cycle_in_its_body_is_a_not_found(
    api, analyst_headers
):
    """The parent arrives in the body rather than the path, and the body is otherwise
    perfectly well formed, so the refusal is a foreign-key 404 and not a 400.

    PRD §2.8: "**Body foreign keys.** Every foreign key supplied in the request body resolves to a stored row, yielding `ERR_ORGANIZATION_NOT_FOUND`, `ERR_METHODOLOGY_VERSION_NOT_FOUND`, `ERR_RATING_CYCLE_NOT_FOUND`, `ERR_CORRECTION_REQUEST_NOT_FOUND` or `ERR_DIMENSION_SCORE_NOT_FOUND` — the code belonging to the entity whose identifier failed to resolve — each HTTP 404."

    Design: Corner/entities/governance_profile_create_with_unknown_cycle_returns_not_found
    """
    scenario = setup_scored_cycle(
        filings=[], evaluate=False, governance_overrides=None, score=False
    )

    response = api.create_governance_profile(
        create_governance_profile_payload(NON_EXISTENT_UUID), analyst_headers
    )
    validate_error(response, "ERR_RATING_CYCLE_NOT_FOUND", 404)

    rows, meta = validate_paginated(
        api.list_governance_profiles(
            analyst_headers, params={"rating_cycle_id": scenario["cycle"]["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_an_unknown_organization_on_a_filing_beats_the_occ_check_that_follows_it(
    api, analyst_headers
):
    """The version number supplied is a real, current version — of a different charity —
    so answering ERR_STALE_VERSION would mean the ladder ran out of order.

    PRD §2.8: "**Body foreign keys.** Every foreign key supplied in the request body resolves to a stored row, yielding `ERR_ORGANIZATION_NOT_FOUND`, `ERR_METHODOLOGY_VERSION_NOT_FOUND`, `ERR_RATING_CYCLE_NOT_FOUND`, `ERR_CORRECTION_REQUEST_NOT_FOUND` or `ERR_DIMENSION_SCORE_NOT_FOUND` — the code belonging to the entity whose identifier failed to resolve — each HTTP 404."

    PRD §2.8: "**Stale parent version.** The supplied `expected_organization_version` or `expected_rating_cycle_version` equals the parent's current `version`, else `ERR_STALE_VERSION` (412)."

    Design: Corner/entities/filing_record_create_with_unknown_organization_returns_not_found
    """
    organization = create_organization()
    version_before = organization_version(organization["id"])

    response = api.create_filing_record(
        create_filing_record_payload(NON_EXISTENT_UUID, version_before), analyst_headers
    )
    validate_error(response, "ERR_ORGANIZATION_NOT_FOUND", 404)

    rows, meta = validate_paginated(
        api.list_organization_filing_records(organization["id"], analyst_headers)
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert organization_version(organization["id"]) == version_before


def test_a_public_reader_asking_for_an_unregistered_charity_gets_a_not_found(
    api, public_headers
):
    """The path sweep runs before any ownership test, so the public reader learns only
    that the row does not exist.

    PRD §2.8: "**Path existence.** Every identifier appearing in the URL path resolves to a stored row, validated left to right, on every endpoint that has a path parameter."

    Design: Corner/entities/organization_not_found_on_get_unknown_id
    """
    create_organization()

    validate_error(
        api.get_organization(NON_EXISTENT_UUID, public_headers),
        "ERR_ORGANIZATION_NOT_FOUND",
        404,
    )

    _rows, meta = validate_paginated(api.list_organizations(public_headers))
    assert meta["total_count"] == 1


def test_an_unknown_methodology_id_does_not_fall_back_to_the_effective_version(
    api, public_headers
):
    """A bad methodology id must 404 rather than quietly resolve to whatever version is
    currently effective, because cycle pinning depends on exact identity.

    PRD §2.8: "**Path existence.** Every identifier appearing in the URL path resolves to a stored row, validated left to right, on every endpoint that has a path parameter."

    Design: Corner/entities/methodology_version_not_found_on_get_unknown_id
    """
    create_organization()

    validate_error(
        api.get_methodology_version(NON_EXISTENT_UUID, public_headers),
        "ERR_METHODOLOGY_VERSION_NOT_FOUND",
        404,
    )

    _rows, meta = validate_paginated(api.list_methodology_versions(public_headers))
    assert meta["total_count"] == 0


def test_disposing_an_unknown_comment_decrements_nothing(api, admin_headers, public_headers):
    """Disposal moves an adoption gate on the comment's parent version, so an unknown
    comment id must not decrement an arbitrary version's counter.

    PRD §2.8: "**Path existence.** Every identifier appearing in the URL path resolves to a stored row, validated left to right, on every endpoint that has a path parameter."

    Design: Corner/entities/public_comment_not_found_on_dispose_unknown_id
    """
    create_organization()

    validate_error(
        api.dispose_public_comment(
            NON_EXISTENT_UUID, dispose_public_comment_payload("DECLINED"), admin_headers
        ),
        "ERR_PUBLIC_COMMENT_NOT_FOUND",
        404,
    )

    _rows, meta = validate_paginated(api.list_methodology_versions(public_headers))
    assert meta["total_count"] == 0


def test_reading_an_invented_transition_grant_does_not_mint_a_grace_licence(
    api, admin_headers
):
    """Grants exist only as an adoption side effect, so an unknown id must 404 rather
    than synthesise a licence to pin a retired methodology.

    PRD §2.8: "**Path existence.** Every identifier appearing in the URL path resolves to a stored row, validated left to right, on every endpoint that has a path parameter."

    Design: Corner/entities/transition_grant_not_found_on_get_unknown_id
    """
    organization = create_organization()

    validate_error(
        api.get_transition_grant(NON_EXISTENT_UUID, admin_headers),
        "ERR_TRANSITION_GRANT_NOT_FOUND",
        404,
    )

    rows, meta = validate_paginated(
        api.list_transition_grants(
            admin_headers, params={"organization_id": organization["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert read_organization(organization["id"])["transition_grace_until"] is None


def test_scoring_an_unknown_cycle_answers_not_found_and_not_wrong_analyst(api):
    """The acting analyst is nobody's assigned analyst, yet the path sweep at check 3
    answers before the identity check at check 11.

    PRD §2.8: "Checks are evaluated in one fixed ascending order, and the **first** failing check determines the response."

    PRD §2.8: "**Assigned-analyst identity.** The acting `RatingAnalyst`'s `X-User-ID` equals the cycle's `assigned_analyst_user_id`, else `ERR_NOT_ASSIGNED_ANALYST` (403)."

    Design: Corner/entities/rating_cycle_not_found_on_score_unknown_id
    """
    create_organization()

    validate_error(
        api.score_rating_cycle(NON_EXISTENT_UUID, make_analyst_headers("analyst-9")),
        "ERR_RATING_CYCLE_NOT_FOUND",
        404,
    )


def test_validating_an_unknown_filing_supersedes_nothing(api, analyst_headers):
    """Acceptance is the transition that retires the incumbent filing for the same
    triple, so a 404 must abort before that supersede sweep can run.

    PRD §2.8: "**Path existence.** Every identifier appearing in the URL path resolves to a stored row, validated left to right, on every endpoint that has a path parameter."

    Design: Corner/entities/filing_record_not_found_on_validate_unknown_id
    """
    organization = create_organization()

    validate_error(
        api.validate_filing_record(
            NON_EXISTENT_UUID, validate_filing_payload("ACCEPT"), analyst_headers
        ),
        "ERR_FILING_RECORD_NOT_FOUND",
        404,
    )

    rows, meta = validate_paginated(
        api.list_organization_filing_records(organization["id"], analyst_headers)
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_evaluating_an_unknown_governance_profile_writes_no_standards_fan_out(
    api, analyst_headers
):
    """Evaluation would write eight standard rows and stamp the parent cycle, so a 404
    must leave the standards table empty.

    PRD §2.8: "**Path existence.** Every identifier appearing in the URL path resolves to a stored row, validated left to right, on every endpoint that has a path parameter."

    Design: Corner/entities/governance_profile_not_found_on_evaluate_unknown_id
    """
    create_organization()

    validate_error(
        api.evaluate_governance_profile(NON_EXISTENT_UUID, analyst_headers),
        "ERR_GOVERNANCE_PROFILE_NOT_FOUND",
        404,
    )

    rows, meta = validate_paginated(api.list_governance_profiles(analyst_headers))
    assert rows == []
    assert meta["total_count"] == 0


def test_waiving_an_unknown_standard_moves_no_counter_anywhere(api, admin_headers, analyst_headers):
    """A waiver would move two profile counters, one cycle counter and the
    accountability arithmetic, so a 404 must precede all of that ledger movement.

    PRD §2.8: "**Path existence.** Every identifier appearing in the URL path resolves to a stored row, validated left to right, on every endpoint that has a path parameter."

    Design: Corner/entities/standard_evaluation_not_found_on_waive_unknown_id
    """
    create_organization()

    validate_error(
        api.waive_standard_evaluation(
            NON_EXISTENT_UUID,
            waive_standard_payload("board vacancy filled after the reporting year"),
            admin_headers,
        ),
        "ERR_STANDARD_EVALUATION_NOT_FOUND",
        404,
    )

    _profiles, profile_meta = validate_paginated(
        api.list_governance_profiles(analyst_headers)
    )
    assert profile_meta["total_count"] == 0
    _cycles, cycle_meta = validate_paginated(api.list_rating_cycles(analyst_headers))
    assert cycle_meta["total_count"] == 0


def test_claiming_an_unknown_correction_answers_not_found_and_not_wrong_analyst(
    api, analyst_headers
):
    """The claim is gated on the parent cycle's assigned analyst, a test that cannot be
    evaluated at all without a row to read.

    PRD §2.8: "**Path existence.** Every identifier appearing in the URL path resolves to a stored row, validated left to right, on every endpoint that has a path parameter."

    PRD §2.8: "**Assigned-analyst identity.** The acting `RatingAnalyst`'s `X-User-ID` equals the cycle's `assigned_analyst_user_id`, else `ERR_NOT_ASSIGNED_ANALYST` (403)."

    Design: Corner/entities/correction_request_not_found_on_claim_unknown_id
    """
    create_organization()

    validate_error(
        api.claim_correction_request(NON_EXISTENT_UUID, analyst_headers),
        "ERR_CORRECTION_REQUEST_NOT_FOUND",
        404,
    )


def test_seating_a_panel_on_an_unknown_appeal_answers_not_found(api, admin_headers):
    """The submitted panel is itself well formed, so the 404 is attributable to the
    unknown appeal rather than to panel composition.

    PRD §2.8: "**Path existence.** Every identifier appearing in the URL path resolves to a stored row, validated left to right, on every endpoint that has a path parameter."

    PRD §2.8: "Checks are evaluated in one fixed ascending order, and the **first** failing check determines the response."

    Design: Corner/entities/appeal_not_found_on_assign_panel_unknown_id
    """
    create_organization()

    validate_error(
        api.assign_appeal_panel(
            NON_EXISTENT_UUID,
            assign_panel_payload(["panel-1", "panel-2", "panel-3"]),
            admin_headers,
        ),
        "ERR_APPEAL_NOT_FOUND",
        404,
    )


def test_triaging_an_unknown_complaint_conjures_no_credibility_row(
    api, analyst_headers
):
    """Triage scores credibility from the complaint's own kind, category and document
    count, none of which exist for an unknown id.

    PRD §2.8: "**Path existence.** Every identifier appearing in the URL path resolves to a stored row, validated left to right, on every endpoint that has a path parameter."

    Design: Corner/entities/complaint_not_found_on_triage_unknown_id
    """
    organization = create_organization()

    validate_error(
        api.triage_complaint(
            NON_EXISTENT_UUID, triage_complaint_payload("INVESTIGATE"), analyst_headers
        ),
        "ERR_COMPLAINT_NOT_FOUND",
        404,
    )

    rows, meta = validate_paginated(
        api.list_complaints(
            analyst_headers, params={"organization_id": organization["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_an_unknown_publication_record_is_not_assembled_on_demand(api, public_headers):
    """The ledger row is created solely as a publish side effect, so there is no lazy
    construction path for an id that was never appended.

    PRD §2.8: "**Path existence.** Every identifier appearing in the URL path resolves to a stored row, validated left to right, on every endpoint that has a path parameter."

    Design: Corner/entities/publication_record_not_found_on_get_unknown_id
    """
    organization = create_organization()

    validate_error(
        api.get_publication_record(NON_EXISTENT_UUID, public_headers),
        "ERR_PUBLICATION_RECORD_NOT_FOUND",
        404,
    )

    rows, meta = validate_paginated(
        api.list_publication_records(
            public_headers, params={"organization_id": organization["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_one_unknown_dimension_row_in_the_batch_writes_nothing_at_all(
    api, analyst_headers
):
    """The path id resolves and the OCC version is correct, so the only fault is the
    unknown dimension row named in the body — and the all-or-nothing rule leaves the
    three sibling rows exactly as scored.

    PRD §3.6: "Every `dimension_score_id` must resolve to a dimension row belonging to **this** cycle — a row that does not exist, or that belongs to a different cycle, is `ERR_DIMENSION_SCORE_NOT_FOUND` — and every `raw_points` must be an integer between 0 and that row's own `max_points` inclusive, or the request is `ERR_INVALID_REQUEST`."

    PRD §3.6: "The operation is all-or-nothing: if any entry in the array is invalid, nothing at all is written."

    Design: Corner/entities/dimension_score_not_found_on_override_unknown_id
    """
    scenario = setup_scored_cycle()
    cycle = scenario["cycle"]
    version_before = cycle["version"]

    response = api.create_dimension_overrides(
        cycle["id"],
        dimension_overrides_payload(
            [{"dimension_score_id": NON_EXISTENT_UUID, "raw_points": 18}],
            version_before,
            override_reason="analyst judgement on restricted reserves",
        ),
        analyst_headers,
    )
    validate_error(response, "ERR_DIMENSION_SCORE_NOT_FOUND", 404)

    rows = read_dimension_scores(cycle["id"], analyst_headers)
    assert len(rows) == 4
    assert all(row["status"] == "COMPUTED" for row in rows)
    assert dimension_by_name(rows, "FINANCIAL_HEALTH")["raw_points"] == 29
    assert dimension_by_name(rows, "ACCOUNTABILITY")["raw_points"] == 21
    assert dimension_by_name(rows, "TRANSPARENCY")["raw_points"] == 20
    assert dimension_by_name(rows, "IMPACT")["raw_points"] == 11

    after = read_cycle(cycle["id"], analyst_headers)
    assert after["version"] == version_before
    assert_score(after["final_composite_score"], 83.13, "final_composite_score")
