# Routes: acquisition offers, deals, rights grants.

from datetime import timedelta

from flask import request

import db
import services as svc
from errors import ApiError
from middleware import authorize
from util import (fmt_dt, new_id, now_utc, paginate, parse_dt, success_list,
                  success_obj, touch, clock_dt)


def _validate_offer_payload(body):
    buyer_code = svc.req_str(body, "buyer_code")
    upfront = svc.req_int(body, "upfront_price_cents")
    if upfront <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "upfront_price_cents must be > 0")
    pct = svc.req_num(body, "backend_participation_pct")
    if pct < 0 or pct > 1:
        raise ApiError("ERR_INVALID_REQUEST", "backend_participation_pct must be in [0, 1]")
    pa_commit = svc.req_int(body, "prints_advertising_commit_cents")
    if pa_commit < 0:
        raise ApiError("ERR_INVALID_REQUEST", "prints_advertising_commit_cents must be >= 0")
    territories = svc.req_list(body, "requested_territory_codes")
    if not territories:
        raise ApiError("ERR_INVALID_REQUEST", "requested_territory_codes must be non-empty")
    known_codes = {t["code"] for t in db.stores["territories"].values()}
    for code in territories:
        if code not in known_codes:
            raise ApiError("ERR_TERRITORY_UNKNOWN", "unknown territory code: %s" % code)
    windows = svc.req_list(body, "requested_windows")
    if not windows:
        raise ApiError("ERR_INVALID_REQUEST", "requested_windows must be non-empty")
    for w in windows:
        if w not in svc.WINDOWS:
            raise ApiError("ERR_INVALID_REQUEST", "invalid window: %s" % w)
    expiry_raw = svc.req_str(body, "expiry_at")
    expiry = parse_dt(expiry_raw, "expiry_at")
    if expiry <= clock_dt():
        raise ApiError("ERR_INVALID_WINDOW", "expiry_at must be in the future")
    return {
        "buyer_code": buyer_code,
        "upfront_price_cents": upfront,
        "backend_participation_pct": pct,
        "prints_advertising_commit_cents": pa_commit,
        "requested_territory_codes": list(territories),
        "requested_windows": list(windows),
        "expiry_at": fmt_dt(expiry),
    }


def _offer_rounds(film_id):
    return [o["round_number"] for o in db.stores["offers"].values()
            if o["film_id"] == film_id]


