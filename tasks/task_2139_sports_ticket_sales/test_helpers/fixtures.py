"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only the endpoints the PRD declares.

Setup calls use get_success_data() so a broken precondition surfaces as a
setup failure rather than as a confusing assertion deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    create_account_payload,
    create_game_payload,
    create_hospitality_package_payload,
    create_plan_order_payload,
    create_season_payload,
    create_season_plan_payload,
    create_seat_hold_payload,
    create_seats_payload,
    create_service_rep_payload,
    create_ticket_transfer_payload,
)
from .test_users import (
    TEST_USERS,
    make_account_holder_headers,
    make_sales_rep_headers,
)

OPS_HEADERS = TEST_USERS["ops_admin_headers"]
RM_HEADERS = TEST_USERS["revenue_manager_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601, headers=None):
    """Move the server's logical clock. Mutates no stored state (PRD 2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or OPS_HEADERS))


def reset_clock():
    return set_clock(DEFAULT_CLOCK_UTC)


# ---------------------------------------------------------------------------
# Tier 1 - single-entity creation
# ---------------------------------------------------------------------------
def create_season(**overrides):
    return get_success_data(
        api_client.create_season(create_season_payload(**overrides), OPS_HEADERS)
    )


def create_game(season_id, **overrides):
    return get_success_data(
        api_client.create_game(create_game_payload(season_id, **overrides), OPS_HEADERS)
    )


def mint_seats(season_id, **overrides):
    """Bulk-mint one contiguous seat range; returns the minted Seat rows."""
    return get_success_data(
        api_client.create_seats(create_seats_payload(season_id, **overrides), OPS_HEADERS)
    )


def create_plan(season_id, game_ids, **overrides):
    return get_success_data(
        api_client.create_season_plan(
            create_season_plan_payload(season_id, game_ids, **overrides), RM_HEADERS
        )
    )


def publish_plan(plan_id):
    return get_success_data(api_client.publish_season_plan(plan_id, RM_HEADERS))


def create_published_plan(season_id, game_ids, **overrides):
    plan = create_plan(season_id, game_ids, **overrides)
    return publish_plan(plan["id"])


def open_renewal(season_id):
    return get_success_data(api_client.open_renewal(season_id, OPS_HEADERS))


def run_ops(season_id):
    return get_success_data(api_client.run_ops(season_id, OPS_HEADERS))


def create_rep(**overrides):
    return get_success_data(
        api_client.create_service_rep(create_service_rep_payload(**overrides), OPS_HEADERS)
    )


def create_account(**overrides):
    return get_success_data(
        api_client.create_account(create_account_payload(**overrides), OPS_HEADERS)
    )


def assign_rep(account_id):
    """Server-side rep selection; returns the updated account."""
    return get_success_data(api_client.assign_rep(account_id, OPS_HEADERS))


def create_account_with_rep(**overrides):
    """Create an account and let the server pick its rep.

    Returns (account, rep_headers) where rep_headers carry the chosen
    assigned_rep_id as X-User-ID, which every ownership-gated write requires.
    """
    account = create_account(**overrides)
    account = assign_rep(account["id"])
    return account, make_sales_rep_headers(account["assigned_rep_id"])


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def read_season(season_id):
    return get_success_data(api_client.get_season(season_id, OPS_HEADERS))


def read_game(game_id):
    return get_success_data(api_client.get_game(game_id, OPS_HEADERS))


def read_seat(seat_id):
    return get_success_data(api_client.get_seat(seat_id, OPS_HEADERS))


def read_plan(plan_id):
    return get_success_data(api_client.get_season_plan(plan_id, OPS_HEADERS))


def read_rep(rep_id):
    return get_success_data(api_client.get_service_rep(rep_id, OPS_HEADERS))


def read_account(account_id):
    return get_success_data(api_client.get_account(account_id, OPS_HEADERS))


def read_order(order_id):
    return get_success_data(api_client.get_plan_order(order_id, OPS_HEADERS))


def read_hold(hold_id):
    return get_success_data(api_client.get_seat_hold(hold_id, OPS_HEADERS))


def read_package(package_id):
    return get_success_data(api_client.get_hospitality_package(package_id, OPS_HEADERS))


def read_transfer(transfer_id):
    return get_success_data(api_client.get_ticket_transfer(transfer_id, OPS_HEADERS))


def seat_version(seat_id):
    """The seat version a hold creation must echo back in expected_seat_version."""
    return read_seat(seat_id)["version"]


def count_rows(response):
    """total_count of a list response."""
    _, meta = validate_paginated(response)
    return meta["total_count"]


# ---------------------------------------------------------------------------
# Tier 2 - holds, orders, packages, transfers
# ---------------------------------------------------------------------------
def place_hold(seat_id, account_id, headers, **overrides):
    """Place a hold, reading the seat's current version for the OCC token."""
    payload = create_seat_hold_payload(
        seat_id, account_id, seat_version(seat_id), **overrides
    )
    return get_success_data(api_client.create_seat_hold(payload, headers))


def release_hold(hold_id, headers, release_reason=None):
    payload = {} if release_reason is None else {"release_reason": release_reason}
    return get_success_data(api_client.release_seat_hold(hold_id, payload, headers))


def create_order(account_id, plan_id, seat_ids, headers, **overrides):
    payload = create_plan_order_payload(account_id, plan_id, seat_ids, **overrides)
    return get_success_data(api_client.create_plan_order(payload, headers))


def submit_order(order_id, headers):
    return get_success_data(api_client.submit_plan_order(order_id, headers))


def review_order(order_id, decision, headers, decision_note=None):
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return get_success_data(api_client.review_plan_order(order_id, payload, headers))


def confirm_order(order_id, headers, installment_count=1):
    return get_success_data(
        api_client.confirm_plan_order(
            order_id, {"installment_count": installment_count}, headers
        )
    )


def pay_order(order_id, headers, amount_cents):
    return get_success_data(
        api_client.pay_plan_order(order_id, {"amount_cents": amount_cents}, headers)
    )


def cancel_order(order_id, headers, cancel_reason=None):
    payload = {} if cancel_reason is None else {"cancel_reason": cancel_reason}
    return get_success_data(api_client.cancel_plan_order(order_id, payload, headers))


def relocate_order(order_id, new_seat_ids, expected_order_version, headers):
    payload = {
        "new_seat_ids": list(new_seat_ids),
        "expected_order_version": expected_order_version,
    }
    return get_success_data(api_client.relocate_plan_order(order_id, payload, headers))


def create_approved_order(account_id, plan_id, seat_ids, rep_headers, **overrides):
    """Create a DRAFT order and submit it. A zero-discount order lands APPROVED."""
    order = create_order(account_id, plan_id, seat_ids, rep_headers, **overrides)
    return submit_order(order["id"], rep_headers)


def create_confirmed_order(
    account_id, plan_id, seat_ids, rep_headers, installment_count=1, **overrides
):
    """Create, submit and confirm one zero-discount order."""
    order = create_approved_order(
        account_id, plan_id, seat_ids, rep_headers, **overrides
    )
    return confirm_order(order["id"], rep_headers, installment_count)


def book_package(game_id, account_id, headers, **overrides):
    payload = create_hospitality_package_payload(game_id, account_id, **overrides)
    return get_success_data(api_client.create_hospitality_package(payload, headers))


def request_transfer(order_id, game_id, seat_id, account_headers, **overrides):
    payload = create_ticket_transfer_payload(order_id, game_id, seat_id, **overrides)
    return get_success_data(api_client.create_ticket_transfer(payload, account_headers))


def decide_transfer(transfer_id, decision, headers=None, decision_reason=None):
    payload = {"decision": decision}
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    return get_success_data(
        api_client.decide_ticket_transfer(transfer_id, payload, headers or RM_HEADERS)
    )


def scan_seat(game_id, seat_id):
    return get_success_data(
        api_client.create_scan(game_id, {"seat_id": seat_id}, OPS_HEADERS)
    )


def log_touchpoint(account_id, headers, touchpoint_type="CALL", outcome="COMMITTED", note=None):
    payload = {"touchpoint_type": touchpoint_type, "outcome": outcome}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.log_touchpoint(account_id, payload, headers))


