"""Monthly service periods, certification and the movement of cash."""

from decimal import Decimal

from flask import Blueprint, request

import auth
import calc
import cascades
import errors
import lookups
import response
import serializers
import validation as v
from auth import (CARRIER, COMMUNITY_REPRESENTATIVE, PROGRAM_ADMIN,
                  SELECTION_OFFICER, endpoint)
from db import (base_row, dec, month_add, month_index, month_of, now_iso, q2,
                store, touch)

bp = Blueprint("periods", __name__)

REPORTABLE_AGREEMENT_STATUSES = ("ACTIVE", "HOLD_IN")
PAYMENT_ACTIONS = ("APPROVE", "DISBURSE", "REVERSE")
REVERSAL_REASON_CODES = ("AUDIT_FINDING", "REPORTING_ERROR", "OVERPAYMENT")

REPORT_FIELDS = ("scheduled_departures", "completed_departures",
                 "cancelled_carrier_departures", "cancelled_weather_departures",
                 "seats_offered", "passengers_enplaned")

CUMULATIVE_BY_FIELD = {
    "scheduled_departures": "cumulative_scheduled_departures",
    "completed_departures": "cumulative_completed_departures",
    "cancelled_carrier_departures": "cumulative_cancelled_carrier_departures",
    "cancelled_weather_departures": "cumulative_cancelled_weather_departures",
}


