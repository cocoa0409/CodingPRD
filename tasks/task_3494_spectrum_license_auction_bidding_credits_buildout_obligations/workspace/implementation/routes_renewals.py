"""License renewals: filing inside the renewal window and TransferReviewer
adjudication (PRD §3.9)."""
from flask import Blueprint

import store
import calcs
import serializers
import sweeps
from errors import ApiError, success
from helpers import (auth, require_role, body, req_present, as_enum,
                     get_or_404, paginate, touch)

bp = Blueprint("renewals", __name__)


@bp.route("/spectrum-auctions/licenses/<lid>/renewal-applications",
          methods=["POST"])
def file_renewal(lid):
    uid, role = auth()
    require_role(role, ("Bidder",))
    license_ = get_or_404("licenses", lid)
    if uid != license_["holder_applicant_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                       "X-User-ID must equal the license holder")
    if license_["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_INVALID_STATE", 409,
                       "Renewal filing requires an ACTIVE license")
    for other in store.DB["renewals"].values():
        if (other["license_id"] == lid
                and other["status"] in ("FILED", "UNDER_REVIEW")):
            raise ApiError("ERR_RENEWAL_INVALID_STATE", 409,
                           "Another renewal application is already open")
    now = store.now()
    window_start = store.add_days(license_["term_end"],
                                  -calcs.RENEWAL_WINDOW_DAYS)
    if not (window_start <= now <= license_["term_end"]):
        raise ApiError("ERR_RENEWAL_WINDOW_CLOSED", 409,
                       "Renewal filing is outside the renewal window")
    # Filing and review-open are one request: the application passes through
    # FILED into UNDER_REVIEW immediately.
    renewal = store.stamp_new({
        "id": store.new_id(),
        "license_id": lid,
        "status": "UNDER_REVIEW",
    })
    store.DB["renewals"][renewal["id"]] = renewal
    license_["status"] = "RENEWAL_REVIEW"
    touch(license_)
    return success(serializers.renewal(renewal), 201)


@bp.route("/spectrum-auctions/licenses/<lid>/renewal-applications",
          methods=["GET"])
def list_renewals(lid):
    auth()
    get_or_404("licenses", lid)
    items = [r for r in store.DB["renewals"].values()
             if r["license_id"] == lid]
    page, meta = paginate(items)
    return success([serializers.renewal(r) for r in page], 200, meta)


@bp.route("/spectrum-auctions/renewal-applications/<rid>/decide",
          methods=["POST"])
def decide_renewal(rid):
    _, role = auth()
    require_role(role, ("TransferReviewer",))
    b = body()
    decision = as_enum(req_present(b, "decision"), "decision",
                       ("GRANT", "DENY"))
    renewal = get_or_404("renewals", rid)
    if renewal["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_RENEWAL_INVALID_STATE", 409,
                       "Decide requires UNDER_REVIEW")
    license_ = store.DB["licenses"][renewal["license_id"]]
    if decision == "GRANT":
        renewal["status"] = "GRANTED"
        touch(renewal)
        license_["status"] = "ACTIVE"
        license_["term_end"] = store.add_days(license_["term_end"],
                                              calcs.RENEWAL_EXTENSION_DAYS)
        touch(license_)
    else:
        renewal["status"] = "DENIED"
        touch(renewal)
        sweeps.terminate_license(license_)
    return success(serializers.renewal(renewal), 200)
