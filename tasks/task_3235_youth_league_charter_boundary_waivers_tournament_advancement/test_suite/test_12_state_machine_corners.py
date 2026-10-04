"""Not-found and invalid-request corners for leagues, renewals, and waivers."""
from test_helpers import (
    TEST_USERS, api_client, validate_error, validate_success,
    get_success_data, ApiErrorId, NON_EXISTENT_UUID,
    set_clock, charter_league, create_league_raw, add_insurance,
    submit_renewal, approve_renewal, register_player, get_league,
    get_renewal, get_player, attach_standard_documents, verify_player,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]


def test_get_unknown_league_returns_league_not_found(api):
    """PRD §2.7: "The first identifier that fails to resolve produces the
    corresponding not-found error — `ERR_LEAGUE_NOT_FOUND`,
    `ERR_DIVISION_NOT_FOUND`, `ERR_PLAYER_NOT_FOUND`, `ERR_RENEWAL_NOT_FOUND`,
    `ERR_WAIVER_NOT_FOUND`, `ERR_VOLUNTEER_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`,
    `ERR_ROSTER_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_GAME_NOT_FOUND`, or
    `ERR_PROTEST_NOT_FOUND` — each with HTTP 404, and no later identifier is
    examined once an earlier one has failed."

    Design: Corner/entities/get_unknown_league_returns_league_not_found
    """
    err = validate_error(api.get_league(NON_EXISTENT_UUID, LA),
                         ApiErrorId.ERR_LEAGUE_NOT_FOUND)
    assert err["error_id"] == "ERR_LEAGUE_NOT_FOUND"


def test_renewal_submission_without_season_year_is_invalid_request(api):
    """PRD §3.2: "A `LeagueAdministrator` submits a renewal request naming the
    `season_year` the renewal covers; the year must not be earlier than the
    league's own `season_year`"
    PRD §5: "ERR_INVALID_REQUEST | 400"

    Design: Corner/entities/renewal_create_missing_season_year_returns_invalid_request
    """
    set_clock("2026-10-15T00:00:00Z")
    league, _divisions = create_league_raw(league_name="Required LL")
    err = validate_error(api.create_charter_renewal(league["id"], {}, LA),
                         ApiErrorId.ERR_INVALID_REQUEST)
    assert err["error_id"] == "ERR_INVALID_REQUEST"


def test_decide_on_approved_renewal_returns_not_pending(api):
    """PRD §3.2: "A decision against a renewal that is no longer `SUBMITTED` is
    rejected with `ERR_RENEWAL_NOT_PENDING` (HTTP 409)."

    Design: Corner/state_machines/renewal_decide_on_approved_returns_not_pending
    """
    ctx = charter_league(league_name="Terminal LL")
    renewal = ctx["renewal"]
    assert renewal["status"] == "APPROVED"

    err = validate_error(api.decide_charter_renewal(
        ctx["league"]["id"], renewal["id"],
        {"action": "REJECT", "late_fee_paid": False}, DA),
        ApiErrorId.ERR_RENEWAL_NOT_PENDING)
    assert err["error_id"] == "ERR_RENEWAL_NOT_PENDING"
    assert get_renewal(renewal["id"])["status"] == "APPROVED"


def test_waiver_create_with_empty_window_is_invalid_request(api):
    """PRD §3.5: "The end must come strictly after the start; a window that is
    empty or inverted is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.5: "Successful creation puts the waiver in `PENDING` status and bumps
    the league's `version` by 1."

    Design: Corner/entities/waiver_create_invalid_window_returns_invalid_request
    """
    ctx = charter_league(league_name="Window LL")
    set_clock("2027-02-01T00:00:00Z")
    player = register_player(ctx["league"]["id"], first_name="Wi",
                             last_name="Ndow")
    league = get_league(ctx["league"]["id"])

    err = validate_error(api.create_boundary_waiver(
        ctx["league"]["id"],
        {"player_id": player["id"], "waiver_type": "RESIDENCY_BOUNDARY",
         "reason": "bad window", "valid_from": "2027-06-01",
         "valid_until": "2027-06-01",
         "expected_league_version": league["version"]}, LA),
        ApiErrorId.ERR_INVALID_REQUEST)
    assert err["error_id"] == "ERR_INVALID_REQUEST"
    # The failed creation does not bump the league's version.
    assert get_league(ctx["league"]["id"])["version"] == league["version"]


def test_waiver_revoke_requires_approved_and_revoked_is_terminal(api):
    """PRD §3.5: "Approval or denial requires the waiver to be `PENDING`;
    revocation requires it to be `APPROVED`; any other combination is rejected
    with `ERR_WAIVER_NOT_PENDING` (HTTP 409)."
    PRD §3.5: "Revocation moves an approved waiver to `REVOKED`, also terminal"

    Design: Corner/state_machines/waiver_revoke_from_pending_rejected_and_approved_revoke_works
    """
    ctx = charter_league(league_name="Waiver State LL")
    set_clock("2027-02-01T00:00:00Z")
    player = register_player(ctx["league"]["id"], first_name="Wa",
                             last_name="Iver")
    league = get_league(ctx["league"]["id"])
    waiver = get_success_data(api.create_boundary_waiver(
        ctx["league"]["id"],
        {"player_id": player["id"], "waiver_type": "RESIDENCY_BOUNDARY",
         "reason": "move pending", "valid_from": "2027-01-01",
         "valid_until": "2027-12-01",
         "expected_league_version": league["version"]}, LA))
    assert waiver["status"] == "PENDING"

    # REVOKE on a PENDING waiver is rejected.
    err = validate_error(api.decide_boundary_waiver(
        ctx["league"]["id"], waiver["id"], {"action": "REVOKE"}, DA),
        ApiErrorId.ERR_WAIVER_NOT_PENDING)
    assert err["error_id"] == "ERR_WAIVER_NOT_PENDING"

    validate_success(api.decide_boundary_waiver(
        ctx["league"]["id"], waiver["id"], {"action": "APPROVE"}, DA), 200)
    revoked = validate_success(api.decide_boundary_waiver(
        ctx["league"]["id"], waiver["id"], {"action": "REVOKE"}, DA), 200)
    assert revoked["status"] == "REVOKED"

    # APPROVE on a REVOKED waiver is rejected — REVOKED is terminal.
    err3 = validate_error(api.decide_boundary_waiver(
        ctx["league"]["id"], waiver["id"], {"action": "APPROVE"}, DA),
        ApiErrorId.ERR_WAIVER_NOT_PENDING)
    assert err3["error_id"] == "ERR_WAIVER_NOT_PENDING"


def test_verify_on_already_eligible_player_rejected(api):
    """PRD §3.4: "A player in any other state cannot be verified; the attempt is
    rejected with `ERR_PLAYER_NOT_VERIFIABLE` (HTTP 409)."

    Design: Corner/state_machines/verify_eligibility_on_already_eligible_rejected
    """
    ctx = charter_league(league_name="Idem LL")
    set_clock("2027-02-01T00:00:00Z")
    player = register_player(ctx["league"]["id"], first_name="Id",
                             last_name="Emp")
    attach_standard_documents(ctx["league"]["id"], player["id"])
    verified = verify_player(ctx["league"]["id"], player["id"])
    assert verified["eligibility_status"] == "ELIGIBLE"

    err = validate_error(api.verify_eligibility(
        ctx["league"]["id"], player["id"], LA, {}),
        ApiErrorId.ERR_PLAYER_NOT_VERIFIABLE)
    assert err["error_id"] == "ERR_PLAYER_NOT_VERIFIABLE"
    assert get_player(player["id"])["eligibility_status"] == "ELIGIBLE"
