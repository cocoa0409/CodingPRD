"""Label amendments (PRD 3.5): OCC-guarded filing, timelines, decisions."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import constants
from auth import require_auth, require_role
from db import new_row, store, touch
from envelope import ok, ok_list
from errors import err
from services.calcs import amendment_review_days
from validate import (
    as_bool,
    as_dict,
    as_enum,
    as_int,
    as_num,
    as_str,
    paginate,
    parse_body,
    reject_unknown,
    validate_use_site,
)

bp = Blueprint("amendments", __name__)


def get_amendment_or_404(amendment_id):
    amendment = store["amendments"].get(amendment_id)
    if amendment is None:
        err("ERR_NOT_FOUND", "Label amendment %s does not exist." % amendment_id)
    return amendment


def _validate_payload(amendment_type, payload):
    """Type-keyed payload shape (stage 3 schema). Returns normalized payload."""
    if amendment_type == "NEW_USE":
        reject_unknown(payload, ["use_site", "commodity_code", "tolerance_ppm"])
        use_site = validate_use_site(payload.get("use_site"))
        commodity_code = None
        if payload.get("commodity_code") is not None:
            commodity_code = as_str(payload, "commodity_code")
        tolerance_ppm = as_num(
            payload, "tolerance_ppm", required=False, minimum=0, exclusive_minimum=True
        )
        if tolerance_ppm is not None and commodity_code is None:
            err(
                "ERR_INVALID_REQUEST",
                "commodity_code is required when tolerance_ppm is present.",
            )
        normalized = {"use_site": use_site}
        if commodity_code is not None:
            normalized["commodity_code"] = commodity_code
        if tolerance_ppm is not None:
            normalized["tolerance_ppm"] = tolerance_ppm
        return normalized
    if amendment_type == "RATE_CHANGE":
        reject_unknown(payload, ["use_site_id", "new_max_application_rate_lbs_acre"])
        return {
            "use_site_id": as_str(payload, "use_site_id", required=True),
            "new_max_application_rate_lbs_acre": as_num(
                payload,
                "new_max_application_rate_lbs_acre",
                required=True,
                minimum=0,
                exclusive_minimum=True,
            ),
        }
    # METHOD_CHANGE
    reject_unknown(payload, ["use_site_id", "new_application_method", "expedited"])
    normalized = {
        "use_site_id": as_str(payload, "use_site_id", required=True),
        "new_application_method": as_enum(
            payload, "new_application_method", constants.APPLICATION_METHODS, required=True
        ),
    }
    expedited = as_bool(payload, "expedited", required=False)
    if expedited is not None:
        normalized["expedited"] = expedited
    return normalized


@bp.post("/label-amendments")
def create_amendment():
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRANT_REPRESENTATIVE])
    data = parse_body()
    reject_unknown(data, ["product_id", "amendment_type", "payload", "expected_product_version"])
    product_id = as_str(data, "product_id", required=True)
    amendment_type = as_enum(data, "amendment_type", constants.AMENDMENT_TYPES, required=True)
    payload = as_dict(data, "payload", required=True)
    expected_product_version = as_int(data, "expected_product_version", required=True)
    normalized_payload = _validate_payload(amendment_type, payload)

    # Stage 4: existence. Stage 5: ownership.
    product = store["products"].get(product_id)
    if product is None:
        err("ERR_PRODUCT_NOT_FOUND", "Product %s does not exist." % product_id)
    if product["registrant_ref"] != caller["user_id"]:
        err("ERR_NOT_RESOURCE_OWNER", "The product belongs to another registrant.")

    # Stage 6: optimistic concurrency, before any business validation.
    if expected_product_version != product["version"]:
        err(
            "ERR_STALE_PRODUCT_VERSION",
            "expected_product_version does not match the product's current version.",
        )

    # Stage 7: product state gate.
    if product["status"] == "CANCELLED":
        err("ERR_PRODUCT_TERMINAL", "The product is CANCELLED.")
    if product["status"] not in ("REGISTERED", "UNDER_REVIEW"):
        err("ERR_PRODUCT_NOT_REGISTERED", "The product is not REGISTERED or UNDER_REVIEW.")

    # Stage 8: absolute rate cap and endangered-species teeth.
    new_rate = None
    if amendment_type == "NEW_USE":
        new_rate = normalized_payload["use_site"]["max_application_rate_lbs_acre"]
    elif amendment_type == "RATE_CHANGE":
        new_rate = normalized_payload["new_max_application_rate_lbs_acre"]
    if new_rate is not None and new_rate > float(constants.ABSOLUTE_RATE_CAP_LBS_ACRE):
        err(
            "ERR_RATE_EXCEEDS_SAFETY_CAP",
            "The proposed rate exceeds the 8.0 lbs/acre absolute cap.",
        )
    in_effect = [
        b
        for b in store["bulletins"].values()
        if b["product_id"] == product_id and b["status"] == "IN_EFFECT"
    ]
    if amendment_type == "NEW_USE" and any(b["restriction_code"] == "PROHIBITED" for b in in_effect):
        err(
            "ERR_ESA_PROHIBITION_CONFLICT",
            "An IN_EFFECT PROHIBITED bulletin blocks NEW_USE amendments on the product.",
        )
    if new_rate is not None:
        for bulletin in in_effect:
            if (
                bulletin["restriction_code"] == "RATE_CAP"
                and new_rate > bulletin["rate_cap_lbs_acre"]
            ):
                err(
                    "ERR_ESA_PROHIBITION_CONFLICT",
                    "The new rate exceeds an IN_EFFECT RATE_CAP bulletin's cap.",
                )

    # Stage 10: cross-reference integrity.
    if amendment_type in ("RATE_CHANGE", "METHOD_CHANGE"):
        site = store["use_sites"].get(normalized_payload["use_site_id"])
        if site is None or site["product_id"] != product_id:
            err(
                "ERR_USE_SITE_PRODUCT_MISMATCH",
                "The payload's use_site_id does not name a use site of this product.",
            )
    if amendment_type == "NEW_USE" and normalized_payload.get("commodity_code") is not None:
        if normalized_payload["commodity_code"] not in constants.CONSUMPTION_G_DAY:
            err(
                "ERR_UNKNOWN_COMMODITY",
                "Unknown commodity_code %s." % normalized_payload["commodity_code"],
            )

    now = clock.now()
    total_days, halved = amendment_review_days(amendment_type, normalized_payload, product)
    priia_category = amendment_type + ("-EXPEDITED" if halved else "")

    row = new_row()
    row.update(
        {
            "product_id": product_id,
            "registrant_ref": caller["user_id"],
            "amendment_type": amendment_type,
            "payload": normalized_payload,
            "status": "SUBMITTED",
            "priia_category": priia_category,
            "submitted_at": now,
            "review_due_at": now + timedelta(days=total_days),
            "decided_at": None,
        }
    )
    store["amendments"][row["id"]] = row
    # Every successful filing advances the product's version by one (PRD 2.7).
    touch(product)
    return ok(row, status=201)


@bp.get("/label-amendments")
def list_amendments():
    require_auth()
    rows = list(store["amendments"].values())
    for key in ("product_id", "amendment_type", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.get("/label-amendments/<amendment_id>")
def get_amendment(amendment_id):
    require_auth()
    return ok(get_amendment_or_404(amendment_id))


@bp.post("/label-amendments/<amendment_id>/withdraw")
def withdraw_amendment(amendment_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRANT_REPRESENTATIVE])
    data = parse_body()
    reject_unknown(data, ["reason"])
    if "reason" in data and data["reason"] is not None:
        as_str(data, "reason")

    amendment = get_amendment_or_404(amendment_id)
    product = store["products"][amendment["product_id"]]
    if product["registrant_ref"] != caller["user_id"]:
        err("ERR_NOT_RESOURCE_OWNER", "The amendment belongs to another registrant.")
    if amendment["status"] != "SUBMITTED":
        err("ERR_AMENDMENT_NOT_PENDING", "The amendment is not SUBMITTED.")
    amendment["status"] = "WITHDRAWN"
    touch(amendment)
    return ok(amendment)


@bp.post("/label-amendments/<amendment_id>/review-decisions")
def decide_amendment(amendment_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(data, ["decision", "decision_notes"])
    decision = as_enum(data, "decision", ["APPROVE", "REJECT"], required=True)
    if "decision_notes" in data and data["decision_notes"] is not None:
        as_str(data, "decision_notes")

    amendment = get_amendment_or_404(amendment_id)
    product = store["products"][amendment["product_id"]]
    if amendment["status"] != "SUBMITTED":
        err("ERR_AMENDMENT_NOT_PENDING", "The amendment is not SUBMITTED.")
    # The product gate is re-checked at decision time exactly as at filing.
    if product["status"] == "CANCELLED":
        err("ERR_PRODUCT_TERMINAL", "The product is CANCELLED.")
    if product["status"] not in ("REGISTERED", "UNDER_REVIEW"):
        err("ERR_PRODUCT_NOT_REGISTERED", "The product is not REGISTERED or UNDER_REVIEW.")

    now = clock.now()
    amendment["decided_at"] = now
    if data.get("decision_notes") is not None:
        amendment["decision_notes"] = data["decision_notes"]
    if decision == "REJECT":
        amendment["status"] = "REJECTED"
        touch(amendment)
        return ok(amendment)

    amendment["status"] = "APPROVED"
    touch(amendment)
    payload = amendment["payload"]
    if amendment["amendment_type"] == "NEW_USE":
        site_row = new_row()
        site_row.update(payload["use_site"])
        site_row.update(
            {
                "product_id": amendment["product_id"],
                "origin": "AMENDMENT",
                "status": "ACTIVE",
                "pre_removal_status": None,
                "removed_at": None,
            }
        )
        store["use_sites"][site_row["id"]] = site_row
        if payload.get("tolerance_ppm") is not None:
            tol_row = new_row()
            tol_row.update(
                {
                    "product_id": amendment["product_id"],
                    "origin": "AMENDMENT",
                    "commodity_code": payload["commodity_code"],
                    "tolerance_ppm": payload["tolerance_ppm"],
                    "status": "ESTABLISHED",
                    "established_at": now,
                    "revoked_at": None,
                    "pre_revocation_status": None,
                }
            )
            store["tolerances"][tol_row["id"]] = tol_row
    elif amendment["amendment_type"] == "RATE_CHANGE":
        site = store["use_sites"][payload["use_site_id"]]
        site["max_application_rate_lbs_acre"] = payload["new_max_application_rate_lbs_acre"]
        touch(site)
    else:  # METHOD_CHANGE
        site = store["use_sites"][payload["use_site_id"]]
        site["application_method"] = payload["new_application_method"]
        touch(site)
    return ok(amendment)
