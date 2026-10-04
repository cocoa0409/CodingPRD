"""Routes: projects, pay items and subcontractor quotes."""

from flask import request

import calc
import db
import services
import services_bid as svc
import views
from response import array_response, object_response
from util import parse_pagination, read_body, require_str

ALL_ROLES = ("PlatformAdmin", "Estimator", "ContractingOfficer", "ProjectManager",
             "Engineer", "Surety")


def _filtered(records, **filters):
    out = records
    for field, value in filters.items():
        if value is not None:
            out = [r for r in out if r[field] == value]
    return out


def _paginate(records, view):
    limit, offset = parse_pagination()
    return array_response([view(r) for r in records], limit, offset)


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

def create_project():
    payload = read_body(
        required=["project_code", "owner_agency_name", "bid_deadline_at"],
        optional=["contract_type", "retention_rate_pct", "advertised_dbe_goal_pct"],
        enums={"contract_type": svc.CONTRACT_TYPES},
    )
    return object_response(views.project_view(svc.create_project(payload)), 201)


def list_projects():
    records = _filtered(
        db.ordered("project"),
        bid_status=request.args.get("bid_status"),
        project_status=request.args.get("project_status"),
    )
    return _paginate(records, views.project_view)


def get_project(project_id):
    return object_response(views.project_view(services.get_project(project_id)))


def project_summary(project_id):
    project = services.get_project(project_id)
    calc.refresh_project_bid(project)
    reconciliation = calc.refresh_reconciliation(project)
    if reconciliation is None:
        overrun, underrun = calc.variance_counts(project)
        net = calc.net_adjustment_cents(project)
    else:
        overrun = reconciliation["overrun_item_count"]
        underrun = reconciliation["underrun_item_count"]
        net = reconciliation["net_adjustment_cents"]
    return object_response({
        "total_bid_cents": project["total_bid_cents"],
        "contract_value_cents": calc.settled_contract_value_cents(project),
        "unbalanced_bid_score": float(project["unbalanced_bid_score"]),
        "dbe_participation_pct": project["dbe_participation_pct"],
        "retention_balance_cents": project["retention_balance_cents"],
        "overrun_item_count": overrun,
        "underrun_item_count": underrun,
        "net_adjustment_cents": net,
    })


def seal_bid(project_id):
    project = services.get_project(project_id)
    return object_response(views.project_view(svc.seal_bid(project)))


def open_bid(project_id):
    project = services.get_project(project_id)
    return object_response(views.project_view(svc.open_bid(project)))


def recall_bid(project_id):
    payload = read_body(required=["reason_code"], enums={"reason_code": svc.RECALL_REASONS})
    project = services.get_project(project_id)
    return object_response(views.project_view(svc.recall_bid(project, payload["reason_code"])))


def reset_bid(project_id):
    project = services.get_project(project_id)
    return object_response(views.project_view(svc.reset_bid(project)))


def start_work(project_id):
    project = services.get_project(project_id)
    return object_response(views.project_view(svc.start_work(project)))


# ---------------------------------------------------------------------------
# BidItem
# ---------------------------------------------------------------------------

def create_item(project_id):
    payload = read_body(
        required=["item_code", "item_description", "unit_of_measure", "estimated_quantity"],
        optional=["overrun_threshold_pct", "underrun_threshold_pct"],
        enums={"unit_of_measure": svc.UNITS_OF_MEASURE},
    )
    project = services.get_project(project_id)
    return object_response(views.item_view(svc.create_item(project, payload)), 201)


def list_bid_items():
    records = _filtered(
        db.ordered("bid_item"),
        project_id=request.args.get("project_id"),
        item_status=request.args.get("item_status"),
    )
    return _paginate(records, views.item_view)


def get_bid_item(item_id):
    return object_response(views.item_view(services.get_item(item_id)))


def price_item(project_id, id):
    payload = read_body(required=["bid_unit_price_cents", "crew_day_labor_cents",
                                  "crew_day_equipment_cents", "daily_productivity_units"])
    project = services.get_project(project_id)
    item = services.get_item_in_project(project, id)
    return object_response(views.item_view(svc.price_item(project, item, payload)))


def submit_item(project_id, id):
    project = services.get_project(project_id)
    item = services.get_item_in_project(project, id)
    return object_response(views.item_view(svc.submit_item(project, item)))


