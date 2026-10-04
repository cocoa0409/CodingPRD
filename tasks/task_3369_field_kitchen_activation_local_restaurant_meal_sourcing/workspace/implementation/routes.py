"""Every endpoint of the PRD section 4 table, mounted under /field-ops.

Each handler applies the PRD 2.5 precedence ladder in order: rule 1 body shape,
rules 2-3 auth, rules 4-5 ownership, rule 6 path ids, rule 7 body foreign keys,
then the state and business rules.
"""

from flask import Blueprint

from core import CLOCK, DB, envelope, fmt_dt, now, paginate, sort_asc, sort_desc
from errors import fail
from models import (
    create_assessment,
    create_distribution_run,
    create_distribution_site,
    create_distribution_stop,
    create_donor_commitment,
    create_field_kitchen,
    create_incident,
    create_ingredient_purchase,
    create_meal_order,
    create_partner_kitchen,
    create_supplier,
    refresh,
    refresh_incident,
    ser,
)
from parsers import (
    parse_assessment_create,
    parse_clock,
    parse_commitment_transition,
    parse_distribution_run_create,
    parse_distribution_site_create,
    parse_distribution_stop_create,
    parse_donor_commitment_create,
    parse_field_kitchen_create,
    parse_field_kitchen_transition,
    parse_incident_create,
    parse_incident_transition,
    parse_ingredient_purchase_create,
    parse_inspection,
    parse_meal_order_create,
    parse_meal_order_transition,
    parse_partner_kitchen_create,
    parse_partner_kitchen_transition,
    parse_purchase_transition,
    parse_run_transition,
    parse_stop_transition,
    parse_supplier_create,
)
from services import (
    inspect_field_kitchen,
    transition_commitment,
    transition_field_kitchen,
    transition_incident,
    transition_meal_order,
    transition_partner_kitchen,
    transition_purchase,
    transition_run,
    transition_stop,
)
from validations import (
    auth_headers,
    get_body,
    parse_pagination,
    path_row,
    query_filter,
    ref_row,
    require_role,
)

bp = Blueprint("field_ops", __name__, url_prefix="/field-ops")

ALL_ROLES = ["PlatformAdmin", "FieldCoordinator", "FoodSafetyOfficer", "PartnershipLead",
             "ProductionPlanner", "SourcingOfficer", "LogisticsCoordinator", "DonorLiaison",
             "KitchenOperator", "SiteCoordinator"]


def ok(data, response_type="object", pagination=None, status=200):
    return envelope(data, response_type, pagination), status


def one(kind, row):
    refresh(kind, row)
    return ser(kind, row)


def authed(allowed):
    """Rules 2 and 3."""
    role, user_id = auth_headers()
    require_role(role, allowed)
    return role, user_id


def listing(kind, rows, reverse=False):
    limit, offset = parse_pagination()
    ordered = sort_desc(rows) if reverse else sort_asc(rows)
    page, pagination = paginate(ordered, limit, offset)
    return ok([one(kind, row) for row in page], "array", pagination)


# --------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------

@bp.post("/incidents")
def post_incident():
    data = parse_incident_create(get_body())
    authed(["PlatformAdmin"])
    row = create_incident(data)
    return ok(one("incidents", row), status=201)


@bp.get("/incidents")
def get_incidents():
    authed(ALL_ROLES)
    status_filter = query_filter("status")
    rows = list(DB["incidents"].values())
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    return listing("incidents", rows, reverse=True)


@bp.get("/incidents/<incident_id>")
def get_incident(incident_id):
    authed(ALL_ROLES)
    row = path_row("incidents", incident_id)
    return ok(one("incidents", row))


@bp.post("/incidents/<incident_id>/transitions")
def post_incident_transition(incident_id):
    data = parse_incident_transition(get_body())
    authed(["PlatformAdmin", "FieldCoordinator"])
    row = path_row("incidents", incident_id)
    row = transition_incident(row, data)
    return ok(one("incidents", row))


@bp.get("/incidents/<incident_id>/accountability-report")
def get_accountability_report(incident_id):
    authed(["PlatformAdmin", "DonorLiaison", "FieldCoordinator"])
    row = path_row("incidents", incident_id)
    refresh_incident(row)
    return ok({
        "incident_id": row["id"],
        "local_sourcing_pct": row["local_sourcing_pct"],
        "cost_per_meal_cents": row["cost_per_meal_cents"],
        "delivered_meal_total": row["delivered_meal_total"],
        "committed_cents": row["committed_cents"],
        "spent_cents": row["spent_cents"],
        "donor_report_flag": ("BELOW_LOCAL_SOURCING_TARGET"
                              if row["local_sourcing_pct"] < 30 else "ON_TARGET"),
    })


