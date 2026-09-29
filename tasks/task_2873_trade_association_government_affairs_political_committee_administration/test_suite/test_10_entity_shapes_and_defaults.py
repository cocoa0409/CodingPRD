"""Entity creation, retrieval, defaults, computed fields and not-found errors."""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    DEFAULT_CLOCK_STAMP,
    DIRECTOR,
    NON_EXISTENT_UUID,
    api_client,
    assert_bare_uuid,
    assert_candidate_accumulator_split,
    assert_instant_equals,
    assert_member,
    canonicalize_instant,
    create_candidate_payload,
    create_contribution_payload,
    create_member_payload,
    create_policy_position_payload,
    create_seat_payload,
    enroll_member,
    open_fund,
    read_candidate,
    read_member,
    register_candidate,
    request_prior_approval,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_creating_a_member_persists_its_inputs_and_derives_its_system_fields():
    """One POST returns 201, a bare UUID, version 1 and the derived notice method.

    PRD 3.1: "Its `home_jurisdiction_code` is one of `FEDERAL`, `STATE_CA` or `STATE_NY` and
    decides which dues-deductibility method the company's annual notice will use; the server
    resolves that decision immediately and stores the answer on the member as
    `notice_method`, either `RATIO` or `FLAT_FLOOR`, taken from the jurisdiction rule book
    of §2.5."
    PRD 2.4: "Every resource the API persists carries a server-minted `id`: a UUID
    string with no type prefix and no client influence."

    Design: Corner/Entities/create_member_persists_inputs_and_derives_system_fields
    """
    set_clock(DEFAULT_CLOCK_STAMP)
    payload = create_member_payload(
        legal_name="Alpha Steel Co",
        membership_tier="PREMIER",
        home_jurisdiction_code="FEDERAL",
        home_district_code="CA-12",
        annual_dues_cents=400_000,
        dues_year=2026,
        restricted_class_size=25,
        status="ACTIVE",
        advocacy_optout=False,
        engagement_score=90,
    )
    member = validate_success(api_client.create_member(payload, ADMIN), 201)

    assert_member(member)
    assert member["legal_name"] == "Alpha Steel Co"
    assert member["membership_tier"] == "PREMIER"
    assert member["home_jurisdiction_code"] == "FEDERAL"
    assert member["home_district_code"] == "CA-12"
    assert member["annual_dues_cents"] == 400_000
    assert member["dues_year"] == 2026
    assert member["restricted_class_size"] == 25
    assert member["status"] == "ACTIVE"
    assert member["advocacy_optout"] is False
    assert member["engagement_score"] == 90
    assert member["notice_method"] == "RATIO"
    assert member["pac_solicitable"] is False
    assert member["recorded_dissent_count"] == 0

    assert_bare_uuid(member["id"])
    assert member["version"] == 1
    assert_instant_equals(member["created_at"], DEFAULT_CLOCK_STAMP, "created_at")
    assert canonicalize_instant(member["updated_at"]) == canonicalize_instant(
        member["created_at"]
    )


def test_reading_a_member_back_mutates_nothing():
    """The GET is a pure read and STATE_CA resolves to the flat-floor method.

    PRD 2.4: "`version` (integer) — a counter that starts at 1 and increments by
    exactly 1 on every mutation of the resource."
    PRD 3.1: "`notice_method` is never accepted from the client, even if supplied."

    Design: Corner/Entities/read_member_returns_the_stored_row
    """
    created = enroll_member(
        legal_name="Beta Foundry Co",
        membership_tier="FULL",
        home_jurisdiction_code="STATE_CA",
        home_district_code="CA-12",
        restricted_class_size=15,
    )

    member = read_member(created["id"])
    assert member["id"] == created["id"]
    assert member["membership_tier"] == "FULL"
    assert member["home_jurisdiction_code"] == "STATE_CA"
    assert member["notice_method"] == "FLAT_FLOOR"
    assert member["version"] == 1
    assert canonicalize_instant(member["updated_at"]) == canonicalize_instant(
        member["created_at"]
    )
    assert member == created


