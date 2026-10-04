"""Flat get/list endpoints (globally-unique ids) + clock endpoint."""
from flask import Blueprint, request

from db import store
from errors import not_found, err
from helpers import serialize, paginate, parse_dt
from middleware import require_read_role, require_role
from response import ok
import engine

bp = Blueprint("flat", __name__)

_FLAT_GETS = [
    ("seasons", "seasons", "season"),
    ("service_lines", "service-lines", "service_line"),
    ("room_classes", "room-classes", "room_class"),
    ("studies", "comparability-studies", "study"),
    ("filings", "rate-filings", "filing"),
    ("reservations", "reservations", "reservation"),
    ("receipts_reports", "receipts-reports", "report"),
    ("fee_statements", "fee-statements", "statement"),
    ("capital_projects", "capital-projects", "project"),
    ("housing_units", "housing-units", "housing_unit"),
    ("hires", "seasonal-hires", "hire"),
    ("vouchers", "transport-vouchers", "voucher"),
    ("incidents", "environmental-incidents", "incident"),
]

_FLAT_LIST_FILTERS = {
    "rate-filings": ["season_id", "room_class_id", "reference_study_id", "revision_of_id", "status"],
    "reservations": ["season_id", "room_class_id", "status", "guest_ref"],
    "receipts-reports": ["period_month", "service_line_id", "status"],
    "seasonal-hires": ["season_id", "service_line_id", "housing_unit_id", "status"],
    "transport-vouchers": ["hire_id", "status"],
}


def _serialize_entity(attr, e):
    if attr == "capital_projects":
        return engine.project_out(e)
    return serialize(e)


def _register_flat_get(attr, path, kind):
    coll = attr

    def handler(item_id):
        require_read_role()
        e = getattr(store, coll).get(item_id)
        if not e:
            raise not_found(kind)
        return ok(_serialize_entity(coll, e))

    bp.add_url_rule(f"/{path}/<item_id>", f"flat_get_{attr}", handler, methods=["GET"])


for attr, path, kind in _FLAT_GETS:
    _register_flat_get(attr, path, kind)


def _register_flat_list(attr, path):
    coll = attr
    filters = _FLAT_LIST_FILTERS[path]

    def handler():
        require_read_role()
        items = list(getattr(store, coll).values())
        for key in filters:
            v = request.args.get(key)
            if v:
                items = [e for e in items if str(e.get(key)) == v]
        page, limit, offset, total = paginate(items)
        if coll == "capital_projects":
            by_id = {e["id"]: e for e in items}
            page = [engine.project_out(by_id[row["id"]]) for row in page]
        return ok(page, 200, True, limit, offset, total)

    bp.add_url_rule(f"/{path}", f"flat_list_{attr}", handler, methods=["GET"])


for attr, path in [("filings", "rate-filings"), ("reservations", "reservations"),
                   ("receipts_reports", "receipts-reports"), ("hires", "seasonal-hires"),
                   ("vouchers", "transport-vouchers")]:
    _register_flat_list(attr, path)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role("SystemTestHarness")
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or "current_utc" not in body:
        raise err("ERR_INVALID_REQUEST", 400, "current_utc required")
    new_dt = parse_dt(body["current_utc"], "current_utc")
    engine.advance_clock(new_dt)
    return ok({})
