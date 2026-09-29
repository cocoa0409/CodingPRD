"""POST /valuation-opinions and its status action (PRD section 3.2)."""

import calc
import clock
import enums
import machines
import services
import store
import validate
from errors import ApiError
from store import set_field

REQUIRED_BY_METHOD = {
    "INCOME_APPROACH": ("normalized_ebitda_cents", "projection_years",
                        "ebitda_growth_bps", "discount_rate_bps",
                        "terminal_growth_bps"),
    "MARKET_APPROACH": ("normalized_ebitda_cents", "market_multiple_bps"),
    "NARRATIVE": ("cr_conclusion",),
}

METHODS_BY_TYPE = {
    "FMV": ("INCOME_APPROACH", "MARKET_APPROACH"),
    "COMMERCIAL_REASONABLENESS": ("NARRATIVE",),
}


def create_opinion():
    user_id, role = validate.gate(enums.ROLES_ANALYST)
    body = validate.json_body()
    acquisition_id = validate.req_id(body, "acquisition_id")
    expected_version = validate.req_int(body, "expected_acquisition_version",
                                        minimum=0)
    opinion_type = validate.req_enum(body, "opinion_type", enums.OPINION_TYPES)
    method = validate.req_enum(body, "method", enums.VALUATION_METHODS)
    ebitda = validate.opt_int(body, "normalized_ebitda_cents", None, minimum=0)
    years = validate.opt_int(body, "projection_years", None, minimum=1,
                             maximum=5)
    growth = validate.opt_int(body, "ebitda_growth_bps", None)
    discount = validate.opt_int(body, "discount_rate_bps", None)
    terminal = validate.opt_int(body, "terminal_growth_bps", None)
    multiple = validate.opt_int(body, "market_multiple_bps", None)
    cr_conclusion = validate.opt_enum(body, "cr_conclusion",
                                      enums.CR_CONCLUSIONS)
    independence = validate.req_bool(body, "independence_attested")
    effective_on = validate.req_date(body, "effective_on")

    # Rank 3 intra-body constraint: a Gordon-growth denominator must be positive.
    if discount is not None and terminal is not None and discount <= terminal:
        raise ApiError("ERR_INVALID_REQUEST",
                       "discount_rate_bps must be strictly greater than "
                       "terminal_growth_bps.")

    # Rank 5, then rank 13, then rank 15.
    acquisition = store.require("acquisitions", acquisition_id)
    services.check_occ(acquisition, expected_version)
    services.check_freeze(acquisition)

    # Rank 22: the chosen method's inputs are all present.
    supplied = {
        "normalized_ebitda_cents": ebitda,
        "projection_years": years,
        "ebitda_growth_bps": growth,
        "discount_rate_bps": discount,
        "terminal_growth_bps": terminal,
        "market_multiple_bps": multiple,
        "cr_conclusion": cr_conclusion,
    }
    for name in REQUIRED_BY_METHOD[method]:
        if supplied[name] is None:
            raise ApiError("ERR_MISSING_VALUATION_INPUT",
                           "Method '%s' requires '%s'." % (method, name))

    # Rank 23: the method is compatible with the opinion type.
    if method not in METHODS_BY_TYPE[opinion_type]:
        raise ApiError("ERR_OPINION_METHOD_MISMATCH",
                       "Opinion type '%s' may not use method '%s'."
                       % (opinion_type, method))

    concluded = calc.fmv_concluded_value(opinion_type, method, ebitda, years,
                                         growth, discount, terminal, multiple)
    row = {
        "acquisition_id": acquisition_id,
        "opinion_type": opinion_type,
        "method": method,
        "normalized_ebitda_cents": ebitda,
        "projection_years": years,
        "ebitda_growth_bps": growth,
        "discount_rate_bps": discount,
        "terminal_growth_bps": terminal,
        "market_multiple_bps": multiple,
        "cr_conclusion": cr_conclusion,
        "concluded_value_cents": concluded,
        "independence_attested": independence,
        "effective_on": clock.format_date(effective_on),
        "expires_on": clock.format_date(calc.opinion_expires_on(effective_on)),
        "prepared_by_user_id": user_id,
        "accepted_by_user_id": None,
        "status": "DRAFT",
        "is_pinned": False,
    }
    store.insert("valuation_opinions", row)
    # The acquisition aggregate advances on every filing.
    store.mark(acquisition)
    return services.respond_created(row)


def opinion_status(entity_id):
    user_id, role = validate.gate(enums.ROLES_OPINION_ACTION)
    body = validate.json_body()
    target = validate.req_enum(body, "target_status",
                               machines.OPINION_STATUS_VALUES)
    validate.opt_str(body, "review_note")

    opinion = store.require("valuation_opinions", entity_id)
    from_state = opinion["status"]

    # Rank 12: only the preparer may submit their own work.
    if target == "SUBMITTED" and user_id != opinion["prepared_by_user_id"]:
        raise ApiError("ERR_NOT_PLAN_OWNER",
                       "Only the preparer may submit this opinion.")

    # Rank 14: transition legality and the preconditions with no dedicated code.
    machines.resolve(machines.OPINION_STATUS, from_state, target, role)
    if target == "ACCEPTED":
        for peer in store.where("valuation_opinions",
                                acquisition_id=opinion["acquisition_id"],
                                opinion_type=opinion["opinion_type"],
                                status="ACCEPTED"):
            if peer["id"] != opinion["id"]:
                raise machines.invalid(from_state, target)
    if from_state == "ACCEPTED" and target == "SUPERSEDED" and opinion["is_pinned"]:
        raise machines.invalid(from_state, target)

    # This endpoint is not one of the sixteen frozen operations.

    # Rank 16: segregation of duties.
    if target in ("ACCEPTED", "REJECTED"):
        if user_id == opinion["prepared_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The preparer of an opinion may not %s it."
                           % ("accept" if target == "ACCEPTED" else "reject"))

    # Rank 24: independence attestation.
    if target == "SUBMITTED" and not opinion["independence_attested"]:
        raise ApiError("ERR_VALUER_INDEPENDENCE_NOT_ATTESTED",
                       "independence_attested must be true to submit an opinion.")

    # Rank 30: the opinion must not be expired at acceptance.
    if target == "ACCEPTED" and services.expired_on(opinion["expires_on"]):
        raise ApiError("ERR_VALUATION_OPINION_EXPIRED",
                       "This opinion expired on %s." % opinion["expires_on"])

    set_field(opinion, "status", target)
    if target == "ACCEPTED":
        set_field(opinion, "accepted_by_user_id", user_id)

    return services.respond(opinion)


def register(app):
    app.add_url_rule("/valuation-opinions", "create_opinion", create_opinion,
                     methods=["POST"])
    app.add_url_rule("/valuation-opinions/<entity_id>/status", "opinion_status",
                     opinion_status, methods=["POST"])
