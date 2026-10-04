"""Standing instructions and money movements, including the C7 verification
sequence and the read-only DOMINANT_RULE probe."""

from core import constants as C
from core.context import body, check_if_match, need
from core.errors import fail
from core.response import ok, paginate
from core.store import STORE, days_between, new_token, parse_dt
from domain import calc
from domain.cascade import refresh_household, reject_movements_for_account
from domain.guards import firm_active_guard
from domain.model import create, serialize, touch
from domain.resolve import sorted_rows
from routes._base import identity, load, load_firm, load_via_account


def register(api):

    # ------------------------------------------------ standing instructions

    @api.route("/ria/accounts/<account_id>/standing-instructions", methods=["POST"],
               roles=["AdvisorOperationsLead"])
    def create_instruction(account_id):
        account = load("HouseholdAccount", account_id)
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        data = body()
        row = create("StandingInstruction",
                     account_id=account_id,
                     instruction_type=need(data, "instruction_type"),
                     payee_name=need(data, "payee_name"),
                     periodic_limit_cents=int(need(data, "periodic_limit_cents")),
                     verification_status="PENDING",
                     verification_token=new_token("vt_"),
                     verified_at=None,
                     round_trip_days=None,
                     consumed_period_cents=0)
        return ok(serialize(row), 201)

    @api.route("/ria/accounts/<account_id>/standing-instructions", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "Client", "PlatformAdmin"])
    def list_instructions(account_id):
        from routes._base import params
        ident = identity()
        account = load("HouseholdAccount", account_id)
        if ident.is_client and account.get("household_id") != ident.user_id:
            fail("ERR_RESOURCE_NOT_FOUND")
        p = params()
        rows = sorted_rows("StandingInstruction",
                           {"account_id": account_id, "verification_status": p.get("verification_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/standing-instructions/<instruction_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "Client", "PlatformAdmin"])
    def read_instruction(instruction_id):
        ident = identity()
        row = load_via_account("StandingInstruction", instruction_id, ident)
        _refresh_round_trip(row)
        return ok(serialize(row), 200)

    @api.route("/ria/standing-instructions/<instruction_id>/verify", methods=["POST"],
               roles=["Client"], if_match=True)
    def verify_instruction(instruction_id):
        ident = identity()
        row = load("StandingInstruction", instruction_id)
        account = load("HouseholdAccount", row.get("account_id"))
        if account.get("household_id") != ident.user_id:
            fail("ERR_RESOURCE_NOT_FOUND")
        data = body()
        check_if_match(row, data)
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, ("PENDING",), ("EXPIRED", "REVOKED"))
        token = need(data, "verification_token")
        if str(token) != str(row.get("verification_token")):
            fail("ERR_RESOURCE_NOT_FOUND", "The verification token does not match.")
        row["verification_status"] = "VERIFIED"
        row["verified_at"] = STORE.clock.now()
        row["round_trip_days"] = 0
        touch(row)
        return ok(serialize(row), 200)

    @api.route("/ria/standing-instructions/<instruction_id>/expire-check", methods=["POST"],
               roles=["CustodyOperationsOfficer"], if_match=True)
    def expire_instruction(instruction_id):
        row = load("StandingInstruction", instruction_id)
        data = body()
        check_if_match(row, data)
        account = load("HouseholdAccount", row.get("account_id"))
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, ("VERIFIED",), ("EXPIRED", "REVOKED"))
        _refresh_round_trip(row)
        if int(row.get("round_trip_days") or 0) < C.STANDING_ROUND_TRIP_CEILING_DAYS:
            fail("ERR_INVALID_STATE", "The round trip has not yet reached seven days.")
        row["verification_status"] = "EXPIRED"
        touch(row)
        reject_movements_for_account(account)
        return ok(serialize(row), 200)

    @api.route("/ria/standing-instructions/<instruction_id>/revoke", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def revoke_instruction(instruction_id):
        row = load("StandingInstruction", instruction_id)
        data = body()
        check_if_match(row, data)
        account = load("HouseholdAccount", row.get("account_id"))
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, ("VERIFIED",), ("EXPIRED", "REVOKED"))
        row["verification_status"] = "REVOKED"
        touch(row)
        reject_movements_for_account(account)
        return ok(serialize(row), 200)

    @api.route("/ria/standing-instructions/<instruction_id>/money-movements", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "Client", "PlatformAdmin"])
    def list_instruction_movements(instruction_id):
        from routes._base import params
        ident = identity()
        load_via_account("StandingInstruction", instruction_id, ident)
        p = params()
        rows = sorted_rows("MoneyMovementInstruction",
                           {"standing_instruction_id": instruction_id,
                            "movement_status": p.get("movement_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    # ------------------------------------------------------- money movements

    @api.route("/ria/money-movements", methods=["POST"], roles=["AdvisorOperationsLead"])
    def create_movement():
        data = body()
        account = load("HouseholdAccount", need(data, "account_id"))
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        instruction = load("StandingInstruction", need(data, "standing_instruction_id"))
        if instruction.get("account_id") != account.get("id"):
            fail("ERR_PARENT_CHILD_MISMATCH")
        amount = int(need(data, "amount_cents"))
        if amount > int(instruction.get("periodic_limit_cents") or 0) - int(instruction.get("consumed_period_cents") or 0):
            fail("ERR_STANDING_LIMIT_EXCEEDED")
        row = create("MoneyMovementInstruction",
                     account_id=account.get("id"),
                     standing_instruction_id=instruction.get("id"),
                     amount_cents=amount,
                     movement_type=need(data, "movement_type"),
                     movement_status="DRAFT",
                     authorization_note=data.get("authorization_note"),
                     jurisdiction_withholding_required=False,
                     withheld_cents=0,
                     net_disbursed_cents=amount,
                     authorized_at=None)
        return ok(serialize(row), 201)

    @api.route("/ria/accounts/<account_id>/money-movements", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "Client", "PlatformAdmin"])
    def list_movements(account_id):
        from routes._base import params
        ident = identity()
        account = load("HouseholdAccount", account_id)
        if ident.is_client and account.get("household_id") != ident.user_id:
            fail("ERR_RESOURCE_NOT_FOUND")
        p = params()
        rows = sorted_rows("MoneyMovementInstruction",
                           {"account_id": account_id, "movement_status": p.get("movement_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/accounts/<account_id>/money-movements/summary", methods=["GET"],
               roles=["AdvisorOperationsLead", "ComplianceReviewer", "CustodyOperationsOfficer",
                      "Client", "PlatformAdmin"])
    def movement_summary(account_id):
        from routes._base import params
        ident = identity()
        account = load("HouseholdAccount", account_id)
        if ident.is_client and account.get("household_id") != ident.user_id:
            fail("ERR_RESOURCE_NOT_FOUND")
        p = params()
        rows = sorted_rows("MoneyMovementInstruction", {"account_id": account_id})
        out = []
        for mov in rows:
            instruction = STORE.get("StandingInstruction", mov.get("standing_instruction_id"))
            payload = serialize(mov)
            payload["restriction_demands"] = calc.dominant_rule_probe(mov, instruction, account)
            payload["probe_withheld_cents"] = max(payload["restriction_demands"].values())
            out.append(payload)
        page, meta = paginate(out, p)
        return ok(page, 200, meta)

    @api.route("/ria/money-movements/<movement_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "AdvisorSupportAnalyst", "CustodyOperationsOfficer",
                      "ComplianceReviewer", "Client", "PlatformAdmin"])
    def read_movement(movement_id):
        ident = identity()
        row = load_via_account("MoneyMovementInstruction", movement_id, ident)
        return ok(serialize(row), 200)

    @api.route("/ria/money-movements/<movement_id>/submit", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def submit_movement(movement_id):
        row = load("MoneyMovementInstruction", movement_id)
        data = body()
        check_if_match(row, data)
        account = load("HouseholdAccount", row.get("account_id"))
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, ("DRAFT",), ("REJECTED", "CANCELLED", "COMPLETED"))
        if account.get("account_status") != "OPEN":
            fail("ERR_ACCOUNT_NOT_ELIGIBLE")
        if firm.get("firm_posture") not in ("OPEN", "LIMITED"):
            fail("ERR_FIRM_NOT_OPEN_FOR_TRADING")
        row["movement_status"] = "PENDING_AUTHORIZATION"
        touch(row)
        return ok(serialize(row), 200)

    @api.route("/ria/money-movements/<movement_id>/authorize", methods=["POST"],
               roles=["Client"], if_match=True)
    def authorize_movement(movement_id):
        ident = identity()
        row = load("MoneyMovementInstruction", movement_id)
        account = load("HouseholdAccount", row.get("account_id"))
        if account.get("household_id") != ident.user_id:
            fail("ERR_RESOURCE_NOT_FOUND")
        data = body()
        check_if_match(row, data)
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, ("PENDING_AUTHORIZATION",), ("REJECTED", "CANCELLED", "COMPLETED"))
        if account.get("account_status") != "OPEN":
            fail("ERR_ACCOUNT_NOT_ELIGIBLE")
        instruction = STORE.get("StandingInstruction", row.get("standing_instruction_id"))
        _refresh_round_trip(instruction)
        error_id, decision = calc.money_movement_decision(row, instruction, account)
        if error_id:
            fail(error_id)
        required, withheld = decision
        row["authorization_note"] = row.get("authorization_note")
        row["jurisdiction_withholding_required"] = required
        row["withheld_cents"] = withheld
        row["net_disbursed_cents"] = int(row.get("amount_cents") or 0) - withheld
        row["movement_status"] = "AUTHORIZED"
        row["authorized_at"] = STORE.clock.now()
        touch(row)
        instruction["consumed_period_cents"] = (int(instruction.get("consumed_period_cents") or 0)
                                                + int(row.get("amount_cents") or 0))
        touch(instruction)
        calc.recompute_account(account)
        refresh_household(STORE.get("Household", account.get("household_id")))
        return ok(serialize(row), 200)

    @api.route("/ria/money-movements/<movement_id>/reject", methods=["POST"],
               roles=["Client"], if_match=True)
    def reject_movement(movement_id):
        ident = identity()
        row = load("MoneyMovementInstruction", movement_id)
        account = load("HouseholdAccount", row.get("account_id"))
        if account.get("household_id") != ident.user_id:
            fail("ERR_RESOURCE_NOT_FOUND")
        data = body()
        check_if_match(row, data)
        firm_active_guard(load_firm(account.get("firm_id")))
        _state_or_terminal(row, ("PENDING_AUTHORIZATION",), ("REJECTED", "CANCELLED", "COMPLETED"))
        row["movement_status"] = "REJECTED"
        touch(row)
        return ok(serialize(row), 200)

    @api.route("/ria/money-movements/<movement_id>/cancel", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def cancel_movement(movement_id):
        row = load("MoneyMovementInstruction", movement_id)
        data = body()
        check_if_match(row, data)
        firm_active_guard(load_firm((STORE.get("HouseholdAccount", row.get("account_id")) or {}).get("firm_id")))
        _state_or_terminal(row, ("DRAFT",), ("REJECTED", "CANCELLED", "COMPLETED"))
        row["movement_status"] = "CANCELLED"
        touch(row)
        return ok(serialize(row), 200)

    @api.route("/ria/money-movements/<movement_id>/complete", methods=["POST"],
               roles=["CustodyOperationsOfficer"], if_match=True)
    def complete_movement(movement_id):
        row = load("MoneyMovementInstruction", movement_id)
        data = body()
        check_if_match(row, data)
        firm_active_guard(load_firm((STORE.get("HouseholdAccount", row.get("account_id")) or {}).get("firm_id")))
        _state_or_terminal(row, ("AUTHORIZED",), ("REJECTED", "CANCELLED", "COMPLETED"))
        row["movement_status"] = "COMPLETED"
        touch(row)
        return ok(serialize(row), 200)


def _refresh_round_trip(instruction):
    if instruction is None:
        return None
    verified = instruction.get("verified_at")
    if verified is None:
        instruction["round_trip_days"] = None
        return None
    instruction["round_trip_days"] = days_between(STORE.clock.now_dt(), parse_dt(verified))
    return instruction["round_trip_days"]


def _state_or_terminal(row, from_states, terminal_states):
    from core.context import STATE_FIELDS
    state = row.get(STATE_FIELDS.get(row.get("_entity")))
    if terminal_states and state in terminal_states:
        fail("ERR_ALREADY_TERMINAL")
    allowed = from_states if isinstance(from_states, (tuple, list, set)) else (from_states,)
    if state not in allowed:
        fail("ERR_INVALID_STATE")