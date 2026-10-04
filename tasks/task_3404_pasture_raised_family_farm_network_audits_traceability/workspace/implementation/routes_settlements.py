"""Weekly settlement runs and farmer payment (PRD 3.8).

POST /farm-network/settlement-runs              (NetworkManager, 201)
GET  /farm-network/settlement-runs/{id}         (NetworkManager, PlatformAdmin, 200)
POST /farm-network/settlement-runs/{id}/finalize (NetworkManager, 200)
"""
from flask import Blueprint

import domain
import store
from auth import authenticate, authorize
from clock import now, parse_date
from errors import ApiError
from responses import ok
from serialize import settlement_out
from validation import get_body, f_date, f_int

bp = Blueprint("settlements", __name__, url_prefix="/farm-network")

_NM = ("NetworkManager",)
_GRADES = ("AA", "A", "B")


def _packed_dozens_by_farm_grade(week_start_date):
    """Cartons packed inside the half-open week, grouped farm -> grade ->
    dozens. Each carton carries exactly 1 dozen (PRD 2.9)."""
    start, end = domain.week_bounds(week_start_date)
    per_farm = {}
    for carton in store.cartons.values():
        packed = carton["packed_at"]
        if not (start <= packed < end):
            continue
        lot = store.lots.get(carton["lot_id"])
        if lot is None or lot["grade"] not in _GRADES:
            continue
        buckets = per_farm.setdefault(carton["source_farm_id"], {"AA": 0, "A": 0, "B": 0})
        buckets[lot["grade"]] += carton["dozens"]
    return per_farm


def _line_cents(dozens_by_grade, rate_cents):
    """Pinned rounding order: per-grade subline rounded half up to whole
    cents first, then summed (PRD 2.10)."""
    return sum(domain.payment_subline_cents(dozens_by_grade[g], rate_cents, g)
               for g in _GRADES)


@bp.route("/settlement-runs", methods=["POST"])
def create_settlement():
    uid, role = authenticate()
    authorize(role, _NM)
    data = get_body()
    week_raw, week = f_date(data, "week_start")
    for s in store.settlement_runs.values():
        if s["week_start"] == week_raw:
            raise ApiError("ERR_DUPLICATE_SETTLEMENT", 409,
                           "a settlement run already exists for this week")
    per_farm = _packed_dozens_by_farm_grade(week)
    lines = []
    for farm_id in sorted(per_farm):
        contract = domain.find_covering_contract(farm_id, week, require_active=False)
        if contract is None:
            continue  # no covering contract: no payable line for this farm
        dozens = per_farm[farm_id]
        rate = (contract["commodity_base_cents_per_dozen"]
                + contract["premium_cents_per_dozen"])
        lines.append({
            "farm_id": farm_id,
            "contract_id": contract["id"],
            "dozens_aa": dozens["AA"],
            "dozens_a": dozens["A"],
            "dozens_b": dozens["B"],
            "total_dozens": dozens["AA"] + dozens["A"] + dozens["B"],
            "provisional_cents": _line_cents(dozens, rate),
            "final_cents": None,
        })
    ts = now()
    run = {
        "id": domain.new_id(),
        "week_start": week_raw,
        "status": "CALCULATED",
        "lines": lines,
        "provisional_total_cents": sum(l["provisional_cents"] for l in lines),
        "final_total_cents": None,
        "actual_commodity_base_cents_per_dozen": None,
        "finalized_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.settlement_runs[run["id"]] = run
    return ok(settlement_out(run), 201)


@bp.route("/settlement-runs/<sid>", methods=["GET"])
def get_settlement(sid):
    uid, role = authenticate()
    authorize(role, ("NetworkManager", "PlatformAdmin"))
    return ok(settlement_out(domain.get_settlement_or_404(sid)))


@bp.route("/settlement-runs/<sid>/finalize", methods=["POST"])
def finalize_settlement(sid):
    uid, role = authenticate()
    authorize(role, _NM)
    run = domain.get_settlement_or_404(sid)
    data = get_body()
    actual = f_int(data, "actual_commodity_base_cents_per_dozen", minimum=0)
    if run["status"] != "CALCULATED":
        raise ApiError("ERR_INVALID_STATE", 409, "settlement run is not CALCULATED")
    ts = now()
    # Final variant: published actual base + the contract's premium (PRD 3.8).
    for line in run["lines"]:
        contract = store.contracts.get(line["contract_id"])
        premium = contract["premium_cents_per_dozen"] if contract else 0
        rate = actual + premium
        dozens = {"AA": line["dozens_aa"], "A": line["dozens_a"], "B": line["dozens_b"]}
        line["final_cents"] = _line_cents(dozens, rate)
    run["final_total_cents"] = sum(l["final_cents"] for l in run["lines"])
    run["actual_commodity_base_cents_per_dozen"] = actual
    run["finalized_at"] = ts
    run["status"] = "FINALIZED"
    run["version"] += 1
    run["updated_at"] = ts
    # Judge the week's ACTIVE commitments (calculations.commitment_fill_evaluation).
    week = parse_date(run["week_start"])
    start, end = domain.week_bounds(week)
    for cm in store.commitments.values():
        if cm["status"] != "ACTIVE" or cm["week_start"] != run["week_start"]:
            continue
        delivered = sum(c["dozens"] for c in store.cartons.values()
                        if c["source_farm_id"] == cm["farm_id"]
                        and start <= c["packed_at"] < end)
        threshold = domain.fill_threshold(cm["committed_dozens"])
        cm["delivered_dozens"] = delivered
        cm["fill_rate"] = domain.commitment_fill_rate(delivered, cm["committed_dozens"])
        cm["status"] = "FILLED" if delivered >= threshold else "SHORTFALL"
        cm["version"] += 1
        cm["updated_at"] = ts
    return ok(settlement_out(run))
