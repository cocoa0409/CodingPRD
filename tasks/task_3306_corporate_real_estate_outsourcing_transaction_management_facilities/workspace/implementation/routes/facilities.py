"""Facilities vendors and sites."""
from core import auth, calc, domain
from core.db import DB, dec, new_common, parse_dt, serialize, touch
from core.errors import ApiError
from core.response import ok

from routes.registry import body, lookup, paginated_ok, req, route, validate

SERVICE_LINES = ("JANITORIAL", "SECURITY", "HVAC", "LANDSCAPING")
DELIVERY_MODELS = ("SELF_PERFORM", "SUBCONTRACTED")
SOURCING_PROGRAMS = ("DIVERSITY", "LOCAL", "NATIONAL")
FM_ONLY = ["FacilitiesManager"]
FM_ROLES = ["AccountExecutive", "FacilitiesManager", "GovernanceManager"]
SITE_ROLES = ["AccountExecutive", "FacilitiesManager", "OccupancyPlanner",
              "GovernanceManager"]


def _new_vendor(account, data):
    reduction = data.get("sqft_reduction", 0)
    if reduction is None:
        reduction = 0
    if isinstance(reduction, bool) or not isinstance(reduction, (int, float)) or reduction < 0:
        raise ApiError("ERR_INVALID_REQUEST", "sqft_reduction may not be negative.")
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "vendor_name": data["vendor_name"],
        "service_line": data["service_line"],
        "delivery_model": data["delivery_model"],
        "sourcing_program": data["sourcing_program"],
        "service_rate_cents_per_sqft": dec(data["service_rate_cents_per_sqft"]),
        "sqft_reduction": reduction,
        "consolidation_window_start": parse_dt(data.get("consolidation_window_start")),
        "consolidation_window_end": parse_dt(data.get("consolidation_window_end")),
        "vendor_state": "SOURCING",
    })
    obj["kpi_track"] = calc.level_for_vendor(obj)
    DB.insert("facilities_vendors", obj)
    return obj


@route("POST", "/api/facilities-vendors", "create_facilities_vendor", FM_ONLY, 201)
def create_facilities_vendor():
    data = validate(body(), [req("account_id"), req("vendor_name"), req("service_line"),
                             req("delivery_model"), req("sourcing_program"),
                             req("service_rate_cents_per_sqft")])
    account = lookup("accounts", data.get("account_id"), "account")
    domain.lifecycle_gate(account, "create_facilities_vendor")
    if data["service_line"] not in SERVICE_LINES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "service_line must be one of %s." % ", ".join(SERVICE_LINES))
    if data["delivery_model"] not in DELIVERY_MODELS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "delivery_model must be SELF_PERFORM or SUBCONTRACTED.")
    if data["sourcing_program"] not in SOURCING_PROGRAMS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "sourcing_program must be one of %s." % ", ".join(SOURCING_PROGRAMS))
    rate = dec(data["service_rate_cents_per_sqft"])
    if rate <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "service_rate_cents_per_sqft must be strictly greater than zero.")
    for existing in DB.children("facilities_vendors", account["id"]):
        if (existing.get("vendor_name") == data["vendor_name"]
                and existing.get("service_line") == data["service_line"]):
            raise ApiError("ERR_INVALID_REQUEST",
                           "vendor_name is unique per account and service line.")
    obj = _new_vendor(account, data)
    return ok(serialize(obj), 201)


@route("GET", "/api/facilities-vendors", "list_facilities_vendors", FM_ROLES)
def list_facilities_vendors():
    rows = DB.ordered("facilities_vendors")
    args = __import__("flask").request.args
    if args.get("account_id"):
        rows = [r for r in rows if r.get("account_id") == args.get("account_id")]
    if args.get("service_line"):
        rows = [r for r in rows if r.get("service_line") == args.get("service_line")]
    return paginated_ok(rows)


@route("GET", "/api/facilities-vendors/<vendor_id>", "get_facilities_vendor", FM_ROLES)
def get_facilities_vendor(vendor_id):
    return ok(serialize(lookup("facilities_vendors", vendor_id, "facilities vendor")))


@route("POST", "/api/facilities-vendors/<vendor_id>/activate",
       "activate_facilities_vendor", FM_ONLY)
def activate_facilities_vendor(vendor_id):
    obj = lookup("facilities_vendors", vendor_id, "facilities vendor")
    account = lookup("accounts", obj.get("account_id"), "account")
    if obj.get("vendor_state") != "SOURCING":
        raise ApiError("ERR_INVALID_STATE", "Only a SOURCING vendor may be activated.")
    if account.get("lifecycle_state") not in ("ACTIVE", "OFFBOARDING"):
        raise ApiError("ERR_INVALID_STATE",
                       "Activation requires an ACTIVE or OFFBOARDING account.")
    domain.lifecycle_gate(account, "activate_facilities_vendor")
    domain.consent_gate(account["id"])
    obj["vendor_state"] = "ACTIVE"
    domain.recompute_vendor_track(obj)
    touch(obj)
    return ok(serialize(obj))


