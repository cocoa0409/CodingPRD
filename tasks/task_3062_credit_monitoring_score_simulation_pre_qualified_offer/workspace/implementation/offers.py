"""Offers: presenting, rendering, withdrawing, render policy and caps."""

from datetime import timedelta

from flask import Blueprint, request

import store
import models
import helpers
from auth import require
from envelope import ok, ok_list, limited
from errors import fail

bp = Blueprint("offers", __name__)

READ_ROLES = ["Consumer", "LenderOps", "Referee", "ComplianceOfficer", "PlatformAdmin"]
CHANNELS = ("WEB", "MOBILE_APP", "MARKETPLACE")
TOPICS = ("factor_explanations", "accuracy_education")

OFFER_INTENT_TTL_DAYS = 30
OFFER_SETTLEMENT_TTL_DAYS = 30


def product_kind_of_decision(dec):
    prog = store.lender_programs.get(dec["lender_program_id"])
    if prog is None:
        return None
    item = store.product_catalog_items.get(prog["product_catalog_item_id"])
    return item["product_kind"] if item else None


def is_stale(row):
    expiry_days = min(OFFER_INTENT_TTL_DAYS, OFFER_SETTLEMENT_TTL_DAYS)
    limit = row["intent_recorded_at"] + timedelta(days=expiry_days)
    return store.now() > limit


def refresh_offer(row):
    if row["status"] in ("PRESENTED", "RENDERED") and is_stale(row):
        row["status"] = "STALE"
    return row


def _presentation_cap(cid, kind):
    for row in store.offer_presentation_caps.values():
        if row["consumer_id"] == cid and row["product_kind"] == kind:
            return row
    row = store.make_row({
        "consumer_id": cid,
        "product_kind": kind,
        "presented_count": 0,
        "presentation_cap_bps": store.OFFER_CAP_BPS,
        "exceeds_cap": False,
    })
    store.offer_presentation_caps[row["id"]] = row
    return row


def _recompute_cap(row):
    total = len([o for o in store.pre_qualified_offers.values()
                 if o["consumer_id"] == row["consumer_id"]
                 and o["status"] != "WITHDRAWN"])
    allowed = (row["presentation_cap_bps"] * total) // 10000
    row["exceeds_cap"] = row["presented_count"] > allowed
    return row


# ---------------------------------------------------------------------------
# Present
# ---------------------------------------------------------------------------
def _unwound_reason(prog, cns, snap):
    scr = helpers.criteria_of(prog["id"])
    return helpers.criteria_of(prog["id"]), scr


@bp.route("/pre-qualification-decisions/<did>/present", methods=["POST"])
def present_decision(did):
    uid, role = require(["Consumer"])
    dec = helpers.decision(did)
    helpers.owned(dec, uid, role, field="consumer_id")
    if dec["decision_status"] == "EXPIRED":
        fail("ERR_INVALID_STATE_TRANSITION", "An EXPIRED decision cannot be presented.")
    if dec["decision_status"] != "PREQUALIFIED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a PREQUALIFIED decision may be presented.")
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    channel = data.get("channel")
    if channel not in CHANNELS:
        fail("ERR_INVALID_REQUEST", "channel must be WEB, MOBILE_APP or MARKETPLACE.")
    cns = helpers.consumer(dec["consumer_id"])
    fresh_until = dec.get("fresh_until")
    if fresh_until is not None and store.now() >= fresh_until:
        fail("ERR_OFFER_EXPIRED")
    prog = helpers.program(dec["lender_program_id"])
    snap = helpers.active_snapshot_for_decision(cns["id"], dec["snapshot_id"])
    moment = store.now()
    row = store.make_row({
        "decision_id": dec["id"],
        "consumer_id": cns["id"],
        "lender_program_id": prog["id"],
        "product_kind": product_kind_of_decision(dec),
        "channel": channel,
        "intent_recorded_at": moment,
        "render_intent_recorded_at": None,
        "status": "PRESENTED",
    }, moment)
    store.pre_qualified_offers[row["id"]] = row
    if not helpers.presentation_policy_eligible(cns, prog, snap):
        _withdraw_decision(dec, prog)
        row["status"] = "WITHDRAWN"
        row["updated_at"] = moment
        fail("ERR_PRESENTATION_INELIGIBLE")
    return ok(models.offer(row), store.now(), 201)


