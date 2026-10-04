"""Broker endpoints."""

from flask import Blueprint

import serializers
from services import broker as broker_service
from services import shared
from routes.helpers import endpoint, ok, listing, query

bp = Blueprint("brokers", __name__)

BLUEPRINTS = [bp]


@bp.route("/brokers", methods=["POST"])
@endpoint("POST", "/brokers")
def create_broker(caller, body):
    row = broker_service.create_broker(body)
    return ok(serializers.broker, row), 201


@bp.route("/brokers", methods=["GET"])
@endpoint("GET", "/brokers")
def list_brokers(caller, body):
    rows = broker_service.list_brokers(
        status=query("status"),
        home_state=query("home_state"),
        tier=query("tier"),
        exclusivity_status=query("exclusivity_status"),
    )
    return listing(serializers.broker, rows)


@bp.route("/brokers/<broker_id>", methods=["GET"])
@endpoint("GET", "/brokers/<broker_id>")
def get_broker(caller, body, broker_id):
    return ok(serializers.broker, shared.get_broker(broker_id))


@bp.route("/brokers/<broker_id>/reconciliation", methods=["GET"])
@endpoint("GET", "/brokers/<broker_id>/reconciliation")
def get_reconciliation(caller, body, broker_id):
    return ok(lambda payload: payload, broker_service.reconciliation(broker_id))


@bp.route("/brokers/<broker_id>/approve", methods=["POST"])
@endpoint("POST", "/brokers/<broker_id>/approve")
def approve_broker(caller, body, broker_id):
    return ok(serializers.broker, broker_service.approve_broker(broker_id))


@bp.route("/brokers/<broker_id>/reinstate", methods=["POST"])
@endpoint("POST", "/brokers/<broker_id>/reinstate")
def reinstate_broker(caller, body, broker_id):
    return ok(serializers.broker, broker_service.reinstate_broker(broker_id))


@bp.route("/brokers/<broker_id>/suspend", methods=["POST"])
@endpoint("POST", "/brokers/<broker_id>/suspend")
def suspend_broker(caller, body, broker_id):
    return ok(serializers.broker, broker_service.suspend_broker(broker_id, body))


@bp.route("/brokers/<broker_id>/terminate", methods=["POST"])
@endpoint("POST", "/brokers/<broker_id>/terminate")
def terminate_broker(caller, body, broker_id):
    return ok(serializers.broker, broker_service.terminate_broker(broker_id))