# ---------------------------------------------------------------------------
# Tier 3 - the standard selling world
# ---------------------------------------------------------------------------
def setup_selling_world(
    games=None,
    seat_ranges=None,
    season=None,
    plan=None,
    account=None,
    rep=None,
    open_window=True,
    with_account=True,
):
    """Build a season all the way to a state where orders can be written.

    season -> games -> seat inventory -> published plan -> renewal window open
    -> service rep -> account with its server-selected rep.

    `games` and `seat_ranges` are lists of payload overrides; `season`, `plan`,
    `account` and `rep` are single override dicts. Returns a dict carrying every
    created row plus ready-to-use headers for the account's rep and for the
    account acting for itself.
    """
    game_specs = games if games is not None else [{}]
    seat_specs = seat_ranges if seat_ranges is not None else [{}]

    season_overrides = dict(season or {})
    season_overrides.setdefault("total_home_games", len(game_specs))
    season_row = create_season(**season_overrides)
    season_id = season_row["id"]

    game_rows = [create_game(season_id, **spec) for spec in game_specs]
    seat_groups = [mint_seats(season_id, **spec) for spec in seat_specs]
    flat_seats = [seat for group in seat_groups for seat in group]

    plan_overrides = dict(plan or {})
    plan_game_ids = plan_overrides.pop("game_ids", [g["id"] for g in game_rows])
    plan_row = create_published_plan(season_id, plan_game_ids, **plan_overrides)

    if open_window:
        season_row = open_renewal(season_id)

    world = {
        "season": season_row,
        "season_id": season_id,
        "games": game_rows,
        "game": game_rows[0] if game_rows else None,
        "game_ids": [g["id"] for g in game_rows],
        "seat_groups": seat_groups,
        "seats": flat_seats,
        "seat_ids": [s["id"] for s in flat_seats],
        "plan": plan_row,
        "plan_id": plan_row["id"],
    }

    if with_account:
        rep_row = create_rep(**(rep or {}))
        account_row, rep_headers = create_account_with_rep(**(account or {}))
        world.update(
            {
                "rep": rep_row,
                "rep_id": account_row["assigned_rep_id"],
                "account": account_row,
                "account_id": account_row["id"],
                "rep_headers": rep_headers,
                "account_headers": make_account_holder_headers(account_row["id"]),
            }
        )
    return world


