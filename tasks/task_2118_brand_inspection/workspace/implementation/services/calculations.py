"""The board's calculation rules (scaffold 1.3, PRD 3.3 / 3.8 / 3.9)."""

from decimal import Decimal

from db import by_created_at, db, now
from services import constants as C
from util import days, minutes, round_half_up, whole_days_between


# ---------------------------------------------------------------- prior use --
def effective_priority_at(original_filed_at, documented_prior_use_years, affidavit_on_file):
    """The affidavit flag gates the credit entirely; the cap then clips it."""
    if affidavit_on_file:
        capped_years = min(documented_prior_use_years, C.PRIOR_USE_CAP_YEARS)
    else:
        capped_years = 0
    return original_filed_at - days(capped_years * C.DAYS_PER_PRIOR_USE_YEAR)


# ------------------------------------------------------- brand conflict group -
def conflict_group_key(row):
    return (row["state_code"], row["brand_symbol"], row["position_code"], row["species_class"])


def _source_correction_rounds(registration):
    application = db.applications.get(registration.get("source_application_id"))
    return application["correction_rounds"] if application else 0


def registration_sort_key(registration):
    return (
        registration["effective_priority_at"],
        _source_correction_rounds(registration),
        registration["created_at"],
        registration["_seq"],
    )


def conflict_group_members(key):
    return [
        reg
        for reg in db.registrations.values()
        if conflict_group_key(reg) == key and reg["status"] in C.REGISTRATION_GROUP_STATUSES
    ]


def recompute_priority_ranks(key, created_id=None):
    """Re-derive priority_rank for every ACTIVE or GRACE member of the group.

    A member whose rank actually moves is mutated in its own right; the record
    being created in this very request carries its rank as part of creation and
    is therefore not bumped again.
    """
    from db import touch

    members = sorted(conflict_group_members(key), key=registration_sort_key)
    for index, registration in enumerate(members, start=1):
        if registration["priority_rank"] != index:
            registration["priority_rank"] = index
            if registration["id"] != created_id:
                touch(registration)
    return members


def filing_outranked_by(application):
    """The incumbent (owned by another owner) whose sort key sorts strictly ahead."""
    key = conflict_group_key(application)
    filing_key = (
        application["effective_priority_at"],
        application["correction_rounds"],
        application["created_at"],
        application["_seq"],
    )
    for registration in conflict_group_members(key):
        if registration["owner_id"] == application["owner_id"]:
            continue
        if registration_sort_key(registration) < filing_key:
            return registration
    return None


# -------------------------------------------------------- renewal filing fee --
def renewal_days_past_expiry(prior_registration):
    return whole_days_between(prior_registration["expires_on"], now())


def renewal_penalty_rate(days_past_expiry):
    """None means the record is beyond recovery (ERR_REGISTRATION_UNRENEWABLE)."""
    if days_past_expiry <= 0:
        return Decimal("0")
    if days_past_expiry <= C.GRACE_DAYS:
        return Decimal(C.GRACE_PENALTY_RATE)
    if days_past_expiry <= C.LAPSE_RECOVERY_DAYS:
        return Decimal(C.LAPSE_PENALTY_RATE)
    return None


def renewal_filing_fee(penalty_rate):
    base = C.BASE_RENEWAL_FEE_CENTS
    return base + round_half_up(Decimal(base) * penalty_rate)


# --------------------------------------------------- inspection fee assessment -
def _band_rate(position):
    if position <= C.BAND_1_MAX_HEAD:
        return C.BAND_1_RATE_CENTS_PER_HEAD
    if position <= C.BAND_2_MAX_HEAD:
        return C.BAND_2_RATE_CENTS_PER_HEAD
    return C.BAND_3_RATE_CENTS_PER_HEAD


def _band_span(start_exclusive, count):
    """Marginal band cost for positions (start_exclusive, start_exclusive + count]."""
    total = 0
    remaining = count
    position = start_exclusive
    while remaining > 0:
        position += 1
        # Consume whole band chunks for speed on large head counts.
        if position <= C.BAND_1_MAX_HEAD:
            chunk = min(remaining, C.BAND_1_MAX_HEAD - position + 1)
            rate = C.BAND_1_RATE_CENTS_PER_HEAD
        elif position <= C.BAND_2_MAX_HEAD:
            chunk = min(remaining, C.BAND_2_MAX_HEAD - position + 1)
            rate = C.BAND_2_RATE_CENTS_PER_HEAD
        else:
            chunk = remaining
            rate = C.BAND_3_RATE_CENTS_PER_HEAD
        total += chunk * rate
        remaining -= chunk
        position += chunk - 1
    return total


def is_after_hours(scheduled_start_at):
    if scheduled_start_at is None:
        return False
    hour = scheduled_start_at.hour
    return hour < C.AFTER_HOURS_END_HOUR_UTC or hour >= C.AFTER_HOURS_START_HOUR_UTC