# --------------------------------------------------------------------------
# Assessments
# --------------------------------------------------------------------------

@bp.post("/assessments")
def post_assessment():
    data = parse_assessment_create(get_body())
    authed(["FieldCoordinator"])
    row = create_assessment(data)
    return ok(one("assessments", row), status=201)


@bp.get("/incidents/<incident_id>/assessments")
def get_incident_assessments(incident_id):
    authed(ALL_ROLES)
    incident = path_row("incidents", incident_id)
    rows = [a for a in DB["assessments"].values() if a["incident_id"] == incident["id"]]
    return listing("assessments", rows)


# --------------------------------------------------------------------------
# Field kitchens
# --------------------------------------------------------------------------

@bp.post("/field-kitchens")
def post_field_kitchen():
    data = parse_field_kitchen_create(get_body())
    authed(["FieldCoordinator"])
    row = create_field_kitchen(data)
    return ok(one("field_kitchens", row), status=201)


@bp.get("/field-kitchens")
def get_field_kitchens():
    authed(ALL_ROLES)
    rows = list(DB["field_kitchens"].values())
    incident_filter = query_filter("incident_id")
    if incident_filter is not None:
        rows = [r for r in rows if r["incident_id"] == incident_filter]
    assessment_filter = query_filter("assessment_id")
    if assessment_filter is not None:
        rows = [r for r in rows if r["assessment_id"] == assessment_filter]
    return listing("field_kitchens", rows)


@bp.get("/field-kitchens/<kitchen_id>")
def get_field_kitchen(kitchen_id):
    authed(ALL_ROLES)
    row = path_row("field_kitchens", kitchen_id)
    return ok(one("field_kitchens", row))


@bp.post("/field-kitchens/<kitchen_id>/transitions")
def post_field_kitchen_transition(kitchen_id):
    data = parse_field_kitchen_transition(get_body())
    authed(["FieldCoordinator", "FoodSafetyOfficer", "PlatformAdmin"])
    row = path_row("field_kitchens", kitchen_id)
    row = transition_field_kitchen(row, data)
    return ok(one("field_kitchens", row))


@bp.post("/field-kitchens/<kitchen_id>/inspections")
def post_field_kitchen_inspection(kitchen_id):
    data = parse_inspection(get_body())
    authed(["FoodSafetyOfficer"])
    row = path_row("field_kitchens", kitchen_id)
    row = inspect_field_kitchen(row, data)
    return ok(one("field_kitchens", row))


# --------------------------------------------------------------------------
# Partner kitchens
# --------------------------------------------------------------------------

@bp.post("/partner-kitchens")
def post_partner_kitchen():
    data = parse_partner_kitchen_create(get_body())
    authed(["PartnershipLead"])
    row = create_partner_kitchen(data)
    return ok(one("partner_kitchens", row), status=201)


@bp.get("/incidents/<incident_id>/partner-kitchens")
def get_incident_partner_kitchens(incident_id):
    authed(ALL_ROLES)
    incident = path_row("incidents", incident_id)
    rows = [k for k in DB["partner_kitchens"].values() if k["incident_id"] == incident["id"]]
    return listing("partner_kitchens", rows)


@bp.get("/partner-kitchens/<kitchen_id>")
def get_partner_kitchen(kitchen_id):
    authed(ALL_ROLES)
    row = path_row("partner_kitchens", kitchen_id)
    return ok(one("partner_kitchens", row))


@bp.post("/partner-kitchens/<kitchen_id>/transitions")
def post_partner_kitchen_transition(kitchen_id):
    data = parse_partner_kitchen_transition(get_body())
    role, user_id = authed(["PartnershipLead", "KitchenOperator", "PlatformAdmin"])
    # Rule 4 -- a KitchenOperator may only drive its own kitchen.
    if role == "KitchenOperator":
        existing = DB["partner_kitchens"].get(kitchen_id)
        if existing is not None and existing["id"] != user_id:
            fail("ERR_NOT_RESOURCE_OWNER")
    row = path_row("partner_kitchens", kitchen_id)
    row = transition_partner_kitchen(row, data)
    return ok(one("partner_kitchens", row))


