# Routes: release plans and market screenings.

from decimal import Decimal

from flask import request

import db
import services as svc
from errors import ApiError
from middleware import authorize
from util import (fmt_dt, new_id, now_utc, paginate, parse_dt, round_half_up_cents,
                  success_list, success_obj, touch)


def _get_plan_scoped(film_id, plan_id):
    svc.get_or_404("films", film_id, "film")
    plan = svc.get_or_404("release_plans", plan_id, "release plan")
    if plan["film_id"] != film_id:
        raise ApiError("ERR_NOT_FOUND", "release plan not found for this film")
    return plan


def _mint_screening(plan_id, market_code, weekend_index):
    ts = now_utc()
    screening = {
        "id": new_id(),
        "release_plan_id": plan_id,
        "market_code": market_code,
        "weekend_index": weekend_index,
        "screen_count": 0,
        "weekend_gross_cents": 0,
        "per_screen_avg_cents": 0,
        "status": "SCHEDULED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.stores["market_screenings"][screening["id"]] = screening
    return screening


def _maybe_wide(plan):
    """EXPANDING -> WIDE when current_screen_count >= 600."""
    if plan["status"] != "EXPANDING":
        return
    if plan["current_screen_count"] >= svc.WIDE_SCREEN_THRESHOLD:
        plan["status"] = "WIDE"
        touch(plan)
        film = db.stores["films"].get(plan["film_id"])
        if film is not None and film["release_posture"] in ("PLATFORM", "EXPANDING"):
            film["release_posture"] = "WIDE"
            touch(film)


def register(app):

    @app.post("/films/<film_id>/release-plans")
    def create_plan(film_id):
        authorize("/films/{film_id}/release-plans")
        svc.get_or_404("films", film_id, "film")
        body = svc.get_json_body()
        deal_id = svc.req_str(body, "deal_id")
        deal = svc.get_or_404("deals", deal_id, "deal")
        strategy = svc.req_enum(body, "platform_strategy", svc.STRATEGIES)
        opening_raw = svc.req_str(body, "opening_weekend_date")
        opening = parse_dt(opening_raw, "opening_weekend_date")
        markets = svc.req_list(body, "target_market_codes")
        threshold = svc.req_int(body, "expansion_threshold_psa_cents")
        if threshold <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "expansion_threshold_psa_cents must be > 0")
        if deal["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "deal not found for this film")
        if deal["status"] not in ("EXECUTED", "IN_RELEASE"):
            raise ApiError("ERR_INVALID_STATE", "Deal must be EXECUTED or IN_RELEASE")
        ts = now_utc()
        plan = {
            "id": new_id(),
            "film_id": film_id,
            "deal_id": deal_id,
            "platform_strategy": strategy,
            "opening_weekend_date": fmt_dt(opening),
            "target_market_codes": list(markets),
            "expansion_threshold_psa_cents": threshold,
            "status": "DRAFT",
            "current_screen_count": 0,
            "cumulative_gross_cents": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.stores["release_plans"][plan["id"]] = plan
        return success_obj(plan, 201)

    @app.get("/films/<film_id>/release-plans")
    def list_film_plans(film_id):
        authorize("/films/{film_id}/release-plans")
        svc.get_or_404("films", film_id, "film")
        rows = [p for p in db.stores["release_plans"].values() if p["film_id"] == film_id]
        q = request.args
        if "deal_id" in q:
            rows = [r for r in rows if r["deal_id"] == q["deal_id"]]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.get("/films/<film_id>/release-plans/<plan_id>")
    def get_film_plan(film_id, plan_id):
        authorize("/films/{film_id}/release-plans/{plan_id}")
        plan = _get_plan_scoped(film_id, plan_id)
        return success_obj(plan)

    @app.get("/release-plans/<plan_id>")
    def get_plan(plan_id):
        authorize("/release-plans/{plan_id}")
        plan = svc.get_or_404("release_plans", plan_id, "release plan")
        return success_obj(plan)

    @app.get("/release-plans")
    def list_plans():
        authorize("/release-plans")
        rows = list(db.stores["release_plans"].values())
        q = request.args
        if "film_id" in q:
            rows = [r for r in rows if r["film_id"] == q["film_id"]]
        if "deal_id" in q:
            rows = [r for r in rows if r["deal_id"] == q["deal_id"]]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.post("/films/<film_id>/release-plans/<plan_id>/open")
    def open_plan(film_id, plan_id):
        authorize("/films/{film_id}/release-plans/{plan_id}/open")
        film = svc.get_or_404("films", film_id, "film")
        plan = svc.get_or_404("release_plans", plan_id, "release plan")
        if plan["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "release plan not found for this film")
        if plan["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Release plan is not DRAFT")
        if film["acquisition_status"] != "ACQUIRED":
            raise ApiError("ERR_FILM_NOT_ACQUIRED", "Film is not ACQUIRED")
        booked = [s for s in db.stores["premiere_slots"].values()
                  if s.get("film_id") == film_id and s["status"] == "BOOKED"]
        if not booked:
            raise ApiError("ERR_PREMIERE_REQUIRED", "No BOOKED premiere slot for the film")
        earliest = min(parse_dt(s["screening_starts_at"]) for s in booked)
        if parse_dt(plan["opening_weekend_date"]) < earliest:
            raise ApiError("ERR_OPEN_BEFORE_PREMIERE",
                           "opening_weekend_date precedes earliest BOOKED slot start")
        plan["status"] = "OPENED"
        touch(plan)
        if film["release_posture"] == "PREMIERE_LOCKED":
            film["release_posture"] = "PLATFORM"
        touch(film)
        for market in plan["target_market_codes"]:
            _mint_screening(plan["id"], market, 1)
        return success_obj(plan)

    @app.post("/films/<film_id>/release-plans/<plan_id>/pull")
    def pull_plan(film_id, plan_id):
        authorize("/films/{film_id}/release-plans/{plan_id}/pull")
        film = svc.get_or_404("films", film_id, "film")
        plan = svc.get_or_404("release_plans", plan_id, "release plan")
        if plan["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "release plan not found for this film")
        if plan["status"] not in ("OPENED", "EXPANDING"):
            raise ApiError("ERR_INVALID_STATE", "Release plan is not OPENED or EXPANDING")
        screenings = [s for s in db.stores["market_screenings"].values()
                      if s["release_plan_id"] == plan_id]
        if screenings:
            current_weekend = max(s["weekend_index"] for s in screenings)
            for s in screenings:
                if s["weekend_index"] > current_weekend:
                    raise ApiError(
                        "ERR_PREREQUISITE_NOT_MET",
                        "Future weekend screenings are scheduled",
                    )
        plan["status"] = "PULLED"
        touch(plan)
        for s in screenings:
            if s["status"] == "SCHEDULED":
                s["status"] = "PULLED"
                touch(s)
        touch(film)
        return success_obj(plan)

    # --- Market screenings -------------------------------------------------------

    @app.post("/release-plans/<plan_id>/market-screenings")
    def create_screening(plan_id):
        authorize("/release-plans/{plan_id}/market-screenings")
        plan = svc.get_or_404("release_plans", plan_id, "release plan")
        body = svc.get_json_body()
        market_code = svc.req_str(body, "market_code")
        weekend_index = svc.req_int(body, "weekend_index")
        if weekend_index < 1:
            raise ApiError("ERR_INVALID_REQUEST", "weekend_index must be >= 1")
        screen_count = svc.req_int(body, "screen_count")
        if screen_count <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "screen_count must be > 0")
        gross = svc.req_int(body, "weekend_gross_cents")
        if gross < 0:
            raise ApiError("ERR_INVALID_REQUEST", "weekend_gross_cents must be >= 0")
        if plan["status"] not in ("DRAFT", "OPENED", "EXPANDING"):
            raise ApiError("ERR_INVALID_STATE", "Release plan does not accept new screenings")
        ts = now_utc()
        screening = {
            "id": new_id(),
            "release_plan_id": plan_id,
            "market_code": market_code,
            "weekend_index": weekend_index,
            "screen_count": screen_count,
            "weekend_gross_cents": gross,
            "per_screen_avg_cents": 0,
            "status": "SCHEDULED",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.stores["market_screenings"][screening["id"]] = screening
        svc.recalc_plan(plan)
        return success_obj(screening, 201)

    @app.get("/release-plans/<plan_id>/market-screenings")
    def list_plan_screenings(plan_id):
        authorize("/release-plans/{plan_id}/market-screenings")
        svc.get_or_404("release_plans", plan_id, "release plan")
        rows = [s for s in db.stores["market_screenings"].values()
                if s["release_plan_id"] == plan_id]
        q = request.args
        if "market_code" in q:
            rows = [r for r in rows if r["market_code"] == q["market_code"]]
        if "weekend_index" in q:
            try:
                wi = int(q["weekend_index"])
            except ValueError:
                raise ApiError("ERR_INVALID_REQUEST", "weekend_index must be an integer")
            rows = [r for r in rows if r["weekend_index"] == wi]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.post("/release-plans/<plan_id>/market-screenings/<screening_id>/report")
    def report_screening(plan_id, screening_id):
        authorize("/release-plans/{plan_id}/market-screenings/{screening_id}/report")
        plan = svc.get_or_404("release_plans", plan_id, "release plan")
        screening = svc.get_or_404("market_screenings", screening_id, "market screening")
        if screening["release_plan_id"] != plan_id:
            raise ApiError("ERR_NOT_FOUND", "market screening not found for this plan")
        if screening["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Market screening is not SCHEDULED")
        if plan["status"] not in ("OPENED", "EXPANDING"):
            raise ApiError("ERR_INVALID_STATE", "Release plan is not OPENED or EXPANDING")
        body = svc.get_json_body()
        screen_count = svc.req_int(body, "screen_count")
        if screen_count <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "screen_count must be > 0")
        gross = svc.req_int(body, "weekend_gross_cents")
        if gross < 0:
            raise ApiError("ERR_INVALID_REQUEST", "weekend_gross_cents must be >= 0")
        screening["screen_count"] = screen_count
        screening["weekend_gross_cents"] = gross
        psa = round_half_up_cents(Decimal(gross) / Decimal(screen_count))
        screening["per_screen_avg_cents"] = psa
        screening["status"] = "REPORTED"
        touch(screening)
        svc.recalc_plan(plan)
        if (psa >= plan["expansion_threshold_psa_cents"]
                and plan["platform_strategy"] != "WIDE_DIRECT"
                and plan["status"] == "OPENED"):
            plan["status"] = "EXPANDING"
            touch(plan)
            screening["status"] = "EXPANSION_TRIGGERED"
            touch(screening)
            film = db.stores["films"].get(plan["film_id"])
            if film is not None and film["release_posture"] == "PLATFORM":
                film["release_posture"] = "EXPANDING"
                touch(film)
        _maybe_wide(plan)
        return success_obj(screening)

    @app.get("/market-screenings/<screening_id>")
    def get_screening(screening_id):
        authorize("/market-screenings/{screening_id}")
        screening = svc.get_or_404("market_screenings", screening_id, "market screening")
        return success_obj(screening)

    @app.get("/market-screenings")
    def list_screenings():
        authorize("/market-screenings")
        rows = list(db.stores["market_screenings"].values())
        q = request.args
        if "release_plan_id" in q:
            rows = [r for r in rows if r["release_plan_id"] == q["release_plan_id"]]
        if "market_code" in q:
            rows = [r for r in rows if r["market_code"] == q["market_code"]]
        if "weekend_index" in q:
            try:
                wi = int(q["weekend_index"])
            except ValueError:
                raise ApiError("ERR_INVALID_REQUEST", "weekend_index must be an integer")
            rows = [r for r in rows if r["weekend_index"] == wi]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)
