"""Registry endpoints (PRD 3.1) and the logical-clock capability (PRD 2.4)."""
from decimal import Decimal

from flask import Blueprint

import serialize
from envelope import success
from errors import ApiError
from guards import (ALL_ROLES, ROLE_HR, ROLE_OFFICER, authenticate, bad, json_body,
                    lookup, need_amount, need_bool, need_date, need_enum, need_int,
                    need_string, opt_bool, opt_enum, opt_int, opt_string)
from store import money_out, new_record, parse_datetime_str, q2, store, touch

bp = Blueprint("registry", __name__)

FUNDING_TYPES = ("FEDERAL_GRANT", "FOUNDATION_GRANT", "EXTERNAL_FELLOWSHIP",
                 "INSTITUTIONAL_FELLOWSHIP")
SALARY_FLOOR_POLICIES = ("NIH_SCALE", "INSTITUTIONAL_MIN")
BIOSAFETY_LEVELS = ("BSL1", "BSL2", "BSL3")
LAB_STATUSES = ("OPEN", "CLOSED")
VERIFY_DECISIONS = ("VERIFY", "SUSPEND")


@bp.post("/postdocs")
def register_postdoc():
    authenticate((ROLE_OFFICER,))
    body = json_body()
    full_name = need_string(body, "full_name", max_length=120)
    email = need_string(body, "email")
    if "@" not in email:
        bad("email must contain an at-sign.")
    for existing in store.postdocs.values():
        if existing["email"] == email:
            bad("email must be unique across scholar records.")
    country = need_string(body, "citizenship_country")
    if len(country) != 2 or not country.isalpha() or country != country.upper():
        bad("citizenship_country must be exactly two uppercase letters.")
    phd_award_date = need_date(body, "phd_award_date")
    requires_sponsorship = opt_bool(body, "requires_sponsorship", False)
    prior_months = opt_int(body, "prior_external_months_in_rank", 0, minimum=0, maximum=60)
    o1_flag = opt_bool(body, "o1_endorsement_on_file", False)
    j1_flag = opt_bool(body, "j1_two_year_bar_flag", False)
    restricted_flag = opt_bool(body, "restricted_party_flag", False)

    record = new_record()
    record.update({
        "full_name": full_name,
        "email": email,
        "citizenship_country": country,
        "requires_sponsorship": requires_sponsorship,
        "phd_award_date": phd_award_date,
        "prior_external_months_in_rank": prior_months,
        "o1_endorsement_on_file": o1_flag,
        "j1_two_year_bar_flag": j1_flag,
        "restricted_party_flag": restricted_flag,
        "total_months_in_rank": prior_months,
        "status": "PROSPECTIVE",
    })
    store.postdocs[record["id"]] = record
    return success(serialize.postdoc_out(record), 201)


@bp.get("/postdocs/<record_id>")
def get_postdoc(record_id):
    authenticate(ALL_ROLES)
    return success(serialize.postdoc_out(lookup("postdoc", record_id)))


@bp.post("/faculty-mentors")
def register_mentor():
    authenticate((ROLE_OFFICER,))
    body = json_body()
    full_name = need_string(body, "full_name")
    department = need_string(body, "department")
    valid_through = need_date(body, "mentor_training_valid_through")
    max_concurrent = opt_int(body, "max_concurrent_postdocs", 3, minimum=1, maximum=12)

    record = new_record()
    record.update({
        "full_name": full_name,
        "department": department,
        "mentor_training_valid_through": valid_through,
        "max_concurrent_postdocs": max_concurrent,
        "active_postdoc_count": 0,
    })
    store.mentors[record["id"]] = record
    return success(serialize.mentor_out(record), 201)


@bp.get("/faculty-mentors/<record_id>")
def get_mentor(record_id):
    authenticate(ALL_ROLES)
    return success(serialize.mentor_out(lookup("mentor", record_id)))


