"""Quote issuance, listing and acceptance (PRD section 3.5)."""

from flask import Blueprint

import calc
import cascades
import validate as v
from auth import authenticate
from envelope import list_response, object_response
from errors import ApiError
from store import parse_date, public, public_list, store

bp = Blueprint("quotes", __name__)

QUOTE_READ_ROLES = [
    "ManufacturerAdmin",
    "ComplianceOfficer",
    "DesignConsultant",
    "ClientRepresentative",
]
VARIANTS = ("PROVISIONAL", "FIRM")


@bp.route("/playground/quotes", methods=["POST"])
def issue_quote():
    authenticate(["DesignConsultant"])
    body = v.raw_body()
    resolved = v.resolve_fks(body, [
        ("project_id", "project", True),
        ("rendering_id", "rendering", True),
    ])
    v.string(body, "project_id", min_len=1)
    v.string(body, "rendering_id", min_len=1)
    variant = v.enum(body, "variant", VARIANTS)
    valid_until = v.date_field(body, "valid_until")
    expected_version = v.integer(body, "expected_project_version", minimum=0)
    project = resolved["project_id"]
    rendering = resolved["rendering_id"]

    if expected_version != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")

    if rendering["status"] != "ISSUED":
        raise ApiError("ERR_RENDERING_NOT_ISSUED")

    if variant == "FIRM":
        for area in store.project_areas(project["id"]):
            if area["surfacing_depth_cm"] < area["required_surfacing_depth_cm"]:
                raise ApiError("ERR_SURFACING_DEPTH_INSUFFICIENT")
        standard = store.active_standard()
        if calc.accessible_route_demanded(project, standard):
            if not calc.accessible_route_satisfied(project):
                raise ApiError("ERR_ACCESSIBLE_ROUTE_MISSING")

    if rendering["project_id"] != project["id"]:
        raise ApiError("ERR_RENDERING_PROJECT_MISMATCH")

    pricing = calc.quote_pricing(project["id"], variant)

    if variant == "FIRM" and pricing["total_cents"] > project["budget_cents"]:
        raise ApiError("ERR_QUOTE_EXCEEDS_BUDGET")

    row = store.insert("quote", {
        "project_id": project["id"],
        "rendering_id": rendering["id"],
        "variant": variant,
        "valid_until": valid_until.isoformat(),
        "subtotal_cents": pricing["subtotal_cents"],
        "freight_cents": pricing["freight_cents"],
        "discount_cents": pricing["discount_cents"],
        "total_cents": pricing["total_cents"],
        "priced_unit_count": pricing["priced_unit_count"],
        "status": "ISSUED",
    })
    cascades.expire_issued_quotes(project["id"], exclude_id=row["id"])
    store.touch(project)
    return object_response(public(row), 201)


@bp.route("/playground/quotes", methods=["GET"])
def list_quotes():
    authenticate(QUOTE_READ_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all("quote"), {
        "project_id": "project_id",
        "rendering_id": "rendering_id",
        "status": "status",
        "variant": "variant",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.route("/playground/quotes/<quote_id>", methods=["GET"])
def get_quote(quote_id):
    authenticate(QUOTE_READ_ROLES)
    return object_response(public(store.require("quote", quote_id)))


@bp.route("/playground/quotes/<quote_id>/accept", methods=["POST"])
def accept_quote(quote_id):
    authenticate(["ClientRepresentative"])
    quote = store.require("quote", quote_id)

    if quote["status"] != "ISSUED":
        raise ApiError("ERR_QUOTE_NOT_ACCEPTED")

    rendering = store.get("rendering", quote["rendering_id"])
    if rendering is None or rendering["status"] != "ISSUED":
        raise ApiError("ERR_RENDERING_NOT_ISSUED")

    if store.clock.today() > parse_date(quote["valid_until"]):
        raise ApiError("ERR_QUOTE_EXPIRED")

    if quote["variant"] != "FIRM":
        raise ApiError("ERR_PROVISIONAL_QUOTE_NOT_ACCEPTABLE")

    quote["status"] = "ACCEPTED"
    store.touch(quote)
    cascades.expire_issued_quotes(quote["project_id"], exclude_id=quote_id)
    return object_response(public(quote))