# --------------------------------------------------------------------------
# Meal orders
# --------------------------------------------------------------------------

@bp.post("/meal-orders")
def post_meal_order():
    data = parse_meal_order_create(get_body())
    authed(["ProductionPlanner", "KitchenOperator"])
    row = create_meal_order(data)
    return ok(one("meal_orders", row), status=201)


@bp.get("/meal-orders")
def get_meal_orders():
    authed(ALL_ROLES)
    rows = list(DB["meal_orders"].values())
    for key, field in (("incident_id", "incident_id"),
                       ("partner_kitchen_id", "partner_kitchen_id"),
                       ("distribution_run_id", "distribution_run_id")):
        value = query_filter(key)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return listing("meal_orders", rows)


@bp.get("/meal-orders/<order_id>")
def get_meal_order(order_id):
    authed(ALL_ROLES)
    row = path_row("meal_orders", order_id)
    return ok(one("meal_orders", row))


@bp.post("/meal-orders/<order_id>/transitions")
def post_meal_order_transition(order_id):
    data = parse_meal_order_transition(get_body())
    role, user_id = authed(["ProductionPlanner", "KitchenOperator",
                            "FoodSafetyOfficer", "LogisticsCoordinator"])
    # Rule 4 -- a KitchenOperator may only act on its own batch.
    if role == "KitchenOperator":
        existing = DB["meal_orders"].get(order_id)
        if existing is not None and existing["partner_kitchen_id"] != user_id:
            fail("ERR_NOT_RESOURCE_OWNER")
    row = path_row("meal_orders", order_id)
    # Rule 7 -- a dispatch target named in the body must resolve.
    if data.get("distribution_run_id") is not None:
        ref_row("distribution_runs", data["distribution_run_id"])
    row = transition_meal_order(row, data)
    return ok(one("meal_orders", row))


# --------------------------------------------------------------------------
# Suppliers and sourcing orders
# --------------------------------------------------------------------------

@bp.post("/suppliers")
def post_supplier():
    data = parse_supplier_create(get_body())
    authed(["SourcingOfficer"])
    row = create_supplier(data)
    return ok(one("suppliers", row), status=201)


@bp.get("/incidents/<incident_id>/suppliers")
def get_incident_suppliers(incident_id):
    authed(ALL_ROLES)
    incident = path_row("incidents", incident_id)
    rows = [s for s in DB["suppliers"].values() if s["incident_id"] == incident["id"]]
    return listing("suppliers", rows)


@bp.post("/ingredient-purchases")
def post_ingredient_purchase():
    data = parse_ingredient_purchase_create(get_body())
    authed(["SourcingOfficer"])
    row = create_ingredient_purchase(data)
    return ok(one("ingredient_purchases", row), status=201)


