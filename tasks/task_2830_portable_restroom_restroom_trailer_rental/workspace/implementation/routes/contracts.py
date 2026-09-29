"""RentalContract endpoints: creation, the two quote variants, the fulfillment
dimension and the billing dimension."""
from flask import Blueprint, g

from auth import ALL_ROLES, endpoint
import calculations as calc
import constants as C
from db import db, insert, ordered, serialize, touch
from errors import fail
from responses import created, ok
from routes.common import list_response, resolve
import services
import validation as V

bp = Blueprint("contracts", __name__)


@bp.post("/rental-contracts")
@endpoint(["SalesRep", "CustomerContact"])
def create_contract():
    body = V.body()
    account_id = V.str_field(body, "account_id", 1)
    site_id = V.str_field(body, "site_id", 1)
    contract_kind = V.enum_field(body, "contract_kind", C.CONTRACT_KINDS)
    term_start = V.date_field(body, "term_start")
    term_end = V.date_field(body, "term_end")
    V.ordering(term_start, term_end, "term_start", "term_end")
    headcount = V.int_field(body, "headcount", 1, 20000)
    event_duration_hours = V.int_field(body, "event_duration_hours", 1, 24)
    service_frequency_per_week = V.int_field(body, "service_frequency_per_week", 1, 7)
    season_code = V.enum_field(body, "season_code", C.SEASON_CODES)
    construction_phase = V.enum_field(body, "construction_phase",
                                      C.CONSTRUCTION_PHASES)
    ada_required = V.bool_field(body, "ada_required", required=False, default=False)
    if contract_kind == "EVENT" and construction_phase != "EVENT_NA":
        V.bad("An EVENT contract must declare construction_phase EVENT_NA.")

    account = resolve("rental_accounts", account_id)
    site = resolve("service_sites", site_id)

    if g.role == "CustomerContact" and account["id"] != g.user_id:
        fail("ERR_ACCOUNT_SCOPE_VIOLATION")

    contract = insert("rental_contracts", {
        "account_id": account["id"],
        "site_id": site["id"],
        "contract_kind": contract_kind,
        "term_start": term_start,
        "term_end": term_end,
        "headcount": headcount,
        "event_duration_hours": event_duration_hours,
        "ada_required": ada_required,
        "service_frequency_per_week": service_frequency_per_week,
        "season_code": season_code,
        "construction_phase": construction_phase,
        "fulfillment_state": "DRAFT",
        "billing_state": "UNBILLED",
        "quoted_cents": 0,
        "reconciled_cents": 0,
        "invoice_subtotal_cents": 0,
        "charge_debits_cents": 0,
        "credit_accrued_cents": 0,
        "net_billable_cents": 0,
    })
    return created(serialize(contract))


@bp.get("/rental-contracts/<contract_id>")
@endpoint(ALL_ROLES)
def read_contract(contract_id):
    return ok(serialize(resolve("rental_contracts", contract_id)))


@bp.get("/rental-contracts")
@endpoint(ALL_ROLES)
def list_contracts():
    limit, offset = V.pagination()
    account_id = V.q_str("account_id")
    site_id = V.q_str("site_id")
    fulfillment_state = V.q_enum("fulfillment_state", C.FULFILLMENT_STATES)
    billing_state = V.q_enum("billing_state", C.BILLING_STATES)
    rows = ordered(db.rental_contracts.values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if site_id is not None:
        rows = [r for r in rows if r["site_id"] == site_id]
    if fulfillment_state is not None:
        rows = [r for r in rows if r["fulfillment_state"] == fulfillment_state]
    if billing_state is not None:
        rows = [r for r in rows if r["billing_state"] == billing_state]
    return list_response(rows, limit, offset)


@bp.get("/rental-contracts/<contract_id>/quote-lines")
@endpoint(ALL_ROLES)
def list_quote_lines(contract_id):
    limit, offset = V.pagination()
    quote_variant = V.q_enum("quote_variant", C.QUOTE_VARIANTS)
    is_superseded = V.q_bool("is_superseded")
    contract = resolve("rental_contracts", contract_id)
    rows = services.quote_lines_of_contract(contract["id"])
    if quote_variant is not None:
        rows = [r for r in rows if r["quote_variant"] == quote_variant]
    if is_superseded is not None:
        rows = [r for r in rows if r["is_superseded"] == is_superseded]
    return list_response(rows, limit, offset)


# ------------------------------------------------------------ fulfillment dim

@bp.post("/rental-contracts/<contract_id>/quote")
@endpoint(["SalesRep"])
def quote_contract(contract_id):
    body = V.body()
    expected_version = V.int_field(body, "expected_contract_version", 0)
    V.str_field(body, "quote_note", 1, None, required=False)
    contract = resolve("rental_contracts", contract_id)

    if expected_version != contract["version"]:
        fail("ERR_STALE_CONTRACT_VERSION")
    if contract["fulfillment_state"] not in ("DRAFT", "QUOTED"):
        fail("ERR_INVALID_STATE_TRANSITION")

    pairs = calc.provisional_mix(contract)
    if not pairs:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The projection produced no priced line.")

    services.supersede_lines(contract["id"], variant="PROVISIONAL")
    total = services.create_quote_lines(contract, pairs, "PROVISIONAL")
    contract["fulfillment_state"] = "QUOTED"
    contract["quoted_cents"] = total
    touch(contract)
    services.recompute_net_billable(contract)
    return ok(serialize(contract))


@bp.post("/rental-contracts/<contract_id>/activate")
@endpoint(["SalesRep"])
def activate_contract(contract_id):
    V.body()
    contract = resolve("rental_contracts", contract_id)
    account = db.rental_accounts.get(contract["account_id"])
    site = db.service_sites.get(contract["site_id"])

    if contract["fulfillment_state"] != "QUOTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if account is None or account["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "The owning account is not in ACTIVE standing.")
    if site is not None and site["site_posture"] == "BLOCKED":
        fail("ERR_SITE_POSTURE_BLOCKED")
    if site is not None and site["site_posture"] == "RESTRICTED":
        fail("ERR_SITE_POSTURE_RESTRICTED")
    if account["billing_hold"]:
        fail("ERR_ACCOUNT_BILLING_HOLD")

    contract["fulfillment_state"] = "ACTIVE"
    touch(contract)
    for deployment in services.deployments_of_contract(contract["id"]):
        if deployment["state"] != "RESERVED":
            continue
        deployment["state"] = "DEPLOYED"
        touch(deployment)
        unit = db.asset_units.get(deployment["asset_unit_id"])
        if unit is not None and unit["status"] == "IN_YARD":
            unit["status"] = "DEPLOYED"
            touch(unit)
    services.recompute_deployed_unit_count(contract["site_id"])
    return ok(serialize(contract))