def setup_world_with_confirmed_order(
    seat_count=1, installment_count=1, discount_pct=None, **world_kwargs
):
    """Standard selling world plus one CONFIRMED order over the first seats."""
    world = setup_selling_world(**world_kwargs)
    overrides = {} if discount_pct is None else {"discount_pct": discount_pct}
    order = create_confirmed_order(
        world["account_id"],
        world["plan_id"],
        world["seat_ids"][:seat_count],
        world["rep_headers"],
        installment_count=installment_count,
        **overrides,
    )
    world["order"] = order
    world["order_id"] = order["id"]
    return world


def setup_world_with_delinquent_order(
    installment_count=3, delinquency_instant="2026-08-12T00:00:00Z", **world_kwargs
):
    """A CONFIRMED order driven past its grace window by one ops checkpoint.

    The first instalment falls due at the confirming instant, so moving the
    clock past that date plus the ten-day grace and running the checkpoint
    flips payment_status to DELINQUENT and the account to PAST_DUE.
    """
    world = setup_world_with_confirmed_order(
        installment_count=installment_count, **world_kwargs
    )
    set_clock(delinquency_instant)
    world["ops_summary"] = run_ops(world["season_id"])
    world["order"] = read_order(world["order_id"])
    world["account"] = read_account(world["account_id"])
    return world


def setup_world_with_requested_resale(
    resale_price_cents=10000, seat_index=0, **world_kwargs
):
    """A CONFIRMED order plus one REQUESTED RESALE transfer on one of its seats."""
    world = setup_world_with_confirmed_order(**world_kwargs)
    transfer = request_transfer(
        world["order_id"],
        world["game"]["id"],
        world["seat_ids"][seat_index],
        world["account_headers"],
        transfer_type="RESALE",
        resale_price_cents=resale_price_cents,
    )
    world["transfer"] = transfer
    world["transfer_id"] = transfer["id"]
    return world