@bp.get("/ingredient-purchases")
def get_ingredient_purchases():
    authed(ALL_ROLES)
    rows = list(DB["ingredient_purchases"].values())
    for key in ("incident_id", "supplier_id", "partner_kitchen_id"):
        value = query_filter(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return listing("ingredient_purchases", rows)


@bp.get("/ingredient-purchases/<purchase_id>")
def get_ingredient_purchase(purchase_id):
    authed(ALL_ROLES)
    row = path_row("ingredient_purchases", purchase_id)
    return ok(one("ingredient_purchases", row))


@bp.post("/ingredient-purchases/<purchase_id>/transitions")
def post_ingredient_purchase_transition(purchase_id):
    data = parse_purchase_transition(get_body())
    authed(["SourcingOfficer", "PlatformAdmin"])
    row = path_row("ingredient_purchases", purchase_id)
    row = transition_purchase(row, data)
    return ok(one("ingredient_purchases", row))


# --------------------------------------------------------------------------
# Distribution sites, runs and stops
# --------------------------------------------------------------------------

@bp.post("/distribution-sites")
def post_distribution_site():
    data = parse_distribution_site_create(get_body())
    authed(["LogisticsCoordinator"])
    row = create_distribution_site(data)
    return ok(one("distribution_sites", row), status=201)


@bp.get("/incidents/<incident_id>/distribution-sites")
def get_incident_distribution_sites(incident_id):
    authed(ALL_ROLES)
    incident = path_row("incidents", incident_id)
    rows = [s for s in DB["distribution_sites"].values() if s["incident_id"] == incident["id"]]
    return listing("distribution_sites", rows)


@bp.post("/distribution-runs")
def post_distribution_run():
    data = parse_distribution_run_create(get_body())
    authed(["LogisticsCoordinator"])
    row = create_distribution_run(data)
    return ok(one("distribution_runs", row), status=201)


@bp.get("/distribution-runs")
def get_distribution_runs():
    authed(ALL_ROLES)
    rows = list(DB["distribution_runs"].values())
    incident_filter = query_filter("incident_id")
    if incident_filter is not None:
        rows = [r for r in rows if r["incident_id"] == incident_filter]
    kitchen_filter = query_filter("field_kitchen_id")
    if kitchen_filter is not None:
        rows = [r for r in rows if r["field_kitchen_id"] == kitchen_filter]
    return listing("distribution_runs", rows)


@bp.get("/distribution-runs/<run_id>")
def get_distribution_run(run_id):
    authed(ALL_ROLES)
    row = path_row("distribution_runs", run_id)
    return ok(one("distribution_runs", row))


@bp.post("/distribution-runs/<run_id>/transitions")
def post_distribution_run_transition(run_id):
    data = parse_run_transition(get_body())
    authed(["LogisticsCoordinator", "PlatformAdmin"])
    row = path_row("distribution_runs", run_id)
    row = transition_run(row, data)
    return ok(one("distribution_runs", row))


@bp.post("/distribution-stops")
def post_distribution_stop():
    data = parse_distribution_stop_create(get_body())
    authed(["LogisticsCoordinator"])
    row = create_distribution_stop(data)
    return ok(one("distribution_stops", row), status=201)


@bp.get("/distribution-stops")
def get_distribution_stops():
    authed(ALL_ROLES)
    rows = list(DB["distribution_stops"].values())
    run_filter = query_filter("distribution_run_id")
    if run_filter is not None:
        rows = [r for r in rows if r["distribution_run_id"] == run_filter]
    site_filter = query_filter("distribution_site_id")
    if site_filter is not None:
        rows = [r for r in rows if r["distribution_site_id"] == site_filter]
    return listing("distribution_stops", rows)


@bp.get("/distribution-stops/<stop_id>")
def get_distribution_stop(stop_id):
    authed(ALL_ROLES)
    row = path_row("distribution_stops", stop_id)
    return ok(one("distribution_stops", row))


@bp.post("/distribution-stops/<stop_id>/transitions")
def post_distribution_stop_transition(stop_id):
    data = parse_stop_transition(get_body())
    role, user_id = authed(["SiteCoordinator", "LogisticsCoordinator", "PlatformAdmin"])
    # Rule 5 -- a SiteCoordinator may only confirm handover at its own site.
    if role == "SiteCoordinator":
        existing = DB["distribution_stops"].get(stop_id)
        if existing is not None and existing["distribution_site_id"] != user_id:
            fail("ERR_NOT_RESOURCE_OWNER")
    row = path_row("distribution_stops", stop_id)
    row = transition_stop(row, data)
    return ok(one("distribution_stops", row))


# --------------------------------------------------------------------------
# Donor commitments and the logical clock
# --------------------------------------------------------------------------

@bp.post("/donor-commitments")
def post_donor_commitment():
    data = parse_donor_commitment_create(get_body())
    authed(["DonorLiaison"])
    row = create_donor_commitment(data)
    return ok(one("donor_commitments", row), status=201)


@bp.get("/incidents/<incident_id>/donor-commitments")
def get_incident_donor_commitments(incident_id):
    authed(ALL_ROLES)
    incident = path_row("incidents", incident_id)
    rows = [c for c in DB["donor_commitments"].values() if c["incident_id"] == incident["id"]]
    return listing("donor_commitments", rows)


@bp.post("/donor-commitments/<commitment_id>/transitions")
def post_donor_commitment_transition(commitment_id):
    data = parse_commitment_transition(get_body())
    authed(["DonorLiaison", "PlatformAdmin"])
    row = path_row("donor_commitments", commitment_id)
    row = transition_commitment(row, data)
    return ok(one("donor_commitments", row))


@bp.post("/_clock/set_current_utc")
def post_clock():
    data = parse_clock(get_body())
    authed(["PlatformAdmin"])
    CLOCK["now"] = data["to_iso8601"]
    return ok({"current_utc": fmt_dt(CLOCK["now"])})
