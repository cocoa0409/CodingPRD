"""Collection lookups.  Every list is returned in created_at ascending order."""

import domain
from store import db, ordered


def _by(collection, field, value):
    return ordered([r for r in collection.values() if r[field] == value])


def commitments_of_opportunity(opportunity_id):
    return _by(db.commitments, "opportunity_id", opportunity_id)


def commitments_of_hotel(hotel_id):
    return _by(db.commitments, "hotel_id", hotel_id)


def holds_of_opportunity(opportunity_id):
    return _by(db.space_holds, "opportunity_id", opportunity_id)


def holds_of_hall(hall_id):
    return _by(db.space_holds, "center_hall_id", hall_id)


def pickups_of_commitment(commitment_id):
    return _by(db.pickup_records, "room_block_commitment_id", commitment_id)


def packages_of_opportunity(opportunity_id):
    return _by(db.bid_packages, "opportunity_id", opportunity_id)


def letters_of_package(bid_package_id):
    return _by(db.support_letters, "bid_package_id", bid_package_id)


def decisions_of_package(bid_package_id):
    return _by(db.decisions, "bid_package_id", bid_package_id)


def decisions_of_fund(fund_id):
    return _by(db.decisions, "fund_id", fund_id)


def receipts_of_fund(fund_id):
    return _by(db.receipts, "fund_id", fund_id)


def estimates_of_opportunity(opportunity_id):
    return _by(db.estimates, "opportunity_id", opportunity_id)


def servicing_orders_of_opportunity(opportunity_id):
    return _by(db.servicing_orders, "opportunity_id", opportunity_id)


def opportunities_of_planner(planner_id):
    return _by(db.opportunities, "planner_id", planner_id)


def live_package(opportunity_id):
    """The at-most-one package of a lead still in DRAFT, INCENTIVE_PENDING,
    APPROVED or SUBMITTED (PRD 3.7)."""
    for row in packages_of_opportunity(opportunity_id):
        if row["status"] in domain.LIVE_BID_STATUSES:
            return row
    return None


def charged_package(opportunity_id):
    """The package carrying the lead's live fund charge -- the charge sits in the
    fund's committed pool from the approving decision until it is decommitted or
    disbursed (PRD 2.10)."""
    for row in packages_of_opportunity(opportunity_id):
        if row.get("_charge_live"):
            return row
    return None


def newest_provisional_estimate(opportunity_id):
    """The estimate with the highest created_at, ties broken in favour of the
    PROVISIONAL variant (PRD 3.6)."""
    rows = [r for r in estimates_of_opportunity(opportunity_id)
            if r["variant"] == "PROVISIONAL"]
    if not rows:
        return None
    return rows[-1]


def active_holds_of_opportunity(opportunity_id):
    return [h for h in holds_of_opportunity(opportunity_id)
            if h["status"] in domain.ACTIVE_HOLD_STATUSES]
