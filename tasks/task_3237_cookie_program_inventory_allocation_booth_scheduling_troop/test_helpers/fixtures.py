"""Composite setup helpers for the Cookie Program tests.

Every fixture builds its preconditions from scratch using only the public
endpoints, because the server is restarted before each test. All setup calls
use the lenient get_success_data() so failures surface as "Setup failed".
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_WINDOW
from .factories import (
    create_agreement_payload,
    create_baker_po_payload,
    create_booth_location_payload,
    create_booth_request_payload,
    create_booth_slot_payload,
    create_digital_order_payload,
    create_order_line_payload,
    create_order_payload,
    create_product_payload,
    create_season_payload,
    create_site_payload,
    create_transfer_payload,
    create_troop_payload,
)
from .test_users import make_council_admin_headers, make_troop_leader_headers


# ---------------------------------------------------------------------------
# Tier 1: Season progression
# ---------------------------------------------------------------------------

def create_season(admin=None, **overrides) -> dict:
    """Create a season in DRAFT. Returns the season dict (id, version, ...)."""
    admin = admin or make_council_admin_headers()
    resp = api_client.create_season(create_season_payload(**overrides), admin)
    return get_success_data(resp)


def add_product(season_id: str, admin=None, **overrides) -> dict:
    """Add one product to a season's catalog."""
    admin = admin or make_council_admin_headers()
    resp = api_client.create_product(season_id, create_product_payload(**overrides), admin)
    return get_success_data(resp)


def add_site(season: dict, admin=None, **overrides) -> dict:
    """Create a distribution site under the season's CURRENT version and return
    it. Refreshes the season's version in the returned tuple's first slot."""
    admin = admin or make_council_admin_headers()
    fresh = get_success_data(api_client.get_season(season["id"], admin))
    site = get_success_data(
        api_client.create_site(
            season["id"],
            create_site_payload(expected_season_version=fresh["version"], **overrides),
            admin,
        )
    )
    season["version"] = fresh["version"] + 1
    return site


def create_and_place_po(season: dict, product_id: str, quantity: int, site_id: str,
                        admin=None, **overrides) -> dict:
    """Create a DRAFT baker purchase order and place it (DRAFT -> ORDERED)."""
    admin = admin or make_council_admin_headers()
    po = get_success_data(
        api_client.create_baker_po(
            season["id"], create_baker_po_payload(product_id, quantity, site_id, **overrides), admin
        )
    )
    placed = get_success_data(api_client.place_baker_po(season["id"], po["id"], admin))
    season["version"] = season.get("version", 1) + 1
    return placed


def deliver_po(season_id: str, po_id: str, delivered_now: int, admin=None) -> dict:
    """Record a delivery against a placed purchase order."""
    admin = admin or make_council_admin_headers()
    return get_success_data(
        api_client.record_delivery(season_id, po_id, {"delivered_now": delivered_now}, admin)
    )


def open_season(season_id: str, admin=None) -> dict:
    """DRAFT -> OPEN."""
    admin = admin or make_council_admin_headers()
    return get_success_data(api_client.open_season(season_id, admin))


def set_clock(to_iso8601: str = DEFAULT_WINDOW["inside"], admin=None) -> dict:
    """Advance the logical clock."""
    admin = admin or make_council_admin_headers()
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, admin))


def get_season(season_id: str, admin=None) -> dict:
    admin = admin or make_council_admin_headers()
    return get_success_data(api_client.get_season(season_id, admin))


def get_account(account_id: str, admin=None) -> dict:
    admin = admin or make_council_admin_headers()
    return get_success_data(api_client.get_account(account_id, admin))


def get_site(site_id: str, admin=None) -> dict:
    admin = admin or make_council_admin_headers()
    return get_success_data(api_client.get_site(site_id, admin))


def get_order(order_id: str, admin=None) -> dict:
    admin = admin or make_council_admin_headers()
    return get_success_data(api_client.get_order(order_id, admin))


def get_transfer(transfer_id: str, admin=None) -> dict:
    admin = admin or make_council_admin_headers()
    return get_success_data(api_client.get_transfer(transfer_id, admin))


def get_digital_order(order_id: str, admin=None) -> dict:
    admin = admin or make_council_admin_headers()
    return get_success_data(api_client.get_digital_order(order_id, admin))


def get_booth_request(request_id: str, admin=None) -> dict:
    admin = admin or make_council_admin_headers()
    return get_success_data(api_client.get_booth_request(request_id, admin))


def get_agreement(agreement_id: str, admin=None) -> dict:
    admin = admin or make_council_admin_headers()
    return get_success_data(api_client.get_agreement(agreement_id, admin))


