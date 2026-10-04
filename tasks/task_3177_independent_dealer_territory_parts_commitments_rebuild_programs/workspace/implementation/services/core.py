"""Business logic: derivation engines, state machines and workflow rules.

Nothing here reads or writes any storage other than the in-memory dicts in
``db``.  No entity is ever created at import time or at server start.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
import request as reqmod
from errors import (
    ApiError,
    E_AGREEMENT_COMMITMENT_OPEN,
    E_AGREEMENT_NOT_FOUND,
    E_CLAIM_NOT_FOUND,
    E_COMMITMENT_BATCH_OPEN,
    E_COMMITMENT_EMPTY,
    E_COMMITMENT_NOT_FOUND,
    E_COMMITMENT_PERF_DEF,
    E_CREDIT_ALREADY_APPLIED,
    E_DEALER_NOT_FOUND,
    E_DEALER_SCOPE_MISMATCH,
    E_DEALER_TERMINATED,
    E_DUPLICATE_SERIAL,
    E_EPOCH_CONFLICT,
    E_EXCLUSIVITY_MISMATCH,
    E_HARD_CAP,
    E_INVALID_STATE,
    E_MACHINE_ALREADY_REGISTERED,
    E_MACHINE_NOT_IN_POPULATION,
    E_MACHINE_POPULATION_RETIRED,
    E_MACHINE_REMARKETED,
    E_NO_ACTIVE_AGREEMENT,
    E_NO_RESTRICTION_PRIORITY,
    E_PARTY_SUPERSEDED,
    E_POPULATION_NOT_FOUND,
    E_REBUILD_CORE_UNRETURNED,
    E_REBUILD_SPEC_EXCEEDED,
    E_RESTRICTION_FULL_STOP,
    E_RESTRICTION_MINIMAL,
    E_REVIEW_AWAITING_CIRCUMSTANCE,
    E_REVIEW_NOT_FOUND,
    E_REVIEW_OUTSTANDING,
    E_SLA_AUDIT_PENDING,
    E_STALE_VERSION,
    E_STOCKING_MANDATE_UNMET,
    E_TERRITORY_OVERLAP,
    E_TOOLING_INCOMPLETE,
    E_TRADE_IN_APPRAISAL,
    E_TRADE_IN_NOT_ACCEPTED,
)

# ---------------------------------------------------------------------------
# §2.10 named constants
# ---------------------------------------------------------------------------
CORE_CREDIT_RATE = Decimal("1.4")
CERTIFIED_HANDLING_MARGIN = Decimal("0.15")
LABOR_RATE_WEIGHT_FACTOR = Decimal("0.0025")
PLANNED_ANNUAL_DIVISOR = Decimal("800")
MANDATE_SETTLEMENT_ARREAR_CENTS = 103040
SETTLEMENT_PER_CORE_CENTS = 1610
RESTRICTION_UNIT_CENTS = 150
SERVICE_RISK_PRIORITY_MULTIPLIER = 10
EMERGENCY_BONUS = 10
PREMIUM_COVERAGE_AGE_BONUS = 5
QUALITY_SPREAD_THRESHOLD_PP = Decimal("10.0")
CSI_BONUS_PCT = Decimal("3.0")
BASE_AVAILABILITY_PCT = Decimal("92.0")
AVAILABILITY_SLOPE_PER_PCT = Decimal("0.1")
AVAILABILITY_KNEE_PCT = Decimal("60")
AVAILABILITY_CAP_PCT = Decimal("4.0")
FILL_DENOM_FIRST_TIER = 2
FILL_DENOM_OVERFLOW = 4
FIRST_TIER_FILL_MAX = Decimal("8.0")

BASE_ANNUAL_PARTS_UNITS = {
    "EXCAVATION": 40,
    "EARTHMOVING": 48,
    "COMPACTION": 28,
    "POWER_SYSTEMS": 60,
    "LIFT_TRUCK": 36,
}

COVERAGE_BY_TIER = {"BASIC": Decimal("1.0"), "PLUS": Decimal("1.25"), "PREMIUM": Decimal("1.5")}

RATE_BY_TIER = {"BASIC": Decimal("0.101"), "STANDARD": Decimal("0.127"), "PREMIUM": Decimal("0.152")}

PRODUCT_FAMILY_MIN_TECHNICIANS = 2

# Certified rebuild specification envelope.  §3.7 names the two limits
# (maximum operating weight, minimum certified technicians) without quoting
# numbers, so they are fixed here as a strictly increasing ladder keyed by the
# three declared specification codes.
REBUILD_SPEC_MAX_WEIGHT_LB = {
    "CAT_CERTIFIED_1": 80000,
    "CAT_CERTIFIED_2": 100000,
    "CAT_CERTIFIED_3": 120000,
}
REBUILD_SPEC_MIN_TECHNICIANS = {
    "CAT_CERTIFIED_1": 2,
    "CAT_CERTIFIED_2": 4,
    "CAT_CERTIFIED_3": 6,
}
# The remanufactured-credit reduction applied when a rebuild is certified.
CERTIFIED_CREDIT_REDUCTION_UNITS = 1

RESTRICTION_ORDER = ["HOURS_SPENT", "METER_RUNNING", "FULL_STOP"]
PRIORITY_RANK = {"HOURS_SPENT": 1, "METER_RUNNING": 2, "FULL_STOP": 3}

D = Decimal


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def q2(value) -> Decimal:
    return D(value).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def q4(value) -> Decimal:
    return D(value).quantize(D("0.0001"), rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal as int when integral, else float (4-decimal figures)."""
    value = D(value).normalize()
    if value == value.to_integral_value():
        return int(value)
    return float(value.quantize(D("0.0001"), rounding=ROUND_HALF_UP))


def int2(value) -> int:
    """Whole cents: the product is rounded half-up to the nearest integer."""
    return int(D(value).quantize(D("1"), rounding=ROUND_HALF_UP))


# Availability bands used by the underperformance availability-tier raise.
AVAILABILITY_TIER_EDGES = [10, 25, 50, 100, 250, 500]


def raise_one_tier(units: int) -> int:
    """Raise a stocking level by one availability tier.

    The mandate's own tiers (MICRO/SMALL/MEDIUM/LARGE) are a 100/500/1500
    ladder; the availability ladder is the finer one the stocking levels
    themselves step along.  A level already above the last edge simply rises by
    one unit so the raise is never a no-op.
    """
    for edge in AVAILABILITY_TIER_EDGES:
        if units < edge:
            return edge
    return units + 1


