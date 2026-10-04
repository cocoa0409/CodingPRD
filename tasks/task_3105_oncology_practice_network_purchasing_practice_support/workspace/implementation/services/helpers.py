"""Shared lookups, validation helpers and recomputation rules."""

from decimal import Decimal

import db
from errors import ApiError
from utils import (
    add_months,
    exact_div,
    num,
    parse_iso,
    ratio4,
    utc_now_dt,
)

TIERS = ("TIER_1", "TIER_2", "TIER_3")


# ---------------------------------------------------------------------------
# Body / field validation (priority 16: ERR_INVALID_REQUEST)


def as_str(data, key, required_=True, default=None):
    if key not in data or data[key] is None:
        if required_:
            raise ApiError("ERR_INVALID_REQUEST", "missing required field: %s" % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "field %s must be a string" % key)
    return value


def as_int(data, key, default=None, required_=False, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        if required_:
            raise ApiError("ERR_INVALID_REQUEST", "missing required field: %s" % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "field %s must be an integer" % key)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "field %s below its minimum" % key)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "field %s above its maximum" % key)
    return value


def as_num(data, key, default=None, required_=False):
    if key not in data or data[key] is None:
        if required_:
            raise ApiError("ERR_INVALID_REQUEST", "missing required field: %s" % key)
        return default
    value = num(data[key])
    if value is None:
        raise ApiError("ERR_INVALID_REQUEST", "field %s must be a number" % key)
    return value


def as_bool(data, key, default=False):
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "field %s must be a boolean" % key)
    return value


def as_enum(data, key, allowed, default=None, required_=False):
    if key not in data or data[key] is None:
        if required_:
            raise ApiError("ERR_INVALID_REQUEST", "missing required field: %s" % key)
        return default
    value = data[key]
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "field %s outside its enum" % key)
    return value


def as_list(data, key, default=None, required_=False):
    if key not in data or data[key] is None:
        if required_:
            raise ApiError("ERR_INVALID_REQUEST", "missing required field: %s" % key)
        return default
    value = data[key]
    if not isinstance(value, list):
        raise ApiError("ERR_INVALID_REQUEST", "field %s must be an array" % key)
    return value


def as_dt(data, key, default=None, required_=False):
    if key not in data or data[key] is None:
        if required_:
            raise ApiError("ERR_INVALID_REQUEST", "missing required field: %s" % key)
        return default
    parsed = parse_iso(data[key])
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "field %s must be an ISO 8601 instant" % key)
    return parsed


def check_occ(body, parent_record, field_name="expected_practice_version"):
    """Priority 3.5: when the request carries expected_<parent>_version it must
    equal the parent's current version, and the check runs BEFORE any business
    logic. The field is not optional on the three operations that declare it."""
    if body.get(field_name) is None:
        raise ApiError("ERR_INVALID_REQUEST", "missing required field: %s" % field_name)
    expected = body.get(field_name)
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "field %s must be an integer" % field_name)
    if expected != parent_record.get("version", 1):
        raise ApiError("ERR_VERSION_MISMATCH")


# ---------------------------------------------------------------------------
# Lookups (priority 3: 404, resolved left to right along the path)


def network_or_404(network_id):
    rec = db.get("networks", network_id)
    if rec is None:
        raise ApiError("ERR_NETWORK_NOT_FOUND")
    return rec


def practice_or_404(practice_id):
    rec = db.get("practices", practice_id)
    if rec is None:
        raise ApiError("ERR_PRACTICE_NOT_FOUND")
    return rec


def provider_or_404(provider_id):
    rec = db.get("providers", provider_id)
    if rec is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND")
    return rec


def product_or_404(product_id):
    rec = db.get("drug_products", product_id)
    if rec is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND")
    return rec


def agreement_or_404(agreement_id):
    rec = db.get("pricing_agreements", agreement_id)
    if rec is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND")
    return rec


def order_or_404(order_id):
    rec = db.get("purchase_orders", order_id)
    if rec is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")
    return rec


def lot_or_404(lot_id):
    rec = db.get("inventory_lots", lot_id)
    if rec is None:
        raise ApiError("ERR_LOT_NOT_FOUND")
    return rec


def treatment_or_404(treatment_id):
    rec = db.get("treatments", treatment_id)
    if rec is None:
        raise ApiError("ERR_TREATMENT_NOT_FOUND")
    return rec


def claim_or_404(claim_id):
    rec = db.get("claims", claim_id)
    if rec is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    return rec


def program_or_404(program_id):
    rec = db.get("rebate_programs", program_id)
    if rec is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND")
    return rec


def qualification_or_404(qualification_id):
    rec = db.get("rebate_qualifications", qualification_id)
    if rec is None:
        raise ApiError("ERR_QUALIFICATION_NOT_FOUND")
    return rec


def protocol_or_404(protocol_id):
    rec = db.get("pathway_protocols", protocol_id)
    if rec is None:
        raise ApiError("ERR_PROTOCOL_NOT_FOUND")
    return rec


