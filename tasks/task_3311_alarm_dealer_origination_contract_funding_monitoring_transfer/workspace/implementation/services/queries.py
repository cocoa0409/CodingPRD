"""Cross-aggregate lookups used by the services."""

import db


def children_of_package(package_id):
    return [c for c in db.state.contracts.values() if c.get("dealer_package_id") == package_id]


def account_for_contract(contract_id):
    for account in db.state.monitoring_accounts.values():
        if account.get("contract_id") == contract_id:
            return account
    return None


def installation_for_contract(contract_id):
    rows = [i for i in db.state.installations.values() if i.get("contract_id") == contract_id]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows[0] if rows else None


def sites_for_contract(contract_id):
    return [s for s in db.state.sites.values() if s.get("contract_id") == contract_id]


def current_site_for_contract(contract_id):
    for site in sites_for_contract(contract_id):
        if site.get("occupancy_status") == "OCCUPIED":
            return site
    return None


def current_owner_for_contract(contract_id):
    for owner in db.state.contract_owners.values():
        if owner.get("contract_id") == contract_id and owner.get("ownership_status") == "CURRENT":
            return owner
    return None


def owners_for_contract(contract_id):
    return [o for o in db.state.contract_owners.values() if o.get("contract_id") == contract_id]


def open_service_required(contract_id):
    account = account_for_contract(contract_id)
    if account is None:
        return None
    for action in db.state.alarm_reduction_actions.values():
        if action.get("monitoring_account_id") == account["id"] \
                and action.get("action_type") == "SERVICE_REQUIRED" \
                and action.get("action_status") == "OPEN":
            return action
    return None


def open_service_required_account(account_id):
    for action in db.state.alarm_reduction_actions.values():
        if action.get("monitoring_account_id") == account_id \
                and action.get("action_type") == "SERVICE_REQUIRED" \
                and action.get("action_status") == "OPEN":
            return action
    return None


def open_reduction_actions(account_id):
    return [a for a in db.state.alarm_reduction_actions.values()
            if a.get("monitoring_account_id") == account_id and a.get("action_status") == "OPEN"]


def active_contracts_for_dealer(dealer_id):
    return [c for c in db.state.contracts.values()
            if c.get("dealer_id") == dealer_id and c.get("contract_status") == "ACTIVE"]


def dispatched_for_account(account_id):
    alarm_ids = {a["id"] for a in db.state.alarm_events.values()
                 if a.get("monitoring_account_id") == account_id}
    return [d for d in db.state.dispatch_requests.values() if d.get("alarm_event_id") in alarm_ids]


def customer_has_other_live_contract(customer_id, exclude_contract_id):
    for c in db.state.contracts.values():
        if c["id"] == exclude_contract_id:
            continue
        if c.get("customer_id") == customer_id and c.get("contract_status") in ("ACTIVE", "DELINQUENT"):
            return True
    return False


def customer_has_any_other_non_terminal(customer_id, exclude_contract_id):
    for c in db.state.contracts.values():
        if c["id"] == exclude_contract_id:
            continue
        if c.get("customer_id") == customer_id and c.get("contract_status") not in ("CANCELLED", "ASSUMED"):
            return True
    return False


def sorted_by_created(rows):
    return sorted(rows, key=lambda r: r.get("created_at", ""))