# ---------------------------------------------------------------------------
# §2.9 recurring lookups
# ---------------------------------------------------------------------------
def base_annual_parts_units(product_family: str) -> int:
    return BASE_ANNUAL_PARTS_UNITS[product_family]


def weight_class_tier(machine_operating_weight_lb: int) -> str:
    if machine_operating_weight_lb < 40000:
        return "LIGHT"
    if machine_operating_weight_lb <= 100000:
        return "MIDDLE"
    return "HEAVY"


def weight_class_tier_multiplier(machine_operating_weight_lb: int) -> Decimal:
    tier = weight_class_tier(machine_operating_weight_lb)
    return q2({"LIGHT": D("0.8"), "MIDDLE": D("1.0"), "HEAVY": D("1.2")}[tier])


def covering_support_agreement(machine_serial):
    """The ACTIVE support agreement covering a serial, if any."""
    if machine_serial is None:
        return None
    for record in db.rows("support_agreements"):
        if record["machine_serial"] == machine_serial and record["status"] == "ACTIVE":
            return record
    return None


def coverage_multiplier(machine_serial) -> Decimal:
    agreement = covering_support_agreement(machine_serial)
    if agreement is None:
        return q2(D("1.0"))
    return q2(COVERAGE_BY_TIER.get(agreement["plan_tier"], D("1.0")))


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def get_dealer(dealer_id, error_id=E_DEALER_NOT_FOUND) -> dict:
    record = db.find("dealers", dealer_id)
    if record is None:
        raise ApiError(error_id)
    return record


def get_agreement(agreement_id) -> dict:
    record = db.find("dealer_agreements", agreement_id)
    if record is None:
        raise ApiError(E_AGREEMENT_NOT_FOUND)
    return record


def get_commitment(commitment_id) -> dict:
    record = db.find("parts_commitments", commitment_id)
    if record is None:
        raise ApiError(E_COMMITMENT_NOT_FOUND)
    return record


def get_claim(claim_id) -> dict:
    record = db.find("rebuild_claims", claim_id)
    if record is None:
        raise ApiError(E_CLAIM_NOT_FOUND)
    return record


def get_review(review_id) -> dict:
    record = db.find("performance_reviews", review_id)
    if record is None:
        raise ApiError(E_REVIEW_NOT_FOUND)
    return record


def get_population(population_id) -> dict:
    record = db.find("machine_population_records", population_id)
    if record is None:
        raise ApiError(E_POPULATION_NOT_FOUND)
    return record


def get_batch(batch_id) -> dict:
    record = db.find("parts_order_batches", batch_id)
    if record is None:
        # A batch is addressed under its commitment; a missing batch is
        # reported with the commitment-level not-found identifier.
        raise ApiError(E_COMMITMENT_NOT_FOUND, "No parts order batch exists for the supplied identifier.")
    return record


def get_service_order(order_id) -> dict:
    record = db.find("service_orders", order_id)
    if record is None:
        raise ApiError(E_COMMITMENT_NOT_FOUND, "No service order exists for the supplied identifier.")
    return record


def get_support_agreement(agreement_id) -> dict:
    record = db.find("support_agreements", agreement_id)
    if record is None:
        raise ApiError(E_AGREEMENT_NOT_FOUND, "No support agreement exists for the supplied identifier.")
    return record


def get_equipment_order(order_id) -> dict:
    record = db.find("equipment_orders", order_id)
    if record is None:
        raise ApiError(E_DEALER_NOT_FOUND, "No equipment order exists for the supplied identifier.")
    return record


def get_certification(cert_id) -> dict:
    record = db.find("certification_records", cert_id)
    if record is None:
        raise ApiError(E_DEALER_NOT_FOUND, "No certification record exists for the supplied identifier.")
    return record


def get_observation(observation_id) -> dict:
    record = db.find("market_share_observations", observation_id)
    if record is None:
        raise ApiError(E_DEALER_NOT_FOUND, "No market-share observation exists for the supplied identifier.")
    return record


def get_party_registration(reg_id) -> dict:
    record = db.find("party_registrations", reg_id)
    if record is None:
        raise ApiError(E_DEALER_NOT_FOUND, "No party registration exists for the supplied identifier.")
    return record


def get_trade_in(trade_in_id) -> dict:
    record = db.find("trade_in_units", trade_in_id)
    if record is None:
        raise ApiError(E_DEALER_NOT_FOUND, "No trade-in unit exists for the supplied identifier.")
    return record


# ---------------------------------------------------------------------------
# §2.5.1 optimistic concurrency control
# ---------------------------------------------------------------------------
def check_expected_version(entity: dict, supplied, error_id=E_STALE_VERSION):
    """Only a supplied value can reject the request; omission skips the check."""
    if supplied is None:
        return
    if int(supplied) != int(entity["version"]):
        raise ApiError(error_id)


# ---------------------------------------------------------------------------
# Common-field plumbing
# ---------------------------------------------------------------------------
def init_common(record: dict) -> dict:
    record["created_at"] = db.stamp()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    return record


_SUPPRESS_TOUCH = False


class suppressing_touches:
    """Refresh derived fields on a read path without recording a mutation.

    Reads recompute derived figures so the caller sees fresh values, but a read
    is not a mutation: the owning resource's ``updated_at`` and ``version``
    must not move, or optimistic-concurrency preconditions would be invalidated
    by a plain GET.
    """

    def __enter__(self):
        global _SUPPRESS_TOUCH
        self._previous = _SUPPRESS_TOUCH
        _SUPPRESS_TOUCH = True
        return self

    def __exit__(self, *_exc):
        global _SUPPRESS_TOUCH
        _SUPPRESS_TOUCH = self._previous
        return False


def touch(record: dict) -> dict:
    """A mutation to a derived field is still a mutation."""
    if _SUPPRESS_TOUCH:
        return record
    record["updated_at"] = db.stamp()
    record["version"] = int(record.get("version", 0)) + 1
    return record


def bump(record: dict) -> dict:
    """Increment version + refresh updated_at without re-stamping order."""
    record["updated_at"] = db.stamp()
    record["version"] = int(record.get("version", 0)) + 1
    return record


# ===========================================================================
# §3.1 Dealer derivation
# ===========================================================================
def dealer_agreements(dealer_id) -> list:
    return [a for a in db.rows("dealer_agreements") if a["dealer_id"] == dealer_id]


