"""Payment determinations: re-pricing, finalization and voiding (PRD 3.7)."""

from flask import Blueprint

import auth
import lookup
import serialize
import validate
from envelope import array_response, object_response
from errors import ApiError
from routes.stays import require_open_period, stay_period
from services import pricing, scoring
from store import db, sorted_rows_desc, touch

bp = Blueprint("payments", __name__)

CO = auth.ROLE_COMPLIANCE_OFFICER
IC = auth.ROLE_INTAKE_COORDINATOR
URN = auth.ROLE_UR_NURSE
RIA = auth.ROLE_REVENUE_ANALYST

DETERMINATION_STATUSES = ("DRAFT", "FINAL", "VOIDED")
RESOLVED_REVIEW_STATUSES = ("CLEARED", "ESCALATED")


def _rescore_stay_review(stay):
    review = lookup.stay_live_review(stay["id"])
    if review is not None:
        scoring.apply_scores(review)
    return review


@bp.route("/stays/<stay_id>/payment-determinations", methods=["POST"])
def create_determination(stay_id):
    body = validate.get_body()
    expected_stay_version = validate.req_int(body, "expected_stay_version")
    recalculation_reason = validate.req_str(body, "recalculation_reason", 1, 500)
    override_drg_rate_id = validate.opt_str(body, "override_drg_rate_id", 1, None)
    auth.require_role(RIA)
    stay = lookup.stay(stay_id)

    if override_drg_rate_id is not None:
        lookup.drg_rate(override_drg_rate_id)

    if expected_stay_version != stay["version"]:
        raise ApiError("ERR_STALE_STAY_VERSION",
                       "expected_stay_version does not match the stay's current version.")

    if stay["clinical_status"] != "DISCHARGED":
        raise ApiError("ERR_INVALID_STATE", "Only a DISCHARGED stay may be priced.")
    require_open_period(stay)

    live = lookup.stay_live_determination(stay["id"])
    if live is not None and live["status"] == "FINAL":
        raise ApiError("ERR_DETERMINATION_EXISTS",
                       "The stay already holds a FINAL payment determination.")
    if live is not None and live["status"] == "DRAFT":
        live["status"] = "VOIDED"
        live["void_reason"] = "SUPERSEDED"
        touch(live)

    drg = pricing.drg_in_force(stay, override_drg_rate_id)
    determination = pricing.create_determination(stay, drg, auth.acting_user_id(),
                                                 recalculation_reason)
    touch(stay)
    _rescore_stay_review(stay)
    return object_response(serialize.determination(determination), 201)


@bp.route("/stays/<stay_id>/payment-determinations", methods=["GET"])
def list_stay_determinations(stay_id):
    auth.require_role(RIA, CO, IC, URN)
    stay = lookup.stay(stay_id)
    limit, offset = validate.pagination()
    status = validate.query_enum("status", DETERMINATION_STATUSES)

    rows = lookup.stay_determinations(stay["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_rows_desc(rows)
    page = lookup.page(rows, limit, offset)
    return array_response([serialize.determination(r) for r in page], limit, offset, len(rows))


@bp.route("/payment-determinations/<determination_id>", methods=["GET"])
def get_determination(determination_id):
    auth.require_role(*auth.ALL_ROLES)
    return object_response(serialize.determination(lookup.determination(determination_id)))


@bp.route("/payment-determinations/<determination_id>/finalize", methods=["POST"])
def finalize_determination(determination_id):
    validate.get_body()
    auth.require_role(RIA)
    determination = lookup.determination(determination_id)
    stay = db.stays[determination["stay_id"]]

    if determination["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT determination may be finalized.")
    if stay["clinical_status"] != "DISCHARGED":
        raise ApiError("ERR_INVALID_STATE", "The determination's stay is not DISCHARGED.")
    period = require_open_period(stay)

    review = lookup.stay_live_review(stay["id"])
    if review is None or review["status"] not in RESOLVED_REVIEW_STATUSES:
        raise ApiError("ERR_REVIEW_NOT_RESOLVED",
                       "The stay's denial-risk review is not resolved.")
    if scoring.has_issued_query(review):
        raise ApiError("ERR_OPEN_QUERIES_BLOCK_FINALIZE",
                       "A documentation query on the stay's review is still ISSUED.")

    actor = auth.acting_user_id()
    if actor == determination["priced_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The analyst finalizing a determination must differ from the one who priced it.")

    determination["status"] = "FINAL"
    determination["finalized_by_user_id"] = actor
    touch(determination)

    stay["payment_review_status"] = "FINALIZED"
    touch(stay)

    if period is not None:
        period["total_payment_cents"] += determination["total_payment_cents"]
        period["final_determination_count"] += 1
        touch(period)

    return object_response(serialize.determination(determination))


@bp.route("/payment-determinations/<determination_id>/void", methods=["POST"])
def void_determination(determination_id):
    body = validate.get_body()
    void_reason = validate.req_str(body, "void_reason", 1, 500)
    auth.require_role(RIA)
    determination = lookup.determination(determination_id)
    stay = db.stays[determination["stay_id"]]

    if determination["status"] not in ("DRAFT", "FINAL"):
        raise ApiError("ERR_INVALID_STATE", "The determination is already VOIDED.")
    period = require_open_period(stay)

    actor = auth.acting_user_id()
    was_final = determination["status"] == "FINAL"
    if was_final and actor == determination["finalized_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The analyst voiding a FINAL determination must differ from the one who "
                       "finalized it.")

    determination["status"] = "VOIDED"
    determination["void_reason"] = void_reason
    touch(determination)

    if was_final and period is not None:
        period["total_payment_cents"] -= determination["total_payment_cents"]
        period["final_determination_count"] -= 1
        touch(period)

    if lookup.stay_live_determination(stay["id"]) is None:
        stay["payment_review_status"] = "PENDING"
        stay["discharge_payment_pct"] = None
        touch(stay)

    return object_response(serialize.determination(determination))
