"""Consultants and skill assertions (PRD 3.2)."""
from decimal import Decimal

from flask import Blueprint

import serial
from derive import assertion_status, availability
from envelope import collection, obj
from errors import bad_request, fail
from ops import need, open_new_spell, settle
from reqctx import (
    GEOGRAPHIES,
    LEVELS,
    begin,
    body,
    filter_enum,
    filter_value,
    opt_bool,
    opt_date,
    opt_dec,
    opt_id,
    opt_industry_experience,
    opt_int,
    opt_str,
    pagination,
    present,
    req_dec,
    req_enum,
    req_id,
    req_int,
    req_str,
    window,
)
from store import bump, db

bp = Blueprint("people", __name__)

CONSULTANT_READ_ROLES = ("ResourceManager", "PracticePartner", "FinanceController", "SalesLead")
ASSERTION_READ_ROLES = CONSULTANT_READ_ROLES + ("Consultant",)
AVAILABILITY = ("BENCH", "ASSIGNED", "RESKILLING", "INTERNAL_PROJECT", "SEPARATED")


def _geography_coherent(consultant_geo, group):
    if consultant_geo != group["geography_code"]:
        fail(
            "ERR_GEOGRAPHY_MISMATCH",
            "The consultant's home geography differs from their practice group's geography.",
        )


# ------------------------------------------------------------------ consultants
@bp.post("/consultants")
def hire_consultant():
    begin("ResourceManager")
    payload = body(
        allowed=(
            "full_name",
            "email",
            "level",
            "practice_group_id",
            "home_city",
            "home_geo_code",
            "cost_rate_usd_per_hour",
            "standard_bill_rate_usd_per_hour",
            "travel_max_nights_per_week",
            "travel_willing_international",
            "development_goal_skill_id",
            "industry_experience",
        ),
        required=(
            "full_name",
            "email",
            "level",
            "practice_group_id",
            "home_city",
            "home_geo_code",
            "cost_rate_usd_per_hour",
            "standard_bill_rate_usd_per_hour",
        ),
    )
    full_name = req_str(payload, "full_name", 1, 120)
    email = req_str(payload, "email", 1, 255)
    if "@" not in email:
        bad_request("Field 'email' must contain an at-sign.")
    level = req_enum(payload, "level", LEVELS)
    group_id = req_id(payload, "practice_group_id")
    home_city = req_str(payload, "home_city", 1, 80)
    home_geo = req_enum(payload, "home_geo_code", GEOGRAPHIES)
    cost_rate = req_dec(payload, "cost_rate_usd_per_hour", Decimal("0.01"), Decimal("2000.00"))
    bill_rate = req_dec(payload, "standard_bill_rate_usd_per_hour", Decimal("0.01"), Decimal("5000.00"))
    travel_max = opt_int(payload, "travel_max_nights_per_week", 0, 5, 3)
    travel_intl = opt_bool(payload, "travel_willing_international", False)
    goal_skill_id = opt_id(payload, "development_goal_skill_id")
    industries = opt_industry_experience(payload, default=[]) or []
    group = need("practice_groups", group_id)
    if goal_skill_id is not None:
        need("skills", goal_skill_id)
    for other in db.all("consultants"):
        if other["email"] == email:
            fail("ERR_UNIQUENESS_CONFLICT", "Another consultant already carries that email.")
    _geography_coherent(home_geo, group)
    row = db.new_row("consultants")
    row.update(
        {
            "full_name": full_name,
            "email": email,
            "level": level,
            "practice_group_id": group_id,
            "home_city": home_city,
            "home_geo_code": home_geo,
            "cost_rate_usd_per_hour": cost_rate,
            "standard_bill_rate_usd_per_hour": bill_rate,
            "travel_max_nights_per_week": travel_max,
            "travel_willing_international": travel_intl,
            "development_goal_skill_id": goal_skill_id,
            "industry_experience": industries,
            "separated_on": None,
        }
    )
    db.insert("consultants", row)
    open_new_spell(row)
    settle()
    return obj(serial.consultant(row), 201)


