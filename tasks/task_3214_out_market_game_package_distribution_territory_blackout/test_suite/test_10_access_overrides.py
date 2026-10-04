"""Access control: auth header requirement, role denial, subscriber ownership,
override grant/rescind duty segregation, and scheduled clock transitions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_game,
    create_grant,
    create_market,
    create_season,
    create_slate,
    create_student_verification,
    make_subscriber_headers,
    make_support_agent_headers,
    register_account,
    set_clock,
    setup_week4_game_account_sub,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["league_ops_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


def test_league_ops_cannot_terminate_rights_grant(api, league_ops_headers):
    """PRD §2.1: "`PlatformAdmin` — the distribution partner's platform
    operator. Owns rights-grant creation and termination, offer creation and
    withdrawal, account closure, subscription entitlement suspension and
    restoration, the logical clock, and payment simulation." PRD §2.1: "Once
    authenticated, if the declared role is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/league_ops_cannot_terminate_rights_grant
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    validate_error(
        api.terminate_rights_grant(grant["id"], league_ops_headers),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )
    grant_now = validate_success(api.get_rights_grant(grant["id"], ADMIN))
    assert grant_now["status"] == "ACTIVE"


def test_subscriber_cannot_move_national_selections(api, league_ops_headers):
    """PRD §2.1: "`LeagueOps` — league operations. Owns season phase
    advancement and all weekly-slate curation: national-selection moves,
    finalize, reopen, and lock." PRD §2.1: "if the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/subscriber_cannot_move_national_selections
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    slate = create_slate(season["id"], week_index=4)
    game = create_game(season["id"], week_index=4, away_team_code="KC",
                       home_team_code="DAL",
                       kickoff_at="2026-08-30T17:00:00Z",
                       home_market_code="DAL")
    account = register_account(email="rbac@x.com", billing_zip="10001")
    validate_error(
        api.slate_selection(
            slate["id"], game["id"], "ADD", slate["version"],
            make_subscriber_headers(account["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )
    slate_now = validate_success(api.get_week_slate(slate["id"], league_ops_headers))
    assert slate_now["national_game_ids"] == []


def test_subscriber_cannot_cancel_another_accounts_subscription(
    api, platform_admin_headers
):
    """PRD §2.1: "When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id`
    of the acting `Account`; ownership checks on any resource that references
    an `Account` compare the resource's account foreign key to `X-User-ID`,
    and a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/peer_role_ownership_enforced_on_subscriber_resources
    """
    ctx = setup_week4_game_account_sub(email="owna@x.com", billing_zip="10001")
    other = register_account(email="ownb@x.com", billing_zip="10001")
    validate_error(
        api.cancel_subscription(
            ctx["subscription"]["id"], make_subscriber_headers(other["id"])
        ),
        ApiErrorId.ERR_NOT_OWNER,
    )
    sub_now = validate_success(
        api.get_subscription(ctx["subscription"]["id"], platform_admin_headers)
    )
    assert sub_now["status"] == "ACTIVE"


def test_owner_subscriber_cancel_succeeds(api, platform_admin_headers):
    """PRD §2.1: "When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id`
    of the acting `Account`; ownership checks on any resource that references
    an `Account` compare the resource's account foreign key to `X-User-ID`,
    and a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/peer_role_ownership_enforced_on_subscriber_resources
    """
    ctx = setup_week4_game_account_sub(email="ownc@x.com", billing_zip="10001")
    cancelled = validate_success(
        api.cancel_subscription(
            ctx["subscription"]["id"],
            make_subscriber_headers(ctx["account"]["id"]),
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["entitlement_state"] == "REVOKED"


def _override_setup(api):
    """NYC-billed account, ACTIVE sub, DAL-home game; device in DAL is
    BLACKED_OUT; override granted by agent sa-jane."""
    ctx = setup_week4_game_account_sub(
        email="ovr@x.com", billing_zip="10001", markets=("NYC", "DAL"),
    )
    override = validate_success(
        api.create_entitlement_override(
            ctx["account"]["id"], ctx["games"][0]["id"], "GOODWILL",
            make_support_agent_headers("sa-jane"),
        ),
        expected_status=201,
    )
    assert override["created_by"] == "sa-jane"
    ctx["override"] = override
    return ctx


def test_active_override_forces_available_and_rescind_restores_blackout(api):
    """PRD §3.10: "while `ACTIVE`, it forces the territory-check verdict
    `AVAILABLE` for that (account, game) pair, overriding any other link in
    the §3.6 chain." PRD §3.10: "Rescinding moves `ACTIVE` → `RESCINDED`
    (terminal) and is permitted only to the agent recorded as `created_by` —
    any other agent, even another `SupportAgent`, is `ERR_NOT_OWNER`."

    Design: Corner/rbac/override_rescind_restricted_to_granting_agent
    """
    ctx = _override_setup(api)
    account_id = ctx["account"]["id"]
    game_id = ctx["games"][0]["id"]
    sub_id = ctx["subscription"]["id"]

    check_with = validate_success(
        api.create_territory_check(
            account_id, sub_id, game_id, "75001",
            make_subscriber_headers(account_id),
        ),
        expected_status=201,
    )
    assert check_with["verdict"] == "AVAILABLE"

    validate_error(
        api.rescind_entitlement_override(
            ctx["override"]["id"], make_support_agent_headers("sa-other")
        ),
        ApiErrorId.ERR_NOT_OWNER,
    )
    override_now = validate_success(
        api.get_entitlement_override(ctx["override"]["id"], ADMIN)
    )
    assert override_now["status"] == "ACTIVE"

    rescinded = validate_success(
        api.rescind_entitlement_override(
            ctx["override"]["id"], make_support_agent_headers("sa-jane")
        )
    )
    assert rescinded["status"] == "RESCINDED"

    check_without = validate_success(
        api.create_territory_check(
            account_id, sub_id, game_id, "75001",
            make_subscriber_headers(account_id),
        ),
        expected_status=201,
    )
    assert check_without["verdict"] == "BLACKED_OUT"


def test_rescinded_override_is_terminal(api):
    """PRD §3.10: "Rescinding moves `ACTIVE` → `RESCINDED` (terminal) and is
    permitted only to the agent recorded as `created_by`".

    Design: Corner/rbac/override_rescind_restricted_to_granting_agent
    """
    ctx = _override_setup(api)
    validate_success(
        api.rescind_entitlement_override(
            ctx["override"]["id"], make_support_agent_headers("sa-jane")
        )
    )
    resp = api.rescind_entitlement_override(
        ctx["override"]["id"], make_support_agent_headers("sa-jane")
    )
    assert resp.status_code == 409, (
        f"rescinding a RESCINDED override must fail 409, got {resp.status_code}"
    )
    assert resp.json()["data"]["error_id"] in (
        ApiErrorId.ERR_ALREADY_TERMINAL.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_missing_auth_headers_rejected_on_protected_endpoint(api):
    """PRD §2.1: "A request missing either header, or carrying a role value
    outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401). The single exception is account registration, which is reachable by
    an unauthenticated caller acting as `Anonymous`."

    Design: Corner/rbac/missing_auth_headers_rejected_on_protected_endpoint
    """
    set_clock("2026-09-01T00:00:00Z")
    market = create_market(code="NYC", name="New York", zip_prefixes=["100"],
                           home_team_codes=["NYC"])
    validate_error(
        api.get_market(market["id"], {"Content-Type": "application/json"}),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )
    account = validate_success(
        api.register_account(
            {
                "email": "anon@x.com",
                "full_name": "Anon Ymous",
                "account_kind": "RESIDENTIAL",
                "billing_zip": "10001",
            },
            {},
        ),
        expected_status=201,
    )
    assert account["status"] == "ACTIVE"


def test_protected_endpoint_requires_known_role_value(api):
    """PRD §2.1: "A request missing either header, or carrying a role value
    outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/rbac/missing_auth_headers_rejected_on_protected_endpoint
    """
    set_clock("2026-09-01T00:00:00Z")
    market = create_market(code="NYC", name="New York", zip_prefixes=["100"],
                           home_team_codes=["NYC"])
    validate_error(
        api.get_market(
            market["id"],
            {"X-User-ID": "nobody", "X-User-Role": "SuperUser",
             "Content-Type": "application/json"},
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )


def test_clock_advance_expires_grant_and_student_verification(api):
    """PRD §3.1: "on every set of the logical clock the system re-evaluates
    time-based transitions, and once the logical clock reaches or passes
    `effective_until` the grant auto-transitions from `ACTIVE` to `EXPIRED`."
    PRD §3.9: "On every logical-clock set, once the clock reaches or passes
    `valid_through`, the record auto-transitions `VERIFIED` → `EXPIRED`".

    Design: Corner/cross_cutting_layers/scheduled_transitions_fire_on_clock_advance
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant(effective_until="2026-10-01T00:00:00Z")
    account = register_account(email="clk@x.com", billing_zip="10001")
    sv = create_student_verification(
        account["id"], valid_through="2026-10-01T00:00:00Z"
    )
    assert sv["status"] == "VERIFIED"

    set_clock("2026-10-02T00:00:00Z")
    grant_now = validate_success(api.get_rights_grant(grant["id"], ADMIN))
    assert grant_now["status"] == "EXPIRED"
    sv_now = validate_success(api.get_student_verification(sv["id"], AUDITOR))
    assert sv_now["status"] == "EXPIRED"


def test_grant_and_verification_survive_until_their_horizons(api):
    """PRD §3.1: "once the logical clock reaches or passes `effective_until`
    the grant auto-transitions from `ACTIVE` to `EXPIRED`." PRD §3.9: "once
    the clock reaches or passes `valid_through`, the record auto-transitions
    `VERIFIED` → `EXPIRED`".

    Design: Corner/cross_cutting_layers/scheduled_transitions_fire_on_clock_advance
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant(effective_until="2026-10-01T00:00:00Z")
    account = register_account(email="clk2@x.com", billing_zip="10001")
    sv = create_student_verification(
        account["id"], valid_through="2026-10-01T00:00:00Z"
    )
    # Before either horizon: both remain in their initial states.
    set_clock("2026-09-30T23:59:59Z")
    grant_now = validate_success(api.get_rights_grant(grant["id"], ADMIN))
    assert grant_now["status"] == "ACTIVE"
    sv_now = validate_success(api.get_student_verification(sv["id"], AUDITOR))
    assert sv_now["status"] == "VERIFIED"
