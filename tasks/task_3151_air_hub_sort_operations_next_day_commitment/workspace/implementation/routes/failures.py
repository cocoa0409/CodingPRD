"""Service failure and refund claim routes (PRD 3.11, 3.12)."""

from flask import Blueprint, request

import calculations as calc
import services as svc
from auth import body, require_enum, require_int
from errors import (
    ApiError,
    ERR_CARRIER_ATTRIBUTED_NOT_DISPUTABLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REOPEN_POSTURE_BLOCKED,
    ERR_RESOURCE_NOT_FOUND,
)
from response import paginate, success_list, success_object
from serializers import to_dict, to_list
from store import STORE

bp = Blueprint("failures", __name__)

CAUSE_CODES = ("LATE_INBOUND", "SORT_MISS", "WEATHER", "MECHANICAL", "NO_SCAN",
               "BAD_ADDRESS", "REVENUE_PRORATE")
OUTCOMES = ("OPEN", "FINALIZED", "DISPUTED", "VOIDED")


def _hub(failure):
    return STORE.get("hubs", failure["hub_id"])


def _claims_for(failure_id):
    rows = [c for c in STORE.all("claims") if c.get("service_failure_id") == failure_id]
    rows.sort(key=lambda c: (int(c.get("claim_index") or 0),
                             c.get("created_at") or "",
                             c.get("id") or ""))
    return rows


def _rederive(failure, actor_role):
    claims = _claims_for(failure["id"])
    failure["claim_sequence"] = len(claims)
    status = svc.service_failure_status(STORE, failure, len(claims))
    if status is not None:
        failure["status"] = status
        if status in ("FINALIZED", "VOIDED"):
            svc.refresh_failure(STORE, failure)
        else:
            svc.refresh_failure(STORE, failure)
    STORE.touch("failures", failure)


@bp.route("/airhub/failures", methods=["POST"])
def create_failure():
    payload = body()
    hub = STORE.get("hubs", payload.get("hub_id"))
    package = STORE.get("packages", payload.get("package_id"))
    if hub is None or package is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND)
    cause = require_enum(payload, "cause_code", CAUSE_CODES)
    minutes = require_int(payload, "failure_minutes")
    failure = STORE.create("failures", {
        "hub_id": hub["id"],
        "package_id": package["id"],
        "cause_code": cause,
        "attributed_role": calc.ATTRIBUTION[cause],
        "failure_minutes": minutes,
        "refund_eligible": calc.ATTRIBUTION[cause] == "CARRIER",
        "refund_amount_cents": 0,
        "status": "OPEN",
        "claim_sequence": 0,
    })
    svc.refresh_failure(STORE, failure)
    return success_object(to_dict("failures", failure), 201)


@bp.route("/airhub/failures", methods=["GET"])
def list_failures():
    rows = STORE.all("failures")
    args = request.args
    for field in ("hub_id", "package_id", "cause_code", "attributed_role", "status"):
        value = args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    if args.get("service_failure_id"):
        rows = [r for r in rows if r["id"] == args["service_failure_id"]]
    if args.get("refund_eligible") is not None:
        wanted = args["refund_eligible"].lower() in ("true", "1", "yes")
        rows = [r for r in rows if bool(r.get("refund_eligible")) is wanted]
    page, limit, offset, total = paginate(rows, args)
    return success_list(to_list("failures", page), limit, offset, total)


@bp.route("/airhub/failures/<failure_id>", methods=["GET"])
def get_failure(failure_id):
    failure = STORE.get("failures", failure_id)
    return success_object(to_dict("failures", failure))


@bp.route("/airhub/failures/<failure_id>/finalize", methods=["POST"])
def finalize_failure(failure_id):
    failure = STORE.get("failures", failure_id)
    if failure.get("status") != "OPEN":
        raise ApiError(ERR_INVALID_STATE)
    if not failure.get("refund_eligible"):
        raise ApiError(ERR_INVALID_STATE,
                       "Only a refund-eligible failure may be finalized.")
    failure["status"] = "FINALIZED"
    svc.refresh_failure(STORE, failure)
    STORE.touch("failures", failure)
    return success_object(to_dict("failures", failure))


