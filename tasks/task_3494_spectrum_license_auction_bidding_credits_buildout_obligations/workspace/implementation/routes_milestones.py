"""Buildout milestones: listing, coverage filings (OCC), and admin review
(PRD §3.8)."""
from flask import Blueprint

import store
import serializers
from errors import ApiError, success
from helpers import (auth, require_role, body, req_present, as_int, as_enum,
                     get_or_404, paginate, touch, check_occ)

bp = Blueprint("milestones", __name__)


@bp.route("/spectrum-auctions/licenses/<lid>/buildout-milestones",
          methods=["GET"])
def list_milestones(lid):
    auth()
    get_or_404("licenses", lid)
    items = [m for m in store.DB["milestones"].values()
             if m["license_id"] == lid]
    page, meta = paginate(items)  # created_at ASC; grant creates INTERIM
    # before FINAL, and the creation sequence preserves that order.
    return success([serializers.milestone(m) for m in page], 200, meta)


@bp.route("/spectrum-auctions/buildout-milestones/<mid>/file-notice",
          methods=["POST"])
def file_notice(mid):
    uid, role = auth()
    require_role(role, ("Bidder",))
    b = body()
    covered = as_int(req_present(b, "covered_population"),
                     "covered_population", minimum=0)
    expected = req_present(b, "expected_milestone_version")
    as_int(expected, "expected_milestone_version")
    ms = get_or_404("milestones", mid)
    license_ = store.DB["licenses"][ms["license_id"]]
    if uid != license_["holder_applicant_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                       "X-User-ID must equal the license holder")
    if ms["status"] not in ("PENDING", "REJECTED"):
        raise ApiError("ERR_MILESTONE_INVALID_STATE", 409,
                       "Filing requires PENDING or REJECTED")
    check_occ(ms, expected, "expected_milestone_version")
    if license_["status"] not in ("ACTIVE", "RENEWAL_REVIEW"):
        raise ApiError("ERR_LICENSE_INVALID_STATE", 409,
                       "Filing requires the license to be ACTIVE or "
                       "RENEWAL_REVIEW")
    ms["covered_population"] = covered
    ms["status"] = "FILED"
    touch(ms)
    return success(serializers.milestone(ms), 200)


@bp.route("/spectrum-auctions/buildout-milestones/<mid>/review",
          methods=["POST"])
def review_milestone(mid):
    _, role = auth()
    require_role(role, ("AuctionAdmin",))
    b = body()
    decision = as_enum(req_present(b, "decision"), "decision",
                       ("ACCEPT", "REJECT"))
    ms = get_or_404("milestones", mid)
    if ms["status"] != "FILED":
        raise ApiError("ERR_MILESTONE_INVALID_STATE", 409,
                       "Review requires FILED")
    if decision == "ACCEPT":
        license_ = store.DB["licenses"][ms["license_id"]]
        area = store.DB["areas"][license_["area_id"]]
        # Integer cross-multiplication, inclusive boundary: exactly the
        # required percentage passes.
        if ms["covered_population"] * 100 < (ms["required_coverage_pct"]
                                             * area["population"]):
            raise ApiError("ERR_COVERAGE_BELOW_REQUIREMENT", 422,
                           "Certified coverage is below the requirement")
        ms["status"] = "ACCEPTED"
    else:
        ms["status"] = "REJECTED"
    touch(ms)
    return success(serializers.milestone(ms), 200)
