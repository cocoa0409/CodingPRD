"""Monitoring consent, bureau pulls, factor explanations and score alerts."""

from flask import Blueprint, request

import store
import models
import helpers
from auth import require
from envelope import ok, ok_list, limited
from errors import fail

bp = Blueprint("monitoring", __name__)

SNAPSHOT_READ_ROLES = ["Consumer", "BureauConnector", "Referee", "ComplianceOfficer",
                       "PlatformAdmin", "DataProtectionOfficer"]
PULL_ROLES = ["BureauConnector", "PlatformAdmin"]
ALERT_ROLES = ["Consumer", "Referee", "PlatformAdmin", "DataProtectionOfficer"]

ACTION_CODES = {"PAY_DOWN_REVOLVING", "CLOSE_OLDEST_TRADELINE",
                "INCREASE_CREDIT_LIMIT", "OPEN_NEW_TRADELINE"}
CHANNELS = {"EMAIL", "PUSH", "SMS"}


def normalize_codes(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        fail("ERR_INVALID_REQUEST", "factor_codes must be an array.")
    out = []
    for code in raw:
        if not isinstance(code, str) or not code.strip():
            fail("ERR_INVALID_REQUEST", "factor_codes entries must be non-empty strings.")
        token = code.strip().lower()
        if token not in out:
            out.append(token)
    return out


def validate_factor_catalog(codes):
    active = [t for t in store.score_tiers.values() if t["status"] == "ACTIVE"]
    if not active:
        return
    known = set()
    for tier in active:
        known.update(tier.get("factor_catalog") or [])
    for code in codes:
        if code not in known:
            fail("ERR_INVALID_REQUEST",
                 "factor code '%s' is absent from every active tier's catalog." % code)


@bp.route("/consumers/<cid>/monitoring-consent", methods=["POST"])
def monitoring_consent(cid):
    uid, role = require(["Consumer"])
    cns = helpers.consumer(cid)
    helpers.owned(cns, uid, role, field="id")
    if cns["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "Monitoring consent requires an ACTIVE consumer.")
    if cns["score_version"] != 0:
        fail("ERR_PRIOR_BUREAU_SNAPSHOT_EXISTS")
    if cns["monitoring_consent_at"] is not None:
        fail("ERR_MONITORING_CONSENT_ALREADY_GRANTED")
    cns["monitoring_consent_at"] = store.now()
    helpers.bump_consumer(cns)
    helpers.refresh_posture(cns)
    return ok(models.consumer(cns), store.now())


def _write_snapshot(cns, payload):
    codes = normalize_codes(payload.get("factor_codes"))
    validate_factor_catalog(codes)
    moment = store.now()
    score = payload.get("score")
    if score is None or isinstance(score, bool) or not isinstance(score, int):
        fail("ERR_INVALID_REQUEST", "score must be an integer.")
    balance = payload.get("total_revolving_balance_cents", 0)
    limit = payload.get("credit_limit_total_cents", 0)
    for name, value in (("total_revolving_balance_cents", balance),
                        ("credit_limit_total_cents", limit)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            fail("ERR_INVALID_REQUEST", "%s must be a non-negative integer." % name)
    added = payload.get("added_account_count", 0)
    if isinstance(added, bool) or not isinstance(added, int) or added < 0:
        fail("ERR_INVALID_REQUEST", "added_account_count must be a non-negative integer.")
    status = "ACTIVE" if codes else "CANCELLED"
    row = store.make_row({
        "consumer_id": cns["id"],
        "snapshot_ordinal": cns["score_version"] + 1,
        "pulled_at": moment,
        "score": score,
        "added_account_count": added,
        "total_revolving_balance_cents": balance,
        "credit_limit_total_cents": limit,
        "overall_credit_utilization_pct": helpers.compute_utilization(balance, limit),
        "factor_codes": codes,
        "status": status,
    }, moment)
    store.bureau_snapshots[row["id"]] = row
    if not codes:
        return row, False
    for index, code in enumerate(codes):
        direction, impact = store.FACTOR_TABLE.get(code, ("NEUTRAL", 0))
        exp = {
            "id": store.new_id(),
            "created_at": moment,
            "snapshot_id": row["id"],
            "factor_code": code,
            "direction": direction,
            "impact_points": impact,
            "rank_index": index,
        }
        store.score_factor_explanations[exp["id"]] = exp
    return row, True


def _supersede_others(cns, keep_id):
    moment = store.now()
    for snap in store.bureau_snapshots.values():
        if snap["consumer_id"] == cns["id"] and snap["id"] != keep_id \
                and snap["status"] == "ACTIVE":
            snap["status"] = "SUPERSEDED"
            snap["updated_at"] = moment
            snap["version"] = int(snap.get("version", 0)) + 1


def evaluate_alert(cns, channel=None):
    """score_alert_threshold: one row per pull, no exceptions (PRD 3.1)."""
    override = None
    for row in store.score_alert_thresholds.values():
        if row["consumer_id"] == cns["id"]:
            override = row
            break
    effective = store.SCORE_ALERT_DEFAULT_THRESHOLD
    if override is not None:
        effective = max(int(override["threshold_override_points"]),
                        store.SCORE_ALERT_DEFAULT_THRESHOLD)
    prev = cns.get("previous_score")
    cur = cns.get("current_score")
    if prev is None:
        kind = "SCORE_FLAT"
    elif cur is not None and (cur - prev) >= effective:
        kind = "SCORE_UP"
    elif cur is not None and (-1 * (cur - prev)) >= effective:
        kind = "SCORE_DOWN"
    else:
        kind = "SCORE_FLAT"
    moment = store.now()
    row = store.make_row({
        "consumer_id": cns["id"],
        "alert_kind": kind,
        "threshold_used": effective,
        "from_score": prev,
        "to_score": cur,
        "channel": channel,
        "status": "PENDING" if kind in ("SCORE_UP", "SCORE_DOWN") else "SUPPRESSED",
        "evaluated_at": moment,
    }, moment)
    store.score_alerts[row["id"]] = row
    return row


@bp.route("/consumers/<cid>/bureau-snapshots", methods=["POST"])
def create_snapshot(cid):
    require(PULL_ROLES)
    cns = helpers.consumer(cid)
    if cns["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "A pull requires an ACTIVE consumer.")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    if cns["monitoring_consent_at"] is None:
        fail("ERR_MONITORING_NOT_CONSENTED")
    if helpers.pull_cooldown_active(cid, store.now()):
        fail("ERR_PULL_COOLDOWN_ACTIVE")
    helpers.checkout_version(cns, data)
    row, bound = _write_snapshot(cns, data)
    if not bound:
        helpers.bump_consumer(cns)
        fail("ERR_PULL_RESULT_EMPTY")
    _supersede_others(cns, row["id"])
    helpers.recompute_consumer(cns)
    helpers.bump_consumer(cns)
    evaluate_alert(cns, data.get("channel"))
    return ok(models.snapshot(row), store.now(), 201)


@bp.route("/bureau-snapshots", methods=["GET"])
def list_snapshots():
    require(SNAPSHOT_READ_ROLES)
    rows = list(store.bureau_snapshots.values())
    cid = request.args.get("consumer_id")
    if cid:
        rows = [r for r in rows if r["consumer_id"] == cid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.snapshot(r) for r in window], store.now(), pagination)


@bp.route("/bureau-snapshots/<sid>", methods=["GET"])
def get_snapshot(sid):
    require(SNAPSHOT_READ_ROLES)
    row = helpers.snapshot(sid)
    return ok(models.snapshot(row), store.now())


@bp.route("/consumers/<cid>/bureau-snapshots", methods=["GET"])
def list_consumer_snapshots(cid):
    require(["Consumer", "BureauConnector", "Referee", "ComplianceOfficer", "PlatformAdmin"])
    helpers.consumer(cid)
    rows = helpers.consumer_snapshots(cid)
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.snapshot(r) for r in window], store.now(), pagination)


@bp.route("/bureau-snapshots/<sid>/replay", methods=["POST"])
def replay_snapshot(sid):
    require(PULL_ROLES)
    row = helpers.snapshot(sid)
    if row["status"] != "CANCELLED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a CANCELLED snapshot may be replayed.")
    cns = helpers.consumer(row["consumer_id"])
    if helpers.pull_cooldown_active(cns["id"], store.now()):
        fail("ERR_PULL_COOLDOWN_ACTIVE")
    row["status"] = "ACTIVE"
    row["updated_at"] = store.now()
    row["version"] = int(row.get("version", 0)) + 1
    moment = store.now()
    for code_index, code in enumerate(row["factor_codes"]):
        direction, impact = store.FACTOR_TABLE.get(code, ("NEUTRAL", 0))
        exp = {"id": store.new_id(), "created_at": moment, "snapshot_id": row["id"],
               "factor_code": code, "direction": direction,
               "impact_points": impact, "rank_index": code_index}
        store.score_factor_explanations[exp["id"]] = exp
    _supersede_others(cns, row["id"])
    helpers.recompute_consumer(cns)
    helpers.bump_consumer(cns)
    evaluate_alert(cns, None)
    return ok(models.snapshot(row), store.now())


