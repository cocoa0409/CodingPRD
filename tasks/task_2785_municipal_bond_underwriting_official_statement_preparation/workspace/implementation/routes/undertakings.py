"""Continuing disclosure undertakings, Rule 15c2-12 (PRD 3.4)."""
from flask import Blueprint

import db
import lookup
import response
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authenticate, require_deal_ownership
from validation import parse_body, query_value, sorted_rows, spec

bp = Blueprint("undertakings", __name__)

UNDERTAKING_SPECS = [
    spec("annual_report_due_days", "integer", minimum=120, maximum=270),
    spec("material_event_notice_days", "integer", minimum=1, maximum=10),
    spec("dissemination_agent", "string", min_len=1, max_len=120),
    spec("audited_financials_included", "boolean", required=False, default=True),
]


@bp.route("/bond-offerings/deals/<deal_id>/undertakings", methods=["POST"])
def create_undertaking(deal_id):
    actor = authenticate(["BondCounsel", "MunicipalAdvisor"])
    deal = lookup.get_deal(deal_id)
    body = parse_body(UNDERTAKING_SPECS)
    require_deal_ownership(actor, deal)
    row = db.new_row(
        deal_id=deal_id,
        annual_report_due_days=body["annual_report_due_days"],
        material_event_notice_days=body["material_event_notice_days"],
        dissemination_agent=body["dissemination_agent"],
        audited_financials_included=body["audited_financials_included"],
        status="DRAFT",
    )
    db.db.undertakings[row["id"]] = row
    return response.created(serializers.undertaking(row))


@bp.route("/bond-offerings/deals/<deal_id>/undertakings", methods=["GET"])
def list_undertakings(deal_id):
    authenticate(ALL_ROLES)
    lookup.get_deal(deal_id)
    rows = sorted_rows(lookup.undertakings_of_deal(deal_id))
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return response.paginated(rows, serializers.undertaking)


@bp.route("/bond-offerings/undertakings/<undertaking_id>/activate", methods=["POST"])
def activate_undertaking(undertaking_id):
    actor = authenticate(["IssuerOfficial"])
    undertaking = lookup.get_undertaking(undertaking_id)
    parse_body([])
    deal = lookup.deal_of_undertaking(undertaking)
    require_deal_ownership(actor, deal)
    if undertaking["status"] != "DRAFT":
        raise ApiError("ERR_UNDERTAKING_INVALID_STATE")
    if deal["status"] in ("CLOSED", "CANCELLED"):
        raise ApiError("ERR_DEAL_INVALID_STATE")
    for other in lookup.undertakings_of_deal(deal["id"]):
        if other["id"] != undertaking_id and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            db.touch(other)
    undertaking["status"] = "ACTIVE"
    db.touch(undertaking)
    return response.ok(serializers.undertaking(undertaking))
