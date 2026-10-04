"""Routes: catalog items, attributes, cross-references, curation and stock."""

from flask import request as flask_request

from common import body_json, require
from db import db
from errors import not_found
from response import ok_object
from route_util import gate, paginated
from serializers import (catalog_item as ser_item)
from serializers import (availability_report as ser_report)
from serializers import (curation_review as ser_review)
from serializers import (curation_review_item as ser_review_item)
from serializers import (item_attribute as ser_attribute)
from serializers import (item_cross_reference as ser_cross_reference)
from serializers import (order_line as ser_line)
from serializers import (stock as ser_stock)
from svc_catalog import (create_attribute, create_cross_reference,
                         create_curation_review, create_item, create_stock,
                         get_item, get_stock, item_attributes, item_availability,
                         item_cross_references, item_matches,
                         revoke_curation_review, stock_matches)


def _curation_review(review_id):
    record = db.curation_reviews.get(review_id)
    if record is None:
        raise not_found("ERR_INVALID_REQUEST",
                        "No curation review exists for id '%s'." % review_id)
    return record


def register(app):

    # ------------------------------------------------------------- items
    @app.post("/items")
    def _item_create():
        gate("POST", "/items")
        return ok_object(ser_item(create_item(db, body_json())), 201)

    @app.get("/items")
    def _item_list():
        gate("GET", "/items")
        rows = [i for i in db.catalog_items.values()
                if item_matches(db, i, flask_request.args)]
        return paginated(rows, ser_item)

    @app.get("/items/<item_id>")
    def _item_get(item_id):
        gate("GET", "/items/<item_id>")
        item = get_item(db, item_id)
        return ok_object(ser_item(item, item_availability(db, item)))

    @app.get("/items/<item_id>/order-lines")
    def _item_order_lines(item_id):
        gate("GET", "/items/<item_id>/order-lines")
        get_item(db, item_id)
        rows = [l for l in db.order_lines.values() if l.get("item_id") == item_id]
        return paginated(rows, ser_line)

    @app.get("/items/<item_id>/availability-reports")
    def _item_reports(item_id):
        gate("GET", "/items/<item_id>/availability-reports")
        get_item(db, item_id)
        rows = [r for r in db.supplier_availability_reports.values()
                if r.get("item_id") == item_id]
        return paginated(rows, ser_report)

    @app.get("/items/<item_id>/curation-review-items")
    def _item_review_items(item_id):
        gate("GET", "/items/<item_id>/curation-review-items")
        get_item(db, item_id)
        rows = [m for m in db.curation_review_items.values()
                if m.get("item_id") == item_id]
        return paginated(rows, ser_review_item)

    # -------------------------------------------------------- attributes
    @app.post("/items/<item_id>/attributes")
    def _attribute_create(item_id):
        gate("POST", "/items/<item_id>/attributes")
        item = get_item(db, item_id)
        return ok_object(ser_attribute(create_attribute(db, item, body_json())), 201)

    @app.get("/items/<item_id>/attributes")
    def _attribute_list(item_id):
        gate("GET", "/items/<item_id>/attributes")
        get_item(db, item_id)
        return paginated(item_attributes(db, item_id), ser_attribute)

    # --------------------------------------------------- cross-references
    @app.post("/items/<item_id>/cross-references")
    def _cross_reference_create(item_id):
        gate("POST", "/items/<item_id>/cross-references")
        item = get_item(db, item_id)
        return ok_object(ser_cross_reference(create_cross_reference(db, item, body_json())), 201)

    @app.get("/items/<item_id>/cross-references")
    def _cross_reference_list(item_id):
        gate("GET", "/items/<item_id>/cross-references")
        get_item(db, item_id)
        return paginated(item_cross_references(db, item_id), ser_cross_reference)

    # ------------------------------------------------------------- curation
    @app.post("/curation-reviews")
    def _review_create():
        user_id, _role = gate("POST", "/curation-reviews")
        body = body_json()
        item_ids = require(body, "item_ids")
        return ok_object(ser_review(create_curation_review(db, user_id, item_ids)), 201)

    @app.get("/curation-reviews")
    def _review_list():
        gate("GET", "/curation-reviews")
        status = flask_request.args.get("review_status")
        rows = [r for r in db.curation_reviews.values()
                if not status or r.get("review_status") == status]
        return paginated(rows, ser_review)

    @app.get("/curation-reviews/<review_id>")
    def _review_get(review_id):
        gate("GET", "/curation-reviews/<review_id>")
        return ok_object(ser_review(_curation_review(review_id)))

    @app.get("/curation-reviews/<review_id>/items")
    def _review_items(review_id):
        gate("GET", "/curation-reviews/<review_id>/items")
        _curation_review(review_id)
        rows = [m for m in db.curation_review_items.values()
                if m.get("review_id") == review_id]
        return paginated(rows, ser_review_item)

    @app.post("/curation-reviews/<review_id>/revoke")
    def _review_revoke(review_id):
        gate("POST", "/curation-reviews/<review_id>/revoke")
        return ok_object(ser_review(revoke_curation_review(db, _curation_review(review_id))))

    # --------------------------------------------------------------- stock
    @app.post("/stock")
    def _stock_create():
        gate("POST", "/stock")
        return ok_object(ser_stock(create_stock(db, body_json())), 201)

    @app.get("/stock")
    def _stock_list():
        gate("GET", "/stock")
        rows = [r for r in db.stock_rows.values()
                if stock_matches(r, flask_request.args)]
        return paginated(rows, ser_stock)

    @app.get("/stock/<stock_id>")
    def _stock_get(stock_id):
        gate("GET", "/stock/<stock_id>")
        return ok_object(ser_stock(get_stock(db, stock_id)))