@route("POST", "/api/facilities-vendors/<vendor_id>/suspend",
       "suspend_facilities_vendor", FM_ONLY)
def suspend_facilities_vendor(vendor_id):
    obj = lookup("facilities_vendors", vendor_id, "facilities vendor")
    account = lookup("accounts", obj.get("account_id"), "account")
    if obj.get("vendor_state") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE vendor may be suspended.")
    if account.get("governance_posture") not in ("ON_WATCH", "RESTRICTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Suspension requires an ON_WATCH or RESTRICTED account posture.")
    obj["vendor_state"] = "SUSPENDED"
    touch(obj)
    return ok(serialize(obj))


@route("POST", "/api/facilities-vendors/<vendor_id>/reinstate",
       "reinstate_facilities_vendor", FM_ONLY)
def reinstate_facilities_vendor(vendor_id):
    obj = lookup("facilities_vendors", vendor_id, "facilities vendor")
    account = lookup("accounts", obj.get("account_id"), "account")
    if obj.get("vendor_state") != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUSPENDED vendor may be reinstated.")
    if account.get("governance_posture") != "NORMAL":
        raise ApiError("ERR_INVALID_STATE",
                       "Reinstatement requires a NORMAL account posture.")
    obj["vendor_state"] = "ACTIVE"
    domain.recompute_vendor_track(obj)
    touch(obj)
    return ok(serialize(obj))


@route("POST", "/api/facilities-vendors/<vendor_id>/terminate",
       "terminate_facilities_vendor", FM_ONLY)
def terminate_facilities_vendor(vendor_id):
    obj = lookup("facilities_vendors", vendor_id, "facilities vendor")
    if obj.get("vendor_state") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE vendor may be terminated.")
    obj["vendor_state"] = "TERMINATED"
    touch(obj)
    for site in DB.children("facility_sites", obj["account_id"]):
        if site.get("vendor_id") == obj["id"] and site.get("vacancy_state") == "OCCUPIED":
            site["vacancy_state"] = "DISPOSED"
            touch(site)
            for lic in DB.children("data_licenses", obj["account_id"]):
                if lic.get("data_scope") == "LINE_ITEM" and lic.get("license_state") == "GRANTED":
                    lic["license_state"] = "REVOKED"
                    touch(lic)
    return ok(serialize(obj))


def _remaining_leasable(account):
    used = 0
    for site in DB.children("facility_sites", account["id"]):
        used += int(site.get("sqft") or 0)
    return int(account.get("portfolio_sqft") or 0) - used


@route("POST", "/api/facility-sites", "create_facility_site", FM_ONLY, 201)
def create_facility_site():
    data = validate(body(), [req("account_id"), req("vendor_id"), req("site_name"),
                             req("sqft")])
    account = lookup("accounts", data.get("account_id"), "account")
    vendor = lookup("facilities_vendors", data.get("vendor_id"), "facilities vendor")
    domain.lifecycle_gate(account, "create_facility_site")
    if vendor.get("account_id") != account["id"]:
        raise ApiError("ERR_RESOURCE_NOT_FOUND",
                       "The vendor does not belong to this account.")
    sqft = data["sqft"]
    if isinstance(sqft, bool) or not isinstance(sqft, int) or sqft < 1:
        raise ApiError("ERR_INVALID_REQUEST", "sqft must be at least 1.")
    reduction = data.get("sqft_reduction", 0)
    if reduction is None:
        reduction = 0
    if isinstance(reduction, bool) or not isinstance(reduction, (int, float)) or reduction < 0:
        raise ApiError("ERR_INVALID_REQUEST", "sqft_reduction may not be negative.")
    project_id = data.get("consolidation_project_id")
    if project_id is not None:
        lookup("consolidation_projects", project_id, "consolidation project")
    start = parse_dt(data.get("consolidation_window_start"))
    end = parse_dt(data.get("consolidation_window_end"))
    if sqft > _remaining_leasable(account):
        raise ApiError("ERR_SITE_EXCEEDS_PORTFOLIO",
                       "The site exceeds the account's remaining leasable area.")
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "vendor_id": vendor["id"],
        "site_name": data["site_name"],
        "sqft": sqft,
        "sqft_reduction": int(reduction),
        "consolidation_project_id": project_id,
        "consolidation_window_start": start,
        "consolidation_window_end": end,
        "vacancy_state": "OCCUPIED",
    })
    DB.insert("facility_sites", obj)
    domain.recompute_vendor_track(vendor)
    domain.recompute_fee(account)
    return ok(serialize(obj), 201)


