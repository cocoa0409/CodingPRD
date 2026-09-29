"""POST /compensation-plans and its status action (PRD section 3.4)."""

import calc
import clock
import enums
import machines
import services
import store
import validate
from errors import ApiError
from store import set_field

EXECUTION_DEAL_STATUSES = ("BOARD_REVIEW", "SIGNED", "CLOSED")


def create_plan():
    user_id, role = validate.gate(enums.ROLES_DESIGNER)
    body = validate.json_body()
    acquisition_id = validate.req_id(body, "acquisition_id")
    expected_version = validate.req_int(body, "expected_acquisition_version",
                                        minimum=0)
    physician_id = validate.req_id(body, "physician_id")
    model_type = validate.req_enum(body, "model_type", enums.MODEL_TYPES)
    base_salary = validate.opt_int(body, "base_salary_cents", 0, minimum=0)
    factor = validate.opt_int(body, "conversion_factor_cents_per_wrvu", 0,
                              minimum=0)
    threshold = validate.opt_int(body, "threshold_wrvu", 0, minimum=0)
    projected_wrvu = validate.opt_int(body, "projected_annual_wrvu", 0,
                                      minimum=0)
    includes_referral = validate.opt_bool(body, "includes_referral_credit",
                                          False)
    stark = validate.req_enum(body, "stark_exception", enums.STARK_EXCEPTIONS)
    fmv_justification = validate.opt_bool(body, "fmv_justification_on_file",
                                          False)

    # Rank 5, then rank 6, then rank 13, then rank 15.
    acquisition = store.require("acquisitions", acquisition_id)
    physician = store.require("physicians", physician_id)
    if physician["acquisition_id"] != acquisition_id:
        raise services.scope_mismatch(
            "Physician '%s' does not belong to acquisition '%s'."
            % (physician_id, acquisition_id))
    services.check_occ(acquisition, expected_version)
    services.check_freeze(acquisition)

    total = calc.projected_total_cash_comp(model_type, base_salary, factor,
                                          threshold, projected_wrvu)
    per_wrvu = calc.comp_per_wrvu(total, projected_wrvu)
    basis = calc.benchmark_basis_for(model_type)
    compared = per_wrvu if basis == "COMP_PER_WRVU" else total
    percentile = calc.compensation_benchmark_percentile(
        compared, basis, physician["specialty"])

    row = {
        "acquisition_id": acquisition_id,
        "physician_id": physician_id,
        "model_type": model_type,
        "base_salary_cents": base_salary,
        "conversion_factor_cents_per_wrvu": factor,
        "threshold_wrvu": threshold,
        "projected_annual_wrvu": projected_wrvu,
        "includes_referral_credit": includes_referral,
        "stark_exception": stark,
        "fmv_justification_on_file": fmv_justification,
        "projected_total_cash_comp_cents": total,
        "comp_per_wrvu_cents": per_wrvu,
        "benchmark_basis": basis,
        "benchmark_percentile": percentile,
        "actual_ytd_wrvu": 0,
        "months_elapsed": 0,
        "comp_true_up_cents": 0,
        "returned_count": 0,
        "status": "DRAFT",
        "approved_by_user_id": None,
        "executed_at": None,
    }
    store.insert("compensation_plans", row)
    store.mark(acquisition)
    return services.respond_created(row)


def _safe_harbour(plan):
    """Rank 19: above the ninetieth percentile a written justification is needed."""
    if (plan["benchmark_percentile"] > calc.FMV_SAFE_HARBOR_PERCENTILE
            and not plan["fmv_justification_on_file"]):
        raise ApiError(
            "ERR_COMP_EXCEEDS_FMV_SAFE_HARBOR",
            "benchmark_percentile %s exceeds the 90.00 safe harbour and no "
            "fair market value justification is on file."
            % plan["benchmark_percentile"],
        )


