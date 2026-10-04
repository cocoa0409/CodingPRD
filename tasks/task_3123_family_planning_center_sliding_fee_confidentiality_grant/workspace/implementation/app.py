"""Family Planning Center API — Flask application.

All 69 endpoints from PRD §4. Validation pipeline order (PRD §2.10):
  1 auth headers -> 2 RBAC -> 3 existence -> 4 affiliate-active ->
  4.5 privacy-hold gate -> 5 state -> 5.5 current assessment -> 6 suppression
  gate -> 7 scope -> 8 telehealth licensure -> 9 temporal -> 10 hold overlap ->
  11 reservation safety -> 12 fiscal caps -> 13 report period checks.
"""
import os
from datetime import timedelta

from flask import Flask, g, request

from auth import authenticate, require_roles
from envelope import error_response, success_list, success_object
from errors import (
    ApiError,
    ERR_AFFILIATE_HAS_OPEN_ENCOUNTERS,
    ERR_AFFILIATE_NOT_ACTIVE,
    ERR_AFFILIATE_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_CLAIM_NOT_SETTLEABLE,
    ERR_CLAIM_RESUBMISSION_EXHAUSTED,
    ERR_CONFIDENTIAL_SERVICE_CANNOT_BILL,
    ERR_CATALOG_ENTRY_NOT_FOUND,
    ERR_ENCOUNTER_NOT_FOUND,
    ERR_HOLD_NOT_FOUND,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LICENSE_NOT_FOUND,
    ERR_LOT_EXPIRED,
    ERR_LOT_NOT_FOUND,
    ERR_NO_CURRENT_ASSESSMENT,
    ERR_OVERPAYMENT,
    ERR_PATIENT_NOT_FOUND,
    ERR_PRIVACY_HOLD_OVERLAP,
    ERR_PROVIDER_NOT_FOUND,
    ERR_RECOUPMENT_EXCEEDS_PAID,
    ERR_REFERRAL_NOT_FOUND,
    ERR_REINSERTION_WINDOW_EXCEEDED,
    ERR_REPORT_NOT_FOUND,
    ERR_REPORT_PERIOD_OPEN,
    ERR_REPORT_PERIOD_OVERLAP,
    ERR_RESERVATION_NOT_FOUND,
    ERR_SERVICE_OUT_OF_SCOPE,
    ERR_STALE_VERSION,
    ERR_STOCK_UNAVAILABLE,
    ERR_TELEHEALTH_LICENSE_GAP,
    ERR_TIER_NOT_FOUND,
)
from services import (
    RAPID_LOT_EXPIRY_GRACE_DAYS,
    RAPID_REINSERTION_WINDOW,
    assign_tier,
    base_entity,
    compute_fpl_pct,
    compute_patient_charge,
    find_catalog_entry,
    iso_format,
    license_derived_status,
    logical_now,
    page,
    parse_date,
    parse_ts,
    patient_is_minor,
    check_privacy_hold,
    req_bool,
    req_enum,
    req_field,
    req_int,
    req_str,
    require_body,
    serialize_affiliate,
    serialize_assessment,
    serialize_catalog_entry,
    serialize_claim,
    serialize_encounter,
    serialize_grant_report,
    serialize_license,
    serialize_lot,
    serialize_patient,
    serialize_privacy_hold,
    serialize_provider,
    serialize_referral,
    serialize_reservation,
    serialize_tier,
    touch,
)
from store import store
from workflows import (
    compute_report_aggregates,
    supersede_assessment_cascade,
)

app = Flask(__name__)

ALL_ROLES = [
    "GrantAdministrator", "PrivacyOfficer", "BillingSpecialist", "CareCoordinator",
    "SupplyCoordinator", "Clinician", "FrontDeskStaff",
]

PREFIX = "/family-planning"


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    return error_response(ERR_INVALID_REQUEST, "route not found", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return error_response(ERR_INVALID_REQUEST, "method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    app.logger.exception("unexpected error: %s", exc)
    return error_response(ERR_INVALID_REQUEST, "unexpected server error", 500)


@app.before_request
def _auth():
    if request.path.startswith(PREFIX):
        authenticate()


# ---------------------------------------------------------------------------
# Existence helpers (priority 3) — left-to-right
# ---------------------------------------------------------------------------

def get_affiliate(affiliate_id):
    a = store.affiliates.get(affiliate_id)
    if a is None:
        raise ApiError(ERR_AFFILIATE_NOT_FOUND, "Affiliate id does not exist", 404)
    return a


def get_patient(patient_id):
    p = store.patients.get(patient_id)
    if p is None:
        raise ApiError(ERR_PATIENT_NOT_FOUND, "Patient id does not exist", 404)
    return p


def get_provider(provider_id):
    p = store.providers.get(provider_id)
    if p is None:
        raise ApiError(ERR_PROVIDER_NOT_FOUND, "Provider id does not exist", 404)
    return p


def get_encounter(encounter_id):
    e = store.encounters.get(encounter_id)
    if e is None:
        raise ApiError(ERR_ENCOUNTER_NOT_FOUND, "Encounter id does not exist", 404)
    return e


def get_claim(claim_id):
    c = store.claims.get(claim_id)
    if c is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, "Claim id does not exist", 404)
    return c


def get_lot(lot_id):
    l = store.stock_lots.get(lot_id)
    if l is None:
        raise ApiError(ERR_LOT_NOT_FOUND, "Stock lot id does not exist", 404)
    return l


def get_reservation(reservation_id):
    r = store.reservations.get(reservation_id)
    if r is None:
        raise ApiError(ERR_RESERVATION_NOT_FOUND, "Device reservation id does not exist", 404)
    return r


def get_referral(referral_id):
    r = store.referrals.get(referral_id)
    if r is None:
        raise ApiError(ERR_REFERRAL_NOT_FOUND, "Referral order id does not exist", 404)
    return r


def get_report(report_id):
    r = store.grant_reports.get(report_id)
    if r is None:
        raise ApiError(ERR_REPORT_NOT_FOUND, "Grant report id does not exist", 404)
    return r


def get_hold(hold_id):
    h = store.privacy_holds.get(hold_id)
    if h is None:
        raise ApiError(ERR_HOLD_NOT_FOUND, "Privacy hold id does not exist", 404)
    return h


def get_assessment(assessment_id):
    a = store.assessments.get(assessment_id)
    if a is None:
        raise ApiError(ERR_INVALID_REQUEST, "Household assessment id does not exist", 404)
    return a


def get_catalog_entry(entry_id):
    e = store.catalog_entries.get(entry_id)
    if e is None:
        raise ApiError(ERR_CATALOG_ENTRY_NOT_FOUND, "Service catalog entry id does not exist", 404)
    return e


def get_tier(tier_id):
    t = store.fee_tiers.get(tier_id)
    if t is None:
        raise ApiError(ERR_TIER_NOT_FOUND, "Fee schedule tier id does not exist", 404)
    return t


def get_license(license_id):
    l = store.licenses.get(license_id)
    if l is None:
        raise ApiError(ERR_LICENSE_NOT_FOUND, "Provider license id does not exist", 404)
    return l


def require_affiliate_active(affiliate):
    """Priority 4: child creation requires parent Affiliate ACTIVE."""
    if affiliate["status"] != "ACTIVE":
        raise ApiError(
            ERR_AFFILIATE_NOT_ACTIVE,
            "Child creation requires parent Affiliate ACTIVE",
            409,
        )


def current_assessment(patient_id):
    for a in store.assessments.values():
        if a["patient_id"] == patient_id and a["status"] == "CURRENT":
            return a
    return None


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles(["GrantAdministrator"])
    body = require_body()
    new_dt = parse_ts(req_field(body, "to_iso8601"), "to_iso8601")
    with store.lock:
        store.clock.set(new_dt)
        # Re-derive EXPIRED ProviderLicense statuses and Patient.is_minor.
        for lic in store.licenses.values():
            lic["status"] = license_derived_status(lic)
        for p in store.patients.values():
            p["is_minor"] = patient_is_minor(p)
    return success_object({"current_utc": iso_format(new_dt)}, 200)


# ---------------------------------------------------------------------------
# Affiliates
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/affiliates", methods=["POST"])
def create_affiliate():
    require_roles(["GrantAdministrator"])
    body = require_body()
    affiliate_code = req_str(body, "affiliate_code")
    state_code = req_str(body, "state_code")
    quota = req_int(body, "low_income_priority_quota", minimum=0, maximum=100)
    with store.lock:
        a = base_entity()
        a.update({
            "affiliate_code": affiliate_code,
            "state_code": state_code,
            "grant_cycle_open": True,
            "low_income_priority_quota": quota,
            "status": "ACTIVE",
        })
        store.affiliates[a["id"]] = a
    return success_object(serialize_affiliate(a), 201)


@app.route(f"{PREFIX}/affiliates", methods=["GET"])
def list_affiliates():
    require_roles(ALL_ROLES)
    state_code = request.args.get("state_code")
    items = list(store.affiliates.values())
    if state_code is not None:
        items = [a for a in items if a["state_code"] == state_code]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_affiliate(a) for a in slice_], limit, offset, total)