def test_a_members_prior_approvals_page_in_created_at_order():
    """limit 1 walks the register chronologically and the status filter narrows it.

    PRD 2.3: "Both appear in the `meta` object of the response envelope alongside
    `total_count` (the number of items that match the request before pagination is
    applied) and `has_more` (true when items remain beyond the returned page)."
    PRD 2.3: "Filters are applied before pagination, so `total_count` reflects the
    filtered set."

    Design: Corner/Entities/list_member_prior_approvals_paginates_in_created_at_order
    """
    member = enroll_member(
        legal_name="Alpha Steel Co", membership_tier="PREMIER", restricted_class_size=25
    )
    first = request_prior_approval(
        member["id"], effective_date="2026-01-01", expires_at_date="2026-03-31"
    )
    second = request_prior_approval(
        member["id"], effective_date="2026-04-01", expires_at_date="2026-06-30"
    )

    rows, meta = validate_paginated(
        api_client.list_member_prior_approvals(
            member["id"], COMPLIANCE, {"limit": 1, "offset": 0}
        )
    )
    assert [row["id"] for row in rows] == [first["id"]]
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0

    rows, meta = validate_paginated(
        api_client.list_member_prior_approvals(
            member["id"], COMPLIANCE, {"limit": 1, "offset": 1}
        )
    )
    assert [row["id"] for row in rows] == [second["id"]]
    assert meta["total_count"] == 2
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_member_prior_approvals(
            member["id"], COMPLIANCE, {"status": "GRANTED"}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_an_unused_but_valid_uuid_is_a_member_not_found():
    """The priority-4 existence check answers 404, not an empty 200.

    PRD 2.11: "Every path-templated resource exists, checked left to right —
    otherwise the matching not-found error (404)."
    PRD 2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/Entities/read_unknown_member_id_returns_member_not_found
    """
    existing = enroll_member(
        legal_name="Alpha Steel Co", membership_tier="PREMIER", restricted_class_size=25
    )

    response = api_client.get_member(NON_EXISTENT_UUID, ADMIN)
    error = validate_error(response, "ERR_MEMBER_NOT_FOUND", 404)
    assert isinstance(error["message"], str)
    assert error["message"].strip() != ""

    assert read_member(existing["id"])["version"] == 1


def test_a_candidate_without_a_district_code_is_a_shape_violation():
    """district_code has no default, so omitting it is caught before any scoring.

    PRD 2.11: "The request body is well shaped: required fields present, types
    correct, enum values legal, contribution amounts of at least 1 cent, hours
    non-negative with at most three decimals, percentages within 0.00 to 100.00, and
    dates written as ISO `YYYY-MM-DD` calendar dates — otherwise
    `ERR_INVALID_REQUEST` (400)."
    PRD 2.11: "This ordering is normative: a request that is both
    unauthenticated and malformed reports `ERR_UNAUTHENTICATED`, and a request whose
    committee roster is still forming and whose position is in the wrong state reports
    the state error first, because the state gate sits above the roster gate."

    Design: Corner/Entities/create_candidate_without_district_code_rejected
    """
    set_clock(DEFAULT_CLOCK_STAMP)
    payload = create_candidate_payload(
        name="Rep. Jane Alvarez",
        office="US_HOUSE",
        jurisdiction_code="FEDERAL",
        election_cycle="2026-GENERAL",
        incumbency="INCUMBENT",
        voting_alignment_pct=90.00,
        committee_relevance_score=80,
    )
    payload.pop("district_code")

    validate_error(api_client.create_candidate(payload, DIRECTOR), "ERR_INVALID_REQUEST", 400)

    accepted = register_candidate(name="Rep. Jane Alvarez", district_code="CA-12")
    assert accepted["district_code"] == "CA-12"


def test_omitting_the_optional_member_fields_applies_the_declared_defaults():
    """The three defaulted inputs land on ACTIVE, false and 50 - not null, not 0.

    PRD 3.1: "Three fields are optional at enrollment and take documented defaults:
    `status`, one of `ACTIVE`, `LAPSED` or `SUSPENDED`, defaults to `ACTIVE`;
    `advocacy_optout`, a boolean, defaults to false; and `engagement_score`, an
    integer from 0 to 100, defaults to 50."
    PRD 3.1: "Two member fields are pure bookkeeping and start at their floor:
    `recorded_dissent_count` is initialised to 0 and rises only when a formal dissent
    of this member is registered by an adoption, and `pac_solicitable` is initialised
    to false."

    Design: Corner/Entities/create_member_omitting_optional_fields_applies_declared_defaults
    """
    set_clock(DEFAULT_CLOCK_STAMP)
    payload = create_member_payload(
        legal_name="Gamma Tooling Co",
        membership_tier="ASSOCIATE",
        home_jurisdiction_code="STATE_NY",
        home_district_code="NY-05",
        annual_dues_cents=250_000,
        dues_year=2026,
        restricted_class_size=5,
    )
    assert "status" not in payload
    assert "advocacy_optout" not in payload
    assert "engagement_score" not in payload

    member = validate_success(api_client.create_member(payload, ADMIN), 201)
    assert member["status"] == "ACTIVE"
    assert member["advocacy_optout"] is False
    assert member["engagement_score"] == 50
    assert member["notice_method"] == "RATIO"
    assert member["pac_solicitable"] is False
    assert member["recorded_dissent_count"] == 0
    assert member["version"] == 1


def test_client_supplied_computed_and_system_fields_on_a_contribution_are_ignored():
    """The server recomputes the score, the ceiling, the status, the id and version.

    PRD 3.9: "An accepted proposal is written in `PENDING_BOARD` status with
    `proposed_by_user_id` taken from `X-User-ID`, `board_approved_by_user_id`,
    `disbursed_at`, `voided_at` and `void_reason` all null, and it adds its
    `amount_cents` to the candidate's `pending_support_cents`."
    PRD 3.9: "The result is written to the contribution's `support_score` and also
    copied to the candidate's `latest_support_score`, which therefore always reflects
    the most recently created contribution for that candidate."

    Design: Corner/Entities/create_contribution_computed_and_system_fields_input_ignored
    """
    fund = open_fund(name="NMA Federal PAC", min_reserve_cents=0)
    candidate = register_candidate(
        name="Rep. Jane Alvarez",
        incumbency="INCUMBENT",
        voting_alignment_pct=90.00,
        committee_relevance_score=80,
    )

    payload = create_contribution_payload(
        fund["id"],
        candidate["id"],
        amount_cents=100_000,
        memo="Client tries to pin the score",
        support_score=99.99,
        max_allowed_cents=999_999,
        status="BOARD_APPROVED",
        id="11111111-1111-1111-1111-111111111111",
        version=7,
    )
    contribution = validate_success(api_client.create_pac_contribution(payload, DIRECTOR), 201)

    assert float(contribution["support_score"]) == 80.50
    assert contribution["max_allowed_cents"] == 250_000
    assert contribution["status"] == "PENDING_BOARD"
    assert contribution["proposed_by_user_id"] == "gad-1"
    assert contribution["id"] != "11111111-1111-1111-1111-111111111111"
    assert contribution["version"] == 1

    stored = read_candidate(candidate["id"])
    assert float(stored["latest_support_score"]) == 80.50
    assert_candidate_accumulator_split(stored, pending=100_000, committed=0, disbursed=0)


def test_seating_under_an_unknown_committee_path_reports_the_committee():
    """The path parent is checked before the body foreign key.

    PRD 2.11: "Every path-templated resource exists, checked left to right —
    otherwise the matching not-found error (404)."
    PRD 2.8: "For any request whose path carries more than one identifier, existence is
    validated **strictly left to right**, and the first identifier that does not resolve
    determines the error."

    Design: Corner/Entities/create_seat_under_unknown_committee_path_not_found
    """
    member = enroll_member(
        legal_name="Alpha Steel Co", membership_tier="PREMIER", restricted_class_size=25
    )

    response = api_client.create_committee_seat(
        NON_EXISTENT_UUID, create_seat_payload(member["id"], seat_role="CHAIR"), DIRECTOR
    )
    validate_error(response, "ERR_COMMITTEE_NOT_FOUND", 404)

    rows, meta = validate_paginated(
        api_client.list_member_committee_seats(member["id"], DIRECTOR)
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_an_unknown_body_committee_id_is_reported_before_jurisdiction_coherence():
    """The priority-7 body foreign key answers 404 ahead of the 422 scope gate.

    PRD 2.8: "Body-level references — `committee_id`, `member_id`, `position_id`,
    `registration_id`, `fund_id` and `candidate_id` — are resolved before any business
    rule that depends on the referenced row is evaluated, and each has its own
    not-found error: `ERR_COMMITTEE_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
    `ERR_POSITION_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_FUND_NOT_FOUND` and
    `ERR_CANDIDATE_NOT_FOUND`."
    PRD 2.11: "Every foreign key supplied in the body resolves — otherwise the
    matching not-found error (404)."

    Design: Corner/Entities/create_position_with_unknown_body_committee_id_not_found
    """
    set_clock(DEFAULT_CLOCK_STAMP)
    payload = create_policy_position_payload(
        NON_EXISTENT_UUID,
        title="Orphan Position",
        jurisdiction_code="STATE_NY",
        summary="References a committee that does not exist.",
    )

    validate_error(
        api_client.create_policy_position(payload, DIRECTOR), "ERR_COMMITTEE_NOT_FOUND", 404
    )


def test_a_membership_tier_outside_the_closed_enum_is_refused():
    """An unlisted tier has no voting weight, so it is refused rather than defaulted.

    PRD 3.1: "Enrollment records the company's `legal_name` (non-empty, at most 200
    characters) and its `membership_tier`, one of `ASSOCIATE`, `FULL` or `PREMIER`."
    PRD 3.1: "The tier is a dues concept on its face, but it is also the source of
    committee voting weight, so it is worth stating the mapping early: an `ASSOCIATE`
    member carries one unit of weight, a `FULL` member two, and a `PREMIER` member
    three."

    Design: Corner/Entities/create_member_with_illegal_membership_tier_rejected
    """
    set_clock(DEFAULT_CLOCK_STAMP)
    illegal = create_member_payload(legal_name="Omega Alloys Co", membership_tier="GOLD")

    validate_error(api_client.create_member(illegal, ADMIN), "ERR_INVALID_REQUEST", 400)

    legal = create_member_payload(legal_name="Omega Alloys Co", membership_tier="ASSOCIATE")
    accepted = validate_success(api_client.create_member(legal, ADMIN), 201)
    assert accepted["membership_tier"] == "ASSOCIATE"
