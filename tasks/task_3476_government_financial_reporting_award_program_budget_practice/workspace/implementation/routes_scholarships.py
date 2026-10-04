"""Small-government scholarship / technical-assistance funds (PRD 3.9).

Fund remaining_cents and status are derived (pool minus GRANTED grants);
allocate is OCC-guarded on the fund version (412) and rescind is the
compensating action.
"""

from clock import clock
from domain import (
    PURPOSE_FOR_PROGRAM_LABEL,
    fund_remaining_cents,
    grant_amount,
)
from envelope import ok
from errors import api_error
from auth import authenticate, authorize
from listing import list_response
from serialize import scholarship_application, scholarship_fund
from store import store, new_id, touch
from validate import (
    ALLOCATION_POLICIES,
    PROGRAM_LABELS,
    PURPOSES,
    get_body,
    opt_enum,
    pagination,
    query_filter,
    req_enum,
    req_int,
    req_pos_int,
    req_str,
)


def _now():
    return clock.now_iso()


def create_fund():
    uid, role = authenticate()
    body = get_body()
    fiscal_year = req_int(body, "fiscal_year")
    program_label = req_enum(body, "program_label", PROGRAM_LABELS)
    pool_total_cents = req_pos_int(body, "pool_total_cents")
    per_applicant_cap_cents = req_pos_int(body, "per_applicant_cap_cents")
    allocation_policy = opt_enum(body, "allocation_policy", ALLOCATION_POLICIES, "FLAT_CAP")
    authorize(role, ["PlatformAdmin"])
    now = _now()
    f = {
        "id": new_id(),
        "fiscal_year": fiscal_year,
        "program_label": program_label,
        "pool_total_cents": pool_total_cents,
        "per_applicant_cap_cents": per_applicant_cap_cents,
        "allocation_policy": allocation_policy,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.scholarship_funds[f["id"]] = f
    return ok(scholarship_fund(f), 201)


def get_fund(fund_id):
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "AwardsDirector"])
    f = store.scholarship_funds.get(fund_id)
    if f is None:
        raise api_error("ERR_FUND_NOT_FOUND", "scholarship fund not found")
    return ok(scholarship_fund(f))


def create_application():
    uid, role = authenticate()
    body = get_body()
    fund_id = req_str(body, "fund_id")
    government_id = req_str(body, "government_id")
    purpose = req_enum(body, "purpose", PURPOSES)
    requested_cents = req_pos_int(body, "requested_cents")
    authorize(role, ["GovernmentContact"])
    # body FKs in canonical order (PRD 2.7): government_id before fund_id
    government = store.governments.get(government_id)
    if government is None:
        raise api_error("ERR_GOVERNMENT_NOT_FOUND", "government not found")
    fund = store.scholarship_funds.get(fund_id)
    if fund is None:
        raise api_error("ERR_FUND_NOT_FOUND", "scholarship fund not found")
    # ownership (5)
    if government_id != uid:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "government_id must equal the caller's identity")
    # structural (10): SMALL government, then purpose-to-program match
    if government["population_band"] != "SMALL":
        raise api_error("ERR_GOVERNMENT_NOT_SMALL", "the government is not in the SMALL population band")
    if purpose != PURPOSE_FOR_PROGRAM_LABEL[fund["program_label"]]:
        raise api_error(
            "ERR_PURPOSE_PROGRAM_MISMATCH",
            "purpose does not match the fund's program_label",
        )
    now = _now()
    a = {
        "id": new_id(),
        "fund_id": fund_id,
        "government_id": government_id,
        "purpose": purpose,
        "requested_cents": requested_cents,
        "granted_cents": 0,
        "status": "PENDING",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.scholarship_applications[a["id"]] = a
    return ok(scholarship_application(a), 201)


def allocate_application(application_id):
    uid, role = authenticate()
    body = get_body()
    expected_fund_version = req_int(body, "expected_fund_version")
    authorize(role, ["AwardsDirector"])
    a = store.scholarship_applications.get(application_id)
    if a is None:
        raise api_error("ERR_APPLICATION_NOT_FOUND", "scholarship application not found")
    fund = store.scholarship_funds[a["fund_id"]]
    # state gates (6): application PENDING, then OCC on the fund version
    if a["status"] != "PENDING":
        raise api_error("ERR_APPLICATION_STATE_INVALID", "allocate requires status PENDING")
    if expected_fund_version != fund["version"]:
        raise api_error(
            "ERR_STALE_FUND_VERSION",
            "expected_fund_version does not match the fund's current version",
        )
    # fiscal (11)
    if fund_remaining_cents(fund) <= 0:
        raise api_error("ERR_POOL_EXHAUSTED", "the fund holds no unallocated balance")
    amount = grant_amount(fund, a)
    now = _now()
    a["granted_cents"] = amount
    a["status"] = "GRANTED"
    touch(a, now)
    touch(fund, now)  # remaining_cents / derived status move with the grant
    return ok(scholarship_application(a))


def rescind_application(application_id):
    uid, role = authenticate()
    get_body()
    authorize(role, ["AwardsDirector"])
    a = store.scholarship_applications.get(application_id)
    if a is None:
        raise api_error("ERR_APPLICATION_NOT_FOUND", "scholarship application not found")
    if a["status"] != "GRANTED":
        raise api_error("ERR_APPLICATION_STATE_INVALID", "rescind requires status GRANTED")
    fund = store.scholarship_funds[a["fund_id"]]
    now = _now()
    # granted_cents is retained for audit; the derived remaining/status recredit
    a["status"] = "RESCINDED"
    touch(a, now)
    touch(fund, now)
    return ok(scholarship_application(a))


def get_application(application_id):
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "AwardsDirector", "GovernmentContact"])
    a = store.scholarship_applications.get(application_id)
    if a is None:
        raise api_error("ERR_APPLICATION_NOT_FOUND", "scholarship application not found")
    if role == "GovernmentContact" and a["government_id"] != uid:
        raise api_error("ERR_NOT_RESOURCE_OWNER", "GovernmentContact sees only own applications")
    return ok(scholarship_application(a))


def list_applications():
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "AwardsDirector", "GovernmentContact"])
    limit, offset = pagination()
    rows = list(store.scholarship_applications.values())
    if role == "GovernmentContact":
        rows = [a for a in rows if a["government_id"] == uid]
    fund_id = query_filter("fund_id")
    if fund_id is not None:
        rows = [a for a in rows if a["fund_id"] == fund_id]
    government_id = query_filter("government_id")
    if government_id is not None:
        rows = [a for a in rows if a["government_id"] == government_id]
    status = query_filter("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return list_response(rows, scholarship_application, limit, offset)


def register(app):
    app.add_url_rule("/gfoa/scholarship-funds", "create_fund", create_fund, methods=["POST"])
    app.add_url_rule("/gfoa/scholarship-funds/<fund_id>", "get_fund", get_fund, methods=["GET"])
    app.add_url_rule("/gfoa/scholarship-applications", "create_application", create_application, methods=["POST"])
    app.add_url_rule("/gfoa/scholarship-applications", "list_applications", list_applications, methods=["GET"])
    app.add_url_rule("/gfoa/scholarship-applications/<application_id>", "get_application", get_application, methods=["GET"])
    app.add_url_rule("/gfoa/scholarship-applications/<application_id>/allocate", "allocate_application", allocate_application, methods=["POST"])
    app.add_url_rule("/gfoa/scholarship-applications/<application_id>/rescind", "rescind_application", rescind_application, methods=["POST"])
