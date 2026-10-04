"""Composite setup helpers for the Oversize Freight Network API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server before every test, so each test
starts against an empty database). Setup calls use the lenient
get_success_data() validator so failures surface as clear "Setup step failed"
errors rather than confusing assertion failures.

Canonical reference scenario (base network chain):
  - clock at 2026-09-05T00:00:00Z
  - supplier SUP-A (drop_ship_enabled=False)
  - hub HUB-A serving ZONE_NE, white-glove capable, daily_capacity 5
  - LTL lane ZONE_NE: base 40000c, per-lb 50c, transit 3 days
  - item SKU-LG-1: 40x40x20 in, 30 lb, declared 80000c, white-glove eligible
    (cube_score 52.52 -> LTL_250; girth 140 -> parcel_ok True)
  - customer C1 in ZONE_NE
  - linehaul L1 into HUB-A arriving 2026-09-10, capacity 10
  - THRESHOLD order for C1 on the item -> OWNED_FINAL_MILE via HUB-A,
    shipment TENDERED bound to L1, promised_date 2026-09-11.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_SETUP
from .factories import (
    create_supplier_payload,
    create_item_payload,
    create_hub_payload,
    create_freight_lane_payload,
    create_customer_payload,
    create_linehaul_payload,
    create_appointment_payload,
    create_damage_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_supplier_rep_headers,
)

ADMIN = TEST_USERS["network_admin_headers"]
HUB_OP = TEST_USERS["hub_operator_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
CARRIER = TEST_USERS["carrier_rep_headers"]

SETUP_CLOCK = CLOCK_SETUP
APPT_WINDOW_START = "2026-09-12T09:00:00Z"
APPT_WINDOW_END = "2026-09-12T13:00:00Z"


# ── Tier 0: primitive creators ────────────────────────────────────────────

def set_clock(current_utc: str = SETUP_CLOCK):
    """Advance the logical clock (NetworkAdmin test-driving capability)."""
    get_success_data(
        api_client.set_clock({"current_utc": current_utc}, ADMIN)
    )


def create_supplier(supplier_code: str = "SUP-A", **overrides) -> dict:
    payload = create_supplier_payload(supplier_code=supplier_code, **overrides)
    return get_success_data(api_client.create_supplier(payload, ADMIN), 201)


def create_hub(hub_code: str = "HUB-A", **overrides) -> dict:
    payload = create_hub_payload(hub_code=hub_code, **overrides)
    return get_success_data(api_client.create_hub(payload, ADMIN), 201)


def create_freight_lane(**overrides) -> dict:
    payload = create_freight_lane_payload(**overrides)
    return get_success_data(api_client.create_freight_lane(payload, ADMIN), 201)


def create_item(supplier_id: str, sku: str = "SKU-LG-1", **overrides) -> dict:
    payload = create_item_payload(supplier_id=supplier_id, sku=sku, **overrides)
    return get_success_data(api_client.create_item(payload, ADMIN), 201)


def create_customer(email: str = "c1@example.com", **overrides) -> dict:
    payload = create_customer_payload(email=email, **overrides)
    return get_success_data(api_client.create_customer(payload, ADMIN), 201)


def create_linehaul(hub_id: str, **overrides) -> dict:
    payload = create_linehaul_payload(hub_id=hub_id, **overrides)
    return get_success_data(api_client.create_linehaul(payload, ADMIN), 201)


def place_order(customer: dict, item_id: str, service_level: str = "THRESHOLD") -> dict:
    """Place an order as the owning customer (identity-backed role)."""
    headers = make_customer_headers(customer["id"])
    payload = {
        "customer_id": customer["id"],
        "item_id": item_id,
        "service_level": service_level,
    }
    return get_success_data(api_client.create_order(payload, headers), 201)


def get_shipment_for_order(order_id: str) -> dict:
    data, _meta = _paginated(api_client.list_shipments(ADMIN, params={"order_id": order_id}))
    assert len(data) == 1, f"expected exactly one shipment for order {order_id}"
    return data[0]


def _paginated(response):
    """Fetch a list endpoint and return (rows, meta); setup-lenient."""
    if not (200 <= response.status_code < 300):
        raise AssertionError(f"Setup step failed with HTTP {response.status_code}")
    body = response.json()
    return body["data"], body["meta"]


def book_appointment(shipment: dict, as_headers=None, **overrides) -> dict:
    """Book an appointment against a shipment with its CURRENT version
    re-read first (OCC). Returns the created appointment."""
    fresh = get_success_data(api_client.get_shipment(shipment["id"], ADMIN))
    payload = create_appointment_payload(
        shipment_id=shipment["id"],
        expected_shipment_version=fresh["version"],
        **overrides,
    )
    return get_success_data(
        api_client.create_appointment(payload, as_headers or HUB_OP), 201
    )


# ── Tier 1: reference-data chains ─────────────────────────────────────────

def setup_reference_data(zone: str = "ZONE_NE") -> dict:
    """Clock + supplier SUP-A (drop-ship off) + hub HUB-A + LTL lane + item-lg
    + customer C1 + linehaul L1. Returns a dict of the created records."""
    set_clock(SETUP_CLOCK)
    supplier = create_supplier()
    hub = create_hub(serves_zones=[zone])
    lane = create_freight_lane(dest_zone=zone)
    item = create_item(supplier["id"])
    customer = create_customer(destination_zone=zone)
    linehaul = create_linehaul(hub["id"])
    return {
        "supplier": supplier,
        "hub": hub,
        "lane": lane,
        "item": item,
        "customer": customer,
        "linehaul": linehaul,
    }


def setup_routed_network_order(zone: str = "ZONE_NE", service_level: str = "THRESHOLD") -> dict:
    """Reference data plus a routed OWNED_FINAL_MILE order; shipment TENDERED
    bound to the linehaul. Returns refs with 'order' and 'shipment' added.

    ROOM_OF_CHOICE additionally needs an ACTIVE OWNED_FINAL_MILE lane for the
    zone: PRD §3.3 branch two routes on that lane and §3.3 pricing takes
    `shipping_amount_cents` from the lane matching the shipment's leg_mode."""
    refs = setup_reference_data(zone)
    if service_level == "ROOM_OF_CHOICE":
        create_freight_lane(
            leg_mode="OWNED_FINAL_MILE", dest_zone=zone,
            base_rate_cents=50000, per_lb_rate_cents=75, transit_days=2,
        )
    refs["order"] = place_order(refs["customer"], refs["item"]["id"], service_level)
    refs["shipment"] = get_shipment_for_order(refs["order"]["id"])
    return refs


