"""Child registration, address changes and the three-branch decide flow."""

from flask import Blueprint, request

import db
import domain
from errors import ApiError
from response import ok, created, listing
from validation import (
    require_roles, ALL_ROLES, body, check_allowed, req_string, req_address,
    parse_date_value, pagination,
)

bp = Blueprint("children", __name__, url_prefix="/library")


def get_child_or_404(cid):
    c = db.children.get(cid)
    if c is None:
        raise ApiError(404, "ERR_CHILD_NOT_FOUND", "Referenced child id does not exist")
    return c


def _create_child_record(affiliate_id, full_name, family_name, birth_raw, birth,
                         address, registered_month, transfer_source_child_id):
    prefix = address["postal_code"].upper()[:3]
    birth_month = "%04d-%02d" % (birth.year, birth.month)
    rec = db.base_record()
    rec.update({
        "affiliate_id": affiliate_id,
        "full_name": full_name,
        "family_name": family_name,
        "birth_date": birth_raw,
        "mailing_address": address,
        "postal_prefix": prefix,
        "registered_month": registered_month,
        "enrollment_status": "ACTIVE",
        "unenroll_reason": None,
        "consecutive_returns": 0,
        "transfer_source_child_id": transfer_source_child_id,
        "expected_final_mailing_month": domain.month_add(birth_month, 59),
        "_birth": birth,
    })
    db.children[rec["id"]] = rec
    return rec


@bp.post("/children")
def create_child():
    uid, role = require_roles("AffiliateCoordinator")
    data = body()
    check_allowed(data, {"affiliate_id", "full_name", "family_name",
                         "birth_date", "mailing_address"})
    affiliate_id = req_string(data, "affiliate_id")
    full_name = req_string(data, "full_name")
    family_name = req_string(data, "family_name")
    birth_raw = req_string(data, "birth_date")
    birth = parse_date_value(birth_raw)
    address = req_address(data, "mailing_address")
    # Priority 5: coordinator registers into their own affiliate only.
    if uid != affiliate_id:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Coordinator may only register children into their own affiliate")
    # Priority 9: scalar temporal rules.
    if birth >= db.logical_date():
        raise ApiError(422, "ERR_BIRTH_DATE_IN_FUTURE",
                       "birth_date is on or after the current logical date")
    registered_month = db.logical_month()
    if domain.age_months(birth, registered_month) >= 60:
        raise ApiError(422, "ERR_CHILD_AGE_INELIGIBLE",
                       "Child is already 60+ months old in the registration month")
    # Priority 10: duplicate registration among non-terminal children.
    prefix = address["postal_code"].upper()[:3]
    fam = family_name.lower()
    for c in db.children.values():
        if (c["affiliate_id"] == affiliate_id
                and c["enrollment_status"] in domain.ACTIVE_CHILD_STATES
                and c["_birth"] == birth
                and c["postal_prefix"] == prefix
                and c["family_name"].lower() == fam):
            raise ApiError(409, "ERR_DUPLICATE_REGISTRATION",
                           "A non-terminal child with the same birth date, postal prefix "
                           "and family name already exists on this affiliate")
    # Priority 11: body-referenced FK, then FK-dependent rules.
    aff = db.affiliates.get(affiliate_id)
    if aff is None:
        raise ApiError(404, "ERR_AFFILIATE_NOT_FOUND",
                       "Referenced affiliate id does not exist")
    if not domain.operative_for_month(affiliate_id, registered_month):
        raise ApiError(409, "ERR_AFFILIATE_NOT_OPERATIVE",
                       "Registering affiliate has no ACTIVE agreement fully covering "
                       "the current logical month")
    if prefix not in aff["postal_prefixes"]:
        raise ApiError(422, "ERR_ADDRESS_NOT_COVERED",
                       "Child's postal_prefix is not covered by the affiliate")
    rec = _create_child_record(affiliate_id, full_name, family_name, birth_raw,
                               birth, address, registered_month, None)
    return created(domain.ser_child(rec))


@bp.get("/children/<cid>")
def get_child(cid):
    require_roles(*ALL_ROLES)
    return ok(domain.ser_child(get_child_or_404(cid)))


@bp.get("/children")
def list_children():
    uid, role = require_roles(*ALL_ROLES)
    limit, offset = pagination()
    f_aff = request.args.get("affiliate_id")
    f_status = request.args.get("enrollment_status")
    f_src = request.args.get("transfer_source_child_id")
    if role == "AffiliateCoordinator":
        if f_aff is not None and f_aff != uid:
            raise ApiError(403, "ERR_FORBIDDEN",
                           "Coordinator may only list their own affiliate's children")
        f_aff = uid
    rows = [c for c in db.children.values()
            if (f_aff is None or c["affiliate_id"] == f_aff)
            and (f_status is None or c["enrollment_status"] == f_status)
            and (f_src is None or c["transfer_source_child_id"] == f_src)]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([domain.ser_child(c) for c in page], limit, offset, total)


