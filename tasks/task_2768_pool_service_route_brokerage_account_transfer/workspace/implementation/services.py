"""Lookups, roll-ups and cascades shared by the route modules."""

from datetime import datetime, time, timezone

from calc import (ROUTE_DAY_RANK, allowance_for, attrition_ledger, claimed_recurring_mrr,
                  account_age_months, parse_date, reprice_threshold, valuation_figures)
from errors import ApiError
from store import new_record, ordered, store, touch


# ---------------------------------------------------------------- lookups
def _found(collection, identifier, error_id):
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id, "No such record: %s" % identifier)
    return record


def get_listing(identifier):
    return _found(store.route_listings, identifier, "ERR_LISTING_NOT_FOUND")


def get_account(identifier):
    return _found(store.service_accounts, identifier, "ERR_ACCOUNT_NOT_FOUND")


def get_deal(identifier):
    return _found(store.deals, identifier, "ERR_DEAL_NOT_FOUND")


def get_escrow(identifier):
    return _found(store.escrow_accounts, identifier, "ERR_ESCROW_NOT_FOUND")


def get_settlement(identifier):
    return _found(store.clawback_settlements, identifier, "ERR_SETTLEMENT_NOT_FOUND")


def get_seller(identifier):
    return _found(store.sellers, identifier, "ERR_PARTY_NOT_FOUND")


def get_buyer(identifier):
    return _found(store.buyers, identifier, "ERR_PARTY_NOT_FOUND")


def get_profile(identifier):
    return _found(store.state_license_profiles, identifier, "ERR_LICENSE_PROFILE_NOT_FOUND")


def get_transfer(identifier):
    return _found(store.license_transfers, identifier, "ERR_LICENSE_TRANSFER_NOT_FOUND")


def get_valuation(identifier):
    return _found(store.route_valuations, identifier, "ERR_VALUATION_NOT_FOUND")


def get_billing_record(identifier):
    return _found(store.billing_history_records, identifier, "ERR_BILLING_RECORD_NOT_FOUND")


def get_event(identifier):
    return _found(store.attrition_events, identifier, "ERR_ATTRITION_EVENT_NOT_FOUND")


def profile_for_state(state_code):
    for profile in store.state_license_profiles.values():
        if profile["state_code"] == state_code:
            return profile
    return None


def listing_of_account(account):
    return store.route_listings.get(account["listing_id"])


def listing_of_deal(deal):
    return store.route_listings.get(deal["listing_id"])


def escrow_of_deal(deal):
    for escrow in ordered(store.escrow_accounts):
        if escrow["deal_id"] == deal["id"]:
            return escrow
    return None


def accounts_of_listing(listing_id):
    return ordered(store.service_accounts, lambda a: a["listing_id"] == listing_id)


def transfers_of_deal(deal_id):
    return ordered(store.license_transfers, lambda t: t["deal_id"] == deal_id)


def permits_cleared(deal_id):
    for transfer in transfers_of_deal(deal_id):
        if transfer["status"] not in ("APPROVED", "WAIVED"):
            return False
    return True


def midnight(value):
    """A stored date taken at 00:00:00Z on that date."""
    if isinstance(value, str):
        value = parse_date(value)
    return datetime.combine(value, time(0, 0, 0), tzinfo=timezone.utc)


# ---------------------------------------------------------------- exclusivity
def exclusivity_conflict(seller_id, region_code, start_date, end_date, exclude_listing_id=None):
    """Half-open [start, end) intervals per seller and region; touching is allowed."""
    new_start = parse_date(start_date)
    new_end = parse_date(end_date)
    for listing in store.route_listings.values():
        if exclude_listing_id is not None and listing["id"] == exclude_listing_id:
            continue
        if listing["seller_id"] != seller_id or listing["region_code"] != region_code:
            continue
        if listing["status"] == "WITHDRAWN":
            continue
        other_start = parse_date(listing["exclusive_start_date"])
        other_end = parse_date(listing["exclusive_end_date"])
        if new_start < other_end and other_start < new_end:
            return True
    return False


# ---------------------------------------------------------------- listing roll-ups
def verification_posture(accounts):
    # PRD §3.2: EMPTY when no stop is VERIFIED, INCOMPLETE when at least one stop is
    # UNVERIFIED or DISPUTED, COMPLETE when every stop is VERIFIED or EXCLUDED with at
    # least one verified. PRD §3.3 pins the overlap: "on the two edges that land in
    # DISPUTED the listing's posture is recomputed to INCOMPLETE", so a DISPUTED stop
    # lifts the listing out of EMPTY even while no stop has reached VERIFIED.
    verified = [a for a in accounts if a["verification_status"] == "VERIFIED"]
    disputed = [a for a in accounts if a["verification_status"] == "DISPUTED"]
    if not verified and not disputed:
        return "EMPTY"
    for account in accounts:
        if account["verification_status"] in ("UNVERIFIED", "DISPUTED"):
            return "INCOMPLETE"
    return "COMPLETE"


