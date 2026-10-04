# Routes: awards campaigns, campaign spends, talent obligations.

from flask import request

import db
import services as svc
from errors import ApiError
from middleware import authorize
from util import (fmt_dt, new_id, now_utc, paginate, parse_dt, success_list,
                  success_obj, touch, clock_dt)


def _get_campaign_scoped(film_id, campaign_id):
    svc.get_or_404("films", film_id, "film")
    campaign = svc.get_or_404("awards_campaigns", campaign_id, "awards campaign")
    if campaign["film_id"] != film_id:
        raise ApiError("ERR_NOT_FOUND", "awards campaign not found for this film")
    return campaign


def _maybe_campaigning(film):
    if film["awards_posture"] == "ELIGIBLE":
        film["awards_posture"] = "CAMPAIGNING"
        touch(film)


def _maybe_submitted(film):
    if film["awards_posture"] != "CAMPAIGNING":
        return
    any_active = any(
        c["film_id"] == film["id"] and c["status"] == "ACTIVE"
        for c in db.stores["awards_campaigns"].values()
    )
    if not any_active:
        film["awards_posture"] = "SUBMITTED"
        touch(film)


def _maybe_concluded(film):
    if film["awards_posture"] != "SUBMITTED":
        return
    any_submitted = any(
        c["film_id"] == film["id"] and c["status"] == "SUBMITTED"
        for c in db.stores["awards_campaigns"].values()
    )
    if not any_submitted:
        film["awards_posture"] = "CONCLUDED"
        touch(film)