def dealer_commitments(dealer_id) -> list:
    return [c for c in db.rows("parts_commitments") if c["dealer_id"] == dealer_id]


def recompute_certified_family_count(dealer: dict) -> None:
    families = set()
    for record in db.rows("certification_records"):
        if record["dealer_id"] == dealer["id"] and cert_status(record) == "ACTIVE":
            families.add(record["product_family"])
    dealer["certified_family_count"] = len(families)
    touch(dealer)


def recompute_trusted_commitment_count(dealer: dict) -> None:
    count = 0
    for agreement in db.rows("dealer_agreements"):
        if agreement["dealer_id"] == dealer["id"] and agreement["trusted_commitment"]:
            count += 1
    dealer["trusted_commitment_count"] = count
    touch(dealer)


def recompute_open_backorder_units(dealer: dict) -> None:
    total = 0
    for batch in db.rows("parts_order_batches"):
        if batch["status"] not in ("OPEN", "CORE_PENDING"):
            continue
        commitment = db.find("parts_commitments", batch["commitment_id"])
        if commitment is not None and commitment["dealer_id"] == dealer["id"]:
            total += int(batch["unfilled_units"])
    dealer["open_backorder_units"] = total
    touch(dealer)


def recompute_market_share_pct(dealer: dict) -> None:
    latest = None
    for review in db.rows("performance_reviews"):
        if review["dealer_id"] != dealer["id"]:
            continue
        if review.get("actual_market_share_pct") is None:
            continue
        if latest is None or review["created_at"] > latest["created_at"]:
            latest = review
    dealer["market_share_pct"] = 0.0 if latest is None else latest["actual_market_share_pct"]
    touch(dealer)


def refresh_dealer_derived(dealer: dict) -> None:
    recompute_certified_family_count(dealer)
    recompute_trusted_commitment_count(dealer)
    recompute_open_backorder_units(dealer)
    recompute_market_share_pct(dealer)


def sync_dealer_status(dealer: dict) -> None:
    """Drive the dealer's own status from its agreements (§3.2)."""
    if dealer["status"] == "TERMINATED":
        return
    agreements = dealer_agreements(dealer["id"])
    any_active = any(a["status"] == "ACTIVE" for a in agreements)
    all_suspended = bool(agreements) and all(a["status"] == "SUSPENDED" for a in agreements)
    status = dealer["status"]
    if status == "PENDING_AGREEMENT":
        if dealer["trusted_commitment_count"] >= 1:
            dealer["status"] = "ACTIVE"
            touch(dealer)
            for commitment in dealer_commitments(dealer["id"]):
                set_deferred_rule(commitment["id"], True)
            return
        if all_suspended:
            dealer["status"] = "SUSPENDED"
            touch(dealer)
            return
    if status == "ACTIVE" and not any_active:
        dealer["status"] = "SUSPENDED"
        touch(dealer)
        for commitment in dealer_commitments(dealer["id"]):
            set_deferred_rule(commitment["id"], False)
        return
    if status == "SUSPENDED" and any_active:
        dealer["status"] = "ACTIVE"
        touch(dealer)
        for commitment in dealer_commitments(dealer["id"]):
            set_deferred_rule(commitment["id"], True)


# ===========================================================================
# §3.2 DealerAgreement derivation
# ===========================================================================
def cert_status(record: dict) -> str:
    """Derived on read from certified_at, recurrence and the logical clock."""
    if record.get("revoked"):
        return "REVOKED"
    certified_at = db.as_dt(record["certified_at"])
    horizon = certified_at + timedelta(days=365)
    if db.now() < horizon:
        return "ACTIVE"
    if record.get("recurrence_within_period"):
        return "ACTIVE"
    # A recurrence whose own interval is still in force keeps the credential live.
    for other in db.rows("certification_records"):
        if other["id"] == record["id"]:
            continue
        if other["dealer_id"] != record["dealer_id"]:
            continue
        if other["technician_name"] != record["technician_name"]:
            continue
        if other["product_family"] != record["product_family"]:
            continue
        if other.get("revoked"):
            continue
        start = certified_at
        end = start + timedelta(days=365)
        other_at = db.as_dt(other["certified_at"])
        if start <= other_at < end:
            if db.now() < other_at + timedelta(days=365):
                return "ACTIVE"
    return "EXPIRED"


def recompute_recurrence(record: dict) -> None:
    start = db.as_dt(record["certified_at"])
    end = start + timedelta(days=365)
    found = False
    for other in db.rows("certification_records"):
        if other["id"] == record["id"]:
            continue
        if other["dealer_id"] != record["dealer_id"]:
            continue
        if other["technician_name"] != record["technician_name"]:
            continue
        if other["product_family"] != record["product_family"]:
            continue
        if other.get("revoked"):
            continue
        other_at = db.as_dt(other["certified_at"])
        if start <= other_at < end:
            found = True
            break
    record["recurrence_within_period"] = found


def recompute_all_recurrences() -> None:
    for record in db.rows("certification_records"):
        recompute_recurrence(record)


def recompute_certified_technician_count(agreement: dict) -> None:
    technicians = set()
    for record in db.rows("certification_records"):
        if record["dealer_id"] != agreement["dealer_id"]:
            continue
        if record["product_family"] != agreement["product_family"]:
            continue
        if cert_status(record) == "ACTIVE":
            technicians.add(record["technician_name"])
    agreement["certified_technician_count"] = len(technicians)


def recompute_tooling_compliance_status(agreement: dict) -> None:
    has_any = any(
        r["dealer_id"] == agreement["dealer_id"] and r["product_family"] == agreement["product_family"]
        for r in db.rows("certification_records")
    )
    if not has_any:
        agreement["tooling_compliance_status"] = "NOT_SUBMITTED"
        return
    if int(agreement["certified_technician_count"]) < PRODUCT_FAMILY_MIN_TECHNICIANS:
        agreement["tooling_compliance_status"] = "PARTIAL"
        return
    agreement["tooling_compliance_status"] = "COMPLIANT"


def recompute_performance_actual_share_pct(agreement: dict) -> None:
    latest = None
    for review in db.rows("performance_reviews"):
        if review["agreement_id"] != agreement["id"]:
            continue
        if review.get("actual_market_share_pct") is None:
            continue
        if latest is None or review["created_at"] > latest["created_at"]:
            latest = review
    agreement["performance_actual_share_pct"] = 0.0 if latest is None else latest["actual_market_share_pct"]


