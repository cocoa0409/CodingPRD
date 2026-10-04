"""Award issuance (POST /grants/applications/{id}/award) and award reads."""
from datetime import timedelta

from flask import Blueprint, request

from constants import (
    AWARD_PERIOD_DAYS,
    ROLE_GRANTS_OFFICER,
    TERM_RESTRICTED_DRAW_DOWN,
    TERM_STANDARD,
)
from db import STORE, clock_now, new_entity, touch
from errors import fail
from serializers import award_json
from services import accepted_jit_for, build_award_budget, get
from util import (
    auth_context,
    get_body,
    ok_list,
    ok_object,
    parse_pagination,
    req_dt,
    require_role,
    sort_and_page,
)

bp = Blueprint("awards", __name__)


@bp.route("/grants/applications/<application_id>/award", methods=["POST"])
def issue_award(application_id):
    user_id, role = auth_context()
    require_role(role, (ROLE_GRANTS_OFFICER,))
    app = get("applications", application_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "application not found")
    if app["status"] != "JIT_COMPLETE":
        fail(
            "ERR_APPLICATION_NOT_JIT_COMPLETE",
            "award issuance requires JIT_COMPLETE status",
        )
    body = get_body()
    start_date = req_dt(body, "start_date")
    if start_date < clock_now():
        fail("ERR_VALIDATION", "start_date must not be earlier than the logical clock")
    foa = get("funding_opportunities", app["foa_id"])
    institute = get("institutes", app["institute_id"])
    jit = accepted_jit_for(app["id"])
    cut = jit["budget_cut_pct"] if jit is not None else 0
    period_totals, total = build_award_budget(app, foa, institute, cut)
    years = app["requested_years"]
    terms = [TERM_STANDARD]
    if cut > 0:
        terms.append(TERM_RESTRICTED_DRAW_DOWN)
    award = new_entity()
    award.update(
        {
            "application_id": app["id"],
            "institute_id": institute["id"],
            "institution_id": app["institution_id"],
            "start_date": start_date,
            "end_date": start_date + timedelta(days=AWARD_PERIOD_DAYS * years),
            "period_total_cents": period_totals,
            "total_awarded_cents": total,
            "disbursed_cents": 0,
            "disbursed_per_period_cents": [0] * years,
            "carried_out_per_period_cents": [0] * years,
            "current_period": 1,
            "terms_and_conditions": terms,
            "originating_transfer_id": None,
            "status": "ACTIVE",
        }
    )
    STORE["awards"][award["id"]] = award
    institute["committed_cents"] += total
    touch(institute)
    app["status"] = "AWARDED"
    touch(app)
    return ok_object(award_json(award), 201)


@bp.route("/grants/awards", methods=["GET"])
def list_awards():
    auth_context()
    limit, offset = parse_pagination(request.args)
    items = list(STORE["awards"].values())
    for field in (
        "application_id",
        "institute_id",
        "institution_id",
        "originating_transfer_id",
        "status",
    ):
        if request.args.get(field) is not None:
            items = [a for a in items if a.get(field) == request.args[field]]
    page, total = sort_and_page(items, limit, offset)
    return ok_list([award_json(a) for a in page], total, limit, offset)


@bp.route("/grants/awards/<award_id>", methods=["GET"])
def get_award(award_id):
    auth_context()
    award = get("awards", award_id)
    if award is None:
        fail("ERR_AWARD_NOT_FOUND", "award not found")
    return ok_object(award_json(award))