@route("GET", "/api/facility-sites", "list_facility_sites", SITE_ROLES)
def list_facility_sites():
    rows = DB.ordered("facility_sites")
    args = __import__("flask").request.args
    for key in ("account_id", "vendor_id", "consolidation_project_id"):
        if args.get(key):
            rows = [r for r in rows if r.get(key) == args.get(key)]
    return paginated_ok(rows)


@route("GET", "/api/facility-sites/<site_id>", "get_facility_site", SITE_ROLES)
def get_facility_site(site_id):
    return ok(serialize(lookup("facility_sites", site_id, "facility site")))


@route("POST", "/api/facility-sites/<site_id>/vacate", "vacate_facility_site", FM_ONLY)
def vacate_facility_site(site_id):
    site = lookup("facility_sites", site_id, "facility site")
    if site.get("vacancy_state") != "OCCUPIED":
        raise ApiError("ERR_INVALID_STATE", "Only an OCCUPIED site may be vacated.")
    site["vacancy_state"] = "VACATED"
    touch(site)
    return ok(serialize(site))


@route("POST", "/api/facility-sites/<site_id>/consolidate",
       "consolidate_facility_site", FM_ONLY)
def consolidate_facility_site(site_id):
    site = lookup("facility_sites", site_id, "facility site")
    account = lookup("accounts", site.get("account_id"), "account")
    data = body()
    if site.get("vacancy_state") != "VACATED":
        raise ApiError("ERR_INVALID_STATE", "Only a VACATED site may be consolidated.")
    if account.get("governance_posture") not in ("NORMAL", "ON_WATCH"):
        raise ApiError("ERR_INVALID_STATE",
                       "Consolidation is blocked while the account is RESTRICTED.")
    project = DB.get("consolidation_projects", site.get("consolidation_project_id"))
    if project is None or project.get("project_state") != "APPROVED":
        raise ApiError("ERR_INVALID_STATE",
                       "The site's consolidation project must be APPROVED.")
    start = parse_dt(data.get("window_start"))
    end = parse_dt(data.get("window_end"))
    if start is None or end is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "window_start and window_end are required half-open instants.")
    if domain.consolidation_interval_conflict(account["id"], start, end, exclude_id=site["id"]):
        raise ApiError("ERR_SITE_OVERLAP",
                       "The consolidation interval overlaps a committed interval on the account.")
    site["consolidation_window_start"] = start
    site["consolidation_window_end"] = end
    site["vacancy_state"] = "CONSOLIDATING"
    touch(site)
    credit = domain.site_consolidation_credit(site)
    open_accruals = [a for a in DB.children("fee_accruals", account["id"])
                     if a.get("credit_application_state") == "OPEN"]
    if open_accruals:
        accrual = sorted(open_accruals, key=lambda a: a.get("_seq", 0))[0]
        accrual["applied_credit_cents"] = dec(accrual.get("applied_credit_cents") or 0) + credit
        touch(accrual)
    account["portfolio_leased_sqft"] = calc.portfolio_leased_sqft(account["id"])
    domain.recompute_fee(account)
    vendor = DB.get("facilities_vendors", site.get("vendor_id"))
    if vendor is not None:
        domain.recompute_vendor_track(vendor)
    return ok(serialize(site))


@route("POST", "/api/facility-sites/<site_id>/dispose", "dispose_facility_site", FM_ONLY)
def dispose_facility_site(site_id):
    site = lookup("facility_sites", site_id, "facility site")
    account = lookup("accounts", site.get("account_id"), "account")
    if site.get("vacancy_state") != "CONSOLIDATING":
        raise ApiError("ERR_INVALID_STATE", "Only a CONSOLIDATING site may be disposed.")
    if account.get("lifecycle_state") not in ("ACTIVE", "OFFBOARDING"):
        raise ApiError("ERR_INVALID_STATE",
                       "Disposal requires an ACTIVE or OFFBOARDING account.")
    site["vacancy_state"] = "DISPOSED"
    touch(site)
    account["portfolio_leased_sqft"] = calc.portfolio_leased_sqft(account["id"])
    touch(account)
    for lic in DB.children("data_licenses", account["id"]):
        if lic.get("data_scope") == "LINE_ITEM" and lic.get("license_state") == "GRANTED":
            lic["license_state"] = "REVOKED"
            touch(lic)
    vendor = DB.get("facilities_vendors", site.get("vendor_id"))
    if vendor is not None:
        domain.recompute_vendor_track(vendor)
    return ok(serialize(site))