"""POST /billing-conversions and its status action (PRD section 3.9)."""

import calc
import clock
import enums
import machines
import services
import store
import validate
from errors import ApiError
from store import set_field

ATTEST_DEAL_STATUSES = ("BOARD_REVIEW", "SIGNED", "CLOSED")
CONVERT_DEAL_STATUSES = ("SIGNED", "CLOSED")
NOTIFIED_STATES = ("NOTICES_ISSUED", "CONVERTED", "WITHDRAWN")


def _derive(row):
    """The three derived notification values (PRD section 3.9)."""
    row["notice_coverage_bps"] = calc.patient_notice_coverage_bps(
        row["notified_patient_count"], row["required_notice_count"])
    issued = clock.parse_date(row["notices_issued_on"])
    row["notice_lead_days"] = calc.notice_lead_days(
        issued, clock.parse_date(row["effective_on"]))
    row["provider_based_uplift_bps"] = calc.provider_based_uplift_bps(
        row["conversion_type"])


def create_conversion():
    validate.gate(enums.ROLES_MANAGER)
    body = validate.json_body()
    acquisition_id = validate.req_id(body, "acquisition_id")
    site_name = validate.req_str(body, "site_name")
    conversion_type = validate.req_enum(body, "conversion_type",
                                        enums.CONVERSION_TYPES)
    required_notice_count = validate.req_int(body, "required_notice_count",
                                             minimum=1)
    notified = validate.opt_int(body, "notified_patient_count", 0, minimum=0)
    notices_issued_on = validate.opt_date(body, "notices_issued_on")
    effective_on = validate.req_date(body, "effective_on")

    acquisition = store.require("acquisitions", acquisition_id)
    services.check_freeze(acquisition)

    row = {
        "acquisition_id": acquisition_id,
        "site_name": site_name,
        "conversion_type": conversion_type,
        "required_notice_count": required_notice_count,
        "notified_patient_count": notified,
        "notices_issued_on": (clock.format_date(notices_issued_on)
                              if notices_issued_on is not None else None),
        "effective_on": clock.format_date(effective_on),
        "notice_lead_days": None,
        "notice_coverage_bps": 0,
        "provider_based_uplift_bps": 0,
        "attested_on": None,
        "status": "NOT_STARTED",
    }
    _derive(row)
    store.insert("billing_conversions", row)
    return services.respond_created(row)


def conversion_status(entity_id):
    user_id, role = validate.gate(enums.ROLES_MANAGER)
    body = validate.json_body()
    target = validate.req_enum(body, "target_status",
                               machines.CONVERSION_STATUS_VALUES)
    validate.opt_str(body, "note")

    conversion = store.require("billing_conversions", entity_id)
    acquisition = store.require("acquisitions", conversion["acquisition_id"])
    from_state = conversion["status"]

    # Rank 14: transition legality and the preconditions with no dedicated code.
    machines.resolve(machines.CONVERSION_STATUS, from_state, target, role)
    if target == "ATTESTED":
        if acquisition["deal_status"] not in ATTEST_DEAL_STATUSES:
            raise machines.invalid(from_state, target)
    elif target == "NOTICES_ISSUED":
        if conversion["notices_issued_on"] is None:
            raise machines.invalid(from_state, target)
    elif target == "CONVERTED":
        if acquisition["deal_status"] not in CONVERT_DEAL_STATUSES:
            raise machines.invalid(from_state, target)

    # Rank 15.
    services.check_freeze(acquisition)

    _derive(conversion)

    if target == "NOTICES_ISSUED":
        # Rank 34, then rank 35.
        if conversion["notice_lead_days"] < calc.PATIENT_NOTICE_LEAD_DAYS:
            raise ApiError("ERR_PATIENT_NOTICE_LEAD_TIME_SHORT",
                           "notice_lead_days is %d; at least %d days are required."
                           % (conversion["notice_lead_days"],
                              calc.PATIENT_NOTICE_LEAD_DAYS))
        if conversion["notice_coverage_bps"] < calc.FULL_COVERAGE_BPS:
            raise ApiError("ERR_PATIENT_NOTICE_COVERAGE_INCOMPLETE",
                           "notice_coverage_bps is %d; %d is required."
                           % (conversion["notice_coverage_bps"],
                              calc.FULL_COVERAGE_BPS))
    elif target == "CONVERTED":
        # Rank 42.
        if conversion["conversion_type"] == "PROVIDER_BASED_DEPARTMENT":
            novated = [c for c in store.where("payer_contracts",
                                              acquisition_id=acquisition["id"],
                                              payer_type="MEDICARE")
                       if c["novation_status"] == "NOVATED"]
            if not novated:
                raise ApiError(
                    "ERR_PAYER_NOVATION_INCOMPLETE",
                    "A provider-based department requires a NOVATED MEDICARE "
                    "payer contract on the acquisition.")

    set_field(conversion, "status", target)

    if target == "ATTESTED":
        set_field(conversion, "attested_on", clock.CLOCK.today_str())
    elif target == "NOTICES_ISSUED":
        peers = store.where("billing_conversions",
                           acquisition_id=acquisition["id"])
        if all(p["status"] in NOTIFIED_STATES for p in peers):
            services.cascade_complete_task(acquisition, "PATIENT_NOTIFICATION")
        services.recompute_posture(acquisition)
    elif target == "WITHDRAWN" and from_state == "NOTICES_ISSUED":
        services.recompute_posture(acquisition)

    return services.respond(conversion)


def register(app):
    app.add_url_rule("/billing-conversions", "create_conversion",
                     create_conversion, methods=["POST"])
    app.add_url_rule("/billing-conversions/<entity_id>/status",
                     "conversion_status", conversion_status, methods=["POST"])
