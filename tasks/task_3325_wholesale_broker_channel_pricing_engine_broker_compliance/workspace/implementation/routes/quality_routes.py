"""Quality control review endpoints."""

from flask import Blueprint

import db
import serializers
from services import quality, shared
from routes.helpers import endpoint, ok, listing, query

bp = Blueprint("quality_routes", __name__)

BLUEPRINTS = [bp]


@bp.route("/quality-control-reviews", methods=["POST"])
@endpoint("POST", "/quality-control-reviews")
def create_quality_control_review(caller, body):
    row = quality.create_quality_control_review(caller, body)
    return ok(serializers.quality_control_review, row), 201


@bp.route("/quality-control-reviews", methods=["GET"])
@endpoint("GET", "/quality-control-reviews")
def list_all_reviews(caller, body):
    rows = list(db.quality_control_reviews.values())
    broker_id = query("broker_id")
    if broker_id:
        rows = [row for row in rows if row["broker_id"] == broker_id]
    loan_id = query("loan_submission_id")
    if loan_id:
        rows = [row for row in rows if row["loan_submission_id"] == loan_id]
    outcome = query("outcome")
    if outcome:
        rows = [row for row in rows if row["outcome"] == outcome]
    return listing(serializers.quality_control_review, rows)


@bp.route("/brokers/<broker_id>/quality-control-reviews", methods=["GET"])
@endpoint("GET", "/brokers/<broker_id>/quality-control-reviews")
def list_broker_reviews(caller, body, broker_id):
    broker = shared.get_broker(broker_id)
    rows = [row for row in db.quality_control_reviews.values() if row["broker_id"] == broker["id"]]
    outcome = query("outcome")
    if outcome:
        rows = [row for row in rows if row["outcome"] == outcome]
    return listing(serializers.quality_control_review, rows)


@bp.route("/loan-submissions/<loan_id>/quality-control-reviews", methods=["GET"])
@endpoint("GET", "/loan-submissions/<loan_id>/quality-control-reviews")
def list_loan_reviews(caller, body, loan_id):
    loan = shared.get_loan(loan_id)
    rows = [row for row in db.quality_control_reviews.values()
            if row["loan_submission_id"] == loan["id"]]
    return listing(serializers.quality_control_review, rows)


@bp.route("/quality-control-reviews/<review_id>/resolve", methods=["POST"])
@endpoint("POST", "/quality-control-reviews/<review_id>/resolve")
def resolve_review(caller, body, review_id):
    return ok(serializers.quality_control_review,
              quality.resolve_quality_control_review(caller, review_id, body))


@bp.route("/quality-control-reviews/<review_id>/repurchase", methods=["POST"])
@endpoint("POST", "/quality-control-reviews/<review_id>/repurchase")
def repurchase_review(caller, body, review_id):
    return ok(serializers.loan_submission, quality.repurchase(review_id))