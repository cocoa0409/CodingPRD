"""Consumer enrollment, reads, the credit-health view and account closure."""

from flask import Blueprint, request

import store
import models
import helpers
from auth import require
from envelope import ok, ok_list, limited
from errors import fail

bp = Blueprint("consumers", __name__)

READ_ROLES = ["Consumer", "Referee", "ComplianceOfficer", "PlatformAdmin",
              "DataProtectionOfficer"]


def _scope(cid, uid, role):
    if role == "Consumer" and not helpers.identity_matches(cid, uid):
        fail("ERR_CONSUMER_NOT_FOUND", "No consumer resolves to this identifier.")
    return helpers.consumer(cid)


@bp.route("/consumers", methods=["POST"])
def enroll():
    uid, role = require(["Consumer"])
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    for field in ("full_name", "email", "state_code", "bureau_pin", "dti_pct"):
        if data.get(field) in (None, ""):
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    email = str(data["email"])
    for row in store.consumers.values():
        if row["email"] == email:
            fail("ERR_INVALID_REQUEST", "email must be unique across consumers.")
    state = str(data["state_code"])
    if len(state) != 2:
        fail("ERR_INVALID_REQUEST", "state_code must be a two-letter code.")
    try:
        dti = float(data["dti_pct"])
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "dti_pct must be numeric.")
    row = store.make_row({
        "full_name": str(data["full_name"]),
        "email": email,
        "state_code": state.upper(),
        "bureau_pin": str(data["bureau_pin"]),
        "dti_pct": dti,
        "monitoring_consent_at": None,
        "monitoring_posture": "ENROLLED",
        "status": "ACTIVE",
        "archive_status": "LIVE",
        "score_version": 0,
        "current_score": None,
        "previous_score": None,
        "utilization_pct": None,
        "open_dispute_count": 0,
        "_owner_uid": uid,
    })
    store.consumers[row["id"]] = row
    return ok(models.consumer(row), store.now(), 201)


@bp.route("/consumers", methods=["GET"])
def list_consumers():
    require(READ_ROLES)
    rows = list(store.consumers.values())
    state = request.args.get("state_code")
    if state:
        rows = [r for r in rows if r["state_code"] == state.upper()]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.consumer(r) for r in window], store.now(), pagination)


@bp.route("/consumers/<cid>", methods=["GET"])
def get_consumer(cid):
    uid, role = require(READ_ROLES)
    row = _scope(cid, uid, role)
    return ok(models.consumer(row), store.now())


def _education_topics(cid):
    return sorted({str(d["inaccuracy_type"]).lower()
                   for d in store.dispute_referrals.values()
                   if d["consumer_id"] == cid
                   and d["status"] in ("SUBMITTED_OFFLINE", "ACKNOWLEDGED_BY_BUREAU")})


def _volatility(cid):
    rows = [s for s in helpers.consumer_snapshots(cid)
            if s["status"] in ("ACTIVE", "SUPERSEDED")]
    rows.sort(key=lambda s: s["snapshot_ordinal"])
    deltas = [rows[i]["score"] - rows[i - 1]["score"] for i in range(1, len(rows))]
    volatility = (max(deltas) - min(deltas)) if len(deltas) >= 2 else 0
    drift = (rows[-1]["score"] - rows[0]["score"]) if rows else 0
    return volatility, drift, (rows[-1] if rows else None)


@bp.route("/consumers/<cid>/adverse-action-summary", methods=["GET"])
def adverse_action_summary(cid):
    uid, role = require(["Consumer", "ComplianceOfficer", "PlatformAdmin"])
    row = _scope(cid, uid, role)
    volatility, drift, latest = _volatility(cid)
    tier_code = None
    if latest is not None and row.get("current_score") is not None:
        import simulation as _sim
        tier_code = _sim.lookup_tier_raw(row["current_score"])
    factors = list(latest["factor_codes"]) if latest is not None else []
    payload = {
        "consumer_id": row["id"],
        "current_score": row.get("current_score"),
        "previous_score": row.get("previous_score"),
        "volatility_points": volatility,
        "drift_points": drift,
        "tier_code": tier_code,
        "factor_codes": factors,
        "open_dispute_count": helpers.open_dispute_count(row["id"]),
        "education_topics_consumed": _education_topics(row["id"]),
    }
    return ok(payload, store.now())


@bp.route("/consumers/<cid>/close", methods=["POST"])
def close_consumer(cid):
    require(["DataProtectionOfficer"])
    row = helpers.consumer(cid)
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE consumer may be closed.")
    for ref in store.referrals.values():
        if ref["consumer_id"] == cid and ref["status"] not in (
                "FUNDED", "REVERSED", "DECLINED", "UNFUNDED"):
            fail("ERR_CONSUMER_HAS_OPEN_REFERRAL")
    for dec in store.pre_qual_decisions.values():
        if dec["consumer_id"] == cid and dec["decision_status"] in (
                "ELIGIBLE", "PREQUALIFIED", "NEEDS_SNAPSHOT", "INELIGIBLE"):
            fail("ERR_CONSUMER_HAS_OPEN_DECISION")
    moment = store.now()
    row["status"] = "CLOSED"
    row["archive_status"] = "ARCHIVED"
    for con in store.consent_records.values():
        if con["consumer_id"] == cid and con["status"] in ("PENDING", "SEALED"):
            con["status"] = "NOT_SEALED"
            con["consumer_pii_ciphertext"] = None
            con["updated_at"] = moment
    for snap in store.bureau_snapshots.values():
        if snap["consumer_id"] == cid and snap["status"] != "CANCELLED":
            snap["status"] = "SUPERSEDED"
            snap["updated_at"] = moment
    for dec in store.pre_qual_decisions.values():
        if dec["consumer_id"] == cid and dec["decision_status"] in ("PREQUALIFIED", "ELIGIBLE"):
            dec["decision_status"] = "ELIGIBLE"
            dec["updated_at"] = moment
            dec["version"] = int(dec.get("version", 0)) + 1
    helpers.refresh_posture(row)
    row["updated_at"] = moment
    row["version"] = int(row.get("version", 0)) + 1
    return ok(models.consumer(row), store.now())