def _withdraw_decision(dec, prog):
    """Retroactive unwind attributed to the original decided_at (PRD 3.7)."""
    crit_list = helpers.criteria_of(prog["id"])
    failed = []
    snap = helpers.active_snapshot_for_decision(dec["consumer_id"], dec["snapshot_id"])
    cns = store.consumers.get(dec["consumer_id"])
    for crit in crit_list:
        if not crit["is_hard_requirement"]:
            continue
        if cns is None or snap is None or not helpers.criterion_matches(crit, cns, snap):
            failed.append(crit)
    dec["decision_status"] = "INELIGIBLE"
    dec["disqualifying_criteria"] = sorted(
        [{"criterion_field": c["criterion_field"], "operator": c["operator"],
          "criterion_value": c["criterion_value"]} for c in failed],
        key=lambda c: c["criterion_field"])
    dec["modeled_odds_pct"] = None
    dec["reason"] = "HARD_CRITERIA_FAILED" if failed else "NOT_PREQUALIFIED"
    dec["version"] = int(dec.get("version", 0)) + 1


# ---------------------------------------------------------------------------
# Offer reads
# ---------------------------------------------------------------------------
@bp.route("/pre-qualified-offers", methods=["GET"])
def list_offers():
    require(READ_ROLES)
    rows = [refresh_offer(o) for o in store.pre_qualified_offers.values()]
    cid = request.args.get("consumer_id")
    if cid:
        rows = [r for r in rows if r["consumer_id"] == cid]
    did = request.args.get("decision_id")
    if did:
        rows = [r for r in rows if r["decision_id"] == did]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.offer(r) for r in window], store.now(), pagination)


@bp.route("/pre-qualified-offers/<oid>", methods=["GET"])
def get_offer(oid):
    uid, role = require(READ_ROLES)
    row = refresh_offer(helpers.offer(oid))
    helpers.owned(row, uid, role, field="consumer_id")
    return ok(models.offer(row), store.now())


@bp.route("/pre-qualification-decisions/<did>/pre-qualified-offers", methods=["GET"])
def decision_offers(did):
    require(READ_ROLES)
    helpers.decision(did)
    rows = [refresh_offer(o) for o in store.pre_qualified_offers.values()
            if o["decision_id"] == did]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.offer(r) for r in window], store.now(), pagination)


@bp.route("/consumers/<cid>/pre-qualified-offers", methods=["GET"])
def consumer_offers(cid):
    require(READ_ROLES)
    helpers.consumer(cid)
    rows = [refresh_offer(o) for o in store.pre_qualified_offers.values()
            if o["consumer_id"] == cid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.offer(r) for r in window], store.now(), pagination)


@bp.route("/lender-programs/<pid>/pre-qualified-offers", methods=["GET"])
def program_offers(pid):
    require(["LenderOps", "Referee", "ComplianceOfficer", "PlatformAdmin"])
    helpers.program(pid)
    rows = [refresh_offer(o) for o in store.pre_qualified_offers.values()
            if o["lender_program_id"] == pid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.offer(r) for r in window], store.now(), pagination)


# ---------------------------------------------------------------------------
# Render and withdraw
# ---------------------------------------------------------------------------
@bp.route("/offers/<oid>/render", methods=["POST"])
def render_offer(oid):
    uid, role = require(["Consumer"])
    row = refresh_offer(helpers.offer(oid))
    helpers.owned(row, uid, role, field="consumer_id")
    if row["status"] != "PRESENTED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a PRESENTED offer may be rendered.")
    dec = helpers.decision(row["decision_id"])
    cns = helpers.consumer(row["consumer_id"])
    prog = helpers.program(row["lender_program_id"])
    fresh_until = dec.get("fresh_until")
    if fresh_until is not None and store.now() > fresh_until:
        fail("ERR_OFFER_EXPIRED")
    snap = helpers.active_snapshot_for_decision(cns["id"], dec["snapshot_id"])
    if not helpers.presentation_policy_eligible(cns, prog, snap):
        fail("ERR_OFFER_PRESENTATION_BLOCKED")
    cap = _presentation_cap(cns["id"], row["product_kind"])
    total = len([o for o in store.pre_qualified_offers.values()
                 if o["consumer_id"] == cns["id"] and o["status"] != "WITHDRAWN"])
    allowed = (cap["presentation_cap_bps"] * total) // 10000
    if cap["presented_count"] > allowed:
        fail("ERR_OFFER_PRESENTATION_CAP_EXCEEDED")
    policy = helpers.policy_for(cns["id"])
    blanket = bool(policy and policy.get("blanket_presentation_override"))
    if not whole_render_completeness(cns["id"], policy) and not blanket:
        fail("ERR_RENDER_COMPLETENESS_INCOMPLETE")
    if not helpers.collateral_eligible(cns, prog):
        fail("ERR_COLLATERAL_ELIGIBILITY_CHANGED")
    moment = store.now()
    row["status"] = "RENDERED"
    row["render_intent_recorded_at"] = moment
    row["updated_at"] = moment
    row["version"] = int(row.get("version", 0)) + 1
    cap["presented_count"] = int(cap["presented_count"]) + 1
    cap["updated_at"] = moment
    cap["version"] = int(cap.get("version", 0)) + 1
    _recompute_cap(cap)
    return ok(models.offer(row), store.now())


