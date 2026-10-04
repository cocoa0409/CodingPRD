"""Composite setup helpers.

Every test runs against a freshly restarted, empty server, so each helper
builds its preconditions from scratch using only PRD-declared endpoints. All
setup calls use get_success_data (lenient) so setup failures surface as clear
"Setup failed" errors.
"""

import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .constants import SPRING_NOW
from .factories import (
    create_chick_order_payload,
    create_hatchery_schedule_payload,
    create_livestock_lot_payload,
    create_loyalty_account_payload,
    create_pickup_order_payload,
    create_season_campaign_payload,
    create_service_event_payload,
    create_staging_bay_payload,
    create_store_payload,
    create_weighted_sale_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
)

RA = TEST_USERS["regional_admin_headers"]
MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]
ANON = TEST_USERS["anonymous_headers"]

_phone_seq = itertools.count(100)


def _next_phone() -> str:
    return f"555-{next(_phone_seq):04d}"


# ---- Tier 1: clock and store -------------------------------------------------


def set_clock(to_iso8601: str):
    get_success_data(_api.set_clock({"to_iso8601": to_iso8601}, RA))


def create_store(name: str = "Test Farm & Ranch", region_code: str = "TX-CENTRAL") -> dict:
    data = get_success_data(
        _api.create_store(create_store_payload(store_name=name, region_code=region_code), RA)
    )
    assert data is not None, "Setup failed: store creation"
    return data


def create_account(full_name: str = "Test Member", phone: str = None) -> dict:
    data = get_success_data(
        _api.create_loyalty_account(
            create_loyalty_account_payload(full_name=full_name, phone=phone or _next_phone()),
            ANON,
        )
    )
    assert data is not None, "Setup failed: loyalty account creation"
    return data


# ---- Tier 2: campaign lifecycle ----------------------------------------------


def create_campaign_ready(store: dict, season: str, aisle_count: int = 1) -> dict:
    """Create a campaign and walk it DRAFT -> TEARDOWN -> VERIFY_PENDING ->
    READY. The campaign is NOT activated."""
    camp = get_success_data(
        _api.create_season_campaign(
            create_season_campaign_payload(
                store["id"], season=season, aisle_count=aisle_count,
                planogram_map=f"{season.lower()}-plan",
            ),
            RA,
        )
    )
    assert camp is not None, "Setup failed: campaign creation"
    get_success_data(_api.begin_teardown(camp["id"], MGR))
    get_success_data(
        _api.complete_reset(camp["id"], {"aisles_reset_count": aisle_count}, MGR)
    )
    ready = get_success_data(_api.verify_campaign(camp["id"], {"audit_passed": True}, RA))
    assert ready is not None and ready["status"] == "READY", (
        f"Setup failed: campaign not READY, got {ready!r}"
    )
    return ready


def activate_campaign(campaign_id: str) -> dict:
    """Activate a READY campaign with a fresh OCC read of the store version."""
    camp = get_success_data(_api.get_season_campaign(campaign_id, RA))
    store = get_success_data(_api.get_store(camp["store_id"], RA))
    activated = get_success_data(
        _api.activate_campaign(
            campaign_id, {"expected_store_version": store["version"]}, RA
        )
    )
    assert activated is not None and activated["status"] == "ACTIVE", (
        f"Setup failed: campaign not ACTIVE, got {activated!r}"
    )
    return activated


def create_open_store(
    season: str = "WINTER_HEATING",
    aisle_count: int = 1,
    name: str = "Test Farm & Ranch",
    region_code: str = "TX-CENTRAL",
) -> dict:
    """Store with one fully activated campaign (posture == season)."""
    store = create_store(name=name, region_code=region_code)
    camp = create_campaign_ready(store, season, aisle_count=aisle_count)
    activate_campaign(camp["id"])
    return get_success_data(_api.get_store(store["id"], RA))


# ---- Tier 3: hatchery schedule + livestock lot -------------------------------


def create_published_schedule(store: dict, **overrides) -> dict:
    sched = get_success_data(
        _api.create_hatchery_schedule(
            create_hatchery_schedule_payload(store["id"], **overrides), MGR
        )
    )
    assert sched is not None, "Setup failed: schedule creation"
    pub = get_success_data(_api.publish_hatchery_schedule(sched["id"], MGR))
    assert pub is not None and pub["status"] == "PUBLISHED", (
        f"Setup failed: schedule not PUBLISHED, got {pub!r}"
    )
    return pub