@bp.post("/rental-contracts/<contract_id>/demobilize")
@endpoint(["DispatchPlanner"])
def demobilize_contract(contract_id):
    body = V.body()
    V.str_field(body, "demobilization_note", 1, None, required=False)
    contract = resolve("rental_contracts", contract_id)

    if contract["fulfillment_state"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION")

    deployments = services.deployments_of_contract(contract["id"])
    reconciled = [d for d in deployments if d["state"] in ("DEPLOYED", "RETURNED")]
    if not reconciled:
        fail("ERR_RECONCILIATION_NO_DEPLOYMENTS")

    unit_classes = []
    for deployment in reconciled:
        unit = db.asset_units.get(deployment["asset_unit_id"])
        if unit is not None:
            unit_classes.append(unit["unit_class"])
    services.supersede_lines(contract["id"])
    total = services.create_quote_lines(
        contract, calc.reconciled_mix(unit_classes), "RECONCILED")
    contract["reconciled_cents"] = total
    touch(contract)
    services.recompute_net_billable(contract)

    affected_sites = []
    for deployment in deployments:
        if deployment["state"] != "DEPLOYED":
            continue
        deployment["state"] = "RETURNED"
        touch(deployment)
        unit = db.asset_units.get(deployment["asset_unit_id"])
        if unit is not None and unit["status"] == "DEPLOYED":
            unit["status"] = "IN_YARD"
            touch(unit)
        if deployment["site_id"] not in affected_sites:
            affected_sites.append(deployment["site_id"])
    for site_id in affected_sites:
        services.recompute_deployed_unit_count(site_id)

    for schedule in services.schedules_of_contract(contract["id"]):
        if schedule["state"] in ("ACTIVE", "SUSPENDED"):
            services.terminate_schedule(schedule)

    if contract["billing_state"] == "SETTLED":
        contract["fulfillment_state"] = "CLOSED"
    else:
        contract["fulfillment_state"] = "DEMOBILIZED"
    touch(contract)
    return ok(serialize(contract))


# ---------------------------------------------------------------- billing dim

@bp.post("/rental-contracts/<contract_id>/invoice")
@endpoint(["SalesRep"])
def invoice_contract(contract_id):
    V.body()
    contract = resolve("rental_contracts", contract_id)
    account = db.rental_accounts.get(contract["account_id"])

    if contract["billing_state"] not in ("UNBILLED", "REBILL_REQUIRED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    if (contract["billing_state"] == "UNBILLED"
            and contract["fulfillment_state"] not in ("ACTIVE", "DEMOBILIZED")):
        fail("ERR_INVALID_STATE_TRANSITION",
             "The contract has not been mobilized.")
    lines = services.active_quote_lines(contract["id"])
    if not lines:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The contract carries no current quote line.")
    if account is not None and account["billing_hold"]:
        fail("ERR_ACCOUNT_BILLING_HOLD")

    combined_pct = calc.combined_escalation_pct(contract)
    subtotal = 0
    for line in lines:
        escalated = calc.escalated_line_cents(line["extended_cents"], combined_pct)
        line["escalated_cents"] = escalated
        subtotal += escalated
    contract["invoice_subtotal_cents"] = subtotal
    contract["billing_state"] = "INVOICED"
    touch(contract)
    services.recompute_net_billable(contract)
    return ok(serialize(contract))


@bp.post("/rental-contracts/<contract_id>/settle-invoice")
@endpoint(["PlatformAdmin"])
def settle_contract(contract_id):
    body = V.body()
    V.str_field(body, "payment_reference", 1, None, required=False)
    contract = resolve("rental_contracts", contract_id)

    if contract["billing_state"] != "INVOICED":
        fail("ERR_INVALID_STATE_TRANSITION")

    contract["billing_state"] = "SETTLED"
    if contract["fulfillment_state"] == "DEMOBILIZED":
        contract["fulfillment_state"] = "CLOSED"
    touch(contract)
    return ok(serialize(contract))
