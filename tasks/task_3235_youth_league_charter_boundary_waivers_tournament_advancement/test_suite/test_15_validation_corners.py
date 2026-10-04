"""Auth, permission, and nested-existence corners of the validation ladder."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, NO_USER_HEADERS,
    set_clock, create_league_raw, charter_league, register_player,
    attach_standard_documents, verify_player, get_player, get_volunteer,
    create_boundary_waiver_payload, get_league,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]


def test_request_without_user_context_headers_rejected(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, naming the role under which the user
    acts. A request missing either header, or carrying a role value outside the
    enumerated set, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_rejected_before_anything
    """
    set_clock("2026-10-15T00:00:00Z")
    league, _ = create_league_raw(league_name="Auth LL")
    err = validate_error(api.get_league(league["id"], NO_USER_HEADERS),
                         ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    assert err["error_id"] == "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"


def test_wrong_role_for_write_returns_forbidden(api):
    """PRD §2.1: "A request whose role is valid but not authorized for the
    target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    PRD §4: "| POST | /leagues/{leagueId}/players | Register a player;
    computes league age, division assignment, and participation percentage |
    LeagueAdministrator |"
    PRD §4: "| POST | /leagues/{leagueId}/charter-renewals/{renewalId}/decide |
    Approve or reject a SUBMITTED renewal; approval computes the final fee and
    charters the league | DistrictAdministrator |"

    Design: Corner/validations/wrong_role_for_write_returns_forbidden
    """
    set_clock("2026-10-15T00:00:00Z")
    league, _ = create_league_raw(league_name="Roles LL")
    renewal = get_success_data(api.create_charter_renewal(
        league["id"], {"season_year": 2027}, LA))

    err1 = validate_error(api.create_player(
        league["id"],
        {"first_name": "X", "last_name": "Y", "birth_date": "2015-03-10",
         "residence_within_boundary": True, "school_within_boundary": False,
         "games_played": 3, "games_scheduled": 5}, TD),
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert err1["error_id"] == "ERR_INSUFFICIENT_PERMISSIONS"

    err2 = validate_error(api.decide_charter_renewal(
        league["id"], renewal["id"],
        {"action": "APPROVE", "late_fee_paid": False}, LA),
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert err2["error_id"] == "ERR_INSUFFICIENT_PERMISSIONS"


def test_nested_existence_validated_left_to_right(api):
    """PRD §2.7: "For every nested endpoint, the path parameters are validated
    strictly left to right: the league identifier first, then the next
    identifier in the path (player, volunteer, renewal, waiver, roster, or
    division), then the entry identifier, then the game identifier, and finally
    the protest or screening identifier. The first identifier that fails to
    resolve produces the corresponding not-found error"

    Design: Corner/validations/nested_existence_left_to_right
    """
    set_clock("2026-10-15T00:00:00Z")
    league, _ = create_league_raw(league_name="Nested LL")

    # Unknown league + unknown player: the league check fires first.
    err1 = validate_error(api.list_eligibility_documents(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID, LA),
        ApiErrorId.ERR_LEAGUE_NOT_FOUND)
    assert err1["error_id"] == "ERR_LEAGUE_NOT_FOUND"

    # Known league + unknown player: the player check fires.
    err2 = validate_error(api.list_eligibility_documents(
        league["id"], NON_EXISTENT_UUID, LA),
        ApiErrorId.ERR_PLAYER_NOT_FOUND)
    assert err2["error_id"] == "ERR_PLAYER_NOT_FOUND"


def test_residency_waiver_satisfies_boundary_requirement(api):
    """PRD §3.4: "The third condition is boundary satisfaction: at least one of
    the player's `residence_within_boundary` flag, the player's
    `school_within_boundary` flag, or an approved residency-boundary waiver
    whose window covers the current clock date must hold; otherwise the
    verification is rejected with `ERR_OUTSIDE_BOUNDARY` (HTTP 422)."

    Design: Corner/validations/residency_waiver_satisfies_boundary_requirement
    """
    ctx = charter_league(league_name="Boundary LL")
    set_clock("2027-02-01T00:00:00Z")
    player = register_player(ctx["league"]["id"], first_name="Out",
                             last_name="Sider", residence=False, school=False)
    attach_standard_documents(ctx["league"]["id"], player["id"])

    err = validate_error(api.verify_eligibility(
        ctx["league"]["id"], player["id"], LA, {}),
        ApiErrorId.ERR_OUTSIDE_BOUNDARY)
    assert err["error_id"] == "ERR_OUTSIDE_BOUNDARY"

    league = get_league(ctx["league"]["id"])
    waiver = get_success_data(api.create_boundary_waiver(
        ctx["league"]["id"],
        {"player_id": player["id"], "waiver_type": "RESIDENCY_BOUNDARY",
         "reason": "parental relocation", "valid_from": "2027-01-01",
         "valid_until": "2027-12-01",
         "expected_league_version": league["version"]}, LA))
    validate_success(api.decide_boundary_waiver(
        ctx["league"]["id"], waiver["id"], {"action": "APPROVE"}, DA), 200)

    verified = verify_player(ctx["league"]["id"], player["id"])
    assert verified["eligibility_status"] == "ELIGIBLE"


def test_stale_document_rejected_then_fresh_document_passes(api):
    """PRD §3.4: "In addition, each `RESIDENCE_PROOF` or `SCHOOL_ENROLLMENT`
    relied upon must have been issued within 365 days before the verification
    date; a document issued more than 365 days earlier yields
    `ERR_DOCUMENT_EXPIRED` (HTTP 422)."

    Design: Corner/validations/stale_document_rejected_at_verify
    """
    ctx = charter_league(league_name="Stale Docs LL")
    set_clock("2027-02-01T00:00:00Z")
    # Eligibility rests on school attendance, so the document the freshness
    # rule relies upon is the SCHOOL_ENROLLMENT.
    player = register_player(ctx["league"]["id"], first_name="St",
                             last_name="Ale", residence=False, school=True)
    get_success_data(api.create_eligibility_document(
        ctx["league"]["id"], player["id"],
        {"doc_type": "BIRTH_CERTIFICATE", "issued_date": "2015-03-12"}, LA))
    # 396 days old at the 2027-02-01 verification.
    get_success_data(api.create_eligibility_document(
        ctx["league"]["id"], player["id"],
        {"doc_type": "SCHOOL_ENROLLMENT", "issued_date": "2026-01-01"}, LA))

    err = validate_error(api.verify_eligibility(
        ctx["league"]["id"], player["id"], LA, {}),
        ApiErrorId.ERR_DOCUMENT_EXPIRED)
    assert err["error_id"] == "ERR_DOCUMENT_EXPIRED"

    # A fresh residency-basis document then passes the same verification.
    get_success_data(api.create_eligibility_document(
        ctx["league"]["id"], player["id"],
        {"doc_type": "SCHOOL_ENROLLMENT", "issued_date": "2027-01-15"}, LA))
    verified = verify_player(ctx["league"]["id"], player["id"])
    assert verified["eligibility_status"] == "ELIGIBLE"


def test_severe_screening_cannot_be_approved_but_can_be_disqualified(api):
    """PRD §3.8: "At submission the screening computes `auto_flagged`: true
    exactly when the `offense_category` is one of `VIOLENT_FELONY`,
    `SEXUAL_OFFENSE`, or `CHILD_ABUSE`."
    PRD §3.8: "and the `offense_category` must not be one of the three severe
    categories — `VIOLENT_FELONY`, `SEXUAL_OFFENSE`, `CHILD_ABUSE` — or the
    approval is rejected with `ERR_DISQUALIFYING_OFFENSE` (HTTP 422)."
    PRD §3.8: "A disqualification moves the screening to `DISQUALIFIED` and the
    volunteer from `REGISTERED` to `DISQUALIFIED`, which is terminal for the
    volunteer."

    Design: Corner/validations/severe_screening_cannot_be_approved_but_can_be_disqualified
    """
    ctx = charter_league(league_name="Severe LL")
    volunteer = get_success_data(api.create_volunteer(
        ctx["league"]["id"],
        {"full_name": "Bad Actor", "role_title": "COACH"}, LA))
    screening = get_success_data(api.create_screening(
        ctx["league"]["id"], volunteer["id"],
        {"offense_category": "SEXUAL_OFFENSE",
         "valid_from": "2027-01-01", "valid_through": "2027-12-31"}, LA))
    assert screening["auto_flagged"] is True

    err = validate_error(api.adjudicate_screening(
        ctx["league"]["id"], volunteer["id"], screening["id"],
        {"action": "APPROVE"}, DA),
        ApiErrorId.ERR_DISQUALIFYING_OFFENSE)
    assert err["error_id"] == "ERR_DISQUALIFYING_OFFENSE"

    disqualified = validate_success(api.adjudicate_screening(
        ctx["league"]["id"], volunteer["id"], screening["id"],
        {"action": "DISQUALIFY"}, DA), 200)
    assert disqualified["status"] == "DISQUALIFIED"
    assert get_volunteer(volunteer["id"])["status"] == "DISQUALIFIED"