@bp.post("/funding-sources")
def register_funding_source():
    authenticate((ROLE_OFFICER,))
    body = json_body()
    sponsor_name = need_string(body, "sponsor_name")
    funding_type = need_enum(body, "funding_type", FUNDING_TYPES)
    policy = need_enum(body, "salary_floor_policy", SALARY_FLOOR_POLICIES)
    award_start = need_date(body, "award_start_date")
    award_end = need_date(body, "award_end_date")
    budget = need_amount(body, "annual_budget_usd", positive=True)
    requires_mentoring_plan = opt_bool(body, "requires_mentoring_plan", False)
    requires_idp = opt_bool(body, "requires_idp", False)

    record = new_record()
    record.update({
        "sponsor_name": sponsor_name,
        "funding_type": funding_type,
        "salary_floor_policy": policy,
        "award_start_date": award_start,
        "award_end_date": award_end,
        "annual_budget_usd": q2(budget),
        "requires_mentoring_plan": requires_mentoring_plan,
        "requires_idp": requires_idp,
        "verification_status": "UNVERIFIED",
        "verified_at": None,
        "verified_by_user_id": None,
        "encumbered_usd": Decimal("0.00"),
        "available_balance_usd": q2(budget),
    })
    store.funding_sources[record["id"]] = record
    return success(serialize.funding_source_out(record), 201)


@bp.get("/funding-sources/<record_id>")
def get_funding_source(record_id):
    authenticate(ALL_ROLES)
    return success(serialize.funding_source_out(lookup("funding_source", record_id)))


@bp.post("/funding-sources/<record_id>/verification")
def verify_funding_source(record_id):
    user_id, _ = authenticate((ROLE_HR,))
    funding_source = lookup("funding_source", record_id)
    body = json_body()
    decision = need_enum(body, "decision", VERIFY_DECISIONS)
    status = funding_source["verification_status"]

    if decision == "VERIFY":
        if status not in ("UNVERIFIED", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "An award in %s cannot be verified." % status)
        if funding_source["award_end_date"] < store.today():
            raise ApiError("ERR_AWARD_EXPIRED",
                           "The award ended before the current logical date.")
        funding_source["verification_status"] = "VERIFIED"
        funding_source["verified_at"] = store.now()
        funding_source["verified_by_user_id"] = user_id
    else:
        if status != "VERIFIED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "An award in %s cannot be suspended." % status)
        funding_source["verification_status"] = "SUSPENDED"
    touch(funding_source)
    return success(serialize.funding_source_out(funding_source))


@bp.post("/laboratories")
def register_laboratory():
    authenticate((ROLE_OFFICER,))
    body = json_body()
    name = need_string(body, "name")
    biosafety_level = need_enum(body, "biosafety_level", BIOSAFETY_LEVELS)
    bench_capacity = need_int(body, "bench_capacity", minimum=1, maximum=40)
    buffer_days = opt_int(body, "decontamination_buffer_days", 0, minimum=0, maximum=30)
    status = opt_enum(body, "status", LAB_STATUSES, "OPEN")

    record = new_record()
    record.update({
        "name": name,
        "biosafety_level": biosafety_level,
        "bench_capacity": bench_capacity,
        "decontamination_buffer_days": buffer_days,
        "status": status,
    })
    store.laboratories[record["id"]] = record
    return success(serialize.laboratory_out(record), 201)


@bp.get("/laboratories/<record_id>")
def get_laboratory(record_id):
    authenticate(ALL_ROLES)
    return success(serialize.laboratory_out(lookup("laboratory", record_id)))


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(ALL_ROLES)
    body = json_body()
    raw = body.get("current_utc")
    if raw is None or not isinstance(raw, str):
        bad("current_utc is required and must be an ISO 8601 UTC instant.")
    parsed = parse_datetime_str(raw)
    if parsed is None:
        bad("current_utc must be an ISO 8601 UTC instant.")
    store.clock = parsed
    from store import iso_ts
    return success({"current_utc": iso_ts(store.clock)})