def recompute_listing(listing, bump=True):
    accounts = accounts_of_listing(listing["id"])
    included = [a for a in accounts if a["verification_status"] != "EXCLUDED"]
    verified = [a for a in accounts if a["verification_status"] == "VERIFIED"]
    listing["claimed_recurring_mrr_cents"] = sum(a["claimed_recurring_mrr_cents"] for a in included)
    listing["claimed_repair_mrr_cents"] = sum(a["avg_monthly_repair_cents"] for a in included)
    listing["claimed_account_count"] = len(included)
    listing["verified_recurring_mrr_cents"] = sum((a["verified_recurring_mrr_cents"] or 0) for a in verified)
    listing["verified_repair_mrr_cents"] = sum((a["verified_repair_mrr_cents"] or 0) for a in verified)
    listing["verified_account_count"] = len(verified)
    listing["verification_posture"] = verification_posture(accounts)
    listing["introductions_completed_count"] = len(
        [a for a in accounts if a["transfer_status"] in ("INTRODUCED", "TRANSFERRED", "LOST", "REPLACED")])
    if bump:
        touch(listing)


# ---------------------------------------------------------------- valuations
def valuation_inputs(listing_id, basis):
    inputs = []
    for account in accounts_of_listing(listing_id):
        if basis == "LISTED_BASIS":
            if account["verification_status"] == "EXCLUDED":
                continue
            recurring = account["claimed_recurring_mrr_cents"]
            repair = account["avg_monthly_repair_cents"]
        else:
            if account["verification_status"] != "VERIFIED":
                continue
            recurring = account["verified_recurring_mrr_cents"] or 0
            repair = account["verified_repair_mrr_cents"] or 0
        inputs.append((recurring, repair, account_age_months(store.clock, account["service_start_date"])))
    return inputs


def live_valuation(listing_id, basis):
    live = [v for v in ordered(store.route_valuations)
            if v["listing_id"] == listing_id and v["basis"] == basis and not v["is_superseded"]]
    return live[-1] if live else None


def supersede_valuations(listing_id, basis):
    for valuation in ordered(store.route_valuations):
        if (valuation["listing_id"] == listing_id and valuation["basis"] == basis
                and not valuation["is_superseded"]):
            valuation["is_superseded"] = True
            touch(valuation)


def write_valuation(listing_id, basis, inputs):
    figures = valuation_figures(inputs)
    record = new_record()
    record.update({"listing_id": listing_id, "basis": basis, "is_superseded": False,
                   "computed_from_clock_utc": store.clock})
    record.update(figures)
    store.route_valuations[record["id"]] = record
    return record


def create_valuation(listing, basis):
    """Snapshot creation: an empty input set is ERR_NO_VALUATION_INPUTS."""
    inputs = valuation_inputs(listing["id"], basis)
    if not inputs:
        raise ApiError("ERR_NO_VALUATION_INPUTS",
                       "The requested valuation basis selects no accounts at all.")
    supersede_valuations(listing["id"], basis)
    return write_valuation(listing["id"], basis, inputs)


# ---------------------------------------------------------------- diligence cascade
def diligence_cascade(listing):
    """Hops 3 to 5 of PRD section 3.6, after a VERIFIED stop was excluded and
    the listing roll-ups were recomputed."""
    if live_valuation(listing["id"], "VERIFIED_BASIS") is None:
        return
    supersede_valuations(listing["id"], "VERIFIED_BASIS")
    inputs = valuation_inputs(listing["id"], "VERIFIED_BASIS")
    if not inputs:
        return
    fresh = write_valuation(listing["id"], "VERIFIED_BASIS", inputs)
    for deal in ordered(store.deals, lambda d: d["listing_id"] == listing["id"]):
        if deal["status"] not in ("ACCEPTED", "DILIGENCE_CLEARED"):
            continue
        if fresh["valuation_cents"] >= reprice_threshold(deal["current_offer_price_cents"]):
            continue
        deal["status"] = "REPRICE_REQUIRED"
        deal["repricing_reason_code"] = "VERIFIED_VALUATION_BELOW_OFFER"
        touch(deal)
        escrow = escrow_of_deal(deal)
        if escrow is not None and escrow["status"] == "OPEN":
            escrow["target_amount_cents"] = 0
            escrow["deposits_blocked"] = True
            touch(escrow)


# ---------------------------------------------------------------- deal ledger
def events_of_deal(deal_id):
    return ordered(store.attrition_events, lambda e: e["deal_id"] == deal_id)


