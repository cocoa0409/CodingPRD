from flask import Blueprint

import rating
import store
import views
from common import (API_PREFIX, body, clock_now, envelope_object, fail, get_enum,
                    get_int, require)

bp = Blueprint("rate_rules", __name__)


@bp.post(API_PREFIX + "/rate-rules")
def create_rate_rule():
    require("Actuary")
    b = body()
    equipment_type = get_enum(b, "equipment_type", rating.EQUIPMENT_TYPES)
    territory_code = get_enum(b, "territory_code", rating.TERRITORIES)
    age_min = get_int(b, "age_band_min_years", minimum=0)
    age_max = get_int(b, "age_band_max_years", minimum=0)
    if age_max < age_min:
        fail("ERR_INVALID_REQUEST",
             "age_band_max_years must be >= age_band_min_years")
    base_rate_bp = get_int(b, "base_rate_bp", minimum=1)
    grade = get_enum(b, "theft_hazard_grade", ("A", "B", "C", "D"))
    index_bp = get_int(b, "replacement_cost_index_bp", required=False,
                       minimum=10000, default=11000)
    row = store.make({
        "equipment_type": equipment_type,
        "territory_code": territory_code,
        "age_band_min_years": age_min,
        "age_band_max_years": age_max,
        "base_rate_bp": base_rate_bp,
        "theft_hazard_grade": grade,
        "replacement_cost_index_bp": index_bp,
        "status": "DRAFT",
        "published_at": None,
    })
    store.rate_rules[row["id"]] = row
    return envelope_object(views.rate_rule_view(row), 201)


@bp.post(API_PREFIX + "/rate-rules/<rule_id>/publish")
def publish_rate_rule(rule_id):
    require("Actuary")
    rule = store.find(store.rate_rules, rule_id, "ERR_RATE_RULE_NOT_FOUND")
    if rule["status"] != "DRAFT":
        fail("ERR_RATE_RULE_NOT_DRAFT",
             "Rate rule is already %s" % rule["status"])
    # Publication retires competition: any other cell already PUBLISHED with the
    # identical equipment_type, territory_code and age band is moved to RETIRED.
    for other in store.order(list(store.rate_rules.values())):
        if other["id"] == rule["id"]:
            continue
        if other["status"] != "PUBLISHED":
            continue
        if (other["equipment_type"] == rule["equipment_type"]
                and other["territory_code"] == rule["territory_code"]
                and other["age_band_min_years"] == rule["age_band_min_years"]
                and other["age_band_max_years"] == rule["age_band_max_years"]):
            other["status"] = "RETIRED"
            store.touch(other)
    rule["status"] = "PUBLISHED"
    rule["published_at"] = clock_now()
    store.touch(rule)
    return envelope_object(views.rate_rule_view(rule), 200)


@bp.get(API_PREFIX + "/rate-rules/<rule_id>")
def get_rate_rule(rule_id):
    require("Actuary", "Underwriter", "UnderwritingManager")
    rule = store.find(store.rate_rules, rule_id, "ERR_RATE_RULE_NOT_FOUND")
    return envelope_object(views.rate_rule_view(rule), 200)