@bp.post("/children/<cid>/address-changes")
def create_address_change(cid):
    uid, role = require_roles("AffiliateCoordinator")
    child = get_child_or_404(cid)
    data = body()
    check_allowed(data, {"new_address"})
    new_address = req_address(data, "new_address")
    if uid != child["affiliate_id"]:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Coordinator may only act on children of their own affiliate")
    if child["enrollment_status"] not in domain.ACTIVE_CHILD_STATES:
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Address changes require a non-terminal child "
                       "(ACTIVE or UNDELIVERABLE_HOLD)")
    rec = db.base_record()
    rec.update({
        "child_id": cid,
        "new_address": new_address,
        "new_postal_prefix": new_address["postal_code"].upper()[:3],
        "status": "PENDING",
        "decided_by": None,
        "resulting_child_id": None,
    })
    db.address_changes[rec["id"]] = rec
    return created(domain.ser_address_change(rec))


@bp.get("/children/<cid>/address-changes")
def list_address_changes(cid):
    uid, role = require_roles(*ALL_ROLES)
    child = get_child_or_404(cid)
    if role == "AffiliateCoordinator" and uid != child["affiliate_id"]:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Coordinator may only read their own affiliate's address changes")
    limit, offset = pagination()
    f_status = request.args.get("status")
    rows = [a for a in db.address_changes.values()
            if a["child_id"] == cid
            and (f_status is None or a["status"] == f_status)]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([domain.ser_address_change(a) for a in page], limit, offset, total)


def _select_transfer_target(new_postal_prefix, month):
    """Operative affiliates covering the prefix, ranked by earliest covering
    agreement effective_from, tie-broken by agreement created_at ascending."""
    best_aff = None
    best_key = None
    for aff in db.affiliates.values():
        if new_postal_prefix not in aff["postal_prefixes"]:
            continue
        covering = [a for a in db.agreements.values()
                    if a["affiliate_id"] == aff["id"]
                    and domain.agreement_covers_month(a, month)]
        if not covering:
            continue
        key = min((a["_from"], a["created_at"], a["_seq"]) for a in covering)
        if best_aff is None or key < best_key:
            best_aff = aff
            best_key = key
    return best_aff


@bp.post("/address-changes/<acid>/decide")
def decide_address_change(acid):
    uid, role = require_roles("AffiliateCoordinator")
    ac = db.address_changes.get(acid)
    if ac is None:
        raise ApiError(404, "ERR_ADDRESS_CHANGE_NOT_FOUND",
                       "Referenced address change id does not exist")
    data = body()
    check_allowed(data, {"outcome"})
    outcome = req_string(data, "outcome")
    if outcome not in ("APPROVE", "REJECT"):
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "outcome must be APPROVE or REJECT")
    child = db.children[ac["child_id"]]
    if uid != child["affiliate_id"]:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Coordinator may only decide changes of their own affiliate")
    if ac["status"] != "PENDING":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a PENDING address change can be decided")
    if outcome == "REJECT":
        ac["status"] = "REJECTED"
        ac["decided_by"] = uid
        db.touch(ac)
        return ok(domain.ser_address_change(ac))

    # APPROVE: child must still be non-terminal.
    if child["enrollment_status"] not in domain.ACTIVE_CHILD_STATES:
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Child is terminal; the address change can no longer be applied")
    current_month = db.logical_month()
    current_aff = db.affiliates[child["affiliate_id"]]
    if ac["new_postal_prefix"] in current_aff["postal_prefixes"]:
        # Branch 1: in-area move; revalidates the address and clears any hold.
        ac["status"] = "APPLIED_IN_AREA"
        child["mailing_address"] = ac["new_address"]
        child["postal_prefix"] = ac["new_postal_prefix"]
        child["enrollment_status"] = "ACTIVE"
        child["consecutive_returns"] = 0
        db.touch(child)
    else:
        target = _select_transfer_target(ac["new_postal_prefix"], current_month)
        if target is not None:
            # Branch 2: transfer to a different operative affiliate.
            ac["status"] = "APPLIED_TRANSFER"
            child["enrollment_status"] = "TRANSFERRED_OUT"
            db.touch(child)
            new_child = _create_child_record(
                target["id"], child["full_name"], child["family_name"],
                child["birth_date"], child["_birth"], ac["new_address"],
                current_month, child["id"])
            ac["resulting_child_id"] = new_child["id"]
        else:
            # Branch 3: no operative affiliate covers the new prefix.
            ac["status"] = "APPLIED_UNENROLLED"
            child["enrollment_status"] = "UNENROLLED"
            child["unenroll_reason"] = "MOVED_OUT_OF_AREA"
            db.touch(child)
    ac["decided_by"] = uid
    db.touch(ac)
    return ok(domain.ser_address_change(ac))
