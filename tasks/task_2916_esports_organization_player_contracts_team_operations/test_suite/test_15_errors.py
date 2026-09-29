"""One envelope for every refusal, and nothing written by any of them.

A 404, a 400, a 409, a 412 and a 403 arrive in five different bands of the
evaluation order, but the shape of the body is identical in all five and each one
leaves the database exactly as it found it.
"""

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    api_client,
    assertions,
    factories,
    fixtures,
    is_iso8601_timestamp,
    make_finance_officer_headers,
    make_general_manager_headers,
    make_league_admin_headers,
    make_scout_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ERROR_DATA_KEYS = {"error_id", "message"}
ERROR_META_KEYS = {"api_request_id", "api_request_timestamp"}


def _refusal(response, expected_error_id, expected_status):
    """Assert one refusal and return its whole envelope for shape checks."""
    validate_error(response, expected_error_id, expected_status)
    body = response.json()
    assertions.assert_error_envelope(body, expected_error_id)
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == ERROR_META_KEYS
    assert body["meta"]["api_request_id"]
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert set(body["data"].keys()) == ERROR_DATA_KEYS
    assert body["data"]["message"].strip()
    return body


def test_five_refusals_from_five_bands_share_one_envelope_and_write_nothing():
    """404, 400, 409, 412 and 403 all carry exactly error_id and message, and none of them persists.

    PRD: "An unresolvable league yields `ERR_LEAGUE_NOT_FOUND`, an organization
    `ERR_ORGANIZATION_NOT_FOUND`, a player `ERR_PLAYER_NOT_FOUND`, a contract offer
    `ERR_OFFER_NOT_FOUND`, a player contract `ERR_CONTRACT_NOT_FOUND`, a team house
    `ERR_TEAM_HOUSE_NOT_FOUND`, a practice block `ERR_PRACTICE_BLOCK_NOT_FOUND`, a sponsorship deal
    `ERR_DEAL_NOT_FOUND`, a deliverable assignment `ERR_DELIVERABLE_NOT_FOUND`, a prize distribution
    `ERR_DISTRIBUTION_NOT_FOUND` and a roster move `ERR_ROSTER_MOVE_NOT_FOUND`."
    PRD: "New talent enters the system through a scout, who registers a prospect with a `full_name`
    of 1 to 120 characters, a `birth_date` written as `YYYY-MM-DD`, and a `region_code` of 2 to 8
    uppercase characters naming the competitive region the player was found in."
    PRD: "Any of these yields `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD: "A distribution must be in `CALCULATED`, or `ERR_DISTRIBUTION_NOT_CALCULATED` (HTTP 409) is
    returned, and the approving `X-User-ID` must differ from the recorded `calculated_by_user_id`, or
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) is returned."
    PRD: "If the value does not equal the organization's current `version`, the filing is rejected
    with `ERR_ORGANIZATION_VERSION_STALE` and HTTP 412, and no move is created."
    PRD: "**Authorization** — `X-User-Role` recognised and permitted on the endpoint, else
    `ERR_UNAUTHORIZED`."
    PRD: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/error_envelope_shape_is_uniform_across_status_classes
    """
    ctx = fixtures.setup_signed_player()
    org_id = ctx["org"]["id"]
    admin_headers = make_league_admin_headers()
    scout_headers = make_scout_headers()
    finance_headers = make_finance_officer_headers()

    distribution = fixtures.create_distribution(org_id, ctx["league"]["id"])
    assert distribution["distribution_status"] == "DRAFT"

    stale_organization_version = fixtures.current_organization_version(org_id)
    bumped = validate_success(
        api_client.update_organization(
            org_id, {"annual_salary_budget_cents": 60000000}, admin_headers
        )
    )
    assert bumped["version"] == stale_organization_version + 1

    not_found = _refusal(
        api_client.get_player(MISSING_UUID, scout_headers),
        ApiErrorId.ERR_PLAYER_NOT_FOUND.value,
        404,
    )

    malformed = _refusal(
        api_client.create_player(
            {"full_name": "Iris Vale", "birth_date": "2003-02-02"}, scout_headers
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    wrong_state = _refusal(
        api_client.approve_prize_distribution(distribution["id"], admin_headers),
        ApiErrorId.ERR_DISTRIBUTION_NOT_CALCULATED.value,
        409,
    )

    stale = _refusal(
        api_client.create_roster_move(
            factories.create_roster_move_payload(
                org_id,
                ctx["player"]["id"],
                "RELEASE",
                ctx["contract"]["id"],
                stale_organization_version,
            ),
            make_general_manager_headers(org_id),
        ),
        ApiErrorId.ERR_ORGANIZATION_VERSION_STALE.value,
        412,
    )

    forbidden = _refusal(
        api_client.create_league(factories.create_minimal_league_payload(), scout_headers),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    for envelope in (not_found, malformed, wrong_state, stale, forbidden):
        assert envelope["response_type"] == "error"
        assert set(envelope["data"].keys()) == ERROR_DATA_KEYS
        for leaked in ("id", "version", "created_at", "updated_at"):
            assert leaked not in envelope["data"]

    players, players_meta = validate_paginated(
        api_client.list_players(scout_headers, params={"limit": 10, "offset": 0})
    )
    assert players_meta["total_count"] == 1
    assert [row["id"] for row in players] == [ctx["player"]["id"]]

    _moves, moves_meta = validate_paginated(
        api_client.list_roster_moves(
            admin_headers, params={"organization_id": org_id, "limit": 10, "offset": 0}
        )
    )
    assert moves_meta["total_count"] == 0

    untouched_distribution = validate_success(
        api_client.get_prize_distribution(distribution["id"], finance_headers)
    )
    assert untouched_distribution["distribution_status"] == "DRAFT"
    assert untouched_distribution["version"] == distribution["version"]
    assert untouched_distribution["approved_by_user_id"] is None

    leagues, leagues_meta = validate_paginated(
        api_client.list_leagues(admin_headers, params={"limit": 10, "offset": 0})
    )
    assert leagues_meta["total_count"] == 1
    assert [row["id"] for row in leagues] == [ctx["league"]["id"]]
