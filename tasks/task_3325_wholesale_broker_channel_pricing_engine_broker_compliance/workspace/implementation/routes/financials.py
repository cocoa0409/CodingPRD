"""Financial review, product eligibility and compensation plan endpoints."""

from flask import Blueprint

import db
import serializers
from services import finance, shared
from routes.helpers import endpoint, ok, listing, query

bp = Blueprint("financials", __name__)

BLUEPRINTS = [bp]


# --- Financial reviews -----------------------------------------------------
@bp.route("/brokers/<broker_id>/financial-reviews", methods=["POST"])
@endpoint("POST", "/brokers/<broker_id>/financial-reviews")
def create_financial_review(caller, body, broker_id):
    payload = dict(body)
    payload.setdefault("broker_id", broker_id)
    row = finance.create_financial_review(payload)
    return ok(serializers.financial_review, row), 201


@bp.route("/brokers/<broker_id>/financial-reviews", methods=["GET"])
@endpoint("GET", "/brokers/<broker_id>/financial-reviews")
def list_financial_reviews(caller, body, broker_id):
    broker = shared.get_broker(broker_id)
    rows = [row for row in db.financial_reviews.values() if row["broker_id"] == broker["id"]]
    status = query("status")
    if status:
        rows = [row for row in rows if row["status"] == status]
    return listing(serializers.financial_review, rows)


@bp.route("/financial-reviews/<review_id>/decision", methods=["POST"])
@endpoint("POST", "/financial-reviews/<review_id>/decision")
def decide_financial_review(caller, body, review_id):
    return ok(serializers.financial_review,
              finance.decide_financial_review(review_id, body))


# --- Product eligibility ---------------------------------------------------
@bp.route("/brokers/<broker_id>/product-eligibilities", methods=["POST"])
@endpoint("POST", "/brokers/<broker_id>/product-eligibilities")
def create_product_eligibility(caller, body, broker_id):
    payload = dict(body)
    payload.setdefault("broker_id", broker_id)
    row = finance.create_product_eligibility(payload)
    return ok(serializers.product_eligibility, row), 201


@bp.route("/brokers/<broker_id>/product-eligibilities", methods=["GET"])
@endpoint("GET", "/brokers/<broker_id>/product-eligibilities")
def list_product_eligibilities(caller, body, broker_id):
    broker = shared.get_broker(broker_id)
    rows = [row for row in db.product_eligibilities.values() if row["broker_id"] == broker["id"]]
    status = query("status")
    if status:
        rows = [row for row in rows if row["status"] == status]
    product_code = query("product_code")
    if product_code:
        rows = [row for row in rows if row["product_code"] == product_code]
    return listing(serializers.product_eligibility, rows)


@bp.route("/product-eligibilities/<eligibility_id>/decision", methods=["POST"])
@endpoint("POST", "/product-eligibilities/<eligibility_id>/decision")
def decide_product_eligibility(caller, body, eligibility_id):
    return ok(serializers.product_eligibility,
              finance.decide_product_eligibility(eligibility_id, body))


# --- Compensation plans ----------------------------------------------------
@bp.route("/compensation-plans", methods=["POST"])
@endpoint("POST", "/compensation-plans")
def create_compensation_plan(caller, body):
    row = finance.create_compensation_plan(body)
    return ok(serializers.compensation_plan, row), 201


@bp.route("/brokers/<broker_id>/compensation-plans", methods=["GET"])
@endpoint("GET", "/brokers/<broker_id>/compensation-plans")
def list_compensation_plans(caller, body, broker_id):
    broker = shared.get_broker(broker_id)
    rows = [row for row in db.compensation_plans.values() if row["broker_id"] == broker["id"]]
    is_active = query("is_active")
    if is_active is not None:
        wanted = str(is_active).strip().lower() in ("true", "1", "yes")
        rows = [row for row in rows if bool(row["is_active"]) is wanted]
    return listing(serializers.compensation_plan, rows)


@bp.route("/compensation-plans/<plan_id>", methods=["GET"])
@endpoint("GET", "/compensation-plans/<plan_id>")
def get_compensation_plan(caller, body, plan_id):
    return ok(serializers.compensation_plan, shared.get_plan(plan_id))


@bp.route("/compensation-plans/<plan_id>", methods=["PUT"])
@endpoint("PUT", "/compensation-plans/<plan_id>")
def update_compensation_plan(caller, body, plan_id):
    return ok(serializers.compensation_plan,
              finance.update_compensation_plan(plan_id, body))