def create_on_sale_lot(store: dict, schedule: dict, **overrides) -> dict:
    lot = get_success_data(
        _api.create_livestock_lot(
            create_livestock_lot_payload(store["id"], schedule["id"], **overrides), MGR
        )
    )
    assert lot is not None, "Setup failed: lot creation"
    opened = get_success_data(_api.open_lot_sale(lot["id"], MGR))
    assert opened is not None and opened["status"] == "ON_SALE", (
        f"Setup failed: lot not ON_SALE, got {opened!r}"
    )
    return opened


def setup_spring_store(clock: str = SPRING_NOW) -> dict:
    """Spring-posture store with a published schedule and an ON_SALE lot of 100.

    Returns dict with keys: store, campaign, schedule, lot (ON_SALE, current
    version), lot_version.
    """
    set_clock(clock)
    store = create_open_store(
        season="SPRING_PLANTING", aisle_count=2,
        name="Waxahachie Farm & Ranch", region_code="TX-NORTH",
    )
    schedule = create_published_schedule(store)
    lot = create_on_sale_lot(store, schedule)
    return {
        "store": store,
        "campaign_id": store["active_campaign_id"],
        "schedule": schedule,
        "lot": lot,
        "lot_version": lot["version"],
    }


def place_chick_order(
    store: dict, lot: dict, account: dict, quantity: int = 6,
    pickup_date: str = "2026-03-12T10:00:00Z", lot_version: int = None,
) -> dict:
    """Reserve birds as the owning customer (identity-threaded headers)."""
    if lot_version is None:
        lot = get_success_data(_api.get_livestock_lot(lot["id"], MGR))
        lot_version = lot["version"]
    resp = _api.create_chick_order(
        create_chick_order_payload(
            store["id"], lot["id"], account["id"], lot_version,
            quantity=quantity, pickup_date=pickup_date,
        ),
        make_customer_headers(account["id"]),
    )
    data = get_success_data(resp)
    assert data is not None and data.get("status") == "RESERVED", (
        f"Setup failed: chick order not RESERVED, got {resp.status_code} {resp.text}"
    )
    return data


def setup_reserved_order(clock: str = SPRING_NOW, quantity: int = 6) -> dict:
    """Spring store + lot ON_SALE + account + RESERVED order of `quantity`.

    Returns dict: store, campaign_id, schedule, lot (refreshed), lot_version,
    account, order.
    """
    ctx = setup_spring_store(clock=clock)
    account = create_account(full_name="Jesse Pruitt")
    order = place_chick_order(
        ctx["store"], ctx["lot"], account, quantity=quantity,
        lot_version=ctx["lot_version"],
    )
    lot = get_success_data(_api.get_livestock_lot(ctx["lot"]["id"], MGR))
    ctx.update({
        "account": account, "order": order,
        "lot": lot, "lot_version": lot["version"],
    })
    return ctx


def brooder_verify(order_id: str, headers=None) -> dict:
    data = get_success_data(
        _api.verify_brooder(
            order_id,
            {"heat_lamp_ok": True, "thermometer_ok": True, "bedding_ok": True},
            headers or ASSOC,
        )
    )
    assert data is not None and data["status"] == "BROODER_VERIFIED", (
        f"Setup failed: order not BROODER_VERIFIED, got {data!r}"
    )
    return data


def post_care_log(lot_id: str, entry_type: str = "FEEDING", **extra) -> dict:
    payload = {"entry_type": entry_type}
    payload.update(extra)
    data = get_success_data(_api.create_care_log(lot_id, payload, ASSOC))
    assert data is not None, "Setup failed: care log append"
    return data


def setup_fulfilled_order(clock: str = SPRING_NOW, quantity: int = 6) -> dict:
    """Reserved -> brooder verified -> fresh care log -> FULFILLED order.

    Returns the setup_reserved_order context with order in FULFILLED.
    """
    ctx = setup_reserved_order(clock=clock, quantity=quantity)
    brooder_verify(ctx["order"]["id"])
    post_care_log(ctx["lot"]["id"], "FEEDING")
    fulfilled = get_success_data(_api.fulfill_chick_order(ctx["order"]["id"], ASSOC))
    assert fulfilled is not None and fulfilled["status"] == "FULFILLED", (
        f"Setup failed: order not FULFILLED, got {fulfilled!r}"
    )
    ctx["order"] = fulfilled
    return ctx


# ---- Tier 4: weighted sales ---------------------------------------------------


def create_provisional_sale(store: dict, **overrides) -> dict:
    data = get_success_data(
        _api.create_weighted_sale(create_weighted_sale_payload(store["id"], **overrides), ASSOC)
    )
    assert data is not None and data.get("status") == "PROVISIONAL", (
        f"Setup failed: sale not PROVISIONAL, got {data!r}"
    )
    return data