def unsubmit_item(project_id, id):
    project = services.get_project(project_id)
    item = services.get_item_in_project(project, id)
    return object_response(views.item_view(svc.unsubmit_item(project, item)))


def close_item(project_id, id):
    project = services.get_project(project_id)
    item = services.get_item_in_project(project, id)
    return object_response(views.item_view(svc.close_item(project, item)))


# ---------------------------------------------------------------------------
# SubcontractorQuote
# ---------------------------------------------------------------------------

def create_quote():
    payload = read_body(
        required=["project_id", "trade_code", "contact_name", "quoted_amount_cents",
                  "quote_window_start", "quote_window_end"],
        optional=["unicap_registered", "good_faith_effort_basis"],
        enums={"good_faith_effort_basis": svc.GOOD_FAITH_BASES},
        booleans=["unicap_registered"],
    )
    return object_response(views.quote_view(svc.create_quote(payload)), 201)


def list_quotes():
    records = _filtered(
        db.ordered("quote"),
        project_id=request.args.get("project_id"),
        quote_status=request.args.get("quote_status"),
        trade_code=request.args.get("trade_code"),
    )
    return _paginate(records, views.quote_view)


def get_quote(quote_id):
    return object_response(views.quote_view(services.get_quote(quote_id)))


def carry_quote(quote_id):
    quote = services.get_quote(quote_id)
    return object_response(views.quote_view(svc.carry_quote(quote)))


def withdraw_quote(quote_id):
    quote = services.get_quote(quote_id)
    return object_response(views.quote_view(svc.withdraw_quote(quote)))


def select_quote(quote_id):
    quote = services.get_quote(quote_id)
    return object_response(views.quote_view(svc.select_quote(quote)))


def reject_quote(quote_id):
    quote = services.get_quote(quote_id)
    return object_response(views.quote_view(svc.reject_quote(quote)))


ROUTES = [
    ("POST", "/construction/projects", ("Estimator", "PlatformAdmin"), True, create_project),
    ("GET", "/construction/projects", ALL_ROLES, True, list_projects),
    ("GET", "/construction/projects/<project_id>", ALL_ROLES, True, get_project),
    ("GET", "/construction/projects/<project_id>/summary", ALL_ROLES, True, project_summary),
    ("POST", "/construction/projects/<project_id>/seal-bid", ("Estimator",), True, seal_bid),
    ("POST", "/construction/projects/<project_id>/open-bid", ("ContractingOfficer",), True, open_bid),
    ("POST", "/construction/projects/<project_id>/recall-bid", ("ContractingOfficer",), True,
     recall_bid),
    ("POST", "/construction/projects/<project_id>/reset-bid", ("ContractingOfficer",), True,
     reset_bid),
    ("POST", "/construction/projects/<project_id>/start-work", ("ProjectManager",), True, start_work),

    ("POST", "/construction/projects/<project_id>/bid-items", ("Estimator",), True, create_item),
    ("GET", "/construction/bid-items", ALL_ROLES, True, list_bid_items),
    ("GET", "/construction/bid-items/<item_id>", ALL_ROLES, True, get_bid_item),
    ("POST", "/construction/projects/<project_id>/bid-items/<id>/price", ("Estimator",), True,
     price_item),
    ("POST", "/construction/projects/<project_id>/bid-items/<id>/submit", ("Estimator",), True,
     submit_item),
    ("POST", "/construction/projects/<project_id>/bid-items/<id>/unsubmit", ("Estimator",), True,
     unsubmit_item),
    ("POST", "/construction/projects/<project_id>/bid-items/<id>/close", ("ProjectManager",), True,
     close_item),

    ("POST", "/construction/subcontractor-quotes", ("Estimator",), True, create_quote),
    ("GET", "/construction/subcontractor-quotes", ALL_ROLES, True, list_quotes),
    ("GET", "/construction/subcontractor-quotes/<quote_id>", ALL_ROLES, True, get_quote),
    ("POST", "/construction/subcontractor-quotes/<quote_id>/carry", ("Estimator",), True,
     carry_quote),
    ("POST", "/construction/subcontractor-quotes/<quote_id>/withdraw", ("Estimator",), True,
     withdraw_quote),
    ("POST", "/construction/subcontractor-quotes/<quote_id>/select", ("ContractingOfficer",), True,
     select_quote),
    ("POST", "/construction/subcontractor-quotes/<quote_id>/reject", ("ContractingOfficer",), True,
     reject_quote),
]