def plan_status(entity_id):
    user_id, role = validate.gate(enums.ROLES_PLAN_ACTION)
    body = validate.json_body()
    target = validate.req_enum(body, "target_status",
                               machines.PLAN_STATUS_VALUES)
    validate.opt_str(body, "review_note")

    plan = store.require("compensation_plans", entity_id)
    acquisition = store.require("acquisitions", plan["acquisition_id"])
    physician = store.get("physicians", plan["physician_id"])
    from_state = plan["status"]

    # Rank 12: only the physician the plan addresses may execute it.
    if target == "EXECUTED" and from_state == "APPROVED":
        if user_id != plan["physician_id"]:
            raise ApiError("ERR_NOT_PLAN_OWNER",
                           "Only the physician named on this plan may execute it.")

    # Rank 14: transition legality plus the preconditions with no dedicated code.
    landing = machines.resolve(machines.PLAN_STATUS, from_state, target, role)
    if target == "EXECUTED" and from_state == "APPROVED":
        if acquisition["deal_status"] not in EXECUTION_DEAL_STATUSES:
            raise machines.invalid(from_state, target)

    # This endpoint is exempt from the compliance-clearance freeze.

    pinned = services.pinned_fmv_opinion(acquisition)

    # Rank 16: segregation of duties against the accepted valuation.
    if target == "APPROVED" and pinned is not None:
        if user_id == pinned["accepted_by_user_id"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The officer who accepted the pinned valuation may not approve "
                "compensation benchmarked against it.")

    if target == "SUBMITTED":
        # Rank 17, then rank 18, then rank 20.
        if plan["includes_referral_credit"]:
            raise ApiError("ERR_REFERRAL_LINKED_COMPENSATION",
                           "Compensation may not vary with referral volume or value.")
        if plan["stark_exception"] == "NONE":
            raise ApiError("ERR_STARK_EXCEPTION_REQUIRED",
                           "A referral-prohibition exception must be named.")
        if physician is not None and services.expired_on(
                physician["state_license_expires_on"]):
            raise ApiError("ERR_PHYSICIAN_LICENSE_EXPIRED",
                           "The physician's licence expired on %s."
                           % physician["state_license_expires_on"])

    # Rank 19: the fair market value safe harbour.
    if target in ("APPROVED", "EXECUTED"):
        _safe_harbour(plan)

    # Rank 30: the governing valuation must not be stale.
    if target == "APPROVED" and pinned is not None:
        if services.expired_on(pinned["expires_on"]):
            raise ApiError("ERR_VALUATION_OPINION_EXPIRED",
                           "The pinned valuation expired on %s."
                           % pinned["expires_on"])

    # Rank 36: a pinned accepted fair market value opinion must exist.
    if target == "APPROVED" and pinned is None:
        raise ApiError("ERR_FMV_OPINION_NOT_ACCEPTED",
                       "No pinned accepted FMV opinion exists on this acquisition.")

    _apply_plan_transition(plan, acquisition, physician, from_state, target,
                           landing, user_id)
    return services.respond(plan)


def _apply_plan_transition(plan, acquisition, physician, from_state, target,
                           landing, user_id):
    if from_state == "SUBMITTED" and target == "DRAFT":
        # The bounded revision cycle branches on the plan's own allowance.
        services.apply_plan_return(plan)
        return

    set_field(plan, "status", target)

    if target == "APPROVED":
        # Supersede first, so the recomputed employment_status reads OFFERED.
        for peer in store.ordered(store.where("compensation_plans",
                                              physician_id=plan["physician_id"])):
            if peer["id"] != plan["id"] and peer["status"] == "EXECUTED":
                set_field(peer, "status", "SUPERSEDED")
        set_field(plan, "approved_by_user_id", user_id)
    elif target == "EXECUTED" and from_state == "APPROVED":
        set_field(plan, "executed_at", clock.CLOCK.instant_str())
    elif target == "COMPLIANCE_HOLD":
        if acquisition["compliance_clearance"] == "CLEARED":
            services.flag_clearance(acquisition)

    if physician is not None:
        services.recompute_employment_status(physician)


def register(app):
    app.add_url_rule("/compensation-plans", "create_plan", create_plan,
                     methods=["POST"])
    app.add_url_rule("/compensation-plans/<entity_id>/status", "plan_status",
                     plan_status, methods=["POST"])
