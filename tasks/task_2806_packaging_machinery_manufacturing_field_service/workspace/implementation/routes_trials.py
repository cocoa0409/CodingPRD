"""Application-engineering product trials (PRD 3.2)."""
from flask import Blueprint, g

import auth
import calc
import domain
import envelope
import store
import validation
from errors import ApiError

bp = Blueprint("trials", __name__)

TRIAL_STATUSES = ("SUBMITTED", "TESTING", "RETEST_REQUIRED", "PASSED", "REJECTED")
OUTCOMES = ("PASS", "RETEST", "REJECT")


@bp.post("/product-trials")
def create_product_trial():
    auth.authorize(("ApplicationEngineer", "CustomerContact"))
    payload = validation.body()
    customer_id = validation.req_str(payload, "customer_id", 1, None)
    machine_model_id = validation.req_str(payload, "machine_model_id", 1, None)
    product_name = validation.req_str(payload, "product_name", 1, 80)
    container_family = validation.req_str(payload, "container_family", 1, 32)
    container_diameter_mm = validation.req_int(payload, "container_diameter_mm", 1)
    domain.must_get("customers", customer_id)
    domain.must_get("machine_models", machine_model_id)
    auth.require_owner(g.role, g.user_id, customer_id)
    row = {
        "customer_id": customer_id,
        "machine_model_id": machine_model_id,
        "product_name": product_name,
        "container_family": container_family,
        "container_diameter_mm": container_diameter_mm,
        "status": "SUBMITTED",
        "retest_count": 0,
        "measured_rate_cpm": 0,
        "config_recommendation": "PENDING",
        "rate_ratio_pct": 0,
    }
    return envelope.created(store.insert("product_trials", row))


@bp.get("/product-trials")
def list_product_trials():
    auth.authorize(("ApplicationEngineer", "PlatformAdmin", "CustomerContact"))
    limit, offset = validation.pagination()
    filters = {
        "customer_id": validation.query_str("customer_id"),
        "machine_model_id": validation.query_str("machine_model_id"),
        "status": validation.query_enum("status", TRIAL_STATUSES),
    }
    items = [row for row in store.rows("product_trials")
             if all(value is None or row.get(key) == value
                    for key, value in filters.items())]
    return envelope.ok_list(validation.paginate(items, limit, offset),
                            limit, offset, len(items))


@bp.get("/product-trials/<product_trial_id>")
def read_product_trial(product_trial_id):
    auth.authorize(("ApplicationEngineer", "PlatformAdmin", "CustomerContact"))
    return envelope.ok(domain.must_get("product_trials", product_trial_id))


@bp.post("/product-trials/<product_trial_id>/start-testing")
def start_testing(product_trial_id):
    auth.authorize(("ApplicationEngineer",))
    trial = domain.must_get("product_trials", product_trial_id)
    customer = store.get("customers", trial["customer_id"])
    model = store.get("machine_models", trial["machine_model_id"])
    if trial["status"] == "SUBMITTED":
        # rungs 6, 7, 8 then 45 (PRD 3.2: four conditions on this edge)
        if customer["status"] != "ACTIVE":
            raise ApiError("ERR_CUSTOMER_SUSPENDED",
                           "The owning customer is suspended.")
        if model["lifecycle_status"] != "ACTIVE":
            raise ApiError("ERR_MODEL_OBSOLETE",
                           "The candidate machine model is obsolete.")
        diameter = int(trial["container_diameter_mm"])
        if (diameter < int(model["min_container_diameter_mm"])
                or diameter > int(model["max_container_diameter_mm"])):
            raise ApiError("ERR_CONTAINER_OUT_OF_RANGE",
                           "The trialled container is outside the base machine "
                           "diameter window.")
        trial["status"] = "TESTING"
        store.touch(trial)
        return envelope.ok(trial)
    if trial["status"] == "RETEST_REQUIRED":
        # the loop edge: only the retest ceiling guards it (rung 44)
        if int(trial["retest_count"]) >= calc.MAX_TRIAL_RETESTS:
            raise ApiError("ERR_TRIAL_RETEST_LIMIT",
                           "The trial has exhausted its retest allowance.")
        trial["retest_count"] = int(trial["retest_count"]) + 1
        trial["status"] = "TESTING"
        store.touch(trial)
        return envelope.ok(trial)
    raise ApiError("ERR_INVALID_TRIAL_STATE",
                   "A trial in %s cannot be moved onto the rig." % trial["status"])


@bp.post("/product-trials/<product_trial_id>/record-result")
def record_result(product_trial_id):
    auth.authorize(("ApplicationEngineer",))
    payload = validation.body()
    measured_rate_cpm = validation.req_int(payload, "measured_rate_cpm", 0)
    outcome = validation.req_enum(payload, "outcome", OUTCOMES)
    trial = domain.must_get("product_trials", product_trial_id)
    status = trial["status"]
    if not (status == "TESTING"
            or (status == "RETEST_REQUIRED" and outcome == "REJECT")):
        raise ApiError("ERR_INVALID_TRIAL_STATE",
                       "A trial in %s admits no %s result." % (status, outcome))
    if outcome == "RETEST" and int(trial["retest_count"]) >= calc.MAX_TRIAL_RETESTS:
        raise ApiError("ERR_TRIAL_RETEST_LIMIT",
                       "The trial has exhausted its retest allowance.")
    customer = store.get("customers", trial["customer_id"])
    model = store.get("machine_models", trial["machine_model_id"])
    rate_ratio_pct, _effective, recommendation = calc.trial_config_recommendation(
        measured_rate_cpm, model["nameplate_rate_cpm"],
        customer["product_variation_pct"], outcome)
    trial["measured_rate_cpm"] = measured_rate_cpm
    trial["rate_ratio_pct"] = rate_ratio_pct
    trial["config_recommendation"] = recommendation
    if outcome == "PASS":
        if recommendation != "NOT_FEASIBLE":
            trial["status"] = "PASSED"
    elif outcome == "RETEST":
        trial["status"] = "RETEST_REQUIRED"
    else:
        trial["status"] = "REJECTED"
    store.touch(trial)
    return envelope.ok(trial)
