"""Row factories and serializers.

Every top-level resource carries the same four system-managed fields (§2.8):
`id`, `created_at`, `updated_at` and `version`. `version` starts at 1 at
creation and increments by one on every modification, including modifications
the server performs on the client's behalf.

The `db` import is deliberately deferred into the functions: `db` imports this
module for its row factories, so a module-level import here would be circular.
"""

from utils import new_id, now_iso, to_iso


def _common():
    stamp = now_iso()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }


# --------------------------------------------------------------------------
# Row factories — one per entity. `source: system` fields are initialized to
# their declared starting values; `source: computed` fields are never stored
# here because they are recomputed on every read.
# --------------------------------------------------------------------------

def new_store(name, region_code, daily_event_capacity, event_space_capacity):
    row = _common()
    row.update({
        "name": name,
        "region_code": region_code,
        "reporting_tier": "STANDARD",
        "daily_event_capacity": daily_event_capacity,
        "event_space_capacity": event_space_capacity,
        "status": "ACTIVE",
    })
    return row


def new_set_release(set_code, prerelease_start_date, prerelease_end_date, street_date):
    row = _common()
    row.update({
        "set_code": set_code,
        "prerelease_start_date": prerelease_start_date,
        "prerelease_end_date": prerelease_end_date,
        "street_date": street_date,
        "status": "ANNOUNCED",
    })
    return row


def new_format(name, format_code, rotation_policy):
    row = _common()
    row.update({
        "name": name,
        "format_code": format_code,
        "rotation_policy": rotation_policy,
        "current_epoch": 0,
        "banned_card_refs": [],
        "restricted_card_refs": [],
    })
    return row


def new_event_application(store_id, set_release_id, format_id, format_code, tier,
                          scheduled_date, expected_headcount):
    row = _common()
    row.update({
        "store_id": store_id,
        "set_release_id": set_release_id,
        "format_id": format_id,
        "format_code": format_code,
        "tier": tier,
        "scheduled_date": scheduled_date,
        "expected_headcount": expected_headcount,
        "status": "SUBMITTED",
        "prizing_report_status": "NOT_DUE",
        "reporting_due_by": None,
        "prize_allocation_id": None,
        "prize_report_id": None,
    })
    return row


def new_prize_allocation(store_id, event_application_id, tier, base_tp):
    row = _common()
    row.update({
        "store_id": store_id,
        "event_application_id": event_application_id,
        "tier": tier,
        "base_tp": base_tp,
        "remaining_tp": base_tp,
        "total_drawn_tp": 0,
        "total_restored_tp": 0,
        "status": "OPEN",
    })
    return row


def new_prize_distribution(prize_allocation_id, recipient_ref, quantity):
    row = _common()
    row.update({
        "prize_allocation_id": prize_allocation_id,
        "recipient_ref": recipient_ref,
        "quantity": quantity,
        "status": "PROPOSED",
    })
    return row


def new_prize_report(event_application_id, prize_allocation_id, unclaimed_tp,
                     reported_headcount):
    row = _common()
    row.update({
        "event_application_id": event_application_id,
        "prize_allocation_id": prize_allocation_id,
        "unclaimed_tp": unclaimed_tp,
        "reported_headcount": reported_headcount,
        "status": "FILED",
    })
    return row


def new_enforcement_case(event_application_id, player_ref, judge_ref, offense_class,
                         rules_enforcement_level, repeated_offense):
    row = _common()
    row.update({
        "event_application_id": event_application_id,
        "player_ref": player_ref,
        "judge_ref": judge_ref,
        "offense_class": offense_class,
        "rules_enforcement_level": rules_enforcement_level,
        "repeated_offense": repeated_offense,
        "penalty_points": 0,
        "current_points": 0,
        "status": "FILED",
    })
    return row


def new_code_redemption(code_kind, redemption_code, event_application_id):
    row = _common()
    row.update({
        "code_kind": code_kind,
        "redemption_code": redemption_code,
        "event_application_id": event_application_id,
        "redemption_seq": None,
        "status": "AVAILABLE",
        "physical_grant_status": "NOT_APPLICABLE",
        "prize_allocation_id": None,
    })
    return row


def new_product_configuration(set_release_id, configuration_kind, pack_count,
                              print_run_units):
    row = _common()
    row.update({
        "set_release_id": set_release_id,
        "configuration_kind": configuration_kind,
        "pack_count": pack_count,
        "print_run_units": print_run_units,
        "units_allocated": 0,
    })
    return row


def new_allocation_order(distributor_name, product_configuration_id, quantity):
    row = _common()
    row.update({
        "distributor_name": distributor_name,
        "product_configuration_id": product_configuration_id,
        "quantity": quantity,
        "submitted_seq": None,
        "status": "PENDING",
        "approval_rank": None,
        "fulfilled_qty": 0,
    })
    return row