def setup_written_off_account_world(**world_kwargs):
    """Drive an account all the way to WRITTEN_OFF through two checkpoints.

    A CONFIRMED, unpaid single-instalment order goes DELINQUENT at the grace
    boundary, stamping past_due_since_utc; ninety days later one checkpoint
    walks PAST_DUE -> LAPSED -> WRITTEN_OFF and runs the write-off cascade.
    """
    defaults = {
        "season": {
            "renewal_deadline_utc": "2026-12-01T00:00:00Z",
            "total_home_games": 1,
        },
        "games": [
            {
                "opponent_tier": "STANDARD",
                "day_bucket": "WEEKDAY",
                "demand_index": 50,
                "game_date_utc": "2027-03-01T23:00:00Z",
            }
        ],
        "seat_ranges": [
            {
                "section_code": "310",
                "row_label": "C",
                "price_zone": "ZONE_D",
                "seat_number_from": 1,
                "seat_number_to": 8,
            }
        ],
        "plan": {"min_seats": 1, "max_seats": 8},
    }
    defaults.update(world_kwargs)
    world = setup_selling_world(**defaults)
    confirmed = create_confirmed_order(
        world["account_id"],
        world["plan_id"],
        [world["seat_ids"][0]],
        world["rep_headers"],
        installment_count=1,
    )
    draft = create_order(
        world["account_id"],
        world["plan_id"],
        [world["seat_ids"][1]],
        world["rep_headers"],
    )
    set_clock("2026-08-12T00:00:00Z")
    world["first_ops_summary"] = run_ops(world["season_id"])
    world["account_past_due"] = read_account(world["account_id"])
    set_clock("2026-11-11T00:00:00Z")
    world["ops_summary"] = run_ops(world["season_id"])
    world["confirmed_order"] = read_order(confirmed["id"])
    world["draft_order"] = read_order(draft["id"])
    world["account"] = read_account(world["account_id"])
    return world


# ---------------------------------------------------------------------------
# Tier 4 - worlds tuned to specific price points
# ---------------------------------------------------------------------------
def setup_four_seat_zone_c_world(**overrides):
    """Four ZONE_C seats against one PREMIUM / WEEKEND / demand 85 game.

    Every seat-game line prices at 9,344 cents, so a four-seat order quotes
    38,430 cents once the four-to-nine volume tier applies.
    """
    kwargs = {
        "seat_ranges": [
            {
                "section_code": "104",
                "row_label": "A",
                "price_zone": "ZONE_C",
                "seat_number_from": 1,
                "seat_number_to": 4,
            }
        ],
        "plan": {"min_seats": 1, "max_seats": 8},
    }
    kwargs.update(overrides)
    return setup_selling_world(**kwargs)


def setup_zone_d_world(**overrides):
    """Two ZONE_D seats against one PREMIUM / WEEKEND / demand 85 game.

    Each seat-game line prices at 5,606 cents, so a single-seat order totals
    5,942 cents.
    """
    kwargs = {
        "seat_ranges": [
            {
                "section_code": "310",
                "row_label": "C",
                "price_zone": "ZONE_D",
                "seat_number_from": 1,
                "seat_number_to": 2,
            }
        ]
    }
    kwargs.update(overrides)
    return setup_selling_world(**kwargs)


def setup_hospitality_world(headcount_cap=200, **overrides):
    """A selling world whose game carries an explicit hospitality headcount cap."""
    kwargs = {
        "games": [{"hospitality_headcount_cap": headcount_cap}],
        "account": {"account_type": "CORPORATE"},
    }
    kwargs.update(overrides)
    return setup_selling_world(**kwargs)


def setup_dual_variant_world():
    """One ZONE_B seat over a MARQUEE opener and a STANDARD closer.

    The plan sells two games ten days apart, so moving the clock between them
    lets the final pricing variant drop the game already behind the clock while
    the quoted figure frozen at creation still prices both.
    """
    return setup_selling_world(
        season={"total_home_games": 2},
        games=[
            {
                "opponent_code": "RIV",
                "opponent_tier": "MARQUEE",
                "game_date_utc": "2026-10-10T23:00:00Z",
                "day_bucket": "WEEKEND",
                "demand_index": 85,
            },
            {
                "opponent_code": "MID",
                "opponent_tier": "STANDARD",
                "game_date_utc": "2026-10-20T23:00:00Z",
                "day_bucket": "WEEKDAY",
                "demand_index": 50,
            },
        ],
        seat_ranges=[
            {
                "section_code": "104",
                "row_label": "A",
                "price_zone": "ZONE_B",
                "seat_number_from": 1,
                "seat_number_to": 1,
            }
        ],
        account={"tenure_years": 4},
    )


def setup_marquee_transfer_world(tenure_years=1):
    """A CONFIRMED single-seat order on a MARQUEE game for a short-tenure account."""
    return setup_world_with_confirmed_order(
        games=[
            {
                "opponent_tier": "MARQUEE",
                "day_bucket": "WEEKEND",
                "demand_index": 85,
            }
        ],
        seat_ranges=[
            {
                "section_code": "310",
                "row_label": "C",
                "price_zone": "ZONE_D",
                "seat_number_from": 1,
                "seat_number_to": 1,
            }
        ],
        account={"tenure_years": tenure_years},
    )
