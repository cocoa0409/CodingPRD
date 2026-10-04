"""OTILicense + embedded surety-bond ledger (PRD §3.4)."""
from flask import Blueprint

import store
from auth import require_roles, any_role
from envelope import ok_object, ok_list, paginate
from errors import (
    fail,
    ERR_CARRIER_NOT_FOUND,
    ERR_LICENSE_NOT_FOUND,
    ERR_FORBIDDEN_RESOURCE_ACCESS,
    ERR_INVALID_REQUEST,
    ERR_LICENSE_TYPE_MISMATCH,
    ERR_DUPLICATE_BOND_REF,
    ERR_BOND_COVERAGE_EXCEEDED,
    ERR_BOND_REVERSAL_EXCEEDED,
    ERR_STALE_VERSION,
)
from serialization import ser_license
from services.cascades import refresh_bond_coverage, apply_license_sufficiency
from store import touch
from util import body, req_str, req_int, req_enum, opt_str
from constants import BOND_REQUIRED_NVOCC_CENTS, BOND_REQUIRED_OFF_CENTS

bp = Blueprint("licenses", __name__)

LICENSE_TYPES = ("NVOCC", "OFF")


@bp.post("/fmc/carriers/<carrierId>/oti-licenses")
def apply_license(carrierId):
    uid, _role = require_roles("CarrierRep")
    carrier = store.carriers.get(carrierId)
    if carrier is None:
        fail(ERR_CARRIER_NOT_FOUND, "carrier organization not found: %s" % carrierId)
    if uid != carrierId:
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "a CarrierRep may apply for licenses only under its own organization")
    b = body()
    license_type = req_enum(b, "license_type", LICENSE_TYPES)
    if carrier["org_type"] != license_type:
        fail(ERR_LICENSE_TYPE_MISMATCH,
             "license_type must equal the organization's org_type (NVOCC or OFF)")
    rec = store.base_record()
    rec.update(
        organization_id=carrierId,
        license_type=license_type,
        license_status="PENDING_BOND",
        required_bond_cents=(
            BOND_REQUIRED_NVOCC_CENTS if license_type == "NVOCC"
            else BOND_REQUIRED_OFF_CENTS
        ),
        surety_bonds=[],
        total_available_coverage_cents=0,
        _suspended_contract_ids=set(),
    )
    store.licenses[rec["id"]] = rec
    return ok_object(ser_license(rec), 201)


@bp.get("/fmc/carriers/<carrierId>/oti-licenses")
def list_licenses(carrierId):
    any_role()
    if carrierId not in store.carriers:
        fail(ERR_CARRIER_NOT_FOUND, "carrier organization not found: %s" % carrierId)
    recs = [l for l in store.licenses.values() if l["organization_id"] == carrierId]
    page, limit, offset, total = paginate(recs)
    return ok_list([ser_license(l) for l in page], limit, offset, total)


@bp.post("/fmc/oti-licenses/<licenseId>/surety-bonds")
def append_bond(licenseId):
    uid, _role = require_roles("CarrierRep")
    lic = store.licenses.get(licenseId)
    if lic is None:
        fail(ERR_LICENSE_NOT_FOUND, "OTI license not found: %s" % licenseId)
    if uid != lic["organization_id"]:
        fail(ERR_FORBIDDEN_RESOURCE_ACCESS,
             "a CarrierRep may post bonds only on its own organization's licenses")
    b = body()
    bond_ref = req_str(b, "bond_ref")
    surety_name = req_str(b, "surety_name")
    coverage_cents = req_int(b, "coverage_cents", lo=1)
    if any(x["bond_ref"] == bond_ref for x in lic["surety_bonds"]):
        fail(ERR_DUPLICATE_BOND_REF,
             "bond_ref %s is already in use on this license" % bond_ref)
    lic["surety_bonds"].append({
        "bond_ref": bond_ref,
        "surety_name": surety_name,
        "coverage_cents": coverage_cents,
        "drawn_cents": 0,
        "available_cents": coverage_cents,
        "bond_status": "ACTIVE",
    })
    refresh_bond_coverage(lic)
    apply_license_sufficiency(lic)
    touch(lic)
    return ok_object(ser_license(lic), 201)


@bp.post("/fmc/oti-licenses/<licenseId>/draws")
def post_draw(licenseId):
    require_roles("EnforcementCounsel")
    lic = store.licenses.get(licenseId)
    if lic is None:
        fail(ERR_LICENSE_NOT_FOUND, "OTI license not found: %s" % licenseId)
    b = body()
    bond_ref = req_str(b, "bond_ref")
    amount_cents = req_int(b, "amount_cents")
    opt_str(b, "reason")  # free-text; recorded nowhere on the bond element
    expected_license_version = req_int(b, "expected_license_version")
    bond = next((x for x in lic["surety_bonds"] if x["bond_ref"] == bond_ref), None)
    if bond is None:
        fail(ERR_INVALID_REQUEST,
             "no bond with bond_ref %s on this license" % bond_ref)
    # Bond-ledger sufficiency (rung 13) precedes the OCC assertion (rung 16).
    if amount_cents > 0 and amount_cents > bond["available_cents"]:
        fail(ERR_BOND_COVERAGE_EXCEEDED,
             "draw amount exceeds the bond's available_cents")
    if amount_cents < 0 and -amount_cents > bond["drawn_cents"]:
        fail(ERR_BOND_REVERSAL_EXCEEDED,
             "reversal magnitude exceeds the bond's drawn_cents")
    if expected_license_version != lic["version"]:
        fail(ERR_STALE_VERSION,
             "expected_license_version does not match the license's current version")
    bond["drawn_cents"] += amount_cents
    refresh_bond_coverage(lic)
    apply_license_sufficiency(lic)
    touch(lic)
    return ok_object(ser_license(lic))