def setup_shipment_in_transit(zone: str = "ZONE_NE") -> dict:
    """Routed network order whose shipment has departed (IN_TRANSIT) and whose
    linehaul has also departed."""
    refs = setup_routed_network_order(zone)
    get_success_data(api_client.depart_shipment(refs["shipment"]["id"], CARRIER))
    get_success_data(api_client.depart_linehaul(refs["linehaul"]["id"], ADMIN))
    return refs


def setup_shipment_at_hub(zone: str = "ZONE_NE", service_level: str = "THRESHOLD") -> dict:
    """Network shipment walked through to AT_HUB (linehaul arrived)."""
    refs = setup_routed_network_order(zone, service_level)
    get_success_data(api_client.depart_shipment(refs["shipment"]["id"], CARRIER))
    get_success_data(api_client.depart_linehaul(refs["linehaul"]["id"], ADMIN))
    get_success_data(api_client.arrive_linehaul(refs["linehaul"]["id"], HUB_OP))
    return refs


def setup_delivered_network_order(zone: str = "ZONE_NE", service_level: str = "THRESHOLD") -> dict:
    """Full network lifecycle through DELIVERED:
    routed -> departed -> linehaul departed/arrived -> appointment booked ->
    completed. Adds 'appointment' and re-reads 'shipment' / 'order'."""
    refs = setup_shipment_at_hub(zone, service_level)
    refs["appointment"] = book_appointment(refs["shipment"])
    get_success_data(api_client.complete_appointment(refs["appointment"]["id"], HUB_OP))
    refs["shipment"] = get_success_data(api_client.get_shipment(refs["shipment"]["id"], ADMIN))
    refs["order"] = get_success_data(api_client.get_order(refs["order"]["id"], ADMIN))
    return refs


# ── Tier 2: damage-claim pipelines ────────────────────────────────────────

def open_claim(shipment_id: str, customer: dict = None, **overrides) -> dict:
    """Open a damage claim. Claims opened by a customer use identity-backed
    headers; otherwise the HubOperator shared constant is used."""
    payload = create_damage_claim_payload(shipment_id=shipment_id, **overrides)
    headers = make_customer_headers(customer["id"]) if customer else HUB_OP
    return get_success_data(api_client.create_damage_claim(payload, headers), 201)