@app.route(f"{PREFIX}/affiliates/<affiliateId>", methods=["GET"])
def get_affiliate_route(affiliateId):
    require_roles(ALL_ROLES)
    a = get_affiliate(affiliateId)
    return success_object(serialize_affiliate(a), 200)


@app.route(f"{PREFIX}/affiliates/<affiliateId>/suspend", methods=["POST"])
def suspend_affiliate(affiliateId):
    require_roles(["GrantAdministrator"])
    a = get_affiliate(affiliateId)
    with store.lock:
        if a["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Affiliate is not ACTIVE", 409)
        a["status"] = "SUSPENDED"
        touch(a)
        for e in store.catalog_entries.values():
            if e["affiliate_id"] == a["id"] and e["status"] == "ACTIVE":
                e["status"] = "SUSPENDED"
                touch(e)
    return success_object(serialize_affiliate(a), 200)


@app.route(f"{PREFIX}/affiliates/<affiliateId>/reinstate", methods=["POST"])
def reinstate_affiliate(affiliateId):
    require_roles(["GrantAdministrator"])
    a = get_affiliate(affiliateId)
    with store.lock:
        if a["status"] != "SUSPENDED":
            raise ApiError(ERR_INVALID_STATE, "Affiliate is not SUSPENDED", 409)
        a["status"] = "ACTIVE"
        touch(a)
        for e in store.catalog_entries.values():
            if e["affiliate_id"] == a["id"] and e["status"] == "SUSPENDED":
                e["status"] = "ACTIVE"
                touch(e)
    return success_object(serialize_affiliate(a), 200)