def recompute_trusted_commitment(agreement: dict) -> None:
    if agreement["tooling_compliance_status"] != "COMPLIANT":
        agreement["trusted_commitment"] = False
        return
    holds = any(
        c["agreement_id"] == agreement["id"] and c["status"] == "ORDER_READY"
        for c in db.rows("parts_commitments")
    )
    agreement["trusted_commitment"] = bool(holds)


def refresh_agreement_derived(agreement: dict) -> None:
    recompute_certified_technician_count(agreement)
    recompute_tooling_compliance_status(agreement)
    recompute_performance_actual_share_pct(agreement)
    recompute_trusted_commitment(agreement)


# ===========================================================================
# §3.4 Stocking mandate derivation
# ===========================================================================
def tier_weighted_numerator(commitment: dict) -> Decimal:
    return q2(D(commitment["machine_population_units"]) * D(commitment["machine_population_slope"]))


def machine_population_tier_of(numerator: Decimal) -> str:
    if numerator < D("100"):
        return "MICRO"
    if numerator < D("500"):
        return "SMALL"
    if numerator < D("1500"):
        return "MEDIUM"
    return "LARGE"


def emergency_tier_of(window_hours) -> str:
    hours = D(window_hours)
    if hours <= D("8"):
        return "PREMIUM"
    if hours <= D("24"):
        return "STANDARD"
    return "BASIC"


def compute_stocking_mandate(commitment: dict) -> None:
    """Recompute the whole stocking mandate (active and final variants)."""
    numerator = tier_weighted_numerator(commitment)
    tier = machine_population_tier_of(numerator)
    window_hours = D(commitment["emergency_fill_window_hours"])
    etier = emergency_tier_of(window_hours)
    rate = RATE_BY_TIER[etier]

    target_from_rate = numerator * rate
    target_from_fill = D(commitment["planned_annual_units"]) / PLANNED_ANNUAL_DIVISOR

    active = max(math.ceil(target_from_rate), math.ceil(target_from_fill))
    final = max(math.floor(target_from_rate), math.floor(target_from_fill))

    commitment["machine_population_tier"] = tier
    commitment["emergency_tier"] = etier
    commitment["required_stocking_units"] = int(active)
    commitment["required_stocking_units_final"] = int(final)
    recompute_availability_target(commitment)
    recompute_available_units(commitment)


def recompute_availability_target(commitment: dict) -> None:
    target = D(commitment["emergency_stocking_target_pct"])
    excess = max(D("0"), target - AVAILABILITY_KNEE_PCT)
    uplift = min(AVAILABILITY_CAP_PCT, AVAILABILITY_SLOPE_PER_PCT * excess)
    commitment["availability_target_pct"] = num(q4(BASE_AVAILABILITY_PCT + uplift))


def commitment_batches(commitment_id) -> list:
    return [b for b in db.rows("parts_order_batches") if b["commitment_id"] == commitment_id]


def recompute_committed_units(commitment: dict) -> None:
    """Units reserved against this commitment but not yet received.

    A batch's `unfilled_units` is "the portion of `reserved_units` not yet
    received" (PRD §3.5), so the units still standing committed are exactly the
    outstanding portion of every batch that has not been cancelled or closed.
    """
    total = 0
    for batch in commitment_batches(commitment["id"]):
        if batch["status"] in ("OPEN", "ORDERED", "RECEIVED", "PARTIALLY_RETURNED", "CORE_PENDING"):
            total += int(batch["unfilled_units"])
    commitment["committed_units"] = total
    recompute_available_units(commitment)


def recompute_available_units(commitment: dict) -> None:
    commitment["available_commitment_units"] = max(
        0, int(commitment["required_stocking_units_final"]) - int(commitment["committed_units"])
    )


def recompute_fill_rate(commitment: dict) -> None:
    """Fulfilment rate: the received share of everything the mandate has taken on.

    PRD §3.5 recomputes `fill_rate_pct` at place-order, at receipt and at every
    fill, and §2.7 fixes it to four decimal places half-up.
    """
    fulfilled = int(commitment["fulfilled_units"])
    outstanding = int(commitment["committed_units"])
    total = fulfilled + outstanding
    if total < 1:
        commitment["fill_rate_pct"] = 0.0
        return
    commitment["fill_rate_pct"] = num(q4(D("100") * D(fulfilled) / D(total)))


def recompute_fulfilled_units(commitment: dict) -> None:
    """Units already received against this commitment's batches."""
    total = 0
    for batch in commitment_batches(commitment["id"]):
        if batch["status"] == "CLOSED":
            total += int(batch["requested_units"])
        elif batch["status"] in ("RECEIVED", "PARTIALLY_RETURNED", "CORE_PENDING"):
            total += int(batch["reserved_units"]) - int(batch["unfilled_units"])
    commitment["fulfilled_units"] = total


def commitment_service_orders(commitment_id) -> list:
    return [o for o in db.rows("service_orders") if o["commitment_id"] == commitment_id]


def first_agreement(dealer_id, product_family):
    candidates = [
        a
        for a in db.rows("dealer_agreements")
        if a["dealer_id"] == dealer_id and a["product_family"] == product_family
    ]
    candidates.sort(key=lambda a: a["created_at"])
    return candidates[0] if candidates else None


def recompute_observed_share(record: dict) -> None:
    """100 * observed / territory over the dealer and family's summed rows.

    PRD §3.6: "`observed_share_pct` is 100 multiplied by
    `observed_machine_units` and divided by `territory_machine_units`,
    recomputed from the summed observation values of the dealer and family, to
    four decimal places half-up."  The sum runs over every recorded
    observation of that dealer and family, weighted by the row's `kind`.
    """
    observed = D("0")
    territory = D("0")
    for row in db.rows("market_share_observations"):
        if row["dealer_id"] != record["dealer_id"] or row["product_family"] != record["product_family"]:
            continue
        weight = D("1.0") if row["kind"] == "MACHINE" else D("0.5")
        observed += D(row["observed_machine_units"]) * weight
        territory += D(row["territory_machine_units"]) * weight
    if territory == 0:
        record["observed_share_pct"] = 0.0
    else:
        record["observed_share_pct"] = num(q4(D("100") * observed / territory))


def recompute_dealer_family_observed_shares(dealer_id, product_family) -> None:
    """Refresh the shared ratio on every observation of this dealer and family.

    PRD §3.6 defines `observed_share_pct` as a summed reading, so recording a
    later observation re-keys the ratio served on the earlier rows as well.
    """
    for row in db.rows("market_share_observations"):
        if row["dealer_id"] != dealer_id or row["product_family"] != product_family:
            continue
        recompute_observed_share(row)


