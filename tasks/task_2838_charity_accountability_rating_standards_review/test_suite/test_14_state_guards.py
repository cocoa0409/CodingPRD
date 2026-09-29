"""Initial states, idempotency refusals and undeclared transitions."""
from test_helpers import (
    FILING_FY2025,
    adopt_methodology_payload,
    assert_instant,
    assert_score,
    create_draft_methodology,
    create_governance_profile_payload,
    create_organization,
    decide_correction_payload,
    file_complaint,
    make_public_headers,
    open_comment,
    read_complaint,
    read_correction,
    read_cycle,
    read_filing,
    read_governance_profile,
    revoke_waiver_payload,
    set_clock,
    setup_scored_cycle,
    setup_submitted_correction,
    submit_validated_filing,
    triage_complaint,
    triage_complaint_payload,
    validate_error,
    validate_filing_payload,
    validate_paginated,
    validate_success,
    waive_standard_payload,
)


def _standard_by_code(api, profile_id, headers, standard_code):
    rows, _meta = validate_paginated(
        api.list_standard_evaluations(
            profile_id, headers, params={"standard_code": standard_code}
        )
    )
    assert len(rows) == 1, f"expected one {standard_code} row, got {len(rows)}"
    return rows[0]


def test_recording_a_governance_disclosure_evaluates_nothing(api, analyst_headers):
    """Both board counts are stored, yet the independence ratio and all four standards
    counts wait for the separate evaluate step, and no dimension row exists yet.

    PRD §3.4: "Recording the disclosure evaluates nothing: the new profile lands with `evaluation_status` `PENDING`, a null `independence_ratio`, a null `evaluated_at`, and `standards_met_count`, `standards_not_met_count`, `standards_waived_count` and `standards_not_applicable_count` all zero."

    PRD §3.5: "Scoring closes by writing everything at once: the four dimension rows are created on a first score, travelling `PENDING` → `COMPUTED`, or rewritten on a re-score; `program_expense_ratio`, `fundraising_efficiency` and `months_of_reserve` are stored; `failed_standard_count` is refreshed from the governance profile; `data_completeness_pct` is stored; both composite variants are evaluated, writing `weighted_sum_provisional`, `provisional_composite_score` and `provisional_grade` from the provisional variant and `weighted_sum_final`, `final_composite_score` and `grade` from the final one, with `standards_penalty_points` recording the **final** variant's penalty; and the cycle's `version` counter advances by one."

    Design: Corner/state_machines/governance_profile_initial_state_is_pending_with_zeroed_counts
    """
    scenario = setup_scored_cycle(
        filings=[(2025, FILING_FY2025)], evaluate=False, score=False
    )
    cycle = scenario["cycle"]

    profile = validate_success(
        api.create_governance_profile(
            create_governance_profile_payload(cycle["id"]), analyst_headers
        ),
        201,
    )

    assert profile["evaluation_status"] == "PENDING"
    assert profile["evaluated_at"] is None
    assert profile["independence_ratio"] is None
    assert profile["board_member_count"] == 7
    assert profile["independent_board_member_count"] == 4
    assert profile["standards_met_count"] == 0
    assert profile["standards_not_met_count"] == 0
    assert profile["standards_waived_count"] == 0
    assert profile["standards_not_applicable_count"] == 0

    _rows, standards_meta = validate_paginated(
        api.list_standard_evaluations(profile["id"], analyst_headers)
    )
    assert standards_meta["total_count"] == 0

    after = read_cycle(cycle["id"], analyst_headers)
    assert after["status"] == "DATA_COLLECTION"
    assert after["failed_standard_count"] == 0

    _dimensions, dimension_meta = validate_paginated(
        api.list_dimension_scores(cycle["id"], analyst_headers)
    )
    assert dimension_meta["total_count"] == 0