def management_or_404(agreement_id):
    rec = db.get("management_agreements", agreement_id)
    if rec is None:
        raise ApiError("ERR_MANAGEMENT_AGREEMENT_NOT_FOUND")
    return rec


def participation_or_404(participation_id):
    rec = db.get("research_participations", participation_id)
    if rec is None:
        raise ApiError("ERR_PARTICIPATION_NOT_FOUND")
    return rec


def shortage_or_404(shortage_id):
    rec = db.get("drug_shortages", shortage_id)
    if rec is None:
        raise ApiError("ERR_SHORTAGE_NOT_FOUND")
    return rec


def allocation_or_404(allocation_id):
    rec = db.get("shortage_allocations", allocation_id)
    if rec is None:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND")
    return rec


def contract_or_404(contract_id):
    rec = db.get("affiliation_contracts", contract_id)
    if rec is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND")
    return rec


# ---------------------------------------------------------------------------
# Network-scoped referential integrity (priority 15)


def network_id_of(record):
    """The network a record belongs to, following its owning chain."""
    if record is None:
        return None
    if record.get("network_id"):
        return record["network_id"]
    if record.get("practice_id"):
        practice = db.get("practices", record["practice_id"])
        return practice.get("network_id") if practice else None
    if record.get("treatment_id"):
        return network_id_of(db.get("treatments", record["treatment_id"]))
    if record.get("shortage_id"):
        shortage = db.get("drug_shortages", record["shortage_id"])
        return shortage.get("network_id") if shortage else None
    if record.get("rebate_program_id"):
        program = db.get("rebate_programs", record["rebate_program_id"])
        return program.get("network_id") if program else None
    if record.get("purchase_order_id"):
        return network_id_of(db.get("purchase_orders", record["purchase_order_id"]))
    return None


def same_network(record, network_id):
    if record is None or network_id is None:
        return True
    return network_id_of(record) == network_id


# ---------------------------------------------------------------------------
# Tier ladder


def ladder_tier(network, spend_cents):
    """Read the ordered descending tier ladder; TIER_3 is the highest rung."""
    ladder = network.get("tier_market_share_boundaries") or []
    for rung in ladder:
        if not isinstance(rung, dict):
            continue
        minimum = num(rung.get("min_trailing_12m_purchases_cents"))
        tier = rung.get("tier")
        if minimum is None or tier not in TIERS:
            continue
        if Decimal(spend_cents or 0) >= minimum:
            return tier
    return "TIER_1"


def has_suspended_agreement(practice_id):
    return any(
        a["status"] == "SUSPENDED"
        for a in db.where("pricing_agreements", practice_id=practice_id)
    )


def recompute_tier(practice):
    """Recompute tier_level from trailing purchases. A practice whose pricing is
    suspended buys at the entry tier, so the suspension reaches the ladder."""
    if has_suspended_agreement(practice["id"]):
        practice["tier_level"] = "TIER_1"
        return
    network = db.get("networks", practice.get("network_id"))
    if network is None:
        practice["tier_level"] = "TIER_1"
        return
    practice["tier_level"] = ladder_tier(
        network, practice.get("trailing_12m_network_purchases_cents", 0)
    )


def tier_from_latest_agreement(practice):
    """Affiliation consumes the tier the practice was sold: the tier of the most
    recently created agreement, tie-broken by latest effective_from then the
    greater identifier lexicographically."""
    rows = db.where("pricing_agreements", practice_id=practice["id"])
    if not rows:
        return None
    rows.sort(
        key=lambda a: (a.get("created_at") or "", a.get("effective_from") or "", a["id"])
    )
    return rows[-1].get("tier_level")


# ---------------------------------------------------------------------------
# Affiliation contracts


def affiliation_contracts(practice_id):
    return db.where("affiliation_contracts", practice_id=practice_id)


def active_contract(practice_id):
    rows = [c for c in affiliation_contracts(practice_id) if c["status"] == "ACTIVE"]
    if not rows:
        return None
    rows.sort(
        key=lambda c: (c.get("term_start") or "", c.get("created_at") or "", c["id"])
    )
    return rows[-1]


def earliest_contract_start(practice_id):
    starts = [c["term_start"] for c in affiliation_contracts(practice_id) if c.get("term_start")]
    return min(starts) if starts else None


def contract_covers(contract, instant):
    """term_start at or before the instant, and the instant strictly before
    term_end."""
    if contract is None:
        return False
    start = parse_iso(contract.get("term_start"))
    end = parse_iso(contract.get("term_end"))
    if start is None or end is None:
        return False
    return start <= instant < end


# ---------------------------------------------------------------------------
# Pricing agreements


def agreements_of(practice_id):
    return db.where("pricing_agreements", practice_id=practice_id)


