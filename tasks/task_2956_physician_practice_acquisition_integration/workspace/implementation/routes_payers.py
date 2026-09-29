"""POST /payer-contracts and the novation action (PRD section 3.6)."""

import calc
import clock
import enums
import machines
import services
import store
import validate
from errors import ApiError
from store import set_field

LIVE_FOR_OVERLAP = ("DENIED", "TERMINATED")
NOTICE_DEAL_STATUSES = ("BOARD_REVIEW", "SIGNED")
PACKAGE_CASCADE_STATES = ("DRAFT", "SUBMITTED", "IN_REVIEW")


def create_contract():
    validate.gate(enums.ROLES_MANAGER)
    body = validate.json_body()
    acquisition_id = validate.req_id(body, "acquisition_id")
    payer_name = validate.req_str(body, "payer_name")
    payer_type = validate.req_enum(body, "payer_type", enums.PAYER_TYPES)
    contract_form = validate.req_enum(body, "contract_form",
                                      enums.CONTRACT_FORMS)
    notice_days = validate.req_int(body, "notice_days_required", minimum=0)
    effective_on = validate.req_date(body, "effective_on")
    terminates_on = validate.req_date(body, "terminates_on")
    revenue_share = validate.req_int(body, "annual_revenue_share_bps",
                                     minimum=0, maximum=10000)
    slots = validate.opt_int(body, "committee_slots_per_cycle", 2, minimum=1)

    if terminates_on < effective_on:
        raise ApiError("ERR_INVALID_REQUEST",
                       "terminates_on must be on or after effective_on.")

    # Rank 5, then rank 15, then rank 31.
    acquisition = store.require("acquisitions", acquisition_id)
    services.check_freeze(acquisition)

    for peer in store.where("payer_contracts", acquisition_id=acquisition_id,
                            payer_name=payer_name):
        if peer["novation_status"] in LIVE_FOR_OVERLAP:
            continue
        if calc.intervals_overlap(effective_on, terminates_on,
                                  clock.parse_date(peer["effective_on"]),
                                  clock.parse_date(peer["terminates_on"])):
            raise ApiError(
                "ERR_PAYER_CONTRACT_INTERVAL_OVERLAP",
                "The term overlaps a live term for payer '%s' on this acquisition."
                % payer_name)

    row = {
        "acquisition_id": acquisition_id,
        "payer_name": payer_name,
        "payer_type": payer_type,
        "contract_form": contract_form,
        "notice_days_required": notice_days,
        "effective_on": clock.format_date(effective_on),
        "terminates_on": clock.format_date(terminates_on),
        "annual_revenue_share_bps": revenue_share,
        "committee_slots_per_cycle": slots,
        "notice_sent_on": None,
        "consent_received_on": None,
        "novation_status": "NOT_REQUESTED",
    }
    store.insert("payer_contracts", row)
    return services.respond_created(row)


def contract_novation(entity_id):
    user_id, role = validate.gate(enums.ROLES_MANAGER)
    body = validate.json_body()
    action = validate.req_enum(body, "action", machines.NOVATION_ACTIONS)
    note = validate.opt_str(body, "note")

    contract = store.require("payer_contracts", entity_id)
    acquisition = store.require("acquisitions", contract["acquisition_id"])
    from_state = contract["novation_status"]

    # Rank 14: the action must be declared, and its preconditions carry no
    # dedicated code of their own.
    target = machines.resolve(machines.NOVATION, from_state, action, role)
    if action == "SEND_NOTICE":
        if acquisition["deal_status"] not in NOTICE_DEAL_STATUSES:
            raise machines.invalid(from_state, action)
    elif action == "RECORD_CONSENT":
        sent_on = clock.parse_date(contract["notice_sent_on"])
        if sent_on is None:
            raise machines.invalid(from_state, action)
        elapsed = calc.day_diff(clock.CLOCK.today(), sent_on)
        if elapsed < contract["notice_days_required"]:
            raise machines.invalid(from_state, action)
    elif action == "NOVATE":
        approved = store.where("credentialing_packages",
                               payer_contract_id=contract["id"],
                               status="APPROVED")
        if not approved:
            raise machines.invalid(from_state, action)
    elif action == "START_NEW_AGREEMENT":
        if contract["contract_form"] == "NON_ASSIGNABLE":
            raise machines.invalid(from_state, action)

    # This endpoint is not one of the sixteen frozen operations.

    set_field(contract, "novation_status", target)
    if action == "SEND_NOTICE":
        set_field(contract, "notice_sent_on", clock.CLOCK.today_str())
    elif action == "RECORD_CONSENT":
        set_field(contract, "consent_received_on", clock.CLOCK.today_str())
    elif action == "DENY":
        _cascade_denial(contract, acquisition, note)

    return services.respond(contract)


def _cascade_denial(contract, acquisition, note):
    """A payer's denial cascades in three directions (PRD section 3.6)."""
    for package in store.ordered(store.where("credentialing_packages",
                                             payer_contract_id=contract["id"])):
        if package["status"] in PACKAGE_CASCADE_STATES:
            set_field(package, "status", "WITHDRAWN")
    reason = note if note else ("Payer '%s' denied the novation."
                               % contract["payer_name"])
    services.cascade_fail_task(acquisition, "PAYER_CREDENTIALING", reason)
    services.recompute_posture(acquisition)


def register(app):
    app.add_url_rule("/payer-contracts", "create_contract", create_contract,
                     methods=["POST"])
    app.add_url_rule("/payer-contracts/<entity_id>/novation",
                     "contract_novation", contract_novation, methods=["POST"])
