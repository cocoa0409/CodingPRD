"""Dispute referrals, accuracy education and the pending-dispute cap."""

from flask import Blueprint, request

import store
import models
import helpers
from auth import require
from envelope import ok, ok_list, limited
from errors import fail

bp = Blueprint("disputes", __name__)

READ_ROLES = ["Consumer", "Referee", "ComplianceOfficer", "PlatformAdmin"]
LIST_ROLES = READ_ROLES + ["DataProtectionOfficer"]
INACCURACY_TYPES = ("PERSONAL_INFO", "ACCOUNT_INFO", "INQUIRY", "BALANCE")


def _refresh(cns):
    cns["open_dispute_count"] = helpers.open_dispute_count(cns["id"])


@bp.route("/dispute-referrals", methods=["POST"])
def create_dispute():
    uid, role = require(["Consumer", "Referee"])
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    cid = data.get("consumer_id")
    if not cid:
        fail("ERR_INVALID_REQUEST", "consumer_id is required.")
    cns = helpers.consumer(str(cid))
    if role == "Consumer":
        helpers.owned(cns, uid, role, field="id")
    sid = data.get("snapshot_id")
    if not sid:
        fail("ERR_INVALID_REQUEST", "snapshot_id is required.")
    helpers.snapshot(str(sid))
    inaccuracy = data.get("inaccuracy_type")
    if inaccuracy not in INACCURACY_TYPES:
        fail("ERR_INVALID_REQUEST", "inaccuracy_type is not a declared type.")
    narrative = data.get("narrative")
    if not isinstance(narrative, str) or len(narrative) < 20 or len(narrative) > 1000:
        fail("ERR_INVALID_REQUEST", "narrative must be between 20 and 1000 characters.")
    usable = [s for s in store.bureau_snapshots.values()
              if s["consumer_id"] == str(cid) and s["status"] in ("ACTIVE", "SUPERSEDED")]
    if not usable:
        fail("ERR_DISPUTE_SNAPSHOT_REQUIRED")
    row = store.make_row({
        "consumer_id": str(cid),
        "snapshot_id": str(sid),
        "referral_id": None,
        "referral_count": 0,
        "inaccuracy_type": inaccuracy,
        "narrative": narrative,
        "bureau_case_ref": None,
        "education_code": str(inaccuracy).lower(),
        "status": "DRAFT",
    })
    store.dispute_referrals[row["id"]] = row
    return ok(models.dispute(row), store.now(), 201)


@bp.route("/dispute-referrals", methods=["GET"])
def list_disputes():
    require(LIST_ROLES)
    rows = list(store.dispute_referrals.values())
    for key in ("consumer_id", "snapshot_id", "referral_id", "status"):
        wanted = request.args.get(key)
        if wanted:
            rows = [r for r in rows if r.get(key) == wanted]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.dispute(r) for r in window], store.now(), pagination)


@bp.route("/dispute-referrals/<did>", methods=["GET"])
def get_dispute(did):
    uid, role = require(READ_ROLES)
    row = helpers.dispute(did)
    helpers.owned(row, uid, role, field="consumer_id")
    return ok(models.dispute(row), store.now())


@bp.route("/consumers/<cid>/dispute-referrals", methods=["GET"])
def consumer_disputes(cid):
    require(READ_ROLES)
    helpers.consumer(cid)
    rows = [d for d in store.dispute_referrals.values() if d["consumer_id"] == cid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.dispute(r) for r in window], store.now(), pagination)


@bp.route("/bureau-snapshots/<sid>/dispute-referrals", methods=["GET"])
def snapshot_disputes(sid):
    require(READ_ROLES)
    helpers.snapshot(sid)
    rows = [d for d in store.dispute_referrals.values() if d["snapshot_id"] == sid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.dispute(r) for r in window], store.now(), pagination)


@bp.route("/referrals/<rid>/dispute-referrals", methods=["GET"])
def referral_disputes(rid):
    require(READ_ROLES)
    helpers.referral(rid)
    rows = [d for d in store.dispute_referrals.values() if d["referral_id"] == rid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.dispute(r) for r in window], store.now(), pagination)


@bp.route("/dispute-referrals/<did>/submit", methods=["POST"])
def submit_dispute(did):
    require(["Referee"])
    row = helpers.dispute(did)
    if row["status"] != "DRAFT" or row["referral_count"] != 0:
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a draft dispute with referral_count 0 may be submitted.")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    rid = data.get("referral_id")
    if not rid:
        fail("ERR_INVALID_REQUEST", "referral_id is required.")
    ref = helpers.referral(str(rid))
    if ref["status"] != "SENT":
        fail("ERR_PRESENTATION_INELIGIBLE",
             "The supplied referral is not in SENT status, so it does not unlock the route.")
    pending = len([d for d in store.dispute_referrals.values()
                   if d["consumer_id"] == row["consumer_id"]
                   and d["status"] == "SUBMITTED_OFFLINE"])
    if pending >= store.PENDING_DISPUTE_CAP:
        fail("ERR_DISPUTE_CAP_EXCEEDED")
    row["referral_id"] = str(rid)
    row["referral_count"] = 1
    row["status"] = "SUBMITTED_OFFLINE"
    models.touch(row)
    _refresh(helpers.consumer(row["consumer_id"]))
    return ok(models.dispute(row), store.now())


@bp.route("/dispute-referrals/<did>/acknowledge", methods=["POST"])
def acknowledge_dispute(did):
    require(["Referee"])
    row = helpers.dispute(did)
    if row["status"] != "SUBMITTED_OFFLINE":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a submitted dispute may be acknowledged.")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    case_ref = data.get("bureau_case_ref")
    if not case_ref:
        fail("ERR_INVALID_REQUEST", "bureau_case_ref is required.")
    row["bureau_case_ref"] = str(case_ref)
    row["status"] = "ACKNOWLEDGED_BY_BUREAU"
    models.touch(row)
    return ok(models.dispute(row), store.now())


@bp.route("/dispute-referrals/<did>/withdraw", methods=["POST"])
def withdraw_dispute(did):
    require(["Referee"])
    row = helpers.dispute(did)
    if row["status"] != "SUBMITTED_OFFLINE":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a submitted dispute may be withdrawn.")
    row["status"] = "WITHDRAWN"
    models.touch(row)
    _refresh(helpers.consumer(row["consumer_id"]))
    return ok(models.dispute(row), store.now())