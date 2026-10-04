"""Composite setup helpers.

The default scenario spine mirrors the shared reference timeline: logical
clock at 2026-09-01T00:00:00Z, grant cap 2000, 18-week season starting
2026-08-05 (so 2026-09-01 falls inside week 4).

All helpers use get_success_data() for setup calls so a failure surfaces as a
clear "Setup failed" error. Every helper builds preconditions from scratch —
the server restarts between tests with an empty database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT, TEST_DEFAULTS
from .factories import (
    create_game_payload,
    create_market_payload,
    create_offer_payload,
    create_rights_grant_payload,
    create_season_payload,
    create_student_verification_payload,
    create_venue_license_payload,
    create_week_slate_payload,
    register_account_payload,
)
from .test_users import (
    TEST_USERS,
    make_subscriber_headers,
    make_venue_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["league_ops_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


def _ok(resp, what):
    data = get_success_data(resp)
    assert resp.status_code < 300, f"Setup failed ({what}): {resp.status_code} {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 1: state progression / base resources
# ---------------------------------------------------------------------------

def set_clock(current_utc=CLOCK_DEFAULT):
    return _ok(api_client.set_clock(current_utc, ADMIN), "set clock")


def create_grant(**overrides) -> dict:
    return _ok(
        api_client.create_rights_grant(create_rights_grant_payload(**overrides), ADMIN),
        "create rights grant",
    )


def create_season(grant_id, **overrides) -> dict:
    return _ok(
        api_client.create_season(create_season_payload(grant_id, **overrides), OPS),
        "create season",
    )


def create_market(**overrides) -> dict:
    return _ok(
        api_client.create_market(create_market_payload(**overrides), OPS),
        "create market",
    )


def create_nyc_dal_la_markets() -> dict:
    """Create the NYC / DAL / LA market set from the shared scenario spine."""
    nyc = create_market(code="NYC", name="New York",
                        zip_prefixes=["100"], home_team_codes=["NYC"])
    dal = create_market(code="DAL", name="Dallas",
                        zip_prefixes=["750"], home_team_codes=["DAL"])
    la = create_market(code="LA", name="Los Angeles",
                       zip_prefixes=["900"], home_team_codes=["LAC"])
    return {"NYC": nyc, "DAL": dal, "LA": la}


def create_slate(season_id, week_index=4) -> dict:
    return _ok(
        api_client.create_week_slate(
            create_week_slate_payload(season_id, week_index=week_index), OPS
        ),
        "create week slate",
    )


def create_game(season_id, **overrides) -> dict:
    return _ok(
        api_client.create_game(create_game_payload(season_id, **overrides), OPS),
        "create game",
    )


def create_offer(season_id, **overrides) -> dict:
    return _ok(
        api_client.create_offer(create_offer_payload(season_id, **overrides), ADMIN),
        "create offer",
    )


def register_account(**overrides) -> dict:
    return _ok(
        api_client.register_account(register_account_payload(**overrides), {}),
        "register account",
    )


def create_student_verification(account_id, **overrides) -> dict:
    return _ok(
        api_client.create_student_verification(
            create_student_verification_payload(account_id, **overrides), AUDITOR
        ),
        "create student verification",
    )


def create_venue_license(account_id, **overrides) -> dict:
    payload = create_venue_license_payload(account_id, **overrides)
    return _ok(
        api_client.create_venue_license(
            payload, make_venue_manager_headers(account_id)
        ),
        "create venue license",
    )


# ---------------------------------------------------------------------------
# Tier 2/3: scenario spine + subscription lifecycle
# ---------------------------------------------------------------------------

def setup_grant_season(clock=CLOCK_DEFAULT, grant_overrides=None, season_overrides=None) -> dict:
    """Grant + season created at the given clock. Returns both."""
    set_clock(clock)
    grant = create_grant(**(grant_overrides or {}))
    season = create_season(grant["id"], **(season_overrides or {}))
    return {"grant": grant, "season": season}


def purchase_subscription(account, offer) -> dict:
    """Create a PENDING_PAYMENT subscription owned by the given account."""
    role_headers = (
        make_venue_manager_headers(account["id"])
        if account["account_kind"] == "COMMERCIAL"
        else make_subscriber_headers(account["id"])
    )
    return _ok(
        api_client.create_subscription(account["id"], offer["id"], role_headers),
        "purchase subscription",
    )


def activate_subscription(subscription) -> dict:
    """Simulate a successful payment: PENDING_PAYMENT -> ACTIVE with the
    entitlement fan-out and CHARGE ledger row."""
    return _ok(
        api_client.simulate_payment(subscription["id"], "SUCCEEDED", ADMIN),
        "activate subscription",
    )


def setup_season_with_offer(clock=CLOCK_DEFAULT, season_overrides=None,
                            offer_overrides=None) -> dict:
    """Grant + season + offer."""
    ctx = setup_grant_season(clock, season_overrides=season_overrides)
    ctx["offer"] = create_offer(ctx["season"]["id"], **(offer_overrides or {}))
    return ctx


def setup_account_with_pending_sub(email="user@x.com", billing_zip="10001",
                                   account_kind="RESIDENTIAL",
                                   season_overrides=None,
                                   offer_overrides=None,
                                   clock=CLOCK_DEFAULT) -> dict:
    """Grant + season + offer + account + PENDING_PAYMENT subscription."""
    ctx = setup_season_with_offer(clock, season_overrides, offer_overrides)
    ctx["account"] = register_account(email=email, billing_zip=billing_zip,
                                      account_kind=account_kind)
    ctx["subscription"] = purchase_subscription(ctx["account"], ctx["offer"])
    return ctx


def setup_account_with_active_sub(email="user@x.com", billing_zip="10001",
                                  account_kind="RESIDENTIAL",
                                  season_overrides=None,
                                  offer_overrides=None,
                                  clock=CLOCK_DEFAULT) -> dict:
    """Grant + season + offer + account + ACTIVE paid subscription."""
    ctx = setup_account_with_pending_sub(
        email, billing_zip, account_kind, season_overrides, offer_overrides, clock
    )
    ctx["subscription"] = activate_subscription(ctx["subscription"])
    return ctx


def setup_week4_game_account_sub(email="user@x.com", billing_zip="75001",
                                 season_overrides=None,
                                 offer_overrides=None,
                                 clock=CLOCK_DEFAULT,
                                 markets=("DAL",),
                                 games=("KC@DAL",),
                                 advance_to_regular=False) -> dict:
    """Grant + season + markets + week-4 slate + games + offer + account +
    ACTIVE paid subscription.

    ``games`` is a tuple of "AWAY@HOME" specs; the home market code is taken
    from the trailing "@HOME" when it matches a market code, else the first
    market. Kickoff alternates between the early and late week-4 instants.
    """
    ctx = setup_grant_season(clock, season_overrides=season_overrides)
    ctx["markets"] = {}
    for code in markets:
        spec = {
            "DAL": dict(code="DAL", name="Dallas", zip_prefixes=["750"],
                        home_team_codes=["DAL"]),
            "NYC": dict(code="NYC", name="New York", zip_prefixes=["100"],
                        home_team_codes=["NYC"]),
            "LA": dict(code="LA", name="Los Angeles", zip_prefixes=["900"],
                       home_team_codes=["LAC"]),
        }[code]
        ctx["markets"][code] = create_market(**spec)
    ctx["slate"] = create_slate(ctx["season"]["id"], week_index=4)
    ctx["games"] = []
    kickoffs = [TEST_DEFAULTS["WEEK4_GAME_KICKOFF_EARLY"],
                TEST_DEFAULTS["WEEK4_GAME_KICKOFF_LATE"]]
    for i, spec in enumerate(games):
        away, home = spec.split("@")
        ctx["games"].append(
            create_game(
                ctx["season"]["id"],
                week_index=4,
                away_team_code=away,
                home_team_code=home,
                kickoff_at=kickoffs[i % len(kickoffs)],
                home_market_code=home if home in ctx["markets"] else markets[0],
            )
        )
    if advance_to_regular:
        _ok(
            api_client.advance_season_phase(
                ctx["season"]["id"], ctx["season"]["version"], OPS
            ),
            "advance season to REGULAR",
        )
        ctx["season"] = _ok(
            api_client.get_season(ctx["season"]["id"], OPS), "re-read season"
        )
    ctx["offer"] = create_offer(ctx["season"]["id"], **(offer_overrides or {}))
    ctx["account"] = register_account(email=email, billing_zip=billing_zip)
    ctx["subscription"] = purchase_subscription(ctx["account"], ctx["offer"])
    ctx["subscription"] = activate_subscription(ctx["subscription"])
    return ctx
