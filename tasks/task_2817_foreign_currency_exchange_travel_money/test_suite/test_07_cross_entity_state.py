"""Transitions gated by a field on another row entirely.

PRD 2.8 rank 7: "the branch's posture must not be FROZEN on POST
/exchange-transactions/{id}/authorize", a field the transaction never writes.
PRD 3.3: activation requires "the logical clock ... at or after season_start_date
and strictly before season_end_date", two immutable dates on the corridor.
"""

from test_helpers import (
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)


def _frozen_branch_world(api, vault_limit_usd_cents):
    """A branch trading EUR with a 30 x 10000 position - whose posture depends
    entirely on the vault ceiling the caller chooses."""
    return fx.trading_world(
        api,
        vault_limit_usd_cents=vault_limit_usd_cents,
        position_mix=[f.denom(10000, 30)],
        customer_overrides={"full_name": "Jonas Weber", "nationality_code": "DE"},
    )


def test_authorisation_is_refused_while_the_branch_posture_is_frozen(api, teller_headers):
    """300000 EUR minor units value at 326087 cents against a 320000-cent ceiling,
    which is 10190 bps and a FROZEN posture, so a perfectly well-formed one-note
    quote cannot advance: ERR_BRANCH_POSTURE_FROZEN, the deal stays QUOTED and no
    notes are reserved.

    Design: Difficulty/cross_entity_state_dependency/authorize_blocked_by_frozen_branch_posture
    """
    world = _frozen_branch_world(api, 320_000)
    branch = fx.read_branch(api, world["branch"]["id"])
    a.assert_vault_state(branch, 326087, 10190, "FROZEN")

    quote = fx.quote_deal(api, world, denominations=[f.denom(10000, 1)], headers=teller_headers)

    validate_error(
        api.authorize_transaction(quote["id"], teller_headers),
        ApiErrorId.ERR_BRANCH_POSTURE_FROZEN,
    )

    unchanged = fx.read_transaction(api, quote["id"])
    assert unchanged["settlement_status"] == "QUOTED"
    assert unchanged["authorized_at"] is None
    assert fx.read_position(api, world["position"]["id"])["total_minor_units"] == 300000


def test_the_identical_quote_authorises_at_a_branch_with_vault_headroom(api, teller_headers):
    """The same 30 x 10000 stock behind a 20,000,000-cent ceiling is only 163 bps and
    leaves the branch OPEN, and the identical one-note quote authorises - so nothing
    about the transaction row was ever at fault.

    Design: Difficulty/cross_entity_state_dependency/authorize_blocked_by_frozen_branch_posture
    """
    world = _frozen_branch_world(api, 20_000_000)
    branch = fx.read_branch(api, world["branch"]["id"])
    a.assert_vault_state(branch, 326087, 163, "OPEN")

    quote = fx.quote_deal(api, world, denominations=[f.denom(10000, 1)], headers=teller_headers)
    authorized = validate_success(api.authorize_transaction(quote["id"], teller_headers))

    assert authorized["settlement_status"] == "AUTHORIZED"
    a.assert_timestamp_equals(authorized["authorized_at"], "2026-08-01T00:00:00Z")


def _approved_winter_plan(api):
    """An APPROVED plan against a WINTER corridor that does not open until December."""
    branch = fx.register_branch(api, vault_limit_usd_cents=5_000_000)
    fx.register_currency(api)
    fx.record_wholesale_rate(api)
    corridor = fx.register_corridor(
        api,
        code="LHR-DXB-WINTER",
        destination_country_code="AE",
        destination_currency_code="EUR",
        season="WINTER",
        season_start_date="2026-12-01T00:00:00Z",
        season_end_date="2027-03-01T00:00:00Z",
        demand_index_bps=13500,
    )
    plan = fx.draft_plan(
        api,
        branch["id"],
        corridor["id"],
        season_days=92,
        target_lines=[f.target_line("EUR", 2000)],
    )
    fx.submit_plan(api, plan["id"])
    approved = fx.review_plan(api, plan["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    return {"branch": branch, "corridor": corridor, "plan": approved}


def test_activation_is_refused_while_the_clock_sits_outside_the_corridor_season(
    api, manager_headers
):
    """With the clock four months before the corridor opens, activating a fully
    APPROVED plan is refused with ERR_PLAN_OUTSIDE_SEASON; the plan stays APPROVED
    and keeps its 250000-unit EUR target.

    Design: Difficulty/cross_entity_state_dependency/plan_activation_blocked_by_corridor_season_window
    """
    world = _approved_winter_plan(api)

    validate_error(
        api.activate_inventory_plan(world["plan"]["id"], manager_headers),
        ApiErrorId.ERR_PLAN_OUTSIDE_SEASON,
    )

    unchanged = fx.read_plan(api, world["plan"]["id"])
    assert unchanged["status"] == "APPROVED"
    assert unchanged["computed_targets"] == [
        {"currency_code": "EUR", "target_minor_units": 250000}
    ]


def test_the_same_activation_succeeds_once_the_clock_enters_the_season(api, manager_headers):
    """Moving the logical clock to 2026-12-15 - changing neither the plan nor the
    corridor - turns the identical activate call into a 200 and the plan ACTIVE, while
    the corridor's season dates read back exactly as registered.

    Design: Difficulty/cross_entity_state_dependency/plan_activation_blocked_by_corridor_season_window
    """
    world = _approved_winter_plan(api)
    validate_error(
        api.activate_inventory_plan(world["plan"]["id"], manager_headers),
        ApiErrorId.ERR_PLAN_OUTSIDE_SEASON,
    )

    fx.set_clock(api, "2026-12-15T00:00:00Z")
    activated = validate_success(
        api.activate_inventory_plan(world["plan"]["id"], manager_headers)
    )

    assert activated["status"] == "ACTIVE"
    assert activated["computed_targets"] == [
        {"currency_code": "EUR", "target_minor_units": 250000}
    ]

    corridor = validate_success(
        api.get_travel_corridor(world["corridor"]["id"], manager_headers)
    )
    a.assert_travel_corridor(corridor)
    a.assert_timestamp_equals(corridor["season_start_date"], "2026-12-01T00:00:00Z")
    a.assert_timestamp_equals(corridor["season_end_date"], "2027-03-01T00:00:00Z")