@app.route(f"{PREFIX}/affiliates/<affiliateId>/close", methods=["POST"])
def close_affiliate(affiliateId):
    require_roles(["GrantAdministrator"])
    a = get_affiliate(affiliateId)
    with store.lock:
        if a["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError(ERR_INVALID_STATE, "Affiliate is already CLOSED", 409)
        for enc in store.encounters.values():
            if enc["affiliate_id"] == a["id"] and enc["clinical_status"] in ("SCHEDULED", "IN_PROGRESS"):
                raise ApiError(
                    ERR_AFFILIATE_HAS_OPEN_ENCOUNTERS,
                    "Affiliate close blocked by encounters in SCHEDULED or IN_PROGRESS",
                    409,
                )
        a["status"] = "CLOSED"
        touch(a)
    return success_object(serialize_affiliate(a), 200)


# ---------------------------------------------------------------------------
# Service catalog
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/affiliates/<affiliateId>/service-catalog", methods=["POST"])
def create_catalog_entry(affiliateId):
    require_roles(["GrantAdministrator"])
    a = get_affiliate(affiliateId)
    require_affiliate_active(a)
    body = require_body()
    service_code = req_str(body, "service_code")
    in_scope = req_bool(body, "in_scope")
    telehealth_eligible = body.get("telehealth_eligible", False)
    if not isinstance(telehealth_eligible, bool):
        raise ApiError(ERR_INVALID_REQUEST, "telehealth_eligible must be a boolean", 400)
    full_fee_cents = req_int(body, "full_fee_cents", minimum=0)
    with store.lock:
        e = base_entity()
        e.update({
            "affiliate_id": a["id"],
            "service_code": service_code,
            "in_scope": in_scope,
            "telehealth_eligible": telehealth_eligible,
            "full_fee_cents": full_fee_cents,
            "status": "ACTIVE",
        })
        store.catalog_entries[e["id"]] = e
    return success_object(serialize_catalog_entry(e), 201)


@app.route(f"{PREFIX}/affiliates/<affiliateId>/service-catalog", methods=["GET"])
def list_catalog_entries(affiliateId):
    require_roles(ALL_ROLES)
    a = get_affiliate(affiliateId)
    items = [e for e in store.catalog_entries.values() if e["affiliate_id"] == a["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_catalog_entry(e) for e in slice_], limit, offset, total)


@app.route(f"{PREFIX}/service-catalog/<entryId>", methods=["GET"])
def get_catalog_entry_route(entryId):
    require_roles(ALL_ROLES)
    e = get_catalog_entry(entryId)
    return success_object(serialize_catalog_entry(e), 200)


# ---------------------------------------------------------------------------
# Fee tiers
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/affiliates/<affiliateId>/fee-tiers", methods=["POST"])
def create_fee_tier(affiliateId):
    require_roles(["GrantAdministrator"])
    a = get_affiliate(affiliateId)
    require_affiliate_active(a)
    body = require_body()
    tier_code = req_str(body, "tier_code")
    fpl_min = req_int(body, "fpl_pct_min_inclusive", minimum=0)
    fpl_max = req_int(body, "fpl_pct_max_exclusive", minimum=0)
    discount_pct = req_int(body, "discount_pct", minimum=0, maximum=100)
    nominal = body.get("nominal_copay_cents", 0)
    if isinstance(nominal, bool) or not isinstance(nominal, int) or nominal < 0:
        raise ApiError(ERR_INVALID_REQUEST, "nominal_copay_cents must be a non-negative integer", 400)
    requires_doc = req_bool(body, "requires_documentation")
    with store.lock:
        t = base_entity()
        t.update({
            "affiliate_id": a["id"],
            "tier_code": tier_code,
            "fpl_pct_min_inclusive": fpl_min,
            "fpl_pct_max_exclusive": fpl_max,
            "discount_pct": discount_pct,
            "nominal_copay_cents": nominal,
            "requires_documentation": requires_doc,
        })
        store.fee_tiers[t["id"]] = t
    return success_object(serialize_tier(t), 201)


@app.route(f"{PREFIX}/affiliates/<affiliateId>/fee-tiers", methods=["GET"])
def list_fee_tiers(affiliateId):
    require_roles(ALL_ROLES)
    a = get_affiliate(affiliateId)
    items = [t for t in store.fee_tiers.values() if t["affiliate_id"] == a["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_tier(t) for t in slice_], limit, offset, total)


@app.route(f"{PREFIX}/fee-tiers/<tierId>", methods=["GET"])
def get_fee_tier_route(tierId):
    require_roles(ALL_ROLES)
    t = get_tier(tierId)
    return success_object(serialize_tier(t), 200)


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/affiliates/<affiliateId>/patients", methods=["POST"])
def create_patient(affiliateId):
    require_roles(["FrontDeskStaff"])
    a = get_affiliate(affiliateId)
    require_affiliate_active(a)
    body = require_body()
    external_ref = req_str(body, "external_ref")
    dob = req_str(body, "date_of_birth")
    parse_date(dob, "date_of_birth")
    confidentiality_flag = body.get("confidentiality_flag", False)
    if not isinstance(confidentiality_flag, bool):
        raise ApiError(ERR_INVALID_REQUEST, "confidentiality_flag must be a boolean", 400)
    insurance_policy_id = body.get("insurance_policy_id")
    if insurance_policy_id is not None and not isinstance(insurance_policy_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "insurance_policy_id must be a string", 400)
    with store.lock:
        p = base_entity()
        p.update({
            "affiliate_id": a["id"],
            "external_ref": external_ref,
            "date_of_birth": dob,
            "confidentiality_flag": confidentiality_flag,
            "insurance_policy_id": insurance_policy_id,
            "status": "ACTIVE",
        })
        p["is_minor"] = patient_is_minor(p)
        store.patients[p["id"]] = p
    return success_object(serialize_patient(p), 201)


@app.route(f"{PREFIX}/affiliates/<affiliateId>/patients", methods=["GET"])
def list_patients(affiliateId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "BillingSpecialist",
                   "CareCoordinator", "Clinician", "FrontDeskStaff"])
    a = get_affiliate(affiliateId)
    items = [p for p in store.patients.values() if p["affiliate_id"] == a["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_patient(p) for p in slice_], limit, offset, total)


@app.route(f"{PREFIX}/patients/<patientId>", methods=["GET"])
def get_patient_route(patientId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "BillingSpecialist",
                   "CareCoordinator", "Clinician", "FrontDeskStaff"])
    p = get_patient(patientId)
    check_privacy_hold(p["id"])
    return success_object(serialize_patient(p), 200)


# ---------------------------------------------------------------------------
# Household assessments
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/patients/<patientId>/household-assessments", methods=["POST"])
def create_assessment(patientId):
    require_roles(["FrontDeskStaff"])
    p = get_patient(patientId)
    affiliate = store.affiliates.get(p["affiliate_id"])
    # Assessments and encounters are not in PRD §2.8's child-creation list;
    # affiliate suspension is surfaced via the catalog cascade
    # (ERR_SERVICE_OUT_OF_SCOPE, PRD §2.7), not ERR_AFFILIATE_NOT_ACTIVE.
    check_privacy_hold(p["id"])
    body = require_body()
    household_size = req_int(body, "household_size", minimum=1)
    annual_income_cents = req_int(body, "annual_income_cents", minimum=0)
    income_basis = req_enum(body, "income_basis", {"DOCUMENTED", "SELF_DECLARED"})
    expected_version = req_field(body, "expected_patient_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_patient_version must be an integer", 400)
    if expected_version != p["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_patient_version does not match the patient's current version",
            412,
        )
    with store.lock:
        fpl_pct = compute_fpl_pct(household_size, annual_income_cents)
        tier = assign_tier(p["affiliate_id"], fpl_pct, income_basis)
        # Link 1: supersede prior CURRENT
        prior = current_assessment(p["id"])
        if prior is not None:
            prior["status"] = "SUPERSEDED"
            touch(prior)
        a = base_entity()
        a.update({
            "patient_id": p["id"],
            "household_size": household_size,
            "annual_income_cents": annual_income_cents,
            "income_basis": income_basis,
            "fpl_pct": fpl_pct,
            "assigned_tier_code": tier["tier_code"],
            "effective_from": iso_format(logical_now()),
            "status": "CURRENT",
        })
        store.assessments[a["id"]] = a
        # Links 2-4 cascade
        supersede_assessment_cascade(p, a)
        touch(p)
    return success_object(serialize_assessment(a), 201)


@app.route(f"{PREFIX}/patients/<patientId>/household-assessments", methods=["GET"])
def list_assessments(patientId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "BillingSpecialist", "FrontDeskStaff"])
    p = get_patient(patientId)
    check_privacy_hold(p["id"])
    items = [a for a in store.assessments.values() if a["patient_id"] == p["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_assessment(a) for a in slice_], limit, offset, total)


@app.route(f"{PREFIX}/household-assessments/<assessmentId>", methods=["GET"])
def get_assessment_route(assessmentId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "BillingSpecialist", "FrontDeskStaff"])
    a = get_assessment(assessmentId)
    check_privacy_hold(a["patient_id"])
    return success_object(serialize_assessment(a), 200)


@app.route(f"{PREFIX}/household-assessments/<assessmentId>/encounters", methods=["GET"])
def list_assessment_encounters(assessmentId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "BillingSpecialist", "FrontDeskStaff"])
    a = get_assessment(assessmentId)
    check_privacy_hold(a["patient_id"])
    items = [e for e in store.encounters.values() if e["assessment_id"] == a["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_encounter(e) for e in slice_], limit, offset, total)


# ---------------------------------------------------------------------------
# Providers and licenses
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/affiliates/<affiliateId>/providers", methods=["POST"])
def create_provider(affiliateId):
    require_roles(["GrantAdministrator"])
    a = get_affiliate(affiliateId)
    require_affiliate_active(a)
    body = require_body()
    display_name = req_str(body, "display_name")
    provider_type = req_enum(body, "provider_type", {"PHYSICIAN", "NP", "RN", "COUNSELOR"})
    with store.lock:
        p = base_entity()
        p.update({
            "affiliate_id": a["id"],
            "display_name": display_name,
            "provider_type": provider_type,
            "status": "ACTIVE",
        })
        store.providers[p["id"]] = p
    return success_object(serialize_provider(p), 201)


@app.route(f"{PREFIX}/affiliates/<affiliateId>/providers", methods=["GET"])
def list_providers(affiliateId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "CareCoordinator", "Clinician", "FrontDeskStaff"])
    a = get_affiliate(affiliateId)
    items = [p for p in store.providers.values() if p["affiliate_id"] == a["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_provider(p) for p in slice_], limit, offset, total)


@app.route(f"{PREFIX}/providers/<providerId>", methods=["GET"])
def get_provider_route(providerId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "CareCoordinator", "Clinician", "FrontDeskStaff"])
    p = get_provider(providerId)
    return success_object(serialize_provider(p), 200)


@app.route(f"{PREFIX}/providers/<providerId>/licenses", methods=["POST"])
def create_license(providerId):
    require_roles(["GrantAdministrator"])
    p = get_provider(providerId)
    body = require_body()
    state_code = req_str(body, "state_code")
    valid_from = req_str(body, "valid_from")
    valid_until = req_str(body, "valid_until")
    parse_ts(valid_from, "valid_from")
    parse_ts(valid_until, "valid_until")
    with store.lock:
        lic = base_entity()
        lic.update({
            "provider_id": p["id"],
            "state_code": state_code,
            "valid_from": valid_from,
            "valid_until": valid_until,
        })
        lic["status"] = license_derived_status(lic)
        store.licenses[lic["id"]] = lic
    return success_object(serialize_license(lic), 201)


@app.route(f"{PREFIX}/providers/<providerId>/licenses", methods=["GET"])
def list_licenses(providerId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "CareCoordinator", "Clinician", "FrontDeskStaff"])
    p = get_provider(providerId)
    state_code = request.args.get("state_code")
    items = [l for l in store.licenses.values() if l["provider_id"] == p["id"]]
    if state_code is not None:
        items = [l for l in items if l["state_code"] == state_code]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_license(l) for l in slice_], limit, offset, total)


@app.route(f"{PREFIX}/licenses/<licenseId>", methods=["GET"])
def get_license_route(licenseId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "CareCoordinator", "Clinician", "FrontDeskStaff"])
    lic = get_license(licenseId)
    return success_object(serialize_license(lic), 200)


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------

def _encounter_list(filters):
    clinical = request.args.get("clinical_status")
    billing = request.args.get("billing_status")
    items = list(filters)
    if clinical is not None:
        items = [e for e in items if e["clinical_status"] == clinical]
    if billing is not None:
        items = [e for e in items if e["billing_status"] == billing]
    return items


@app.route(f"{PREFIX}/patients/<patientId>/encounters", methods=["POST"])
def create_encounter(patientId):
    require_roles(["FrontDeskStaff"])
    p = get_patient(patientId)
    affiliate = store.affiliates.get(p["affiliate_id"])
    # Assessments and encounters are not in PRD §2.8's child-creation list;
    # affiliate suspension is surfaced via the catalog cascade
    # (ERR_SERVICE_OUT_OF_SCOPE, PRD §2.7), not ERR_AFFILIATE_NOT_ACTIVE.
    check_privacy_hold(p["id"])
    body = require_body()
    service_code = req_str(body, "service_code")
    provider_id = req_str(body, "provider_id")
    channel = req_enum(body, "channel", {"IN_PERSON", "TELEHEALTH"})
    patient_location_state = body.get("patient_location_state")
    scheduled_start_s = req_str(body, "scheduled_start")
    scheduled_end_s = req_str(body, "scheduled_end")
    scheduled_start = parse_ts(scheduled_start_s, "scheduled_start")
    scheduled_end = parse_ts(scheduled_end_s, "scheduled_end")
    provider = get_provider(provider_id)
    # Priority 5.5: current assessment required
    assessment = current_assessment(p["id"])
    if assessment is None:
        raise ApiError(
            ERR_NO_CURRENT_ASSESSMENT,
            "Encounter creation requires a CURRENT HouseholdAssessment for the patient",
            422,
        )
    # Priority 7: service scope
    entry = find_catalog_entry(p["affiliate_id"], service_code)
    if entry is None or not entry["in_scope"] or entry["status"] != "ACTIVE":
        raise ApiError(
            ERR_SERVICE_OUT_OF_SCOPE,
            "service_code missing, not in_scope, or catalog entry SUSPENDED for this affiliate",
            422,
        )
    # Priority 8: telehealth licensure (whole-interval containment)
    if channel == "TELEHEALTH":
        if not isinstance(patient_location_state, str) or not patient_location_state:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "patient_location_state is required for TELEHEALTH encounters",
                400,
            )
        covered = False
        for lic in store.licenses.values():
            if lic["provider_id"] != provider["id"]:
                continue
            if lic["state_code"] != patient_location_state:
                continue
            if license_derived_status(lic) != "ACTIVE":
                continue
            if parse_ts(lic["valid_from"], "valid_from") <= scheduled_start and \
               parse_ts(lic["valid_until"], "valid_until") >= scheduled_end:
                covered = True
                break
        if not covered:
            raise ApiError(
                ERR_TELEHEALTH_LICENSE_GAP,
                "No ACTIVE ProviderLicense contains the whole encounter interval for patient_location_state",
                422,
            )
    # Priority 9: temporal well-formedness
    if scheduled_end <= scheduled_start or not affiliate or not affiliate["grant_cycle_open"]:
        raise ApiError(
            ERR_INVALID_INTERVAL,
            "scheduled_end must be > scheduled_start and the grant cycle must be open at creation",
            400,
        )
    with store.lock:
        tier = None
        for t in store.fee_tiers.values():
            if t["affiliate_id"] == p["affiliate_id"] and t["tier_code"] == assessment["assigned_tier_code"]:
                tier = t
                break
        from services import sliding_fee_charge
        charge = sliding_fee_charge(entry["full_fee_cents"], tier) if tier else entry["full_fee_cents"]
        e = base_entity()
        e.update({
            "patient_id": p["id"],
            "affiliate_id": p["affiliate_id"],
            "service_code": service_code,
            "provider_id": provider["id"],
            "channel": channel,
            "patient_location_state": patient_location_state,
            "scheduled_start": scheduled_start_s,
            "scheduled_end": scheduled_end_s,
            "assessment_id": assessment["id"],
            "patient_charge_cents": charge,
            "clinical_status": "SCHEDULED",
            "billing_status": "UNBILLED",
        })
        store.encounters[e["id"]] = e
    return success_object(serialize_encounter(e), 201)


@app.route(f"{PREFIX}/patients/<patientId>/encounters", methods=["GET"])
def list_patient_encounters(patientId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "BillingSpecialist",
                   "CareCoordinator", "Clinician", "FrontDeskStaff"])
    p = get_patient(patientId)
    check_privacy_hold(p["id"])
    items = _encounter_list(e for e in store.encounters.values() if e["patient_id"] == p["id"])
    slice_, limit, offset, total = page(items)
    return success_list([serialize_encounter(e) for e in slice_], limit, offset, total)