# =========================================================================
# opening a month (PRD 3.6)
# =========================================================================
@bp.route("/service-periods", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def create_period():
    data = v.body()
    agreement_id = v.id_field(data, "agreement_id")
    period_month = v.month_field(data, "period_month")
    agreement = lookups.agreement(agreement_id)

    existing = lookups.periods_of_agreement(agreement["id"])
    if existing:
        greatest = max(p["period_month"] for p in existing)
        expected = month_add(greatest, 1)
    else:
        expected = month_of(v.parse_stamp(agreement["rate_effective_from"]))

    # A month the agreement already has is a duplicate, not a sequence gap
    # (PRD 3.6): the sequencing rule only governs months not yet recorded.
    for row in existing:
        if row["period_month"] == period_month:
            errors.fail(errors.ERR_DUPLICATE_PERIOD,
                        "Month %s is already open on this agreement." % period_month)

    if period_month != expected:
        errors.fail(errors.ERR_PERIOD_SEQUENCE_GAP,
                    "The next reportable month for this agreement is %s." % expected)

    period = base_row(True)
    period.update({
        "agreement_id": agreement["id"],
        "period_month": period_month,
        "scheduled_departures": 0,
        "completed_departures": 0,
        "cancelled_carrier_departures": 0,
        "cancelled_weather_departures": 0,
        "seats_offered": 0,
        "passengers_enplaned": 0,
        "period_completion_factor": None,
        "status": "OPEN",
        "amendment_count": 0,
    })
    store.periods[period["id"]] = period
    return response.created(serializers.period(period))


@bp.route("/service-periods/<pid>", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE, CARRIER)
def read_period(pid):
    return response.ok(serializers.period(lookups.period(pid)))


@bp.route("/service-periods", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE, CARRIER)
def list_periods():
    rows = list(store.periods.values())
    for field in ("agreement_id", "status", "period_month"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows.sort(key=lambda r: (r["period_month"], r["_seq"]))
    return response.paginate(rows, serializers.period)


# =========================================================================
# the monthly operating report and its amendments (PRD 3.6)
# =========================================================================
def _read_counts(data):
    counts = {}
    for field in REPORT_FIELDS:
        counts[field] = v.int_field(data, field, minimum=0)
    return counts


def _reconcile(counts):
    """Rung 23 then rung 28 of the ladder."""
    total = (counts["completed_departures"]
             + counts["cancelled_carrier_departures"]
             + counts["cancelled_weather_departures"])
    if (total != counts["scheduled_departures"]
            or counts["passengers_enplaned"] > counts["seats_offered"]):
        errors.fail(errors.ERR_DEPARTURE_COUNTS_UNBALANCED,
                    "Completed plus cancelled departures must equal the scheduled "
                    "departures, and passengers may not exceed seats offered.")
    if counts["scheduled_departures"] < 1:
        errors.fail(errors.ERR_NO_SCHEDULED_DEPARTURES,
                    "The month must have had at least one scheduled departure.")
    return calc.q4_completion(counts["completed_departures"],
                              counts["scheduled_departures"])


@bp.route("/service-periods/<pid>/report", methods=["POST"])
@endpoint(CARRIER)
def report_period(pid):
    data = v.body()
    counts = _read_counts(data)
    period = lookups.period(pid)
    agreement = lookups.agreement(period["agreement_id"])

    auth.require_owner(agreement["carrier_id"])

    if period["status"] != "OPEN":
        errors.fail(errors.ERR_PERIOD_NOT_REPORTABLE,
                    "A period in status %s accepts no report." % period["status"])
    if agreement["status"] not in REPORTABLE_AGREEMENT_STATUSES:
        errors.fail(errors.ERR_AGREEMENT_NOT_ACTIVE,
                    "An agreement in status %s has no service to report."
                    % agreement["status"])

    factor = _reconcile(counts)

    for field in REPORT_FIELDS:
        period[field] = counts[field]
    period["period_completion_factor"] = factor
    period["status"] = "REPORTED"
    touch(period)

    for field, cumulative in CUMULATIVE_BY_FIELD.items():
        agreement[cumulative] = agreement[cumulative] + counts[field]
    touch(agreement)

    return response.ok(serializers.period(period))


@bp.route("/service-periods/<pid>/amend", methods=["POST"])
@endpoint(CARRIER)
def amend_period(pid):
    data = v.body()
    expected_version = v.int_field(data, "expected_agreement_version", minimum=0)
    counts = _read_counts(data)
    period = lookups.period(pid)
    agreement = lookups.agreement(period["agreement_id"])

    auth.require_owner(agreement["carrier_id"])

    if period["status"] != "REPORTED":
        errors.fail(errors.ERR_PERIOD_NOT_AMENDABLE,
                    "A period in status %s may not be amended." % period["status"])
    if expected_version != agreement["version"]:
        errors.fail(errors.ERR_STALE_VERSION,
                    "The agreement has moved on to version %d." % agreement["version"])

    factor = _reconcile(counts)

    for field, cumulative in CUMULATIVE_BY_FIELD.items():
        agreement[cumulative] = agreement[cumulative] - period[field] + counts[field]
    touch(agreement)

    for field in REPORT_FIELDS:
        period[field] = counts[field]
    period["period_completion_factor"] = factor
    period["amendment_count"] = period["amendment_count"] + 1
    touch(period)

    return response.ok(serializers.period(period))


# =========================================================================
# the dual-variant payment preview (PRD 3.7) -- persists nothing
# =========================================================================
@bp.route("/service-periods/<pid>/payment-preview", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, CARRIER)
def payment_preview(pid):
    period = lookups.period(pid)
    agreement = lookups.agreement(period["agreement_id"])
    annual = agreement["annual_subsidy_usd"]

    proration = calc.payment_amounts(annual, period, "COMPLETED_FLIGHT_PRORATION")
    flat = calc.payment_amounts(annual, period, "SCHEDULED_FLIGHT_FLAT")

    payload = {
        "completed_flight_proration_net_usd": proration["net_payment_usd"],
        "scheduled_flight_flat_net_usd": flat["net_payment_usd"],
        "variant_in_effect": agreement["payment_basis"],
        "divergence_usd": q2(abs(proration["net_payment_usd"]
                                - flat["net_payment_usd"])),
        "per_departure_rate_usd": proration["per_departure_rate_usd"],
        "credited_departures": proration["credited_departures"],
    }
    return response.ok(payload)


# =========================================================================
# certification and the subsidy payment (PRD 3.7)
# =========================================================================
@bp.route("/service-periods/<pid>/certify", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def certify_period(pid):
    data = v.body(required=False)
    v.str_field(data, "certification_note", required=False, min_len=0, max_len=2000)
    period = lookups.period(pid)
    agreement = lookups.agreement(period["agreement_id"])

    if period["status"] != "REPORTED":
        errors.fail(errors.ERR_PERIOD_NOT_CERTIFIABLE,
                    "A period in status %s may not be certified." % period["status"])
    this_month = month_index(period["period_month"])
    for other in lookups.periods_of_agreement(agreement["id"]):
        if (other["status"] == "OPEN"
                and month_index(other["period_month"]) < this_month):
            errors.fail(errors.ERR_PERIOD_NOT_CERTIFIABLE,
                        "Month %s is still open and must be settled first."
                        % other["period_month"])

    variant = agreement["payment_basis"]
    figures = calc.payment_amounts(agreement["annual_subsidy_usd"], period, variant)

    if figures["cancellation_adjustment_usd"] > figures["adjustment_cap_usd"]:
        errors.fail(errors.ERR_ADJUSTMENT_EXCEEDS_CAP,
                    "The cancellation adjustment exceeds 25 percent of the monthly "
                    "entitlement.")

    required = q2(figures["monthly_entitlement_usd"]
                  - figures["cancellation_adjustment_usd"])
    if required > dec(agreement["obligated_remaining_usd"]):
        errors.fail(errors.ERR_OBLIGATION_EXCEEDED,
                    "Certifying this month would overrun the agreement's remaining "
                    "obligation.")

    net = figures["net_payment_usd"]
    if agreement["status"] == "HOLD_IN":
        premium, total = calc.hold_in_premium(net)
    else:
        premium, total = Decimal("0.00"), q2(net)

    payment = base_row(True)
    payment.update({
        "service_period_id": period["id"],
        "variant_used": variant,
        "monthly_entitlement_usd": figures["monthly_entitlement_usd"],
        "per_departure_rate_usd": figures["per_departure_rate_usd"],
        "credited_departures": figures["credited_departures"],
        "gross_subsidy_usd": figures["gross_subsidy_usd"],
        "cancellation_adjustment_usd": figures["cancellation_adjustment_usd"],
        "withholding_pct": figures["withholding_pct"],
        "performance_withholding_usd": figures["performance_withholding_usd"],
        "net_payment_usd": net,
        "hold_in_premium_usd": premium,
        "total_disbursement_usd": total,
        "status": "COMPUTED",
        "approved_by_user_id": None,
        "disbursed_by_user_id": None,
        "reversal_reason_code": None,
    })
    store.payments[payment["id"]] = payment

    period["status"] = "CERTIFIED"
    touch(period)

    # Certification drives the period state machine, so the mutated period is
    # what comes back at 200 (PRD section 4); the payment it created is read
    # back through the subsidy-payment endpoints.
    return response.ok(serializers.period(period))


# =========================================================================
# subsidy payments (PRD 3.7)
# =========================================================================
@bp.route("/subsidy-payments/<pid>", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE, CARRIER)
def read_payment(pid):
    return response.ok(serializers.payment(lookups.payment(pid)))


@bp.route("/subsidy-payments", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, CARRIER)
def list_payments():
    rows = list(store.payments.values())
    for field in ("service_period_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return response.paginate(rows, serializers.payment)


@bp.route("/subsidy-payments/<pid>/actions", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def payment_actions(pid):
    data = v.body()
    action = v.enum_field(data, "action", PAYMENT_ACTIONS)
    reason_code = v.enum_field(data, "reversal_reason_code", REVERSAL_REASON_CODES,
                               required=(action == "REVERSE"))
    payment = lookups.payment(pid)
    period = lookups.period(payment["service_period_id"])
    agreement = lookups.agreement(period["agreement_id"])

    if action == "APPROVE":
        if payment["status"] != "COMPUTED" or period["status"] != "CERTIFIED":
            errors.fail(errors.ERR_PAYMENT_NOT_APPROVABLE,
                        "Only a COMPUTED payment on a CERTIFIED period may be "
                        "approved.")
        payment["status"] = "APPROVED"
        payment["approved_by_user_id"] = auth.user_id()
        touch(payment)
        return response.ok(serializers.payment(payment))

    if action == "DISBURSE":
        if payment["status"] != "APPROVED":
            errors.fail(errors.ERR_PAYMENT_NOT_DISBURSABLE,
                        "A payment in status %s may not be disbursed."
                        % payment["status"])
        if payment.get("approved_by_user_id") == auth.user_id():
            errors.fail(errors.ERR_SEGREGATION_OF_DUTIES,
                        "The operator who approved this payment may not release "
                        "its cash.")
        if dec(payment["net_payment_usd"]) > dec(agreement["obligated_remaining_usd"]):
            errors.fail(errors.ERR_OBLIGATION_EXCEEDED,
                        "The net payment exceeds the agreement's remaining "
                        "obligation.")
        payment["status"] = "DISBURSED"
        payment["disbursed_by_user_id"] = auth.user_id()
        touch(payment)

        agreement["disbursed_to_date_usd"] = q2(
            dec(agreement["disbursed_to_date_usd"]) + dec(payment["net_payment_usd"]))
        agreement["hold_in_premium_paid_usd"] = q2(
            dec(agreement["hold_in_premium_paid_usd"])
            + dec(payment["hold_in_premium_usd"]))
        cascades.recompute_obligation(agreement)
        touch(agreement)

        period["status"] = "PAID"
        touch(period)
        return response.ok(serializers.payment(payment))

    # --- REVERSE -----------------------------------------------------------
    if payment["status"] not in ("APPROVED", "DISBURSED"):
        errors.fail(errors.ERR_PAYMENT_NOT_REVERSIBLE,
                    "A payment in status %s may not be reversed." % payment["status"])

    was_disbursed = payment["status"] == "DISBURSED"
    payment["status"] = "REVERSED"
    payment["reversal_reason_code"] = reason_code
    touch(payment)

    if was_disbursed:
        agreement["disbursed_to_date_usd"] = q2(
            dec(agreement["disbursed_to_date_usd"]) - dec(payment["net_payment_usd"]))
        agreement["hold_in_premium_paid_usd"] = q2(
            dec(agreement["hold_in_premium_paid_usd"])
            - dec(payment["hold_in_premium_usd"]))
        cascades.recompute_obligation(agreement)
        touch(agreement)

    period["status"] = "REPORTED"
    touch(period)
    return response.ok(serializers.payment(payment))
