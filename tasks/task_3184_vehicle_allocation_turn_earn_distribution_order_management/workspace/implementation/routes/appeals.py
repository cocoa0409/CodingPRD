"""Allocation appeals (PRD §3.10)."""
from datetime import timedelta

from flask import Blueprint, request

import errors as err
from db import get_store, now_iso
from middleware import auth_context, require_dealer_owns
from response import success_list, success_object
from services.core import (FILING_WINDOW_DAYS, get_da, is_new_point,
                           recompute_da_pools)
from util import bump, new_entity, now_dt, parse_dt, req_enum, req_int, req_str

bp = Blueprint("appeals", __name__)

ALLOC_ONLY = ["RegionalAllocator"]
READ = ["RegionalAllocator", "Dealer"]


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _get_appeal_or_404(appeal_id):
    appeal = get_store("appeals").get(appeal_id)
    if appeal is None:
        raise err.not_found("appeal not found")
    return appeal


def _market_gap_supported(dealer: dict, run: dict) -> bool:
    """MARKET_GAP eligibility: the dealer's regional share of the line must
    sit below the regional average. Share metric: base_units on this run.
    Regional average: mean base_units across ACTIVE dealers in the same
    region with an allocation on this run."""
    region_id = dealer["region_id"]
    shares = []
    own = None
    for da in get_store("dealer_allocations").values():
        if da["run_id"] != run["id"]:
            continue
        d = get_store("dealers").get(da["dealer_id"])
        if d is None or d["region_id"] != region_id or d["status"] != "ACTIVE":
            continue
        shares.append(da["base_units"])
        if da["dealer_id"] == dealer["id"]:
            own = da["base_units"]
    if own is None or not shares:
        return False
    average = sum(shares) / len(shares)
    return own < average


@bp.post("/wholesale/appeals")
def create_appeal():
    _role, user_id = auth_context(["Dealer"])
    body = _body()
    dealer_id = req_str(body, "dealer_id")
    run_id = req_str(body, "run_id")
    appeal_type = req_enum(body, "appeal_type", ("NEW_POINT", "MARKET_GAP"))
    requested_units = req_int(body, "requested_units", 1)

    require_dealer_owns(user_id, dealer_id)
    dealer = get_store("dealers").get(dealer_id)
    if dealer is None:
        raise err.not_found("dealer not found")
    run = get_store("allocation_runs").get(run_id)
    if run is None:
        raise err.not_found("run not found")

    # Priority 6: run must be PUBLISHED.
    if run["status"] != "PUBLISHED":
        raise err.parent_not_active("run is not PUBLISHED")
    published_at = parse_dt(run["published_at"]) if run.get("published_at") else now_dt()

    # Priority 11: filing window measured from run.published_at.
    if now_dt() > published_at + timedelta(days=FILING_WINDOW_DAYS):
        raise err.window_closed("appeal filing window closed")

    # Priority 15: eligibility at filing.
    if appeal_type == "NEW_POINT":
        if not is_new_point(dealer, published_at):
            raise err.appeal_ineligible("dealer outside new-point grace window")
    else:
        if not _market_gap_supported(dealer, run):
            raise err.appeal_ineligible("market-gap claim not supported")

    appeal = new_entity({
        "dealer_id": dealer_id,
        "run_id": run_id,
        "appeal_type": appeal_type,
        "requested_units": requested_units,
        "granted_units": None,
        "state": "FILED",
        "filed_at": now_iso(),
    })
    get_store("appeals")[appeal["id"]] = appeal
    return success_object(appeal, 201)


@bp.get("/wholesale/appeals")
def list_appeals():
    auth_context(READ)
    rows = list(get_store("appeals").values())
    for key in ("dealer_id", "run_id", "state"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.get("/wholesale/appeals/<aid>")
def get_appeal(aid):
    auth_context(READ)
    return success_object(_get_appeal_or_404(aid))


@bp.post("/wholesale/appeals/<aid>/review")
def review_appeal(aid):
    auth_context(ALLOC_ONLY)
    appeal = _get_appeal_or_404(aid)
    if appeal["state"] != "FILED":
        raise err.invalid_state("appeal is not FILED")
    appeal["state"] = "UNDER_REVIEW"
    bump(appeal)
    return success_object(appeal)


@bp.post("/wholesale/appeals/<aid>/grant")
def grant_appeal(aid):
    auth_context(ALLOC_ONLY)
    appeal = _get_appeal_or_404(aid)
    run = get_store("allocation_runs").get(appeal["run_id"])
    if run is None:
        raise err.not_found("run not found")
    if appeal["state"] != "UNDER_REVIEW":
        raise err.invalid_state("appeal is not UNDER_REVIEW")
    if run["status"] != "PUBLISHED":
        raise err.parent_not_active("run is not PUBLISHED")
    body = _body()
    granted_units = req_int(body, "granted_units", 0)
    expected_run_version = req_int(body, "expected_run_version", 1)
    if expected_run_version != run["version"]:
        raise err.stale_run_version()

    dealer = get_store("dealers").get(appeal["dealer_id"])
    if dealer is None:
        raise err.not_found("dealer not found")
    # NEW_POINT eligibility rechecked at grant (§3.10).
    if appeal["appeal_type"] == "NEW_POINT":
        published_at = parse_dt(run["published_at"]) if run.get("published_at") else now_dt()
        if not is_new_point(dealer, published_at):
            raise err.appeal_ineligible("dealer outside new-point grace window")

    appeal["state"] = "GRANTED"
    appeal["granted_units"] = granted_units
    bump(appeal)
    da = get_da(appeal["run_id"], appeal["dealer_id"])
    if da is not None:
        da["adjustment_units"] += granted_units
        recompute_da_pools(da, run, dealer)
        bump(da)
    bump(run)
    return success_object(appeal)


@bp.post("/wholesale/appeals/<aid>/deny")
def deny_appeal(aid):
    auth_context(ALLOC_ONLY)
    appeal = _get_appeal_or_404(aid)
    if appeal["state"] != "UNDER_REVIEW":
        raise err.invalid_state("appeal is not UNDER_REVIEW")
    appeal["state"] = "DENIED"
    bump(appeal)
    return success_object(appeal)


@bp.post("/wholesale/appeals/<aid>/withdraw")
def withdraw_appeal(aid):
    _role, user_id = auth_context(["Dealer"])
    appeal = _get_appeal_or_404(aid)
    if appeal["state"] != "FILED":
        raise err.invalid_state("appeal is not FILED")
    require_dealer_owns(user_id, appeal["dealer_id"])
    appeal["state"] = "WITHDRAWN"
    bump(appeal)
    return success_object(appeal)