def test_accepting_an_already_validated_filing_does_not_supersede_it_with_itself(
    api, analyst_headers
):
    """A replayed acceptance would run the supersede sweep over the row itself and leave
    the fiscal year with no winning filing, so the transition is refused.

    PRD §3.3: "Validation is a `RatingAnalyst` decision on a `RECEIVED` filing — any other starting status is `ERR_FILING_STATE_INVALID` — carrying a `decision` and, when that decision is to reject, a `rejection_code`; a rejection with no code supplied is `ERR_INVALID_REQUEST`."

    PRD §3.3: "Any *other* filing sharing the same `organization_id`, the same `fiscal_year` and the same `source_kind` whose `status` is `VALIDATED` moves `VALIDATED` → `SUPERSEDED`, takes `superseded_at` from the logical clock, and has its own `version` counter advanced by one."

    Design: Corner/state_machines/filing_record_validate_twice_returns_filing_state_invalid
    """
    organization = create_organization()
    filing = submit_validated_filing(organization["id"], fiscal_year=2025, **FILING_FY2025)
    assert filing["status"] == "VALIDATED"

    response = api.validate_filing_record(
        filing["id"], validate_filing_payload("ACCEPT"), analyst_headers
    )
    validate_error(response, "ERR_FILING_STATE_INVALID", 409)

    after = read_filing(filing["id"], analyst_headers)
    assert after["status"] == "VALIDATED"
    assert after["superseded_at"] is None
    assert_instant(after["validated_at"], filing["validated_at"], "validated_at")
    assert after["version"] == filing["version"]


def test_a_comment_window_cannot_be_re_armed_and_adoption_cannot_skip_the_close(
    api, admin_headers
):
    """Re-opening would silently extend the public consultation from a clock that has
    moved on, and adoption is reachable only through close-comment.

    PRD §3.1: "Opening the public comment window moves the version `DRAFT` → `COMMENT_OPEN`; attempting it on a version in any other status is `ERR_METHODOLOGY_STATE_INVALID`."

    PRD §3.2: "The version must be `COMMENT_CLOSED`, or the request is `ERR_METHODOLOGY_STATE_INVALID`; its `unresolved_comment_count` must be zero, or the request is `ERR_UNRESOLVED_COMMENTS`; and its effectivity window must satisfy every rule of admission check 17 — a `effective_from` at least 30 days beyond the logical clock, an `effective_until` strictly after `effective_from` when supplied, and no overlap with the closed effectivity interval of any other `ADOPTED` version other than the one this adoption is superseding — or the request is `ERR_METHODOLOGY_WINDOW_CONFLICT`."

    PRD §3.1: "The transition stamps `comment_open_at` with the logical clock, derives `comment_deadline_at` as that instant plus the version's own `comment_period_days`, and advances the version's `version` counter by one."

    Design: Corner/state_machines/methodology_open_comment_from_comment_open_rejected
    """
    methodology = create_draft_methodology()
    opened = open_comment(methodology["id"])
    assert opened["status"] == "COMMENT_OPEN"
    set_clock("2026-08-10T00:00:00Z")

    validate_error(
        api.open_comment(methodology["id"], admin_headers),
        "ERR_METHODOLOGY_STATE_INVALID",
        409,
    )
    validate_error(
        api.adopt_methodology_version(
            methodology["id"],
            adopt_methodology_payload("2026-12-01T00:00:00Z"),
            admin_headers,
        ),
        "ERR_METHODOLOGY_STATE_INVALID",
        409,
    )

    after = validate_success(
        api.get_methodology_version(methodology["id"], admin_headers)
    )
    assert after["status"] == "COMMENT_OPEN"
    assert_instant(after["comment_open_at"], "2026-08-01T00:00:00Z", "comment_open_at")
    assert_instant(
        after["comment_deadline_at"], "2026-08-31T00:00:00Z", "comment_deadline_at"
    )
    assert after["adopted_at"] is None
    assert after["effective_from"] is None


