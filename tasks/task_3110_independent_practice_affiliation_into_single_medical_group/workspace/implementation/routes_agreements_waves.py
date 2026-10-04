"""Routes: affiliation agreements and implementation waves."""

from datetime import date

from flask import Blueprint, request

from db import store
from errors import (
    err_cutover,
    err_invalid,
    err_no_wave,
    err_non_compete,
    err_not_found,
    err_ownership,
    err_stale,
    err_transition,
    err_wave_overlap,
)
from middleware import get_context, require_roles
from response import created, new_entity, ok, paginate, parse_pagination, touch
from validate import (
    body_json,
    optional_number,
    require_bool,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("agreements_waves", __name__)


# ---------------------------------------------------------------------------
# AffiliationAgreement
# ---------------------------------------------------------------------------

def _agreement_seq(practice_id):
    seqs = [
        a["agreement_seq"]
        for a in store.agreements.values()
        if a["practice_id"] == practice_id
    ]
    return (max(seqs) + 1) if seqs else 1


@bp.route("/api/affiliation-agreements", methods=["POST"])
def create_agreement():
    user_id, _role = require_roles("PracticeExecutive")
    data = body_json()
    practice_id = require_str(data, "practice_id")
    distribution_model = require_enum(
        data, "distribution_model", {"NET_OF_SHARED_SERVICES"}
    )
    non_compete_accepted = require_bool(data, "non_compete_accepted")
    expected_practice_version = require_int(data, "expected_practice_version")
    override = None
    if "shared_services_rate_override" in data and data["shared_services_rate_override"] is not None:
        override = optional_number(data, "shared_services_rate_override")
    # Identity binding (priority 3) precedes shape-vs-existence nuance for the
    # PracticeExecutive role: X-User-ID must equal the target practice_id.
    if user_id != practice_id:
        raise err_ownership()
    practice = store.practices.get(practice_id)
    if practice is None:
        raise err_not_found("PRACTICE", "Practice not found")
    if expected_practice_version != practice["version"]:
        raise err_stale()
    if non_compete_accepted is not True:
        raise err_non_compete()
    ag = new_entity()
    ag.update(
        practice_id=practice_id,
        agreement_seq=_agreement_seq(practice_id),
        distribution_model=distribution_model,
        shared_services_rate_override=override,
        non_compete_accepted=non_compete_accepted,
        status="DRAFT",
    )
    store.agreements[ag["id"]] = ag
    touch(practice)  # drafting increments the practice's version
    return created(ag)


@bp.route("/api/affiliation-agreements", methods=["GET"])
def list_agreements():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.agreements.values())
    pid = request.args.get("practice_id")
    if pid is not None:
        items = [a for a in items if a["practice_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    return paginate(items, limit, offset)


@bp.route("/api/affiliation-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    get_context()
    a = store.agreements.get(aid)
    if a is None:
        raise err_not_found("AGREEMENT", "Agreement not found")
    return ok(a)


@bp.route("/api/affiliation-agreements/<aid>/execute", methods=["POST"])
def execute_agreement(aid):
    user_id, _role = require_roles("PracticeExecutive")
    ag = store.agreements.get(aid)
    if ag is None:
        raise err_not_found("AGREEMENT", "Agreement not found")
    if user_id != ag["practice_id"]:
        raise err_ownership()
    if ag["status"] != "DRAFT":
        raise err_transition("Agreement is not DRAFT")
    practice = store.practices.get(ag["practice_id"])
    if practice is None:
        raise err_not_found("PRACTICE", "Practice not found")
    if practice["status"] not in ("PROSPECT", "AFFILIATED"):
        raise err_transition("Practice must be PROSPECT or AFFILIATED")
    wave = None
    if practice["status"] == "PROSPECT":
        candidates = [
            w
            for w in store.waves.values()
            if w["market_id"] == practice["market_id"] and w["status"] == "IN_CUTOVER"
        ]
        if not candidates:
            raise err_no_wave()
        candidates.sort(key=lambda w: (w["cutover_start_date"], w["created_at"], w["id"]))
        wave = candidates[0]
    # side effects: supersede other EXECUTED agreements of this practice
    for other in store.agreements.values():
        if (
            other["id"] != ag["id"]
            and other["practice_id"] == practice["id"]
            and other["status"] == "EXECUTED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    ag["status"] = "EXECUTED"
    touch(ag)
    if practice["status"] == "PROSPECT":
        practice["status"] = "ONBOARDING"
        practice["wave_id"] = wave["id"]
        touch(practice)
    return ok(ag)


# ---------------------------------------------------------------------------
# ImplementationWave
# ---------------------------------------------------------------------------

@bp.route("/api/implementation-waves", methods=["POST"])
def create_wave():
    require_roles("GroupAdministrator")
    data = body_json()
    market_id = require_str(data, "market_id")
    wave_code = require_str(data, "wave_code")
    from validate import require_date

    start = require_date(data, "cutover_start_date")
    end = require_date(data, "cutover_end_date")
    if market_id not in store.markets:
        raise err_not_found("MARKET", "Market not found")
    if not (end > start):
        raise err_cutover("cutover_end_date must be strictly after cutover_start_date")
    # half-open [start, end) overlap against non-COMPLETE waves in same market
    for w in store.waves.values():
        if w["market_id"] != market_id or w["status"] == "COMPLETE":
            continue
        ws = date.fromisoformat(w["cutover_start_date"])
        we = date.fromisoformat(w["cutover_end_date"])
        if start < we and ws < end:
            raise err_wave_overlap()
    w = new_entity()
    w.update(
        market_id=market_id,
        wave_code=wave_code,
        cutover_start_date=start.isoformat(),
        cutover_end_date=end.isoformat(),
        status="PLANNED",
    )
    store.waves[w["id"]] = w
    return created(w)


@bp.route("/api/implementation-waves", methods=["GET"])
def list_waves():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.waves.values())
    mid = request.args.get("market_id")
    if mid is not None:
        items = [w for w in items if w["market_id"] == mid]
    st = request.args.get("status")
    if st is not None:
        items = [w for w in items if w["status"] == st]
    return paginate(items, limit, offset)


@bp.route("/api/implementation-waves/<wid>", methods=["GET"])
def get_wave(wid):
    get_context()
    w = store.waves.get(wid)
    if w is None:
        raise err_not_found("WAVE", "Wave not found")
    return ok(w)


@bp.route("/api/implementation-waves/<wid>/lock", methods=["POST"])
def lock_wave(wid):
    require_roles("GroupAdministrator")
    data = body_json()
    w = store.waves.get(wid)
    if w is None:
        raise err_not_found("WAVE", "Wave not found")
    if "expected_wave_version" not in data:
        raise err_invalid("expected_wave_version is required")
    expected = require_int(data, "expected_wave_version")
    if expected != w["version"]:
        raise err_stale()
    if w["status"] != "PLANNED":
        raise err_transition("Wave is not PLANNED")
    w["status"] = "LOCKED"
    touch(w)
    return ok(w)


@bp.route("/api/implementation-waves/<wid>/start-cutover", methods=["POST"])
def start_cutover(wid):
    require_roles("GroupAdministrator")
    w = store.waves.get(wid)
    if w is None:
        raise err_not_found("WAVE", "Wave not found")
    if w["status"] != "LOCKED":
        raise err_transition("Wave is not LOCKED")
    today = store.clock_date()
    if today < date.fromisoformat(w["cutover_start_date"]):
        raise err_cutover("Clock date is before cutover_start_date")
    w["status"] = "IN_CUTOVER"
    touch(w)
    return ok(w)


@bp.route("/api/implementation-waves/<wid>/complete", methods=["POST"])
def complete_wave(wid):
    require_roles("GroupAdministrator")
    w = store.waves.get(wid)
    if w is None:
        raise err_not_found("WAVE", "Wave not found")
    if w["status"] != "IN_CUTOVER":
        raise err_transition("Wave is not IN_CUTOVER")
    today = store.clock_date()
    if not (today < date.fromisoformat(w["cutover_end_date"])):
        raise err_cutover("Clock date is not before cutover_end_date")
    w["status"] = "COMPLETE"
    touch(w)
    from services import practice_affiliate

    for p in list(store.practices.values()):
        if p["wave_id"] == w["id"] and p["status"] == "ONBOARDING":
            practice_affiliate(p)
    return ok(w)


@bp.route("/api/implementation-waves/<wid>/rollback", methods=["POST"])
def rollback_wave(wid):
    require_roles("GroupAdministrator")
    w = store.waves.get(wid)
    if w is None:
        raise err_not_found("WAVE", "Wave not found")
    if w["status"] != "IN_CUTOVER":
        raise err_transition("Wave is not IN_CUTOVER")
    w["status"] = "LOCKED"
    touch(w)
    return ok(w)
