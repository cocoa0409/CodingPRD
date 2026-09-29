"""POST /staff-transition-offers and its status action (PRD section 3.8)."""

import calc
import clock
import enums
import machines
import services
import store
import validate
from errors import ApiError
from store import set_field

EXTEND_DEAL_STATUSES = ("DILIGENCE", "BOARD_REVIEW", "SIGNED")
RELEASING_EXITS = ("DECLINED", "RESCINDED", "EXPIRED")


def create_offer():
    validate.gate(enums.ROLES_MANAGER)
    body = validate.json_body()
    acquisition_id = validate.req_id(body, "acquisition_id")
    staff_member_name = validate.req_str(body, "staff_member_name")
    role_code = validate.req_enum(body, "role_code", enums.ROLE_CODES)
    legacy_wage = validate.req_int(body, "legacy_annual_wage_cents", minimum=0)
    pto_hours = validate.opt_int(body, "legacy_pto_hours", 0, minimum=0)
    credited_months = validate.opt_int(body, "credited_service_months", 0,
                                       minimum=0)
    offer_expires_on = validate.req_date(body, "offer_expires_on")

    acquisition = store.require("acquisitions", acquisition_id)
    services.check_freeze(acquisition)

    wage = calc.staff_offer_wage_harmonization(role_code, legacy_wage, pto_hours)
    bonus = calc.retention_bonus_award(role_code,
                                       wage["offered_annual_wage_cents"],
                                       credited_months)
    row = {
        "acquisition_id": acquisition_id,
        "staff_member_name": staff_member_name,
        "role_code": role_code,
        "legacy_annual_wage_cents": legacy_wage,
        "legacy_pto_hours": pto_hours,
        "credited_service_months": credited_months,
        "uplift_component_cents": wage["uplift_component_cents"],
        "pto_component_cents": wage["pto_component_cents"],
        "wage_floor_applied": wage["wage_floor_applied"],
        "offered_annual_wage_cents": wage["offered_annual_wage_cents"],
        "retention_bonus_cents": bonus,
        "offer_expires_on": clock.format_date(offer_expires_on),
        "extended_on": None,
        "accepted_on": None,
        "status": "DRAFT",
    }
    store.insert("staff_transition_offers", row)
    return services.respond_created(row)


def offer_status(entity_id):
    user_id, role = validate.gate(enums.ROLES_MANAGER)
    body = validate.json_body()
    target = validate.req_enum(body, "target_status",
                               machines.OFFER_STATUS_VALUES)
    validate.opt_str(body, "note")

    offer = store.require("staff_transition_offers", entity_id)
    acquisition = store.require("acquisitions", offer["acquisition_id"])
    from_state = offer["status"]
    lapsed = services.expired_on(offer["offer_expires_on"])

    # Rank 14: transition legality and the date preconditions, which carry no
    # dedicated code of their own.
    machines.resolve(machines.OFFER_STATUS, from_state, target, role)
    if target == "EXTENDED":
        if acquisition["deal_status"] not in EXTEND_DEAL_STATUSES:
            raise machines.invalid(from_state, target)
        if lapsed:
            raise machines.invalid(from_state, target)
    elif target == "ACCEPTED" and lapsed:
        raise machines.invalid(from_state, target)
    elif target == "EXPIRED" and not lapsed:
        raise machines.invalid(from_state, target)

    # Rank 15, then rank 45.
    services.check_freeze(acquisition)
    if target == "EXTENDED":
        if offer["retention_bonus_cents"] > acquisition["retention_pool_available_cents"]:
            raise ApiError(
                "ERR_RETENTION_POOL_EXCEEDED",
                "retention_pool_available_cents is %d; this offer commits %d."
                % (acquisition["retention_pool_available_cents"],
                   offer["retention_bonus_cents"]))

    set_field(offer, "status", target)

    if target == "EXTENDED":
        set_field(offer, "extended_on", clock.CLOCK.today_str())
        services.recompute_retention_pool(acquisition)
        services.recompute_hr_coverage(acquisition)
    elif target == "ACCEPTED":
        set_field(offer, "accepted_on", clock.CLOCK.today_str())
        coverage = services.recompute_hr_coverage(acquisition)
        if coverage >= calc.HR_COVERAGE_MIN_PCT:
            services.cascade_complete_task(acquisition, "HR_STAFFING_PLAN")
        services.recompute_posture(acquisition)
    elif target in RELEASING_EXITS and from_state == "EXTENDED":
        services.recompute_retention_pool(acquisition)
        services.recompute_hr_coverage(acquisition)

    return services.respond(offer)


def register(app):
    app.add_url_rule("/staff-transition-offers", "create_offer", create_offer,
                     methods=["POST"])
    app.add_url_rule("/staff-transition-offers/<entity_id>/status",
                     "offer_status", offer_status, methods=["POST"])