@app.route(f"{PREFIX}/affiliates/<affiliateId>/encounters", methods=["GET"])
def list_affiliate_encounters(affiliateId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "BillingSpecialist",
                   "CareCoordinator", "Clinician", "FrontDeskStaff"])
    a = get_affiliate(affiliateId)
    items = _encounter_list(e for e in store.encounters.values() if e["affiliate_id"] == a["id"])
    slice_, limit, offset, total = page(items)
    return success_list([serialize_encounter(e) for e in slice_], limit, offset, total)


@app.route(f"{PREFIX}/providers/<providerId>/encounters", methods=["GET"])
def list_provider_encounters(providerId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "CareCoordinator", "Clinician", "FrontDeskStaff"])
    p = get_provider(providerId)
    items = [e for e in store.encounters.values() if e["provider_id"] == p["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_encounter(e) for e in slice_], limit, offset, total)


@app.route(f"{PREFIX}/encounters/<encounterId>", methods=["GET"])
def get_encounter_route(encounterId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "BillingSpecialist",
                   "CareCoordinator", "Clinician", "FrontDeskStaff"])
    e = get_encounter(encounterId)
    check_privacy_hold(e["patient_id"])
    return success_object(serialize_encounter(e), 200)


@app.route(f"{PREFIX}/encounters/<encounterId>/start", methods=["POST"])
def start_encounter(encounterId):
    require_roles(["Clinician"])
    e = get_encounter(encounterId)
    check_privacy_hold(e["patient_id"])
    with store.lock:
        if e["clinical_status"] != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE, "Encounter is not SCHEDULED", 409)
        if logical_now() < parse_ts(e["scheduled_start"], "scheduled_start"):
            raise ApiError(ERR_INVALID_STATE, "Logical clock has not reached scheduled_start", 409)
        e["clinical_status"] = "IN_PROGRESS"
        touch(e)
    return success_object(serialize_encounter(e), 200)