@bp.get("/consultants")
def list_consultants():
    begin(*CONSULTANT_READ_ROLES)
    limit, offset = pagination()
    group_id = filter_value("practice_group_id")
    goal_skill_id = filter_value("development_goal_skill_id")
    status = filter_enum("availability_status", AVAILABILITY)
    level = filter_enum("level", LEVELS)
    geography = filter_enum("home_geo_code", GEOGRAPHIES)
    rows = db.all("consultants")
    if group_id is not None:
        rows = [r for r in rows if r["practice_group_id"] == group_id]
    if goal_skill_id is not None:
        rows = [r for r in rows if r.get("development_goal_skill_id") == goal_skill_id]
    if level is not None:
        rows = [r for r in rows if r["level"] == level]
    if geography is not None:
        rows = [r for r in rows if r["home_geo_code"] == geography]
    if status is not None:
        rows = [r for r in rows if availability(r) == status]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/consultants/<consultant_id>")
def read_consultant(consultant_id):
    ctx = begin(*ASSERTION_READ_ROLES)
    consultant = need("consultants", consultant_id)
    if ctx.is_consultant and ctx.user_id != consultant["id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "A consultant may read only their own record.")
    return obj(serial.consultant(consultant))


@bp.patch("/consultants/<consultant_id>")
def update_consultant(consultant_id):
    begin("ResourceManager")
    consultant = need("consultants", consultant_id)
    payload = body(
        allowed=(
            "cost_rate_usd_per_hour",
            "standard_bill_rate_usd_per_hour",
            "travel_max_nights_per_week",
            "travel_willing_international",
            "development_goal_skill_id",
            "industry_experience",
            "home_city",
            "home_geo_code",
        )
    )
    cost_rate = opt_dec(payload, "cost_rate_usd_per_hour", Decimal("0.01"), Decimal("2000.00"))
    bill_rate = opt_dec(payload, "standard_bill_rate_usd_per_hour", Decimal("0.01"), Decimal("5000.00"))
    travel_max = opt_int(payload, "travel_max_nights_per_week", 0, 5)
    travel_intl = opt_bool(payload, "travel_willing_international")
    goal_supplied = "development_goal_skill_id" in payload
    goal_skill_id = opt_id(payload, "development_goal_skill_id")
    industries = opt_industry_experience(payload)
    home_city = opt_str(payload, "home_city", 1, 80)
    home_geo = None
    if present(payload, "home_geo_code"):
        home_geo = req_enum(payload, "home_geo_code", GEOGRAPHIES)
    if goal_skill_id is not None:
        need("skills", goal_skill_id)
    if home_geo is not None:
        _geography_coherent(home_geo, need("practice_groups", consultant["practice_group_id"]))
    if cost_rate is not None:
        consultant["cost_rate_usd_per_hour"] = cost_rate
    if bill_rate is not None:
        consultant["standard_bill_rate_usd_per_hour"] = bill_rate
    if travel_max is not None:
        consultant["travel_max_nights_per_week"] = travel_max
    if travel_intl is not None:
        consultant["travel_willing_international"] = travel_intl
    if goal_supplied:
        consultant["development_goal_skill_id"] = goal_skill_id
    if industries is not None:
        consultant["industry_experience"] = industries
    if home_city is not None:
        consultant["home_city"] = home_city
    if home_geo is not None:
        consultant["home_geo_code"] = home_geo
    bump(consultant)
    settle()
    return obj(serial.consultant(consultant))


# ------------------------------------------------------------- skill assertions
def _guard_expiry(code, expires):
    if expires is not None and code is None:
        bad_request("Field 'certification_expires_on' requires a 'certification_code'.")


@bp.post("/skill-assertions")
def create_skill_assertion():
    ctx = begin("ResourceManager", "Consultant")
    payload = body(
        allowed=(
            "consultant_id",
            "skill_id",
            "proficiency_level",
            "certification_code",
            "certification_expires_on",
            "last_used_on",
        ),
        required=("consultant_id", "skill_id", "proficiency_level"),
    )
    consultant_id = req_id(payload, "consultant_id")
    skill_id = req_id(payload, "skill_id")
    level = req_int(payload, "proficiency_level", 1, 5)
    code = opt_str(payload, "certification_code", 1, 40)
    expires = opt_date(payload, "certification_expires_on")
    last_used = opt_date(payload, "last_used_on")
    _guard_expiry(code, expires)
    consultant = need("consultants", consultant_id)
    need("skills", skill_id)
    if ctx.is_consultant and ctx.user_id != consultant_id:
        fail("ERR_NOT_RESOURCE_OWNER", "A consultant may assert only against their own record.")
    if availability(consultant) == "SEPARATED":
        fail("ERR_CONSULTANT_SEPARATED", "That consultant has been separated.")
    for other in db.all("skill_assertions"):
        if other["consultant_id"] == consultant_id and other["skill_id"] == skill_id:
            fail("ERR_UNIQUENESS_CONFLICT", "That consultant already asserts this skill.")
    row = db.new_row("skill_assertions")
    row.update(
        {
            "consultant_id": consultant_id,
            "skill_id": skill_id,
            "proficiency_level": level,
            "certification_code": code,
            "certification_expires_on": expires,
            "last_used_on": last_used,
        }
    )
    db.insert("skill_assertions", row)
    return obj(serial.skill_assertion(row), 201)


@bp.get("/skill-assertions")
def list_skill_assertions():
    begin(*ASSERTION_READ_ROLES)
    limit, offset = pagination()
    consultant_id = filter_value("consultant_id")
    skill_id = filter_value("skill_id")
    status = filter_enum("assertion_status", ("ACTIVE", "EXPIRED"))
    rows = db.all("skill_assertions")
    if consultant_id is not None:
        rows = [r for r in rows if r["consultant_id"] == consultant_id]
    if skill_id is not None:
        rows = [r for r in rows if r["skill_id"] == skill_id]
    if status is not None:
        rows = [r for r in rows if assertion_status(r) == status]
    page, total = window(rows, limit, offset)
    return collection(serial.render_all(page), limit, offset, total)


@bp.get("/skill-assertions/<assertion_id>")
def read_skill_assertion(assertion_id):
    begin(*ASSERTION_READ_ROLES)
    return obj(serial.skill_assertion(need("skill_assertions", assertion_id)))


@bp.patch("/skill-assertions/<assertion_id>")
def update_skill_assertion(assertion_id):
    ctx = begin("ResourceManager", "Consultant")
    assertion = need("skill_assertions", assertion_id)
    payload = body(
        allowed=("proficiency_level", "certification_code", "certification_expires_on", "last_used_on")
    )
    level = opt_int(payload, "proficiency_level", 1, 5)
    code_supplied = "certification_code" in payload
    code = opt_str(payload, "certification_code", 1, 40)
    expires_supplied = "certification_expires_on" in payload
    expires = opt_date(payload, "certification_expires_on")
    last_used = opt_date(payload, "last_used_on")
    merged_code = code if code_supplied else assertion.get("certification_code")
    merged_expires = expires if expires_supplied else assertion.get("certification_expires_on")
    _guard_expiry(merged_code, merged_expires)
    if ctx.is_consultant and ctx.user_id != assertion["consultant_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "A consultant may revise only their own assertions.")
    if level is not None:
        assertion["proficiency_level"] = level
    if code_supplied:
        assertion["certification_code"] = code
    if expires_supplied:
        assertion["certification_expires_on"] = expires
    if last_used is not None:
        assertion["last_used_on"] = last_used
    bump(assertion)
    return obj(serial.skill_assertion(assertion))
