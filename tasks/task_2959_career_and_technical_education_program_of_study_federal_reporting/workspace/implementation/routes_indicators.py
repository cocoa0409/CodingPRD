"""Performance-indicator negotiation, year close and the sanction cascade."""
from flask import Blueprint

import calc
import resolve
import serialize
import services
import shape
from auth import actor, actor_role, endpoint
from envelope import created, listing, ok, page
from errors import ApiError
from store import (INDICATOR_CODES, MAX_NEGOTIATION_ROUNDS, MISS_TOLERANCE,
                   SMALL_COHORT_MIN, clock_date, db, dec, fmt_date, parse_date,
                   stamp_new, touch)

bp = Blueprint("indicators", __name__)
REVIEWER = ("StateComplianceReviewer",)
DIRECTOR_REVIEWER = ("CteDirector", "StateComplianceReviewer")
READERS = ("CteDirector", "StateComplianceReviewer", "GrantFiscalOfficer")


def _check_alternation(indicator):
    """Priority 7: the party holding the standing offer may not answer itself."""
    holder = indicator.get("last_offer_by_user_id")
    if holder is None:
        return
    if actor() == holder or actor_role() == indicator.get("last_offer_by_role"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The party holding the standing offer may neither answer "
                       "itself nor accept its own number.")


# ------------------------------------------------------------------ reads
@bp.get("/cte/performance-indicators/<indicator_id>")
@endpoint(READERS)
def get_indicator(indicator_id):
    return ok(serialize.indicator(resolve.indicator(indicator_id)))


# ------------------------------------------------------------------ open
@bp.post("/cte/programs-of-study/<pos_id>/performance-indicators")
@endpoint(REVIEWER)
def open_indicator(pos_id):
    data = shape.body()
    indicator_code = shape.req_enum(data, "indicator_code", INDICATOR_CODES)
    reporting_year = shape.req_int(data, "reporting_year", minimum=2020, maximum=2035)
    baseline_pct = shape.req_num(data, "baseline_pct", minimum=0, maximum=100,
                                 places=2)
    cohort_year = shape.req_int(data, "cohort_year", minimum=2020, maximum=2035)
    program = resolve.program(pos_id)
    services.refresh_clna(program)
    for existing in db.indicators.values():
        if (existing["pos_id"] == pos_id
                and existing["indicator_code"] == indicator_code
                and int(existing["reporting_year"]) == reporting_year):
            raise ApiError("ERR_INDICATOR_DUPLICATE",
                           "An indicator already exists for this program, code "
                           "and reporting year.")
    indicator = stamp_new({
        "pos_id": pos_id,
        "indicator_code": indicator_code,
        "reporting_year": reporting_year,
        "cohort_year": cohort_year,
        "baseline_pct": baseline_pct,
        "negotiated_level_pct": None,
        "last_offer_pct": None,
        "last_offer_by_user_id": None,
        "last_offer_by_role": None,
        "negotiation_round": 0,
        "actual_pct": None,
        "met_threshold_pct": None,
        "consecutive_miss_count": 0,
        "status": "PROPOSED",
        "closed_on": None,
    })
    db.indicators[indicator["id"]] = indicator
    return created(serialize.indicator(indicator))