def inspection_fee_assessment(order):
    """Marginal per-head bands consumed cumulatively across the order's lots."""
    qualifying = by_created_at(
        [
            lot
            for lot in db.lots.values()
            if lot["inspection_order_id"] == order["id"] and lot["lot_status"] in C.COUNTED_LOT_STATUSES
        ]
    )

    running_head = 0
    subtotal_cents = 0
    for lot in qualifying:
        lot_base_cents = _band_span(running_head, lot["head_count"])
        # The administrative surcharge is rounded PER LOT, and only the already
        # rounded per-lot amounts are summed.
        lot_admin_cents = round_half_up(Decimal(lot_base_cents) * Decimal(C.ADMIN_SURCHARGE_RATE))
        subtotal_cents += lot_base_cents + lot_admin_cents
        running_head += lot["head_count"]

    territory = db.territories.get(order["territory_id"])
    travel = territory["travel_surcharge_cents"] if territory else 0
    premium = C.AFTER_HOURS_FLAT_CENTS if is_after_hours(order.get("scheduled_start_at")) else 0
    return subtotal_cents + travel + premium


def fee_due_on():
    return now() + days(C.FEE_DUE_DAYS)


# --------------------------------------------------- estray proceeds waterfall -
def estray_distribution(head_count, gross_cents, care_days):
    """Strictly ordered waterfall: the handling cap keys on what care leaves behind."""
    gross_cents = gross_cents or 0
    care_cost_cents = C.CARE_RATE_CENTS_PER_HEAD_PER_DAY * head_count * care_days
    net_available_cents = gross_cents - care_cost_cents
    handling_uncapped_cents = round_half_up(Decimal(gross_cents) * Decimal(C.HANDLING_RATE_OF_GROSS))
    handling_cap_cents = round_half_up(
        Decimal(max(net_available_cents, 0)) * Decimal(C.HANDLING_CAP_RATE_OF_NET)
    )
    if net_available_cents <= 0:
        handling_fee_cents = 0
    else:
        handling_fee_cents = min(handling_uncapped_cents, handling_cap_cents)
    claimant_residual_cents = max(net_available_cents - handling_fee_cents, 0)
    return care_cost_cents, handling_fee_cents, claimant_residual_cents


def write_provisional_distribution(case):
    care, handling, residual = estray_distribution(
        case["head_count"], case["estimated_gross_cents"], C.STATUTORY_HOLD_DAYS
    )
    case["care_cost_cents"] = care
    case["handling_fee_cents"] = handling
    case["claimant_residual_cents"] = residual
    case["distribution_variant"] = "PROVISIONAL"


def final_care_days(case):
    """Calendar dates from intake day through sale day, both counted."""
    impounded_date = case["impounded_at"].date()
    sale_date = case["sale_at"].date()
    return (sale_date - impounded_date).days + 1


def write_final_distribution(case):
    care, handling, residual = estray_distribution(
        case["head_count"], case["gross_proceeds_cents"], final_care_days(case)
    )
    case["care_cost_cents"] = care
    case["handling_fee_cents"] = handling
    case["claimant_residual_cents"] = residual
    case["distribution_variant"] = "FINAL"


# ------------------------------------------------------ inspector window rules -
def occupied_orders(inspector_id, exclude_order_id):
    return [
        order
        for order in db.orders.values()
        if order["inspector_id"] == inspector_id
        and order["schedule_status"] in C.OCCUPYING_SCHEDULE_STATUSES
        and order["id"] != exclude_order_id
    ]


def window_conflict(occupied, this_territory_id, new_start, new_end):
    for order in occupied:
        buffer = minutes(0) if order["territory_id"] == this_territory_id else minutes(C.TRAVEL_BUFFER_MINUTES)
        if new_start < order["scheduled_end_at"] + buffer and order["scheduled_start_at"] < new_end + buffer:
            return True
    return False


def same_day_count(occupied, new_start):
    target = new_start.date()
    return sum(1 for order in occupied if order["scheduled_start_at"].date() == target)


# ------------------------------------------------ facility occupancy projection -
def facility_capacity_exceeded(territory, new_head_count):
    """Aggregate test: every instant of the proposed occupancy must stay under capacity."""
    new_start = now()
    new_end = new_start + days(C.STATUTORY_HOLD_DAYS)

    live = []
    for case in db.estrays.values():
        if case["territory_id"] != territory["id"] or case["status"] not in C.LIVE_ESTRAY_STATUSES:
            continue
        start = case["impounded_at"]
        end = case["sale_at"] if case["status"] == "SOLD" else case["statutory_release_on"]
        if end is None:
            end = case["statutory_release_on"]
        live.append((start, end, case["head_count"]))

    breakpoints = {new_start, new_end}
    for start, end, _head in live:
        if new_start < start < new_end:
            breakpoints.add(start)
        if new_start < end < new_end:
            breakpoints.add(end)
    ordered = sorted(breakpoints)

    for index in range(len(ordered) - 1):
        segment_start = ordered[index]
        load = new_head_count
        for start, end, head in live:
            if start <= segment_start and end > segment_start:
                load += head
        if load > territory["impound_capacity_head"]:
            return True
    return False
