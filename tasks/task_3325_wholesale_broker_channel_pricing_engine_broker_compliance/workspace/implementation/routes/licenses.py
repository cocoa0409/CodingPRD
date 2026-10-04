"""Broker license endpoints."""

from flask import Blueprint

import serializers
from services import compliance
from routes.helpers import endpoint, ok, listing, query

bp = Blueprint("licenses", __name__)

BLUEPRINTS = [bp]


@bp.route("/brokers/<broker_id>/licenses", methods=["POST"])
@endpoint("POST", "/brokers/<broker_id>/licenses")
def create_license(caller, body, broker_id):
    row = compliance.create_license(broker_id, body)
    return ok(serializers.license, row), 201


@bp.route("/brokers/<broker_id>/licenses", methods=["GET"])
@endpoint("GET", "/brokers/<broker_id>/licenses")
def list_licenses(caller, body, broker_id):
    rows = compliance.list_licenses(broker_id, status=query("status"))
    return listing(serializers.license, rows)


@bp.route("/brokers/<broker_id>/licenses/<license_id>/revoke", methods=["POST"])
@endpoint("POST", "/brokers/<broker_id>/licenses/<license_id>/revoke")
def revoke_license(caller, body, broker_id, license_id):
    return ok(serializers.license, compliance.revoke_license(broker_id, license_id))