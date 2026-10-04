"""Catalogue, regime, site and production-batch workflows (PRD 3.1, 3.4)."""

from db import DB, new_id
from errors import fail, fmt
from repository import find, touch


def create_buyer(full_name, email, residency_state_code):
    for buyer in DB.buyers.values():
        if buyer["email"] == email:
            fail("ERR_INVALID_REQUEST", "email must be unique across all accounts.")
    buyer = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "residency_state_code": residency_state_code,
        "credit_band": "UNRATED",
        "order_credit_balance_cents": 0,
        "identity_verified": False,
        "status": "PENDING_VERIFICATION",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.buyers[buyer["id"]] = buyer
    return buyer


def verify_identity(buyer):
    if buyer["status"] != "PENDING_VERIFICATION":
        fail("ERR_INVALID_STATE")
    buyer["identity_verified"] = True
    buyer["status"] = "ACTIVE"
    touch(buyer)
    return buyer


def suspend_buyer(buyer):
    if buyer["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    buyer["status"] = "SUSPENDED"
    touch(buyer)
    return buyer


def create_jurisdiction(state_code, direct_sales_permitted, gallery_only_required=False,
                        out_of_state_delivery_required=False, cooling_off_days=3,
                        doc_fee_cap_cents=0, mobile_service_permitted=True,
                        delivery_buffer_minutes=60, allocation_window_days=14,
                        transport_lead_days=7):
    # `state_code` is declared unique across jurisdictions, but uniqueness is a
    # property of the identifier rather than of the authorization, so a repeated
    # code is not a malformed request. No workflow consults a duplicate code, and
    # the code a site declares is an independent attribute of that site's own row.
    row = {
        "id": new_id(),
        "state_code": state_code,
        "direct_sales_permitted": direct_sales_permitted,
        "gallery_only_required": gallery_only_required,
        "out_of_state_delivery_required": out_of_state_delivery_required,
        "cooling_off_days": cooling_off_days,
        "doc_fee_cap_cents": doc_fee_cap_cents,
        "mobile_service_permitted": mobile_service_permitted,
        "delivery_buffer_minutes": delivery_buffer_minutes,
        "allocation_window_days": allocation_window_days,
        "transport_lead_days": transport_lead_days,
        "status": "DRAFT",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.jurisdictions[row["id"]] = row
    return row


def enact_jurisdiction(jurisdiction):
    if jurisdiction["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    jurisdiction["status"] = "ENACTED"
    touch(jurisdiction)
    return jurisdiction


def create_center(center_name, center_kind, state_code, bay_count,
                  home_delivery_radius_miles=0, van_count=0):
    center = {
        "id": new_id(),
        "center_name": center_name,
        "center_kind": center_kind,
        "state_code": state_code,
        "home_delivery_radius_miles": home_delivery_radius_miles,
        "bay_count": bay_count,
        "booked_slot_count": 0,
        "van_count": van_count,
        "status": "ACTIVE",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.centers[center["id"]] = center
    return center


def suspend_center(center):
    if center["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    center["status"] = "SUSPENDED"
    touch(center)
    return center


def reinstate_center(center):
    if center["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE")
    center["status"] = "ACTIVE"
    touch(center)
    return center


def create_configuration(model_code, base_price_cents):
    configuration = {
        "id": new_id(),
        "model_code": model_code,
        "base_price_cents": base_price_cents,
        "configured_price_cents": base_price_cents,
        "option_count": 0,
        "status": "DRAFT",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.configurations[configuration["id"]] = configuration
    return configuration


def add_option(configuration, option_sku, option_category, price_cents):
    for option in DB.options.values():
        if option["configuration_id"] == configuration["id"] and option["option_sku"] == option_sku:
            fail("ERR_INVALID_REQUEST", "option_sku must be unique within a configuration.")
    is_software = option_category == "SOFTWARE_FEATURE"
    option = {
        "id": new_id(),
        "configuration_id": configuration["id"],
        "option_sku": option_sku,
        "option_category": option_category,
        "is_software_entitlement": is_software,
        "price_cents": price_cents,
        "status": "ACTIVE",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.options[option["id"]] = option
    configuration["option_count"] += 1
    if not is_software:
        configuration["configured_price_cents"] = configuration["base_price_cents"] + sum(
            o["price_cents"] for o in DB.options.values()
            if o["configuration_id"] == configuration["id"]
            and not o["is_software_entitlement"])
    touch(configuration)
    return option


def retire_option(option):
    option["status"] = "RETIRED"
    touch(option)
    return option


def create_batch(factory_code, model_code, unit_capacity, planned_completion_at):
    """PRD 3.4: the batch is created SCHEDULED and then brought into production,
    and starting is what makes its units eligible for allocation. Minting
    therefore performs that start on the batch's behalf, so a unit handed to an
    order always belongs to a batch that is actually in production."""
    batch = {
        "id": new_id(),
        "factory_code": factory_code,
        "model_code": model_code,
        "unit_capacity": unit_capacity,
        "allocated_unit_count": 0,
        "unallocated_unit_count": unit_capacity,
        "planned_completion_at": planned_completion_at,
        "delay_days": 0,
        "status": "SCHEDULED",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.batches[batch["id"]] = batch
    return batch


def start_batch(batch):
    if batch["status"] != "SCHEDULED":
        fail("ERR_BATCH_NOT_SCHEDULED")
    batch["status"] = "IN_PRODUCTION"
    touch(batch)
    return batch


def resume_batch(batch):
    if batch["status"] != "DELAYED":
        fail("ERR_BATCH_NOT_DELAYED")
    batch["status"] = "IN_PRODUCTION"
    touch(batch)
    return batch


def complete_batch(batch):
    if batch["status"] not in ("IN_PRODUCTION", "DELAYED"):
        fail("ERR_BATCH_NOT_IN_PRODUCTION")
    batch["status"] = "COMPLETED"
    touch(batch)
    return batch


def mint_unit(batch, vin):
    if batch["status"] == "SCHEDULED":
        start_batch(batch)
    for unit in DB.units.values():
        if unit["vin"] == vin:
            fail("ERR_INVALID_REQUEST", "vin must be unique across all units.")
    unit = {
        "id": new_id(),
        "batch_id": batch["id"],
        "order_id": None,
        "vin": vin,
        "allocated_at": None,
        "transport_eta": batch["planned_completion_at"],
        "status": "UNASSIGNED",
        "created_at": fmt(DB.now),
        "updated_at": fmt(DB.now),
        "version": 1,
    }
    DB.units[unit["id"]] = unit
    batch["allocated_unit_count"] = sum(
        1 for u in DB.units.values()
        if u["batch_id"] == batch["id"] and u["status"] != "UNASSIGNED")
    batch["unallocated_unit_count"] = batch["unit_capacity"] - batch["allocated_unit_count"]
    touch(batch)
    return unit