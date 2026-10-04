"""Composite setup helpers.

Every fixture builds its preconditions from scratch against an empty database
via PRD-declared endpoints. Setup calls use get_success_data() so failures
surface as clear "Setup failed" errors rather than confusing assertions.

Shared scenario vocabulary (mirrors the PRD's canonical numbers):
  - V_A-style vehicle: book 2,000,000, year 2022, odometer 30,000 ->
    provisional offer 1,680,000; with approved lines 100,000 + 50,000 the
    final offer is 1,605,000 and the initial list price is 1,797,600.
  - V_B-style vehicle: book 800,000, year 2020, odometer 95,000 ->
    provisional == final offer 285,500 (zero repair lines), grade A.
"""
import itertools
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT
from .factories import (
    create_store_payload, create_customer_payload, create_associate_payload,
    create_vehicle_payload, create_appraisal_payload, open_inspection_payload,
    add_line_item_payload, create_transfer_request_payload,
    create_sale_payload, create_return_payload, create_auction_lot_payload,
    close_auction_lot_payload,
)
from .test_users import (
    TEST_USERS, make_store_manager_headers, make_appraiser_headers,
    make_inspector_headers, make_sales_associate_headers,
    make_finance_manager_headers, make_customer_headers,
)

_counter = itertools.count(1)


def _unique_vin() -> str:
    """A fresh 17-character VIN (V + 16 hex digits) unique per call."""
    return "V" + uuid.uuid4().hex[:16].upper()


def _unique_email() -> str:
    return f"c{next(_counter)}-{uuid.uuid4().hex[:8]}@x.com"


def admin_headers():
    return TEST_USERS["platform_admin_headers"]


