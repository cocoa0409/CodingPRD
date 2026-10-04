"""Exclusivity policy endpoints."""

from flask import Blueprint

import serializers
from services import compliance
from services import shared
from routes.helpers import endpoint, ok, listing, query

bp = Blueprint("exclusivity", __name__)

BLUEPRINTS = [bp]


@bp.route("/exclusivity-policies", methods=["POST"])
@endpoint("POST", "/exclusivity-policies")
def create_policy(caller, body):
    row = compliance.create_policy(body)
    return ok(serializers.exclusivity_policy, row), 201


@bp.route("/brokers/<broker_id>/exclusivity-policies", methods=["GET"])
@endpoint("GET", "/brokers/<broker_id>/exclusivity-policies")
def list_policies(caller, body, broker_id):
    rows = compliance.list_policies(broker_id, status=query("status"))
    return listing(serializers.exclusivity_policy, rows)


@bp.route("/exclusivity-policies/<policy_id>/void", methods=["POST"])
@endpoint("POST", "/exclusivity-policies/<policy_id>/void")
def void_policy(caller, body, policy_id):
    return ok(serializers.exclusivity_policy, compliance.void_policy(policy_id, body))