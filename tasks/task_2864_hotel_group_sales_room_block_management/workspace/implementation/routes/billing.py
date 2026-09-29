"""Ancillary revenue, the contract receivable and the post-event settlement."""

from flask import Blueprint

from core import *  # noqa: F401,F403
from logic import *  # noqa: F401,F403
from serialize import charge_json, reconciliation_json

bp = Blueprint("billing", __name__)


# ----------------------------------------------------------- ancillary charges

@bp.route("/group-sales/ancillary-charges", methods=["POST"])
@endpoint([ROLE_CONTRACT_ADMIN, ROLE_ACCOUNTING_CLERK])
def create_charge():
    body = body_json()
    contract_id = v_id(body, "contract_id")
    category = v_enum(body, "category", CHARGE_CATEGORIES)
    gross = v_int(body, "gross_amount_cents", minimum=1)
    contract = need_contract(contract_id)
    if contract["status"] != "SIGNED":
        fail("ERR_CONTRACT_INVALID_STATE",
             "Ancillary revenue is quoted against a SIGNED contract; it is %s."
             % contract["status"])
    quote = quote_of_contract(contract)
    package = store.packages.get(quote["concession_package_id"]) if quote else None
    discount_pct = ancillary_discount_pct(package, category) if package else 0.0
    row = new_row({
        "contract_id": contract_id,
        "category": category,
        "gross_amount_cents": gross,
        "discount_pct": discount_pct,
        "net_amount_cents": ancillary_net(gross, discount_pct),
        "status": "QUOTED",
    })
    store.charges[row["id"]] = row
    return ok(charge_json(row), 201)


@bp.route("/group-sales/ancillary-charges/<charge_id>", methods=["GET"])
@endpoint([ROLE_CONTRACT_ADMIN, ROLE_ACCOUNTING_CLERK, ROLE_REVENUE_MANAGER,
           ROLE_GROUP_CONTACT])
def read_charge(charge_id):
    charge = need_charge(charge_id)
    require_owner(owner_of_charge(charge))
    return ok(charge_json(charge))


@bp.route("/group-sales/ancillary-charges/<charge_id>/post", methods=["POST"])
@endpoint([ROLE_ACCOUNTING_CLERK])
def post_charge(charge_id):
    charge = need_charge(charge_id)
    if charge["status"] != "QUOTED":
        fail("ERR_CHARGE_INVALID_STATE",
             "Posting is declared only from QUOTED; the charge is %s."
             % charge["status"])
    contract = need_contract(charge["contract_id"])
    if contract["status"] != "SIGNED":
        fail("ERR_CONTRACT_INVALID_STATE",
             "The contract must be SIGNED to post revenue; it is %s."
             % contract["status"])
    account = account_of_contract(contract)
    if account is not None and account["credit_hold"]:
        fail("ERR_ACCOUNT_CREDIT_HOLD",
             "The client organization is on credit hold.")
    charge["status"] = "POSTED"
    touch(charge)
    recompute_receivable(contract)
    # PRD §2.7: "a newly posted ancillary charge bumps the contract's version".
    touch(contract)
    return ok(charge_json(charge))


@bp.route("/group-sales/ancillary-charges/<charge_id>/void", methods=["POST"])
@endpoint([ROLE_ACCOUNTING_CLERK])
def void_charge(charge_id):
    charge = need_charge(charge_id)
    if charge["status"] not in ("QUOTED", "POSTED"):
        fail("ERR_CHARGE_INVALID_STATE",
             "Voiding is declared from QUOTED or POSTED; the charge is %s."
             % charge["status"])
    contract = need_contract(charge["contract_id"])
    if charge["status"] == "POSTED":
        settled = any(r["status"] == "FINALIZED"
                      for r in reconciliations_of_contract(contract["id"]))
        if settled:
            fail("ERR_RECEIVABLE_ALREADY_SETTLED",
                 "The contract already carries a FINALIZED settlement.")
    charge["status"] = "VOIDED"
    touch(charge)
    recompute_receivable(contract)
    return ok(charge_json(charge))


# ------------------------------------------------------------ reconciliations

