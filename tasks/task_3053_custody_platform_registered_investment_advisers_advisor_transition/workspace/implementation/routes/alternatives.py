"""Alternative asset custody and valuation acceptance."""

from core import constants as C
from core.context import body, check_if_match, need
from core.errors import fail
from core.response import ok, paginate
from core.store import STORE, days_between, parse_dt
from domain import calc
from domain.cascade import refresh_household
from domain.guards import firm_active_guard, require_any_entitlement
from domain.model import create, serialize, touch
from domain.resolve import sorted_rows
from routes._base import load, load_firm


def register(api):

    @api.route("/ria/alternatives", methods=["POST"], roles=["AdvisorOperationsLead"])
    def create_holding():
        data = body()
        account = load("HouseholdAccount", need(data, "account_id"))
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        row = create("AlternativeAssetHolding",
                     account_id=account.get("id"),
                     asset_name=need(data, "asset_name"),
                     asset_acceptance_status="PENDING",
                     unit_count=int(data.get("unit_count") or 0),
                     stated_value_cents=int(data.get("stated_value_cents") or 0),
                     accepted_value_cents=None,
                     haircut_pct=None,
                     valuation_floor_cents=int(data.get("valuation_floor_cents") or 0),
                     valuation_as_of_date=data.get("valuation_as_of_date"),
                     valuation_age_days=None,
                     stale_valuation=False,
                     fee_basis_eligible=False)
        return ok(serialize(row), 201)

    @api.route("/ria/accounts/<account_id>/alternatives", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_holdings(account_id):
        from routes._base import params
        load("HouseholdAccount", account_id)
        p = params()
        rows = sorted_rows("AlternativeAssetHolding",
                           {"account_id": account_id,
                            "asset_acceptance_status": p.get("asset_acceptance_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/alternatives/<holding_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def read_holding(holding_id):
        holding = load("AlternativeAssetHolding", holding_id)
        _refresh_age(holding)
        return ok(serialize(holding), 200)

    @api.route("/ria/alternatives/<holding_id>/submit-valuation", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def submit_valuation(holding_id):
        holding = load("AlternativeAssetHolding", holding_id)
        data = body()
        check_if_match(holding, data)
        firm = load_firm((STORE.get("HouseholdAccount", holding.get("account_id")) or {}).get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(holding, ("PENDING",), ("ACCEPTED", "REJECTED"))
        require_any_entitlement(firm, ("ALTERNATIVE_ASSETS",))
        if "stated_value_cents" in data and data.get("stated_value_cents") is not None:
            holding["stated_value_cents"] = int(data["stated_value_cents"])
        if "valuation_as_of_date" in data and data.get("valuation_as_of_date") is not None:
            holding["valuation_as_of_date"] = data["valuation_as_of_date"]
        _refresh_age(holding)
        _duplicate_period_guard(holding)
        holding["asset_acceptance_status"] = "UNDER_REVIEW"
        touch(holding)
        return ok(serialize(holding), 200)

    @api.route("/ria/alternatives/<holding_id>/accept-valuation", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def accept_valuation(holding_id):
        holding = load("AlternativeAssetHolding", holding_id)
        data = body()
        check_if_match(holding, data)
        account = load("HouseholdAccount", holding.get("account_id"))
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(holding, ("UNDER_REVIEW",), ("ACCEPTED", "REJECTED"))
        _refresh_age(holding)
        # Guard order follows the scaffold's pinned priorities:
        # 25 ambiguous binding < 35 below floor < 36 duplicate holding < 41 stale.
        rival_review = [o for o in STORE.find("AlternativeAssetHolding", account_id=account.get("id"))
                        if o.get("id") != holding.get("id")
                        and o.get("asset_acceptance_status") == "UNDER_REVIEW"]
        duplicate_review = [o for o in rival_review if o.get("asset_name") == holding.get("asset_name")]
        # PRD §3.5 enumerates the four gates in this order — the valuation age is
        # stated first, and a holding older than 270 days "may not be admitted to
        # the fee basis at all", so the age gate is the earliest of the family.
        if int(holding.get("valuation_age_days") or 0) > C.AGE_THRESHOLD_DAYS:
            fail("ERR_VALUATION_STALE")
        if [o for o in rival_review if o.get("asset_name") != holding.get("asset_name")]:
            fail("ERR_AMBIGUOUS_VALUATION_BINDING")
        if int(holding.get("stated_value_cents") or 0) < int(holding.get("valuation_floor_cents") or 0):
            fail("ERR_VALUATION_BELOW_FLOOR")
        if duplicate_review:
            fail("ERR_DUPLICATE_ALTERNATIVE_HOLDING")
        accepted, bps = calc.valuation_haircut(holding.get("stated_value_cents"),
                                               holding.get("valuation_floor_cents"),
                                               int(holding.get("valuation_age_days") or 0))
        holding["asset_acceptance_status"] = "ACCEPTED"
        holding["accepted_value_cents"] = accepted
        holding["haircut_pct"] = bps
        holding["fee_basis_eligible"] = True
        touch(holding)
        calc.recompute_account(account)
        refresh_household(STORE.get("Household", account.get("household_id")))
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(holding), 200)

    @api.route("/ria/alternatives/<holding_id>/reject-valuation", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def reject_valuation(holding_id):
        holding = load("AlternativeAssetHolding", holding_id)
        data = body()
        check_if_match(holding, data)
        account = load("HouseholdAccount", holding.get("account_id"))
        firm = load_firm(account.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(holding, ("UNDER_REVIEW",), ("ACCEPTED", "REJECTED"))
        holding["asset_acceptance_status"] = "REJECTED"
        holding["accepted_value_cents"] = None
        holding["fee_basis_eligible"] = False
        touch(holding)
        calc.recompute_account(account)
        refresh_household(STORE.get("Household", account.get("household_id")))
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(holding), 200)


def _refresh_age(holding):
    as_of = holding.get("valuation_as_of_date")
    if as_of is None:
        holding["valuation_age_days"] = None
        holding["stale_valuation"] = False
        return
    age = days_between(STORE.clock.now_dt(), parse_dt(as_of))
    holding["valuation_age_days"] = age
    holding["stale_valuation"] = age > C.AGE_THRESHOLD_DAYS


def _duplicate_period_guard(holding):
    as_of = holding.get("valuation_as_of_date")
    if as_of is None:
        return
    target = parse_dt(as_of).date()
    for other in STORE.find("AlternativeAssetHolding", account_id=holding.get("account_id")):
        if other.get("id") == holding.get("id"):
            continue
        if other.get("asset_name") != holding.get("asset_name"):
            continue
        if other.get("asset_acceptance_status") != "ACCEPTED":
            continue
        other_as_of = other.get("valuation_as_of_date")
        if other_as_of is not None and parse_dt(other_as_of).date() == target:
            fail("ERR_DUPLICATE_VALUATION_PERIOD")


def _state_or_terminal(row, from_states, terminal_states):
    from core.context import STATE_FIELDS
    state = row.get(STATE_FIELDS.get(row.get("_entity")))
    if terminal_states and state in terminal_states:
        fail("ERR_ALREADY_TERMINAL")
    allowed = from_states if isinstance(from_states, (tuple, list, set)) else (from_states,)
    if state not in allowed:
        fail("ERR_INVALID_STATE")