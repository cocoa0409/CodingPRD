"""Asset transfers and their cost-basis-carryover lots."""

from core.context import body, check_if_match, need
from core.errors import fail
from core.response import ok, paginate
from core.store import STORE
from domain import calc
from domain.cascade import refresh_household
from domain.guards import firm_active_guard
from domain.model import create, serialize, touch
from domain.resolve import sorted_rows
from routes._base import load, load_firm


def register(api):

    @api.route("/ria/asset-transfers", methods=["POST"], roles=["AdvisorOperationsLead"])
    def create_transfer():
        data = body()
        account = load("HouseholdAccount", need(data, "receiving_account_id"))
        firm = load_firm(need(data, "firm_id"))
        if account.get("firm_id") != firm.get("id"):
            fail("ERR_REFERENCE_MISMATCH")
        firm_active_guard(firm)
        row = create("AssetTransfer",
                     receiving_account_id=account.get("id"),
                     firm_id=firm.get("id"),
                     transfer_status="REQUESTED",
                     delivering_firm_name=need(data, "delivering_firm_name"),
                     method=need(data, "method"),
                     sent_basis_confidence=None,
                     carryover_cents=0,
                     cost_basis_complete=False,
                     rejected_reason_code=None,
                     credited_at=None,
                     submitted_at=None)
        return ok(serialize(row), 201)

    @api.route("/ria/asset-transfers", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_transfers():
        from routes._base import params
        p = params()
        rows = sorted_rows("AssetTransfer", {"receiving_account_id": p.get("receiving_account_id"),
                                             "firm_id": p.get("firm_id"),
                                             "transfer_status": p.get("transfer_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/asset-transfers/<transfer_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def read_transfer(transfer_id):
        return ok(serialize(load("AssetTransfer", transfer_id)), 200)

    @api.route("/ria/accounts/<account_id>/asset-transfers", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_account_transfers(account_id):
        from routes._base import params
        load("HouseholdAccount", account_id)
        p = params()
        rows = sorted_rows("AssetTransfer", {"receiving_account_id": account_id,
                                             "transfer_status": p.get("transfer_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/transfers/<transfer_id>/lots", methods=["POST"],
               roles=["AdvisorOperationsLead"])
    def add_lot(transfer_id):
        transfer = load("AssetTransfer", transfer_id)
        firm = load_firm(transfer.get("firm_id"))
        firm_active_guard(firm)
        data = body()
        row = create("TransferLot",
                     transfer_id=transfer.get("id"),
                     symbol=need(data, "symbol"),
                     quantity_micros=int(data.get("quantity_micros") or 0),
                     sent_cost_basis_cents=data.get("sent_cost_basis_cents"),
                     lot_inventory_date=data.get("lot_inventory_date"),
                     valuation_price_micros=int(data.get("valuation_price_micros") or 0),
                     basis_appraisal_cents=None,
                     suspected_double_basis=False,
                     basis_confidence_grade=None,
                     lot_status="PENDING")
        return ok(serialize(row), 201)

    @api.route("/ria/asset-transfers/<transfer_id>/lots", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_lots(transfer_id):
        from routes._base import params
        load("AssetTransfer", transfer_id)
        p = params()
        rows = sorted_rows("TransferLot", {"transfer_id": transfer_id,
                                           "basis_confidence_grade": p.get("basis_confidence_grade")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/assets/<transfer_id>/transfer-out", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def transfer_out(transfer_id):
        transfer = load("AssetTransfer", transfer_id)
        data = body()
        check_if_match(transfer, data)
        firm = load_firm(transfer.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(transfer, ("REQUESTED",), ("CREDITED", "REJECTED"))
        account = load("HouseholdAccount", transfer.get("receiving_account_id"))
        if account.get("account_status") not in ("OPEN", "FROZEN"):
            fail("ERR_ACCOUNT_NOT_ELIGIBLE")
        if firm.get("firm_posture") not in ("OPEN", "LIMITED"):
            fail("ERR_FIRM_NOT_OPEN_FOR_TRADING")
        transfer["transfer_status"] = "SUBMITTED"
        transfer["submitted_at"] = STORE.clock.now()
        touch(transfer)
        return ok(serialize(transfer), 200)

    @api.route("/ria/assets/<transfer_id>/mark-received", methods=["POST"],
               roles=["CustodyOperationsOfficer"], if_match=True)
    def mark_received(transfer_id):
        transfer = load("AssetTransfer", transfer_id)
        data = body()
        check_if_match(transfer, data)
        firm = load_firm(transfer.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(transfer, ("SUBMITTED",), ("CREDITED", "REJECTED"))
        lots = STORE.find("TransferLot", transfer_id=transfer_id)
        grades, carryover = calc.grade_lots(transfer, lots, transfer.get("submitted_at"))
        suspected = calc.suspected_double_basis(transfer)
        for lot in lots:
            lot["basis_confidence_grade"] = grades.get(lot.get("id"))
            lot["suspected_double_basis"] = suspected
            lot["lot_status"] = "STAMPED"
            touch(lot)
        transfer["transfer_status"] = "RECEIVED"
        touch(transfer)
        account = load("HouseholdAccount", transfer.get("receiving_account_id"))
        account["market_value_cents"] = calc.compute_account_market_value(account)
        touch(account)
        refresh_household(STORE.get("Household", account.get("household_id")))

        if lots and all(l.get("sent_cost_basis_cents") is not None for l in lots):
            _credit(transfer, firm)
        elif not lots:
            _credit(transfer, firm)
        else:
            transfer["transfer_status"] = "BASIS_REVIEW"
            transfer["carryover_cents"] = 0
            transfer["cost_basis_complete"] = False
            touch(transfer)
        return ok(serialize(transfer), 200)

    @api.route("/ria/assets/<transfer_id>/accept-basis", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def accept_basis(transfer_id):
        transfer = load("AssetTransfer", transfer_id)
        data = body()
        check_if_match(transfer, data)
        firm = load_firm(transfer.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(transfer, ("BASIS_REVIEW",), ("CREDITED", "REJECTED"))
        lots = STORE.find("TransferLot", transfer_id=transfer_id)
        if not all(l.get("sent_cost_basis_cents") is not None for l in lots):
            fail("ERR_INVALID_STATE", "Every lot must carry a reported cost basis.")
        held = any(e.get("requirement_code") == "QUALIFIED_CUSTODIAN"
                   and e.get("requirement_status") in ("ACCEPTED", "WAIVED")
                   for e in STORE.find("CustodyRulesEvidence", firm_id=firm.get("id")))
        if not held:
            fail("ERR_CUSTODY_AGREEMENT_REQUIRED",
                 "A QUALIFIED_CUSTODIAN evidence row in ACCEPTED or WAIVED is required.")
        _credit(transfer, firm)
        account = load("HouseholdAccount", transfer.get("receiving_account_id"))
        calc.recompute_account(account)
        refresh_household(STORE.get("Household", account.get("household_id")))
        return ok(serialize(transfer), 200)

    @api.route("/ria/assets/<transfer_id>/reject-basis", methods=["POST"],
               roles=["CustodyOperationsOfficer"], if_match=True)
    def reject_basis(transfer_id):
        transfer = load("AssetTransfer", transfer_id)
        data = body()
        check_if_match(transfer, data)
        firm = load_firm(transfer.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(transfer, ("BASIS_REVIEW",), ("CREDITED", "REJECTED"))
        reason = need(data, "rejected_reason_code")
        transfer["transfer_status"] = "REJECTED"
        transfer["rejected_reason_code"] = reason
        transfer["carryover_cents"] = 0
        touch(transfer)
        for lot in STORE.find("TransferLot", transfer_id=transfer_id):
            lot["lot_status"] = "DISCARDED"
            lot["basis_appraisal_cents"] = None
            touch(lot)
        account = load("HouseholdAccount", transfer.get("receiving_account_id"))
        account["market_value_cents"] = calc.compute_account_market_value(account)
        touch(account)
        refresh_household(STORE.get("Household", account.get("household_id")))
        return ok(serialize(transfer), 200)

    @api.route("/ria/assets/<transfer_id>/reject", methods=["POST"],
               roles=["CustodyOperationsOfficer"], if_match=True)
    def reject_transfer(transfer_id):
        transfer = load("AssetTransfer", transfer_id)
        data = body()
        check_if_match(transfer, data)
        firm = load_firm(transfer.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(transfer, ("REQUESTED",), ("CREDITED", "REJECTED"))
        reason = need(data, "rejected_reason_code")
        transfer["transfer_status"] = "REJECTED"
        transfer["rejected_reason_code"] = reason
        touch(transfer)
        return ok(serialize(transfer), 200)


def _credit(transfer, firm):
    """RECEIVED/BASIS_REVIEW -> CREDITED with the C6 carryover result."""
    lots = STORE.find("TransferLot", transfer_id=transfer.get("id"))
    grades, carryover = calc.grade_lots(transfer, lots, transfer.get("submitted_at"))
    for lot in lots:
        lot["lot_status"] = "APPLIED"
        lot["basis_appraisal_cents"] = lot.get("sent_cost_basis_cents")
        touch(lot)
    transfer["transfer_status"] = "CREDITED"
    transfer["carryover_cents"] = carryover
    transfer["sent_basis_confidence"] = _transfer_grade(grades)
    transfer["cost_basis_complete"] = bool(lots) and all(
        grades.get(l.get("id")) == "HIGH" for l in lots)
    transfer["credited_at"] = STORE.clock.now()
    touch(transfer)
    account = STORE.get("HouseholdAccount", transfer.get("receiving_account_id"))
    if account is not None:
        calc.recompute_account(account)
    return transfer


def _transfer_grade(grades):
    values = [g for g in grades.values() if g]
    if not values:
        return "NONE"
    for grade in ("HIGH", "MEDIUM", "LOW"):
        if grade in values:
            return grade
    return "NONE"


def _state_or_terminal(row, from_states, terminal_states):
    from core.context import STATE_FIELDS
    state = row.get(STATE_FIELDS.get(row.get("_entity")))
    if terminal_states and state in terminal_states:
        fail("ERR_ALREADY_TERMINAL")
    allowed = from_states if isinstance(from_states, (tuple, list, set)) else (from_states,)
    if state not in allowed:
        fail("ERR_INVALID_STATE")