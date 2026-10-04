"""Routes: the logical clock, distribution centers, suppliers and accounts.

Registered onto the shared `app` from views_app.py.
"""

from flask import request as flask_request

from common import body_json, find, query_flag, require_int, require_str
from db import db
from response import ok_object
from route_util import gate, paginated
from serializers import account as ser_account
from serializers import availability_report as ser_report
from serializers import dc as ser_dc
from serializers import supplier as ser_supplier
from svc_catalog import (create_supplier, file_availability_report,
                         get_supplier, supplier_matches)
from svc_dc import (clock_tick_payload, create_dc, get_dc, reeducate,
                    roll_cutoff, set_current_utc)
from svc_orders import account_matches, create_account, get_account


def register(app):

    # ------------------------------------------------------------- clock
    @app.post("/_clock/set_current_utc")
    def _clock():
        gate("POST", "/_clock/set_current_utc")
        body = body_json()
        raw = require_str(body, "current_utc")
        from common import parse_clock
        set_current_utc(db, parse_clock(raw))
        return ok_object(clock_tick_payload(db))

    # --------------------------------------------- distribution centers
    @app.post("/distribution-centers")
    def _dc_create():
        gate("POST", "/distribution-centers")
        return ok_object(ser_dc(create_dc(db, body_json())), 201)

    @app.get("/distribution-centers")
    def _dc_list():
        gate("GET", "/distribution-centers")
        region = flask_request.args.get("region")
        rows = [d for d in db.distribution_centers.values()
                if not region or d.get("region") == region]
        return paginated(rows, ser_dc)

    @app.get("/distribution-centers/<dc_id>")
    def _dc_get(dc_id):
        gate("GET", "/distribution-centers/<dc_id>")
        return ok_object(ser_dc(get_dc(db, dc_id)))

    @app.post("/distribution-centers/<dc_id>/roll_cutoff")
    def _dc_roll(dc_id):
        gate("POST", "/distribution-centers/<dc_id>/roll_cutoff")
        return ok_object(ser_dc(roll_cutoff(db, get_dc(db, dc_id))))

    @app.post("/distribution-centers/<dc_id>/reeducate")
    def _dc_reeducate(dc_id):
        gate("POST", "/distribution-centers/<dc_id>/reeducate")
        return ok_object(ser_dc(reeducate(db, get_dc(db, dc_id), body_json())))

    # --------------------------------------------------------- suppliers
    @app.post("/suppliers")
    def _supplier_create():
        gate("POST", "/suppliers")
        return ok_object(ser_supplier(create_supplier(db, body_json())), 201)

    @app.get("/suppliers")
    def _supplier_list():
        gate("GET", "/suppliers")
        rows = [s for s in db.suppliers.values()
                if supplier_matches(s, flask_request.args)]
        return paginated(rows, ser_supplier)

    @app.get("/suppliers/<supplier_id>")
    def _supplier_get(supplier_id):
        gate("GET", "/suppliers/<supplier_id>")
        return ok_object(ser_supplier(get_supplier(db, supplier_id)))

    @app.get("/suppliers/<supplier_id>/availability-reports")
    def _supplier_reports(supplier_id):
        gate("GET", "/suppliers/<supplier_id>/availability-reports")
        get_supplier(db, supplier_id)
        rows = [r for r in db.supplier_availability_reports.values()
                if r.get("supplier_id") == supplier_id]
        return paginated(rows, ser_report)

    @app.post("/suppliers/<supplier_id>/availability-reports")
    def _supplier_report_create(supplier_id):
        gate("POST", "/suppliers/<supplier_id>/availability-reports")
        supplier = get_supplier(db, supplier_id)
        file_availability_report(db, supplier, body_json())
        return ok_object(ser_supplier(supplier), 201)

    # --------------------------------------------------------- accounts
    @app.post("/accounts")
    def _account_create():
        gate("POST", "/accounts")
        return ok_object(ser_account(create_account(db, body_json())), 201)

    @app.get("/accounts")
    def _account_list():
        gate("GET", "/accounts")
        rows = [a for a in db.accounts.values()
                if account_matches(a, flask_request.args)]
        return paginated(rows, ser_account)

    @app.get("/accounts/<account_id>")
    def _account_get(account_id):
        gate("GET", "/accounts/<account_id>")
        return ok_object(ser_account(get_account(db, account_id)))