def setup_inspected_claim(damage_pct=20, is_structural=False, repair_cost_cents=20000,
                          concealment="CONCEALED", claimant_role="CUSTOMER") -> dict:
    """Delivered network order + claim inspected to INSPECTION."""
    refs = setup_delivered_network_order()
    customer = refs["customer"] if claimant_role == "CUSTOMER" else None
    refs["claim"] = open_claim(
        refs["shipment"]["id"], customer,
        concealment=concealment, claimant_role=claimant_role,
    )
    payload = {
        "damage_pct": damage_pct,
        "is_structural": is_structural,
        "repair_cost_cents": repair_cost_cents,
    }
    get_success_data(api_client.inspect_damage_claim(refs["claim"]["id"], payload, HUB_OP))
    refs["claim"] = get_success_data(api_client.get_damage_claim(refs["claim"]["id"], ADMIN))
    return refs


def setup_determined_claim(damage_pct=20, is_structural=False, repair_cost_cents=20000,
                           concealment="CONCEALED", claimant_role="CUSTOMER") -> dict:
    """Delivered network order + claim determined (DETERMINATION). When the
    supplier is liable a PENDING chargeback exists; refs['chargeback'] holds
    it (or None for the carrier-liable variant)."""
    refs = setup_inspected_claim(
        damage_pct=damage_pct, is_structural=is_structural,
        repair_cost_cents=repair_cost_cents, concealment=concealment,
        claimant_role=claimant_role,
    )
    get_success_data(api_client.determine_damage_claim(refs["claim"]["id"], ADJUSTER))
    refs["claim"] = get_success_data(api_client.get_damage_claim(refs["claim"]["id"], ADMIN))
    rows = get_success_data(
        api_client.list_chargebacks(ADMIN, params={"damage_claim_id": refs["claim"]["id"]})
    )
    refs["chargeback"] = rows[0] if isinstance(rows, list) and rows else None
    return refs


# ── Tier 3: drop-ship pipelines ───────────────────────────────────────────

def setup_drop_ship_supplier(supplier_code="SUP-D", lead_time_days=3, zone="ZONE_MA") -> dict:
    """Clock + drop-ship supplier + LTL lane for the zone + drop-ship item
    (40x40x20, 25 lb, declared 50000c, not white-glove) + customer in zone."""
    set_clock(SETUP_CLOCK)
    supplier = create_supplier(
        supplier_code, legal_name="DropShip Direct",
        drop_ship_enabled=True, lead_time_days=lead_time_days,
    )
    lane = create_freight_lane(
        leg_mode="LTL", dest_zone=zone,
        base_rate_cents=30000, per_lb_rate_cents=20, transit_days=4,
    )
    item = create_item(
        supplier["id"], sku=f"{supplier_code}-ITEM",
        dim_length_in=40, dim_width_in=40, dim_height_in=20,
        weight_lb=25, declared_value_cents=50000, white_glove_eligible=False,
    )
    customer = create_customer(email=f"{supplier_code.lower()}-cust@example.com",
                               full_name="Drop Ship Customer", destination_zone=zone)
    return {"supplier": supplier, "lane": lane, "item": item, "customer": customer}


def place_drop_ship_order(refs: dict) -> dict:
    """Place a THRESHOLD order against a drop-ship supplier's item. Returns
    {'order', 'shipment'}."""
    order = place_order(refs["customer"], refs["item"]["id"], "THRESHOLD")
    return {"order": order, "shipment": get_shipment_for_order(order["id"])}


def deliver_drop_ship_shipment(refs: dict, shipment_id: str) -> dict:
    """Supplier ship-confirm + delivery confirm (identity-backed headers)."""
    rep = make_supplier_rep_headers(refs["supplier"]["id"])
    get_success_data(api_client.depart_shipment(shipment_id, rep))
    get_success_data(api_client.deliver_shipment(shipment_id, rep))
    return get_success_data(api_client.get_shipment(shipment_id, ADMIN))


def settle_claim_chargeback_for_shipment(refs: dict, shipment_id: str,
                                         repair_cost_cents: int = 5000,
                                         damage_pct: int = 10) -> dict:
    """Open a CONCEALED customer claim on a delivered shipment, inspect it,
    determine it (supplier-liable), settle the chargeback. Returns the
    chargeback record."""
    claim = open_claim(shipment_id, refs["customer"], concealment="CONCEALED")
    get_success_data(
        api_client.inspect_damage_claim(
            claim["id"],
            {"damage_pct": damage_pct, "is_structural": False,
             "repair_cost_cents": repair_cost_cents},
            HUB_OP,
        )
    )
    get_success_data(api_client.determine_damage_claim(claim["id"], ADJUSTER))
    rows = get_success_data(
        api_client.list_chargebacks(ADMIN, params={"damage_claim_id": claim["id"]})
    )
    chargeback = rows[0]
    get_success_data(api_client.settle_chargeback(chargeback["id"], ADMIN))
    return get_success_data(api_client.get_chargeback(chargeback["id"], ADMIN))