@app.route(f"{PREFIX}/encounters/<encounterId>/complete", methods=["POST"])
def complete_encounter(encounterId):
    require_roles(["Clinician"])
    e = get_encounter(encounterId)
    check_privacy_hold(e["patient_id"])
    with store.lock:
        if e["clinical_status"] != "IN_PROGRESS":
            raise ApiError(ERR_INVALID_STATE, "Encounter is not IN_PROGRESS", 409)
        e["clinical_status"] = "COMPLETED"
        touch(e)
        for res in store.reservations.values():
            if res["encounter_id"] == e["id"] and res["status"] == "RESERVED":
                res["status"] = "FULFILLED"
                touch(res)
                lot = store.stock_lots.get(res["lot_id"])
                if lot is not None:
                    lot["on_hand"] -= 1
                    lot["reserved_out"] -= 1
                    touch(lot)
    return success_object(serialize_encounter(e), 200)


@app.route(f"{PREFIX}/encounters/<encounterId>/cancel", methods=["POST"])
def cancel_encounter(encounterId):
    require_roles(["FrontDeskStaff"])
    e = get_encounter(encounterId)
    check_privacy_hold(e["patient_id"])
    with store.lock:
        if e["clinical_status"] != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE, "Encounter is not SCHEDULED", 409)
        e["clinical_status"] = "CANCELLED"
        touch(e)
        for res in store.reservations.values():
            if res["encounter_id"] == e["id"] and res["status"] == "RESERVED":
                res["status"] = "RELEASED"
                touch(res)
                lot = store.stock_lots.get(res["lot_id"])
                if lot is not None:
                    lot["reserved_out"] -= 1
                    touch(lot)
    return success_object(serialize_encounter(e), 200)


@app.route(f"{PREFIX}/encounters/<encounterId>/waive-billing", methods=["POST"])
def waive_billing(encounterId):
    require_roles(["BillingSpecialist"])
    e = get_encounter(encounterId)
    check_privacy_hold(e["patient_id"])
    with store.lock:
        if e["clinical_status"] != "COMPLETED" or e["billing_status"] != "UNBILLED":
            raise ApiError(
                ERR_INVALID_STATE,
                "Waive requires clinical_status COMPLETED and billing_status UNBILLED",
                409,
            )
        patient = store.patients.get(e["patient_id"])
        minor_at_encounter = patient_is_minor(
            patient, ref=parse_ts(e["scheduled_start"], "scheduled_start").date()
        )
        if not (patient["confidentiality_flag"] or minor_at_encounter):
            raise ApiError(
                ERR_INVALID_STATE,
                "Billing waiver requires a confidential patient (confidentiality_flag or minor at encounter time)",
                409,
            )
        e["billing_status"] = "WAIVED"
        touch(e)
    return success_object(serialize_encounter(e), 200)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/encounters/<encounterId>/claims", methods=["POST"])
def create_claim(encounterId):
    require_roles(["BillingSpecialist"])
    e = get_encounter(encounterId)
    check_privacy_hold(e["patient_id"])
    with store.lock:
        if e["clinical_status"] != "COMPLETED" or e["billing_status"] != "UNBILLED":
            raise ApiError(
                ERR_INVALID_STATE,
                "Claim creation requires clinical_status COMPLETED and billing_status UNBILLED",
                409,
            )
        patient = store.patients.get(e["patient_id"])
        minor_at_encounter = patient_is_minor(
            patient, ref=parse_ts(e["scheduled_start"], "scheduled_start").date()
        )
        suppressed = bool(patient["confidentiality_flag"] or minor_at_encounter)
        if suppressed:
            billed = 0
        else:
            entry = find_catalog_entry(e["affiliate_id"], e["service_code"])
            full_fee = entry["full_fee_cents"] if entry else 0
            billed = full_fee - e["patient_charge_cents"]
        c = base_entity()
        c.update({
            "encounter_id": e["id"],
            "policy_id": patient.get("insurance_policy_id"),
            "confidential_suppression": suppressed,
            "billed_cents": billed,
            "paid_cents": 0,
            "recouped_cents": 0,
            "net_receivable_cents": billed,
            "submission_round": 1,
            "status": "DRAFT",
        })
        store.claims[c["id"]] = c
    return success_object(serialize_claim(c), 201)


