"""Safety cases — PRD §3.7, endpoints 46-50."""

import db
import core
import services
import calculations as calc
from core import ApiError, D, now_iso, try_iso
from response import ok, page_of
from http_util import pagination, must_get, must_resolve, body, coerce_int
from routes._common import route
from models import create


def register(app):

    @route(app, "/api/safety-cases", ["POST"], ["SafetyCaseAuthor"])
    def create_case():
        """§3.7: the supplied version must exceed the corridor's current highest
        safety case version (ERR_INVALID_VERSION); the revision opens in DRAFT with
        filed_date null."""
        raw = body()
        allowed = {"corridor_id", "safety_case_version", "hazard_count",
                   "open_hazard_count"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in ("corridor_id", "safety_case_version", "hazard_count"):
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        corridor = must_resolve("Corridor", raw["corridor_id"])
        version = coerce_int(raw["safety_case_version"])
        if version <= services.highest_safety_case_version(corridor["id"]):
            raise ApiError("ERR_INVALID_VERSION",
                           "The supplied version does not exceed the corridor's highest.")
        row = create("SafetyCase", {
            "corridor_id": corridor["id"],
            "safety_case_version": version,
            "hazard_count": coerce_int(raw["hazard_count"]),
            "open_hazard_count": coerce_int(raw.get("open_hazard_count", 0)),
            "filed_date": None,
        })
        row["case_status"] = "DRAFT"
        services.recompute_corridor_case_summary(corridor)
        services.flush(corridor)
        return ok(row, 201)

    @route(app, "/api/safety-cases", ["GET"], ["Any"])
    def list_cases():
        limit, offset = pagination()
        return page_of(db.sort_created(db.all_rows("safety_cases")), limit, offset)

    @route(app, "/api/safety-cases/<rid>", ["GET"], ["Any"])
    def get_case(rid):
        case = must_get("SafetyCase", rid)
        corridor = db.get("corridors", case.get("corridor_id"))
        if corridor is not None:
            services.mark(case, "case_status_summary",
                          services.case_summary_for(case, corridor))
        return ok(case)

    @route(app, "/api/safety-cases/<rid>/submit", ["POST"], ["SafetyCaseAuthor"])
    def submit_case(rid):
        case = must_get("SafetyCase", rid)
        if case.get("case_status") != "DRAFT":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a draft revision can be submitted.")
        services.mark(case, "case_status", "SUBMITTED")
        services.flush(case)
        return ok(case)

    @route(app, "/api/safety-cases/<rid>/file", ["POST"], ["RegulatoryLiaison"])
    def file_case(rid):
        """§3.7: filing supplies the filed_date, recomputes residual_risk_score,
        supersedes any earlier FILED case on the same corridor and recomputes the
        corridor's case_status_summary.  hazard_count must be at least 1 and
        open_hazard_count must be 0."""
        case = must_get("SafetyCase", rid)
        raw = body()
        for key in raw:
            if key != "filed_date":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if case.get("case_status") not in ("SUBMITTED", "DRAFT"):
            raise ApiError("ERR_INVALID_STATE",
                           "Only a submitted or draft revision can be filed.")
        if coerce_int(case.get("hazard_count") or 0) < 1:
            raise ApiError("ERR_INVALID_STATE", "hazard_count must be at least 1.")
        if coerce_int(case.get("open_hazard_count") or 0) != 0:
            raise ApiError("ERR_INVALID_STATE",
                           "open_hazard_count must be 0 before the case can be filed.")
        corridor = db.get("corridors", case.get("corridor_id"))
        if corridor is None:
            raise ApiError("ERR_CORRIDOR_NOT_FOUND")
        provided = raw.get("filed_date")
        filed = try_iso(provided) if provided else now_iso()
        if filed is None:
            raise ApiError("ERR_INVALID_REQUEST", "filed_date must be ISO 8601 UTC.")
        for other in db.by("safety_cases", "corridor_id", corridor["id"]):
            if other["id"] == case["id"]:
                continue
            if other.get("case_status") == "FILED":
                services.mark(other, "case_status", "SUPERSEDED")
                services.flush(other)
        case["filed_date"] = filed
        return _do_file(case, corridor)


def _do_file(case, corridor):
    services.mark(case, "case_status", "FILED")
    services.mark(case, "residual_risk_score",
                  calc.residual_risk_score(case.get("hazard_count"),
                                           corridor.get("highway_segment_miles")))
    services.flush(case)
    services.recompute_corridor_case_summary(corridor)
    services.flush(corridor)
    return ok(case)