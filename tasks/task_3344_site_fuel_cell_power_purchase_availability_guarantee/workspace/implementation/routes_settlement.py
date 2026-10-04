"""Settlement lines, the accrual ledger, allowances and transition records."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import constants as C
import middleware
import settle_calc
import store
from errors import (
    ERR_ACCRUAL_UNBALANCED, ERR_ALREADY_TERMINAL, ERR_ALLOCATION_LIMIT,
    ERR_BUMPER_EXCEEDED, ERR_GUARANTEE_FLOOR_BREACH, ERR_INVALID_STATE,
    ERR_NO_ELIGIBLE_ACCRUAL, ERR_OUT_OF_ORDER, ERR_PPA_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND, ERR_REVERSAL_WINDOW_CLOSED,
    ERR_SETTLEMENT_PERIOD_BEFORE_ACTIVATION, ERR_SETTLEMENT_PERIOD_INVALID,
    ERR_SETTLEMENT_PERIOD_OVERLAP, ERR_SITE_NOT_FOUND, ERR_STALE_VERSION, ApiError,
)
from fields import Body

bp = Blueprint("settlement", __name__)


def load_ppa(ppa_id):
    ppa = store.get_ppa(ppa_id)
    if ppa is None:
        raise ApiError(ERR_PPA_NOT_FOUND, "no contract exists with that id", 404)
    return ppa


def load_line(ppa, line_id):
    line = store.get_line(line_id)
    if line is None or line.get("ppa_id") != ppa["id"]:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "no settlement line exists for that contract", 404)
    return line


def load_accrual(accrual_id):
    accrual = store.get_accrual(accrual_id)
    if accrual is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "no accrual exists with that id", 404)
    return accrual


def load_allowance(ppa, allowance_id):
    allowance = store.get_allowance(allowance_id)
    if allowance is None or allowance.get("ppa_id") != ppa["id"]:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "no allowance exists for that contract", 404)
    return allowance


def ordinal_of(ppa, line):
    rows = store.by_created(store.ppa_lines(ppa["id"]))
    for index, other in enumerate(rows):
        if other.get("id") == line["id"]:
            return index + 1
    return len(rows)


def most_recent_applied_ordinal(ppa):
    applied = [ln for ln in store.by_created(store.ppa_lines(ppa["id"]))
               if ln.get("status") == "SETTLEMENT_APPLIED"]
    if not applied:
        return 0
    return ordinal_of(ppa, applied[-1])


def period_lines(ppa, line):
    return [ln for ln in store.ppa_lines(ppa["id"])
            if ln.get("period_start") == line.get("period_start")
            and ln.get("period_end") == line.get("period_end")]


def write_trueup(ppa, line):
    """settlement_reversal_trueup, with both counts read before any write."""
    reversed_count = sum(1 for ln in period_lines(ppa, line) if ln.get("status") == "SETTLEMENT_REVERSED")
    open_count = sum(1 for a in store.ppa_accruals(ppa["id"])
                     if a.get("lifecycle_state") == "ACCRUAL_OPEN")
    if reversed_count > open_count:
        amount = calc.r2(calc.D(line.get("net_charge_cents") or 0) * calc.D(C.TRUEUP_EXCESS_PCT))
        existing = [a for a in store.ppa_accruals(ppa["id"])
                    if a.get("accrual_type") == "TRUEUP_ACCRUAL" and a.get("lifecycle_state") == "ACCRUAL_OPEN"]
        if existing:
            target = store.by_created(existing)[-1]
            target["amount_cents"] = amount
            target["signed_amount_cents"] = amount
            store.touch(target)
        else:
            store.create(store.accruals, {
                "ppa_id": ppa["id"],
                "site_id": ppa.get("site_id"),
                "source_settlement_line_id": line["id"],
                "accrual_type": "TRUEUP_ACCRUAL",
                "amount_cents": amount,
                "lifecycle_state": "ACCRUAL_OPEN",
                "signed_amount_cents": amount,
                "applied_allowance_id": None,
                "period_anchor_iso8601": line.get("period_end"),
            })
        return amount
    return 0


def reprice_period(ppa, line):
    for sibling in period_lines(ppa, line):
        if sibling.get("id") == line["id"]:
            continue
        settle_calc.refresh_line(sibling)


# --- settlement lines --------------------------------------------------------
@bp.route("/power/ppas/<ppa_id>/settlement-lines", methods=["POST"])
def create_line(ppa_id):
    middleware.authenticate(request.headers, ("POST", "/power/ppas/{id}/settlement-lines"))
    ppa = load_ppa(ppa_id)
    body = Body(request.get_json(silent=True))
    period_start = body.req("period_start", "string")
    period_end = body.req("period_end", "string")
    metered = body.req("metered_kwh", "number")
    downtime = body.req("downtime_hours", "number")
    customer_index = body.opt("customer_index_cents_per_therm", "number")
    source_deadline = body.req("customer_source_deadline_iso8601", "string")
    hourly = body.opt("hourly_settlement", "boolean", default=False)
    expected_version = body.req("expected_ppa_version", "integer")

    if period_start and period_end:
        if store.parse_dt(period_end) <= store.parse_dt(period_start):
            raise ApiError(ERR_SETTLEMENT_PERIOD_INVALID,
                           "the period end must be after its start", 422)
        start = store.parse_dt(period_start)
        end = store.parse_dt(period_end)
        for other in store.ppa_lines(ppa["id"]):
            if other.get("status") == "SETTLEMENT_REVERSED":
                continue
            other_start = store.parse_dt(other["period_start"])
            other_end = store.parse_dt(other["period_end"])
            if start < other_end and other_start < end:
                raise ApiError(ERR_SETTLEMENT_PERIOD_OVERLAP,
                               "the period overlaps an existing line", 422)
        if start < store.parse_dt(ppa["state_entered_at"]):
            raise ApiError(ERR_SETTLEMENT_PERIOD_BEFORE_ACTIVATION,
                           "the period starts before the contract was activated", 422)
    if expected_version is not None and int(expected_version) != int(ppa.get("version") or 0):
        raise ApiError(ERR_STALE_VERSION, "the observed contract version is stale", 412)
    body.raise_if_invalid()

    line = {
        "ppa_id": ppa["id"],
        "period_start": period_start,
        "period_end": period_end,
        "metered_kwh": metered,
        "downtime_hours": downtime,
        "customer_index_cents_per_therm": customer_index,
        "customer_source_deadline_iso8601": source_deadline,
        "hourly_settlement": bool(hourly),
        "expense_hold_days": 0,
        "status": "SETTLEMENT_DRAFT",
        "customer_sourced_index_cents_per_therm": 0.0,
        "availability_credit_cents": 0,
        "cap_side_pool_cents": 0,
        "output_guarantee_credit_cents": 0,
        "resource_side_pool_cents": 0,
        "variable_energy_cents": 0,
        "fixed_purchase_cents": 0,
        "net_charge_cents": 0,
        "net_charge_allocated_cents": 0,
        "hourly_charge_cents": 0,
        "allocation_basis": "ALLOCATION_ORDER",
        "escalated_rate_cents_per_kwh": 0.0,
        "loss_component_cents": 0,
        "component_sum_cents": 0,
        "single_round_cents": 0,
        "expected_net_charge_cents": 0,
        "index_basis_cents_per_therm": 0.0,
        "expected_net_low_cents": 0,
        "expected_net_high_cents": 0,
        "target_ppa_id": None,
        "applied_at": None,
    }
    store.create(store.settlement_lines, line)
    settle_calc.refresh_line(line)
    store.touch(ppa)
    return middleware.ok(line, status=201)


@bp.route("/power/ppas/<ppa_id>/settlement-lines", methods=["GET"])
def list_lines(ppa_id):
    middleware.authenticate(request.headers, ("GET", "/power/ppas/{id}/settlement-lines"))
    ppa = load_ppa(ppa_id)
    rows = store.by_created(store.ppa_lines(ppa["id"]))
    for key in ("status", "allocation_basis"):
        wanted = request.args.get(key)
        if wanted:
            rows = [ln for ln in rows if ln.get(key) == wanted]
    page, meta = store.paginate(rows, request.args)
    for line in page:
        if line.get("status") in ("SETTLEMENT_DRAFT", "SETTLEMENT_VALIDATED"):
            settle_calc.refresh_line(line)
    return middleware.ok_list(page, meta)


@bp.route("/power/ppas/<ppa_id>/settlement-lines/<line_id>", methods=["GET"])
def get_line(ppa_id, line_id):
    middleware.authenticate(request.headers, ("GET", "/power/ppas/{id}/settlement-lines/{id}"))
    ppa = load_ppa(ppa_id)
    line = load_line(ppa, line_id)
    if line.get("status") in ("SETTLEMENT_DRAFT", "SETTLEMENT_VALIDATED"):
        settle_calc.refresh_line(line)
    return middleware.ok(line)


@bp.route("/power/ppas/<ppa_id>/settlement-lines/<line_id>/validate", methods=["POST"])
def validate_line(ppa_id, line_id):
    middleware.authenticate(
        request.headers, ("POST", "/power/ppas/{id}/settlement-lines/{id}/validate"))
    ppa = load_ppa(ppa_id)
    line = load_line(ppa, line_id)
    if line.get("status") != "SETTLEMENT_DRAFT":
        raise ApiError(ERR_INVALID_STATE, "the line is not a draft", 409)
    if ppa.get("state") not in ("PPA_ACTIVE", "PPA_SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "the contract does not admit validation", 409)
    if store.parse_dt(line["period_end"]) <= store.parse_dt(line["period_start"]):
        raise ApiError(ERR_SETTLEMENT_PERIOD_INVALID, "the period end must be after its start", 422)
    settle_calc.refresh_line(line)
    if int(line.get("cap_side_pool_cents") or 0) <= 0:
        raise ApiError(ERR_NO_ELIGIBLE_ACCRUAL, "the cap-side pool is empty", 422)
    if ordinal_of(ppa, line) <= most_recent_applied_ordinal(ppa):
        raise ApiError(ERR_OUT_OF_ORDER, "the line is not next in sequence", 422)

    line["status"] = "SETTLEMENT_VALIDATED"
    settle_calc.refresh_line(line)
    store.touch(ppa)
    return middleware.ok(line)


@bp.route("/power/ppas/<ppa_id>/settlement-lines/<line_id>/approve", methods=["POST"])
def approve_line(ppa_id, line_id):
    middleware.authenticate(
        request.headers, ("POST", "/power/ppas/{id}/settlement-lines/{id}/approve"))
    ppa = load_ppa(ppa_id)
    line = load_line(ppa, line_id)
    if line.get("status") != "SETTLEMENT_VALIDATED":
        raise ApiError(ERR_INVALID_STATE, "the line is not validated", 409)
    if ppa.get("state") != "PPA_ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "the contract is not active", 409)
    issued = [a for a in store.ppa_allowances(ppa["id"])
              if a.get("allowance_kind") == "CAPACITY_ALLOWANCE"
              and a.get("lifecycle_state") == "ALLOWANCE_ISSUED"]
    if not issued:
        raise ApiError(ERR_INVALID_STATE, "no issued capacity allowance is available", 409)
    consumed = sum(1 for ln in store.ppa_lines(ppa["id"])
                   if ln.get("status") in ("SETTLEMENT_VALIDATED", "SETTLEMENT_APPROVED",
                                           "SETTLEMENT_APPLIED"))
    if ordinal_of(ppa, line) > consumed:
        raise ApiError(ERR_ALLOCATION_LIMIT, "the allocation index is out of range", 422)

    line["status"] = "SETTLEMENT_APPROVED"
    line["cap_side_pool_cents"] = settle_calc.cap_side_pool_for(line, ppa)
    site = store.get_site(ppa["site_id"])
    line["availability_credit_cents"] = settle_calc.availability_credit_cents(line, ppa, site)
    line["output_guarantee_credit_cents"] = settle_calc.output_guarantee_credit_cents(line, ppa, site)
    settle_calc.refresh_line(line)
    line["cap_side_pool_cents"] = settle_calc.cap_side_pool_for(line, ppa)
    store.touch(ppa)
    return middleware.ok(line)


@bp.route("/power/ppas/<ppa_id>/settlement-lines/<line_id>/settle", methods=["POST"])
def settle_line(ppa_id, line_id):
    middleware.authenticate(
        request.headers, ("POST", "/power/ppas/{id}/settlement-lines/{id}/settle"))
    ppa = load_ppa(ppa_id)
    line = load_line(ppa, line_id)
    site = store.get_site(ppa["site_id"])
    if line.get("status") != "SETTLEMENT_APPROVED":
        raise ApiError(ERR_INVALID_STATE, "the line is not approved", 409)
    headroom = int(ppa.get("capacity_reserve_pre_cents") or 0) - int(ppa.get("loss_floor_cents") or 0)
    if int(ppa.get("capacity_reserve_credits_cents") or 0) > headroom:
        raise ApiError(ERR_GUARANTEE_FLOOR_BREACH, "the capacity reserve floor is breached", 422)
    ceiling = int(site.get("lifetime_customer_billable_cents") or 0) + C.SETTLEMENT_CREDIT_CAP_CENTS
    if int(line.get("net_charge_cents") or 0) - int(line.get("output_guarantee_credit_cents") or 0) > ceiling:
        raise ApiError(ERR_BUMPER_EXCEEDED, "the settlement credit ceiling is exceeded", 422)

    line["status"] = "SETTLEMENT_APPLIED"
    line["applied_at"] = store.now_iso()
    store.touch(line)

    issued = [a for a in store.by_created(store.ppa_allowances(ppa["id"]))
              if a.get("allowance_kind") == "CAPACITY_ALLOWANCE"
              and a.get("lifecycle_state") == "ALLOWANCE_ISSUED"]
    if issued:
        allowance = issued[0]
        terms = settle_calc.allowance_terms(allowance, ppa, line)
        allowance.update(terms)
        allowance["lifecycle_state"] = "ALLOWANCE_APPLIED"
        allowance["applied_direction"] = "ALLOWANCE_APPLIED_AS_TIME"
        store.touch(allowance)

    reconciled = 0
    for accrual in store.by_created(store.ppa_accruals(ppa["id"])):
        if accrual.get("lifecycle_state") != "ACCRUAL_OPEN":
            continue
        if (accrual.get("created_at") or "") <= (line.get("created_at") or ""):
            accrual["lifecycle_state"] = "ACCRUAL_RECONCILED"
            store.touch(accrual)
            reconciled += 1

    for delivery in store.site_deliveries(site["id"]):
        if delivery.get("lifecycle_state") == "DELIVERY_CONFIRMED" \
                and delivery.get("selected_ppa_id") == ppa["id"]:
            delivery["lifecycle_state"] = "DELIVERY_SETTLED"
            store.touch(delivery)

    calc.recompute_site(site)
    calc.recompute_customer(store.get_customer(ppa["customer_id"]))
    calc.recompute_ppa(ppa)
    line["cap_side_pool_cents"] = settle_calc.cap_side_pool_for(line, ppa)
    line["availability_credit_cents"] = settle_calc.availability_credit_cents(line, ppa, site)
    store.touch(ppa)
    return middleware.ok(line)


@bp.route("/power/ppas/<ppa_id>/settlement-lines/<line_id>/reverse", methods=["POST"])
def reverse_line(ppa_id, line_id):
    middleware.authenticate(
        request.headers, ("POST", "/power/ppas/{id}/settlement-lines/{id}/reverse"))
    ppa = load_ppa(ppa_id)
    line = load_line(ppa, line_id)
    site = store.get_site(ppa["site_id"])
    if line.get("status") == "SETTLEMENT_REVERSED":
        raise ApiError(ERR_ALREADY_TERMINAL, "the line is already reversed", 409)
    if line.get("status") != "SETTLEMENT_APPLIED":
        raise ApiError(ERR_INVALID_STATE, "the line is not applied", 409)
    applied_at = store.parse_dt(line["applied_at"]) if line.get("applied_at") else None
    if applied_at is None or store.clock() > applied_at + timedelta(days=C.SETTLEMENT_REVERSAL_WINDOW_DAYS):
        raise ApiError(ERR_REVERSAL_WINDOW_CLOSED, "the reversal window has closed", 409)

    reversed_count = sum(1 for ln in period_lines(ppa, line) if ln.get("status") == "SETTLEMENT_REVERSED")
    open_count = sum(1 for a in store.ppa_accruals(ppa["id"])
                     if a.get("lifecycle_state") == "ACCRUAL_OPEN")

    line["status"] = "SETTLEMENT_REVERSED"
    line["allocation_basis"] = "UNIT_INDEX"
    store.touch(line)

    for allowance in store.ppa_allowances(ppa["id"]):
        if allowance.get("lifecycle_state") == "ALLOWANCE_APPLIED" \
                and allowance.get("applied_direction") == "ALLOWANCE_APPLIED_AS_TIME":
            allowance["lifecycle_state"] = "ALLOWANCE_ISSUED"
            allowance["applied_direction"] = None
            allowance["applied_cap_cents"] = 0
            allowance["applied_days"] = 0
            allowance["applied_amount_cents"] = 0
            store.touch(allowance)
            break

    for accrual in store.by_created(store.ppa_accruals(ppa["id"])):
        if accrual.get("lifecycle_state") == "ACCRUAL_RECONCILED" \
                and (accrual.get("created_at") or "") <= (line.get("created_at") or ""):
            accrual["lifecycle_state"] = "ACCRUAL_OPEN"
            store.touch(accrual)

    ppa["lifetime_settled_cents"] = int(ppa.get("lifetime_settled_cents") or 0) \
        - int(line.get("net_charge_cents") or 0)
    ppa["committed_kwh_remaining"] = float(ppa.get("committed_kwh_remaining") or 0) \
        + float(line.get("metered_kwh") or 0)
    ppa["customer_earned_ppa_tokens"] = int(ppa.get("customer_earned_ppa_tokens") or 0) \
        + max(C.EARNED_TOKEN_PER_REVERSAL, reversed_count + 1)
    ppa["customer_spent_ppa_tokens"] = int(ppa.get("customer_spent_ppa_tokens") or 0) \
        + C.SPENT_TOKEN_PER_REVERSAL

    if reversed_count > open_count:
        amount = calc.r2(calc.D(line.get("net_charge_cents") or 0) * calc.D(C.TRUEUP_EXCESS_PCT))
        existing = [a for a in store.ppa_accruals(ppa["id"])
                    if a.get("accrual_type") == "TRUEUP_ACCRUAL"
                    and a.get("lifecycle_state") == "ACCRUAL_OPEN"]
        if existing:
            target = store.by_created(existing)[-1]
            target["amount_cents"] = amount
            target["signed_amount_cents"] = amount
            store.touch(target)
        else:
            store.create(store.accruals, {
                "ppa_id": ppa["id"],
                "site_id": ppa.get("site_id"),
                "source_settlement_line_id": line["id"],
                "accrual_type": "TRUEUP_ACCRUAL",
                "amount_cents": amount,
                "lifecycle_state": "ACCRUAL_OPEN",
                "signed_amount_cents": amount,
                "applied_allowance_id": None,
                "period_anchor_iso8601": line.get("period_end"),
            })

    reprice_period(ppa, line)
    calc.recompute_site(site)
    calc.recompute_customer(store.get_customer(ppa["customer_id"]))
    calc.recompute_ppa(ppa)
    store.touch(ppa)
    return middleware.ok(line)


# --- accruals ----------------------------------------------------------------
@bp.route("/power/ppa-accruals", methods=["POST"])
def create_accrual():
    middleware.authenticate(request.headers, ("POST", "/power/ppa-accruals"))
    body = Body(request.get_json(silent=True))
    ppa_id = body.req("ppa_id", "string")
    site_id = body.req("site_id", "string")
    source_line_id = body.opt("source_settlement_line_id", "string")
    accrual_type = body.req("accrual_type", "string", enum=C.ACCRUAL_TYPES)
    amount = body.req("amount_cents", "integer")
    anchor = body.req("period_anchor_iso8601", "string")
    body.raise_now()
    ppa = load_ppa(ppa_id)
    site = store.get_site(site_id)
    if site is None:
        raise ApiError(ERR_SITE_NOT_FOUND, "no site exists with that id", 404)
    if source_line_id:
        line = store.get_line(source_line_id)
        if line is None or line.get("ppa_id") != ppa["id"]:
            raise ApiError(ERR_REFERENCE_NOT_FOUND, "no settlement line exists for that contract", 404)
    body.raise_if_invalid()

    signed = -amount if accrual_type == "OUTPUT_GUARANTEE_ACCRUAL" else amount
    accrual = {
        "ppa_id": ppa["id"],
        "site_id": site["id"],
        "source_settlement_line_id": source_line_id,
        "accrual_type": accrual_type,
        "amount_cents": amount,
        "lifecycle_state": "ACCRUAL_OPEN",
        "signed_amount_cents": signed,
        "applied_allowance_id": None,
        "period_anchor_iso8601": anchor,
    }
    store.create(store.accruals, accrual)
    calc.recompute_ppa(ppa)
    store.touch(ppa)
    return middleware.ok(accrual, status=201)


@bp.route("/power/ppa-accruals", methods=["GET"])
def list_accruals():
    middleware.authenticate(request.headers, ("GET", "/power/ppa-accruals"))
    rows = store.by_created(list(store.accruals.values()))
    for key in ("ppa_id", "site_id", "accrual_type", "lifecycle_state",
                "source_settlement_line_id", "applied_allowance_id"):
        wanted = request.args.get(key)
        if wanted:
            rows = [a for a in rows if a.get(key) == wanted]
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)


@bp.route("/power/ppa-accruals/<accrual_id>", methods=["GET"])
def get_accrual(accrual_id):
    middleware.authenticate(request.headers, ("GET", "/power/ppa-accruals/{id}"))
    return middleware.ok(load_accrual(accrual_id))


@bp.route("/power/ppa-accruals/<accrual_id>/applied-allowances", methods=["GET"])
def list_applied_allowances(accrual_id):
    middleware.authenticate(request.headers, ("GET", "/power/ppa-accruals/{id}/applied-allowances"))
    accrual = load_accrual(accrual_id)
    rows = store.by_created([a for a in store.allowances.values()
                             if a.get("applied_to_accrual_id") == accrual["id"]])
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)


@bp.route("/power/ppas/<ppa_id>/reconcile-accruals", methods=["POST"])
def reconcile_accruals(ppa_id):
    middleware.authenticate(request.headers, ("POST", "/power/ppas/{id}/reconcile-accruals"))
    ppa = load_ppa(ppa_id)
    body = Body(request.get_json(silent=True))
    accrual_id = body.opt("accrual_id", "string")
    target = None
    if accrual_id:
        target = store.get_accrual(accrual_id)
        if target is None or target.get("ppa_id") != ppa["id"]:
            raise ApiError(ERR_REFERENCE_NOT_FOUND, "no accrual exists for that contract", 404)
    if target is None:
        open_rows = store.by_created([a for a in store.ppa_accruals(ppa["id"])
                                      if a.get("lifecycle_state") == "ACCRUAL_OPEN"])
        if not open_rows:
            raise ApiError(ERR_NO_ELIGIBLE_ACCRUAL, "no open accrual is eligible", 422)
        target = open_rows[0]
    if target.get("lifecycle_state") != "ACCRUAL_OPEN":
        raise ApiError(ERR_ALREADY_TERMINAL, "the accrual is already reconciled", 409)
    created = store.parse_dt(target["created_at"])
    if store.clock() < created + timedelta(days=C.ACCRUAL_RECONCILE_SLA_DAYS):
        raise ApiError(ERR_INVALID_STATE, "the accrual is not yet stale", 409)

    target["lifecycle_state"] = "ACCRUAL_RECONCILED"
    store.touch(target)
    site = store.get_site(ppa["site_id"])
    if site is not None:
        calc.recompute_site(site)
    customer = store.get_customer(ppa["customer_id"])
    if customer is not None:
        calc.recompute_customer(customer)
    calc.recompute_ppa(ppa)
    store.touch(ppa)
    return middleware.ok(target)


# --- allowances --------------------------------------------------------------
@bp.route("/power/ppas/<ppa_id>/allowances", methods=["POST"])
def create_allowance(ppa_id):
    middleware.authenticate(request.headers, ("POST", "/power/ppas/{id}/allowances"))
    ppa = load_ppa(ppa_id)
    body = Body(request.get_json(silent=True))
    kind = body.req("allowance_kind", "string", enum=C.ALLOWANCE_KINDS)
    amount = body.req("amount_cents", "integer")
    expected_version = body.req("expected_ppa_version", "integer")

    open_accruals = [a for a in store.ppa_accruals(ppa["id"])
                     if a.get("lifecycle_state") == "ACCRUAL_OPEN"]
    if not open_accruals:
        raise ApiError(ERR_NO_ELIGIBLE_ACCRUAL, "the ledger holds no open accrual", 422)
    if expected_version is not None and int(expected_version) != int(ppa.get("version") or 0):
        raise ApiError(ERR_STALE_VERSION, "the observed contract version is stale", 412)
    body.raise_if_invalid()

    allowance = {
        "ppa_id": ppa["id"],
        "allowance_kind": kind,
        "amount_cents": amount,
        "lifecycle_state": "ALLOWANCE_ISSUED",
        "applied_direction": None,
        "applied_cap_cents": 0,
        "applied_days": 0,
        "capped_daily_energy_cents": 0,
        "applied_amount_cents": 0,
        "daily_energy_cents": 0,
        "daily_fixed_cents": 0,
        "applied_to_accrual_id": None,
        "applied_to_ppa_id": None,
    }
    store.create(store.allowances, allowance)
    store.touch(ppa)
    return middleware.ok(allowance, status=201)


@bp.route("/power/ppas/<ppa_id>/allowances", methods=["GET"])
def list_allowances(ppa_id):
    middleware.authenticate(request.headers, ("GET", "/power/ppas/{id}/allowances"))
    ppa = load_ppa(ppa_id)
    rows = store.by_created(store.ppa_allowances(ppa["id"]))
    for key in ("allowance_kind", "lifecycle_state", "applied_to_accrual_id", "applied_to_ppa_id"):
        wanted = request.args.get(key)
        if wanted:
            rows = [a for a in rows if a.get(key) == wanted]
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)


@bp.route("/power/ppas/<ppa_id>/allowances/<allowance_id>", methods=["GET"])
def get_allowance(ppa_id, allowance_id):
    middleware.authenticate(request.headers, ("GET", "/power/ppas/{id}/allowances/{id}"))
    ppa = load_ppa(ppa_id)
    return middleware.ok(load_allowance(ppa, allowance_id))


@bp.route("/power/ppas/<ppa_id>/allowances/<allowance_id>/apply", methods=["POST"])
def apply_allowance(ppa_id, allowance_id):
    middleware.authenticate(request.headers, ("POST", "/power/ppas/{id}/allowances/{id}/apply"))
    ppa = load_ppa(ppa_id)
    allowance = load_allowance(ppa, allowance_id)
    site = store.get_site(ppa["site_id"])
    if allowance.get("lifecycle_state") == "ALLOWANCE_APPLIED":
        raise ApiError(ERR_ALREADY_TERMINAL, "the allowance is already applied", 409)

    lines = store.by_created(store.ppa_lines(ppa["id"]))
    target_line = lines[-1] if lines else None
    reversed_lines = [ln for ln in lines if ln.get("status") == "SETTLEMENT_REVERSED"]
    open_accruals = store.by_created([a for a in store.ppa_accruals(ppa["id"])
                                      if a.get("lifecycle_state") == "ACCRUAL_OPEN"])
    terms = settle_calc.allowance_terms(allowance, ppa, target_line)

    # Stop-loss: only a capacity allowance draws against the capacity reserve,
    # and the credit it lands is its applied amount (PRD 2.9).
    if allowance.get("allowance_kind") == "CAPACITY_ALLOWANCE":
        headroom = int(ppa.get("capacity_reserve_pre_cents") or 0) \
            - int(ppa.get("loss_floor_cents") or 0)
        projected = int(ppa.get("capacity_reserve_credits_cents") or 0) \
            + int(terms["applied_amount_cents"])
        if projected > headroom:
            raise ApiError(ERR_GUARANTEE_FLOOR_BREACH, "the capacity reserve floor is breached", 422)
    ceiling = int(site.get("lifetime_customer_billable_cents") or 0) + C.SETTLEMENT_CREDIT_CAP_CENTS
    if int(allowance.get("amount_cents") or 0) > ceiling:
        raise ApiError(ERR_BUMPER_EXCEEDED, "the settlement credit ceiling is exceeded", 422)

    if reversed_lines and open_accruals:
        accrual = open_accruals[0]
        projected_signed = int(accrual.get("signed_amount_cents") or 0) \
            - int(allowance.get("amount_cents") or 0)
        if projected_signed < 0 and int(accrual.get("amount_cents") or 0) > 0:
            raise ApiError(ERR_ACCRUAL_UNBALANCED, "the period would be left unbalanced", 422)
        accrual["applied_allowance_id"] = allowance["id"]
        accrual["signed_amount_cents"] = projected_signed
        store.touch(accrual)
        allowance["applied_direction"] = "ALLOWANCE_APPLIED_AS_REVERSAL"
        allowance["applied_to_accrual_id"] = accrual["id"]
        allowance["applied_to_ppa_id"] = accrual.get("ppa_id")
    else:
        allowance["applied_direction"] = "ALLOWANCE_APPLIED_AS_TIME"

    allowance.update(terms)
    allowance["lifecycle_state"] = "ALLOWANCE_APPLIED"
    store.touch(allowance)

    if allowance.get("allowance_kind") == "CAPACITY_ALLOWANCE" and site is not None:
        site["reserved_capacity_hold_count"] = int(site.get("reserved_capacity_hold_count") or 0) + 1
        calc.recompute_site(site)

    calc.recompute_ppa(ppa)
    store.touch(ppa)
    return middleware.ok(allowance)


# --- transition records ------------------------------------------------------
@bp.route("/power/ppa-transitions", methods=["GET"])
def list_transitions():
    middleware.authenticate(request.headers, ("GET", "/power/ppa-transitions"))
    rows = store.by_created(list(store.transitions.values()))
    wanted = request.args.get("to_state")
    if wanted:
        rows = [t for t in rows if t.get("to_state") == wanted]
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)


@bp.route("/power/ppa-transitions/<transition_id>", methods=["GET"])
def get_transition(transition_id):
    middleware.authenticate(request.headers, ("GET", "/power/ppa-transitions/{id}"))
    record = store.get_transition(transition_id)
    if record is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "no transition exists with that id", 404)
    return middleware.ok(record)


@bp.route("/power/ppas/<ppa_id>/transitions", methods=["GET"])
def list_ppa_transitions(ppa_id):
    middleware.authenticate(request.headers, ("GET", "/power/ppas/{id}/transitions"))
    ppa = load_ppa(ppa_id)
    rows = store.by_created(store.ppa_transitions(ppa["id"]))
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)