# ===========================================================================
# §3.7 deferred shortage rule
# ===========================================================================
def rule_entry(commitment_id) -> dict:
    return db.STATE["deferred_rules"].setdefault(
        commitment_id, {"rule_active": False, "epoch": object()}
    )


def set_deferred_rule(commitment_id, active: bool) -> None:
    entry = rule_entry(commitment_id)
    if entry["rule_active"] != active:
        entry["rule_active"] = active
        entry["epoch"] = object()


def deferred_rule_active(commitment_id) -> bool:
    return bool(rule_entry(commitment_id)["rule_active"])


def credited_core_units(commitment_id) -> int:
    """Cores already returned against this commitment."""
    total = 0
    for batch in commitment_batches(commitment_id):
        if batch["status"] in ("PARTIALLY_RETURNED", "CORE_PENDING"):
            total += int(batch["core_units"])
    return total


def apply_deferred_shortage_rule(commitment: dict, credited_units: int) -> bool:
    """Fires the deferred re-evaluation once the arrear is settled.

    Does nothing at all when no deferred re-evaluation is armed, and does not
    convert a commitment whose arrear is already met.
    """
    if not deferred_rule_active(commitment["id"]):
        return False
    shortage = MANDATE_SETTLEMENT_ARREAR_CENTS - SETTLEMENT_PER_CORE_CENTS * credited_units
    if shortage <= 0:
        db.STATE["re_evaluation_armed"].add(commitment["id"])
        return True
    return False


# ===========================================================================
# §3.10 service bench derivation
# ===========================================================================
def active_population_serials(dealer_id) -> set:
    return {
        r["machine_serial"]
        for r in db.rows("machine_population_records")
        if r["dealer_id"] == dealer_id and r["status"] == "ACTIVE"
    }


def ordering_target_list(dealer_id) -> list:
    serials = active_population_serials(dealer_id)
    targets = [
        o
        for o in db.rows("service_orders")
        if o["dealer_id"] == dealer_id
        and o["kind"] == "RESTRICTION"
        and o["status"] == "OPEN"
        and o["machine_serial"] in serials
    ]
    targets.sort(key=lambda o: (D(o["sla_hours"]), o["created_at"]))
    return targets


def priority_rank_of(restriction_scope) -> int:
    return PRIORITY_RANK[restriction_scope]


def risk_score_of(order: dict) -> int:
    score = priority_rank_of(order["restriction_scope"]) * SERVICE_RISK_PRIORITY_MULTIPLIER
    if order["kind"] == "EMERGENCY_FILL":
        score += EMERGENCY_BONUS
    agreement = covering_support_agreement(order.get("machine_serial"))
    if agreement is not None and agreement["plan_tier"] == "PREMIUM":
        score += PREMIUM_COVERAGE_AGE_BONUS
    return score


def recompute_service_order_derived(order: dict) -> None:
    order["priority_rank"] = priority_rank_of(order["restriction_scope"])
    order["risk_score"] = risk_score_of(order)
    order["emergency_filled_units"] = compute_emergency_filled_units(order)


def recompute_deferral_tiers(dealer_id) -> None:
    has_candidate = len(ordering_target_list(dealer_id)) >= 1
    for order in db.rows("service_orders"):
        if order["dealer_id"] != dealer_id:
            continue
        order["deferral_tier"] = (1 + priority_rank_of(order["restriction_scope"])) if has_candidate else 0


def gross_filled_units(dealer_id) -> Decimal:
    serials = active_population_serials(dealer_id)
    total = D("0")
    for order in db.rows("service_orders"):
        if order["dealer_id"] != dealer_id:
            continue
        if order["kind"] != "RESTRICTION" or order["status"] != "OPEN":
            continue
        if order["machine_serial"] not in serials:
            continue
        total += D(order["sla_hours"])
    return total


def compute_emergency_filled_units(order: dict) -> int:
    gross = gross_filled_units(order["dealer_id"])
    denom = FILL_DENOM_FIRST_TIER if gross <= FIRST_TIER_FILL_MAX else FILL_DENOM_OVERFLOW
    value = gross / D(denom)
    if order.get("orderable_ref_enabled"):
        return int(value.to_integral_value(rounding="ROUND_FLOOR"))
    return int(value.to_integral_value(rounding="ROUND_CEILING"))


def sla_met(order: dict) -> bool:
    window = order.get("response_window_hours")
    if window is None:
        return False
    return D(order["sla_hours"]) <= D(window)


def recompute_sla_outcomes() -> None:
    for order in db.rows("service_orders"):
        recompute_service_order_derived(order)
        commitment = db.find("parts_commitments", order["commitment_id"])
        if commitment is not None and order["status"] in ("OPEN", "IN_PROGRESS"):
            order["response_window_hours"] = commitment["emergency_fill_window_hours"]


# ===========================================================================
# §3.9 machine population derivation
# ===========================================================================
def projected_annual_parts_units(record: dict) -> int:
    base = D(base_annual_parts_units(record["product_family"]))
    coverage = coverage_multiplier(record["machine_serial"])
    weight = weight_class_tier_multiplier(record["machine_operating_weight_lb"])
    return int(math.ceil(base * coverage * weight))


def refresh_population_record(record: dict) -> None:
    record["weight_class_tier"] = weight_class_tier(record["machine_operating_weight_lb"])
    record["coverage_multiplier"] = num(coverage_multiplier(record["machine_serial"]))
    record["projected_annual_parts_units"] = projected_annual_parts_units(record)


def dealer_population(dealer_id, active_only=True) -> list:
    records = [r for r in db.rows("machine_population_records") if r["dealer_id"] == dealer_id]
    if active_only:
        records = [r for r in records if r["status"] == "ACTIVE"]
    return records


def forecast_parts_demand(dealer_id) -> dict:
    per_record_total = 0
    exact_total = D("0")
    for record in dealer_population(dealer_id, active_only=True):
        base = D(base_annual_parts_units(record["product_family"]))
        coverage = coverage_multiplier(record["machine_serial"])
        weight = weight_class_tier_multiplier(record["machine_operating_weight_lb"])
        product = base * coverage * weight
        exact_total += product
        per_record_total += int(math.ceil(product))
    return {
        "forecast_parts_demand_units": per_record_total,
        "per_record_total": per_record_total,
        "sum_then_ceiling_total": int(math.ceil(exact_total)),
    }


