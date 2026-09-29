"""Post-event analysis (PRD 3.10)."""

from flask import Blueprint

import calc
import services
from db import clock_dt, db, new_row, touch
from errors import ApiError
from response import created_response, object_response
from routes.common import (
    ALL_ROLES,
    PREFIX,
    created_asc,
    created_desc,
    get_analysis,
    get_promotion,
    page,
)
from validators import (
    authenticate,
    body_fields,
    get_enum,
    no_body,
    pagination,
    query_enum,
    query_value,
)

bp = Blueprint("analyses", __name__)

ANALYST = "TradeFinanceAnalyst"
BASELINE_METHODS = ("TRAILING", "SEASONAL")
DATA_STATUSES = ("COMPLETE", "INSUFFICIENT_DATA")


@bp.post(PREFIX + "/promotions/<promotion_id>/analyze")
def analyze_promotion(promotion_id):
    authenticate([ANALYST])
    data = body_fields(required=["baseline_method"])
    baseline_method = get_enum(data, "baseline_method", BASELINE_METHODS)
    promo = get_promotion(promotion_id)
    # rung 43
    if promo["lifecycle_status"] not in ("ENDED", "ANALYZED"):
        raise ApiError("ERR_PROMOTION_STATE_INVALID")
    # rung 65
    if calc.analysis_of_promotion(promotion_id) is not None:
        raise ApiError("ERR_ANALYSIS_ALREADY_EXISTS")

    row = new_row()
    row["promotion_id"] = promotion_id
    row.update(services.compute_analysis_values(promo, baseline_method))
    row["computed_at"] = clock_dt()
    db.analyses[row["id"]] = row
    promo["lifecycle_status"] = "ANALYZED"
    touch(promo)
    return created_response(calc.analysis_out(row))


@bp.get(PREFIX + "/promotions/<promotion_id>/post-event-analyses")
def list_promotion_analyses(promotion_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    get_promotion(promotion_id)
    rows = [a for a in db.analyses.values() if a["promotion_id"] == promotion_id]
    return page(created_asc(rows), limit, offset, calc.analysis_out)


@bp.get(PREFIX + "/post-event-analyses")
def list_analyses():
    authenticate(ALL_ROLES)
    limit, offset = pagination(["promotion_id", "baseline_method", "data_status"])
    promotion_id = query_value("promotion_id")
    baseline_method = query_enum("baseline_method", BASELINE_METHODS)
    data_status = query_enum("data_status", DATA_STATUSES)
    rows = list(db.analyses.values())
    if promotion_id is not None:
        get_promotion(promotion_id)
        rows = [r for r in rows if r["promotion_id"] == promotion_id]
    if baseline_method is not None:
        rows = [r for r in rows if r["baseline_method"] == baseline_method]
    if data_status is not None:
        rows = [r for r in rows if r["data_status"] == data_status]
    return page(created_desc(rows), limit, offset, calc.analysis_out)


@bp.get(PREFIX + "/post-event-analyses/<analysis_id>")
def read_analysis(analysis_id):
    authenticate(ALL_ROLES)
    no_body()
    return object_response(calc.analysis_out(get_analysis(analysis_id)))