def whole_render_completeness(cid, policy=None):
    if policy is None:
        policy = helpers.policy_for(cid)
    if policy and policy.get("content_quality_override"):
        return True
    facets = [f for f in store.content_quality_facets.values() if f["consumer_id"] == cid]
    topics = {f["topic"] for f in facets}
    if not {"factor_explanations", "accuracy_education"} <= topics:
        return False
    return all(f["status"] == "COMPLETE" for f in facets)


@bp.route("/offers/<oid>/withdraw", methods=["POST"])
def withdraw_offer(oid):
    require(["ComplianceOfficer", "PlatformAdmin"])
    row = refresh_offer(helpers.offer(oid))
    if row["status"] not in ("PRESENTED", "RENDERED"):
        fail("ERR_INVALID_STATE_TRANSITION", "Only a PRESENTED or RENDERED offer may be withdrawn.")
    was_presented = row["status"] == "PRESENTED"
    moment = store.now()
    row["status"] = "WITHDRAWN"
    row["updated_at"] = moment
    row["version"] = int(row.get("version", 0)) + 1
    if was_presented:
        dec = store.pre_qual_decisions.get(row["decision_id"])
        if dec is not None and dec["decision_status"] in ("ELIGIBLE", "PREQUALIFIED"):
            dec["decision_status"] = "INELIGIBLE"
            dec["updated_at"] = moment
            dec["version"] = int(dec.get("version", 0)) + 1
    return ok(models.offer(row), store.now())


# ---------------------------------------------------------------------------
# Render policy
# ---------------------------------------------------------------------------
def recompute_render_posture(cns, policy):
    if cns.get("monitoring_posture") == "IMMATURE":
        policy["render_posture"] = "RENDER_RESTRICTED"
    elif whole_render_completeness(cns["id"], policy):
        policy["render_posture"] = "RENDER_OPEN"
    else:
        policy["render_posture"] = "RENDER_FACETS_INCOMPLETE"
    return policy


@bp.route("/consumers/<cid>/render-policy", methods=["PUT"])
def put_render_policy(cid):
    require(["Referee", "ComplianceOfficer", "PlatformAdmin"])
    cns = helpers.consumer(cid)
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    policy = helpers.policy_for(cid)
    if policy is None:
        policy = store.make_row({
            "consumer_id": cid,
            "blanket_presentation_override": False,
            "content_quality_override": False,
            "render_posture": "RENDER_FACETS_INCOMPLETE",
        })
        store.render_policies[policy["id"]] = policy
    for field in ("blanket_presentation_override", "content_quality_override"):
        if field in data:
            if not isinstance(data[field], bool):
                fail("ERR_INVALID_REQUEST", "%s must be a boolean." % field)
            policy[field] = data[field]
    models.touch(policy)
    recompute_render_posture(cns, policy)
    return ok(models.policy(policy), store.now())


@bp.route("/render-policies", methods=["GET"])
def list_policies():
    require(["Consumer", "Referee", "ComplianceOfficer", "PlatformAdmin"])
    rows = list(store.render_policies.values())
    cid = request.args.get("consumer_id")
    if cid:
        rows = [r for r in rows if r["consumer_id"] == cid]
    posture = request.args.get("render_posture")
    if posture:
        rows = [r for r in rows if r["render_posture"] == posture]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.policy(r) for r in window], store.now(), pagination)