def dealer_coverage_snapshot(record: dict, commitment: dict | None) -> dict:
    agreement = covering_support_agreement(record["machine_serial"])
    if agreement is not None:
        coverage = D("100") * coverage_multiplier(record["machine_serial"]) / D("1.5")
    else:
        numerator = D(record.get("machine_population_units", 0))
        denominator = D("1")
        if commitment is not None:
            denominator = max(D("1"), tier_weighted_numerator(commitment))
        coverage = D("100") * numerator / denominator
    return {
        "machine_serial": record["machine_serial"],
        "coverage_pct": num(q4(coverage)),
        "weight_class_tier": weight_class_tier(record["machine_operating_weight_lb"]),
    }


def sweep_metrics(dealer_id) -> dict:
    records = [r for r in db.rows("machine_population_records") if r["dealer_id"] == dealer_id and r["status"] == "ACTIVE"]
    records.sort(key=lambda r: (r["created_at"], r["machine_serial"]))
    if not records:
        return {"text_sweep_est_monthly_parts_value_cents": None, "text_sweep_vendor_code_matches": 0}
    first_serial = records[0]["machine_serial"]
    trigger = False
    for commitment in dealer_commitments(dealer_id):
        for record in records:
            if record["machine_serial"] != first_serial:
                continue
            if record["product_family"] == commitment["product_family"] and commitment["status"] in (
                "CORE_PENDING",
                "PERFORMANCE_DEFICIENT",
            ):
                trigger = True
    if trigger:
        total = sum((index + 1) * 100 for index, _ in enumerate(records))
        return {"text_sweep_est_monthly_parts_value_cents": total, "text_sweep_vendor_code_matches": None}
    matches = 0
    for record in records:
        for commitment in dealer_commitments(dealer_id):
            if commitment["product_family"] != record["product_family"]:
                continue
            if commitment["status"] == "ORDER_READY":
                matches += 1
                break
    return {"text_sweep_est_monthly_parts_value_cents": None, "text_sweep_vendor_code_matches": matches}


# ===========================================================================
# §3.7 core credit / rebuild pricing
# ===========================================================================
def core_values(core_purchase_value_cents) -> dict:
    core_value = q2(D(core_purchase_value_cents) * CORE_CREDIT_RATE)
    handling = q2(core_value * CERTIFIED_HANDLING_MARGIN)
    credit = core_value + handling
    increment = q2(credit + D("3") * core_value)
    return {
        "core_value": core_value,
        "core_handling_fee": handling,
        "core_return_credit_cents": credit,
        "credited_settlement_units_increment": increment,
    }


def credited_units_increment() -> int:
    """Cents one returned core settles on a commitment's credit balance.

    §2.10 names this figure directly: one returned core settles 1610 cents of
    the 103040-cent arrear, which is the same constant the deferred shortage
    rule consumes.
    """
    return SETTLEMENT_PER_CORE_CENTS


def rebuild_fee(core_value: Decimal, rebuild_labor_hours, rebuild_labor_rate_cents) -> int:
    rate_per_hour = q2(core_value * LABOR_RATE_WEIGHT_FACTOR)
    labor_component = q2(D(rebuild_labor_hours) * rate_per_hour)
    handling_component = q2(core_value * CERTIFIED_HANDLING_MARGIN)
    return int(q2(labor_component + handling_component))


def dealer_settlement_offset(dealer_id) -> Decimal:
    records = dealer_population(dealer_id, active_only=True)
    if not records:
        mean_hours = D("0")
    else:
        mean_hours = sum((D(r["meter_hours"]) for r in records), D("0")) / D(len(records))
    return q2(D(MANDATE_SETTLEMENT_ARREAR_CENTS) - D(RESTRICTION_UNIT_CENTS) * mean_hours)


# ===========================================================================
# §3.6 performance measures
# ===========================================================================
def quality_index(review: dict) -> Decimal:
    sampled = int(review["sampled_service_orders"])
    if sampled == 0:
        return D("0")
    return q4(D("100") * D(review["met_sla_service_orders"]) / D(sampled))


def machine_lifetime_value(dealer: dict) -> Decimal:
    """The dealer's lifetime-value bonus, expressed in dollars."""
    total = D("0")
    seen = set()
    for record in dealer_population(dealer["id"], active_only=True):
        serial = record["machine_serial"]
        if serial in seen:
            continue
        seen.add(serial)
        commitment = None
        for candidate in dealer_commitments(dealer["id"]):
            if candidate["product_family"] == record["product_family"]:
                commitment = candidate
                break
        if commitment is not None and commitment["status"] == "ORDER_READY":
            core_value = D("0")
            core_fee = D("0")
        else:
            best = None
            for claim in db.rows("rebuild_claims"):
                if claim["dealer_id"] != dealer["id"] or claim["machine_serial"] != serial:
                    continue
                if claim.get("core_purchase_value_cents") is None:
                    continue
                key = (claim["created_at"], D(claim["core_purchase_value_cents"]))
                if best is None or key > best[0]:
                    best = (key, claim)
            core_value = D("0") if best is None else D(best[1]["core_purchase_value_cents"])
            core_fee = q2(core_value * CERTIFIED_HANDLING_MARGIN) if best is not None else D("0")
        total += core_value + core_fee
    return q2(total / D("100"))


def compute_review_share(review: dict) -> None:
    """actual_market_share_pct and performance_ratio_pct, stored as reported."""
    market_units = int(review["territory_market_machine_units"])
    if market_units == 0:
        share = D("0.0")
    else:
        share = q4(D("100") * D(review["actual_territory_machine_units"]) / D(market_units))
    review["actual_market_share_pct"] = num(share)

    agreement = db.find("dealer_agreements", review["agreement_id"])
    plan = D("0") if agreement is None else D(str(agreement["performance_plan_share_pct"]))
    if share >= D("100"):
        ratio = D("100.0")
    elif plan == 0:
        ratio = D("0.0")
    else:
        ratio = q4(D("100") * share / plan)
    review["performance_ratio_pct"] = num(ratio)


def market_share_from_observations(dealer_id, period_start: datetime, period_end: datetime) -> Decimal:
    numerator = D("0")
    denominator = D("0")
    for observation in db.rows("market_share_observations"):
        if observation["dealer_id"] != dealer_id:
            continue
        recorded = db.as_dt(observation["recorded_at"])
        if not (period_start <= recorded < period_end):
            continue
        weight = D("1.0") if observation["kind"] == "MACHINE" else D("0.5")
        numerator += D(observation["observed_machine_units"]) * weight
        denominator += D(observation["territory_machine_units"]) * weight
    if denominator == 0:
        return D("0.0")
    return q4(D("100") * numerator / denominator)


