"""Clock, system configuration, database invariants and regulatory admin actions."""

from core import constants as C
from core.context import body, check_if_match, need
from core.response import ok
from core.store import STORE
from domain import calc
from domain.cascade import apply_posture
from domain.model import create, serialize, touch
from routes._base import identity, load_firm


def register(api):

    @api.route("/_clock/set_current_utc", methods=["POST"], roles=["PlatformAdmin"])
    def set_clock():
        data = body()
        current = need(data, "current_utc")
        STORE.clock.set(current)
        for holding in STORE.all("AlternativeAssetHolding"):
            _refresh_valuation_age(holding)
        for instruction in STORE.all("StandingInstruction"):
            _refresh_round_trip(instruction)
        return ok({}, 200)

    @api.route("/ria/systems/config", methods=["POST"], roles=["PlatformAdmin"])
    def create_config():
        data = body()
        existing = STORE.find_one("SystemConfig", config_key=C.CONFIG_KEY)
        if existing is not None:
            return ok(serialize(existing), 201)
        row = create("SystemConfig",
                     config_key=C.CONFIG_KEY,
                     database_invariant_enforcement=data.get("database_invariant_enforcement", "WARN"),
                     platform_fee_enabled=True if data.get("platform_fee_enabled") is None
                     else bool(data.get("platform_fee_enabled")))
        return ok(serialize(row), 201)

    @api.route("/ria/systems/config/<config_id>", methods=["PATCH"], roles=["PlatformAdmin"],
               if_match=True)
    def patch_config(config_id):
        row = STORE.get("SystemConfig", config_id)
        if row is None:
            from core.errors import fail
            fail("ERR_RESOURCE_NOT_FOUND")
        data = body()
        check_if_match(row, data)
        if "database_invariant_enforcement" in data:
            row["database_invariant_enforcement"] = data["database_invariant_enforcement"]
        if "platform_fee_enabled" in data:
            row["platform_fee_enabled"] = bool(data["platform_fee_enabled"])
        touch(row)
        return ok(serialize(row), 200)

    @api.route("/ria/invariants/evaluate", methods=["POST"],
               roles=["CustodyOperationsOfficer", "PlatformAdmin"], if_match=False)
    def evaluate_invariants():
        data = body()
        firm = load_firm(need(data, "firm_id"))
        from domain.guards import invariant_guard
        invariant_guard(firm)
        calc.recompute_firm_basis_total(firm)
        rows = _evaluate_all(firm)
        return ok([serialize(r) for r in rows], 200)

    @api.route("/ria/firms/<firm_id>/invariants", methods=["GET"],
               roles=["ComplianceReviewer", "PlatformAdmin", "CustodyOperationsOfficer"])
    def list_invariants(firm_id):
        load_firm(firm_id)
        rows = STORE.find("DatabaseInvariant", firm_id=firm_id)
        rows.sort(key=lambda r: r.get("_seq") or 0)
        return ok([serialize(r) for r in rows], 200)

    @api.route("/ria/admin-actions/issue", methods=["POST"], roles=["PlatformAdmin"])
    def issue_admin_action():
        data = body()
        firm = load_firm(need(data, "firm_id"))
        kind = need(data, "admin_action_kind")
        row = create(
            "AdminActionLog",
            firm_id=firm.get("id"),
            admin_action_kind=kind,
            admin_action_status="ACTIVE" if kind == "REGULATORY_FREEZE" else "UNACKNOWLEDGED",
            admin_action_detail=data.get("admin_action_detail"),
            acknowledged_note=None,
            acknowledged_by_user_id=None,
        )
        apply_posture(firm)
        return ok(serialize(row), 201)

    @api.route("/ria/firms/<firm_id>/admin-actions", methods=["GET"],
               roles=["ComplianceReviewer", "PlatformAdmin", "CustodyOperationsOfficer"])
    def list_admin_actions(firm_id):
        load_firm(firm_id)
        rows = STORE.find("AdminActionLog", firm_id=firm_id)
        rows.sort(key=lambda r: r.get("_seq") or 0)
        return ok([serialize(r) for r in rows], 200)

    @api.route("/ria/admin-actions/<action_id>/acknowledge", methods=["POST"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer"], if_match=True)
    def acknowledge_admin_action(action_id):
        row = STORE.get("AdminActionLog", action_id)
        if row is None:
            from core.errors import fail
            fail("ERR_RESOURCE_NOT_FOUND")
        data = body()
        check_if_match(row, data)
        note = need(data, "acknowledged_note")
        ident = identity()
        row["acknowledged_note"] = note
        row["acknowledged_by_user_id"] = ident.user_id
        row["admin_action_status"] = "ACKNOWLEDGED"
        touch(row)
        firm = STORE.get("AdvisorFirm", row.get("firm_id"))
        apply_posture(firm)
        return ok(serialize(row), 200)


def _refresh_valuation_age(holding):
    from core.store import days_between
    age = days_between(STORE.clock.now_dt(), _dt(holding.get("valuation_as_of_date")))
    holding["valuation_age_days"] = age
    holding["stale_valuation"] = age > C.AGE_THRESHOLD_DAYS


def _refresh_round_trip(instruction):
    from core.store import days_between
    verified = instruction.get("verified_at")
    if verified is None:
        instruction["round_trip_days"] = None
        return
    instruction["round_trip_days"] = days_between(STORE.clock.now_dt(), _dt(verified))


def _dt(value):
    from core.store import parse_dt
    return parse_dt(value)


def _evaluate_all(firm):
    """C11 sweep: reconcile the three fee-basis derivations and report every
    invariant code the firm should hold."""
    for code in C.INVARIANT_CODES:
        if STORE.find_one("DatabaseInvariant", firm_id=firm.get("id"), invariant_code=code) is None:
            create("DatabaseInvariant", firm_id=firm.get("id"), invariant_code=code,
                   invariant_status="HOLDING", expected_total_cents=0,
                   observed_total_cents=0, breach_detail_code=None,
                   last_evaluated_at=None)
    now = STORE.clock.now()
    rows = []
    for inv in STORE.find("DatabaseInvariant", firm_id=firm.get("id")):
        inv["last_evaluated_at"] = now
        status, expected, observed, detail = _evaluate_one(firm, inv.get("invariant_code"))
        inv["invariant_status"] = status
        inv["expected_total_cents"] = expected
        inv["observed_total_cents"] = observed
        inv["breach_detail_code"] = detail
        touch(inv)
        rows.append(inv)
    return rows


def _evaluate_one(firm, code):
    from domain.guards import enforcement_enforced
    if code == "HOUSEHOLD_FEE_BASIS_RECONCILIATION":
        basis_1, basis_2, basis_3 = calc.reconciliation_totals(firm)
        drift_household = basis_1 - basis_2
        drift_account = basis_2 - basis_3
        broken = (drift_household != 0 or drift_account != 0) and enforcement_enforced()
        if broken:
            detail = ("HOUSEHOLD_FEE_BASIS_TOTAL_DRIFT" if basis_1 != basis_3
                      else "HOUSEHOLD_FEE_BASIS_STALE_ROLLUP")
            return "BROKEN", basis_1, basis_3, detail
        return "HOLDING", basis_1, basis_3, None
    if code == "CUSTODY_AGREEMENT_CONSISTENCY":
        agreement = None
        for row in STORE.find("CustodyAgreement", firm_id=firm.get("id")):
            if row.get("agreement_status") == "EXECUTED":
                agreement = row
                break
        consistent = agreement is not None and firm.get("custody_agreement_status") == "EXECUTED"
        broken = not consistent and enforcement_enforced()
        return ("BROKEN" if broken else "HOLDING"), 0, 0, ("CUSTODY_AGREEMENT_INCONSISTENT" if broken else None)
    if code == "TRANSFER_BASIS_CONSERVATION":
        expected = sum(int(l.get("sent_cost_basis_cents") or 0) for l in STORE.all("TransferLot")
                       if (STORE.get("AssetTransfer", l.get("transfer_id")) or {}).get("firm_id") == firm.get("id")
                       and l.get("lot_status") == "APPLIED")
        observed = sum(int(l.get("basis_appraisal_cents") or 0) for l in STORE.all("TransferLot")
                       if (STORE.get("AssetTransfer", l.get("transfer_id")) or {}).get("firm_id") == firm.get("id")
                       and l.get("lot_status") == "APPLIED")
        broken = (expected != observed) and enforcement_enforced()
        detail = "TRANSFER_BASIS_DRIFT" if broken else None
        return ("BROKEN" if broken else "HOLDING"), expected, observed, detail
    if code == "CASCADE_ECONOMIC_EFFECT":
        drift = sum(int(a.get("fee_rebate_cents") or 0) for a in STORE.all("BlockAllocation")
                    if (STORE.get("BlockOrder", a.get("block_order_id")) or {}).get("firm_id") == firm.get("id"))
        broken = drift < 0 and enforcement_enforced()
        return ("BROKEN" if broken else "HOLDING"), 0, 0, ("CASCADE_DRIFT" if broken else None)
    return "HOLDING", 0, 0, None