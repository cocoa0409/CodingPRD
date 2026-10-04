"""QualityClaim and CollectorComplaint resources.

Quality claims feed the print-run safety floor and the recall cascade; collector
complaints feed the SALES_HISTORY projection authority and are approved against
the set's availability authority (PRD 3.7).
"""

import datetime

import calc
import db
import requtil
import response
from core import app
from common import license_of_card_set, serialize
from constants import (
    BREACH_REASONS,
    CLAIM_TYPES,
    CLAIM_BACKDATE_WINDOW_DAYS,
    SEVERITIES,
)
from errors import (
    ApiError,
    ERR_CLAIM_BACKDATE_EXCEEDED,
    ERR_CLAIM_QUANTITY_INVALID,
    ERR_COLLECTOR_COMPLAINT_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_QUALITY_CLAIM_NOT_APPROVED,
    ERR_QUALITY_CLAIM_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_REPLACEMENT_POLICY_EXISTS,
    ERR_UNDISCLOSED_RUN_DECLARED,
)
from flask import jsonify, request
from middleware import authenticate, require_role

CLAIM_READ_ROLES = ["QualityAnalyst", "ProductionPlanner", "PlatformAdmin"]
COMPLAINT_READ_ROLES = ["CollectorSupportSpecialist", "QualityAnalyst", "PlatformAdmin"]


def _get_claim(claim_id):
    rec = db.STORE.get("quality_claims", claim_id)
    if rec is None:
        raise ApiError(
            ERR_QUALITY_CLAIM_NOT_FOUND,
            "No QualityClaim exists with id %s" % claim_id,
        )
    return rec


def _get_complaint(complaint_id):
    rec = db.STORE.get("collector_complaints", complaint_id)
    if rec is None:
        raise ApiError(
            ERR_COLLECTOR_COMPLAINT_NOT_FOUND,
            "No CollectorComplaint exists with id %s" % complaint_id,
        )
    return rec


def _claim_count(store, card_set_id):
    return sum(1 for q in store.all("quality_claims") if q["card_set_id"] == card_set_id)


def _refresh_claim_count(store, card_set_id, now):
    card_set = store.get("card_sets", card_set_id)
    if card_set is None:
        return
    card_set["quality_claim_count"] = _claim_count(store, card_set_id)
    db.touch(card_set, now)


def _refresh_settled_complaints(store, card_set_id, now):
    card_set = store.get("card_sets", card_set_id)
    if card_set is None:
        return
    card_set["settled_complaint_count"] = sum(
        1
        for c in store.all("collector_complaints")
        if c["card_set_id"] == card_set_id and c["status"] == "APPROVED"
    )
    db.touch(card_set, now)


def _refresh_outstanding(store, card_set_id, now):
    card_set = store.get("card_sets", card_set_id)
    if card_set is None:
        return
    card_set["autograph_redemptions_outstanding"] = sum(
        1
        for r in store.all("redemptions")
        if r["card_set_id"] == card_set_id and r["status"] in ("ISSUED", "FULFILLED")
    )
    db.touch(card_set, now)


# ---------------------------------------------------------------------------
# QualityClaim
# ---------------------------------------------------------------------------

@app.route("/api/card-sets/<card_set_id>/quality-claims", methods=["POST"])
def create_quality_claim(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["QualityAnalyst"])

    data = requtil.body()
    claim_type = requtil.required_enum(data, "claim_type", CLAIM_TYPES)
    severity = requtil.required_enum(data, "severity", SEVERITIES)
    affected_quantity = requtil.required_int(data, "affected_quantity")
    filed_on = requtil.required_dt(data, "filed_on")

    store = db.STORE
    if not store.exists("card_sets", card_set_id):
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "card_set_id %s does not resolve" % card_set_id
        )

    now = store.now()
    rec = db.record("quality_claims", {
        "card_set_id": card_set_id,
        "claim_type": claim_type,
        "severity": severity,
        "affected_quantity": affected_quantity,
        "filed_on": filed_on,
        "status": "FILED",
        "claim_weight": calc.quality_claim_weight(severity),
    }, now)
    store.insert("quality_claims", rec)
    _refresh_claim_count(store, card_set_id, now)
    return jsonify(response.ok_object(serialize("quality_claims", rec))), 201


@app.route("/api/card-sets/<card_set_id>/quality-claims", methods=["GET"])
def list_set_claims(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["QualityAnalyst", "CollectorSupportSpecialist", "PlatformAdmin"])
    if not db.STORE.exists("card_sets", card_set_id):
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "card_set_id %s does not resolve" % card_set_id
        )
    return _list_claims({"card_set_id": card_set_id})


@app.route("/api/quality-claims", methods=["GET"])
def list_claims():
    principal = authenticate(request.headers)
    require_role(principal, CLAIM_READ_ROLES)
    return _list_claims({})