# ===========================================================================
# Cross-aggregate side effects
# ===========================================================================
def recompute_agreement_commitment_mandates(agreement: dict) -> None:
    for commitment in db.rows("parts_commitments"):
        if commitment["agreement_id"] != agreement["id"]:
            continue
        compute_stocking_mandate(commitment)
        touch(commitment)


def recompute_dealer_commitment_tiers(dealer_id, product_family=None) -> None:
    for commitment in dealer_commitments(dealer_id):
        if product_family is not None and commitment["product_family"] != product_family:
            continue
        compute_stocking_mandate(commitment)
        touch(commitment)


def suppress_deferred_rule_for_dealer(dealer_id, active: bool) -> None:
    for commitment in dealer_commitments(dealer_id):
        set_deferred_rule(commitment["id"], active)


def refresh_serial_coverage(machine_serial) -> None:
    for record in db.rows("machine_population_records"):
        if record["machine_serial"] == machine_serial:
            refresh_population_record(record)
            touch(record)


def maybe_auto_performance_deficient(commitment: dict) -> None:
    """Automatic ORDER_READY -> PERFORMANCE_DEFICIENT at the availability edge."""
    if commitment["status"] != "ORDER_READY":
        return
    threshold = int(commitment["required_stocking_units_final"]) - int(commitment["committed_units"])
    if int(commitment["available_commitment_units"]) < threshold:
        commitment["status"] = "PERFORMANCE_DEFICIENT"
        commitment["backorder_opened_at"] = db.stamp()
        set_deferred_rule(commitment["id"], False)
        touch(commitment)
        dealer = db.find("dealers", commitment["dealer_id"])
        if dealer is not None:
            recompute_open_backorder_units(dealer)
        open_service_order(
            dealer_id=commitment["dealer_id"],
            commitment=commitment,
            kind="EMERGENCY_FILL",
            machine_serial=None,
        )


def maybe_auto_complete(commitment: dict) -> None:
    """Automatic ORDER_READY -> COMPLETE once the arrear and batches clear."""
    if commitment["status"] not in ("ORDER_READY", "CORE_PENDING", "PERFORMANCE_DEFICIENT"):
        return
    threshold = int(commitment["required_stocking_units_final"]) * 100
    if int(commitment["credit_balance_cents"]) < threshold:
        return
    batches = commitment_batches(commitment["id"])
    if not batches:
        return
    if any(b["status"] != "CLOSED" for b in batches):
        return
    commitment["status"] = "COMPLETE"
    touch(commitment)
    set_deferred_rule(commitment["id"], False)
    dealer = db.find("dealers", commitment["dealer_id"])
    if dealer is not None:
        recompute_open_backorder_units(dealer)


def open_service_order(dealer_id, commitment, kind, machine_serial=None, origin_rebuild_id=None,
                       sla_hours=0.0, restriction_scope="HOURS_SPENT", orderable_ref_enabled=False):
    """Open a service order from inside a workflow (never a client call)."""
    record = {
        "id": db.new_id(),
        "dealer_id": dealer_id,
        "commitment_id": commitment["id"] if commitment is not None else None,
        "kind": kind,
        "product_family": commitment["product_family"] if commitment is not None else None,
        "machine_serial": machine_serial,
        "orderable_ref_enabled": orderable_ref_enabled,
        "restriction_scope": restriction_scope,
        "response_window_hours": None,
        "sla_hours": sla_hours,
        "origin_rebuild_id": origin_rebuild_id,
        "opened_at": db.stamp(),
        "resolved_at": None,
        "status": "OPEN",
    }
    init_common(record)
    db.insert("service_orders", record)
    recompute_service_order_derived(record)
    recompute_deferral_tiers(dealer_id)
    return record


def open_restriction_order_for_claim(claim: dict) -> dict:
    commitment = first_family_commitment(claim["dealer_id"], claim["product_family"])
    return open_service_order(
        dealer_id=claim["dealer_id"],
        commitment=commitment,
        kind="RESTRICTION",
        machine_serial=claim["machine_serial"],
    )


def first_family_commitment(dealer_id, product_family):
    for commitment in dealer_commitments(dealer_id):
        if commitment["product_family"] == product_family:
            return commitment
    return None


def has_batch_open_or_ordered(commitment_ids) -> bool:
    for batch in db.rows("parts_order_batches"):
        if batch["commitment_id"] in commitment_ids and batch["status"] in ("OPEN", "ORDERED"):
            return True
    return False


# ===========================================================================
# Serialisation
# ===========================================================================
def serialize(table_name: str, record: dict) -> dict:
    return _SHAPERS[table_name](record)


def _base(record: dict, fields) -> dict:
    out = {"id": record["id"]}
    out["created_at"] = record["created_at"]
    if "updated_at" in record:
        out["updated_at"] = record["updated_at"]
    if "version" in record:
        out["version"] = record["version"]
    for name in fields:
        if name in ("id", "created_at", "updated_at", "version"):
            continue
        out[name] = record.get(name)
    return out


def _dealer(record):
    return _base(
        record,
        [
            "legal_name",
            "home_state_code",
            "territory_code",
            "status",
            "certified_family_count",
            "trusted_commitment_count",
            "open_backorder_units",
            "market_share_pct",
        ],
    )


def _agreement(record):
    return _base(
        record,
        [
            "dealer_id",
            "product_family",
            "territory_code",
            "exclusivity_level",
            "start_at",
            "end_at",
            "status",
            "performance_plan_share_pct",
            "performance_actual_share_pct",
            "certified_technician_count",
            "tooling_compliance_status",
            "trusted_commitment",
            "closed_at",
        ],
    )


def _review(record):
    # PerformanceReview is declared without the common field set: id and
    # created_at only — no updated_at, no version.
    out = {"id": record["id"], "created_at": record["created_at"]}
    for name in (
        "dealer_id",
        "agreement_id",
        "period_start",
        "period_end",
        "status",
        "actual_territory_machine_units",
        "territory_market_machine_units",
        "actual_market_share_pct",
        "performance_ratio_pct",
        "quality_deficiency_pp",
        "quality_deficient",
        "sampled_service_orders",
        "met_sla_service_orders",
        "discrepancy_pp",
        "circumstance_note",
        "loyalty_score",
    ):
        out[name] = record.get(name)
    return out


