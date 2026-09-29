"""POST /credentialing-packages and its status action (PRD section 3.6)."""

import calc
import clock
import enums
import machines
import services
import store
import validate
from errors import ApiError
from store import set_field

LIVE_PACKAGE_STATES = ("DRAFT", "SUBMITTED", "IN_REVIEW", "APPROVED")
SEATED_STATES = ("SUBMITTED", "IN_REVIEW", "APPROVED")
FILEABLE_NOVATION = ("NOTICE_SENT", "CONSENT_RECEIVED",
                     "NEW_AGREEMENT_PENDING", "NOVATED")
CLOSED_PACKAGE_STATES = ("APPROVED", "DENIED", "WITHDRAWN")


def create_package():
    validate.gate(enums.ROLES_MANAGER)
    body = validate.json_body()
    acquisition_id = validate.req_id(body, "acquisition_id")
    physician_id = validate.req_id(body, "physician_id")
    contract_id = validate.req_id(body, "payer_contract_id")
    submitted_on = validate.req_date(body, "submitted_on")

    # Rank 5: every foreign key resolves.
    acquisition = store.require("acquisitions", acquisition_id)
    physician = store.require("physicians", physician_id)
    contract = store.require("payer_contracts", contract_id)

    # Rank 6: all three references belong to the same acquisition.
    if physician["acquisition_id"] != acquisition_id:
        raise services.scope_mismatch(
            "Physician '%s' does not belong to acquisition '%s'."
            % (physician_id, acquisition_id))
    if contract["acquisition_id"] != acquisition_id:
        raise services.scope_mismatch(
            "PayerContract '%s' does not belong to acquisition '%s'."
            % (contract_id, acquisition_id))

    # Rank 10: at most one live package per provider per payer.
    for peer in store.where("credentialing_packages",
                            physician_id=physician_id,
                            payer_contract_id=contract_id):
        if peer["status"] in LIVE_PACKAGE_STATES:
            raise ApiError(
                "ERR_DUPLICATE_CREDENTIALING_PACKAGE",
                "A live credentialing package already exists for this provider "
                "and payer.")

    # Rank 15: the compliance-clearance freeze.
    services.check_freeze(acquisition)

    lead_days = calc.credentialing_lead_days(contract["payer_type"])
    row = {
        "acquisition_id": acquisition_id,
        "physician_id": physician_id,
        "payer_contract_id": contract_id,
        "submitted_on": clock.format_date(submitted_on),
        "lead_days": lead_days,
        "committee_cycle_key": clock.format_date(
            calc.committee_cycle_key(submitted_on)),
        "projected_effective_on": clock.format_date(
            calc.credentialing_projected_effective_date(submitted_on, lead_days)),
        "retro_billing_allowed": calc.retro_billing_allowed(
            contract["payer_type"]),
        "status": "DRAFT",
    }
    store.insert("credentialing_packages", row)
    return services.respond_created(row)


def package_status(entity_id):
    user_id, role = validate.gate(enums.ROLES_MANAGER)
    body = validate.json_body()
    target = validate.req_enum(body, "target_status",
                               machines.PACKAGE_STATUS_VALUES)
    validate.opt_str(body, "note")

    package = store.require("credentialing_packages", entity_id)
    acquisition = store.require("acquisitions", package["acquisition_id"])
    contract = store.require("payer_contracts", package["payer_contract_id"])
    physician = store.get("physicians", package["physician_id"])
    from_state = package["status"]

    # Rank 14, then rank 15.
    machines.resolve(machines.PACKAGE_STATUS, from_state, target, role)
    if target == "SUBMITTED":
        if contract["novation_status"] not in FILEABLE_NOVATION:
            raise machines.invalid(from_state, target)
    services.check_freeze(acquisition)

    if target == "SUBMITTED":
        _filing_gates(package, acquisition, contract, physician)

    set_field(package, "status", target)

    if target == "APPROVED":
        packages = store.where("credentialing_packages",
                               acquisition_id=acquisition["id"])
        if all(p["status"] in CLOSED_PACKAGE_STATES for p in packages):
            services.cascade_complete_task(acquisition, "PAYER_CREDENTIALING")
        services.recompute_posture(acquisition)

    return services.respond(package)


def _filing_gates(package, acquisition, contract, physician):
    # Rank 20, then rank 32, then rank 33.
    if physician is not None and services.expired_on(
            physician["state_license_expires_on"]):
        raise ApiError("ERR_PHYSICIAN_LICENSE_EXPIRED",
                       "The physician's licence expired on %s."
                       % physician["state_license_expires_on"])

    seated = 0
    for peer in store.where("credentialing_packages",
                            payer_contract_id=contract["id"],
                            committee_cycle_key=package["committee_cycle_key"]):
        if peer["id"] != package["id"] and peer["status"] in SEATED_STATES:
            seated += 1
    if seated >= contract["committee_slots_per_cycle"]:
        raise ApiError(
            "ERR_COMMITTEE_CYCLE_CAPACITY_EXCEEDED",
            "Committee cycle %s already seats %d of %d packages."
            % (package["committee_cycle_key"], seated,
               contract["committee_slots_per_cycle"]))

    window = calc.RETRO_BILLING_WINDOW_DAYS[contract["payer_type"]]
    limit = calc.add_days(clock.parse_date(acquisition["target_close_on"]),
                          window)
    if clock.parse_date(package["projected_effective_on"]) > limit:
        raise ApiError(
            "ERR_CREDENTIALING_LEAD_TIME_MISSED",
            "projected_effective_on %s falls after %s."
            % (package["projected_effective_on"], clock.format_date(limit)))


def register(app):
    app.add_url_rule("/credentialing-packages", "create_package",
                     create_package, methods=["POST"])
    app.add_url_rule("/credentialing-packages/<entity_id>/status",
                     "package_status", package_status, methods=["POST"])
