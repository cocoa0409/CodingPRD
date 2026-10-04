"""Advisor technology data feed provisions and the custodian research lookup."""

from core.context import body, check_if_match, need
from core.errors import fail
from core.response import ok, paginate
from core.store import STORE
from domain import calc
from domain.guards import firm_active_guard, invariant_guard, require_any_entitlement
from domain.model import create, serialize, touch
from domain.resolve import sorted_rows
from routes._base import load, load_firm, params


def register(api):

    @api.route("/ria/data-feeds", methods=["POST"], roles=["AdvisorOperationsLead"])
    def create_feed():
        data = body()
        firm = load_firm(need(data, "firm_id"))
        firm_active_guard(firm)
        row = create("DataFeedProvision",
                     firm_id=firm.get("id"),
                     feed_type=need(data, "feed_type"),
                     provision_status="REQUESTED",
                     provisioned_records_count=0,
                     delivery_endpoint_host=data.get("delivery_endpoint_host"),
                     throttle_reason_code=None,
                     last_delivered_at=None,
                     delivered_count=0)
        return ok(serialize(row), 201)

    @api.route("/ria/firms/<firm_id>/data-feeds", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_feeds(firm_id):
        load_firm(firm_id)
        p = params()
        rows = sorted_rows("DataFeedProvision", {"firm_id": firm_id,
                                                 "provision_status": p.get("provision_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/data-feeds/<feed_id>/provision", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def provision_feed(feed_id):
        feed = load("DataFeedProvision", feed_id)
        data = body()
        check_if_match(feed, data)
        firm = load_firm(feed.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(feed, ("REQUESTED",), ("REVOKED",))
        require_any_entitlement(firm, ("DATA_FEED",))
        invariant_guard(firm)
        if firm.get("firm_posture") != "OPEN":
            fail("ERR_FIRM_NOT_OPEN_FOR_TRADING")
        feed["provision_status"] = "ACTIVE"
        feed["throttle_reason_code"] = None
        touch(feed)
        return ok(serialize(feed), 200)

    @api.route("/ria/data-feeds/<feed_id>/revoke", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def revoke_feed(feed_id):
        feed = load("DataFeedProvision", feed_id)
        data = body()
        check_if_match(feed, data)
        firm = load_firm(feed.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(feed, ("THROTTLED", "ACTIVE"), ("REVOKED",))
        feed["provision_status"] = "REVOKED"
        touch(feed)
        return ok(serialize(feed), 200)

    @api.route("/ria/data-feeds/<feed_id>/pull", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=False)
    def pull_feed(feed_id):
        feed = load("DataFeedProvision", feed_id)
        firm = load_firm(feed.get("firm_id"))
        firm_active_guard(firm)
        if feed.get("provision_status") == "THROTTLED":
            fail("ERR_FEED_THROTTLED")
        if feed.get("provision_status") != "ACTIVE":
            fail("ERR_INVALID_STATE")
        p = params()
        delivered = p.limit
        feed["delivered_count"] = delivered
        feed["provisioned_records_count"] = int(feed.get("provisioned_records_count") or 0) + delivered
        feed["last_delivered_at"] = STORE.clock.now()
        touch(feed)
        return ok(serialize(feed), 200)

    # --------------------------------------------- custodian research probe

    @api.route("/ria/lookup/lot-inventory", methods=["POST"], roles=["CustodyOperationsOfficer"])
    def lot_inventory():
        data = body()
        account = load("HouseholdAccount", need(data, "account_id"))
        symbol = need(data, "symbol")
        lookback = int(data.get("lookback_days") or 0)
        highest = 0
        for lot in calc.account_positions(account):
            if lot.get("symbol") != symbol:
                continue
            highest = max(highest, int(lot.get("quantity_micros") or 0))
        card = {
            "account_id": account.get("id"),
            "symbol": symbol,
            "lookback_days": lookback,
            "highest_shares_held_micros": highest,
        }
        return ok(card, 200)


def _state_or_terminal(row, from_states, terminal_states):
    from core.context import STATE_FIELDS
    state = row.get(STATE_FIELDS.get(row.get("_entity")))
    if terminal_states and state in terminal_states:
        fail("ERR_ALREADY_TERMINAL")
    allowed = from_states if isinstance(from_states, (tuple, list, set)) else (from_states,)
    if state not in allowed:
        fail("ERR_INVALID_STATE")