def resolve_active_agreement(practice_id, instant):
    """The single ACTIVE agreement whose half-open window covers the instant:
    latest effective_from, then latest created_at, then greatest identifier."""
    covering = []
    for a in agreements_of(practice_id):
        if a["status"] != "ACTIVE":
            continue
        start = parse_iso(a.get("effective_from"))
        end = parse_iso(a.get("effective_to"))
        if start is None or instant < start:
            continue
        if end is not None and not (instant < end):
            continue
        covering.append(a)
    if not covering:
        return None
    covering.sort(
        key=lambda a: (a.get("effective_from") or "", a.get("created_at") or "", a["id"])
    )
    return covering[-1]


def windows_intersect(a_start, a_end, b_start, b_end):
    """Half-open intersection test: the instant a_end/b_end is outside its own
    window, so a window starting exactly at the other's end does not intersect."""
    if a_end is not None and b_start is not None and not (b_start < a_end):
        return False
    if b_end is not None and a_start is not None and not (a_start < b_end):
        return False
    return True


def epoch_closed_at(network, period_epoch_index):
    """The instant an epoch's measurement period closes: the network's creation
    anniversary advanced one month per period."""
    anchor = parse_iso(network.get("created_at")) if network else None
    if anchor is None:
        anchor = utc_now_dt()
    return add_months(anchor, int(period_epoch_index or 0))


def epoch_window(network, period_epoch_index):
    """Half-open measured window [start, end) for a period."""
    anchor = parse_iso(network.get("created_at")) if network else None
    if anchor is None:
        anchor = utc_now_dt()
    period = int(period_epoch_index or 0)
    return add_months(anchor, max(period - 1, 0)), add_months(anchor, period)


# ---------------------------------------------------------------------------
# Practice-level recomputations


def price_transparency_score(practice_id):
    """1.0 when every pricing agreement of the practice is ACTIVE, 0.0 when at
    least one is SUSPENDED."""
    rows = agreements_of(practice_id)
    if any(a["status"] == "SUSPENDED" for a in rows):
        return Decimal(0)
    return Decimal(1)


def adherence_over(treatments):
    counted = [t for t in treatments if t["status"] in ("ADMINISTERED", "BILLED")]
    if not counted:
        return Decimal(0)
    good = sum(1 for t in counted if t.get("is_pathway_concordant"))
    return Decimal(good) / Decimal(len(counted))


def recompute_adherence(practice):
    """pathway_adherence_pct over the practice's ADMINISTERED/BILLED rows,
    persisted to four decimal places."""
    rows = db.where("treatments", practice_id=practice["id"])
    practice["pathway_adherence_pct"] = ratio4(adherence_over(rows))


def settled_counts(practice_id):
    rows = db.where("claims", practice_id=practice_id)
    denied = sum(1 for c in rows if c["status"] == "DENIED")
    settled = sum(1 for c in rows if c["status"] in ("DENIED", "ADJUDICATED_PAID"))
    return denied, settled


def denial_ratio_exact(practice):
    """Exact rational arithmetic; the threshold comparison uses this value and
    never a rounded one. VOIDED, DRAFT, SUBMITTED and APPEALED rows are excluded
    from both numerator and denominator."""
    denied, settled = settled_counts(practice["id"])
    practice["denied_claim_count"] = denied
    practice["settled_claim_count"] = settled
    if settled == 0:
        return Decimal(0)
    return exact_div(denied, settled)


def denial_ratio_reported(practice):
    return ratio4(denial_ratio_exact(practice))


def recompute_freeze(network):
    """is_commercial_terms_frozen reads true while at least one practice of the
    network is DEPARTED or DEPARTING. An operator-ordered freeze is recorded
    separately and is not undone by a recompute."""
    if network is None:
        return False
    departing = any(
        p["affiliation_status"] in ("DEPARTED", "DEPARTING")
        for p in db.where("practices", network_id=network["id"])
    )
    network["is_commercial_terms_frozen"] = bool(network.get("_freeze_ordered")) or departing
    return network["is_commercial_terms_frozen"]


def order_freeze(network, ordered):
    """Record an operator freeze order and recompute the flag."""
    network["_freeze_ordered"] = bool(ordered)
    return recompute_freeze(network)


# A pathway protocol declares its drug-class scope through `indication`. The two
# vocabularies are distinct, so a protocol is taken as scoped to the product's
# class when it names that class explicitly, and otherwise as unconstrained by
# class — the guard's teeth are the PUBLISHED requirement.
THERAPEUTIC_CLASSES = ("CYTOTOXIC", "IMMUNOTHERAPY", "SUPPORTIVE_CARE", "ORAL_TARGETED")


def protocol_matches_product(protocol, product):
    if protocol is None or product is None:
        return False
    if protocol.get("status") != "PUBLISHED":
        return False
    indication = protocol.get("indication")
    if indication in THERAPEUTIC_CLASSES:
        return indication == product.get("therapeutic_class")
    return True


def may_edit_practice(principal, practice_id):
    """A PracticeAdmin principal acts only within its own scope (PRD S2.1)."""
    from auth import ROLE_PRACTICE_ADMIN

    if principal.role != ROLE_PRACTICE_ADMIN:
        return True
    return principal.user_id == practice_id