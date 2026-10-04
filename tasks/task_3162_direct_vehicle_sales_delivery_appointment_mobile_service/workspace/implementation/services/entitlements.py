"""Over-the-air feature entitlements: bundles, discounts, expiry, revocation (PRD 3.11)."""

from datetime import timedelta

from db import DB, new_id
from errors import fail, fmt
from repository import find, touch
from services import calculation as calc
from services import ledger


def grant_bundle(vehicle, feature_entries, entitlement_source, trial_days=0,
                 basis_version=None):
    if basis_version is not None:
        current = vehicle.get("software_version")
        if current is not None and not basis_version > current:
            fail("ERR_ENTITLEMENT_VERSION_NOT_NEWER")
    prices = [entry.get("price_cents", 0) for entry in feature_entries]
    bps, bundle_net, shares = calc.entitlement_bundle_price_cents(vehicle["id"], prices)
    rows = []
    for index, entry in enumerate(feature_entries):
        row = {
            "id": new_id(),
            "vehicle_id": vehicle["id"],
            "feature_code": entry.get("feature_code"),
            "entitlement_source": entitlement_source,
            "price_cents": entry.get("price_cents", 0),
            "trial_days": trial_days if entitlement_source == "TRIAL" else 0,
            "bundle_discount_bps": bps,
            "payable_cents": shares[index],
            "bundle_net_cents": bundle_net,
            "effective_at": DB.now,
            "expires_at": (DB.now + timedelta(days=trial_days)
                           if entitlement_source == "TRIAL" else None),
            "status": "ACTIVE",
            "created_at": fmt(DB.now),
            "updated_at": fmt(DB.now),
            "version": 1,
            "basis_version": basis_version,
        }
        DB.entitlements[row["id"]] = row
        rows.append(row)
    if entitlement_source == "PURCHASE":
        order = find("order", vehicle["order_id"])
        if order is not None:
            ledger.write_entry(order["id"], "DELIVERY_FEE_WAIVER", bundle_net,
                               "SOFTWARE_ENTITLEMENT_PURCHASE")
    return rows


def revoke(entitlement):
    if entitlement["status"] in ("EXPIRED", "REVOKED"):
        fail("ERR_ALREADY_TERMINAL")
    entitlement["status"] = "REVOKED"
    touch(entitlement)
    vehicle = find("vehicle", entitlement["vehicle_id"])
    order = find("order", vehicle["order_id"]) if vehicle else None
    if order is not None:
        ledger.write_entry(order["id"], "DELIVERY_FEE_WAIVER", entitlement["price_cents"],
                           "SOFTWARE_ENTITLEMENT_REVOKED")
    return entitlement


def retire_vehicle(vehicle):
    if vehicle["status"] != "IN_SERVICE":
        fail("ERR_INVALID_STATE")
    vehicle["status"] = "RETIRED"
    for entitlement in DB.entitlements.values():
        if entitlement["vehicle_id"] != vehicle["id"]:
            continue
        if entitlement["status"] != "ACTIVE":
            continue
        if entitlement["entitlement_source"] == "PURCHASE":
            continue
        entitlement["status"] = "REVOKED"
        touch(entitlement)
    touch(vehicle)
    return vehicle