# ---------------------------------------------------------------------------
# Tier 2: Troop + account hierarchy
# ---------------------------------------------------------------------------

def create_troop(admin=None, **overrides) -> dict:
    """Register a troop (ACTIVE)."""
    admin = admin or make_council_admin_headers()
    return get_success_data(api_client.create_troop(create_troop_payload(**overrides), admin))


def create_account(season_id: str, troop_id: str, admin=None) -> dict:
    """Open the troop's account for the season (balance 0)."""
    admin = admin or make_council_admin_headers()
    return get_success_data(
        api_client.create_account(season_id, {"troop_id": troop_id}, admin)
    )


def create_troop_with_account(season_id: str, admin=None, **troop_overrides) -> tuple:
    """Register a troop and open its season account. Returns (troop, account, leader_headers)."""
    admin = admin or make_council_admin_headers()
    troop = create_troop(admin=admin, **troop_overrides)
    account = create_account(season_id, troop["id"], admin=admin)
    return troop, account, make_troop_leader_headers(troop["id"])


# ---------------------------------------------------------------------------
# Tier 3: Order lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_order_with_lines(season_id: str, troop: dict, lines: list, kind: str = "INITIAL",
                            leader=None) -> dict:
    """Create a DRAFT order and add each (product_id, package_qty) line."""
    leader = leader or make_troop_leader_headers(troop["id"])
    order = get_success_data(
        api_client.create_order(season_id, create_order_payload(troop["id"], kind), leader)
    )
    for product_id, qty in lines:
        get_success_data(
            api_client.add_order_line(
                season_id, order["id"], create_order_line_payload(product_id, qty), leader
            )
        )
    return order


def submit_order(season_id: str, order_id: str, troop: dict, leader=None) -> dict:
    leader = leader or make_troop_leader_headers(troop["id"])
    return get_success_data(api_client.submit_order(season_id, order_id, leader))


def create_and_submit_order(season_id: str, troop: dict, lines: list, kind: str = "INITIAL",
                            leader=None) -> dict:
    """Create order + lines, then submit (DRAFT -> SUBMITTED). Returns the SUBMITTED order."""
    leader = leader or make_troop_leader_headers(troop["id"])
    order = create_order_with_lines(season_id, troop, lines, kind, leader)
    return submit_order(season_id, order["id"], troop, leader)


def create_and_confirm_order(season_id: str, troop: dict, lines: list, kind: str = "INITIAL",
                             leader=None, admin=None) -> dict:
    """Create + submit + confirm. Returns the CONFIRMED order."""
    admin = admin or make_council_admin_headers()
    submitted = create_and_submit_order(season_id, troop, lines, kind, leader)
    return get_success_data(api_client.confirm_order(season_id, submitted["id"], admin))


# ---------------------------------------------------------------------------
# Tier 4: Threshold / state-targeting composites
# ---------------------------------------------------------------------------

def setup_open_season_with_supply(purchase_qty: int, admin=None,
                                  packages_per_case: int = 1,
                                  unit_price_cents: int = 600,
                                  troop_proceeds_cents: int = 100,
                                  deliver: bool = False,
                                  site_capacity: int = 10000) -> dict:
    """Season DRAFT -> product -> site -> placed PO -> OPEN.

    Returns a context dict: season, product, site, po, admin. With
    deliver=True the placed PO is also fully delivered to the site.
    The season is NOT yet SELLING (no orders confirmed) and the clock is NOT
    advanced into the ordering window unless the caller does it.
    """
    admin = admin or make_council_admin_headers()
    season = create_season(admin=admin)
    product = add_product(
        season["id"], admin=admin, packages_per_case=packages_per_case,
        unit_price_cents=unit_price_cents, troop_proceeds_cents=troop_proceeds_cents,
    )
    site = add_site(season, admin=admin, capacity_units=site_capacity)
    po = create_and_place_po(season, product["id"], purchase_qty, site["id"], admin=admin)
    opened = open_season(season["id"], admin=admin)
    season.update(opened)
    if deliver:
        # Deliveries are gated on site posture RECEIVING (PRD §3.1), which
        # requires the season to be OPEN/SELLING — deliver after opening.
        deliver_po(season["id"], po["id"], purchase_qty, admin=admin)
    return {
        "season": season,
        "product": product,
        "site": site,
        "po": po,
        "admin": admin,
    }