# ------------------------------------------------------------------ negotiation
@bp.post("/cte/performance-indicators/<indicator_id>/negotiation-offers")
@endpoint(DIRECTOR_REVIEWER)
def table_offer(indicator_id):
    data = shape.body()
    offered = shape.req_num(data, "offered_level_pct", minimum=0, maximum=100,
                            places=2)
    shape.opt_string(data, "rationale")
    indicator = resolve.indicator(indicator_id)
    _check_alternation(indicator)

    status = indicator["status"]
    if status == "ARBITRATED":
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
                       "The negotiation budget is spent and the arbitrated level "
                       "is binding.")
    if status == "PROPOSED":
        if actor_role() != "StateComplianceReviewer":
            raise ApiError("ERR_INVALID_INDICATOR_STATE",
                           "Only a StateComplianceReviewer may open the exchange "
                           "on a PROPOSED indicator.")
        indicator["status"] = "NEGOTIATING"
        indicator["negotiation_round"] = 1
    elif status == "NEGOTIATING":
        current_round = int(indicator["negotiation_round"])
        indicator["negotiation_round"] = current_round + 1
        if current_round >= MAX_NEGOTIATION_ROUNDS:
            indicator["status"] = "ARBITRATED"
            indicator["negotiated_level_pct"] = dec(indicator["baseline_pct"])
            indicator["met_threshold_pct"] = calc.met_threshold(
                indicator["baseline_pct"])
    else:
        raise ApiError("ERR_INVALID_INDICATOR_STATE",
                       "Indicator status %s does not admit a negotiation offer."
                       % status)

    indicator["last_offer_pct"] = offered
    indicator["last_offer_by_user_id"] = actor()
    indicator["last_offer_by_role"] = actor_role()
    touch(indicator)
    return ok(serialize.indicator(indicator))


@bp.post("/cte/performance-indicators/<indicator_id>/accept-level")
@endpoint(DIRECTOR_REVIEWER)
def accept_level(indicator_id):
    data = shape.body()
    shape.opt_string(data, "acceptance_note")
    indicator = resolve.indicator(indicator_id)
    _check_alternation(indicator)

    status = indicator["status"]
    if status == "ARBITRATED":
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
                       "The negotiation budget is spent and the arbitrated level "
                       "is binding.")
    if status != "NEGOTIATING":
        raise ApiError("ERR_INVALID_INDICATOR_STATE",
                       "Indicator status %s does not admit a level acceptance."
                       % status)
    if indicator["last_offer_pct"] is None:
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
                       "There is no standing offer to accept.")
    level = dec(indicator["last_offer_pct"])
    indicator["negotiated_level_pct"] = level
    indicator["met_threshold_pct"] = calc.met_threshold(level)
    indicator["status"] = "AGREED"
    touch(indicator)
    return ok(serialize.indicator(indicator))


# ------------------------------------------------------------------ year close
@bp.post("/cte/performance-indicators/<indicator_id>/close-reporting-year")
@endpoint(REVIEWER)
def close_reporting_year(indicator_id):
    data = shape.body()
    closed_on = shape.req_date(data, "closed_on")
    indicator = resolve.indicator(indicator_id)
    status = indicator["status"]
    if status not in ("AGREED", "ARBITRATED", "NOT_MET", "MONITORING"):
        raise ApiError("ERR_INVALID_INDICATOR_STATE",
                       "Indicator status %s does not admit a reporting-year "
                       "close." % status)
    if status in ("NOT_MET", "MONITORING"):
        previous = parse_date(indicator["closed_on"])
        if previous is not None and closed_on <= previous:
            raise ApiError("ERR_INVALID_INDICATOR_STATE",
                           "Each close must advance the reporting year: closed_on "
                           "must be strictly later than %s."
                           % indicator["closed_on"])

    denominator, numerator, small, raw = calc.raw_actual(indicator)
    indicator["actual_pct"] = raw
    indicator["closed_on"] = fmt_date(closed_on)
    threshold = indicator.get("met_threshold_pct")
    escalate = False
    if denominator < SMALL_COHORT_MIN:
        indicator["status"] = "NOT_SCORED"
    elif raw is not None and threshold is not None and dec(raw) >= dec(threshold):
        indicator["status"] = "MET"
        indicator["consecutive_miss_count"] = 0
    else:
        indicator["status"] = "NOT_MET"
        indicator["consecutive_miss_count"] = \
            int(indicator["consecutive_miss_count"]) + 1
        escalate = int(indicator["consecutive_miss_count"]) >= MISS_TOLERANCE
    touch(indicator)
    if escalate:
        services.escalate_indicator(indicator)
    return ok(serialize.indicator(indicator))