@bp.route("/airhub/failures/<failure_id>/dispute", methods=["POST"])
def dispute_failure(failure_id):
    failure = STORE.get("failures", failure_id)
    if failure.get("status") != "OPEN":
        raise ApiError(ERR_INVALID_STATE)
    if failure.get("attributed_role") == "CARRIER":
        raise ApiError(ERR_CARRIER_ATTRIBUTED_NOT_DISPUTABLE)
    failure["status"] = "DISPUTED"
    svc.refresh_failure(STORE, failure)
    STORE.touch("failures", failure)
    return success_object(to_dict("failures", failure))


@bp.route("/airhub/failures/<failure_id>/reopen", methods=["POST"])
def reopen_failure(failure_id):
    failure = STORE.get("failures", failure_id)
    hub = _hub(failure)
    if failure.get("status") != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE)
    if hub.get("posture") not in ("OPEN", "CONGESTED"):
        raise ApiError(ERR_REOPEN_POSTURE_BLOCKED)
    failure["status"] = "OPEN"
    svc.refresh_failure(STORE, failure)
    STORE.touch("failures", failure)
    return success_object(to_dict("failures", failure))


@bp.route("/airhub/failures/<failure_id>/void", methods=["POST"])
def void_failure(failure_id):
    failure = STORE.get("failures", failure_id)
    hub = _hub(failure)
    if failure.get("status") != "OPEN":
        raise ApiError(ERR_INVALID_STATE)
    if failure.get("attributed_role") != "CARRIER":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a carrier-attributed failure may be voided.")
    failure["status"] = "VOIDED"
    svc.refresh_failure(STORE, failure)
    STORE.touch("failures", failure)
    package = STORE.get("packages", failure.get("package_id"))
    if package is not None and package.get("commitment_status") == "DOWNGRADED":
        package["commitment_status"] = "COMMITTED"
        package["final_commitment_minutes"] = None
        package["service_level"] = _committed_level(package)
        svc.refresh_package_postures(package)
        STORE.touch("packages", package)
        svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("failures", failure))


def _committed_level(package):
    hub = STORE.get("hubs", package["hub_id"])
    close = int(hub["sort_window_close_minutes"]) if hub else 0
    delta = int(package.get("commitment_cutoff_minutes") or close) - close
    if delta >= calc.GROUND_SLIP_MINUTES:
        return "GROUND"
    if delta >= calc.SECOND_DAY_SLIP_MINUTES:
        return "SECOND_DAY_AIR"
    return "NEXT_DAY_AIR"


@bp.route("/airhub/failures/<failure_id>/claims", methods=["POST"])
def append_claim(failure_id):
    failure = STORE.get("failures", failure_id)
    payload = body()
    outcome = require_enum(payload, "outcome", OUTCOMES)
    note = payload.get("note")
    if note is not None and not isinstance(note, str):
        raise ApiError(ERR_INVALID_REQUEST, "note must be a string.")
    actor_role = request.headers.get("X-User-Role")
    index = len(_claims_for(failure["id"])) + 1
    claim = STORE.create("claims", {
        "service_failure_id": failure["id"],
        "claim_index": index,
        "outcome": outcome,
        "actor_role": actor_role,
        "note": note,
    })
    _rederive(failure, actor_role)
    return success_object(to_dict("claims", claim), 201)


@bp.route("/airhub/failures/<failure_id>/claims", methods=["GET"])
def list_failure_claims(failure_id):
    STORE.get("failures", failure_id)
    rows = _claims_for(failure_id)
    if request.args.get("service_failure_id"):
        wanted = request.args["service_failure_id"]
        if wanted != failure_id:
            raise ApiError(ERR_RESOURCE_NOT_FOUND)
        rows = [r for r in rows if r["service_failure_id"] == wanted]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list(to_list("claims", page), limit, offset, total)


@bp.route("/airhub/service-failure-claims", methods=["GET"])
def list_claims():
    rows = STORE.all("claims")
    if request.args.get("service_failure_id"):
        wanted = request.args["service_failure_id"]
        rows = [r for r in rows if r.get("service_failure_id") == wanted]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list(to_list("claims", page), limit, offset, total)


@bp.route("/airhub/service-failure-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    claim = STORE.get("claims", claim_id)
    return success_object(to_dict("claims", claim))