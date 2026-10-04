"""Secondary-market transfers and leases (PRD §3.9)."""
from flask import Blueprint

import store
import calcs
import serializers
from errors import ApiError, success
from helpers import (auth, require_role, body, req_present, as_str, as_enum,
                     as_datetime, get_or_404, paginate, touch)

bp = Blueprint("transfers", __name__)

REVIEW_ACTIONS = ("BEGIN_REVIEW", "REQUEST_INFO", "PROVIDE_INFO", "APPROVE",
                  "DENY")
REVIEWER_ACTIONS = ("BEGIN_REVIEW", "REQUEST_INFO", "APPROVE", "DENY")


@bp.route("/spectrum-auctions/licenses/<lid>/transfer-applications",
          methods=["POST"])
def file_transfer(lid):
    uid, role = auth()
    require_role(role, ("Bidder",))
    b = body()
    transfer_type = as_enum(req_present(b, "transfer_type"), "transfer_type",
                            ("FULL_ASSIGNMENT", "LEASE"))
    transferee_id = as_str(req_present(b, "transferee_applicant_id"),
                           "transferee_applicant_id")
    lease_start = lease_end = None
    if transfer_type == "LEASE":
        lease_start = as_datetime(req_present(b, "lease_start"), "lease_start")
        lease_end = as_datetime(req_present(b, "lease_end"), "lease_end")
    license_ = get_or_404("licenses", lid)
    transferee = get_or_404("applicants", transferee_id)
    if uid != license_["holder_applicant_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                       "X-User-ID must equal the license holder")
    if license_["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_INVALID_STATE", 409,
                       "Transfer filing requires an ACTIVE license")
    if transfer_type == "LEASE":
        if lease_end <= lease_start:
            raise ApiError("ERR_LEASE_DATES_INVALID", 422,
                           "lease_end must be strictly after lease_start")
        # Half-open [start, end) overlap against ALL approved lease windows
        # of this license; touching endpoints are allowed.
        for other in store.DB["transfers"].values():
            if (other["license_id"] == lid
                    and other["transfer_type"] == "LEASE"
                    and other["status"] == "APPROVED"):
                if (lease_start < other["lease_end"]
                        and other["lease_start"] < lease_end):
                    raise ApiError("ERR_LEASE_WINDOW_OVERLAP", 409,
                                   "The lease window overlaps an approved "
                                   "lease on this license")
    unjust = calcs.unjust_enrichment(license_, transferee, store.now())
    tr = store.stamp_new({
        "id": store.new_id(),
        "license_id": lid,
        "transferor_applicant_id": uid,
        "transferee_applicant_id": transferee_id,
        "transfer_type": transfer_type,
        "lease_start": lease_start,
        "lease_end": lease_end,
        "unjust_enrichment_cents": unjust,
        "status": "FILED",
    })
    store.DB["transfers"][tr["id"]] = tr
    return success(serializers.transfer(tr), 201)


@bp.route("/spectrum-auctions/licenses/<lid>/transfer-applications",
          methods=["GET"])
def list_license_transfers(lid):
    auth()
    get_or_404("licenses", lid)
    items = [t for t in store.DB["transfers"].values()
             if t["license_id"] == lid]
    page, meta = paginate(items)
    return success([serializers.transfer(t) for t in page], 200, meta)


@bp.route("/spectrum-auctions/applicants/<aid>/transfer-applications",
          methods=["GET"])
def list_applicant_transfers(aid):
    auth()
    get_or_404("applicants", aid)
    items = [t for t in store.DB["transfers"].values()
             if t["transferor_applicant_id"] == aid
             or t["transferee_applicant_id"] == aid]
    page, meta = paginate(items)
    return success([serializers.transfer(t) for t in page], 200, meta)


@bp.route("/spectrum-auctions/transfer-applications/<tid>", methods=["GET"])
def get_transfer(tid):
    auth()
    return success(serializers.transfer(get_or_404("transfers", tid)), 200)


@bp.route("/spectrum-auctions/transfer-applications/<tid>/review",
          methods=["POST"])
def review_transfer(tid):
    uid, role = auth()
    require_role(role, ("TransferReviewer", "Bidder"))
    b = body()
    action = as_enum(req_present(b, "action"), "action", REVIEW_ACTIONS)
    # Per-action authorization: adjudication actions are TransferReviewer
    # only; PROVIDE_INFO is the transferor's (Bidder) only action.
    if action in REVIEWER_ACTIONS and role != "TransferReviewer":
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "Action %s requires TransferReviewer" % action)
    if action == "PROVIDE_INFO" and role != "Bidder":
        raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                       "Action PROVIDE_INFO requires Bidder")
    tr = get_or_404("transfers", tid)

    def bad_state():
        raise ApiError("ERR_TRANSFER_INVALID_STATE", 409,
                       "Transfer transition %s is not available from %s"
                       % (action, tr["status"]))

    if action == "PROVIDE_INFO":
        if uid != tr["transferor_applicant_id"]:
            raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                           "Only the transferor may provide information")
        if tr["status"] != "INFO_REQUESTED":
            bad_state()
        tr["status"] = "UNDER_REVIEW"
        touch(tr)
    elif action == "BEGIN_REVIEW":
        if tr["status"] != "FILED":
            bad_state()
        tr["status"] = "UNDER_REVIEW"
        touch(tr)
    elif action == "REQUEST_INFO":
        if tr["status"] != "UNDER_REVIEW":
            bad_state()
        tr["status"] = "INFO_REQUESTED"
        touch(tr)
    elif action == "APPROVE":
        if tr["status"] != "UNDER_REVIEW":
            bad_state()
        license_ = store.DB["licenses"][tr["license_id"]]
        if license_["status"] not in ("ACTIVE", "RENEWAL_REVIEW"):
            raise ApiError("ERR_LICENSE_INVALID_STATE", 409,
                           "Approval requires the license to be ACTIVE or "
                           "RENEWAL_REVIEW")
        if (tr["unjust_enrichment_cents"] > 0
                and b.get("confirm_unjust_enrichment_repayment") is not True):
            raise ApiError("ERR_UNJUST_ENRICHMENT_CONFIRMATION_REQUIRED", 422,
                           "Approval requires "
                           "confirm_unjust_enrichment_repayment: true")
        tr["status"] = "APPROVED"
        touch(tr)
        if tr["transfer_type"] == "FULL_ASSIGNMENT":
            license_["holder_applicant_id"] = tr["transferee_applicant_id"]
            touch(license_)
        else:
            # A window containing the current logical instant activates
            # immediately; a future window is activated by the clock sweep.
            now = store.now()
            if tr["lease_start"] <= now < tr["lease_end"]:
                license_["active_lease_start"] = tr["lease_start"]
                license_["active_lease_end"] = tr["lease_end"]
                license_["leased_to_applicant_id"] = (
                    tr["transferee_applicant_id"])
                touch(license_)
    else:  # DENY
        if tr["status"] != "UNDER_REVIEW":
            bad_state()
        tr["status"] = "DENIED"
        touch(tr)
    return success(serializers.transfer(tr), 200)


@bp.route("/spectrum-auctions/transfer-applications/<tid>/withdraw",
          methods=["POST"])
def withdraw_transfer(tid):
    uid, role = auth()
    require_role(role, ("Bidder",))
    tr = get_or_404("transfers", tid)
    if uid != tr["transferor_applicant_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                       "Only the transferor may withdraw")
    if tr["status"] not in ("FILED", "INFO_REQUESTED"):
        raise ApiError("ERR_TRANSFER_INVALID_STATE", 409,
                       "Withdrawal requires FILED or INFO_REQUESTED")
    tr["status"] = "WITHDRAWN"
    touch(tr)
    return success(serializers.transfer(tr), 200)
