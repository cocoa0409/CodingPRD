"""Player surface: league-age cutoff computation, division auto-assignment,
document immutability, and list filtering."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    validate_paginated, ApiErrorId,
    set_clock, charter_league, major_division, register_player,
    register_and_verify_player, attach_standard_documents, get_player,
    assert_player, assert_eligibility_document,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]
SCORER = TEST_USERS["official_scorer_headers"]


def test_league_age_cutoff_and_division_assignment(api):
    """PRD §3.3: "Concretely: the age is the league's season year minus the
    player's birth year, and if the player's month-and-day of birth falls after
    August 31 in the calendar — that is, a birth date later in the year than the
    August 31 cutoff — one is subtracted. Players born on or before August 31
    keep the unsubtracted value."
    PRD §3.3: "if the standard division whose range covers the player's
    `league_age` exists among the five — `min_league_age` at or below the age
    and `max_league_age` at or above it — the player's `division_id` is set to
    that division."

    Design: Corner/entities/player_computed_fields_league_age_and_division_assignment
    """
    ctx = charter_league(league_name="Cutoff LL")
    set_clock("2027-02-01T00:00:00Z")
    by_code = ctx["division_by_code"]

    sep = register_player(ctx["league"]["id"], birth_date="2015-09-01",
                          first_name="Sep", last_name="First")
    aug = register_player(ctx["league"]["id"], birth_date="2015-08-31",
                          first_name="Aug", last_name="ThirtyOne")
    assert_player(sep)
    assert_player(aug)
    # Born one day past the cutoff: 2027 - 2015 - 1 = 11 (division: MAJOR, since
    # PRD §3.1 gives MAJOR the 10-12 range; the design instance's "MINOR" label is
    # inconsistent with PRD and is not asserted).
    assert sep["league_age"] == 11
    # Born on the cutoff: 2027 - 2015 = 12 -> MAJOR.
    assert aug["league_age"] == 12
    assert aug["division_id"] == by_code["MAJOR"]["id"]
    assert sep["eligibility_status"] == "PENDING"
    assert aug["eligibility_status"] == "PENDING"
    assert sep["version"] == 1
    assert aug["version"] == 1


def test_age_outside_all_ranges_gets_null_division_and_fails_verify(api):
    """PRD §3.3: "If no standard division covers the age (for example a
    17-year-old, or a 3-year-old), `division_id` is left null."
    PRD §3.4: "The fourth is division assignment: the player's `division_id`
    must be non-null — either from automatic assignment at registration or from
    an approved waiver — and a null `division_id` is rejected with
    `ERR_AGE_DIVISION_MISMATCH` (HTTP 422)."

    Design: Corner/entities/player_age_outside_all_ranges_gets_null_division
    """
    ctx = charter_league(league_name="Too Old LL")
    set_clock("2027-02-01T00:00:00Z")
    player = register_player(ctx["league"]["id"], birth_date="2010-01-01",
                             first_name="Old", last_name="Timer")
    assert player["league_age"] == 17
    assert player["division_id"] is None

    attach_standard_documents(ctx["league"]["id"], player["id"],
                              birth_date="2010-01-01")
    err = validate_error(api.verify_eligibility(
        ctx["league"]["id"], player["id"], LA, {}),
        ApiErrorId.ERR_AGE_DIVISION_MISMATCH)
    assert err["error_id"] == "ERR_AGE_DIVISION_MISMATCH"
    assert get_player(player["id"])["eligibility_status"] == "PENDING"


def test_eligibility_documents_are_immutable_attestations(api):
    """PRD §2.4: "The single exception is the eligibility document resource,
    which is immutable evidence: it carries only `id` and `created_at`;
    `updated_at` and `version` are absent from it entirely."
    PRD §3.4: "Documents are immutable evidence records: they carry an `id` and
    a `created_at` and nothing else — no `updated_at`, no `version`."

    Design: Corner/entities/eligibility_document_is_immutable_attestation
    """
    ctx = charter_league(league_name="Docs LL")
    set_clock("2027-02-01T00:00:00Z")
    player = register_player(ctx["league"]["id"], first_name="Doc",
                             last_name="Holder")

    validate_success(api.create_eligibility_document(
        ctx["league"]["id"], player["id"],
        {"doc_type": "RESIDENCE_PROOF", "issued_date": "2027-01-15"}, LA), 201)
    validate_success(api.create_eligibility_document(
        ctx["league"]["id"], player["id"],
        {"doc_type": "RESIDENCE_PROOF", "issued_date": "2027-01-20"}, LA), 201)

    documents, meta = validate_paginated(api.list_eligibility_documents(
        ctx["league"]["id"], player["id"], LA))
    assert len(documents) == 2
    assert meta["total_count"] == 2
    for document in documents:
        assert_eligibility_document(document)


def test_players_list_filters_by_division_and_eligibility(api):
    """PRD §4: "| GET | /leagues/{leagueId}/players | List players of a league;
    filterable by division_id and eligibility_status |"
    PRD §2.3: "Every list endpoint accepts two optional query parameters:
    `limit`, defaulting to 10, with a minimum of 1 and a maximum of 100, and
    `offset`, defaulting to 0. List responses carry `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object."

    Design: Corner/entities/players_list_filters_by_division_and_eligibility
    """
    ctx = charter_league(league_name="List LL")
    set_clock("2027-02-01T00:00:00Z")
    register_and_verify_player(ctx["league"]["id"], birth_date="2015-03-10",
                               last_name="One")
    register_and_verify_player(ctx["league"]["id"], birth_date="2015-04-11",
                               last_name="Two")
    register_player(ctx["league"]["id"], birth_date="2015-05-12",
                    last_name="Three")
    major = major_division(ctx)

    eligible, meta_eligible = validate_paginated(api.list_players(
        ctx["league"]["id"], TD, params={"eligibility_status": "ELIGIBLE"}))
    assert len(eligible) == 2
    assert meta_eligible["total_count"] == 2

    page, meta_page = validate_paginated(api.list_players(
        ctx["league"]["id"], SCORER,
        params={"division_id": major["id"], "limit": 2, "offset": 2}))
    assert len(page) == 1
    assert meta_page["total_count"] == 3
    assert meta_page["has_more"] is False
    assert meta_page["limit"] == 2
    assert meta_page["offset"] == 2

    all_players, meta_all = validate_paginated(api.list_players(
        ctx["league"]["id"], TD))
    assert meta_all["total_count"] == 3
    assert meta_all["limit"] == 10
    assert len(all_players) == 3