@bp.route("/consumers/<cid>/render-policies", methods=["GET"])
def consumer_policies(cid):
    require(["Consumer", "Referee", "ComplianceOfficer", "PlatformAdmin"])
    helpers.consumer(cid)
    rows = [p for p in store.render_policies.values() if p["consumer_id"] == cid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.policy(r) for r in window], store.now(), pagination)


# ---------------------------------------------------------------------------
# Content quality facets
# ---------------------------------------------------------------------------
@bp.route("/consumers/<cid>/content-quality-facets", methods=["POST"])
def create_facet(cid):
    require(["Referee", "PlatformAdmin"])
    helpers.consumer(cid)
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    topic = data.get("topic")
    if topic not in TOPICS:
        fail("ERR_INVALID_REQUEST", "topic must be factor_explanations or accuracy_education.")
    score = data.get("score_bps")
    if isinstance(score, bool) or not isinstance(score, int):
        fail("ERR_INVALID_REQUEST", "score_bps must be an integer.")
    if score < 0 or score > 10000:
        fail("ERR_INVALID_REQUEST", "score_bps must fall between 0 and 10000.")
    row = store.make_row({
        "consumer_id": cid,
        "topic": topic,
        "score_bps": score,
        "status": "COMPLETE" if score >= store.CONTENT_QUALITY_MIN else "INCOMPLETE",
    })
    store.content_quality_facets[row["id"]] = row
    return ok(models.facet(row), store.now(), 201)


@bp.route("/content-quality-facets", methods=["GET"])
def list_facets():
    require(["Consumer", "Referee", "ComplianceOfficer", "PlatformAdmin"])
    rows = list(store.content_quality_facets.values())
    cid = request.args.get("consumer_id")
    if cid:
        rows = [r for r in rows if r["consumer_id"] == cid]
    topic = request.args.get("topic")
    if topic:
        rows = [r for r in rows if r["topic"] == topic]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.facet(r) for r in window], store.now(), pagination)


@bp.route("/consumers/<cid>/content-quality-facets", methods=["GET"])
def consumer_facets(cid):
    require(["Consumer", "Referee", "ComplianceOfficer", "PlatformAdmin"])
    helpers.consumer(cid)
    rows = [f for f in store.content_quality_facets.values() if f["consumer_id"] == cid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.facet(r) for r in window], store.now(), pagination)


@bp.route("/content-quality-facets/<fid>/score", methods=["POST"])
def score_facet(fid):
    require(["Referee"])
    row = store.content_quality_facets.get(fid)
    if row is None:
        fail("ERR_CONSUMER_NOT_FOUND", "ContentQualityFacet not found.")
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    score = data.get("score_bps")
    if isinstance(score, bool) or not isinstance(score, int):
        fail("ERR_INVALID_REQUEST", "score_bps must be an integer.")
    if score < store.CONTENT_QUALITY_MIN:
        fail("ERR_FACET_SCORE_BELOW_MINIMUM")
    if row["status"] != "COMPLETE":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a COMPLETE facet may be rescored.")
    row["score_bps"] = score
    row["status"] = "COMPLETE"
    models.touch(row)
    return ok(models.facet(row), store.now())


# ---------------------------------------------------------------------------
# Presentation caps
# ---------------------------------------------------------------------------
def _cap_view(row):
    total = len([o for o in store.pre_qualified_offers.values()
                 if o["consumer_id"] == row["consumer_id"]
                 and o["status"] != "WITHDRAWN"])
    row["exceeds_cap"] = row["presented_count"] > (
        (row["presentation_cap_bps"] * total) // 10000)
    return models.cap(row)


@bp.route("/offer-presentation-caps", methods=["GET"])
def list_caps():
    require(["Consumer", "ComplianceOfficer", "PlatformAdmin"])
    rows = list(store.offer_presentation_caps.values())
    cid = request.args.get("consumer_id")
    if cid:
        rows = [r for r in rows if r["consumer_id"] == cid]
    kind = request.args.get("product_kind")
    if kind:
        rows = [r for r in rows if r["product_kind"] == kind]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([_cap_view(r) for r in window], store.now(), pagination)


@bp.route("/consumers/<cid>/offer-presentation-caps", methods=["GET"])
def consumer_caps(cid):
    require(["Consumer", "ComplianceOfficer", "PlatformAdmin"])
    helpers.consumer(cid)
    rows = [c for c in store.offer_presentation_caps.values() if c["consumer_id"] == cid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([_cap_view(r) for r in window], store.now(), pagination)