def create_finalized_propane_sale(store: dict, gross_weight_lbs: float = 101.8) -> dict:
    """A FINALIZED 20-gallon propane exchange (gross 101.8, measured tare 17)."""
    sale = create_provisional_sale(
        store, sale_kind="PROPANE_EXCHANGE", container_class="CYLINDER_20",
        gross_weight_lbs=gross_weight_lbs,
    )
    fin = get_success_data(
        _api.finalize_weighted_sale(sale["id"], {"measured_tare_lbs": 17}, ASSOC)
    )
    assert fin is not None and fin["status"] == "FINALIZED", (
        f"Setup failed: propane sale not FINALIZED, got {fin!r}"
    )
    return fin


def accrue_points(account: dict, store: dict, base_amount_cents: int,
                  earn_context: str = "OTHER") -> dict:
    data = get_success_data(
        _api.create_ledger_entry(
            account["id"],
            {
                "entry_type": "ACCRUAL",
                "store_id": store["id"],
                "base_amount_cents": base_amount_cents,
                "earn_context": earn_context,
            },
            ASSOC,
        )
    )
    assert data is not None, "Setup failed: accrual entry"
    return data


def create_account_with_points(store: dict, points: int, earn_context: str = "OTHER") -> dict:
    """Account carrying exactly `points` points from one accrual (base =
    points * 100, which is exact under the floor(cents/100) rule for
    NEIGHBOR x1 multiplier)."""
    account = create_account()
    accrue_points(account, store, points * 100, earn_context=earn_context)
    fresh = get_success_data(_api.get_loyalty_account(account["id"], ASSOC))
    return fresh


# ---- Tier 5: pickup orders and events ----------------------------------------


def create_staging_bay(store: dict, bay_no: int, size_class: str) -> dict:
    data = get_success_data(
        _api.create_staging_bay(
            create_staging_bay_payload(store["id"], bay_no=bay_no, size_class=size_class),
            MGR,
        )
    )
    assert data is not None, "Setup failed: staging bay creation"
    return data


def create_pickup_order(store: dict, account: dict, **overrides) -> dict:
    resp = _api.create_pickup_order(
        create_pickup_order_payload(store["id"], account["id"], **overrides),
        make_customer_headers(account["id"]),
    )
    data = get_success_data(resp)
    assert data is not None and data.get("fulfillment_status") == "PLACED", (
        f"Setup failed: pickup order not PLACED, got {resp.status_code} {resp.text}"
    )
    return data


def setup_ready_pickup(clock: str = "2026-09-10T09:00:00Z", **order_overrides) -> dict:
    """Floor-open store + one bay + account + pickup order driven to
    READY_FOR_PICKUP. Returns dict: store, bay, account, order."""
    set_clock(clock)
    store = create_open_store(season="WINTER_HEATING")
    bay = create_staging_bay(store, bay_no=1, size_class="XL")
    account = create_account()
    order = create_pickup_order(store, account, **order_overrides)
    staged = get_success_data(_api.stage_pickup_order(order["id"], ASSOC))
    assert staged is not None and staged["fulfillment_status"] == "STAGED", (
        f"Setup failed: pickup order not STAGED, got {staged!r}"
    )
    ready = get_success_data(_api.mark_pickup_ready(order["id"], ASSOC))
    assert ready is not None and ready["fulfillment_status"] == "READY_FOR_PICKUP", (
        f"Setup failed: pickup order not READY_FOR_PICKUP, got {ready!r}"
    )
    return {"store": store, "bay": bay, "account": account, "order": ready}


def create_published_event(store: dict, **overrides) -> dict:
    ev = get_success_data(
        _api.create_service_event(create_service_event_payload(store["id"], **overrides), MGR)
    )
    assert ev is not None, "Setup failed: service event creation"
    pub = get_success_data(_api.publish_service_event(ev["id"], MGR))
    assert pub is not None and pub["status"] == "PUBLISHED", (
        f"Setup failed: event not PUBLISHED, got {pub!r}"
    )
    return pub


def create_booking(event: dict, account: dict, slot_start: str, **overrides) -> dict:
    payload = {
        "service_event_id": event["id"],
        "loyalty_account_id": account["id"],
        "slot_start": slot_start,
    }
    payload.update(overrides)
    resp = _api.create_event_booking(payload, make_customer_headers(account["id"]))
    data = get_success_data(resp)
    assert data is not None and data.get("status") == "BOOKED", (
        f"Setup failed: booking not BOOKED, got {resp.status_code} {resp.text}"
    )
    return data
