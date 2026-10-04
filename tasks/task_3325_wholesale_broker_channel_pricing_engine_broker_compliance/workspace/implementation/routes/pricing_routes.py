"""Rate sheet and pricing quote endpoints."""

from flask import Blueprint

import db
import serializers
from services import pricing, shared
from routes.helpers import endpoint, ok, listing, query

bp = Blueprint("pricing_routes", __name__)

BLUEPRINTS = [bp]


@bp.route("/brokers/<broker_id>/rate-sheets", methods=["POST"])
@endpoint("POST", "/brokers/<broker_id>/rate-sheets")
def publish_rate_sheet(caller, body, broker_id):
    row = pricing.publish_rate_sheet(broker_id, body)
    return ok(serializers.rate_sheet, row), 201


@bp.route("/brokers/<broker_id>/rate-sheets", methods=["GET"])
@endpoint("GET", "/brokers/<broker_id>/rate-sheets")
def list_broker_rate_sheets(caller, body, broker_id):
    broker = shared.get_broker(broker_id)
    rows = [row for row in db.rate_sheets.values() if row["broker_id"] == broker["id"]]
    product_code = query("product_code")
    if product_code:
        rows = [row for row in rows if row["product_code"] == product_code]
    status = query("status")
    if status:
        rows = [row for row in rows if row["status"] == status]
    return listing(serializers.rate_sheet, rows)


@bp.route("/brokers/<broker_id>/rate-sheets/<sheet_id>/retire", methods=["POST"])
@endpoint("POST", "/brokers/<broker_id>/rate-sheets/<sheet_id>/retire")
def retire_rate_sheet(caller, body, broker_id, sheet_id):
    return ok(serializers.rate_sheet, pricing.retire_rate_sheet(broker_id, sheet_id))


@bp.route("/rate-sheets", methods=["GET"])
@endpoint("GET", "/rate-sheets")
def list_rate_sheets(caller, body):
    rows = list(db.rate_sheets.values())
    broker_id = query("broker_id")
    if broker_id:
        rows = [row for row in rows if row["broker_id"] == broker_id]
    product_code = query("product_code")
    if product_code:
        rows = [row for row in rows if row["product_code"] == product_code]
    status = query("status")
    if status:
        rows = [row for row in rows if row["status"] == status]
    superseded_by = query("superseded_by_sheet_id")
    if superseded_by:
        rows = [row for row in rows if row["superseded_by_sheet_id"] == superseded_by]
    return listing(serializers.rate_sheet, rows)


@bp.route("/rate-sheets/<sheet_id>", methods=["GET"])
@endpoint("GET", "/rate-sheets/<sheet_id>")
def get_rate_sheet(caller, body, sheet_id):
    return ok(serializers.rate_sheet, shared.get_rate_sheet(sheet_id))


@bp.route("/rate-sheets/<sheet_id>/pricing-quotes", methods=["POST"])
@endpoint("POST", "/rate-sheets/<sheet_id>/pricing-quotes")
def create_pricing_quote(caller, body, sheet_id):
    row = pricing.create_pricing_quote(sheet_id, caller, body)
    # PRD 3.5: the creation response reports the snapshot's staleness through
    # `is_repriced`, so the quote is serialized rather than returned raw.
    return ok(pricing.serialize_quote, row), 201


@bp.route("/rate-sheets/<sheet_id>/pricing-quotes", methods=["GET"])
@endpoint("GET", "/rate-sheets/<sheet_id>/pricing-quotes")
def list_sheet_quotes(caller, body, sheet_id):
    sheet = shared.get_rate_sheet(sheet_id)
    rows = [row for row in db.pricing_quotes.values() if row["rate_sheet_id"] == sheet["id"]]
    return listing(pricing.serialize_quote, rows)


@bp.route("/pricing-quotes", methods=["GET"])
@endpoint("GET", "/pricing-quotes")
def list_pricing_quotes(caller, body):
    rows = list(db.pricing_quotes.values())
    broker_id = query("broker_id")
    if broker_id:
        rows = [row for row in rows if row["broker_id"] == broker_id]
    product_code = query("product_code")
    if product_code:
        rows = [row for row in rows if row["product_code"] == product_code]
    return listing(pricing.serialize_quote, rows)


@bp.route("/pricing-quotes/<quote_id>", methods=["GET"])
@endpoint("GET", "/pricing-quotes/<quote_id>")
def get_pricing_quote(caller, body, quote_id):
    return ok(pricing.serialize_quote, shared.get_quote(quote_id))