def events_in_guarantee_window(deal):
    start = deal.get("guarantee_start_utc")
    end = deal.get("guarantee_end_utc")
    if start is None or end is None:
        return []
    rows = []
    for event in events_of_deal(deal["id"]):
        moment = midnight(event["effective_date"])
        if start <= moment < end:
            rows.append(event)
    return rows


def replacement_mrr_of_deal(deal):
    total = 0
    for account in ordered(store.service_accounts, lambda a: a["deal_id"] == deal["id"]):
        if account["replaced_account_id"] and account["transfer_status"] == "TRANSFERRED":
            total += account["claimed_recurring_mrr_cents"]
    return total


def recompute_deal_ledger(deal, bump=True):
    """Recomputed from scratch on every append and every replacement."""
    guaranteed = deal.get("guaranteed_mrr_cents") or 0
    ledger = attrition_ledger(events_in_guarantee_window(deal), guaranteed,
                              replacement_mrr_of_deal(deal))
    deal["attrited_mrr_cents"] = ledger["attrited_mrr_cents"]
    deal["retained_mrr_cents"] = ledger["retained_mrr_cents"]
    deal["replacement_mrr_cents"] = ledger["replacement_mrr_cents"]
    deal["net_attrition_mrr_cents"] = ledger["net_attrition_mrr_cents"]
    deal["allowance_mrr_cents"] = ledger["allowance_mrr_cents"]
    deal["attrition_pct"] = ledger["attrition_pct"]

    if deal["clawback_status"] != "SETTLED":
        escrow = escrow_of_deal(deal)
        if ledger["triggered"]:
            deal["clawback_status"] = "CLAWBACK_TRIGGERED"
            if escrow is not None and (not escrow["holdback_release_blocked"]
                                      or escrow["scheduled_holdback_release_utc"] is not None):
                escrow["holdback_release_blocked"] = True
                escrow["scheduled_holdback_release_utc"] = None
                touch(escrow)
        else:
            deal["clawback_status"] = "MONITORING"
            scheduled = deal.get("holdback_release_utc")
            if escrow is not None and (escrow["holdback_release_blocked"]
                                      or escrow["scheduled_holdback_release_utc"] != scheduled):
                escrow["holdback_release_blocked"] = False
                escrow["scheduled_holdback_release_utc"] = scheduled
                touch(escrow)
    if bump:
        touch(deal)
    return ledger


def live_ledger(deal):
    """The ledger figures without writing anything (used by settlement snapshots)."""
    guaranteed = deal.get("guaranteed_mrr_cents") or 0
    return attrition_ledger(events_in_guarantee_window(deal), guaranteed,
                            replacement_mrr_of_deal(deal))


# ---------------------------------------------------------------- introductions
def introduction_queue(listing_id):
    """route_day rank, then service_start_date, then created_at (PRD section 3.8)."""
    queue = [a for a in accounts_of_listing(listing_id)
             if a["verification_status"] in ("UNVERIFIED", "VERIFIED", "DISPUTED")
             and a["transfer_status"] == "PENDING"]
    queue.sort(key=lambda a: (ROUTE_DAY_RANK[a["route_day"]], a["service_start_date"],
                              a["created_at"], a["_seq"]))
    return queue


def customer_ref_taken(listing_id, customer_ref):
    for account in store.service_accounts.values():
        if account["listing_id"] == listing_id and account["customer_ref"] == customer_ref:
            return True
    return False


def build_account(listing_id, data, deal_id=None, replaced_account_id=None,
                  verification_status="UNVERIFIED", transfer_status="PENDING"):
    record = new_record()
    claimed = claimed_recurring_mrr(data["monthly_service_fee_cents"],
                                    data["avg_monthly_chemical_cents"],
                                    data["chemical_billing_method"],
                                    data["billing_frequency"])
    record.update({
        "listing_id": listing_id,
        "deal_id": deal_id,
        "replaced_account_id": replaced_account_id,
        "customer_ref": data["customer_ref"],
        "service_start_date": data["service_start_date"],
        "route_day": data["route_day"],
        "monthly_service_fee_cents": data["monthly_service_fee_cents"],
        "avg_monthly_chemical_cents": data["avg_monthly_chemical_cents"],
        "avg_monthly_repair_cents": data["avg_monthly_repair_cents"],
        "chemical_billing_method": data["chemical_billing_method"],
        "billing_frequency": data["billing_frequency"],
        "claimed_recurring_mrr_cents": claimed,
        "verified_recurring_mrr_cents": None,
        "verified_repair_mrr_cents": None,
        "verification_variance": None,
        "verification_status": verification_status,
        "transfer_status": transfer_status,
        "introduction_sequence_no": None,
        "introduced_on": None,
        "current_mrr_cents": None,
        "exclusion_reason_code": None,
        "verified_by_user_id": None,
    })
    store.service_accounts[record["id"]] = record
    return record


def allowance_of(guaranteed_mrr_cents):
    return allowance_for(guaranteed_mrr_cents)