def auction_manager_headers():
    return TEST_USERS["auction_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: base entity creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_DEFAULT):
    return get_success_data(
        api_client.set_clock(to_iso8601, admin_headers()))


def create_store(store_code="PHX-01", display_name="Phoenix", region="WEST",
                 **overrides):
    payload = create_store_payload(store_code=store_code,
                                   display_name=display_name,
                                   region=region, **overrides)
    return get_success_data(api_client.create_store(payload, admin_headers()))


def create_customer(email=None, **overrides):
    payload = create_customer_payload(email=email or _unique_email(),
                                      **overrides)
    return get_success_data(api_client.create_customer(payload,
                                                       admin_headers()))


def create_associate(store_id, role_kind, display_name=None, **overrides):
    payload = create_associate_payload(
        store_id, role_kind=role_kind,
        display_name=display_name or f"{role_kind.title()} One", **overrides)
    return get_success_data(api_client.create_associate(payload,
                                                        admin_headers()))


def create_vehicle(store_id, manager_id, vin=None, **overrides):
    payload = create_vehicle_payload(store_id,
                                     vin=vin or _unique_vin(), **overrides)
    return get_success_data(api_client.create_vehicle(
        payload, make_store_manager_headers(manager_id)))


# ---------------------------------------------------------------------------
# Tier 2: store + staff scenarios
# ---------------------------------------------------------------------------

def setup_store_with_staff(store_code="PHX-01", region="WEST", **store_kw):
    """Store + one associate per role kind. Returns (store, staff_dict)."""
    set_clock()
    store = create_store(store_code=store_code, region=region, **store_kw)
    sid = store["id"]
    staff = {
        "manager": create_associate(sid, "MANAGER", "Manager One"),
        "appraiser": create_associate(sid, "APPRAISER", "Appraiser One"),
        "inspector": create_associate(sid, "INSPECTOR", "Inspector One"),
        "sales": create_associate(sid, "SALES", "Sales One"),
        "finance": create_associate(sid, "FINANCE", "Finance One"),
    }
    return store, staff


def create_appraisal_for(vehicle_id, customer_id, appraiser_id):
    return get_success_data(api_client.create_appraisal(
        create_appraisal_payload(vehicle_id, customer_id, appraiser_id),
        make_appraiser_headers(appraiser_id)))


def open_inspection_for(vehicle_id, inspector_id):
    return get_success_data(api_client.open_inspection(
        vehicle_id, open_inspection_payload(inspector_id),
        make_inspector_headers(inspector_id)))


def add_line_item_for(inspection_id, inspector_id, category="MECHANICAL",
                      cost_cents=100000):
    return get_success_data(api_client.add_line_item(
        inspection_id,
        add_line_item_payload(category=category, cost_cents=cost_cents),
        make_inspector_headers(inspector_id)))


def approve_line_item_for(inspection_id, line_item_id, inspector_id):
    return get_success_data(api_client.approve_line_item(
        inspection_id, line_item_id, make_inspector_headers(inspector_id)))


def reject_line_item_for(inspection_id, line_item_id, inspector_id):
    return get_success_data(api_client.reject_line_item(
        inspection_id, line_item_id, make_inspector_headers(inspector_id)))


def complete_inspection_for(inspection_id, inspector_id):
    return get_success_data(api_client.complete_inspection(
        inspection_id, make_inspector_headers(inspector_id)))


def list_vehicle_for(vehicle_id, manager_id):
    return get_success_data(api_client.list_vehicle(
        vehicle_id, make_store_manager_headers(manager_id)))


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_vehicle_appraised(store, staff, customer, vin=None, **vehicle_kw):
    """Vehicle INTAKE -> APPRAISED. Returns (vehicle, appraisal)."""
    vehicle = create_vehicle(store["id"], staff["manager"]["id"], vin=vin,
                             **vehicle_kw)
    appraisal = create_appraisal_for(vehicle["id"], customer["id"],
                                     staff["appraiser"]["id"])
    return vehicle, appraisal


def create_vehicle_retail_listed(store, staff, customer, vin=None,
                                 line_items=None, **vehicle_kw):
    """Vehicle driven INTAKE -> APPRAISED -> IN_INSPECTION -> RECON ->
    RETAIL_LISTED. `line_items` is a list of (category, cost_cents) approved
    line items; default is the canonical V_A set (100,000 + 50,000).

    Returns (vehicle, appraisal, inspection).
    """
    if line_items is None:
        line_items = [("MECHANICAL", 100000), ("BODY", 50000)]
    vehicle, appraisal = create_vehicle_appraised(store, staff, customer,
                                                  vin=vin, **vehicle_kw)
    inspection = open_inspection_for(vehicle["id"], staff["inspector"]["id"])
    for category, cost in line_items:
        item = add_line_item_for(inspection["id"], staff["inspector"]["id"],
                                 category=category, cost_cents=cost)
        approve_line_item_for(inspection["id"], item["id"],
                              staff["inspector"]["id"])
    complete_inspection_for(inspection["id"], staff["inspector"]["id"])
    list_vehicle_for(vehicle["id"], staff["manager"]["id"])
    vehicle = get_success_data(api_client.get_vehicle(
        vehicle["id"], make_store_manager_headers(staff["manager"]["id"])))
    appraisal = get_success_data(api_client.get_appraisal(
        appraisal["id"], make_appraiser_headers(staff["appraiser"]["id"])))
    return vehicle, appraisal, inspection


def create_vehicle_wholesale_pending(store, staff, customer, vin=None,
                                     line_items=None, **vehicle_kw):
    """Vehicle driven to WHOLESALE_PENDING (WHOLESALE disposition).
    Returns (vehicle, appraisal, inspection)."""
    if line_items is None:
        line_items = [("SAFETY", 100000)]
    vehicle, appraisal = create_vehicle_appraised(store, staff, customer,
                                                  vin=vin, **vehicle_kw)
    inspection = open_inspection_for(vehicle["id"], staff["inspector"]["id"])
    for category, cost in line_items:
        item = add_line_item_for(inspection["id"], staff["inspector"]["id"],
                                 category=category, cost_cents=cost)
        approve_line_item_for(inspection["id"], item["id"],
                              staff["inspector"]["id"])
    complete_inspection_for(inspection["id"], staff["inspector"]["id"])
    vehicle = get_success_data(api_client.get_vehicle(
        vehicle["id"], make_store_manager_headers(staff["manager"]["id"])))
    appraisal = get_success_data(api_client.get_appraisal(
        appraisal["id"], make_appraiser_headers(staff["appraiser"]["id"])))
    return vehicle, appraisal, inspection


def create_vehicle_with_active_appraisal(store, staff, customer, vin=None,
                                         line_items=None, **vehicle_kw):
    """Vehicle appraised and inspected (no listing); the sourcing appraisal is
    ACTIVE with its final offer. Returns (vehicle, appraisal)."""
    if line_items is None:
        line_items = []
    vehicle, appraisal = create_vehicle_appraised(store, staff, customer,
                                                  vin=vin, **vehicle_kw)
    inspection = open_inspection_for(vehicle["id"], staff["inspector"]["id"])
    for category, cost in line_items:
        item = add_line_item_for(inspection["id"], staff["inspector"]["id"],
                                 category=category, cost_cents=cost)
        approve_line_item_for(inspection["id"], item["id"],
                              staff["inspector"]["id"])
    complete_inspection_for(inspection["id"], staff["inspector"]["id"])
    vehicle = get_success_data(api_client.get_vehicle(
        vehicle["id"], make_store_manager_headers(staff["manager"]["id"])))
    appraisal = get_success_data(api_client.get_appraisal(
        appraisal["id"], make_appraiser_headers(staff["appraiser"]["id"])))
    return vehicle, appraisal


def create_sale_for(vehicle, customer, associate, trade_in_appraisal_id=None):
    payload = create_sale_payload(
        vehicle["id"], customer["id"], associate["id"],
        **({"trade_in_appraisal_id": trade_in_appraisal_id}
           if trade_in_appraisal_id else {}))
    return get_success_data(api_client.create_sale(
        payload, make_sales_associate_headers(associate["id"])))


def create_completed_cash_sale(store, staff, customer, vin=None,
                               line_items=None, trade_in_appraisal_id=None,
                               **vehicle_kw):
    """RETAIL_LISTED vehicle sold cash (no financing) and completed.
    Returns (vehicle, appraisal, inspection, sale)."""
    vehicle, appraisal, inspection = create_vehicle_retail_listed(
        store, staff, customer, vin=vin, line_items=line_items, **vehicle_kw)
    sale = create_sale_for(vehicle, customer, staff["sales"],
                           trade_in_appraisal_id=trade_in_appraisal_id)
    sale = get_success_data(api_client.complete_sale(
        sale["id"], make_sales_associate_headers(staff["sales"]["id"])))
    vehicle = get_success_data(api_client.get_vehicle(
        vehicle["id"], make_store_manager_headers(staff["manager"]["id"])))
    return vehicle, appraisal, inspection, sale


def get_vehicle_version(vehicle_id, headers):
    data = get_success_data(api_client.get_vehicle(vehicle_id, headers))
    return data["version"]


def create_transfer_for(vehicle, customer, to_store_id, expedited=False,
                        supersedes_request_id=None):
    """Create a transfer request with the vehicle's current version."""
    version = get_vehicle_version(vehicle["id"],
                                  make_customer_headers(customer["id"]))
    payload = create_transfer_request_payload(
        vehicle["id"], customer["id"], to_store_id, version,
        expedited=expedited,
        **({"supersedes_request_id": supersedes_request_id}
           if supersedes_request_id else {}))
    return get_success_data(api_client.create_transfer_request(
        payload, make_customer_headers(customer["id"])))


def setup_returned_cash_sale(store, staff, customer, odometer_at_return=30100,
                             reason_code="CHANGED_MIND", **vehicle_kw):
    """Cash sale completed, return opened and approved (not settled).
    Returns (vehicle, appraisal, sale, return_request)."""
    vehicle, appraisal, _insp, sale = create_completed_cash_sale(
        store, staff, customer, **vehicle_kw)
    ret = get_success_data(api_client.create_return(
        create_return_payload(sale["id"], reason_code=reason_code,
                              odometer_at_return=odometer_at_return),
        make_customer_headers(customer["id"])))
    ret = get_success_data(api_client.approve_return(
        ret["id"], make_store_manager_headers(staff["manager"]["id"])))
    return vehicle, appraisal, sale, ret


def store_ledger_entries(store_id, manager_id, entry_kind=None):
    params = {"limit": 100}
    if entry_kind:
        params["entry_kind"] = entry_kind
    data, _meta = _paginated(api_client.list_ledger_entries(
        store_id, make_store_manager_headers(manager_id), params=params))
    return data


def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)
