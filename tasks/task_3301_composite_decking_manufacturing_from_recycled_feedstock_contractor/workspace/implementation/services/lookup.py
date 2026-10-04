"""Lookup helpers: path/body existence checks with the correct error ids."""
import db as dbmod
from errors import (raise_err, ERR_NOT_FOUND, ERR_REFERENCED_NOT_FOUND,
                    ERR_INVALID_REQUEST)

COLLECTIONS = {
    "plants": "plants",
    "suppliers": "suppliers",
    "collection_programs": "collection_programs",
    "feedstock_lots": "feedstock_lots",
    "formulations": "formulations",
    "product_lines": "product_lines",
    "dealers": "dealers",
    "shipment_orders": "shipment_orders",
    "stocking_commitments": "stocking_commitments",
    "allocation_commitments": "allocation_commitments",
    "production_runs": "production_runs",
    "board_lots": "board_lots",
    "contractors": "contractors",
    "training_modules": "training_modules",
    "training_records": "training_records",
    "lead_referrals": "lead_referrals",
    "install_registrations": "install_registrations",
    "warranty_claims": "warranty_claims",
    "claim_samples": "claim_samples",
    "sample_kits": "sample_kits",
    "color_chip_requests": "color_chip_requests",
    "price_books": "price_books",
}


def get_path(collection, rid):
    coll = getattr(dbmod.db, COLLECTIONS[collection])
    r = coll.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, f"{collection} not found: {rid}")
    return r


def get_body_ref(collection, rid, field=None):
    if rid is None:
        raise_err(ERR_INVALID_REQUEST,
                  f"missing required field: {field or collection}")
    coll = getattr(dbmod.db, COLLECTIONS[collection])
    r = coll.get(rid)
    if r is None:
        raise_err(ERR_REFERENCED_NOT_FOUND,
                  f"referenced {collection} not found: {field or rid}")
    return r


def single_plant():
    """Most fixtures create exactly one plant; lots live against it."""
    plants = list(dbmod.db.plants.values())
    return plants[0] if plants else None


def plant_for_line(line_id):
    """Pick the plant holding this line's finished-goods ledger: prefer one
    with an existing fg_store/reserved_fg_store entry or runs for the line;
    otherwise the first plant. The bench is single-plant per recipe."""
    plants = list(dbmod.db.plants.values())
    if not plants:
        return None
    for p in plants:
        if line_id in p["fg_store"] or line_id in p["reserved_fg_store"]:
            return p
    for r in dbmod.db.production_runs.values():
        if r["product_line_id"] == line_id:
            p = dbmod.db.plants.get(r["plant_id"])
            if p is not None:
                return p
    return plants[0]
