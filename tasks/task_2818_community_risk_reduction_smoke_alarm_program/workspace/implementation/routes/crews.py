"""Canvass crew reference data (PRD 3.4)."""

from flask import Blueprint

import db
import domain
import response
import validation
from db import store
from errors import ApiError
from middleware import endpoint

bp = Blueprint("crews", __name__)


@bp.post("/crr/crews")
@endpoint("ProgramAdmin")
def create_crew():
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    crew_code = validation.req_str(body, "crew_code")
    member_count = validation.req_int(body, "member_count", minimum=1)
    certification_level = validation.req_enum(
        body, "certification_level", domain.CERTIFICATION_LEVELS
    )
    max_daily_minutes = validation.req_int(body, "max_daily_minutes", minimum=60)
    status = validation.opt_enum(body, "status", domain.CREW_STATUSES, default="ACTIVE")

    for existing in store.crews.values():
        if existing["crew_code"] == crew_code:
            raise ApiError("ERR_CREW_CODE_TAKEN")

    row = db.stamp_new({})
    crew = {
        "id": row["id"],
        "crew_code": crew_code,
        "member_count": member_count,
        "certification_level": certification_level,
        "max_daily_minutes": max_daily_minutes,
        "status": status,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "_seq": row["_seq"],
    }
    store.crews[crew["id"]] = crew
    return response.ok_row(crew, 201)
