"""The daily operations run and the logical clock."""

from datetime import timedelta

from flask import Blueprint, request

import store
import models
import helpers
import analytics
import consent as consent_mod
import prequal
from auth import require
from envelope import ok, ok_list, limited
from errors import fail

bp = Blueprint("opsrun", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(["PlatformAdmin"])
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    raw = data.get("current_utc")
    if raw in (None, ""):
        fail("ERR_INVALID_REQUEST", "current_utc is required.")
    import lenders as lenders_mod
    moment = lenders_mod.parse_instant(raw)
    if moment < store.now():
        fail("ERR_CLOCK_NOT_MONOTONIC")
    store.set_clock(moment)
    return ok({}, store.now())


# ---------------------------------------------------------------------------
# Constituent stages
# ---------------------------------------------------------------------------
def _mobility():
    moment = store.now()
    cutoff = moment - timedelta(days=store.SNAPSHOT_STALENESS_DAYS)
    for snap in store.bureau_snapshots.values():
        if snap["status"] == "ACTIVE" and snap["pulled_at"] <= cutoff:
            snap["status"] = "SUPERSEDED"
            snap["updated_at"] = moment
            snap["version"] = int(snap.get("version", 0)) + 1
    for ref in store.referrals.values():
        if ref["status"] != "SENT":
            continue
        sent = ref.get("sent_at") or ref["created_at"]
        if moment > sent + timedelta(days=30):
            ref["status"] = "UNFUNDED"
            ref["updated_at"] = moment
            ref["version"] = int(ref.get("version", 0)) + 1
            con = consent_mod.consent_for(ref["consumer_id"], ref["decision_id"])
            if con is not None and con["status"] == "PENDING":
                consent_mod.release_consent(con)
    for dec in store.pre_qual_decisions.values():
        if dec["decision_status"] in ("ELIGIBLE", "PREQUALIFIED") and dec.get("fresh_until"):
            if dec["fresh_until"] <= moment:
                dec["decision_status"] = "EXPIRED"
                dec["updated_at"] = moment
                dec["version"] = int(dec.get("version", 0)) + 1
    # decision TRAP: a PREQUALIFIED decision with no consent record whose pinned
    # snapshot has gone stale is rescued back to ELIGIBLE (PRD 3.5). A still-ACTIVE
    # pinned snapshot leaves the decision untouched.
    for dec in store.pre_qual_decisions.values():
        if dec["decision_status"] != "PREQUALIFIED":
            continue
        if consent_mod.consent_for(dec["consumer_id"], dec["id"]) is not None:
            continue
        pinned = store.bureau_snapshots.get(dec.get("snapshot_id"))
        if pinned is not None and pinned["status"] == "ACTIVE":
            continue
        dec["decision_status"] = "ELIGIBLE"
        dec["reason"] = "NO_ACTIVE_SNAPSHOT"
        dec["updated_at"] = moment
        dec["version"] = int(dec.get("version", 0)) + 1
    for prog in store.lender_programs.values():
        if prog["status"] in ("ACTIVE", "PAUSED") and prog.get("expiry_at"):
            if prog["expiry_at"] <= moment:
                prog["status"] = "EXPIRED"
                prog["updated_at"] = moment
                prog["version"] = int(prog.get("version", 0)) + 1


def _settlement():
    import referrals as ref_mod
    for ref in store.referrals.values():
        if ref["status"] == "FUNDED" and not ref_mod.has_entry(ref["id"], "REVENUE"):
            ref_mod.post_revenue_entry(ref)
        if ref["status"] == "REVERSED" and not ref_mod.has_entry(ref["id"], "CLAWBACK"):
            funded_at = ref.get("funded_at")
            if funded_at is None:
                continue
            if store.now() <= funded_at + timedelta(days=int(ref["clawback_days"])):
                ref_mod.post_clawback_entry(ref)


def _adverse_selection():
    moment = store.now()
    for dec in store.pre_qual_decisions.values():
        if dec["decision_status"] != "ELIGIBLE":
            continue
        snap = store.bureau_snapshots.get(dec.get("snapshot_id"))
        if snap is None or snap["status"] != "ACTIVE":
            dec["decision_status"] = "NEEDS_SNAPSHOT"
            dec["reason"] = "NO_ACTIVE_SNAPSHOT"
            dec["modeled_odds_pct"] = None
            dec["updated_at"] = moment
            dec["version"] = int(dec.get("version", 0)) + 1


def _consent_sealing():
    pending = [c for c in store.consent_records.values() if c["status"] == "PENDING"]
    pending.sort(key=lambda c: (c["created_at"], c["id"]))
    for con in pending[:store.CONSENT_SEAL_MAX_PER_RUN]:
        dec = store.pre_qual_decisions.get(con["decision_id"])
        prog = store.lender_programs.get(dec["lender_program_id"]) if dec else None
        consent_mod.seal_consent(con, prog)


def _retention():
    moment = store.now()
    cutoff = moment - timedelta(days=store.RETENTION_DAYS)
    for con in store.consent_records.values():
        if con["status"] == "SEALED" and con.get("sealed_at") is not None:
            if con["sealed_at"] <= cutoff:
                con["archive_status"] = "ARCHIVED"


def _cap_window():
    import offers as offers_mod
    for cap in store.offer_presentation_caps.values():
        cap["presented_count"] = 0
        cap["updated_at"] = store.now()
        cap["version"] = int(cap.get("version", 0)) + 1
        offers_mod._recompute_cap(cap)


def _stale_offers():
    import offers as offers_mod
    for row in store.pre_qualified_offers.values():
        if row["status"] == "RENDERED" and offers_mod.is_stale(row):
            row["status"] = "STALE"
            row["updated_at"] = store.now()
            row["version"] = int(row.get("version", 0)) + 1
        elif row["status"] == "RENDERED":
            row["status"] = "STALE"
            row["updated_at"] = store.now()
            row["version"] = int(row.get("version", 0)) + 1


def _calibration():
    for item in store.product_catalog_items.values():
        analytics.calibration_index(item["id"], "including_provisional")


def _posture_rollup():
    for cns in store.consumers.values():
        helpers.refresh_posture(cns)
        moment = store.now()
        for alert in store.score_alerts.values():
            if alert["consumer_id"] == cns["id"] and alert["status"] == "PENDING":
                if cns["monitoring_posture"] != "COMPLETE":
                    alert["status"] = "SUPPRESSED"
                    alert["updated_at"] = moment
                    alert["version"] = int(alert.get("version", 0)) + 1
        import offers as offers_mod
        policy = helpers.policy_for(cns["id"])
        if policy is None:
            policy = store.make_row({
                "consumer_id": cns["id"],
                "blanket_presentation_override": False,
                "content_quality_override": False,
                "render_posture": "RENDER_FACETS_INCOMPLETE",
            })
            store.render_policies[policy["id"]] = policy
        offers_mod.recompute_render_posture(cns, policy)
        run_blanket_renders(cns)


def run_blanket_renders(cns):
    """blanket_presentation_override renders PRESENTED offers via the daily run."""
    policy = helpers.policy_for(cns["id"])
    if not policy or not policy.get("blanket_presentation_override"):
        return
    for row in store.pre_qualified_offers.values():
        if row["consumer_id"] != cns["id"] or row["status"] != "PRESENTED":
            continue
        if not policy.get("content_quality_override"):
            if not helpers.content_quality_required_met(cns["id"]):
                continue
        row["status"] = "RENDERED"
        row["render_intent_recorded_at"] = store.now()
        row["updated_at"] = store.now()
        row["version"] = int(row.get("version", 0)) + 1
        import offers as offers_mod
        cap = offers_mod._presentation_cap(cns["id"], row["product_kind"])
        cap["presented_count"] = int(cap["presented_count"]) + 1
        offers_mod._recompute_cap(cap)


STAGE_FUNCS = {
    "daily_mobility": _mobility,
    "settlement": _settlement,
    "adverse_selection": _adverse_selection,
    "consent_sealing": _consent_sealing,
    "retention": _retention,
    "cap_window": _cap_window,
    "stale_offer": _stale_offers,
    "calibration": _calibration,
    "posture_rollup": _posture_rollup,
}


@bp.route("/_ops/runs", methods=["POST"])
def create_run():
    require(["PlatformAdmin"])
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    run_key = data.get("run_key")
    if not run_key:
        fail("ERR_INVALID_REQUEST", "run_key is required.")
    for existing in store.ops_runs.values():
        if existing["run_key"] == run_key:
            fail("ERR_OPS_RUN_KEY_DUPLICATE")
    moment = store.now()
    run = store.make_row({
        "run_key": str(run_key),
        "status": "RUNNING",
        "stages_passed": [],
        "requested_at": moment,
    }, moment)
    store.ops_runs[run["id"]] = run
    passed = []
    for stage in store.OPS_STAGES:
        STAGE_FUNCS[stage]()
        passed.append(stage)
    run["stages_passed"] = passed
    run["status"] = "COMPLETED"
    models.touch(run)
    return ok(models.ops_run(run), store.now(), 201)