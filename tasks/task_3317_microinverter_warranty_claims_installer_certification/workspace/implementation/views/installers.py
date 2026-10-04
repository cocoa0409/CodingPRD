"""Installer routes: registration, certification lifecycle, level changes,
and the portfolio read (PRD 3.1)."""

import db
from approval import as_enum, as_str, body, required
from auth import (
    ROLE_PLATFORM_ADMIN,
    get_installer,
    require,
)
from errors import fail
from respond import ok, paginate
from services import common



def create_installer():
    data = body()
    installer_code = as_str(data, "installer_code")
    company_name = as_str(data, "company_name")
    contact_email = as_str(data, "contact_email", required_=False)

    for existing in db.DB.installers.values():
        if existing.get("installer_code") == installer_code:
            fail("ERR_INVALID_REQUEST_BODY", "installer_code must be unique")

    installer = {
        "id": common.new_id(),
        "created_at": common.now_iso(),
        "updated_at": common.now_iso(),
        "version": 1,
        "installer_code": installer_code,
        "company_name": company_name,
        "contact_email": contact_email,
        "certification_level": "CERTIFIED",
        "certification_status": "PENDING",
        "certified_until": None,
        "design_tool_enabled": False,
        "commissioning_enabled": False,
        "active_system_count": 0,
        "claim_approval_rate_pct": 100.00,
        "labor_approved_cents_total": 0,
        "labor_reversed_cents_total": 0,
        "labor_paid_cents_total": 0,
    }
    db.DB.installers[installer["id"]] = installer
    common.recompute_installer(installer)
    return ok(common.lazy_installer(installer), 201)


def read_installer(installer_id):
    installer = get_installer(installer_id)
    return ok(common.lazy_installer(installer))


def activate_installer(installer_id):
    installer = get_installer(installer_id)
    common.lazy_installer(installer)
    if installer.get("certification_status") != "PENDING":
        fail("ERR_INVALID_STATE", "only a PENDING installer can be activated")
    common.set_many(installer, {
        "certification_status": "ACTIVE",
        "certified_until": common.iso(
            common.add_months(common.now(), common.CERT_TERM_MONTHS)),
    })
    common.recompute_installer(installer)
    return ok(installer)


def suspend_installer(installer_id):
    installer = get_installer(installer_id)
    common.lazy_installer(installer)
    if installer.get("certification_status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "only an ACTIVE installer can be suspended")
    common.set_many(installer, {
        "certification_status": "SUSPENDED",
        "design_tool_enabled": False,
        "commissioning_enabled": False,
    })
    common.recompute_installer(installer)
    return ok(installer)


def reinstate_installer(installer_id):
    installer = get_installer(installer_id)
    common.lazy_installer(installer)
    if installer.get("certification_status") != "SUSPENDED":
        fail("ERR_INVALID_STATE", "only a SUSPENDED installer can be reinstated")
    mid_flight = [c for c in db.claims_of_installer(installer["id"])
                  if c.get("status") in ("SUBMITTED", "DIAGNOSED")]
    if mid_flight:
        fail("ERR_INVALID_STATE",
             "the installer has claims in SUBMITTED or DIAGNOSED status")
    common.set_many(installer, {
        "certification_status": "ACTIVE",
        "certified_until": common.iso(
            common.add_months(common.now(), common.CERT_TERM_MONTHS)),
    })
    common.recompute_installer(installer)
    return ok(installer)


def set_installer_level():
    """POST /warranty/installer-levels -- one rung at a time (PRD 3.1)."""
    data = body()
    installer_id = as_str(data, "installer_id")
    level = as_enum(data, "level", common.LEVELS)
    installer = get_installer(installer_id)
    common.lazy_installer(installer)

    current = installer.get("certification_level")
    current_index = common.LEVELS.index(current) if current in common.LEVELS else -1
    target_index = common.LEVELS.index(level)
    if target_index != current_index + 1:
        fail("ERR_LEVEL_UP_NOT_ELIGIBLE",
             "the requested level must be exactly one step above the current level")

    values = {"certification_level": level}
    if installer.get("certification_status") == "EXPIRED":
        values["certification_status"] = "ACTIVE"
        values["certified_until"] = common.iso(
            common.add_months(common.now(), common.CERT_TERM_MONTHS))
    common.set_many(installer, values)
    common.recompute_installer(installer)
    return ok(installer)


def read_portfolio(installer_id):
    """Portfolio read with the informational fleet-wide and flat projections."""
    installer = get_installer(installer_id)
    common.lazy_installer(installer)

    fleet_ratio = portfolio_fleet_ratio(installer["id"])
    flat_fee = portfolio_flat_metering_fee(installer["id"])

    return ok({
        "installer_id": installer["id"],
        "certification_level": installer.get("certification_level"),
        "certification_status": installer.get("certification_status"),
        "design_tool_enabled": installer.get("design_tool_enabled"),
        "commissioning_enabled": installer.get("commissioning_enabled"),
        "active_system_count": installer.get("active_system_count"),
        "fleet_wide_ratio": fleet_ratio,
        "claim_approval_rate_pct": installer.get("claim_approval_rate_pct"),
        "labor_approved_cents_total": installer.get("labor_approved_cents_total"),
        "labor_reversed_cents_total": installer.get("labor_reversed_cents_total"),
        "labor_paid_cents_total": installer.get("labor_paid_cents_total"),
        "flat_metering_fee_cents": flat_fee,
    })


def portfolio_fleet_ratio(installer_id):
    """The same numerator as the system ratio, divided by active_system_count."""
    count = common.active_system_count(installer_id)
    if count == 0:
        return 0.0
    numerator = 0
    for system in db.DB.systems.values():
        if system.get("installer_id") != installer_id:
            continue
        numerator += common.coverage_figures(system).get("installed_in_base_count", 0)
    return common.ratio4(common.dec(numerator) / common.dec(count))


def portfolio_flat_metering_fee(installer_id):
    """The flat projection: the age-adjusted unit rate charged once per system."""
    total = 0
    for system in db.DB.systems.values():
        if system.get("installer_id") != installer_id:
            continue
        age_months = common.system_age_months(system, common.now())
        age_factor = common.age_factor_for_months(age_months)
        total += common.money(common.dec(common.METERING_BASE_RATE_CENTS) * age_factor)
    return total


def register(app):
    app.add_url_rule("/warranty/installers", "create_installer",
                     require(ROLE_PLATFORM_ADMIN)(create_installer), methods=["POST"])
    app.add_url_rule("/warranty/installers/<installer_id>", "read_installer",
                     require(ROLE_PLATFORM_ADMIN, "Installer")(read_installer), methods=["GET"])
    app.add_url_rule("/warranty/installers/<installer_id>/activate", "activate_installer",
                     require(ROLE_PLATFORM_ADMIN)(activate_installer), methods=["POST"])
    app.add_url_rule("/warranty/installers/<installer_id>/suspend", "suspend_installer",
                     require(ROLE_PLATFORM_ADMIN)(suspend_installer), methods=["POST"])
    app.add_url_rule("/warranty/installers/<installer_id>/reinstate", "reinstate_installer",
                     require(ROLE_PLATFORM_ADMIN)(reinstate_installer), methods=["POST"])
    app.add_url_rule("/warranty/installers/<installer_id>/portfolio", "read_portfolio",
                     require(ROLE_PLATFORM_ADMIN, "Installer")(read_portfolio), methods=["GET"])
    app.add_url_rule("/warranty/installer-levels", "set_installer_level",
                     require(ROLE_PLATFORM_ADMIN)(set_installer_level), methods=["POST"])