def test_evaluating_a_governance_profile_twice_does_not_append_a_second_eight_rows(
    api, analyst_headers
):
    """A replay would double the standards fan-out and re-derive the counts from a clock
    that has moved, so only a PENDING profile may be evaluated.

    PRD §3.4: "Evaluation is a separate step, admissible only while the profile's `evaluation_status` is `PENDING` — otherwise `ERR_GOVERNANCE_STATE_INVALID` — and only while the owning rating cycle is still in `DATA_COLLECTION`, otherwise `ERR_CYCLE_STATE_INVALID`."

    PRD §3.4: "It then mints exactly eight `StandardEvaluation` rows, one per `standard_code`, each carrying the `governance_profile_id` it belongs to, a `result`, a stringified `observed_value` taken from the profile, a stringified `required_value` naming the threshold, an `evaluated_at` stamped from the logical clock, and a null `waiver_reason` and null `waived_by_user_id`."

    Design: Corner/state_machines/governance_profile_evaluate_twice_returns_governance_state_invalid
    """
    scenario = setup_scored_cycle(filings=[(2025, FILING_FY2025)], score=False)
    profile = scenario["governance_profile"]
    assert profile["evaluation_status"] == "EVALUATED"

    validate_error(
        api.evaluate_governance_profile(profile["id"], analyst_headers),
        "ERR_GOVERNANCE_STATE_INVALID",
        409,
    )

    _rows, meta = validate_paginated(
        api.list_standard_evaluations(profile["id"], analyst_headers)
    )
    assert meta["total_count"] == 8

    after = read_governance_profile(profile["id"], analyst_headers)
    assert after["standards_met_count"] == 7
    assert after["standards_not_met_count"] == 1
    assert after["standards_waived_count"] == 0
    assert after["standards_not_applicable_count"] == 0
    assert after["version"] == profile["version"]

    cycle = read_cycle(scenario["cycle"]["id"], analyst_headers)
    assert cycle["failed_standard_count"] == 1


def test_a_met_standard_cannot_be_waived_and_a_not_met_standard_has_no_waiver_to_revoke(
    api, admin_headers, analyst_headers
):
    """Both waiver doors are keyed on the row's current result, which is the only reason
    the four-way partition of the eight standards stays conserved.

    PRD §3.4: "Waiving is admissible only on a row whose `result` is `NOT_MET`, otherwise `ERR_STANDARD_STATE_INVALID`, and only while the owning profile's rating cycle is in neither `PUBLISHED` nor `WITHDRAWN`, otherwise `ERR_CYCLE_STATE_INVALID`."

    PRD §3.4: "Revocation is admissible only on a row whose `result` is `WAIVED`, otherwise `ERR_STANDARD_STATE_INVALID`, and only while the owning cycle is in neither `PUBLISHED` nor `WITHDRAWN`, otherwise `ERR_CYCLE_STATE_INVALID`."

    Design: Corner/state_machines/standard_evaluation_waive_a_met_standard_rejected
    """
    scenario = setup_scored_cycle(filings=[(2025, FILING_FY2025)], score=False)
    profile = scenario["governance_profile"]
    met_row = _standard_by_code(api, profile["id"], admin_headers, "BOARD_SIZE_MIN")
    not_met_row = _standard_by_code(
        api, profile["id"], admin_headers, "CEO_COMP_REVIEW"
    )
    assert met_row["result"] == "MET"
    assert not_met_row["result"] == "NOT_MET"

    validate_error(
        api.waive_standard_evaluation(
            met_row["id"], waive_standard_payload("Board is small by design"), admin_headers
        ),
        "ERR_STANDARD_STATE_INVALID",
        409,
    )
    validate_error(
        api.revoke_standard_waiver(
            not_met_row["id"],
            revoke_waiver_payload("No waiver was ever granted"),
            admin_headers,
        ),
        "ERR_STANDARD_STATE_INVALID",
        409,
    )

    still_met = validate_success(
        api.get_standard_evaluation(met_row["id"], admin_headers)
    )
    assert still_met["result"] == "MET"
    assert still_met["waiver_reason"] is None
    assert still_met["waived_by_user_id"] is None
    assert still_met["version"] == met_row["version"]

    after_profile = read_governance_profile(profile["id"], analyst_headers)
    assert after_profile["standards_met_count"] == 7
    assert after_profile["standards_not_met_count"] == 1
    assert after_profile["standards_waived_count"] == 0
    assert after_profile["version"] == profile["version"]

    cycle = read_cycle(scenario["cycle"]["id"], analyst_headers)
    assert cycle["failed_standard_count"] == 1


