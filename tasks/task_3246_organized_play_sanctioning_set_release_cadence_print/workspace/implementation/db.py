"""In-memory data store.

The store starts EMPTY on every boot. Nothing here seeds, preloads or
registers an entity: every row any caller needs is constructed through the
declared API surface (POST /op/stores, POST /op/formats, ...).
"""

import models as _models


class Db:
    def __init__(self):
        self.stores = {}
        self.set_releases = {}
        self.formats = {}
        self.event_applications = {}
        self.prize_allocations = {}
        self.prize_distributions = {}
        self.prize_reports = {}
        self.enforcement_cases = {}
        self.code_redemptions = {}
        self.product_configurations = {}
        self.allocation_orders = {}
        self.judge_certifications = {}
        self.reprint_plans = {}

        # format_id -> {set_release_id: epoch}. Populated when a set release
        # reaches its street date and every ACTIVE format gains an epoch entry
        # for it (§3.7); the epoch recorded is the one the format sat at, which
        # is the epoch the format must not have rotated past for the release to
        # stay legal for a sanctioned event.
        self.format_legal_sets = {}

        # Global monotonic sequences (§1.1): assigned at creation, never reset.
        self.redemption_seq = 0
        self.submitted_seq = 0

        # Payloads staged for a deferred event, applied at the end of a request.
        self.pending = None


db = Db()


# --------------------------------------------------------------------------
# Mutation helpers — every write to an EXISTING row refreshes updated_at and
# bumps version; row creation does not (a new row carries version 1).
# --------------------------------------------------------------------------

def touch(row, **changes):
    for key, value in changes.items():
        row[key] = value
    row["updated_at"] = _models.now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


# --------------------------------------------------------------------------
# Inserts
# --------------------------------------------------------------------------

def insert_store(name, region_code, daily_event_capacity, event_space_capacity):
    row = _models.new_store(name, region_code, daily_event_capacity, event_space_capacity)
    db.stores[row["id"]] = row
    return row


def insert_set_release(set_code, prerelease_start_date, prerelease_end_date, street_date):
    row = _models.new_set_release(set_code, prerelease_start_date,
                                  prerelease_end_date, street_date)
    db.set_releases[row["id"]] = row
    return row


def insert_format(name, format_code, rotation_policy):
    row = _models.new_format(name, format_code, rotation_policy)
    db.formats[row["id"]] = row
    return row


def insert_event_application(store_id, set_release_id, format_id, format_code, tier,
                             scheduled_date, expected_headcount):
    row = _models.new_event_application(store_id, set_release_id, format_id, format_code,
                                        tier, scheduled_date, expected_headcount)
    db.event_applications[row["id"]] = row
    return row


def insert_prize_allocation(store_id, event_application_id, tier, base_tp):
    row = _models.new_prize_allocation(store_id, event_application_id, tier, base_tp)
    db.prize_allocations[row["id"]] = row
    return row


def insert_prize_distribution(prize_allocation_id, recipient_ref, quantity):
    row = _models.new_prize_distribution(prize_allocation_id, recipient_ref, quantity)
    db.prize_distributions[row["id"]] = row
    return row


def insert_prize_report(event_application_id, prize_allocation_id, unclaimed_tp,
                        reported_headcount, status="FILED"):
    row = _models.new_prize_report(event_application_id, prize_allocation_id,
                                   unclaimed_tp, reported_headcount)
    row["status"] = status
    db.prize_reports[row["id"]] = row
    return row


def insert_enforcement_case(event_application_id, player_ref, judge_ref, offense_class,
                            rules_enforcement_level, repeated_offense):
    row = _models.new_enforcement_case(event_application_id, player_ref, judge_ref,
                                       offense_class, rules_enforcement_level,
                                       repeated_offense)
    db.enforcement_cases[row["id"]] = row
    return row


def insert_code_redemption(code_kind, redemption_code, event_application_id):
    row = _models.new_code_redemption(code_kind, redemption_code, event_application_id)
    db.code_redemptions[row["id"]] = row
    return row


def insert_product_configuration(set_release_id, configuration_kind, pack_count,
                                 print_run_units):
    row = _models.new_product_configuration(set_release_id, configuration_kind,
                                            pack_count, print_run_units)
    db.product_configurations[row["id"]] = row
    return row


def insert_allocation_order(distributor_name, product_configuration_id, quantity):
    row = _models.new_allocation_order(distributor_name, product_configuration_id, quantity)
    db.allocation_orders[row["id"]] = row
    return row


def insert_judge_certification(judge_ref, name, level):
    row = _models.new_judge_certification(judge_ref, name, level)
    db.judge_certifications[row["judge_ref"]] = row
    return row


def insert_reprint_plan(card_name, set_release_id, format_id, secondary_market_index,
                        first_print_index):
    row = _models.new_reprint_plan(card_name, set_release_id, format_id,
                                   secondary_market_index, first_print_index)
    db.reprint_plans[row["id"]] = row
    return row


# --------------------------------------------------------------------------
# Child lookups — one-to-many children live in their own dicts and are
# filtered by foreign key, so creating a child never mutates the parent.
# --------------------------------------------------------------------------

def distributions_of(allocation_id):
    return [d for d in db.prize_distributions.values()
            if d["prize_allocation_id"] == allocation_id]


def reports_of(allocation_id):
    return [r for r in db.prize_reports.values()
            if r["prize_allocation_id"] == allocation_id]


def reports_for_application(application_id):
    return [r for r in db.prize_reports.values()
            if r["event_application_id"] == application_id]


def applications_of_store(store_id):
    return [a for a in db.event_applications.values() if a["store_id"] == store_id]


def allocations_of_store(store_id):
    return [a for a in db.prize_allocations.values() if a["store_id"] == store_id]


def orders_of_configuration(config_id):
    return [o for o in db.allocation_orders.values()
            if o["product_configuration_id"] == config_id]


def redemptions_for_application(application_id):
    return [c for c in db.code_redemptions.values()
            if c["event_application_id"] == application_id]


def cases_of_store(store_id):
    """Enforcement cases whose associated application belongs to the store."""
    own = {a["id"] for a in applications_of_store(store_id)}
    return [c for c in db.enforcement_cases.values()
            if c["event_application_id"] in own]


def plans_of_format(format_id):
    return [p for p in db.reprint_plans.values() if p["format_id"] == format_id]


def plans_of_set_release(set_release_id):
    return [p for p in db.reprint_plans.values()
            if p["set_release_id"] == set_release_id]


def applications_of_set_release(set_release_id):
    return [a for a in db.event_applications.values()
            if a["set_release_id"] == set_release_id]


def applications_of_format(format_id):
    return [a for a in db.event_applications.values() if a["format_id"] == format_id]


def next_redemption_seq():
    db.redemption_seq += 1
    return db.redemption_seq


def next_submitted_seq():
    db.submitted_seq += 1
    return db.submitted_seq