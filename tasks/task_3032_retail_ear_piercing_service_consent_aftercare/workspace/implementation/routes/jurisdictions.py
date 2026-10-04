"""Jurisdiction, store and piercer routes (PRD 2.4, 2.7, 2.10, 3.9)."""

import re

from flask import Blueprint, request

import db
import errors as E
import response as R
from middleware import authenticated
from services import common
from services import certifications as cert_svc

bp = Blueprint("jurisdictions", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
US_ROLE = dict(roles=["ComplianceOfficer"])
ANY = dict(roles=["AnyAuthenticated"])


# =============================================================================
# Jurisdictions
# =============================================================================
@bp.route("/jurisdictions", methods=["POST"])
@authenticated("ComplianceOfficer")
def create_jurisdiction():
    data = common.body()
    state_code = common.require_str(data, "state_code")
    if not STATE_CODE_RE.match(state_code):
        E.fail(E.ERR_INVALID_REQUEST,
               "state_code must be exactly two uppercase letters")
    for existing in db.DB.jurisdictions.values():
        if existing.state_code == state_code:
            E.fail(E.ERR_INVALID_REQUEST, "state_code must be unique")

    permitted_sites = common.validated_list(data, "permitted_sites", db.ALLOWED_SITES)
    jurisdiction = db.Jurisdiction()
    jurisdiction.state_code = state_code
    jurisdiction.min_age_self_consent = common.require_int(data, "min_age_self_consent")
    jurisdiction.min_age_with_guardian = common.require_int(data, "min_age_with_guardian")
    jurisdiction.min_age_absolute = common.require_int(data, "min_age_absolute")
    jurisdiction.permitted_sites = permitted_sites
    jurisdiction.requires_guardian_presence = common.require_bool(
        data, "requires_guardian_presence")
    jurisdiction.record_retention_years = common.require_int(data, "record_retention_years")
    jurisdiction.consent_form_version = common.require_str(data, "consent_form_version")
    jurisdiction.sterilization_protocol_code = common.require_str(
        data, "sterilization_protocol_code")
    jurisdiction.status = "ACTIVE"
    db.DB.jurisdictions[jurisdiction.id] = jurisdiction
    return R.object_response(jurisdiction, 201)


@bp.route("/jurisdictions", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_jurisdictions():
    limit, offset = common.pagination_params()
    rows = common.sorted_rows(db.DB.jurisdictions.values())
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/jurisdictions/<jurisdiction_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_jurisdiction(jurisdiction_id):
    return R.object_response(common.get_jurisdiction(jurisdiction_id))


@bp.route("/jurisdictions/<jurisdiction_id>/stores", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_jurisdiction_stores(jurisdiction_id):
    common.get_jurisdiction(jurisdiction_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows([s for s in db.DB.stores.values()
                               if s.jurisdiction_id == jurisdiction_id])
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/jurisdictions/<jurisdiction_id>/consents", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_jurisdiction_consents(jurisdiction_id):
    common.get_jurisdiction(jurisdiction_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows([c for c in db.DB.consents.values()
                               if c.jurisdiction_id == jurisdiction_id])
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/jurisdictions/<jurisdiction_id>/supersede", methods=["POST"])
@authenticated("ComplianceOfficer")
def supersede_jurisdiction(jurisdiction_id):
    jurisdiction = common.get_jurisdiction(jurisdiction_id)
    data = common.body()
    common.require_str(data, "successor_state_code")
    if jurisdiction.status == "SUPERSEDED":
        E.fail(E.ERR_INVALID_STATE, "Jurisdiction is already SUPERSEDED")
    jurisdiction.status = "SUPERSEDED"
    jurisdiction.touch()
    return R.object_response(jurisdiction)


# =============================================================================
# Stores
# =============================================================================
@bp.route("/stores", methods=["POST"])
@authenticated("ComplianceOfficer")
def create_store():
    data = common.body()
    jurisdiction = common.get_jurisdiction(common.require_str(data, "jurisdiction_id"))
    store = db.StoreLocation()
    store.name = common.require_str(data, "name")
    store.jurisdiction_id = jurisdiction.id
    store.piercing_room_count = common.require_int(data, "piercing_room_count")
    store.compliance_posture = "OPEN"
    store.open_incident_count = 0
    store.status = "OPEN"
    db.DB.stores[store.id] = store
    return R.object_response(store, 201)


@bp.route("/stores", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_stores():
    limit, offset = common.pagination_params()
    rows = list(db.DB.stores.values())
    requested = request.args.get("jurisdiction_id")
    if requested:
        rows = [s for s in rows if s.jurisdiction_id == requested]
    rows = common.sorted_rows(rows)
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/stores/<store_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_store(store_id):
    return R.object_response(common.get_store(store_id))


@bp.route("/stores/<store_id>/posture", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_store_posture(store_id):
    store = common.get_store(store_id)
    common.refresh_store_posture_read(store)
    return R.success({
        "compliance_posture": store.compliance_posture,
        "open_incident_count": store.open_incident_count,
    }, "object", 200)


@bp.route("/stores/<store_id>/incidents", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_store_incidents(store_id):
    common.get_store(store_id)
    limit, offset = common.pagination_params()
    from calculations import store_incident_rows
    rows = common.sorted_rows(store_incident_rows(db.DB, store_id))
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/stores/<store_id>/piercers", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_store_piercers(store_id):
    common.get_store(store_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows([p for p in db.DB.piercers.values()
                               if p.home_store_id == store_id])
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/stores/<store_id>/cartridge-lots", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_store_lots(store_id):
    common.get_store(store_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows([l for l in db.DB.lots.values()
                               if l.store_location_id == store_id])
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/stores/<store_id>/sterilization-cycles", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_store_cycles(store_id):
    common.get_store(store_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows([c for c in db.DB.cycles.values()
                               if c.store_location_id == store_id])
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/stores/<store_id>/appointments", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_store_appointments(store_id):
    common.get_store(store_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows(common.appointments_at_store(store_id))
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/stores/<store_id>/posture/freeze", methods=["POST"])
@authenticated("ComplianceOfficer")
def freeze_store(store_id):
    store = common.get_store(store_id)
    # Freezing is entered from a posture that is OPEN or RESTRICTED, and the
    # posture is itself a derived value: reconcile it before deciding (PRD 2.7),
    # so a freeze is refused only for a genuinely frozen store.
    common.refresh_store_posture_read(store)
    if store.compliance_posture not in ("OPEN", "RESTRICTED"):
        E.fail(E.ERR_INVALID_STATE, "Store posture is FROZEN")
    if store.status not in ("OPEN", "RESTRICTED"):
        E.fail(E.ERR_INVALID_STATE, "Store status does not permit freezing")
    store.compliance_posture = "FROZEN"
    store.touch()
    common.cancel_booking_rows([a for a in common.appointments_at_store(store.id)
                                if a.status in ("BOOKED", "CONFIRMED")])
    return R.object_response(store)


@bp.route("/stores/<store_id>/posture/unfreeze", methods=["POST"])
@authenticated("ComplianceOfficer")
def unfreeze_store(store_id):
    store = common.get_store(store_id)
    if store.compliance_posture != "FROZEN":
        E.fail(E.ERR_INVALID_STATE, "Store posture is not FROZEN")
    store.compliance_posture = "RESTRICTED"
    store.touch()
    return R.object_response(store)


@bp.route("/stores/<store_id>/posture/clear", methods=["POST"])
@authenticated("ComplianceOfficer")
def clear_store_posture(store_id):
    store = common.get_store(store_id)
    if store.compliance_posture != "RESTRICTED":
        E.fail(E.ERR_INVALID_STATE, "Store posture is not RESTRICTED")
    common.refresh_store_posture_read(store)
    if store.open_incident_count != 0:
        E.fail(E.ERR_INVALID_STATE,
               "open_incident_count must be 0 before a store can be cleared")
    blocking = [c for c in db.DB.cycles.values()
                if c.store_location_id == store.id
                and c.status in ("IN_PROGRESS", "FAILED", "QUARANTINED")]
    if blocking:
        E.fail(E.ERR_INVALID_STATE,
               "No bound sterilization cycle may be IN_PROGRESS, FAILED or QUARANTINED")
    store.compliance_posture = "OPEN"
    store.touch()
    return R.object_response(store)


@bp.route("/stores/<store_id>/close", methods=["POST"])
@authenticated("ComplianceOfficer")
def close_store(store_id):
    store = common.get_store(store_id)
    blocking = [a for a in common.appointments_at_store(store.id)
                if a.status in ("CHECKED_IN", "SCREENED", "IN_SERVICE")]
    if blocking:
        E.fail(E.ERR_INVALID_STATE,
               "No appointment may be CHECKED_IN, SCREENED or IN_SERVICE")
    store.status = "CLOSED"
    store.touch()
    common.cancel_booking_rows([a for a in common.appointments_at_store(store.id)
                                if a.status in ("BOOKED", "CONFIRMED")])
    for piercer in db.DB.piercers.values():
        if piercer.home_store_id == store.id and piercer.status == "ACTIVE":
            piercer.status = "SUSPENDED"
            piercer.touch()
    return R.object_response(store)


# =============================================================================
# Piercers
# =============================================================================
@bp.route("/piercers", methods=["POST"])
@authenticated("StoreManager")
def create_piercer():
    data = common.body()
    home_store = common.get_store(common.require_str(data, "home_store_id"))
    piercer = db.Piercer()
    piercer.full_name = common.require_str(data, "full_name")
    piercer.home_store_id = home_store.id
    piercer.eligibility_score = 100
    piercer.assigned_session_count = 0
    piercer.status = "ACTIVE"
    db.DB.piercers[piercer.id] = piercer
    return R.object_response(piercer, 201)


@bp.route("/piercers", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_piercers():
    limit, offset = common.pagination_params()
    rows = list(db.DB.piercers.values())
    requested = request.args.get("home_store_id")
    if requested:
        rows = [p for p in rows if p.home_store_id == requested]
    rows = common.sorted_rows(rows)
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/piercers/<piercer_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_piercer(piercer_id):
    return R.object_response(common.get_piercer(piercer_id))


@bp.route("/piercers/<piercer_id>/eligibility-audit", methods=["GET"])
@authenticated("AnyAuthenticated")
def piercer_eligibility_audit(piercer_id):
    piercer = common.get_piercer(piercer_id)
    cumulative = cert_svc.cumulative_score(piercer.id)
    return R.success({
        "eligibility_score": piercer.eligibility_score,
        "cumulative_score": cumulative,
    }, "object", 200)


@bp.route("/piercers/<piercer_id>/certifications", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_piercer_certifications(piercer_id):
    common.get_piercer(piercer_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows([c for c in db.DB.certifications.values()
                               if c.piercer_id == piercer_id])
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/piercers/<piercer_id>/reinstate", methods=["POST"])
@authenticated("StoreManager")
def reinstate_piercer(piercer_id):
    piercer = common.get_piercer(piercer_id)
    if piercer.status != "SUSPENDED":
        E.fail(E.ERR_INVALID_STATE, "Piercer is not SUSPENDED")
    if piercer.eligibility_score < 60:
        E.fail(E.ERR_INVALID_STATE, "eligibility_score must be at least 60")
    qualifying = [c for c in db.DB.certifications.values()
                  if c.piercer_id == piercer.id
                  and c.certification_level in ("STANDARD", "SENIOR", "INSTRUCTOR")
                  and c.status == "VALID"]
    if not qualifying:
        E.fail(E.ERR_INVALID_STATE,
               "At least one STANDARD-or-higher VALID certification is required")
    piercer.status = "ACTIVE"
    piercer.touch()
    return R.object_response(piercer)


@bp.route("/piercers/<piercer_id>/deactivate", methods=["POST"])
@authenticated("StoreManager")
def deactivate_piercer(piercer_id):
    piercer = common.get_piercer(piercer_id)
    if piercer.status not in ("ACTIVE", "SUSPENDED"):
        E.fail(E.ERR_INVALID_STATE, "Piercer is not ACTIVE or SUSPENDED")
    if piercer.assigned_session_count != 0:
        E.fail(E.ERR_INVALID_STATE, "assigned_session_count must be 0")
    piercer.status = "INACTIVE"
    piercer.touch()
    for cert in db.DB.certifications.values():
        if cert.piercer_id == piercer.id and cert.status in ("VALID", "EXPIRING_SOON"):
            cert.status = "REVOKED"
            cert.touch()
    common.recompute_piercer_governing_state(piercer)
    return R.object_response(piercer)