def register(app):

    # --- Awards campaigns ---------------------------------------------------

    @app.post("/films/<film_id>/awards-campaigns")
    def create_campaign(film_id):
        user_id, _ = authorize("/films/{film_id}/awards-campaigns")
        svc.get_or_404("films", film_id, "film")
        body = svc.get_json_body()
        deal_id = svc.req_str(body, "deal_id")
        deal = svc.get_or_404("deals", deal_id, "deal")
        body_enum = svc.req_enum(body, "awards_body", svc.AWARDS_BODIES)
        categories = svc.req_list(body, "target_categories")
        budget = svc.req_int(body, "budget_total_cents")
        if budget <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "budget_total_cents must be > 0")
        if deal["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "deal not found for this film")
        ts = now_utc()
        campaign = {
            "id": new_id(),
            "film_id": film_id,
            "deal_id": deal_id,
            "awards_body": body_enum,
            "target_categories": list(categories),
            "budget_total_cents": budget,
            "budget_screenings_cents": 0,
            "budget_mailers_cents": 0,
            "budget_publicity_cents": 0,
            "budget_remaining_cents": budget,
            "status": "PLANNING",
            "created_by": user_id,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.stores["awards_campaigns"][campaign["id"]] = campaign
        return success_obj(campaign, 201)

    @app.get("/films/<film_id>/awards-campaigns")
    def list_film_campaigns(film_id):
        authorize("/films/{film_id}/awards-campaigns")
        svc.get_or_404("films", film_id, "film")
        rows = [c for c in db.stores["awards_campaigns"].values() if c["film_id"] == film_id]
        q = request.args
        if "deal_id" in q:
            rows = [r for r in rows if r["deal_id"] == q["deal_id"]]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        if "awards_body" in q:
            rows = [r for r in rows if r["awards_body"] == q["awards_body"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.get("/awards-campaigns/<campaign_id>")
    def get_campaign(campaign_id):
        authorize("/awards-campaigns/{campaign_id}")
        campaign = svc.get_or_404("awards_campaigns", campaign_id, "awards campaign")
        return success_obj(campaign)

    @app.get("/awards-campaigns")
    def list_campaigns():
        authorize("/awards-campaigns")
        rows = list(db.stores["awards_campaigns"].values())
        q = request.args
        if "film_id" in q:
            rows = [r for r in rows if r["film_id"] == q["film_id"]]
        if "deal_id" in q:
            rows = [r for r in rows if r["deal_id"] == q["deal_id"]]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        if "awards_body" in q:
            rows = [r for r in rows if r["awards_body"] == q["awards_body"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.post("/films/<film_id>/awards-campaigns/<campaign_id>/activate")
    def activate_campaign(film_id, campaign_id):
        authorize("/films/{film_id}/awards-campaigns/{campaign_id}/activate")
        film = svc.get_or_404("films", film_id, "film")
        campaign = svc.get_or_404("awards_campaigns", campaign_id, "awards campaign")
        if campaign["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "awards campaign not found for this film")
        if campaign["status"] != "PLANNING":
            raise ApiError("ERR_CAMPAIGN_ALREADY_ACTIVE", "Campaign is not PLANNING")
        if film["acquisition_status"] != "ACQUIRED":
            raise ApiError("ERR_FILM_NOT_ACQUIRED", "Film is not ACQUIRED")
        if film["release_posture"] not in ("PREMIERE_LOCKED", "PLATFORM", "EXPANDING", "WIDE"):
            raise ApiError("ERR_PREREQUISITE_NOT_MET",
                           "Campaign cannot activate before premiere or after home window")
        if not campaign["target_categories"]:
            raise ApiError("ERR_PREREQUISITE_NOT_MET", "target_categories must be non-empty")
        if campaign["budget_total_cents"] <= 0:
            raise ApiError("ERR_PREREQUISITE_NOT_MET", "budget_total_cents must be > 0")
        campaign["status"] = "ACTIVE"
        touch(campaign)
        _maybe_campaigning(film)
        return success_obj(campaign)

    @app.post("/films/<film_id>/awards-campaigns/<campaign_id>/submit")
    def submit_campaign(film_id, campaign_id):
        user_id, _ = authorize("/films/{film_id}/awards-campaigns/{campaign_id}/submit")
        film = svc.get_or_404("films", film_id, "film")
        campaign = svc.get_or_404("awards_campaigns", campaign_id, "awards campaign")
        if campaign["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "awards campaign not found for this film")
        if campaign["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Campaign is not ACTIVE")
        if campaign.get("created_by") == user_id:
            raise ApiError("ERR_DUTY_SEPARATION_VIOLATION",
                           "The user who created the campaign cannot submit it")
        for ob in db.stores["talent_obligations"].values():
            if ob.get("campaign_id") == campaign_id:
                svc.refresh_obligation(ob)
        outstanding = [
            ob for ob in db.stores["talent_obligations"].values()
            if ob.get("campaign_id") == campaign_id
            and ob["status"] in ("REQUESTED", "CONFIRMED")
        ]
        if outstanding:
            raise ApiError("ERR_OBLIGATIONS_OUTSTANDING",
                           "Some talent obligations are still outstanding")
        campaign["status"] = "SUBMITTED"
        touch(campaign)
        _maybe_submitted(film)
        return success_obj(campaign)

    @app.post("/films/<film_id>/awards-campaigns/<campaign_id>/conclude")
    def conclude_campaign(film_id, campaign_id):
        authorize("/films/{film_id}/awards-campaigns/{campaign_id}/conclude")
        film = svc.get_or_404("films", film_id, "film")
        campaign = svc.get_or_404("awards_campaigns", campaign_id, "awards campaign")
        if campaign["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "awards campaign not found for this film")
        if campaign["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Campaign is not SUBMITTED")
        campaign["status"] = "CONCLUDED"
        touch(campaign)
        _maybe_concluded(film)
        return success_obj(campaign)

    # --- Campaign spends -------------------------------------------------------

    @app.post("/awards-campaigns/<campaign_id>/spends")
    def create_spend(campaign_id):
        authorize("/awards-campaigns/{campaign_id}/spends")
        campaign = svc.get_or_404("awards_campaigns", campaign_id, "awards campaign")
        body = svc.get_json_body()
        category = svc.req_enum(body, "category", svc.SPEND_CATEGORIES)
        amount = svc.req_int(body, "amount_cents")
        if amount <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be > 0")
        incurred_raw = svc.req_str(body, "incurred_at")
        incurred = parse_dt(incurred_raw, "incurred_at")
        target_category = body.get("target_category")
        if target_category is not None and not isinstance(target_category, str):
            raise ApiError("ERR_INVALID_REQUEST", "target_category must be a string")
        if campaign["status"] != "ACTIVE":
            raise ApiError("ERR_CAMPAIGN_NOT_ACTIVE", "Campaign is not ACTIVE")
        if target_category is not None and target_category not in campaign["target_categories"]:
            raise ApiError("ERR_CATEGORY_NOT_TARGETED",
                           "target_category not in campaign target_categories")
        existing = sum(
            s["amount_cents"]
            for s in db.stores["campaign_spends"].values()
            if s["campaign_id"] == campaign_id
        )
        if existing + amount > campaign["budget_total_cents"]:
            raise ApiError("ERR_CAMPAIGN_BUDGET_EXCEEDED",
                           "Spend would exceed campaign budget")
        eligible = svc.compute_eligible_spend(campaign, category, amount)
        ts = now_utc()
        spend = {
            "id": new_id(),
            "campaign_id": campaign_id,
            "category": category,
            "amount_cents": amount,
            "incurred_at": fmt_dt(incurred),
            "target_category": target_category,
            "eligible_amount_cents": eligible,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.stores["campaign_spends"][spend["id"]] = spend
        svc.recalc_campaign_budgets(campaign)
        deal = db.stores["deals"].get(campaign["deal_id"])
        if deal is not None:
            svc.recalc_deal_pa(deal)
        return success_obj(spend, 201)

    @app.get("/awards-campaigns/<campaign_id>/spends")
    def list_campaign_spends(campaign_id):
        authorize("/awards-campaigns/{campaign_id}/spends")
        svc.get_or_404("awards_campaigns", campaign_id, "awards campaign")
        rows = [s for s in db.stores["campaign_spends"].values()
                if s["campaign_id"] == campaign_id]
        if "category" in request.args:
            rows = [r for r in rows if r["category"] == request.args["category"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.get("/campaign-spends/<spend_id>")
    def get_spend(spend_id):
        authorize("/campaign-spends/{spend_id}")
        spend = svc.get_or_404("campaign_spends", spend_id, "campaign spend")
        return success_obj(spend)

    @app.get("/campaign-spends")
    def list_spends():
        authorize("/campaign-spends")
        rows = list(db.stores["campaign_spends"].values())
        q = request.args
        if "campaign_id" in q:
            rows = [r for r in rows if r["campaign_id"] == q["campaign_id"]]
        if "category" in q:
            rows = [r for r in rows if r["category"] == q["category"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)


    # --- Talent obligations ------------------------------------------------------

    @app.post("/films/<film_id>/talent-obligations")
    def create_obligation(film_id):
        authorize("/films/{film_id}/talent-obligations")
        film = svc.get_or_404("films", film_id, "film")
        body = svc.get_json_body()
        talent_name = svc.req_str(body, "talent_name")
        kind = svc.req_enum(body, "obligation_kind", svc.OBLIGATION_KINDS)
        starts_raw = svc.req_str(body, "window_starts_at")
        ends_raw = svc.req_str(body, "window_ends_at")
        starts = parse_dt(starts_raw, "window_starts_at")
        ends = parse_dt(ends_raw, "window_ends_at")
        city_code = svc.req_str(body, "city_code")
        campaign_id = body.get("campaign_id")
        if campaign_id is not None:
            if not isinstance(campaign_id, str):
                raise ApiError("ERR_INVALID_REQUEST", "campaign_id must be a string")
            svc.get_or_404("awards_campaigns", campaign_id, "awards campaign")
        if ends <= starts:
            raise ApiError("ERR_INVALID_WINDOW", "window_ends_at must be after window_starts_at")
        if talent_name not in film["principal_cast"] and talent_name != film["director_name"]:
            raise ApiError("ERR_TALENT_NOT_ON_FILM", "talent_name is not on this film")
        ts = now_utc()
        ob = {
            "id": new_id(),
            "film_id": film_id,
            "campaign_id": campaign_id,
            "talent_name": talent_name,
            "obligation_kind": kind,
            "window_starts_at": fmt_dt(starts),
            "window_ends_at": fmt_dt(ends),
            "city_code": city_code,
            "status": "REQUESTED",
            "conflicts_with_obligation_id": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.stores["talent_obligations"][ob["id"]] = ob
        return success_obj(ob, 201)

    @app.get("/films/<film_id>/talent-obligations")
    def list_film_obligations(film_id):
        authorize("/films/{film_id}/talent-obligations")
        svc.get_or_404("films", film_id, "film")
        rows = []
        for ob in db.stores["talent_obligations"].values():
            if ob["film_id"] == film_id:
                svc.refresh_obligation(ob)
                rows.append(ob)
        q = request.args
        if "talent_name" in q:
            rows = [r for r in rows if r["talent_name"] == q["talent_name"]]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.get("/talent-obligations/<obligation_id>")
    def get_obligation(obligation_id):
        authorize("/talent-obligations/{obligation_id}")
        ob = svc.get_or_404("talent_obligations", obligation_id, "talent obligation")
        svc.refresh_obligation(ob)
        return success_obj(ob)

    @app.get("/talent-obligations")
    def list_obligations():
        authorize("/talent-obligations")
        rows = []
        for ob in db.stores["talent_obligations"].values():
            svc.refresh_obligation(ob)
            rows.append(ob)
        q = request.args
        if "film_id" in q:
            rows = [r for r in rows if r["film_id"] == q["film_id"]]
        if "campaign_id" in q:
            rows = [r for r in rows if r.get("campaign_id") == q["campaign_id"]]
        if "conflicts_with_obligation_id" in q:
            rows = [r for r in rows if r.get("conflicts_with_obligation_id") == q["conflicts_with_obligation_id"]]
        if "talent_name" in q:
            rows = [r for r in rows if r["talent_name"] == q["talent_name"]]
        if "status" in q:
            rows = [r for r in rows if r["status"] == q["status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.post("/films/<film_id>/talent-obligations/<obligation_id>/confirm")
    def confirm_obligation(film_id, obligation_id):
        authorize("/films/{film_id}/talent-obligations/{obligation_id}/confirm")
        svc.get_or_404("films", film_id, "film")
        ob = svc.get_or_404("talent_obligations", obligation_id, "talent obligation")
        if ob["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "talent obligation not found for this film")
        svc.refresh_obligation(ob)
        if ob["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", "Obligation is not REQUESTED")
        error_id, conflict_id = svc.check_talent_conflicts(ob)
        if error_id is not None:
            ob["conflicts_with_obligation_id"] = conflict_id
            touch(ob)
            raise ApiError(error_id, "talent obligation conflicts with another obligation")
        ob["status"] = "CONFIRMED"
        ob["conflicts_with_obligation_id"] = None
        touch(ob)
        return success_obj(ob)

    @app.post("/films/<film_id>/talent-obligations/<obligation_id>/fulfill")
    def fulfill_obligation(film_id, obligation_id):
        authorize("/films/{film_id}/talent-obligations/{obligation_id}/fulfill")
        svc.get_or_404("films", film_id, "film")
        ob = svc.get_or_404("talent_obligations", obligation_id, "talent obligation")
        if ob["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "talent obligation not found for this film")
        svc.refresh_obligation(ob)
        if ob["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE", "Obligation is not CONFIRMED")
        if parse_dt(ob["window_ends_at"]) > clock_dt():
            raise ApiError("ERR_FULFILL_TOO_EARLY",
                           "Cannot fulfill before obligation window_ends_at")
        ob["status"] = "FULFILLED"
        touch(ob)
        return success_obj(ob)

    @app.post("/films/<film_id>/talent-obligations/<obligation_id>/waive")
    def waive_obligation(film_id, obligation_id):
        authorize("/films/{film_id}/talent-obligations/{obligation_id}/waive")
        svc.get_or_404("films", film_id, "film")
        ob = svc.get_or_404("talent_obligations", obligation_id, "talent obligation")
        if ob["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "talent obligation not found for this film")
        svc.refresh_obligation(ob)
        if ob["status"] not in ("REQUESTED", "CONFIRMED"):
            raise ApiError("ERR_INVALID_STATE", "Obligation cannot be waived from %s" % ob["status"])
        ob["status"] = "WAIVED"
        touch(ob)
        return success_obj(ob)
