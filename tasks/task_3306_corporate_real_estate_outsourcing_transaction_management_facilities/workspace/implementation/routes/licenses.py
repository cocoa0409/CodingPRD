"""DataLicense routes."""
from core import auth, calc, domain
from core.db import DB, new_common, serialize, touch
from core.errors import ApiError
from core.response import ok

from routes.registry import body, lookup, paginated_ok, req, route, validate

DS_ONLY = ["DataSteward"]
LICENSE_ROLES = ["AccountExecutive", "DataSteward", "GovernanceManager"]

TIERS = ("BASIC", "COMPLETE", "ENTERPRISE")
SCOPES = ("AGGREGATE", "LINE_ITEM")


@route("POST", "/api/data-licenses", "create_data_license", DS_ONLY, 201)
def create_data_license():
    data = validate(body(), [req("account_id"), req("licensee_name"),
                             req("platform_tier_at_issue"), req("data_scope")])
    account = lookup("accounts", data.get("account_id"), "account")
    domain.lifecycle_gate(account, "create_data_license")
    if data["platform_tier_at_issue"] not in TIERS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "platform_tier_at_issue must be BASIC, COMPLETE or ENTERPRISE.")
    if data["data_scope"] not in SCOPES:
        raise ApiError("ERR_INVALID_REQUEST", "data_scope must be AGGREGATE or LINE_ITEM.")
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "licensee_name": data["licensee_name"],
        "platform_tier_at_issue": data["platform_tier_at_issue"],
        "data_scope": data["data_scope"],
        "license_state": "REQUESTED",
    })
    obj["requires_written_client_consent"] = calc.data_license_consent_required(obj, account)
    DB.insert("data_licenses", obj)
    return ok(serialize(obj), 201)


@route("GET", "/api/data-licenses", "list_data_licenses", LICENSE_ROLES)
def list_data_licenses():
    rows = DB.ordered("data_licenses")
    args = __import__("flask").request.args
    if args.get("account_id"):
        rows = [r for r in rows if r.get("account_id") == args.get("account_id")]
    return paginated_ok(rows)


@route("GET", "/api/data-licenses/<license_id>", "get_data_license", LICENSE_ROLES)
def get_data_license(license_id):
    return ok(serialize(lookup("data_licenses", license_id, "data license")))


@route("POST", "/api/data-licenses/<license_id>/grant", "grant_data_license", DS_ONLY)
def grant_data_license(license_id):
    license_row = lookup("data_licenses", license_id, "data license")
    account = lookup("accounts", license_row.get("account_id"), "account")
    if license_row.get("license_state") != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED licence may be granted.")
    if account.get("client_data_rights") == "BROKER_OWNED":
        raise ApiError("ERR_INVALID_STATE",
                       "A BROKER_OWNED account's data cannot be licensed.")
    domain.consent_gate(account["id"])
    data = body()
    consent = data.get("client_consent_confirmed", False)
    if consent is None:
        consent = False
    license_row["requires_written_client_consent"] = calc.data_license_consent_required(
        license_row, account)
    if license_row["requires_written_client_consent"] and not consent:
        raise ApiError("ERR_CONSENT_REQUIRED",
                       "Written client consent must be recorded before granting.")
    license_row["license_state"] = "GRANTED"
    if consent:
        license_row["client_consent_confirmed"] = True
    touch(license_row)
    return ok(serialize(license_row))


@route("POST", "/api/data-licenses/<license_id>/reject", "reject_data_license", DS_ONLY)
def reject_data_license(license_id):
    license_row = lookup("data_licenses", license_id, "data license")
    if license_row.get("license_state") != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED licence may be rejected.")
    license_row["license_state"] = "REJECTED"
    touch(license_row)
    return ok(serialize(license_row))