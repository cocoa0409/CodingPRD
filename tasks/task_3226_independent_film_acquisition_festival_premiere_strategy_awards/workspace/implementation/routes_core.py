# Routes: clock, films, territories, festivals.

from flask import request

import db
import services as svc
from errors import ApiError
from middleware import authorize
from util import (fmt_dt, new_id, now_utc, paginate, parse_dt, success_list,
                  success_obj, touch, clock_dt)


def register(app):

    @app.post("/_clock/set_current_utc")
    def set_clock():
        authorize("/_clock/set_current_utc")
        body = svc.get_json_body()
        current_utc = svc.req_str(body, "current_utc")
        parse_dt(current_utc, "current_utc")
        db.logical_clock = current_utc
        svc.reevaluate_clock_transitions()
        return success_obj({"current_utc": db.logical_clock}, 200)

    # --- Films -------------------------------------------------------------

    @app.post("/films")
    def create_film():
        authorize("/films")
        body = svc.get_json_body()
        title = svc.req_str(body, "title")
        director_name = svc.req_str(body, "director_name")
        principal_cast = svc.req_list(body, "principal_cast")
        genre = svc.req_enum(body, "genre", svc.GENRES)
        runtime = svc.req_int(body, "runtime_minutes")
        if runtime <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "runtime_minutes must be > 0")
        budget = svc.req_int(body, "production_budget_cents")
        if budget < 0:
            raise ApiError("ERR_INVALID_REQUEST", "production_budget_cents must be >= 0")
        ts = now_utc()
        film = {
            "id": new_id(),
            "title": title,
            "director_name": director_name,
            "principal_cast": list(principal_cast),
            "genre": genre,
            "runtime_minutes": runtime,
            "production_budget_cents": budget,
            "acquisition_status": "SHOPPING",
            "release_posture": "PRE_ACQUISITION",
            "awards_posture": "INELIGIBLE",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.stores["films"][film["id"]] = film
        return success_obj(film, 201)

    @app.get("/films/<film_id>")
    def get_film(film_id):
        authorize("/films/{film_id}")
        film = svc.get_or_404("films", film_id, "film")
        svc.refresh_film(film)
        return success_obj(film)

    @app.get("/films")
    def list_films():
        authorize("/films")
        rows = []
        for f in db.stores["films"].values():
            svc.refresh_film(f)
            rows.append(f)
        q = request.args
        if "acquisition_status" in q:
            rows = [r for r in rows if r["acquisition_status"] == q["acquisition_status"]]
        if "release_posture" in q:
            rows = [r for r in rows if r["release_posture"] == q["release_posture"]]
        if "genre" in q:
            rows = [r for r in rows if r["genre"] == q["genre"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.get("/films/<film_id>/premiere-slots")
    def list_film_premiere_slots(film_id):
        authorize("/films/{film_id}/premiere-slots")
        svc.get_or_404("films", film_id, "film")
        rows = [s for s in db.stores["premiere_slots"].values() if s.get("film_id") == film_id]
        q = request.args
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.post("/films/<film_id>/pass")
    def pass_film(film_id):
        authorize("/films/{film_id}/pass")
        film = svc.get_or_404("films", film_id, "film")
        if film["acquisition_status"] != "SHOPPING":
            raise ApiError("ERR_INVALID_STATE", "Film is not in SHOPPING")
        for o in db.stores["offers"].values():
            if o["film_id"] == film_id:
                svc.refresh_offer(o)
        has_open = any(
            o["status"] == "OPEN"
            for o in db.stores["offers"].values()
            if o["film_id"] == film_id
        )
        if has_open:
            raise ApiError("ERR_NO_OPEN_OFFERS_TO_PASS", "Cannot pass while an OPEN offer exists")
        film["acquisition_status"] = "PASSED"
        touch(film)
        return success_obj(film)

    @app.post("/films/<film_id>/archive")
    def archive_film(film_id):
        authorize("/films/{film_id}/archive")
        film = svc.get_or_404("films", film_id, "film")
        svc.refresh_film(film)
        if film["release_posture"] != "HOME_WINDOW":
            raise ApiError("ERR_INVALID_STATE", "Film is not in HOME_WINDOW")
        for plan in db.stores["release_plans"].values():
            if plan["film_id"] == film_id and plan["status"] in ("OPENED", "EXPANDING"):
                raise ApiError(
                    "ERR_PREREQUISITE_NOT_MET",
                    "A release plan is still OPENED or EXPANDING",
                )
        for c in db.stores["awards_campaigns"].values():
            if c["film_id"] == film_id and c["status"] != "CONCLUDED":
                raise ApiError(
                    "ERR_PREREQUISITE_NOT_MET",
                    "Not all awards campaigns are CONCLUDED",
                )
        film["release_posture"] = "ARCHIVED"
        touch(film)
        return success_obj(film)

    # --- Territories ---------------------------------------------------------

    @app.post("/territories")
    def create_territory():
        authorize("/territories")
        body = svc.get_json_body()
        code = svc.req_str(body, "code")
        if not (2 <= len(code) <= 8) or code != code.upper():
            raise ApiError("ERR_INVALID_REQUEST", "code must be 2-8 uppercase characters")
        name = svc.req_str(body, "name")
        eligible = svc.req_bool(body, "is_home_ent_eligible")
        for t in db.stores["territories"].values():
            if t["code"] == code:
                raise ApiError("ERR_INVALID_REQUEST", "territory code must be unique")
        ts = now_utc()
        terr = {
            "id": new_id(),
            "code": code,
            "name": name,
            "is_home_ent_eligible": eligible,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.stores["territories"][terr["id"]] = terr
        return success_obj(terr, 201)

    @app.get("/territories")
    def list_territories():
        authorize("/territories")
        rows = svc.sort_rows(list(db.stores["territories"].values()))
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.get("/territories/<territory_id>")
    def get_territory(territory_id):
        authorize("/territories/{territory_id}")
        terr = db.stores["territories"].get(territory_id)
        if terr is None:
            for t in db.stores["territories"].values():
                if t["code"] == territory_id:
                    terr = t
                    break
        if terr is None:
            raise ApiError("ERR_NOT_FOUND", "territory not found")
        return success_obj(terr)

    # --- Festivals ------------------------------------------------------------

    @app.post("/festivals")
    def create_festival():
        authorize("/festivals")
        body = svc.get_json_body()
        code = svc.req_str(body, "code")
        name = svc.req_str(body, "name")
        start_raw = svc.req_str(body, "start_date")
        end_raw = svc.req_str(body, "end_date")
        start = parse_dt(start_raw, "start_date")
        end = parse_dt(end_raw, "end_date")
        tier = svc.req_enum(body, "prestige_tier", svc.PRESTIGE_TIERS)
        embargo = svc.req_int(body, "default_review_embargo_hours")
        if embargo < 0:
            raise ApiError("ERR_INVALID_REQUEST", "default_review_embargo_hours must be >= 0")
        for f in db.stores["festivals"].values():
            if f["code"] == code:
                raise ApiError("ERR_INVALID_REQUEST", "festival code must be unique")
        if end <= start:
            raise ApiError("ERR_INVALID_WINDOW", "end_date must be after start_date")
        ts = now_utc()
        fest = {
            "id": new_id(),
            "code": code,
            "name": name,
            "start_date": fmt_dt(start),
            "end_date": fmt_dt(end),
            "prestige_tier": tier,
            "default_review_embargo_hours": embargo,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.stores["festivals"][fest["id"]] = fest
        return success_obj(fest, 201)

    @app.get("/festivals/<festival_id>")
    def get_festival(festival_id):
        authorize("/festivals/{festival_id}")
        fest = svc.get_or_404("festivals", festival_id, "festival")
        return success_obj(fest)
