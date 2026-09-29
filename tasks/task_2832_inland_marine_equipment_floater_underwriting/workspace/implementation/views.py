"""Serialisation: every `computed` field is derived at read time."""
import rating
import store


def premium_balance(policy):
    return sum(e["amount_cents"] for e in store.entries_of_policy(policy["id"])
               if e["ledger"] == "PREMIUM")


def incurred_loss(policy):
    return sum(e["amount_cents"] for e in store.entries_of_policy(policy["id"])
               if e["ledger"] == "LOSS")


def aggregate_paid_net(part):
    total = 0
    for claim in store.claims_of_part(part["id"]):
        total += claim.get("settlement_paid_cents") or 0
        total -= claim.get("salvage_credit_cents") or 0
    return total


def aggregate_available(part):
    return part["aggregate_limit_cents"] - aggregate_paid_net(part)


def earned_reported_premium(part):
    return sum(r["period_earned_premium_cents"] or 0
               for r in store.reports_of_part(part["id"])
               if r["status"] in ("ACCEPTED", "PENALIZED"))


def latest_report_period_end_date(part):
    best = None
    for report in store.reports_of_part(part["id"]):
        if report["status"] not in ("SUBMITTED", "ACCEPTED", "PENALIZED", "DELINQUENT"):
            continue
        key = (report["period_end_date"], report["created_at"], report["_seq"])
        if best is None or key > best:
            best = key
    return best[0] if best else None


def active_floater_count(jobsite):
    return len([f for f in store.installation_floaters.values()
                if f["jobsite_id"] == jobsite["id"]
                and f["status"] in ("PENDING", "ACTIVE")])


def in_transit_value(vehicle):
    return sum(s["declared_value_cents"] for s in store.transit_shipments.values()
               if s["vehicle_id"] == vehicle["id"] and s["status"] == "IN_TRANSIT")


def policy_view(policy):
    out = store.serialize(policy)
    out["term_days"] = rating.policy_term_days(policy)
    out["premium_balance_cents"] = premium_balance(policy)
    out["incurred_loss_cents"] = incurred_loss(policy)
    return out


def part_view(part):
    out = store.serialize(part)
    out["aggregate_paid_net_cents"] = aggregate_paid_net(part)
    out["aggregate_available_cents"] = aggregate_available(part)
    out["earned_reported_premium_cents"] = earned_reported_premium(part)
    latest = latest_report_period_end_date(part)
    out["latest_report_period_end_date"] = store._scalar(latest)
    return out


def rate_rule_view(rule):
    return store.serialize(rule)


def item_view(item):
    return store.serialize(item)


def jobsite_view(jobsite):
    out = store.serialize(jobsite)
    out["active_floater_count"] = active_floater_count(jobsite)
    return out


def floater_view(floater):
    return store.serialize(floater)


def vehicle_view(vehicle):
    out = store.serialize(vehicle)
    out["in_transit_value_cents"] = in_transit_value(vehicle)
    return out


def shipment_view(shipment):
    return store.serialize(shipment)


def report_view(report):
    return store.serialize(report)


def claim_view(claim):
    return store.serialize(claim)


def entry_view(entry):
    return store.serialize(entry)
