"""The clock sweep: four families of expirable rows in one pass (PRD 3.10)."""

import domain_dispense
import domain_donor
from store import db, find, set_field
from util import add_days, parse_date


def sweep():
    today = db.clock_date()

    for approval in db.rows("approvals"):
        if approval["status"] != "ACTIVE":
            continue
        valid_until = parse_date(approval["valid_until"])
        if valid_until is not None and valid_until < today:
            set_field(approval, "status", "EXPIRED")

    for lot in db.rows("lots"):
        if lot["release_status"] != "HOLD":
            continue
        expiration = parse_date(lot["expiration_date"])
        if expiration is not None and expiration < today:
            set_field(lot, "release_status", "EXPIRED")

    touched_tiers = set()
    for prescription in db.rows("prescriptions"):
        if prescription["status"] not in ("QUEUED", "PARTIALLY_FILLED"):
            continue
        needed_by = parse_date(prescription["needed_by_date"])
        if needed_by is not None and needed_by < today:
            set_field(prescription, "status", "EXPIRED")
            set_field(prescription, "waitlist_position", None)
            touched_tiers.add(prescription["priority_tier"])
    for tier in sorted(touched_tiers):
        domain_dispense.renumber_tier(tier)

    touched_donors = set()
    for event in db.rows("deferrals"):
        if event["status"] != "ACTIVE" or event["deferral_type"] != "TEMPORARY":
            continue
        effective_from = parse_date(event["effective_from"])
        if effective_from is None:
            continue
        if add_days(effective_from, event["deferral_days"]) < today:
            set_field(event, "status", "EXPIRED")
            touched_donors.add(event["donor_id"])
    for donor_id in touched_donors:
        donor = find("donors", donor_id)
        if donor is not None:
            domain_donor.refresh_active_deferral_until(donor)