@app.route(f"{PREFIX}/encounters/<encounterId>/claims", methods=["GET"])
def list_claims(encounterId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "BillingSpecialist"])
    e = get_encounter(encounterId)
    check_privacy_hold(e["patient_id"])
    items = [c for c in store.claims.values() if c["encounter_id"] == e["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_claim(c) for c in slice_], limit, offset, total)


@app.route(f"{PREFIX}/claims/<claimId>", methods=["GET"])
def get_claim_route(claimId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "BillingSpecialist"])
    c = get_claim(claimId)
    enc = store.encounters.get(c["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    return success_object(serialize_claim(c), 200)


@app.route(f"{PREFIX}/claims/<claimId>/submit", methods=["POST"])
def submit_claim(claimId):
    require_roles(["BillingSpecialist"])
    c = get_claim(claimId)
    enc = store.encounters.get(c["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    with store.lock:
        if c["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, "Claim is not DRAFT", 409)
        if enc is None or enc["clinical_status"] != "COMPLETED":
            raise ApiError(ERR_INVALID_STATE, "Encounter is not COMPLETED", 409)
        # Priority 6: confidential-suppression gate
        if c["confidential_suppression"]:
            raise ApiError(
                ERR_CONFIDENTIAL_SERVICE_CANNOT_BILL,
                "Suppressed claims may never reach a payer",
                422,
            )
        c["status"] = "SUBMITTED"
        touch(c)
        if enc["billing_status"] == "UNBILLED":
            enc["billing_status"] = "CLAIMED"
            touch(enc)
    return success_object(serialize_claim(c), 200)


@app.route(f"{PREFIX}/claims/<claimId>/return", methods=["POST"])
def return_claim(claimId):
    require_roles(["BillingSpecialist"])
    c = get_claim(claimId)
    enc = store.encounters.get(c["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    with store.lock:
        if c["status"] != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, "Claim is not SUBMITTED", 409)
        c["status"] = "RETURNED"
        touch(c)
    return success_object(serialize_claim(c), 200)


@app.route(f"{PREFIX}/claims/<claimId>/resubmit", methods=["POST"])
def resubmit_claim(claimId):
    require_roles(["BillingSpecialist"])
    c = get_claim(claimId)
    enc = store.encounters.get(c["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    with store.lock:
        if c["status"] != "RETURNED":
            raise ApiError(ERR_INVALID_STATE, "Claim is not RETURNED", 409)
        if c["submission_round"] >= 3:
            raise ApiError(
                ERR_CLAIM_RESUBMISSION_EXHAUSTED,
                "Resubmit attempted at submission_round == 3",
                409,
            )
        c["status"] = "SUBMITTED"
        c["submission_round"] += 1
        touch(c)
    return success_object(serialize_claim(c), 200)


@app.route(f"{PREFIX}/claims/<claimId>/adjudicate", methods=["POST"])
def adjudicate_claim(claimId):
    require_roles(["BillingSpecialist"])
    c = get_claim(claimId)
    enc = store.encounters.get(c["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    body = require_body()
    amount = req_int(body, "amount_cents", minimum=0)
    with store.lock:
        if c["status"] != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, "Claim is not SUBMITTED", 409)
        # Safety gate before fiscal checks (priority 6 before 12)
        if c["confidential_suppression"]:
            raise ApiError(
                ERR_CONFIDENTIAL_SERVICE_CANNOT_BILL,
                "Suppressed claims may never reach a payer",
                422,
            )
        if amount > c["net_receivable_cents"]:
            raise ApiError(ERR_OVERPAYMENT, "Payment amount exceeds net_receivable_cents", 422)
        c["status"] = "PAID"
        c["paid_cents"] += amount
        c["net_receivable_cents"] = c["billed_cents"] - c["paid_cents"] + c["recouped_cents"]
        touch(c)
    return success_object(serialize_claim(c), 200)


@app.route(f"{PREFIX}/claims/<claimId>/deny", methods=["POST"])
def deny_claim(claimId):
    require_roles(["BillingSpecialist"])
    c = get_claim(claimId)
    enc = store.encounters.get(c["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    with store.lock:
        if c["status"] != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, "Claim is not SUBMITTED", 409)
        c["status"] = "DENIED"
        touch(c)
    return success_object(serialize_claim(c), 200)


@app.route(f"{PREFIX}/claims/<claimId>/void", methods=["POST"])
def void_claim(claimId):
    require_roles(["BillingSpecialist"])
    c = get_claim(claimId)
    enc = store.encounters.get(c["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    with store.lock:
        if c["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, "Claim is not DRAFT", 409)
        c["status"] = "VOID"
        touch(c)
        if enc is not None and enc["billing_status"] == "CLAIMED":
            enc["billing_status"] = "UNBILLED"
            touch(enc)
    return success_object(serialize_claim(c), 200)


@app.route(f"{PREFIX}/claims/<claimId>/recoup", methods=["POST"])
def recoup_claim(claimId):
    require_roles(["BillingSpecialist"])
    c = get_claim(claimId)
    enc = store.encounters.get(c["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    body = require_body()
    amount = req_int(body, "amount_cents", minimum=0)
    with store.lock:
        if c["status"] != "PAID":
            raise ApiError(ERR_INVALID_STATE, "Claim is not PAID", 409)
        if amount > c["paid_cents"] - c["recouped_cents"]:
            raise ApiError(
                ERR_RECOUPMENT_EXCEEDS_PAID,
                "Recoupment amount exceeds paid_cents - recouped_cents",
                422,
            )
        c["recouped_cents"] += amount
        c["net_receivable_cents"] = c["billed_cents"] - c["paid_cents"] + c["recouped_cents"]
        touch(c)
    return success_object(serialize_claim(c), 200)


@app.route(f"{PREFIX}/claims/<claimId>/settle", methods=["POST"])
def settle_claim(claimId):
    require_roles(["BillingSpecialist"])
    c = get_claim(claimId)
    enc = store.encounters.get(c["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    with store.lock:
        if enc is None:
            raise ApiError(ERR_CLAIM_NOT_SETTLEABLE, "Claim has no encounter", 409)
        if enc["clinical_status"] != "COMPLETED" or enc["billing_status"] != "CLAIMED":
            raise ApiError(
                ERR_CLAIM_NOT_SETTLEABLE,
                "Settle requires encounter COMPLETED and CLAIMED",
                409,
            )
        settleable = (c["status"] == "PAID" and c["net_receivable_cents"] == 0) or c["status"] == "DENIED"
        if not settleable:
            raise ApiError(
                ERR_CLAIM_NOT_SETTLEABLE,
                "Settle requires claim PAID with net_receivable_cents == 0, or DENIED",
                409,
            )
        enc["billing_status"] = "SETTLED"
        touch(enc)
    return success_object(serialize_encounter(enc), 200)


# ---------------------------------------------------------------------------
# Stock lots and device reservations
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/affiliates/<affiliateId>/stock-lots", methods=["POST"])
def create_stock_lot(affiliateId):
    require_roles(["SupplyCoordinator"])
    a = get_affiliate(affiliateId)
    require_affiliate_active(a)
    body = require_body()
    device_code = req_enum(body, "device_code", {"IUD_COPPER", "IUD_HORMONAL", "IMPLANT"})
    lot_number = req_str(body, "lot_number")
    unit_cost_cents = req_int(body, "unit_cost_cents", minimum=0)
    on_hand = req_int(body, "on_hand", minimum=0)
    expires_on = req_str(body, "expires_on")
    parse_date(expires_on, "expires_on")
    with store.lock:
        l = base_entity()
        l.update({
            "affiliate_id": a["id"],
            "device_code": device_code,
            "lot_number": lot_number,
            "unit_cost_cents": unit_cost_cents,
            "on_hand": on_hand,
            "reserved_out": 0,
            "expires_on": expires_on,
        })
        store.stock_lots[l["id"]] = l
    return success_object(serialize_lot(l), 201)


@app.route(f"{PREFIX}/affiliates/<affiliateId>/stock-lots", methods=["GET"])
def list_stock_lots(affiliateId):
    require_roles(["GrantAdministrator", "SupplyCoordinator", "Clinician"])
    a = get_affiliate(affiliateId)
    device_code = request.args.get("device_code")
    items = [l for l in store.stock_lots.values() if l["affiliate_id"] == a["id"]]
    if device_code is not None:
        items = [l for l in items if l["device_code"] == device_code]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_lot(l) for l in slice_], limit, offset, total)


@app.route(f"{PREFIX}/stock-lots/<lotId>", methods=["GET"])
def get_stock_lot_route(lotId):
    require_roles(["GrantAdministrator", "SupplyCoordinator", "Clinician"])
    l = get_lot(lotId)
    return success_object(serialize_lot(l), 200)


@app.route(f"{PREFIX}/stock-lots/<lotId>/device-reservations", methods=["GET"])
def list_lot_reservations(lotId):
    require_roles(["GrantAdministrator", "SupplyCoordinator", "Clinician"])
    l = get_lot(lotId)
    items = [r for r in store.reservations.values() if r["lot_id"] == l["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_reservation(r) for r in slice_], limit, offset, total)


@app.route(f"{PREFIX}/encounters/<encounterId>/device-reservations", methods=["POST"])
def create_reservation(encounterId):
    require_roles(["SupplyCoordinator"])
    e = get_encounter(encounterId)
    check_privacy_hold(e["patient_id"])
    body = require_body()
    lot_id = req_str(body, "lot_id")
    is_rapid = body.get("is_rapid_reinsertion", False)
    if not isinstance(is_rapid, bool):
        raise ApiError(ERR_INVALID_REQUEST, "is_rapid_reinsertion must be a boolean", 400)
    expulsion_at = body.get("expulsion_recorded_at")
    if is_rapid:
        if not isinstance(expulsion_at, str) or not expulsion_at:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "expulsion_recorded_at is required when is_rapid_reinsertion is true",
                400,
            )
        expulsion_dt = parse_ts(expulsion_at, "expulsion_recorded_at")
    else:
        expulsion_dt = parse_ts(expulsion_at, "expulsion_recorded_at") if expulsion_at else None
    lot = get_lot(lot_id)
    with store.lock:
        # Priority 11: reservation safety
        if e["clinical_status"] != "SCHEDULED":
            raise ApiError(
                ERR_INVALID_STATE,
                "Reservations are only allowed against SCHEDULED encounters",
                422,
            )
        if lot["on_hand"] - lot["reserved_out"] < 1:
            raise ApiError(ERR_STOCK_UNAVAILABLE, "Lot has on_hand - reserved_out < 1", 422)
        scheduled_start = parse_ts(e["scheduled_start"], "scheduled_start")
        if is_rapid:
            # Inclusive 30-day window, second precision
            if scheduled_start - expulsion_dt > RAPID_REINSERTION_WINDOW:
                raise ApiError(
                    ERR_REINSERTION_WINDOW_EXCEEDED,
                    "Rapid reinsertion scheduled more than 30 days after expulsion_recorded_at",
                    422,
                )
        expires = parse_date(lot["expires_on"], "expires_on")
        enc_date = scheduled_start.date()
        if expires < enc_date:
            if is_rapid:
                if (enc_date - expires).days > RAPID_LOT_EXPIRY_GRACE_DAYS:
                    raise ApiError(
                        ERR_LOT_EXPIRED,
                        "Lot expires before the encounter date (grace only for eligible rapid reinsertion)",
                        422,
                    )
            else:
                raise ApiError(
                    ERR_LOT_EXPIRED,
                    "Lot expires before the encounter date (grace only for eligible rapid reinsertion)",
                    422,
                )
        r = base_entity()
        r.update({
            "encounter_id": e["id"],
            "lot_id": lot["id"],
            "is_rapid_reinsertion": is_rapid,
            "expulsion_recorded_at": expulsion_at,
            "status": "RESERVED",
        })
        store.reservations[r["id"]] = r
        lot["reserved_out"] += 1
        touch(lot)
    return success_object(serialize_reservation(r), 201)


@app.route(f"{PREFIX}/encounters/<encounterId>/device-reservations", methods=["GET"])
def list_encounter_reservations(encounterId):
    require_roles(["GrantAdministrator", "SupplyCoordinator", "Clinician"])
    e = get_encounter(encounterId)
    check_privacy_hold(e["patient_id"])
    items = [r for r in store.reservations.values() if r["encounter_id"] == e["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_reservation(r) for r in slice_], limit, offset, total)


@app.route(f"{PREFIX}/device-reservations/<reservationId>", methods=["GET"])
def get_reservation_route(reservationId):
    require_roles(["GrantAdministrator", "SupplyCoordinator", "Clinician"])
    r = get_reservation(reservationId)
    enc = store.encounters.get(r["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    return success_object(serialize_reservation(r), 200)


@app.route(f"{PREFIX}/device-reservations/<reservationId>/release", methods=["POST"])
def release_reservation(reservationId):
    require_roles(["SupplyCoordinator"])
    r = get_reservation(reservationId)
    enc = store.encounters.get(r["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    with store.lock:
        if r["status"] != "RESERVED":
            raise ApiError(ERR_INVALID_STATE, "Reservation is not RESERVED", 409)
        r["status"] = "RELEASED"
        touch(r)
        lot = store.stock_lots.get(r["lot_id"])
        if lot is not None:
            lot["reserved_out"] -= 1
            touch(lot)
    return success_object(serialize_reservation(r), 200)


# ---------------------------------------------------------------------------
# Referral orders
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/encounters/<encounterId>/referral-orders", methods=["POST"])
def create_referral(encounterId):
    require_roles(["Clinician", "CareCoordinator"])
    e = get_encounter(encounterId)
    check_privacy_hold(e["patient_id"])
    body = require_body()
    requested_service_code = req_str(body, "requested_service_code")
    receiving_org = req_str(body, "receiving_org")
    reason_code = req_enum(
        body, "reason_code",
        {"OUT_OF_SCOPE_STATE_LAW", "OUT_OF_SCOPE_AFFILIATE", "CAPACITY"},
    )
    with store.lock:
        r = base_entity()
        r.update({
            "encounter_id": e["id"],
            "requested_service_code": requested_service_code,
            "receiving_org": receiving_org,
            "reason_code": reason_code,
            "status": "OPEN",
        })
        store.referrals[r["id"]] = r
    return success_object(serialize_referral(r), 201)


@app.route(f"{PREFIX}/encounters/<encounterId>/referral-orders", methods=["GET"])
def list_referrals(encounterId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "CareCoordinator", "Clinician"])
    e = get_encounter(encounterId)
    check_privacy_hold(e["patient_id"])
    items = [r for r in store.referrals.values() if r["encounter_id"] == e["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_referral(r) for r in slice_], limit, offset, total)


@app.route(f"{PREFIX}/referral-orders/<referralId>", methods=["GET"])
def get_referral_route(referralId):
    require_roles(["GrantAdministrator", "PrivacyOfficer", "CareCoordinator", "Clinician"])
    r = get_referral(referralId)
    enc = store.encounters.get(r["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    return success_object(serialize_referral(r), 200)


@app.route(f"{PREFIX}/referral-orders/<referralId>/acknowledge", methods=["POST"])
def acknowledge_referral(referralId):
    require_roles(["CareCoordinator"])
    r = get_referral(referralId)
    enc = store.encounters.get(r["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    with store.lock:
        if r["status"] != "OPEN":
            raise ApiError(ERR_INVALID_STATE, "Referral is not OPEN", 409)
        r["status"] = "ACKNOWLEDGED"
        touch(r)
    return success_object(serialize_referral(r), 200)


@app.route(f"{PREFIX}/referral-orders/<referralId>/complete", methods=["POST"])
def complete_referral(referralId):
    require_roles(["CareCoordinator"])
    r = get_referral(referralId)
    enc = store.encounters.get(r["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    with store.lock:
        if r["status"] != "ACKNOWLEDGED":
            raise ApiError(ERR_INVALID_STATE, "Referral is not ACKNOWLEDGED", 409)
        r["status"] = "COMPLETED"
        touch(r)
    return success_object(serialize_referral(r), 200)


@app.route(f"{PREFIX}/referral-orders/<referralId>/withdraw", methods=["POST"])
def withdraw_referral(referralId):
    require_roles(["CareCoordinator"])
    r = get_referral(referralId)
    enc = store.encounters.get(r["encounter_id"])
    if enc is not None:
        check_privacy_hold(enc["patient_id"])
    with store.lock:
        if r["status"] not in ("OPEN", "ACKNOWLEDGED"):
            raise ApiError(ERR_INVALID_STATE, "Referral is not OPEN or ACKNOWLEDGED", 409)
        r["status"] = "WITHDRAWN"
        touch(r)
    return success_object(serialize_referral(r), 200)


# ---------------------------------------------------------------------------
# Grant reports
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/affiliates/<affiliateId>/grant-reports", methods=["POST"])
def create_grant_report(affiliateId):
    require_roles(["GrantAdministrator"])
    a = get_affiliate(affiliateId)
    require_affiliate_active(a)
    body = require_body()
    period_start_s = req_str(body, "period_start")
    period_end_s = req_str(body, "period_end")
    period_start = parse_ts(period_start_s, "period_start")
    period_end = parse_ts(period_end_s, "period_end")
    valuation_variant = req_enum(body, "valuation_variant", {"FIFO", "WEIGHTED_AVERAGE"})
    amendment_of = body.get("amendment_of")
    expected_version = req_field(body, "expected_affiliate_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_affiliate_version must be an integer", 400)
    if expected_version != a["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_affiliate_version does not match the affiliate's current version",
            412,
        )
    if period_end <= period_start:
        raise ApiError(
            ERR_INVALID_INTERVAL,
            "period_end must be strictly after period_start",
            400,
        )
    amended = None
    if amendment_of is not None:
        amended = get_report(amendment_of)
        if amended["status"] != "FINALIZED":
            raise ApiError(
                ERR_INVALID_STATE,
                "amendment_of must reference a FINALIZED report",
                409,
            )
    with store.lock:
        for rep in store.grant_reports.values():
            if rep["affiliate_id"] != a["id"] or rep["status"] != "DRAFT":
                continue
            rs = parse_ts(rep["period_start"], "period_start")
            re_ = parse_ts(rep["period_end"], "period_end")
            if rs < period_end and period_start < re_:
                raise ApiError(
                    ERR_REPORT_PERIOD_OVERLAP,
                    "Another DRAFT report on this affiliate overlaps the requested half-open period",
                    409,
                )
        aggregates = compute_report_aggregates(a, period_start, period_end, valuation_variant)
        r = base_entity()
        r.update({
            "affiliate_id": a["id"],
            "period_start": period_start_s,
            "period_end": period_end_s,
            "valuation_variant": valuation_variant,
            "amendment_of": amendment_of,
            "status": "DRAFT",
        })
        r.update(aggregates)
        store.grant_reports[r["id"]] = r
        if amended is not None:
            amended["status"] = "SUPERSEDED"
            touch(amended)
        touch(a)
    return success_object(serialize_grant_report(r), 201)


@app.route(f"{PREFIX}/affiliates/<affiliateId>/grant-reports", methods=["GET"])
def list_grant_reports(affiliateId):
    require_roles(["GrantAdministrator", "PrivacyOfficer"])
    a = get_affiliate(affiliateId)
    items = [r for r in store.grant_reports.values() if r["affiliate_id"] == a["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_grant_report(r) for r in slice_], limit, offset, total)


@app.route(f"{PREFIX}/grant-reports/<reportId>", methods=["GET"])
def get_grant_report_route(reportId):
    require_roles(["GrantAdministrator", "PrivacyOfficer"])
    r = get_report(reportId)
    return success_object(serialize_grant_report(r), 200)


@app.route(f"{PREFIX}/grant-reports/<reportId>/amendments", methods=["GET"])
def list_report_amendments(reportId):
    require_roles(["GrantAdministrator", "PrivacyOfficer"])
    r = get_report(reportId)
    items = [x for x in store.grant_reports.values() if x.get("amendment_of") == r["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_grant_report(x) for x in slice_], limit, offset, total)


@app.route(f"{PREFIX}/grant-reports/<reportId>/finalize", methods=["POST"])
def finalize_grant_report(reportId):
    require_roles(["GrantAdministrator"])
    r = get_report(reportId)
    with store.lock:
        if r["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, "Report is not DRAFT", 409)
        if logical_now() < parse_ts(r["period_end"], "period_end"):
            raise ApiError(
                ERR_REPORT_PERIOD_OPEN,
                "Finalize attempted before period_end (logical clock)",
                409,
            )
        r["status"] = "FINALIZED"
        touch(r)
    return success_object(serialize_grant_report(r), 200)


# ---------------------------------------------------------------------------
# Privacy holds
# ---------------------------------------------------------------------------

@app.route(f"{PREFIX}/patients/<patientId>/privacy-holds", methods=["POST"])
def create_privacy_hold(patientId):
    require_roles(["PrivacyOfficer"])
    p = get_patient(patientId)
    body = require_body()
    hold_start_s = req_str(body, "hold_start")
    hold_end_s = req_str(body, "hold_end")
    hold_start = parse_ts(hold_start_s, "hold_start")
    hold_end = parse_ts(hold_end_s, "hold_end")
    scope = req_enum(body, "scope", {"RECORD_VIEW", "BILLING_CORRESPONDENCE", "ALL"})
    authorized = req_field(body, "authorized_staff_ids")
    if not isinstance(authorized, list) or any(not isinstance(x, str) for x in authorized):
        raise ApiError(ERR_INVALID_REQUEST, "authorized_staff_ids must be an array of strings", 400)
    if hold_end <= hold_start:
        raise ApiError(ERR_INVALID_INTERVAL, "hold_end must be strictly after hold_start", 400)
    with store.lock:
        # Priority 10: same-patient, same-scope ACTIVE half-open overlap
        for h in store.privacy_holds.values():
            if h["patient_id"] != p["id"] or h["status"] != "ACTIVE" or h["scope"] != scope:
                continue
            hs = parse_ts(h["hold_start"], "hold_start")
            he = parse_ts(h["hold_end"], "hold_end")
            if hs < hold_end and hold_start < he:
                raise ApiError(
                    ERR_PRIVACY_HOLD_OVERLAP,
                    "Same-patient, same-scope ACTIVE hold overlaps the requested half-open interval",
                    409,
                )
        h = base_entity()
        h.update({
            "patient_id": p["id"],
            "hold_start": hold_start_s,
            "hold_end": hold_end_s,
            "scope": scope,
            "authorized_staff_ids": authorized,
            "status": "ACTIVE",
        })
        store.privacy_holds[h["id"]] = h
    return success_object(serialize_privacy_hold(h), 201)


@app.route(f"{PREFIX}/patients/<patientId>/privacy-holds", methods=["GET"])
def list_privacy_holds(patientId):
    require_roles(["GrantAdministrator", "PrivacyOfficer"])
    p = get_patient(patientId)
    items = [h for h in store.privacy_holds.values() if h["patient_id"] == p["id"]]
    slice_, limit, offset, total = page(items)
    return success_list([serialize_privacy_hold(h) for h in slice_], limit, offset, total)


@app.route(f"{PREFIX}/privacy-holds/<holdId>", methods=["GET"])
def get_privacy_hold_route(holdId):
    require_roles(["GrantAdministrator", "PrivacyOfficer"])
    h = get_hold(holdId)
    return success_object(serialize_privacy_hold(h), 200)


@app.route(f"{PREFIX}/privacy-holds/<holdId>/release", methods=["POST"])
def release_privacy_hold(holdId):
    require_roles(["PrivacyOfficer"])
    h = get_hold(holdId)
    with store.lock:
        if h["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Hold is not ACTIVE", 409)
        h["status"] = "RELEASED"
        touch(h)
    return success_object(serialize_privacy_hold(h), 200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
