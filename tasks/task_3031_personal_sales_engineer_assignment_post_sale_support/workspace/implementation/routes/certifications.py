"""Certification, product knowledge and the seniority ladder.

PRD §3.9.
"""

from db import DB, add_months, iso
from errors import ApiError, Err, invalid_value
from middleware import guard
from response import (as_enum, as_int, as_str, body, created_obj, ensure_known,
                      ok_obj, page)
from services import calc, core

ATTEMPT_ROLES = ["PlatformAdmin", "SalesEngineerOps", "Engineer"]


def register(app):
    @app.route("/certification-attempts", methods=["POST"])
    def create_attempt():
        guard(["SalesEngineerOps"])
        data = body()
        ensure_known(data, ["engineer_id", "product_family", "score_pct"])
        engineer = core.fetch("engineers", as_str(data, "engineer_id", required=True),
                              Err.ENGINEER_NOT_FOUND)
        score = as_int(data, "score_pct", required=True)
        if score < 0 or score > 100:
            raise invalid_value("score_pct must fall between 0 and 100.")
        row = core.new_row(
            "certification_attempts",
            engineer_id=engineer["id"],
            product_family=as_enum(data, "product_family", calc.PRODUCT_FAMILIES),
            score_pct=score,
            attempt_index=1 + core.prior_attempt_count(
                engineer["id"], data.get("product_family")),
            eligible_to_retake=True,
            certified=False,
            status="SCHEDULED",
            assessed_at=None,
            expires_at=None,
        )
        row["eligible_to_retake"] = int(row["attempt_index"]) < 3
        return created_obj(core.public(row))

    @app.route("/certification-attempts", methods=["GET"])
    def list_attempts():
        guard(ATTEMPT_ROLES)
        return page(core.all_rows("certification_attempts"), filters=(
            ("engineer_id", "engineer_id", None),
            ("product_family", "product_family", None),
            ("status", "status", None),
        ))

    @app.route("/certification-attempts/<ident>", methods=["GET"])
    def get_attempt(ident):
        guard(ATTEMPT_ROLES)
        return ok_obj(core.public(core.fetch("certification_attempts", ident,
                                             Err.REFERENCED_RESOURCE_NOT_FOUND)))

    @app.route("/certification-attempts/<ident>/grade", methods=["POST"])
    def grade_attempt(ident):
        guard(["SalesEngineerOps"])
        attempt = core.fetch("certification_attempts", ident,
                             Err.REFERENCED_RESOURCE_NOT_FOUND)
        core.require_state(attempt, ("SCHEDULED",))
        now = DB.now()
        if int(attempt.get("score_pct") or 0) >= 80:
            attempt["status"] = "PASSED"
            attempt["certified"] = True
            attempt["assessed_at"] = iso(now)
            attempt["expires_at"] = iso(add_months(now, calc.CERT_VALIDITY_MONTHS))
        else:
            attempt["status"] = "FAILED"
            attempt["certified"] = False
            core.recompute_attempt_index(attempt)
        core.touch(attempt)
        core.recompute_certified_family_count(attempt["engineer_id"])
        return ok_obj(core.public(attempt))

    @app.route("/certification-attempts/<ident>/reschedule", methods=["POST"])
    def reschedule_attempt(ident):
        guard(["SalesEngineerOps"])
        attempt = core.fetch("certification_attempts", ident,
                             Err.REFERENCED_RESOURCE_NOT_FOUND)
        core.require_state(attempt, ("FAILED",))
        # priority 28: a third failed attempt is the end of the road.
        if not attempt.get("eligible_to_retake") \
                or int(attempt.get("attempt_index") or 0) >= 3:
            raise ApiError(Err.RETAKE_NOT_ELIGIBLE)
        attempt["status"] = "SCHEDULED"
        attempt["score_pct"] = None
        core.touch(attempt)
        return ok_obj(core.public(attempt))

    @app.route("/certification-attempts/<ident>/expire", methods=["POST"])
    def expire_attempt(ident):
        guard(["SalesEngineerOps", "PlatformAdmin"])
        attempt = core.fetch("certification_attempts", ident,
                             Err.REFERENCED_RESOURCE_NOT_FOUND)
        core.require_state(attempt, ("SCHEDULED", "PASSED", "FAILED"))
        attempt["status"] = "EXPIRED"
        attempt["certified"] = False
        core.touch(attempt)
        core.recompute_certified_family_count(attempt["engineer_id"])
        return ok_obj(core.public(attempt))