def setup_selling_season(purchase_qty: int = 100, confirm_qty: int = 80, admin=None,
                         packages_per_case: int = 1,
                         unit_price_cents: int = 600,
                         troop_proceeds_cents: int = 100,
                         deliver: bool = False,
                         site_capacity: int = 10000) -> dict:
    """Season OPEN with a confirmed order large enough to trip the 80% gate.

    Default: purchased 100, confirmed 80 -> attainment exactly 80.00 -> SELLING.
    Returns context: season (refreshed), product, site, po, troop, account, order, admin, leader.
    """
    admin = admin or make_council_admin_headers()
    ctx = setup_open_season_with_supply(
        purchase_qty, admin=admin, packages_per_case=packages_per_case,
        unit_price_cents=unit_price_cents, troop_proceeds_cents=troop_proceeds_cents,
        deliver=deliver, site_capacity=site_capacity,
    )
    season = ctx["season"]
    troop, account, leader = create_troop_with_account(season["id"], admin=admin)
    set_clock(DEFAULT_WINDOW["inside"], admin=admin)
    order = create_and_confirm_order(
        season["id"], troop, [(ctx["product"]["id"], confirm_qty)], leader=leader, admin=admin
    )
    ctx["season"] = get_season(season["id"], admin=admin)
    ctx.update({"troop": troop, "account": account, "order": order, "leader": leader})
    return ctx


def setup_reconciliation_season(purchase_qty: int = 100, confirm_qty: int = 80, admin=None,
                                **kwargs) -> dict:
    """Season walked all the way to RECONCILIATION (no transfers/booth noise)."""
    admin = admin or make_council_admin_headers()
    ctx = setup_selling_season(purchase_qty, confirm_qty, admin=admin, **kwargs)
    season = ctx["season"]
    recon = get_success_data(api_client.begin_reconciliation(season["id"], admin))
    ctx["season"] = recon
    return ctx


def setup_closed_season(purchase_qty: int = 100, confirm_qty: int = 80, admin=None, **kwargs) -> dict:
    """Season walked all the way to CLOSED. Context gains close_out summary."""
    admin = admin or make_council_admin_headers()
    ctx = setup_reconciliation_season(purchase_qty, confirm_qty, admin=admin, **kwargs)
    close_out = get_success_data(api_client.close_out_season(ctx["season"]["id"], admin))
    ctx["close_out"] = close_out
    ctx["season"] = get_season(ctx["season"]["id"], admin=admin)
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: Transfers, booths, digital orders, agreements, recalls
# ---------------------------------------------------------------------------

def create_transfer(season_id: str, product_id: str, qty: int, creator_headers, **overrides) -> dict:
    """Create a REQUESTED transfer. creator_headers chooses the requester."""
    return get_success_data(
        api_client.create_transfer(
            create_transfer_payload(season_id, product_id, qty, **overrides), creator_headers
        )
    )


def setup_booth_arena(season_id: str, admin=None, permission: bool = True,
                      blackout_dates=None, capacity_troops: int = 1,
                      start_at: str = "2027-02-10T14:00:00Z",
                      end_at: str = "2027-02-10T16:00:00Z") -> dict:
    """Create a booth location and one slot at it. Returns {location, slot}."""
    admin = admin or make_council_admin_headers()
    loc_payload = create_booth_location_payload(host_permission_granted=permission)
    if blackout_dates is not None:
        loc_payload["blackout_dates"] = blackout_dates
    location = get_success_data(api_client.create_booth_location(season_id, loc_payload, admin))
    slot = get_success_data(
        api_client.create_booth_slot(
            create_booth_slot_payload(
                location["id"], start_at=start_at, end_at=end_at, capacity_troops=capacity_troops
            ),
            admin,
        )
    )
    return {"location": location, "slot": slot}


def create_digital_order(season_id: str, troop: dict, items: list, leader=None,
                         fulfillment_type: str = "SHIPPED", **overrides) -> dict:
    leader = leader or make_troop_leader_headers(troop["id"])
    return get_success_data(
        api_client.create_digital_order(
            season_id,
            create_digital_order_payload(troop["id"], items, fulfillment_type, **overrides),
            leader,
        )
    )


def create_agreement(season_id: str, troop: dict, leader=None, **overrides) -> dict:
    leader = leader or make_troop_leader_headers(troop["id"])
    return get_success_data(
        api_client.create_agreement(
            troop["id"], create_agreement_payload(season_id, **overrides), leader
        )
    )


def create_active_recall(season_id: str, product_id: str, admin=None, **overrides) -> dict:
    """Create a recall notice and activate it (DRAFT -> ACTIVE)."""
    admin = admin or make_council_admin_headers()
    recall = get_success_data(
        api_client.create_recall(season_id, _recall_payload(product_id, **overrides), admin)
    )
    return get_success_data(api_client.activate_recall(season_id, recall["id"], admin))


def _recall_payload(product_id: str, **overrides) -> dict:
    from .factories import create_recall_payload
    return create_recall_payload(product_id, **overrides)
