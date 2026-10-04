"""Donation sites, donation intake, and the sort."""
import uuid

from flask import Blueprint

import errors
from clock import now
from db import store
from envelope import success
from serializers import ser_donation, ser_site
from services import (
    CATEGORIES,
    GRADES,
    new_entity,
    new_light_entity,
    org_of_donation,
    receipt_fmv,
    touch,
)
from validate import auth, field, get_body, paginate, require_role, sort_created

bp = Blueprint("donations", __name__)

SITE_TYPES = {"ADC", "STORE_DROP"}


def _get_org(oid):
    org = store.member_orgs.get(oid)
    if org is None:
        errors.not_found("MemberOrg not found")
    return org


@bp.post("/donated-goods/donation-sites")
def create_site():
    body = get_body()
    member_org_id = field(body, "member_org_id", "str", required=True)
    name = field(body, "name", "str", required=True)
    site_type = field(body, "site_type", "str", required=True, enum=SITE_TYPES)
    uid, role = auth()
    require_role(role, {"MemberAdmin"})
    if uid != member_org_id:
        errors.ownership_mismatch()
    org = _get_org(member_org_id)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    with store.lock:
        site = new_light_entity()
        site.update({
            "member_org_id": member_org_id,
            "name": name,
            "site_type": site_type,
        })
        store.donation_sites[site["id"]] = site
    return success(ser_site(site), 201)


@bp.get("/donated-goods/member-orgs/<oid>/donation-sites")
def list_sites(oid):
    auth()
    _get_org(oid)
    items = sort_created(
        [s for s in store.donation_sites.values() if s["member_org_id"] == oid]
    )
    page, meta = paginate(items)
    return success([ser_site(s) for s in page], 200,
                   response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Donations
# ---------------------------------------------------------------------------

@bp.post("/donated-goods/donations")
def create_donation():
    body = get_body()
    site_id = field(body, "site_id", "str", required=True)
    donor_name = field(body, "donor_name", "str", required=True)
    donor_email = field(body, "donor_email", "str", required=False)
    item_count = field(body, "item_count_declared", "int", required=True, minval=0)
    uid, role = auth()
    require_role(role, {"DonationAttendant"})
    # Ownership on create: the request's site_id must equal X-User-ID.
    if uid != site_id:
        errors.ownership_mismatch()
    site = store.donation_sites.get(site_id)
    if site is None:
        errors.not_found("DonationSite not found")
    # Donation intake is NOT an org-scoped write under the suspension gate
    # (PRD 2.7 enumeration); only the sort is gated.
    with store.lock:
        is_adc = site["site_type"] == "ADC"
        donation = new_entity()
        donation.update({
            "site_id": site_id,
            "donor_name": donor_name,
            "donor_email": donor_email,
            "item_count_declared": item_count,
            "status": "RECEIVED",
            "receipt_issued": is_adc,
            "receipt_token": str(uuid.uuid4()) if is_adc else None,
            "receipt_fmv_total_cents": None,
            "sorted_at": None,
        })
        store.donations[donation["id"]] = donation
    return success(ser_donation(donation), 201)


@bp.get("/donated-goods/donations")
def list_donations():
    auth()
    from flask import request
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    items = store.donations.values()
    if site_id is not None:
        items = [d for d in items if d["site_id"] == site_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_donation(d) for d in page], 200,
                   response_type="array", pagination=meta)


def _get_donation(did):
    donation = store.donations.get(did)
    if donation is None:
        errors.not_found("Donation not found")
    return donation


@bp.get("/donated-goods/donations/<did>")
def get_donation(did):
    auth()
    return success(ser_donation(_get_donation(did)), 200)


@bp.post("/donated-goods/donations/<did>/sort")
def sort_donation(did):
    body = get_body()
    items_in = field(body, "items", "list", required=True)
    parsed = []
    for entry in items_in:
        if not isinstance(entry, dict):
            errors.invalid_request("Each item descriptor must be an object")
        cat = field(entry, "category", "str", required=True, enum=CATEGORIES)
        grade = field(entry, "condition_grade", "str", required=True, enum=GRADES)
        ev = field(entry, "estimated_value_cents", "int", required=True)
        wt = field(entry, "weight_lbs", "number", required=True, minval=0)
        parsed.append((cat, grade, ev, wt))
    uid, role = auth()
    require_role(role, {"DonationAttendant"})
    donation = _get_donation(did)
    # Ownership: the donation's own site_id must equal X-User-ID.
    if donation["site_id"] != uid:
        errors.ownership_mismatch()
    org = org_of_donation(donation)
    if org["brand_license_status"] != "ACTIVE":
        errors.org_suspended()
    if donation["status"] != "RECEIVED":
        errors.invalid_state("Donation is not RECEIVED")
    if len(parsed) != donation["item_count_declared"]:
        errors.item_count_mismatch()
    with store.lock:
        for cat, grade, ev, wt in parsed:
            item = new_entity()
            item.update({
                "donation_id": did,
                "category": cat,
                "condition_grade": grade,
                "estimated_value_cents": ev,
                "weight_lbs": wt,
                "status": "SALVAGED" if grade == "UNSALABLE" else "SORTED",
                "price_cents": None,
                "current_selling_price_cents": None,
                "color_tag": None,
                "floor_week": None,
                "markdown_step": 0,
                "priced_standard_id": None,
                "unit_cost_cents": None,
                "salvage_lot_id": None,
                "sold_at": None,
            })
            store.donated_items[item["id"]] = item
        donation["receipt_fmv_total_cents"] = receipt_fmv(parsed)
        donation["status"] = "SORTED"
        donation["sorted_at"] = now()
        touch(donation)
    return success(ser_donation(donation), 200)
