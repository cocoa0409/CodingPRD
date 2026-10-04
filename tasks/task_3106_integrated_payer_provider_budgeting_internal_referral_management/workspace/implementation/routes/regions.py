"""Region and Member endpoints."""

from flask import Blueprint

from constants import (
    ROLE_PLATFORM_ADMIN,
    ROLE_REGIONAL_FINANCE_OFFICER,
)
from db import STORE
from domain import (
    check_member_version,
    enforce_posture_gate,
    get_member,
    get_region,
    new_record,
    perfor_m_fiscal_line_check,
    recompute_member_capitation,
    recompute_region_aggregates,
    recompute_region_providers,
    require_body_reference,
    run_posture_ladder,
    store_row,
    touch,
)
from errors import (
    ERR_CROSS_REGION_REFERENCE,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ApiError,
    raise_error,
)
from routes._common import (
    READERS,
    arg,
    filter_rows,
    list_response,
    optional_field,
    payload,
    principal,
    require_field,
    single_response,
)

bp = Blueprint("regions", __name__)

REGION_READERS = READERS


@bp.post("/regions")
def create_region():
    principal((ROLE_PLATFORM_ADMIN,))
    body = payload()
    row = new_record(
        name=require_field(body, "name"),
        state_codes=require_field(body, "state_codes"),
        posture="OPEN",
        margin_target_pct=require_field(body, "margin_target_pct"),
        capitation_index=optional_field(body, "capitation_index", 1.0),
        premium_revenue_cents=0,
        operating_margin_cents=0,
        computed_margin_cents=0,
    )
    store_row("regions", row)
    return single_response("regions", row, 201)


@bp.get("/regions")
def list_regions():
    principal(REGION_READERS)
    posture = arg("posture")
    state_code = arg("state_code")
    rows = list(STORE.regions.values())
    if posture is not None:
        rows = [r for r in rows if r.get("posture") == posture]
    if state_code is not None:
        rows = [r for r in rows
                if state_code in (r.get("state_codes") or [])]
    return list_response("regions", rows)


@bp.get("/regions/<region_id>")
def get_one_region(region_id):
    principal(REGION_READERS)
    return single_response("regions", get_region(region_id))


@bp.post("/regions/<region_id>/members")
def enroll_member(region_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    get_region(region_id)  # 404 when unknown
    body = payload()

    provider_id = optional_field(body, "attributed_provider_id")
    if provider_id is not None:
        provider = require_body_reference("providers", provider_id)
        if provider.get("region_id") != region_id:
            raise_error(ERR_CROSS_REGION_REFERENCE)

    enforce_posture_gate(region_id)
    perfor_m_fiscal_line_check(region_id)

    member_ref = require_field(body, "member_ref")
    for existing in STORE.members.values():
        if existing.get("member_ref") == member_ref:
            raise ApiError("ERR_DUPLICATE_MEMBER_REF",
                           "member_ref must be unique across all members.", 409)

    row = new_record(
        region_id=region_id,
        member_ref=member_ref,
        attributed_provider_id=provider_id,
        plan_product=require_field(body, "plan_product"),
        benefit_tier=require_field(body, "benefit_tier"),
        risk_score=require_field(body, "risk_score"),
        coverage_effective_date=require_field(body, "coverage_effective_date"),
        capitation_rate_cents=0,
        status="ACTIVE",
    )
    store_row("members", row)
    recompute_member_capitation(row)

    recompute_region_providers(region_id, bump_versions=True)
    recompute_region_aggregates(region_id, bump_version=True)
    run_posture_ladder(region_id)
    return single_response("members", row, 201)


@bp.get("/regions/<region_id>/members")
def list_region_members(region_id):
    principal(REGION_READERS)
    get_region(region_id)
    rows = [m for m in STORE.members.values() if m.get("region_id") == region_id]
    rows = filter_rows(rows, status=arg("status"),
                       plan_product=arg("plan_product"))
    return list_response("members", rows)


@bp.get("/members")
def list_members():
    principal(REGION_READERS)
    rows = list(STORE.members.values())
    rows = filter_rows(
        rows,
        region_id=arg("region_id"),
        attributed_provider_id=arg("attributed_provider_id"),
        status=arg("status"),
    )
    return list_response("members", rows)


@bp.get("/members/<member_id>")
def get_one_member(member_id):
    principal(REGION_READERS)
    return single_response("members", get_member(member_id))


@bp.post("/members/<member_id>/terminate")
def terminate_member(member_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    member = get_member(member_id)
    body = payload()
    expected = optional_field(body, "expected_member_version")
    if expected is None:
        raise_error(ERR_STALE_VERSION)

    region_id = member["region_id"]
    check_member_version(member, expected)
    enforce_posture_gate(region_id)
    if member.get("status") != "ACTIVE":
        raise_error(ERR_INVALID_STATE)

    member["status"] = "TERMINATED"
    touch(member)

    recompute_region_providers(region_id, bump_versions=True)
    recompute_region_aggregates(region_id, bump_version=True)
    run_posture_ladder(region_id)
    return single_response("members", member)


@bp.patch("/members/<member_id>")
def correct_risk_score(member_id):
    principal((ROLE_REGIONAL_FINANCE_OFFICER,))
    member = get_member(member_id)
    body = payload()
    expected = optional_field(body, "expected_member_version")
    if expected is None:
        raise_error(ERR_STALE_VERSION)
    check_member_version(member, expected)

    region_id = member["region_id"]
    enforce_posture_gate(region_id)

    member["risk_score"] = require_field(body, "risk_score")
    recompute_member_capitation(member)
    touch(member)

    recompute_region_aggregates(region_id, bump_version=True)
    run_posture_ladder(region_id)
    return single_response("members", member)