def test_a_correction_cannot_be_decided_before_it_is_claimed(api, analyst_headers):
    """The claim step is what records the claimant, so deciding straight from SUBMITTED
    would leave an accepted correction with nobody attached to it.

    PRD §3.7: "The same analyst then decides it with a `decision` and an optional `decision_note`; deciding a request that is not `UNDER_ANALYST_REVIEW` is `ERR_CORRECTION_STATE_INVALID`."

    PRD §3.7: "The cycle's own analyst — and nobody else, on pain of `ERR_NOT_ASSIGNED_ANALYST` — takes ownership of a submitted request, moving it `SUBMITTED` → `UNDER_ANALYST_REVIEW` and recording the acting `X-User-ID` as `claimed_by_user_id`; claiming a request in any other status is `ERR_CORRECTION_STATE_INVALID`."

    Design: Corner/state_machines/correction_request_decide_before_claim_rejected
    """
    scenario = setup_submitted_correction()
    correction = scenario["correction"]
    assert correction["status"] == "SUBMITTED"

    validate_error(
        api.decide_correction_request(
            correction["id"],
            decide_correction_payload("ACCEPT", decision_note="Skipping the claim step"),
            analyst_headers,
        ),
        "ERR_CORRECTION_STATE_INVALID",
        409,
    )

    after = read_correction(correction["id"], analyst_headers)
    assert after["status"] == "SUBMITTED"
    assert after["claimed_by_user_id"] is None
    assert after["decided_by_user_id"] is None
    assert after["decided_at"] is None

    cycle = read_cycle(scenario["cycle"]["id"], analyst_headers)
    assert cycle["status"] == "CORRECTION_REQUESTED"
    assert cycle["correction_round"] == 0

    rows, meta = validate_paginated(
        api.list_dimension_scores(cycle["id"], analyst_headers)
    )
    assert meta["total_count"] == 4
    assert all(row["status"] == "COMPUTED" for row in rows)


def test_a_second_triage_cannot_overwrite_the_credibility_of_an_open_investigation(
    api, analyst_headers
):
    """The replay carries a different disposition, so allowing it would reset an
    investigating complaint's credibility and stamp a resolution on an open case.

    PRD §3.8: "A `RatingAnalyst` triages a complaint that is in `INTAKE`; any other status is `ERR_COMPLAINT_STATE_INVALID`."

    PRD §3.8: "`INVESTIGATE` moves the complaint `INTAKE` → `INVESTIGATING`, computes `credibility_score` under the intake variant, sets `credibility_variant` to `INTAKE`, derives `severity_tier`, and arms `investigation_due_at` at the logical clock plus 30 days."

    Design: Corner/state_machines/complaint_triage_twice_returns_complaint_state_invalid
    """
    organization = create_organization()
    set_clock("2026-09-01T00:00:00Z")
    complaint = file_complaint(
        organization["id"],
        headers=make_public_headers("donor-1"),
        complainant_kind="DONOR",
        category="MISUSE_OF_FUNDS",
        narrative="Restricted gift was spent on general overhead",
        corroborating_document_count=2,
    )
    triaged = triage_complaint(
        complaint["id"], "INVESTIGATE", triage_note="Documents warrant review"
    )
    assert triaged["status"] == "INVESTIGATING"

    validate_error(
        api.triage_complaint(
            complaint["id"],
            triage_complaint_payload("CLOSE_NO_ACTION", triage_note="Changed my mind"),
            analyst_headers,
        ),
        "ERR_COMPLAINT_STATE_INVALID",
        409,
    )

    after = read_complaint(complaint["id"], analyst_headers)
    assert after["status"] == "INVESTIGATING"
    assert after["credibility_variant"] == "INTAKE"
    assert_score(after["credibility_score"], 76.00, "credibility_score")
    assert after["severity_tier"] == "MEDIUM"
    assert after["resolved_at"] is None
    assert_instant(
        after["investigation_due_at"], "2026-10-01T00:00:00Z", "investigation_due_at"
    )