def _commitment(record):
    return _base(
        record,
        [
            "agreement_id",
            "dealer_id",
            "product_family",
            "machine_population_units",
            "machine_population_slope",
            "machine_population_tier",
            "planned_annual_units",
            "emergency_stocking_target_pct",
            "emergency_fill_window_hours",
            "required_stocking_units",
            "required_stocking_units_final",
            "available_commitment_units",
            "availability_target_pct",
            "emergency_tier",
            "committed_units",
            "fulfilled_units",
            "fill_rate_pct",
            "credit_balance_cents",
            "status",
            "backorder_opened_at",
        ],
    )


def _batch(record):
    return _base(
        record,
        [
            "commitment_id",
            "product_family",
            "requested_units",
            "reserved_units",
            "unfilled_units",
            "status",
            "requested_at",
            "received_at",
            "emergency",
            "core_return_required",
            "core_units",
            "core_return_credit_cents",
        ],
    )


def _certification(record):
    out = _base(record, ["dealer_id", "technician_name", "product_family", "credential_code", "certified_at", "recurrence_within_period", "status"])
    out["status"] = cert_status(record)
    return out


def _claim(record):
    return _base(
        record,
        [
            "dealer_id",
            "product_family",
            "machine_serial",
            "machine_operating_weight_lb",
            "client_meter_hours",
            "requested_at",
            "core_purchase_value_cents",
            "core_return_credit_cents",
            "core_returned_at",
            "rebuild_labor_hours",
            "rebuild_labor_rate_cents",
            "rebuild_fee_cents",
            "certified_rebuild_spec_code",
            "status",
        ],
    )


def _equipment_order(record):
    return _base(
        record,
        [
            "dealer_id",
            "product_family",
            "machine_serial",
            "list_price_cents",
            "trade_in_serial",
            "status",
            "financing_approval_reference",
            "supportable_machine_registered",
            "requested_at",
            "bundle_support_plan",
        ],
    )


def _trade_in(record):
    return _base(
        record,
        [
            "order_id",
            "machine_serial",
            "machine_operating_weight_lb",
            "appraised_value_cents",
            "status",
        ],
    )


def _support_agreement(record):
    return _base(record, ["dealer_id", "machine_serial", "plan_tier", "enrolled_at", "coverage_multiplier", "status"])


def _observation(record):
    return _base(
        record,
        ["dealer_id", "product_family", "observed_machine_units", "territory_machine_units", "observed_share_pct", "recorded_at", "kind"],
    )


def _party(record):
    return _base(record, ["dealer_id", "territory_code", "registered_at", "status"])


def _population(record):
    return _base(
        record,
        [
            "dealer_id",
            "product_family",
            "machine_serial",
            "machine_operating_weight_lb",
            "meter_hours",
            "weight_class_tier",
            "coverage_multiplier",
            "projected_annual_parts_units",
            "status",
        ],
    )


def _service_order(record):
    return _base(
        record,
        [
            "dealer_id",
            "commitment_id",
            "kind",
            "product_family",
            "machine_serial",
            "orderable_ref_enabled",
            "response_window_hours",
            "restriction_scope",
            "priority_rank",
            "risk_score",
            "sla_hours",
            "emergency_filled_units",
            "deferral_tier",
            "origin_rebuild_id",
            "opened_at",
            "resolved_at",
            "status",
        ],
    )


_SHAPERS = {
    "dealers": _dealer,
    "dealer_agreements": _agreement,
    "performance_reviews": _review,
    "parts_commitments": _commitment,
    "parts_order_batches": _batch,
    "certification_records": _certification,
    "rebuild_claims": _claim,
    "equipment_orders": _equipment_order,
    "trade_in_units": _trade_in,
    "support_agreements": _support_agreement,
    "market_share_observations": _observation,
    "party_registrations": _party,
    "machine_population_records": _population,
    "service_orders": _service_order,
}


# ===========================================================================
# List helpers
# ===========================================================================
def sort_by_created(records: list) -> list:
    return sorted(records, key=lambda r: r["created_at"])


# ===========================================================================
# Dealer working balance and delivery charge against a restriction
# ===========================================================================
def dealer_restriction_credit(dealer_id) -> int:
    return int(db.STATE["deferral_slots"].get("credit:" + str(dealer_id), 0))


def adjust_dealer_restriction_credit(dealer_id, delta: int) -> None:
    key = "credit:" + str(dealer_id)
    db.STATE["deferral_slots"][key] = int(db.STATE["deferral_slots"].get(key, 0)) + int(delta)


def trade_in_serial_for(dealer_id, trade_in_serial) -> str:
    """The taken-in serial carrying the dealer's current client meter hours."""
    latest = None
    for claim in db.rows("rebuild_claims"):
        if claim["dealer_id"] != dealer_id or claim.get("client_meter_hours") is None:
            continue
        if latest is None or claim["created_at"] > latest["created_at"]:
            latest = claim
    meter = 0 if latest is None else latest["client_meter_hours"]
    return "%s%s" % (trade_in_serial, num(D(str(meter))))


def serial_matches(candidate, machine_serial) -> bool:
    """A taken-in serial carries the machine serial with meter hours affixed."""
    if candidate == machine_serial:
        return True
    return str(candidate).startswith(str(machine_serial))


def recompute_supportable_machine_registered(order: dict) -> None:
    registered = any(
        a["machine_serial"] == order["machine_serial"] and a["status"] == "ACTIVE"
        for a in db.rows("support_agreements")
    )
    order["supportable_machine_registered"] = bool(registered)


def charge_restriction_deferral(dealer_id) -> None:
    """Charge a delivery against the latest restriction's deferral tier."""
    restrictive = [
        o
        for o in db.rows("service_orders")
        if o["dealer_id"] == dealer_id and o["kind"] == "RESTRICTION"
    ]
    if not restrictive:
        return
    restrictive.sort(key=lambda o: o["created_at"])
    latest = restrictive[-1]
    if latest["restriction_scope"] != "FULL_STOP":
        return
    # Consume one pending deferral slot rather than opening a new re-evaluation.
    key = "slots:" + str(dealer_id)
    slots = int(db.STATE["deferral_slots"].get(key, 0))
    db.STATE["deferral_slots"][key] = max(0, slots - 1)


def matches_filters(record: dict, filters: dict) -> bool:
    for key, value in filters.items():
        if value is None:
            continue
        if record.get(key) != value:
            return False
    return True