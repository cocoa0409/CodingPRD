# Routes: filmmaker statements (participation waterfall).

from flask import request

import db
import services as svc
from errors import ApiError
from middleware import authorize
from util import new_id, now_utc, paginate, success_list, success_obj


def register(app):

    @app.post("/films/<film_id>/statements")
    def create_statement(film_id):
        authorize("/films/{film_id}/statements")
        film = svc.get_or_404("films", film_id, "film")
        body = svc.get_json_body()
        deal_id = svc.req_str(body, "deal_id")
        deal = svc.get_or_404("deals", deal_id, "deal")
        period_label = svc.req_str(body, "period_label")
        basis = svc.req_enum(body, "basis", svc.BASES)
        gross = svc.req_int(body, "gross_receipts_cents")
        if gross < 0:
            raise ApiError("ERR_INVALID_AMOUNT", "gross_receipts_cents must be >= 0")
        if deal["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "deal not found for this film")
        fee, recoup, participation = svc.compute_waterfall(film, deal, basis, gross)
        statement = {
            "id": new_id(),
            "film_id": film_id,
            "deal_id": deal_id,
            "period_label": period_label,
            "basis": basis,
            "gross_receipts_cents": gross,
            "distribution_fee_cents": fee,
            "recoupable_costs_cents": recoup,
            "filmmaker_participation_cents": participation,
            "statement_status": "ISSUED",
            "created_at": now_utc(),
        }
        db.stores["statements"][statement["id"]] = statement
        return success_obj(statement, 201)

    @app.get("/films/<film_id>/statements")
    def list_film_statements(film_id):
        authorize("/films/{film_id}/statements")
        svc.get_or_404("films", film_id, "film")
        rows = [s for s in db.stores["statements"].values() if s["film_id"] == film_id]
        q = request.args
        if "deal_id" in q:
            rows = [r for r in rows if r["deal_id"] == q["deal_id"]]
        if "basis" in q:
            rows = [r for r in rows if r["basis"] == q["basis"]]
        if "statement_status" in q:
            rows = [r for r in rows if r["statement_status"] == q["statement_status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)

    @app.get("/films/<film_id>/statements/<statement_id>")
    def get_film_statement(film_id, statement_id):
        authorize("/films/{film_id}/statements/{statement_id}")
        svc.get_or_404("films", film_id, "film")
        st = svc.get_or_404("statements", statement_id, "statement")
        if st["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "statement not found for this film")
        return success_obj(st)

    @app.post("/films/<film_id>/statements/<statement_id>/finalize")
    def finalize_statement(film_id, statement_id):
        authorize("/films/{film_id}/statements/{statement_id}/finalize")
        svc.get_or_404("films", film_id, "film")
        st = svc.get_or_404("statements", statement_id, "statement")
        if st["film_id"] != film_id:
            raise ApiError("ERR_NOT_FOUND", "statement not found for this film")
        if st["statement_status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", "Statement is not ISSUED")
        st["statement_status"] = "FINAL"
        return success_obj(st)

    @app.get("/statements/<statement_id>")
    def get_statement(statement_id):
        authorize("/statements/{statement_id}")
        st = svc.get_or_404("statements", statement_id, "statement")
        return success_obj(st)

    @app.get("/statements")
    def list_statements():
        authorize("/statements")
        rows = list(db.stores["statements"].values())
        q = request.args
        if "film_id" in q:
            rows = [r for r in rows if r["film_id"] == q["film_id"]]
        if "deal_id" in q:
            rows = [r for r in rows if r["deal_id"] == q["deal_id"]]
        if "basis" in q:
            rows = [r for r in rows if r["basis"] == q["basis"]]
        if "statement_status" in q:
            rows = [r for r in rows if r["statement_status"] == q["statement_status"]]
        rows = svc.sort_rows(rows)
        page, total, limit, offset = paginate(rows)
        return success_list(page, total, limit, offset)