def new_judge_certification(judge_ref, name, level):
    row = _common()
    row.update({
        "judge_ref": judge_ref,
        "name": name,
        "level": level,
        "status": "ACTIVE",
        "practice_events": 0,
    })
    return row


def new_reprint_plan(card_name, set_release_id, format_id, secondary_market_index,
                     first_print_index):
    row = _common()
    row.update({
        "card_name": card_name,
        "set_release_id": set_release_id,
        "format_id": format_id,
        "secondary_market_index": secondary_market_index,
        "first_print_index": first_print_index,
        "verdict": None,
        "status": "DRAFT",
    })
    return row


# --------------------------------------------------------------------------
# Derived (source: computed) fields. None of these are stored columns, and
# evaluating them never mutates the row (§2.8).
# --------------------------------------------------------------------------

def units_allocated(config_id):
    """Sum of fulfilled_qty over orders in APPROVED or PARTIALLY_FULFILLED."""
    import db
    return sum(
        o["fulfilled_qty"] for o in db.db.allocation_orders.values()
        if o["product_configuration_id"] == config_id
        and o["status"] in ("APPROVED", "PARTIALLY_FULFILLED")
    )


def units_available(config_id):
    import db
    config = db.db.product_configurations.get(config_id)
    if config is None:
        return 0
    return config["print_run_units"] - units_allocated(config_id)


def approval_rank(order_id):
    """Queue position over orders that cannot be satisfied in full right now.

    Candidates: status IN {PENDING, PARTIALLY_FULFILLED} and
    quantity > units_available, ordered by submitted_seq ascending (§3.12).
    An order whose request fits inside current availability is not a candidate
    and does not appear in the queue at all.
    """
    import db
    order = db.db.allocation_orders.get(order_id)
    if order is None:
        return None
    if order["status"] not in ("PENDING", "PARTIALLY_FULFILLED"):
        return None
    config_id = order["product_configuration_id"]
    available = units_available(config_id)
    if order["quantity"] <= available:
        return None
    candidates = [
        o for o in db.db.allocation_orders.values()
        if o["product_configuration_id"] == config_id
        and o["status"] in ("PENDING", "PARTIALLY_FULFILLED")
        and o["quantity"] > available
    ]
    candidates.sort(key=lambda o: o["submitted_seq"])
    for index, candidate in enumerate(candidates, start=1):
        if candidate["id"] == order_id:
            return index
    return None


def promotion_eligible(judge_ref):
    """True exactly when level is LEVEL_2 and practice_events >= 5 (§3.10)."""
    import db
    judge = db.db.judge_certifications.get(judge_ref)
    if judge is None:
        return False
    return judge["level"] == "LEVEL_2" and judge["practice_events"] >= 5


# --------------------------------------------------------------------------
# Serializers — stored values plus the computed fields of each entity, with
# datetimes rendered as ISO 8601 UTC at whole-second precision.
# --------------------------------------------------------------------------

def store_view(row):
    import computed
    view = dict(row)
    view["reporting_tier"] = computed.store_reporting_tier(row["id"])
    view["tp_balance"] = computed.store_tp_balance(row["id"])
    view["reporting_violation_points"] = computed.store_reporting_violation_points(row["id"])
    return view


def set_release_view(row):
    view = dict(row)
    view["prerelease_start_date"] = to_iso(row["prerelease_start_date"])
    view["prerelease_end_date"] = to_iso(row["prerelease_end_date"])
    view["street_date"] = to_iso(row["street_date"])
    return view


def format_view(row):
    view = dict(row)
    view["banned_card_refs"] = list(row["banned_card_refs"])
    view["restricted_card_refs"] = list(row["restricted_card_refs"])
    return view


def event_application_view(row):
    view = dict(row)
    view["scheduled_date"] = to_iso(row["scheduled_date"])
    view["reporting_due_by"] = to_iso(row["reporting_due_by"])
    return view


def prize_allocation_view(row):
    import computed
    view = dict(row)
    view["remaining_tp"] = computed.prize_pool_remaining(row)
    return view


def prize_distribution_view(row):
    return dict(row)


def prize_report_view(row):
    return dict(row)


def enforcement_case_view(row):
    return dict(row)


def code_redemption_view(row):
    return dict(row)


def product_configuration_view(row):
    view = dict(row)
    view["units_allocated"] = units_allocated(row["id"])
    view["units_available"] = view["print_run_units"] - view["units_allocated"]
    return view


def allocation_order_view(row):
    view = dict(row)
    view["approval_rank"] = approval_rank(row["id"])
    return view


def judge_view(row):
    view = dict(row)
    view["promotion_eligible"] = promotion_eligible(row["judge_ref"])
    return view


def reprint_plan_view(row):
    return dict(row)