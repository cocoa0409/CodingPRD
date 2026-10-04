"""Production runs: scheduling, press windows, striking, inspection, rework
(PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import serialize
import store
from helpers import (auth, bad_request, body, envelope, err, list_response,
                     need_datetime, need_enum, need_int, need_str,
                     no_undeclared, not_found, try_datetime)
from routes_denominations import advance_order_after_run_change

bp = Blueprint("runs", __name__)

FACILITIES = {"PHILADELPHIA", "DENVER"}
RUN_NONTERMINAL = {"PLANNED", "STRIKING", "REWORK"}
ERROR_RATE_NUM = 1    # 0.02 as an exact rational: 1/50
ERROR_RATE_DEN = 50
ERROR_WINDOW_DAYS = 30


@bp.route("/mint/production-runs", methods=["POST"])
def create_run():
    auth("ProductionPlanner")
    b = body()
    # Body FK: the parent Federal Reserve order must resolve.
    order = None
    if isinstance(b.get("fed_order_id"), str):
        order = store.db["fed_orders"].get(b["fed_order_id"])
        if order is None:
            not_found("Federal Reserve order not found")
    # Rung 8 (temporal) precedes rung 9 (shape): evaluate the press window
    # whenever both datetimes are present and parseable.
    ps, _raw_ps = try_datetime(b, "planned_start")
    pe, _raw_pe = try_datetime(b, "planned_end")
    facility = b.get("facility")
    press_line = b.get("press_line")
    if ps is not None and pe is not None:
        if pe <= ps:
            err("ERR_PRESS_WINDOW_OVERLAP", 409,
                "planned_end must be after planned_start")
        if isinstance(facility, str) and isinstance(press_line, str):
            for r in store.db["runs"].values():
                if (r["facility"] == facility and r["press_line"] == press_line
                        and r["status"] in RUN_NONTERMINAL
                        and r["_ps"] < pe and ps < r["_pe"]):
                    err("ERR_PRESS_WINDOW_OVERLAP", 409,
                        "Window overlaps a non-terminal run on the same press line")
    # Rung 9: shape.
    no_undeclared(b, {"fed_order_id", "facility", "press_line", "planned_start",
                      "planned_end", "planned_quantity"})
    if order is None:
        need_str(b, "fed_order_id")  # raises the missing/invalid-type 400
        not_found("Federal Reserve order not found")
    facility = need_enum(b, "facility", FACILITIES)
    press_line = need_str(b, "press_line")
    dt_ps, raw_ps = need_datetime(b, "planned_start")
    dt_pe, raw_pe = need_datetime(b, "planned_end")
    qty = need_int(b, "planned_quantity")
    if qty <= 0:
        err("ERR_QUANTITY_INVALID", 400, "planned_quantity must be greater than zero")
    # Runs inherit their denomination from the parent order.
    if order["denomination_code"] not in store.db["denominations"]:
        err("ERR_UNKNOWN_DENOMINATION", 422, "Unresolvable denomination for order")
    run = store.mint_entity({
        "fed_order_id": order["id"],
        "denomination_code": order["denomination_code"],
        "facility": facility,
        "press_line": press_line,
        "planned_start": raw_ps,
        "planned_end": raw_pe,
        "_ps": dt_ps,
        "_pe": dt_pe,
        "planned_quantity": qty,
        "status": "PLANNED",
        "reserved_blanks": 0,
        "produced_pieces": 0,
        "scrapped_pieces": 0,
        "rework_count": 0,
        "_last_inspection_at": None,
    })
    store.db["runs"][run["id"]] = run
    # First run against a SUBMITTED order moves it to SCHEDULED.
    if order["status"] == "SUBMITTED":
        order["status"] = "SCHEDULED"
        store.bump(order)
    return envelope(serialize.run(run), status=201)


@bp.route("/mint/production-runs", methods=["GET"])
def list_runs():
    auth("ProductionPlanner", "QualityInspector", "FedLiaison", "MintDirector",
         "PlatformAdmin")
    items = list(store.db["runs"].values())
    for param, field in (("fed_order_id", "fed_order_id"),
                         ("facility", "facility"),
                         ("status", "status"),
                         ("denomination_code", "denomination_code")):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[field] == v]
    return list_response(items, serialize.run)


def _get_run_or_404(rid):
    r = store.db["runs"].get(rid)
    if r is None:
        not_found("Production run not found")
    return r


@bp.route("/mint/production-runs/<rid>", methods=["GET"])
def get_run(rid):
    auth("ProductionPlanner", "QualityInspector", "FedLiaison", "MintDirector",
         "PlatformAdmin")
    return envelope(serialize.run(_get_run_or_404(rid)))


def _quality_gate(denom_code):
    """Trailing-30-day error rate: breach iff any pieces were struck in the
    window and error_pieces / struck_pieces >= 0.02 (exact rational compare)."""
    now = store.now_dt()
    window_start = now - timedelta(days=ERROR_WINDOW_DAYS)
    error_pieces = 0
    for c in store.db["error_cases"].values():
        r = store.db["runs"].get(c["production_run_id"])
        if r is None or r["denomination_code"] != denom_code:
            continue
        if window_start <= c["created_at"] <= now:
            error_pieces += c["error_pieces"]
    struck = 0
    for r in store.db["runs"].values():
        if r["denomination_code"] != denom_code:
            continue
        t = r["_last_inspection_at"]
        if t is not None and window_start <= t <= now:
            struck += r["produced_pieces"] + r["scrapped_pieces"]
    return struck > 0 and error_pieces * ERROR_RATE_DEN >= struck * ERROR_RATE_NUM


@bp.route("/mint/production-runs/<rid>/start", methods=["POST"])
def start_run(rid):
    auth("ProductionPlanner")
    run = _get_run_or_404(rid)
    order = store.db["fed_orders"].get(run["fed_order_id"])
    if (run["status"] not in ("PLANNED", "REWORK")
            or order is None or order["status"] not in ("SCHEDULED", "FULFILLING")):
        err("ERR_RUN_NOT_STARTABLE", 422,
            "Run must be PLANNED or REWORK and its order SCHEDULED or FULFILLING")
    denom = store.db["denominations"][run["denomination_code"]]
    # Rung 7: quality gate.
    if _quality_gate(denom["code"]):
        err("ERR_QUALITY_THRESHOLD_BREACH", 422,
            "Denomination trailing-30-day error rate is at or above 0.02")
    # Rung 9: shape.
    no_undeclared(body(), set())
    # Rung 10: blank stock sufficiency.
    if denom["blank_stock_pieces"] < run["planned_quantity"]:
        err("ERR_BLANKS_INSUFFICIENT", 422,
            "Denomination blank stock is below the run's planned quantity")
    denom["blank_stock_pieces"] -= run["planned_quantity"]
    store.bump(denom)
    run["reserved_blanks"] = run["planned_quantity"]
    run["status"] = "STRIKING"
    store.bump(run)
    if order["status"] == "SCHEDULED":
        order["status"] = "FULFILLING"
        store.bump(order)
    return envelope(serialize.run(run))


@bp.route("/mint/production-runs/<rid>/inspect", methods=["POST"])
def inspect_run(rid):
    auth("QualityInspector")
    run = _get_run_or_404(rid)
    if run["status"] != "STRIKING":
        err("ERR_RUN_NOT_INSPECTABLE", 422, "Only a STRIKING run may be inspected")
    b = body()
    no_undeclared(b, {"outcome", "good_pieces"})
    outcome = need_enum(b, "outcome", {"PASS", "FAIL"})
    reserved = run["reserved_blanks"]
    run["_last_inspection_at"] = store.now_dt()
    if outcome == "PASS":
        good = b.get("good_pieces")
        if not isinstance(good, bool) and isinstance(good, int) \
                and 0 <= good <= reserved:
            pass
        else:
            bad_request("good_pieces must be an integer between 0 and reserved_blanks")
        run["produced_pieces"] = good
        run["scrapped_pieces"] += reserved - good
        run["reserved_blanks"] = 0
        run["status"] = "COMPLETED"
        store.bump(run)
        order = store.db["fed_orders"].get(run["fed_order_id"])
        if order is not None:
            order["quantity_fulfilled_pieces"] += good
            advance_order_after_run_change(order)
    else:
        # FAIL: the entire reservation is scrapped; the run returns to REWORK.
        run["scrapped_pieces"] += reserved
        run["reserved_blanks"] = 0
        run["rework_count"] += 1
        run["status"] = "REWORK"
        store.bump(run)
    return envelope(serialize.run(run))


@bp.route("/mint/production-runs/<rid>/cancel", methods=["POST"])
def cancel_run(rid):
    auth("ProductionPlanner")
    run = _get_run_or_404(rid)
    if run["status"] not in ("PLANNED", "REWORK"):
        err("ERR_RUN_NOT_CANCELLABLE", 422,
            "Only a PLANNED or REWORK run may be cancelled")
    no_undeclared(body(), set())
    run["status"] = "CANCELLED"
    store.bump(run)
    order = store.db["fed_orders"].get(run["fed_order_id"])
    if order is not None:
        advance_order_after_run_change(order)
    return envelope(serialize.run(run))