@bp.route("/bureau-snapshots/<sid>/score-factor-explanations", methods=["GET"])
def snapshot_factors(sid):
    require(["Consumer", "Referee", "PlatformAdmin"])
    helpers.snapshot(sid)
    rows = [f for f in store.score_factor_explanations.values() if f["snapshot_id"] == sid]
    rows.sort(key=lambda r: r["rank_index"])
    return ok_list([models.factor(r) for r in rows], store.now(), {
        "limit": len(rows) or 1, "offset": 0, "total_count": len(rows), "has_more": False})


@bp.route("/score-factor-explanations", methods=["GET"])
def list_factors():
    require(["Consumer", "Referee", "PlatformAdmin"])
    rows = list(store.score_factor_explanations.values())
    sid = request.args.get("snapshot_id")
    if sid:
        rows = [r for r in rows if r["snapshot_id"] == sid]
    direction = request.args.get("direction")
    if direction:
        rows = [r for r in rows if r["direction"] == direction]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.factor(r) for r in window], store.now(), pagination)


@bp.route("/score-factor-explanations/<fid>", methods=["GET"])
def get_factor(fid):
    require(["Consumer", "Referee", "PlatformAdmin"])
    row = store.score_factor_explanations.get(fid)
    if row is None:
        fail("ERR_CONSUMER_NOT_FOUND", "ScoreFactorExplanation not found.")
    return ok(models.factor(row), store.now())


