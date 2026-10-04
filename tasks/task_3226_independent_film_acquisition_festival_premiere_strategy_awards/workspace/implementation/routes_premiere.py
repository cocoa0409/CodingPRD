# Routes: premiere slots (declare, hold, book, release-hold, cancel, reads).

from flask import request

import db
import services as svc
from errors import ApiError
from middleware import authorize
from util import (fmt_dt, new_id, now_utc, paginate, parse_dt, success_list,
                  success_obj, touch)


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _get_slot_scoped(festival_id, slot_id):
    svc.get_or_404("festivals", festival_id, "festival")
    slot = svc.get_or_404("premiere_slots", slot_id, "premiere slot")
    if slot["festival_id"] != festival_id:
        raise ApiError("ERR_NOT_FOUND", "premiere slot not found for this festival")
    return slot


def register(app):

    @app.post("/festivals/<festival_id>/premiere-slots")
    def create_slot(festival_id):
        authorize("/festivals/{festival_id}/premiere-slots")
        fest = svc.get_or_404("festivals", festival_id, "festival")
        body = svc.get_json_body()
        section = svc.req_enum(body, "section", svc.SECTIONS)
        starts_raw = svc.req_str(body, "screening_starts_at")
        ends_raw = svc.req_str(body, "screening_ends_at")
        lifts_raw = svc.req_str(body, "review_embargo_lifts_at")
        starts = parse_dt(starts_raw, "screening_starts_at")
        ends = parse_dt(ends_raw, "screening_ends_at")
        lifts = parse_dt(lifts_raw, "review_embargo_lifts_at")
        if ends <= starts:
            raise ApiError("ERR_INVALID_WINDOW", "screening_ends_at must be after screening_starts_at")
        if lifts < ends:
            raise ApiError("ERR_INVALID_WINDOW", "review_embargo_lifts_at must be >= screening_ends_at")
        fest_start = parse_dt(fest["start_date"])
        fest_end = parse_dt(fest["end_date"])
        if starts < fest_start or ends > fest_end:
            raise ApiError("ERR_INVALID_WINDOW", "screening must lie inside the festival window")
        delay_hours = int((lifts - ends).total_seconds() // 3600)
        if delay_hours > 168:
            raise ApiError("ERR_EMBARGO_TOO_LONG", "embargo delay exceeds 168 hours")
        ts = now_utc()
        slot = {
            "id": new_id(),
            "festival_id": festival_id,
            "film_id": None,
            "section": section,
            "screening_starts_at": fmt_dt(starts),
            "screening_ends_at": fmt_dt(ends),
            "review_embargo_lifts_at": fmt_dt(lifts),
            "status": "OPEN",
            "cachet_score": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.stores["premiere_slots"][slot["id"]] = slot
        return success_obj(slot, 201)

    @app.get("/festivals/<festival_id>/premiere-slots")
    def list_festival_slots(festival_id):
        authorize("/festivals/{festival_id}/premiere-slots")
        svc.get_or_404("festivals", festival_id, "festival")
        rows = [s for s in db.stores["premiere_slots"].values()
                if s["festival_id"] == festival_id]
        q = request.args
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        if "section" in q:
            rows = [r for r in rows if r["section"] == q["section"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.get("/festivals/<festival_id>/premiere-slots/<slot_id>")
    def get_slot_nested(festival_id, slot_id):
        authorize("/festivals/{festival_id}/premiere-slots/{slot_id}")
        slot = _get_slot_scoped(festival_id, slot_id)
        return success_obj(slot)

    @app.get("/premiere-slots/<slot_id>")
    def get_slot(slot_id):
        authorize("/premiere-slots/{slot_id}")
        slot = svc.get_or_404("premiere_slots", slot_id, "premiere slot")
        return success_obj(slot)

    @app.get("/premiere-slots")
    def list_slots():
        authorize("/premiere-slots")
        rows = list(db.stores["premiere_slots"].values())
        q = request.args
        if "festival_id" in q:
            rows = [r for r in rows if r["festival_id"] == q["festival_id"]]
        if "film_id" in q:
            rows = [r for r in rows if r.get("film_id") == q["film_id"]]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.post("/festivals/<festival_id>/premiere-slots/<slot_id>/hold")
    def hold_slot(festival_id, slot_id):
        authorize("/festivals/{festival_id}/premiere-slots/{slot_id}/hold")
        slot = _get_slot_scoped(festival_id, slot_id)
        body = svc.get_json_body()
        film_id = svc.req_str(body, "film_id")
        svc.get_or_404("films", film_id, "film")
        if slot["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Slot is not OPEN")
        fest = db.stores["festivals"][festival_id]
        slot["status"] = "HELD"
        slot["film_id"] = film_id
        slot["cachet_score"] = svc.compute_cachet(slot, fest)
        touch(slot)
        return success_obj(slot)

    @app.post("/festivals/<festival_id>/premiere-slots/<slot_id>/book")
    def book_slot(festival_id, slot_id):
        authorize("/festivals/{festival_id}/premiere-slots/{slot_id}/book")
        slot = _get_slot_scoped(festival_id, slot_id)
        if slot["status"] in ("BOOKED", "CANCELLED"):
            raise ApiError("ERR_SLOT_ALREADY_BOOKED", "Slot already BOOKED or CANCELLED")
        if slot["status"] != "HELD":
            raise ApiError("ERR_SLOT_NOT_HELD", "Slot must be HELD before booking")
        film = db.stores["films"].get(slot["film_id"])
        if film is None:
            raise ApiError("ERR_NOT_FOUND", "film not found")
        body = svc.get_json_body()
        expected = svc.req_int(body, "expected_film_version")
        if expected != film["version"]:
            raise ApiError("ERR_STALE_VERSION", "expected_film_version does not match Film.version")
        if film["acquisition_status"] != "ACQUIRED":
            raise ApiError("ERR_FILM_NOT_ACQUIRED", "Film is not ACQUIRED")
        s_start = parse_dt(slot["screening_starts_at"])
        s_end = parse_dt(slot["screening_ends_at"])
        for other in db.stores["premiere_slots"].values():
            if other["id"] == slot_id or other["status"] != "BOOKED":
                continue
            o_start = parse_dt(other["screening_starts_at"])
            o_end = parse_dt(other["screening_ends_at"])
            if not _overlaps(s_start, s_end, o_start, o_end):
                continue
            if other.get("film_id") == film["id"]:
                raise ApiError("ERR_FILM_DOUBLE_BOOKED",
                               "Another BOOKED slot on the same film overlaps")
            if other["festival_id"] == festival_id:
                raise ApiError("ERR_VENUE_OVERLAP",
                               "Another BOOKED slot at the same festival overlaps")
        fest = db.stores["festivals"][festival_id]
        slot["status"] = "BOOKED"
        slot["cachet_score"] = svc.compute_cachet(slot, fest)
        touch(slot)
        if film["release_posture"] == "PRE_ACQUISITION":
            film["release_posture"] = "PREMIERE_LOCKED"
        touch(film)
        return success_obj(slot)

    @app.post("/festivals/<festival_id>/premiere-slots/<slot_id>/release-hold")
    def release_hold(festival_id, slot_id):
        authorize("/festivals/{festival_id}/premiere-slots/{slot_id}/release-hold")
        slot = _get_slot_scoped(festival_id, slot_id)
        if slot["status"] != "HELD":
            raise ApiError("ERR_INVALID_STATE", "Slot is not HELD")
        slot["status"] = "OPEN"
        slot["film_id"] = None
        slot["cachet_score"] = 0
        touch(slot)
        return success_obj(slot)

    @app.post("/festivals/<festival_id>/premiere-slots/<slot_id>/cancel")
    def cancel_slot(festival_id, slot_id):
        authorize("/festivals/{festival_id}/premiere-slots/{slot_id}/cancel")
        slot = _get_slot_scoped(festival_id, slot_id)
        if slot["status"] not in ("OPEN", "HELD"):
            raise ApiError("ERR_INVALID_STATE", "Slot cannot be cancelled from %s" % slot["status"])
        slot["status"] = "CANCELLED"
        touch(slot)
        return success_obj(slot)
