"""Installer accounts, premises and the logical-clock capability."""

from flask import Blueprint

import shape
import store
from common import (
    CERT_LEVELS,
    CERT_STATUSES,
    MODEL_CODES,
    PANEL_AMPS,
    TERRITORIES,
    kw,
)
from envelope import created, ok
from errors import invalid
from security import guard, path_ref

bp = Blueprint("core", __name__)


# --------------------------------------------------------------------------- #
# InstallerAccount
# --------------------------------------------------------------------------- #

@bp.route("/installers", methods=["POST"])
@guard("ManufacturerWarrantyAgent")
def create_installer(actor):
    payload = shape.body()
    company_name = payload.str_("company_name", max_len=120)
    level = payload.enum(
        "certification_level", CERT_LEVELS, required=False, default="CERTIFIED"
    )
    models = payload.str_list("certified_model_codes", values=MODEL_CODES)
    expires_on = payload.iso("certification_expires_on")
    if not models and level != "NONE":
        raise invalid(
            "'certified_model_codes' may only be empty for a NONE certification level."
        )
    record = store.insert(
        "installers",
        {
            "company_name": company_name,
            "certification_level": level,
            "certified_model_codes": models,
            "certification_expires_on": expires_on,
            "certification_status": "ACTIVE",
            "clawback_count": 0,
            "late_warranty_registration_count": 0,
            "commissioned_system_count": 0,
        },
    )
    return created(store.view(record))


@bp.route("/installers/<installer_id>", methods=["GET"])
@guard(
    "ManufacturerWarrantyAgent",
    "CertifiedInstaller",
    "RebateAdministrator",
    "UtilityInterconnectionReviewer",
    "AuthorityHavingJurisdiction",
)
def read_installer(actor, installer_id):
    record = path_ref(actor, "installer", installer_id)
    return ok(store.view(record))


@bp.route("/installers/<installer_id>/certification", methods=["POST"])
@guard("ManufacturerWarrantyAgent")
def amend_certification(actor, installer_id):
    record = path_ref(actor, "installer", installer_id)
    payload = shape.body()
    level = payload.enum("certification_level", CERT_LEVELS, required=False)
    models = payload.str_list("certified_model_codes", required=False, values=MODEL_CODES)
    expires_on = payload.iso("certification_expires_on", required=False)
    status = payload.enum("certification_status", CERT_STATUSES, required=False)
    if level is not None:
        record["certification_level"] = level
    if models is not None:
        record["certified_model_codes"] = models
    if expires_on is not None:
        record["certification_expires_on"] = expires_on
    if status is not None:
        record["certification_status"] = status
    store.touch(record)
    return ok(store.view(record))


# --------------------------------------------------------------------------- #
# Site
# --------------------------------------------------------------------------- #

@bp.route("/sites", methods=["POST"])
@guard("CertifiedInstaller")
def create_site(actor):
    payload = shape.body()
    homeowner_name = payload.str_("homeowner_name")
    territory = payload.enum("utility_territory_code", TERRITORIES)
    panel_amps = payload.integer("service_panel_amps", choices=PANEL_AMPS)
    floor_area = payload.number("floor_area_sqft", exclusive_min=True)
    postal_code = payload.str_("postal_code")
    if len(postal_code.strip()) != 5 or not postal_code.strip().isdigit():
        raise invalid("'postal_code' must be five digits.")
    existing_pv = payload.number("existing_pv_kw_dc", required=False, default=0)
    record = store.insert(
        "sites",
        {
            "homeowner_name": homeowner_name,
            "utility_territory_code": territory,
            "service_panel_amps": panel_amps,
            "floor_area_sqft": floor_area,
            "postal_code": postal_code.strip(),
            "existing_pv_kw_dc": kw(existing_pv),
        },
    )
    return created(store.view(record))


@bp.route("/sites/<site_id>", methods=["GET"])
@guard(
    "CertifiedInstaller",
    "Homeowner",
    "AuthorityHavingJurisdiction",
    "UtilityInterconnectionReviewer",
    "RebateAdministrator",
)
def read_site(actor, site_id):
    record = path_ref(actor, "site", site_id)
    return ok(store.view(record))


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #

@bp.route("/_clock/set_current_utc", methods=["POST"])
@guard(
    "ManufacturerWarrantyAgent",
    "CertifiedInstaller",
    "Homeowner",
    "AuthorityHavingJurisdiction",
    "UtilityInterconnectionReviewer",
    "RebateAdministrator",
)
def set_clock(actor):
    payload = shape.body()
    moment = payload.iso("to_iso8601")
    store.set_clock(moment)
    return ok({})