@bp.route("/score-alerts", methods=["GET"])
def list_alerts():
    require(ALERT_ROLES)
    rows = list(store.score_alerts.values())
    cid = request.args.get("consumer_id")
    if cid:
        rows = [r for r in rows if r["consumer_id"] == cid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.alert(r) for r in window], store.now(), pagination)


@bp.route("/consumers/<cid>/score-alerts", methods=["GET"])
def list_consumer_alerts(cid):
    require(["Consumer", "Referee", "PlatformAdmin"])
    helpers.consumer(cid)
    rows = [r for r in store.score_alerts.values() if r["consumer_id"] == cid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["evaluated_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.alert(r) for r in window], store.now(), pagination)


@bp.route("/score-alerts/<aid>", methods=["GET"])
def get_alert(aid):
    uid, role = require(["Consumer", "Referee", "PlatformAdmin"])
    row = helpers.alert(aid)
    helpers.owned(row, uid, role, field="consumer_id")
    return ok(models.alert(row), store.now())


@bp.route("/score-alerts/<aid>/acknowledge", methods=["POST"])
def acknowledge_alert(aid):
    uid, role = require(["Consumer"])
    row = helpers.alert(aid)
    helpers.owned(row, uid, role, field="consumer_id")
    if row["status"] != "PENDING":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a PENDING alert may be acknowledged.")
    row["status"] = "DELIVERED"
    row["updated_at"] = store.now()
    row["version"] = int(row.get("version", 0)) + 1
    return ok(models.alert(row), store.now())


@bp.route("/score-alerts/<aid>/suppress", methods=["POST"])
def suppress_alert(aid):
    require(["Referee"])
    row = helpers.alert(aid)
    if row["status"] != "PENDING":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a PENDING alert may be suppressed.")
    row["status"] = "SUPPRESSED"
    row["updated_at"] = store.now()
    row["version"] = int(row.get("version", 0)) + 1
    return ok(models.alert(row), store.now())


@bp.route("/consumers/<cid>/score-alert-threshold", methods=["PUT"])
def put_threshold(cid):
    uid, role = require(["Consumer"])
    cns = helpers.consumer(cid)
    helpers.owned(cns, uid, role, field="id")
    data = request.get_json(silent=True) or {}
    value = data.get("threshold_override_points")
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "threshold_override_points must be an integer.")
    row = None
    for existing in store.score_alert_thresholds.values():
        if existing["consumer_id"] == cid:
            row = existing
            break
    if row is None:
        row = store.make_row({"consumer_id": cid,
                              "threshold_override_points": value}, store.now())
        store.score_alert_thresholds[row["id"]] = row
    else:
        row["threshold_override_points"] = value
        models.touch(row)
    return ok(models.alert_threshold(row), store.now())


@bp.route("/score-alert-thresholds", methods=["GET"])
def list_thresholds():
    require(["Consumer", "Referee", "PlatformAdmin"])
    rows = list(store.score_alert_thresholds.values())
    cid = request.args.get("consumer_id")
    if cid:
        rows = [r for r in rows if r["consumer_id"] == cid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.alert_threshold(r) for r in window], store.now(), pagination)


@bp.route("/score-alert-thresholds/<tid>", methods=["GET"])
def get_threshold(tid):
    require(["Consumer", "Referee", "PlatformAdmin"])
    row = store.score_alert_thresholds.get(tid)
    if row is None:
        fail("ERR_CONSUMER_NOT_FOUND", "ScoreAlertThreshold not found.")
    return ok(models.alert_threshold(row), store.now())