def _mint_offer(film_id, fields, round_number, created_by):
    ts = now_utc()
    offer = {
        "id": new_id(),
        "film_id": film_id,
        "buyer_code": fields["buyer_code"],
        "round_number": round_number,
        "upfront_price_cents": fields["upfront_price_cents"],
        "backend_participation_pct": fields["backend_participation_pct"],
        "prints_advertising_commit_cents": fields["prints_advertising_commit_cents"],
        "requested_territory_codes": fields["requested_territory_codes"],
        "requested_windows": fields["requested_windows"],
        "expiry_at": fields["expiry_at"],
        "status": "OPEN",
        "created_by": created_by,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.stores["offers"][offer["id"]] = offer
    return offer


def register(app):

    @app.post("/films/<film_id>/offers")
    def create_offer(film_id):
        user_id, _ = authorize("/films/{film_id}/offers")
        film = svc.get_or_404("films", film_id, "film")
        if film["acquisition_status"] not in ("SHOPPING", "UNDER_NEGOTIATION"):
            raise ApiError("ERR_INVALID_STATE", "Film is not open to offers")
        fields = _validate_offer_payload(svc.get_json_body())
        rounds = _offer_rounds(film_id)
        round_number = (max(rounds) + 1) if rounds else 1
        offer = _mint_offer(film_id, fields, round_number, user_id)
        if film["acquisition_status"] == "SHOPPING":
            film["acquisition_status"] = "UNDER_NEGOTIATION"
        touch(film)
        return success_obj(offer, 201)

    @app.get("/films/<film_id>/offers")
    def list_film_offers(film_id):
        authorize("/films/{film_id}/offers")
        svc.get_or_404("films", film_id, "film")
        rows = []
        for o in db.stores["offers"].values():
            if o["film_id"] == film_id:
                svc.refresh_offer(o)
                rows.append(o)
        if "status" in request.args:
            rows = [r for r in rows if r["status"] == request.args["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.get("/films/<film_id>/offers/<offer_id>")
    def get_film_offer(film_id, offer_id):
        authorize("/films/{film_id}/offers/{offer_id}")
        svc.get_or_404("films", film_id, "film")
        offer = svc.get_or_404("offers", offer_id, "offer")
        if offer["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "offer not found for this film")
        svc.refresh_offer(offer)
        return success_obj(offer)

    @app.get("/offers/<offer_id>")
    def get_offer(offer_id):
        authorize("/offers/{offer_id}")
        offer = svc.get_or_404("offers", offer_id, "offer")
        svc.refresh_offer(offer)
        return success_obj(offer)

    @app.get("/offers")
    def list_offers():
        authorize("/offers")
        rows = []
        for o in db.stores["offers"].values():
            svc.refresh_offer(o)
            rows.append(o)
        q = request.args
        if "film_id" in q:
            rows = [r for r in rows if r["film_id"] == q["film_id"]]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.post("/films/<film_id>/offers/<offer_id>/counter")
    def counter_offer(film_id, offer_id):
        user_id, _ = authorize("/films/{film_id}/offers/{offer_id}/counter")
        svc.get_or_404("films", film_id, "film")
        offer = svc.get_or_404("offers", offer_id, "offer")
        if offer["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "offer not found for this film")
        svc.refresh_offer(offer)
        if offer["status"] == "EXPIRED":
            raise ApiError("ERR_OFFER_EXPIRED", "Offer has expired")
        if offer["status"] != "OPEN":
            raise ApiError("ERR_OFFER_ALREADY_TERMINAL", "Offer is in a terminal state")
        fields = _validate_offer_payload(svc.get_json_body())
        offer["status"] = "COUNTERED"
        touch(offer)
        new_offer = _mint_offer(film_id, fields, offer["round_number"] + 1, user_id)
        film = db.stores["films"][film_id]
        touch(film)
        return success_obj(new_offer, 201)

    @app.post("/films/<film_id>/offers/<offer_id>/accept")
    def accept_offer(film_id, offer_id):
        user_id, _ = authorize("/films/{film_id}/offers/{offer_id}/accept")
        film = svc.get_or_404("films", film_id, "film")
        offer = svc.get_or_404("offers", offer_id, "offer")
        if offer["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "offer not found for this film")
        svc.refresh_offer(offer)
        if offer["status"] == "EXPIRED":
            raise ApiError("ERR_OFFER_EXPIRED", "Offer has expired")
        if offer["status"] != "OPEN":
            raise ApiError("ERR_OFFER_ALREADY_TERMINAL", "Offer is in a terminal state")
        body = svc.get_json_body()
        expected = svc.req_int(body, "expected_film_version")
        if expected != film["version"]:
            raise ApiError("ERR_STALE_VERSION", "expected_film_version does not match Film.version")
        if offer["created_by"] == user_id:
            raise ApiError(
                "ERR_DUTY_SEPARATION_VIOLATION",
                "The user who created the offer cannot accept it",
            )
        # Rights-window scope: HOME_ENT requires eligible territory
        terr_by_code = {t["code"]: t for t in db.stores["territories"].values()}
        for code in offer["requested_territory_codes"]:
            terr = terr_by_code.get(code)
            if terr is None:
                raise ApiError("ERR_TERRITORY_UNKNOWN", "unknown territory code: %s" % code)
            if "HOME_ENT" in offer["requested_windows"] and not terr["is_home_ent_eligible"]:
                raise ApiError(
                    "ERR_WINDOW_NOT_AVAILABLE",
                    "HOME_ENT not available for territory %s" % code,
                )
        # One live deal per film
        for d in db.stores["deals"].values():
            if d["film_id"] == film_id and d["status"] in ("EXECUTED", "IN_RELEASE"):
                raise ApiError("ERR_DEAL_ALREADY_EXISTS", "A live deal already exists for this film")
        # Commit cascades
        offer["status"] = "ACCEPTED"
        touch(offer)
        for sibling in db.stores["offers"].values():
            if sibling["film_id"] == film_id and sibling["id"] != offer_id and sibling["status"] == "OPEN":
                sibling["status"] = "REJECTED"
                touch(sibling)
        close_dt = clock_dt()
        ts = now_utc()
        deal = {
            "id": new_id(),
            "film_id": film_id,
            "source_offer_id": offer_id,
            "buyer_code": offer["buyer_code"],
            "upfront_price_cents": offer["upfront_price_cents"],
            "backend_participation_pct": offer["backend_participation_pct"],
            "prints_advertising_commit_cents": offer["prints_advertising_commit_cents"],
            "status": "EXECUTED",
            "pa_spent_theatrical_cents": 0,
            "pa_spent_awards_cents": 0,
            "pa_shortfall_cents": offer["prints_advertising_commit_cents"],
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.stores["deals"][deal["id"]] = deal
        grant_end = close_dt + timedelta(days=svc.TEN_YEARS_DAYS)
        for code in offer["requested_territory_codes"]:
            for window in offer["requested_windows"]:
                gts = now_utc()
                grant = {
                    "id": new_id(),
                    "deal_id": deal["id"],
                    "territory_code": code,
                    "window": window,
                    "window_starts_at": fmt_dt(close_dt),
                    "window_ends_at": fmt_dt(grant_end),
                    "status": "GRANTED",
                    "created_at": gts,
                    "updated_at": gts,
                    "version": 1,
                }
                db.stores["rights_grants"][grant["id"]] = grant
        film["acquisition_status"] = "ACQUIRED"
        if "THEATRICAL" in offer["requested_windows"] and film["awards_posture"] == "INELIGIBLE":
            film["awards_posture"] = "ELIGIBLE"
        touch(film)
        return success_obj(deal, 201)

    @app.post("/films/<film_id>/offers/<offer_id>/reject")
    def reject_offer(film_id, offer_id):
        authorize("/films/{film_id}/offers/{offer_id}/reject")
        svc.get_or_404("films", film_id, "film")
        offer = svc.get_or_404("offers", offer_id, "offer")
        if offer["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "offer not found for this film")
        svc.refresh_offer(offer)
        if offer["status"] != "OPEN":
            raise ApiError("ERR_OFFER_ALREADY_TERMINAL", "Offer is in a terminal state")
        offer["status"] = "REJECTED"
        touch(offer)
        svc._maybe_collapse_negotiation(film_id)
        return success_obj(offer)

    @app.post("/films/<film_id>/offers/<offer_id>/withdraw")
    def withdraw_offer(film_id, offer_id):
        authorize("/films/{film_id}/offers/{offer_id}/withdraw")
        svc.get_or_404("films", film_id, "film")
        offer = svc.get_or_404("offers", offer_id, "offer")
        if offer["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "offer not found for this film")
        svc.refresh_offer(offer)
        if offer["status"] != "OPEN":
            raise ApiError("ERR_OFFER_ALREADY_TERMINAL", "Offer is in a terminal state")
        offer["status"] = "WITHDRAWN"
        touch(offer)
        svc._maybe_collapse_negotiation(film_id)
        return success_obj(offer)

    # --- Deals ----------------------------------------------------------------

    @app.get("/deals/<deal_id>")
    def get_deal(deal_id):
        authorize("/deals/{deal_id}")
        deal = svc.get_or_404("deals", deal_id, "deal")
        return success_obj(deal)

    @app.get("/deals")
    def list_deals():
        authorize("/deals")
        rows = list(db.stores["deals"].values())
        q = request.args
        if "source_offer_id" in q:
            rows = [r for r in rows if r["source_offer_id"] == q["source_offer_id"]]
        if "film_id" in q:
            rows = [r for r in rows if r["film_id"] == q["film_id"]]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.get("/films/<film_id>/deals")
    def list_film_deals(film_id):
        authorize("/films/{film_id}/deals")
        svc.get_or_404("films", film_id, "film")
        rows = [d for d in db.stores["deals"].values() if d["film_id"] == film_id]
        if "status" in request.args:
            rows = [r for r in rows if r["status"] == request.args["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.post("/deals/<deal_id>/report-theatrical-spend")
    def report_theatrical_spend(deal_id):
        authorize("/deals/{deal_id}/report-theatrical-spend")
        deal = svc.get_or_404("deals", deal_id, "deal")
        body = svc.get_json_body()
        amount = svc.req_int(body, "amount_cents")
        if amount <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be > 0")
        deal["pa_spent_theatrical_cents"] += amount
        svc.recalc_deal_pa(deal)
        return success_obj(deal)

    # --- Rights grants -----------------------------------------------------------

    @app.get("/rights-grants/<grant_id>")
    def get_rights_grant(grant_id):
        authorize("/rights-grants/{grant_id}")
        grant = svc.get_or_404("rights_grants", grant_id, "rights grant")
        return success_obj(grant)

    @app.get("/rights-grants")
    def list_rights_grants():
        authorize("/rights-grants")
        rows = list(db.stores["rights_grants"].values())
        q = request.args
        if "deal_id" in q:
            rows = [r for r in rows if r["deal_id"] == q["deal_id"]]
        if "territory_code" in q:
            rows = [r for r in rows if r["territory_code"] == q["territory_code"]]
        if "window" in q:
            rows = [r for r in rows if r["window"] == q["window"]]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.get("/deals/<deal_id>/rights-grants")
    def list_deal_rights_grants(deal_id):
        authorize("/deals/{deal_id}/rights-grants")
        svc.get_or_404("deals", deal_id, "deal")
        rows = [g for g in db.stores["rights_grants"].values() if g["deal_id"] == deal_id]
        q = request.args
        if "territory_code" in q:
            rows = [r for r in rows if r["territory_code"] == q["territory_code"]]
        if "window" in q:
            rows = [r for r in rows if r["window"] == q["window"]]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)