@bp.route("/group-sales/contracts/<contract_id>/reconciliations", methods=["POST"])
@endpoint([ROLE_ACCOUNTING_CLERK])
def open_reconciliation(contract_id):
    body = body_json()
    expected = v_int(body, "expected_contract_version", minimum=0)
    contract = need_contract(contract_id)
    if expected != contract["version"]:
        fail("ERR_STALE_CONTRACT_VERSION",
             "expected_contract_version %s does not match the contract's version %s."
             % (expected, contract["version"]))
    if contract["status"] != "SIGNED":
        fail("ERR_CONTRACT_INVALID_STATE",
             "A settlement opens against a SIGNED contract; it is %s."
             % contract["status"])
    if store.today() < parse_date_str(contract["departure_date"]):
        fail("ERR_EVENT_NOT_CONCLUDED",
             "The group is still in house until %s." % contract["departure_date"])
    blocks = blocks_of_contract(contract_id)
    for block in blocks:
        if block["inventory_status"] not in ("CUT_OFF", "RELEASED", "CLOSED"):
            fail("ERR_BLOCKS_NOT_CUT_OFF",
                 "Block %s is still %s." % (block["id"], block["inventory_status"]))
    # Any earlier draft stops being the contract's newest settlement.
    for earlier in reconciliations_of_contract(contract_id):
        if earlier["status"] == "DRAFT":
            earlier["status"] = "SUPERSEDED"
            touch(earlier)
    # Waivers land before the figures are frozen.
    for block in blocks:
        if (block["billing_status"] == "UNBILLED"
                and block["inventory_status"] in ("CUT_OFF", "CLOSED")):
            block["billing_status"] = "ATTRITION_ASSESSED"
            touch(block)
    account = account_of_contract(contract)
    if account is not None:
        snapshot = account_rebooking_tier(*account_history(account["id"]))
    else:
        snapshot = 0.01
    quote = quote_of_contract(contract)
    liability = attrition_liability(contract)
    ancillary = posted_ancillary_cents(contract_id)
    waterfall = settlement_waterfall(
        liability["attrition_damages_cents"], ancillary,
        quote["rebate_per_room_night_cents"] if quote else 0,
        liability["billable_room_nights"], snapshot)
    row = new_row({
        "contract_id": contract_id,
        "status": "DRAFT",
        "prepared_by_user_id": actor(),
        "finalized_by_user_id": None,
        "actualized_room_nights": liability["actualized_room_nights"],
        "billable_room_nights": liability["billable_room_nights"],
        "attrition_shortfall_room_nights": liability["attrition_shortfall_room_nights"],
        "attrition_damages_cents": liability["attrition_damages_cents"],
        "ancillary_net_cents": ancillary,
        "incentive_rate_snapshot": snapshot,
    })
    row.update(waterfall)
    store.reconciliations[row["id"]] = row
    touch(contract)
    return ok(reconciliation_json(row), 201)


@bp.route("/group-sales/reconciliations/<recon_id>", methods=["GET"])
@endpoint([ROLE_CONTRACT_ADMIN, ROLE_ACCOUNTING_CLERK, ROLE_REVENUE_MANAGER,
           ROLE_GROUP_CONTACT])
def read_reconciliation(recon_id):
    recon = need_reconciliation(recon_id)
    require_owner(owner_of_reconciliation(recon))
    return ok(reconciliation_json(recon))


@bp.route("/group-sales/reconciliations/<recon_id>/finalize", methods=["POST"])
@endpoint([ROLE_ACCOUNTING_CLERK])
def finalize_reconciliation(recon_id):
    recon = need_reconciliation(recon_id)
    if actor() == recon["prepared_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The user who prepared the settlement may not finalize it.")
    if recon["status"] != "DRAFT":
        fail("ERR_RECONCILIATION_ALREADY_FINALIZED",
             "The settlement is %s; finalization is a one-shot step."
             % recon["status"])
    contract = need_contract(recon["contract_id"])
    if contract["status"] != "SIGNED":
        fail("ERR_CONTRACT_INVALID_STATE",
             "The contract must be SIGNED to finalize its settlement; it is %s."
             % contract["status"])
    recon["status"] = "FINALIZED"
    recon["finalized_by_user_id"] = actor()
    touch(recon)
    contract["status"] = "COMPLETED"
    contract["assessed_damages_cents"] = recon["attrition_damages_cents"]
    contract["rebate_paid_cents"] = recon["rebate_payable_cents"]
    recompute_receivable(contract)
    for block in blocks_of_contract(contract["id"]):
        if block["billing_status"] in ("ATTRITION_ASSESSED", "WAIVED"):
            block["billing_status"] = "SETTLED"
            if block["inventory_status"] == "CUT_OFF":
                block["inventory_status"] = "CLOSED"
            touch(block)
    touch(contract)
    return ok(reconciliation_json(recon))
