"""Organization-scoped list endpoints plus license request/read."""

from flask import Blueprint

import auth
import calc
import listing
import response
import store
import svc
import webutil

bp = Blueprint("org_lists", __name__)

READ_ALL = (
    auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER,
    auth.ROLE_ORGANIZATION_USER, auth.ROLE_DATA_CONSUMER,
)


@bp.route("/nonprofits/organizations/<org_id>/seals", methods=["GET"])
def list_seals(org_id):
    acting = auth.actor()
    auth.require_role(acting, READ_ALL)
    svc.get_organization(org_id)
    rows = store.where("seals", organization_id=org_id)
    return listing.list_endpoint(rows, svc.ser_seal, (("status", "status", "str"),))


@bp.route("/nonprofits/organizations/<org_id>/correction-requests", methods=["GET"])
def list_org_corrections(org_id):
    acting = auth.actor()
    auth.require_role(acting, (
        auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER, auth.ROLE_ORGANIZATION_USER,
    ))
    svc.get_organization(org_id)
    rows = store.where("correction_requests", organization_id=org_id)
    return listing.list_endpoint(rows, svc.ser_correction, (("status", "status", "str"),))


@bp.route("/nonprofits/organizations/<org_id>/identity-cases", methods=["GET"])
def list_identity_cases(org_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER))
    svc.get_organization(org_id)
    rows = [
        case for case in store.rows("identity_cases")
        if case.get("subject_organization_id") == org_id
        or case.get("surviving_organization_id") == org_id
    ]
    spec = (("status", "status", "str"), ("case_type", "case_type", "str"))
    return listing.list_endpoint(rows, svc.ser_identity_case, spec)


@bp.route("/nonprofits/organizations/<org_id>/filings", methods=["GET"])
def list_filings(org_id):
    acting = auth.actor()
    auth.require_role(acting, READ_ALL)
    svc.get_organization(org_id)
    rows = store.where("filings", organization_id=org_id)
    spec = (
        ("tax_year", "tax_year", "int"),
        ("form_type", "form_type", "str"),
        ("status", "status", "str"),
    )
    return listing.list_endpoint(rows, svc.ser_filing, spec)


@bp.route("/nonprofits/organizations/<org_id>/grants", methods=["GET"])
def list_org_grants(org_id):
    acting = auth.actor()
    auth.require_role(acting, READ_ALL)
    svc.get_organization(org_id)
    rows = svc.org_grants(store.find("organizations", org_id))
    spec = (
        ("funder_organization_id", "funder_organization_id", "str"),
        ("recipient_organization_id", "recipient_organization_id", "str"),
        ("fiscal_year", "fiscal_year", "int"),
        ("recipient_match_status", "recipient_match_status", "str"),
        ("status", "status", "str"),
    )
    return listing.list_endpoint(rows, svc.ser_grant, spec)


# --- DataLicense ---------------------------------------------------------

@bp.route("/nonprofits/organizations/<org_id>/licenses", methods=["POST"])
def create_license(org_id):
    acting = auth.actor()
    auth.require_role(acting, (auth.ROLE_DATA_CONSUMER, auth.ROLE_PLATFORM_ADMIN))
    org = svc.get_organization(org_id)
    auth.require_owner(acting, org_id, "licenses")

    data = webutil.body()
    webutil.reject_unknown(data, (
        "tier", "permitted_use", "term_start", "term_end",
        "projected_annual_records", "auto_renew",
    ))
    tier = webutil.as_enum(data, "tier", calc.TIERS)
    permitted_use = webutil.as_enum(data, "permitted_use", calc.PERMITTED_USES)
    term_start = webutil.as_datetime(data, "term_start")
    term_end = webutil.as_datetime(data, "term_end")
    projected_annual_records = webutil.as_int(
        data, "projected_annual_records", required=False, default=0
    )
    auto_renew = webutil.as_bool(data, "auto_renew", default=False)

    included_records = calc.TIER_INCLUDED_RECORDS[tier]
    license_row = store.new_row(
        licensee_organization_id=org_id,
        tier=tier,
        permitted_use=permitted_use,
        term_start=term_start,
        term_end=term_end,
        status="DRAFT",
        projected_annual_records=projected_annual_records,
        included_records=included_records,
        records_accessed=0,
        # PRD 3.9: the license opens with overage_records 0 and overage_flag
        # false; the overage is a read-time figure derived from records_accessed.
        overage_records=0,
        projected_annual_fee_cents=calc.license_fee_cents(tier, projected_annual_records),
        final_annual_fee_cents=calc.license_fee_cents(tier, 0),
        overage_flag=False,
        auto_renew=auto_renew,
    )
    store.insert("licenses", license_row)
    return response.ok(svc.ser_license(license_row), status=201)


@bp.route("/nonprofits/organizations/<org_id>/licenses", methods=["GET"])
def list_licenses(org_id):
    acting = auth.actor()
    auth.require_role(acting, (
        auth.ROLE_PLATFORM_ADMIN, auth.ROLE_PLATFORM_VERIFIER, auth.ROLE_DATA_CONSUMER,
    ))
    svc.get_organization(org_id)
    rows = store.where("licenses", licensee_organization_id=org_id)
    spec = (("status", "status", "str"), ("tier", "tier", "str"))
    return listing.list_endpoint(rows, svc.ser_license, spec)
