"""Business logic: serializers, computed fields, calculations, cascades."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import constants as C
from db import store, iso_z, new_id


# ---------------------------------------------------------------------------
# Derived / computed field helpers
# ---------------------------------------------------------------------------

def waiting_time_days(recipient):
    delta = store.now() - _parse(recipient["listed_at_utc"])
    return max(0, delta.days)


def _parse(ts):
    from db import parse_iso
    return parse_iso(ts)


def recompute_center_active_chain_count(center):
    count = 0
    for ch in store.chains.values():
        if ch["chain_state"] != "SCHEDULED":
            continue
        involved = False
        for o in store.offers.values():
            if o["chain_id"] == ch["id"] and (
                o["donor_center_id"] == center["id"] or o["recipient_center_id"] == center["id"]
            ):
                involved = True
                break
        if not involved and ch.get("starts_at_center_id") == center["id"]:
            involved = True
        if involved:
            count += 1
    center["active_chain_count"] = count


def recompute_all_active_chain_counts():
    for c in store.centers.values():
        recompute_center_active_chain_count(c)


def recompute_reputation(center):
    failure_component = min(
        C.REPUTATION_FAILURE_CAP_BPS,
        center["failed_outcome_count"] * C.REPUTATION_FAILURE_PENALTY_BPS,
    )
    cit_component = center["probed_cold_ischemia_violations"] * C.REPUTATION_CIT_PENALTY_BPS
    shipment_component = min(
        C.REPUTATION_SHIPMENT_CAP_BPS,
        center["shipped_organ_count"] * C.REPUTATION_SHIPMENT_BONUS_BPS,
    )
    raw = C.REPUTATION_BASE_BPS - failure_component - cit_component + shipment_component
    center["reputation_score_bps"] = max(0, min(10000, raw))


def recompute_donor_travel(donor):
    donor["traveled_distance_miles"] = sum(
        it["segment_miles"]
        for it in store.itineraries.values()
        if it["donor_id"] == donor["id"] and it["itinerary_state"] == "CONFIRMED"
    )


def chain_offers(chain_id):
    return sorted(
        (o for o in store.offers.values() if o["chain_id"] == chain_id),
        key=lambda o: o["position_index"],
    )


def chain_by_offer(offer):
    return store.chains.get(offer["chain_id"])


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def serialize_center(c):
    return dict(c)


def serialize_donor(d):
    return dict(d)


def serialize_recipient(r):
    out = dict(r)
    out["waiting_time_days"] = waiting_time_days(r)
    return out


def serialize_pair(p):
    return dict(p)


def serialize_chain_run(r):
    return dict(r)


def serialize_chain(ch):
    return dict(ch)


def serialize_offer(o):
    return dict(o)


def serialize_review(rv):
    return dict(rv)


def serialize_slot(s):
    return dict(s)


def serialize_shipment(s):
    return dict(s)


def serialize_itinerary(it):
    return dict(it)


def serialize_policy(p):
    return dict(p)


def serialize_claim(cl):
    return dict(cl)


def serialize_outcome(oc):
    return dict(oc)


def serialize_chain_break(ev):
    return dict(ev)


# ---------------------------------------------------------------------------
# Calculations (§1.3)
# ---------------------------------------------------------------------------

ABO_DONOR_MAP = {
    "O": {"A", "B", "AB", "O"},
    "A": {"A", "AB"},
    "B": {"B", "AB"},
    "AB": {"AB"},
}


def abo_compatible(donor, recipient):
    return recipient["abo_type"] in ABO_DONOR_MAP.get(donor["abo_type"], set())


def _locus_set(value):
    return {a.strip() for a in str(value).split(",") if a.strip()}


def hla_mismatch_count(donor, recipient):
    count = 0
    for locus in ("hla_a", "hla_b", "hla_drb1"):
        d = _locus_set(donor.get(locus, ""))
        r = _locus_set(recipient.get(locus, ""))
        if not (d & r):
            count += 1
    return count


def unacceptable_antigen_hit(donor, recipient):
    donor_antigens = (
        _locus_set(donor.get("hla_a", ""))
        | _locus_set(donor.get("hla_b", ""))
        | _locus_set(donor.get("hla_drb1", ""))
    )
    return bool(donor_antigens & set(recipient.get("unacceptable_antigens") or []))


def match_score_bps(donor, recipient, compat, hit, mismatch):
    if not compat:
        return 0
    if hit:
        return 0
    kdri = donor["kdri_score"]
    kdri_component = max(
        0,
        min(
            10000,
            int(10000 - (kdri - C.KDRI_MIN) * 10000 / (C.KDRI_MAX - C.KDRI_MIN)),
        ),
    )
    hla_penalty = mismatch * C.HLA_PENALTY_PER_LOCUS_BPS
    wait_bonus = min(
        C.WAIT_BONUS_CAP_BPS, waiting_time_days(recipient) * C.WAIT_BONUS_PER_DAY_BPS
    )
    priority_bonus = C.PRIORITY_BOOST_BPS if recipient.get("priority_boost_active") else 0
    cpra_bonus = recipient["cpra_percent"] * C.CPRA_BONUS_PER_PCT_BPS
    raw = kdri_component - hla_penalty + wait_bonus + priority_bonus + cpra_bonus
    return max(0, min(10000, raw))


def crossmatch_decision(virtual_result, dsa_mfi_max):
    if virtual_result == "NEGATIVE":
        return "PASS" if dsa_mfi_max < C.DSA_PASS_THRESHOLD else "FAIL"
    if virtual_result == "WEAK_POSITIVE":
        return "PASS" if dsa_mfi_max < C.DSA_WEAK_THRESHOLD else "FAIL"
    # STRONG_POSITIVE or INDETERMINATE
    return "FAIL"


def travel_estimate_cents(donor_kind, segment_miles, lodging_nights):
    per_mile = Decimal(C.FLIGHT_CENTS_PER_MILE)
    if donor_kind == "ALTRUISTIC":
        flight_raw = per_mile * Decimal(str(C.ALTRUISTIC_MILEAGE_MULTIPLIER)) * Decimal(segment_miles)
        flight_cap = C.FLIGHT_CAP_CENTS_ALTRUISTIC
        lodging_cap = C.LODGING_CAP_CENTS_ALTRUISTIC
    else:
        flight_raw = per_mile * Decimal(segment_miles)
        flight_cap = C.FLIGHT_CAP_CENTS
        lodging_cap = C.LODGING_CAP_CENTS
    flight_component = int(
        flight_raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    flight_component = min(flight_cap, flight_component)
    lodging_component = min(lodging_cap, lodging_nights * C.LODGING_PER_NIGHT_CENTS)
    return flight_component + lodging_component + C.FLAT_FEE_CENTS


def cold_ischemia_hours(nephrectomy_completed_iso, actual_arrival_iso):
    delta = _parse(actual_arrival_iso) - _parse(nephrectomy_completed_iso)
    hours = Decimal(delta.total_seconds()) / Decimal(3600)
    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_completion_grade(chain):
    if chain["chain_state"] == "COMPLETED":
        return "FULL"
    if chain["chain_state"] == "BROKEN":
        if chain["length_actual"] >= chain["length_target"]:
            return "FULL"
        return "BROKEN_PARTIAL"
    return "PENDING"


def recompute_chain_completion(chain):
    chain["length_actual"] = sum(
        1
        for o in store.offers.values()
        if o["chain_id"] == chain["id"] and o["offer_state"] == "TRANSPLANT_COMPLETED"
    )
    if chain["chain_state"] == "EXECUTING" and chain["length_actual"] == chain["length_target"]:
        chain["chain_state"] = "COMPLETED"
    chain["completion_grade"] = compute_completion_grade(chain)


# ---------------------------------------------------------------------------
# Offer / deadline helpers
# ---------------------------------------------------------------------------

def apply_time_transitions():
    """Triggered whenever the logical clock moves (§2.7)."""
    now = store.now()
    for slot in store.slots.values():
        if slot["slot_state"] in ("OPEN", "RESERVED"):
            if _parse(slot["slot_end_utc"]) <= now:
                if slot["slot_state"] == "OPEN":
                    slot["slot_state"] = "EXPIRED"
                    store.touch(slot)
                elif slot["slot_state"] == "RESERVED":
                    ch = store.chains.get(slot.get("reserved_for_chain_id"))
                    if ch is None or ch["chain_state"] in ("LOCKED", "PROPOSED", "ACCEPTING"):
                        slot["slot_state"] = "EXPIRED"
                        store.touch(slot)
    for offer in store.offers.values():
        if offer["offer_state"] == "PENDING_CROSSMATCH":
            if _parse(offer["crossmatch_deadline_utc"]) <= now:
                _fail_offer(offer, "CHAIN_BREAK_PROPAGATION")
        elif offer["offer_state"] == "CROSSMATCH_PASSED":
            if _parse(offer["center_accept_deadline_utc"]) <= now:
                _fail_offer(offer, "CHAIN_BREAK_PROPAGATION")


def _fail_offer(offer, reason):
    offer["offer_state"] = "OFFER_FAILED"
    offer["offer_failure_reason"] = reason
    store.touch(offer)


# ---------------------------------------------------------------------------
# Chain break cascade (§3.8)
# ---------------------------------------------------------------------------

TERMINAL_OFFER_STATES = ("TRANSPLANT_COMPLETED", "OFFER_FAILED")


def _find_offer_for_donor_in_chain(donor_id):
    """Find the non-terminal offer whose donor is this donor, in an active chain."""
    candidates = []
    for o in store.offers.values():
        if o["donor_id"] != donor_id:
            continue
        ch = store.chains.get(o["chain_id"])
        if ch is None:
            continue
        if ch["chain_state"] in ("LOCKED", "SCHEDULED", "EXECUTING"):
            candidates.append(o)
    if not candidates:
        return None
    return sorted(candidates, key=lambda o: o["position_index"])[0]


def _mint_bridge_donor(broken_donor):
    rec = {
        "external_ref": "bridge-%s" % new_id()[:8],
        "home_center_id": broken_donor["home_center_id"],
        "abo_type": broken_donor["abo_type"],
        "hla_a": broken_donor["hla_a"],
        "hla_b": broken_donor["hla_b"],
        "hla_drb1": broken_donor["hla_drb1"],
        "kdri_score": broken_donor["kdri_score"],
        "age_at_registration": broken_donor["age_at_registration"],
        "donor_kind": "BRIDGE",
        "medical_status": "CLEARED",
        "surgery_state": "PRE_SURGERY",
        "chain_participation_state": "POOL",
        "protection_policy_id": None,
        "priority_waitlist_status": "NONE",
        "traveled_distance_miles": 0,
        "complications_recorded": 0,
    }
    return store.insert(store.donors, rec)


def create_chain_break(chain, broken_offer, trigger_kind):
    """Create a ChainBreakEvent and cascade immediately (RECORDED -> CASCADED)."""
    already_transplanted = sum(
        1
        for o in store.offers.values()
        if o["chain_id"] == chain["id"] and o["offer_state"] == "TRANSPLANT_COMPLETED"
    )

    broken_reason = "ORGAN_LOST_IN_TRANSIT" if trigger_kind == "ORGAN_LOST_IN_TRANSIT" else "DONOR_UNAVAILABLE"

    event = {
        "chain_id": chain["id"],
        "broken_at_offer_id": broken_offer["id"] if broken_offer else None,
        "trigger_kind": trigger_kind,
        "recipients_already_transplanted": already_transplanted,
        "downstream_recipients_orphaned": 0,
        "bridge_donor_id": None,
        "event_state": "RECORDED",
    }
    store.insert(store.chain_breaks, event)

    broken_at_index = broken_offer["position_index"] if broken_offer else 0

    # Fail the broken offer itself.
    if broken_offer is not None and broken_offer["offer_state"] not in TERMINAL_OFFER_STATES:
        _fail_offer(broken_offer, broken_reason)

    # Cascade downstream offers.
    orphaned = 0
    for o in chain_offers(chain["id"]):
        if broken_offer is not None and o["id"] == broken_offer["id"]:
            continue
        if o["position_index"] > broken_at_index and o["offer_state"] not in TERMINAL_OFFER_STATES:
            _fail_offer(o, "CHAIN_BREAK_PROPAGATION")
            recipient = store.recipients.get(o["recipient_id"])
            if recipient is not None and recipient["chain_participation_state"] == "COMMITTED":
                recipient["chain_participation_state"] = "ORPHANED"
                # If their paired donor already donated, grant priority boost.
                pair = _pair_for_recipient(recipient["id"])
                if pair is not None:
                    pd = store.donors.get(pair["donor_id"])
                    if pd is not None and pd["surgery_state"] == "NEPHRECTOMY_DONE":
                        recipient["priority_boost_active"] = True
                store.touch(recipient)
                orphaned += 1

    # Bridge-donor minting: broken donor's paired recipient already transplanted.
    if broken_offer is not None:
        broken_donor = store.donors.get(broken_offer["donor_id"])
        if broken_donor is not None:
            pair = _pair_for_donor(broken_donor["id"])
            if pair is not None:
                pr = store.recipients.get(pair["recipient_id"])
                if pr is not None and pr["medical_status"] == "TRANSPLANTED":
                    bridge = _mint_bridge_donor(broken_donor)
                    event["bridge_donor_id"] = bridge["id"]

    # Chain transitions to BROKEN.
    chain["broken_at_index"] = broken_at_index if broken_offer is not None else None
    chain["chain_state"] = "BROKEN"
    chain["completion_grade"] = compute_completion_grade(chain)
    store.touch(chain)

    # Release reserved slots of the chain.
    for slot in store.slots.values():
        if slot.get("reserved_for_chain_id") == chain["id"] and slot["slot_state"] == "RESERVED":
            slot["slot_state"] = "RELEASED"
            slot["reserved_for_chain_id"] = None
            slot["reserved_for_offer_id"] = None
            slot["simultaneous_group_id"] = None
            store.touch(slot)

    # Dissolve pairs that were locked into this chain.
    for o in chain_offers(chain["id"]):
        recipient = store.recipients.get(o["recipient_id"])
        if recipient is None:
            continue
        pair = _pair_for_recipient(recipient["id"])
        if pair is not None and pair["pair_state"] == "LOCKED":
            if pair["dissolution_reason"] == "NONE":
                pair["pair_state"] = "DISSOLVED"
                pair["dissolution_reason"] = "CHAIN_BROKEN"
                store.touch(pair)

    event["downstream_recipients_orphaned"] = orphaned
    event["event_state"] = "CASCADED"
    store.touch(event)
    recompute_all_active_chain_counts()
    return event


def _pair_for_donor(donor_id):
    for p in store.pairs.values():
        if p["donor_id"] == donor_id and p["pair_state"] not in ("DISSOLVED", "RELEASED"):
            return p
    # fall back to any pair record
    for p in store.pairs.values():
        if p["donor_id"] == donor_id:
            return p
    return None


def _pair_for_recipient(recipient_id):
    for p in store.pairs.values():
        if p["recipient_id"] == recipient_id and p["pair_state"] not in ("DISSOLVED", "RELEASED"):
            return p
    for p in store.pairs.values():
        if p["recipient_id"] == recipient_id:
            return p
    return None


# ---------------------------------------------------------------------------
# Chain construction (§3.3)
# ---------------------------------------------------------------------------

def run_chain_construction(run):
    """Execute the chain-construction algorithm; mints chains and offers."""
    pool_pairs = [p for p in store.pairs.values() if p["pair_state"] == "IN_POOL"]
    altruistic = [
        d
        for d in store.donors.values()
        if d["donor_kind"] == "ALTRUISTIC"
        and d["medical_status"] == "CLEARED"
        and d["chain_participation_state"] == "POOL"
    ]
    bridge = [
        d
        for d in store.donors.values()
        if d["donor_kind"] == "BRIDGE"
        and d["medical_status"] == "CLEARED"
        and d["chain_participation_state"] == "POOL"
    ]

    run["candidate_pool_size"] = len(pool_pairs)

    # Donor/recipient universes from pool pairs.
    pair_by_donor = {p["donor_id"]: p for p in pool_pairs}
    pair_by_recipient = {p["recipient_id"]: p for p in pool_pairs}
    donors = {p["donor_id"]: store.donors[p["donor_id"]] for p in pool_pairs if p["donor_id"] in store.donors}
    recipients = {
        p["recipient_id"]: store.recipients[p["recipient_id"]]
        for p in pool_pairs
        if p["recipient_id"] in store.recipients
    }
    for d in altruistic + bridge:
        donors[d["id"]] = d

    # Edge scoring: every (donor, recipient) from different pairs.
    edges = {}  # donor_id -> list of (score, listed_at, created_at, recipient_id)
    for d_id, donor in donors.items():
        for r_id, recipient in recipients.items():
            d_pair = pair_by_donor.get(d_id)
            r_pair = pair_by_recipient.get(r_id)
            if d_pair is not None and r_pair is not None and d_pair["id"] == r_pair["id"]:
                continue
            compat = abo_compatible(donor, recipient)
            hit = unacceptable_antigen_hit(donor, recipient)
            if not compat or hit:
                continue
            mismatch = hla_mismatch_count(donor, recipient)
            score = match_score_bps(donor, recipient, compat, hit, mismatch)
            if score <= 0:
                continue
            edges.setdefault(d_id, []).append(
                (score, recipient["listed_at_utc"], recipient["created_at"], r_id)
            )

    # Starters: altruistic by created_at asc, then bridge by created_at asc.
    starters = sorted(altruistic, key=lambda d: (d["created_at"], d["id"])) + sorted(
        bridge, key=lambda d: (d["created_at"], d["id"])
    )

    used_recipients = set()
    used_donors = set()
    proposed = []

    def best_edge(d_id):
        cands = [e for e in edges.get(d_id, []) if e[3] not in used_recipients]
        if not cands:
            return None
        cands.sort(key=lambda e: (-e[0], e[1], e[2]))
        return cands[0]

    for starter in starters:
        if starter["id"] in used_donors:
            continue
        # Build one chain greedily.
        chain_pairs = []  # list of (donor_id, recipient_id)
        current_donor = starter
        while len(chain_pairs) < C.MAX_CHAIN_LENGTH:
            edge = best_edge(current_donor["id"])
            if edge is None:
                break
            r_id = edge[3]
            chain_pairs.append((current_donor["id"], r_id))
            used_recipients.add(r_id)
            used_donors.add(current_donor["id"])
            r_pair = pair_by_recipient.get(r_id)
            if r_pair is None:
                break
            next_donor = store.donors.get(r_pair["donor_id"])
            if next_donor is None or next_donor["id"] in used_donors:
                break
            current_donor = next_donor
        if not chain_pairs:
            continue

        start_center = store.donors[starter["id"]]["home_center_id"]
        chain = {
            "chain_run_id": run["id"],
            "starter_donor_id": starter["id"],
            "chain_state": "PROPOSED",
            "length_target": len(chain_pairs),
            "length_actual": 0,
            "starts_at_center_id": start_center,
            "completion_grade": "PENDING",
            "scheduled_date": None,
            "broken_at_index": None,
        }
        store.insert(store.chains, chain)

        proposed_at = store.now_iso()
        proposed_dt = store.now()
        xm_deadline = iso_z(proposed_dt + timedelta(hours=C.CROSSMATCH_REVIEW_HOURS))
        ca_deadline = iso_z(proposed_dt + timedelta(hours=C.CENTER_ACCEPT_HOURS))

        for idx, (d_id, r_id) in enumerate(chain_pairs, start=1):
            donor = store.donors[d_id]
            recipient = store.recipients[r_id]
            compat = abo_compatible(donor, recipient)
            hit = unacceptable_antigen_hit(donor, recipient)
            mismatch = hla_mismatch_count(donor, recipient)
            score = match_score_bps(donor, recipient, compat, hit, mismatch)
            offer = {
                "chain_id": chain["id"],
                "position_index": idx,
                "donor_id": d_id,
                "recipient_id": r_id,
                "donor_center_id": donor["home_center_id"],
                "recipient_center_id": recipient["home_center_id"],
                "offer_state": "PENDING_CROSSMATCH",
                "match_score_bps": score,
                "abo_compatible": compat,
                "hla_mismatch_count": mismatch,
                "unacceptable_antigen_hit": hit,
                "proposed_at_utc": proposed_at,
                "accepted_at_utc": None,
                "crossmatch_deadline_utc": xm_deadline,
                "center_accept_deadline_utc": ca_deadline,
                "donor_travel_required": donor["home_center_id"] != recipient["home_center_id"],
                "offer_failure_reason": "NONE",
            }
            store.insert(store.offers, offer)
            r_pair = pair_by_recipient.get(r_id)
            if r_pair is not None and r_pair["pair_state"] == "IN_POOL":
                r_pair["pair_state"] = "IN_PROPOSED_CHAIN"
                store.touch(r_pair)
        proposed.append(chain)

    run["proposed_chain_count"] = len(proposed)
    return proposed