def _list_claims(fixed):
    store = db.STORE
    items = list(store.all("quality_claims"))
    card_set_id = fixed.get("card_set_id") or requtil.filter_value("card_set_id")
    status = requtil.filter_value("status")
    severity = requtil.filter_value("severity")
    if card_set_id is not None:
        items = [q for q in items if q["card_set_id"] == card_set_id]
    if status is not None:
        items = [q for q in items if q["status"] == status]
    if severity is not None:
        items = [q for q in items if q["severity"] == severity]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(
        response.paginate([serialize("quality_claims", q) for q in items], request.args)
    ), 200


@app.route("/api/quality-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    principal = authenticate(request.headers)
    require_role(principal, CLAIM_READ_ROLES)
    return jsonify(response.ok_object(serialize("quality_claims", _get_claim(claim_id)))), 200


@app.route("/api/quality-claims/<claim_id>/open-review", methods=["POST"])
def open_claim_review(claim_id):
    principal = authenticate(request.headers)
    require_role(principal, ["QualityAnalyst"])

    store = db.STORE
    now = store.now()
    rec = _get_claim(claim_id)

    # Strict comparison: filed_on must be strictly after now - 30 days.
    lower = now - datetime.timedelta(days=CLAIM_BACKDATE_WINDOW_DAYS)
    if not rec["filed_on"] > lower:
        raise ApiError(
            ERR_CLAIM_BACKDATE_EXCEEDED,
            "The claim is back-dated beyond the evidence window",
        )
    if rec["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, "Quality claim is not FILED")

    rec["status"] = "UNDER_REVIEW"
    db.bump(rec, now)
    _refresh_claim_count(store, rec["card_set_id"], now)
    return jsonify(response.ok_object(serialize("quality_claims", rec))), 200


@app.route("/api/quality-claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    principal = authenticate(request.headers)
    require_role(principal, ["QualityAnalyst"])

    store = db.STORE
    now = store.now()
    rec = _get_claim(claim_id)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Quality claim is not UNDER_REVIEW")
    if rec["affected_quantity"] < 1:
        raise ApiError(
            ERR_CLAIM_QUANTITY_INVALID, "affected_quantity must be at least 1"
        )

    rec["status"] = "APPROVED"
    rec["claim_weight"] = calc.quality_claim_weight(rec["severity"])
    db.bump(rec, now)
    return jsonify(response.ok_object(serialize("quality_claims", rec))), 200


@app.route("/api/quality-claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    principal = authenticate(request.headers)
    require_role(principal, ["QualityAnalyst"])

    store = db.STORE
    now = store.now()
    rec = _get_claim(claim_id)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Quality claim is not UNDER_REVIEW")

    rec["status"] = "DENIED"
    db.bump(rec, now)
    return jsonify(response.ok_object(serialize("quality_claims", rec))), 200


@app.route("/api/quality-claims/<claim_id>/credit", methods=["POST"])
def credit_claim(claim_id):
    principal = authenticate(request.headers)
    require_role(principal, ["QualityAnalyst"])

    store = db.STORE
    now = store.now()
    rec = _get_claim(claim_id)
    if rec["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Quality claim is not APPROVED")

    rec["status"] = "CREDITED"
    db.bump(rec, now)

    card_set_id = rec["card_set_id"]

    # Every FULFILLED redemption for this set is returned to ISSUED with its
    # scratch value restored, and the set's version is advanced by one.
    for redemption in store.all("redemptions"):
        if redemption["card_set_id"] != card_set_id:
            continue
        if redemption["status"] != "FULFILLED":
            continue
        if "_scratch_before_cancel" in redemption and redemption.get(
            "_restore_scratch"
        ):
            redemption["estimated_value_cents"] = redemption["_scratch_before_cancel"]
        redemption["status"] = "ISSUED"
        db.bump(redemption, now)

    _refresh_outstanding(store, card_set_id, now)

    card_set = store.get("card_sets", card_set_id)
    if card_set is not None:
        db.bump(card_set, now)
    return jsonify(response.ok_object(serialize("quality_claims", rec))), 200


# ---------------------------------------------------------------------------
# CollectorComplaint
# ---------------------------------------------------------------------------

@app.route("/api/card-sets/<card_set_id>/complaints", methods=["POST"])
def create_complaint(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["CollectorSupportSpecialist"])

    data = requtil.body()
    complaint_label = requtil.required_str(data, "complaint_label")
    breach_reason = requtil.required_enum(data, "breach_reason", BREACH_REASONS)
    claim_quantity = requtil.required_int(data, "claim_quantity")

    store = db.STORE
    if not store.exists("card_sets", card_set_id):
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "card_set_id %s does not resolve" % card_set_id
        )

    now = store.now()
    rec = db.record("collector_complaints", {
        "card_set_id": card_set_id,
        "complaint_label": complaint_label,
        "breach_reason": breach_reason,
        "claim_quantity": claim_quantity,
        # The SALES_HISTORY projection counts complaints whose filed_on lies in
        # the back-date window, but the scaffold gives a collector complaint no
        # filed_on input field.  Its filing instant is therefore its creation
        # time, stamped from the logical clock.
        "filed_on": now,
        "status": "OPEN",
    }, now)
    store.insert("collector_complaints", rec)
    return jsonify(response.ok_object(serialize("collector_complaints", rec))), 201


@app.route("/api/card-sets/<card_set_id>/complaints", methods=["GET"])
def list_set_complaints(card_set_id):
    principal = authenticate(request.headers)
    require_role(
        principal, ["CollectorSupportSpecialist", "QualityAnalyst", "PlatformAdmin"]
    )
    if not db.STORE.exists("card_sets", card_set_id):
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "card_set_id %s does not resolve" % card_set_id
        )
    return _list_complaints({"card_set_id": card_set_id})


@app.route("/api/collector-complaints", methods=["GET"])
def list_complaints():
    principal = authenticate(request.headers)
    require_role(principal, COMPLAINT_READ_ROLES)
    return _list_complaints({})


def _list_complaints(fixed):
    store = db.STORE
    items = list(store.all("collector_complaints"))
    card_set_id = fixed.get("card_set_id") or requtil.filter_value("card_set_id")
    status = requtil.filter_value("status")
    breach_reason = requtil.filter_value("breach_reason")
    if card_set_id is not None:
        items = [c for c in items if c["card_set_id"] == card_set_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if breach_reason is not None:
        items = [c for c in items if c["breach_reason"] == breach_reason]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(
        response.paginate(
            [serialize("collector_complaints", c) for c in items], request.args
        )
    ), 200


@app.route("/api/collector-complaints/<complaint_id>", methods=["GET"])
def get_complaint(complaint_id):
    principal = authenticate(request.headers)
    require_role(principal, COMPLAINT_READ_ROLES)
    return jsonify(
        response.ok_object(serialize("collector_complaints", _get_complaint(complaint_id)))
    ), 200


@app.route("/api/collector-complaints/<complaint_id>/start-review", methods=["POST"])
def start_complaint_review(complaint_id):
    principal = authenticate(request.headers)
    require_role(principal, ["CollectorSupportSpecialist"])

    store = db.STORE
    now = store.now()
    rec = _get_complaint(complaint_id)
    if rec["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Collector complaint is not OPEN")

    rec["status"] = "UNDER_REVIEW"
    db.bump(rec, now)
    return jsonify(response.ok_object(serialize("collector_complaints", rec))), 200


@app.route("/api/collector-complaints/<complaint_id>/approve", methods=["POST"])
def approve_complaint(complaint_id):
    principal = authenticate(request.headers)
    require_role(principal, ["CollectorSupportSpecialist"])

    store = db.STORE
    now = store.now()
    rec = _get_complaint(complaint_id)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Collector complaint is not UNDER_REVIEW")

    card_set = store.get("card_sets", rec["card_set_id"])
    if card_set is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "The referenced card set does not resolve")

    # The two breach reasons are tested completely differently.
    if rec["breach_reason"] == "UNDISCLOSED_PRINT_RUN":
        current = _compound_status(store, card_set)
        if current != "UNDISCLOSED":
            raise ApiError(
                ERR_UNDISCLOSED_RUN_DECLARED,
                "The set's print run was in fact DISCLOSED",
            )
    elif rec["breach_reason"] == "NO_REPLACEMENT_POLICY":
        if _claim_count(store, card_set["id"]) != 0:
            raise ApiError(
                ERR_REPLACEMENT_POLICY_EXISTS,
                "The set already carries quality claims, so it does have a replacement policy",
            )

    if rec["claim_quantity"] < 1:
        raise ApiError(ERR_CLAIM_QUANTITY_INVALID, "claim_quantity must be at least 1")

    rec["status"] = "APPROVED"
    db.bump(rec, now)
    _refresh_settled_complaints(store, rec["card_set_id"], now)
    return jsonify(response.ok_object(serialize("collector_complaints", rec))), 200


def _compound_status(store, card_set):
    from common import derive_print_run_status

    return derive_print_run_status(store, card_set)


@app.route("/api/collector-complaints/<complaint_id>/reject", methods=["POST"])
def reject_complaint(complaint_id):
    principal = authenticate(request.headers)
    require_role(principal, ["CollectorSupportSpecialist"])

    store = db.STORE
    now = store.now()
    rec = _get_complaint(complaint_id)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Collector complaint is not UNDER_REVIEW")

    rec["status"] = "REJECTED"
    db.bump(rec, now)
    return jsonify(response.ok_object(serialize("collector_complaints", rec))), 200


@app.route("/api/collector-complaints/<complaint_id>/settle", methods=["POST"])
def settle_complaint(complaint_id):
    principal = authenticate(request.headers)
    require_role(principal, ["CollectorSupportSpecialist"])

    store = db.STORE
    now = store.now()
    rec = _get_complaint(complaint_id)
    if rec["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Collector complaint is not APPROVED")

    rec["status"] = "SETTLED"
    db.bump(rec, now)
    return jsonify(response.ok_object(serialize("collector_complaints", rec))), 200