"""Opening a cycle: the records the commission mints, how they are read back,
and the shape of every envelope around them."""

from test_helpers import (
    ApiErrorId,
    NONEXISTENT_ID,
    PETITION_DEADLINE,
    TEST_USERS,
    adjudicate_signature_payload,
    assert_candidacy,
    assert_election,
    assert_petition_ledger_conserved,
    assert_pct,
    assert_stamped_timestamp,
    assert_student,
    create_ballot,
    create_candidacy_payload,
    create_election_payload,
    create_office_payload,
    create_student_payload,
    declare_election,
    declare_office,
    is_valid_uuid,
    make_candidate_headers,
    open_petitioning,
    read_candidacy,
    read_election,
    register_student,
    set_clock,
    setup_petition_under_review,
    setup_three_member_slate,
    validate_error,
    validate_paginated,
    validate_success,
)

COMMISSIONER = TEST_USERS["commissioner_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def test_election_declaration_applies_the_declared_defaults(api):
    """PRD §3.1: "A newly declared election begins in `DRAFT` with `current_round` at 1
    and `ballot_integrity_status` at `INTACT`. Its `voting_opens_at`, `voting_closes_at`,
    `certified_by_user_id` and `certified_at` are all empty, and its derived counters —
    `eligible_voter_count`, `ballots_cast_count` and `runoff_required_office_count` at
    zero, `turnout_pct` at 0.00 — stay that way until the cycle produces the facts that
    fill them."
    PRD §3.1: "The commission may also set `quiet_period_hours`, the length of the
    pre-poll campaign blackout measured backwards from the moment polls open; it is a
    non-negative integer and defaults to 24 — one full day of silence before voting —
    when the payload omits it."
    PRD §2.6: "`version` (integer): starts at 1 when the resource is created and
    increments by exactly 1 on every mutation of that resource."

    Design: Corner/entities/election_creation_applies_declared_defaults
    """
    payload = create_election_payload()
    payload.pop("quiet_period_hours", None)

    election = validate_success(api.create_election(payload, COMMISSIONER), 201)

    assert_election(election)
    assert election["status"] == "DRAFT", f"expected DRAFT, got {election['status']}"
    assert election["current_round"] == 1
    assert election["quiet_period_hours"] == 24, (
        f"quiet_period_hours defaults to 24, got {election['quiet_period_hours']}"
    )
    assert election["ballot_integrity_status"] == "INTACT"
    assert election["eligible_voter_count"] == 0
    assert election["ballots_cast_count"] == 0
    assert_pct(election["turnout_pct"], 0.00, "turnout_pct")
    assert election["runoff_required_office_count"] == 0
    assert election["certified_by_user_id"] is None
    assert election["certified_at"] is None
    assert election["voting_opens_at"] is None
    assert election["voting_closes_at"] is None
    assert election["version"] == 1


def test_student_registration_mints_the_system_managed_properties(api):
    """PRD §2.6: "`id` (string): a server-minted UUID, with no type prefix of any kind."
    PRD §2.6: "`created_at` (string): an ISO 8601 UTC timestamp with three fractional
    digits (for example `2026-08-01T00:00:00.000Z`), stamped from the logical clock at
    the moment of creation."
    PRD §3.1: "three attributes with defaults: `enrollment_status`, which is `ENROLLED`
    unless stated otherwise and may also be `LEAVE` or `WITHDRAWN`; `credits_completed`,
    a non-negative integer defaulting to 0; and `disciplinary_hold`, a boolean defaulting
    to false."

    Design: Corner/entities/student_system_fields_are_server_minted
    """
    payload = create_student_payload(full_name="Ava Stone", class_year="SENIOR",
                                     gpa=3.50, credits_completed=95)
    payload.pop("enrollment_status", None)
    payload.pop("disciplinary_hold", None)

    student = validate_success(api.create_student(payload, REGISTRAR), 201)

    assert_student(student)
    assert is_valid_uuid(student["id"]), f"id must be a bare UUID, got {student['id']!r}"
    assert len(student["id"]) == 36, "a server-minted UUID carries no type prefix"
    assert_stamped_timestamp(student["created_at"], "Student.created_at")
    assert student["version"] == 1
    assert student["enrollment_status"] == "ENROLLED"
    assert student["disciplinary_hold"] is False


def test_election_listing_paginates_and_reports_envelope_metadata(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return.
    If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The
    `offset` parameter specifies the number of items to skip and defaults to 0."
    PRD §2.3: "Paginated and non-paginated list-based responses include the following
    fields in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/election_listing_is_paginated_with_envelope_metadata
    """
    declare_election(title="Fall 2026 SGA General")
    declare_election(title="Fall 2026 Class Council")

    response = api.list_elections(
        COMMISSIONER, params={"limit": 1, "offset": 0, "academic_year": "2026-2027"}
    )
    rows, meta = validate_paginated(response)

    body = response.json()
    assert body["response_type"] == "array", "a list read reports response_type array"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert meta["total_count"] == 2, f"expected 2 elections, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert meta["limit"] == 1 and meta["offset"] == 0
    assert len(rows) == 1, f"limit=1 returns one row, got {len(rows)}"


def test_limit_above_the_maximum_is_rejected_and_the_maximum_itself_is_accepted(api):
    """PRD §2.3: "A `limit` that is not an integer, or that falls outside the inclusive
    range 1 through 100, and an `offset` that is not an integer or is negative, are both
    rejected with `ERR_INVALID_PAGINATION`."

    Design: Corner/validations/pagination_limit_above_maximum_returns_invalid_pagination
    """
    declare_election()

    rejected = api.list_elections(COMMISSIONER, params={"limit": 101})
    validate_error(rejected, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)

    rows, meta = validate_paginated(api.list_elections(COMMISSIONER, params={"limit": 100}))
    assert meta["total_count"] == 1, "limit 100 sits inside the inclusive range"
    assert meta["has_more"] is False
    assert len(rows) == 1


def test_reading_an_unknown_election_returns_the_election_not_found_code(api):
    """PRD §2.5: "Each path parameter has its own dedicated not-found error:
    `election_id` yields `ERR_ELECTION_NOT_FOUND`, `office_id` yields
    `ERR_OFFICE_NOT_FOUND`, `student_id` yields `ERR_STUDENT_NOT_FOUND`, `candidacy_id`
    yields `ERR_CANDIDACY_NOT_FOUND`, `petition_signature_id` yields
    `ERR_SIGNATURE_NOT_FOUND`, `campaign_expense_id` yields `ERR_EXPENSE_NOT_FOUND`,
    `compliance_case_id` yields `ERR_CASE_NOT_FOUND`, `referendum_id` yields
    `ERR_REFERENDUM_NOT_FOUND`, `ballot_id` yields `ERR_BALLOT_NOT_FOUND`,
    `ballot_line_id` yields `ERR_BALLOT_LINE_NOT_FOUND`, `vote_id` yields
    `ERR_VOTE_NOT_FOUND`, and `appeal_id` yields `ERR_APPEAL_NOT_FOUND`."

    Design: Corner/entities/election_not_found_returns_404
    """
    response = api.get_election(NONEXISTENT_ID, COMMISSIONER)

    validate_error(response, ApiErrorId.ERR_ELECTION_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"


def test_every_collection_answers_with_its_own_not_found_code(api):
    """PRD §2.5: "Each path parameter has its own dedicated not-found error:
    `election_id` yields `ERR_ELECTION_NOT_FOUND`, `office_id` yields
    `ERR_OFFICE_NOT_FOUND`, `student_id` yields `ERR_STUDENT_NOT_FOUND`, `candidacy_id`
    yields `ERR_CANDIDACY_NOT_FOUND`, `petition_signature_id` yields
    `ERR_SIGNATURE_NOT_FOUND`, `campaign_expense_id` yields `ERR_EXPENSE_NOT_FOUND`,
    `compliance_case_id` yields `ERR_CASE_NOT_FOUND`, `referendum_id` yields
    `ERR_REFERENDUM_NOT_FOUND`, `ballot_id` yields `ERR_BALLOT_NOT_FOUND`,
    `ballot_line_id` yields `ERR_BALLOT_LINE_NOT_FOUND`, `vote_id` yields
    `ERR_VOTE_NOT_FOUND`, and `appeal_id` yields `ERR_APPEAL_NOT_FOUND`."
    PRD §2.5: "All twelve carry HTTP 404."

    Design: Corner/errors/unknown_resource_ids_return_entity_specific_not_found_codes
    """
    probes = [
        (api.get_student(NONEXISTENT_ID, COMMISSIONER), ApiErrorId.ERR_STUDENT_NOT_FOUND),
        (api.get_candidacy(NONEXISTENT_ID, COMMISSIONER), ApiErrorId.ERR_CANDIDACY_NOT_FOUND),
        (api.get_petition_signature(NONEXISTENT_ID, COMMISSIONER), ApiErrorId.ERR_SIGNATURE_NOT_FOUND),
        (api.get_campaign_expense(NONEXISTENT_ID, COMMISSIONER), ApiErrorId.ERR_EXPENSE_NOT_FOUND),
        (api.get_compliance_case(NONEXISTENT_ID, COMMISSIONER), ApiErrorId.ERR_CASE_NOT_FOUND),
        (api.get_referendum(NONEXISTENT_ID, COMMISSIONER), ApiErrorId.ERR_REFERENDUM_NOT_FOUND),
        (api.get_ballot(NONEXISTENT_ID, COMMISSIONER), ApiErrorId.ERR_BALLOT_NOT_FOUND),
        (api.get_ballot_line(NONEXISTENT_ID, COMMISSIONER), ApiErrorId.ERR_BALLOT_LINE_NOT_FOUND),
        (api.get_vote(NONEXISTENT_ID, COMMISSIONER), ApiErrorId.ERR_VOTE_NOT_FOUND),
        (api.get_appeal(NONEXISTENT_ID, COMMISSIONER), ApiErrorId.ERR_APPEAL_NOT_FOUND),
    ]
    for response, expected in probes:
        assert response.status_code == 404, (
            f"expected HTTP 404 for {expected.value}, got {response.status_code}"
        )
        assert response.json()["response_type"] == "error"
        validate_error(response, expected.value, 404)


def test_declaring_an_election_without_the_quorum_share_is_rejected(api):
    """PRD §2.5: "Every required body field is present and every value satisfies its
    declared type, enum domain and numeric range — `ERR_INVALID_REQUEST` (400), on every
    endpoint with a request body."
    PRD §3.1: "The declaration carries a `title` of between 1 and 200 characters, an
    `academic_year` label written as two four-digit years joined by a hyphen (for example
    `2026-2027`), a `petition_deadline` instant after which no candidacy may be approved
    onto the ballot, the per-candidacy campaign `spending_cap_cents` and `poster_cap`
    (both non-negative), a `quorum_pct` that any referendum on this ballot must clear on
    turnout, and a `runoff_threshold_pct` that a leading candidacy must reach to win a
    seat outright."

    Design: Corner/entities/election_missing_required_field_returns_invalid_request
    """
    payload = create_election_payload()
    payload.pop("quorum_pct")

    validate_error(
        api.create_election(payload, COMMISSIONER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _, meta = validate_paginated(api.list_elections(COMMISSIONER))
    assert meta["total_count"] == 0, "a rejected declaration mints no election"


def test_office_class_year_outside_the_enum_domain_is_rejected(api):
    """PRD §3.1: "Each **Office** names the `election_id` it belongs to, a `name` such as
    President or Junior Class Representative, the `eligible_class_years` permitted both to
    run for and to vote on that seat — a non-empty subset of `FRESHMAN`, `SOPHOMORE`,
    `JUNIOR`, `SENIOR` and `GRADUATE` — the `required_signature_count` a petition must
    reach, and the `term_start_date` and `term_end_date` the seat confers."
    PRD §2.5: "Every required body field is present and every value satisfies its declared
    type, enum domain and numeric range — `ERR_INVALID_REQUEST` (400), on every endpoint
    with a request body."

    Design: Corner/entities/office_invalid_class_year_enum_returns_invalid_request
    """
    election = declare_election()

    payload = create_office_payload(election["id"], eligible_class_years=["SUPERSENIOR"])
    validate_error(
        api.create_office(payload, COMMISSIONER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _, meta = validate_paginated(
        api.list_offices(COMMISSIONER, params={"election_id": election["id"]})
    )
    assert meta["total_count"] == 0, "a rejected declaration mints no office"


def test_freshly_filed_candidacy_reports_every_counter_at_zero(api):
    """PRD §3.2: "A candidacy is born in `status` `DRAFT` with `transition_status`
    `NOT_APPLICABLE`; its `training_modules_completed`, every one of its petition and
    spending counters, `penalty_points_total`, `raw_votes_count` and
    `certified_votes_count` all start at zero, `provisional_share_pct` and
    `certified_share_pct` at 0.00, `slate_snapshot_member_ids` empty, and
    `ballot_position`, `spending_final_cents`, `disqualified_reason`, `term_start_date`,
    `term_end_date` and `activated_at` all empty."

    Design: Corner/entities/candidacy_computed_counters_start_at_zero
    """
    election = declare_election()
    office = declare_office(election["id"], eligible_class_years=["SENIOR"])
    student = register_student(class_year="SENIOR", gpa=3.50, credits_completed=95)
    open_petitioning(election["id"])

    candidacy = validate_success(
        api.create_candidacy(
            create_candidacy_payload(election["id"], office["id"], student["id"]),
            make_candidate_headers(student["id"]),
        ),
        201,
    )

    assert_candidacy(candidacy)
    assert candidacy["status"] == "DRAFT"
    assert candidacy["transition_status"] == "NOT_APPLICABLE"
    assert candidacy["training_modules_completed"] == 0
    assert candidacy["petition_signature_total_count"] == 0
    assert candidacy["petition_signature_valid_count"] == 0
    assert candidacy["spending_reported_cents"] == 0
    assert candidacy["spending_committed_cents"] == 0
    assert candidacy["penalty_points_total"] == 0
    assert candidacy["raw_votes_count"] == 0
    assert candidacy["certified_votes_count"] == 0
    assert_pct(candidacy["provisional_share_pct"], 0.00, "provisional_share_pct")
    assert_pct(candidacy["certified_share_pct"], 0.00, "certified_share_pct")
    assert candidacy["slate_snapshot_member_ids"] == []
    assert candidacy["ballot_position"] is None
    assert candidacy["spending_final_cents"] is None
    assert candidacy["disqualified_reason"] is None
    assert candidacy["activated_at"] is None
    assert_petition_ledger_conserved(candidacy)


def test_body_foreign_key_to_an_unknown_office_returns_the_office_code(api):
    """PRD §2.5: "Identifiers supplied in a request body are resolved next, in the order
    the fields appear in that endpoint's input list, and they raise the same twelve
    not-found errors. Body-level foreign-key resolution applies to candidacy filing,
    office declaration, petition-signature creation, campaign-expense reporting,
    compliance-case filing, referendum drafting, ballot creation, ballot-line creation,
    vote casting, appeal filing, and slate-membership changes."

    Design: Corner/entities/candidacy_body_foreign_key_to_unknown_office_returns_not_found
    """
    election = declare_election()
    declare_office(election["id"], eligible_class_years=["SENIOR"])
    student = register_student(class_year="SENIOR", gpa=3.50, credits_completed=95)
    open_petitioning(election["id"])

    validate_error(
        api.create_candidacy(
            create_candidacy_payload(election["id"], NONEXISTENT_ID, student["id"]),
            make_candidate_headers(student["id"]),
        ),
        ApiErrorId.ERR_OFFICE_NOT_FOUND.value,
        404,
    )

    _, meta = validate_paginated(
        api.list_candidacies(COMMISSIONER, params={"election_id": election["id"]})
    )
    assert meta["total_count"] == 0, "the rejected filing mints no candidacy"


def test_candidacy_list_filtered_by_slate_leader_returns_only_the_members(api):
    """PRD §2.3: "Candidacies filter on `election_id`, `office_id`, `student_id`,
    `slate_leader_candidacy_id`, `status` and `transition_status`."
    PRD §3.2: "Two optional attributes may accompany the filing: a `statement` printed on
    the ballot, and a `slate_leader_candidacy_id` naming the slate this run belongs to.
    Omitting the latter files an independent run."

    Design: Corner/entities/candidacy_list_filtered_by_slate_leader_returns_members
    """
    scenario = setup_three_member_slate()
    leader = scenario["leader"]
    members = {scenario["member_one"]["id"], scenario["member_two"]["id"]}

    rows, meta = validate_paginated(
        api.list_candidacies(
            COMMISSIONER, params={"slate_leader_candidacy_id": leader["id"]}
        )
    )

    assert meta["total_count"] == 2, (
        f"the leader has exactly two members, got {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == members
    assert leader["id"] not in {row["id"] for row in rows}, (
        "the leader carries no slate leader of its own and must not match the filter"
    )


def test_election_version_moves_only_on_its_own_declared_mutations(api):
    """PRD §2.6: "`version` (integer): starts at 1 when the resource is created and
    increments by exactly 1 on every mutation of that resource."
    PRD §3.1: "Opening petitioning moves the election from `DRAFT` to `PETITIONING` and is
    the commission's own act."
    PRD §3.6: "All three forms increment the election's `version`."

    Design: Corner/cross_cutting_complexity_layers/election_version_increments_on_each_declared_mutation
    """
    election = declare_election()
    assert election["version"] == 1, "a freshly declared election is at version 1"

    declare_office(election["id"], eligible_class_years=["SENIOR"])
    after_office = read_election(election["id"])
    assert after_office["version"] == 1, (
        "declaring a seat mutates no field of the election, so its version holds at 1, "
        f"got {after_office['version']}"
    )

    after_open = open_petitioning(election["id"])
    assert after_open["version"] == 2, (
        f"opening petitioning is a mutation of the election, got {after_open['version']}"
    )

    set_clock(PETITION_DEADLINE)
    create_ballot(election["id"], 1, after_open["version"])

    final = read_election(election["id"])
    assert final["version"] == 3, (
        f"the ballot create increments the election version, got {final['version']}"
    )
    assert final["status"] == "BALLOT_BUILDING"


def test_signature_adjudication_reports_its_cascade_inside_the_same_request(api):
    """PRD §2.9: "When they do, every affected resource independently receives a fresh
    `updated_at` and an incremented `version`, and the full cascade completes within the
    single request that triggered it — this system has no deferred or eventual
    reconciliation."
    PRD §3.3: "an outcome of `VERIFIED` moves the signature `SUBMITTED → VERIFIED` and
    stamps both `verified_by_user_id` and the signature's `eligibility_result`"
    PRD §3.3: "`petition_signature_valid_count` is the number of verified rows whose
    verdict is `ELIGIBLE`, and `petition_signature_ineligible_count` is the number of
    verified rows minus that valid count."

    Design: Corner/consistency_model/cascade_effects_are_visible_in_the_same_request
    """
    scenario = setup_petition_under_review(required_signature_count=1, signer_count=1)
    signature = scenario["signatures"][0]

    adjudicated = validate_success(
        api.adjudicate_signature(
            signature["id"], adjudicate_signature_payload("VERIFIED"), COMMISSIONER
        )
    )

    assert adjudicated["status"] == "VERIFIED", (
        "the adjudicate response already carries the new signature status"
    )
    assert adjudicated["eligibility_result"] == "ELIGIBLE"
    assert adjudicated["verified_by_user_id"] == "commissioner-1"

    candidacy = read_candidacy(scenario["candidacy"]["id"])
    assert candidacy["petition_signature_valid_count"] == 1, (
        "the counter is recomputed inside the adjudicating request"
    )
    assert candidacy["petition_signature_pending_count"] == 0
    assert candidacy["petition_signature_total_count"] == 1
    assert_petition_ledger_conserved(candidacy)
