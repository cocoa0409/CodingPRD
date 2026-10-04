"""Store assortment items (add / get / list / soft-delete)."""
from flask import request

import errors as E
import middleware as mw
from db import db
from response import success_list, success_no_content, success_object
from services import calculations as calc
from routes.agreements import bp, get_store


def pub_assortment(ai):
    return {
        "id": ai["id"], "store_id": ai["store_id"], "product_item_id": ai["product_item_id"],
        "par_level": ai["par_level"], "on_hand": ai["on_hand"], "active": ai["active"],
        "created_at": ai["created_at"], "updated_at": ai["updated_at"], "version": ai["version"],
    }


def _licensee_scope(uid, role, store):
    if role == "LicenseeManager" and uid != mw.licensee_of_store(store):
        raise E.err_forbidden()


@bp.post("/licensing/stores/<sid>/assortment-items")
def add_assortment_item(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    store = get_store(sid)
    _licensee_scope(uid, role, store)
    b = mw.body()
    product_item_id = mw.req_str(b, "product_item_id")
    product = db.product_items.get(product_item_id)
    if product is None:
        raise E.err_not_found("product item not found")
    # business-safety gates precede business constraints (PRD §2.6), so the
    # venue-type / posture / footprint checks run before the par_level shape
    # check below.
    agreement = db.license_agreements[store["agreement_id"]]
    venue = db.host_venues[agreement["venue_id"]]
    if product["venue_type_restrictions"] and venue["venue_type"] not in product["venue_type_restrictions"]:
        raise E.err_venue_type_prohibited()
    # proprietary-posture gate
    if product["proprietary"] and store["compliance_posture"] == "PROBATION":
        raise E.err_proprietary_restricted()
    # footprint gate
    usage = calc.venue_footprint_usage(venue["id"]) + product["footprint_units"]
    if usage > venue["max_equipment_footprint_units"]:
        raise E.err_footprint()
    par_level = mw.req_int(b, "par_level", minimum=0, maximum=calc.MAX_PAR_LEVEL)
    rec = mw.make_resource({
        "store_id": sid, "product_item_id": product_item_id,
        "par_level": par_level, "on_hand": 0, "active": True,
    })
    db.assortment_items[rec["id"]] = rec
    mw.touch(store)
    return success_object(pub_assortment(rec), 201)


@bp.get("/licensing/store-assortment-items/<aiid>")
def get_assortment_item(aiid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    ai = db.assortment_items.get(aiid)
    if ai is None:
        raise E.err_not_found("assortment item not found")
    if role == "LicenseeManager":
        store = db.stores[ai["store_id"]]
        _licensee_scope(uid, role, store)
    return success_object(pub_assortment(ai))


@bp.get("/licensing/store-assortment-items")
def list_assortment_items():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    items = list(db.assortment_items.values())
    if role == "LicenseeManager":
        items = [
            ai for ai in items
            if mw.licensee_of_store(db.stores[ai["store_id"]]) == uid
        ]
    sid = request.args.get("store_id")
    if sid is not None:
        items = [ai for ai in items if ai["store_id"] == sid]
    pid = request.args.get("product_item_id")
    if pid is not None:
        items = [ai for ai in items if ai["product_item_id"] == pid]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_assortment(x) for x in page], limit, offset, total)


@bp.delete("/licensing/store-assortment-items/<aiid>")
def delete_assortment_item(aiid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    ai = db.assortment_items.get(aiid)
    if ai is None:
        raise E.err_not_found("assortment item not found")
    store = db.stores[ai["store_id"]]
    _licensee_scope(uid, role, store)
    if store["operating_status"] == "OPERATING":
        raise E.err_invalid_store_state(
            "assortment may not be removed while the store is OPERATING"
        )
    ai["active"] = False
    mw.touch(ai)
    return success_no_content()
