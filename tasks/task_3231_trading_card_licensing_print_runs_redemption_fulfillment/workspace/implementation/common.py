"""Cross-entity helpers: licensing authority, aggregate recomputes, compound
print-run state derivation, and serialization to the wire shape.
"""

from constants import fmt_dt
import db


# ---------------------------------------------------------------------------
# Licensing authority (PRD 2.7 / SCAFFOLD state-machine semantics)
# ---------------------------------------------------------------------------

def license_in_force(license_rec, now):
    """Three things hold together: status == ACTIVE as of the logical clock,
    the clock has reached or passed term_starts_on, and the clock has not
    passed term_ends_on."""
    if license_rec is None:
        return False
    if license_rec["status"] != "ACTIVE":
        return False
    if now < license_rec["term_starts_on"]:
        return False
    if now > license_rec["term_ends_on"]:
        return False
    return True


def license_of_product_line(store, product_line):
    return store.get("licenses", product_line["license_id"])


def record_license_status(license_rec, status, now):
    """Append a status transition to the license's internal history.

    The history backs the continuous-activeness test of PRD 2.7: a license that
    was suspended at any point inside [artwork.submitted_on, now], and later
    reactivated, must fail the card-set approval window test even though it is
    in force at the moment of approval.
    """
    log = license_rec.setdefault("_status_log", [])
    log.append((now, status))


def license_status_at(license_rec, instant):
    """The license's status as of `instant`, read from its history."""
    status = None
    for at, value in license_rec.get("_status_log", []):
        if at <= instant:
            status = value
        else:
            break
    if status is None:
        status = license_rec.get("status", "DRAFT")
    return status


def license_active_across(license_rec, start, now):
    """True when the license was continuously ACTIVE across [start, now]."""
    if license_rec is None:
        return False
    if license_status_at(license_rec, start) != "ACTIVE":
        return False
    for at, value in license_rec.get("_status_log", []):
        if start < at <= now and value != "ACTIVE":
            return False
    return True


def license_of_card_set(store, card_set):
    line = store.get("product_lines", card_set["product_line_id"])
    if line is None:
        return None
    return store.get("licenses", line["license_id"])


# ---------------------------------------------------------------------------
# Aggregate recomputes.  These are field writes (they refresh updated_at) but
# they do NOT bump the version of the entity the aggregate describes.
# ---------------------------------------------------------------------------

def recompute_license_counts(store, license_id, now):
    if license_id is None:
        return
    lic = store.get("licenses", license_id)
    if lic is None:
        return
    line_ids = {
        p["id"] for p in store.all("product_lines") if p["license_id"] == license_id
    }
    set_count = 0
    approved = 0
    for s in store.all("card_sets"):
        if s["product_line_id"] in line_ids:
            set_count += 1
            if s["status"] == "APPROVED":
                approved += 1
    lic["set_count"] = set_count
    lic["approved_set_count"] = approved
    db.touch(lic, now)


def recompute_license_counts_for_line(store, product_line, now):
    if product_line is not None:
        recompute_license_counts(store, product_line["license_id"], now)


def sets_under_line(store, product_line_id):
    return [s for s in store.all("card_sets") if s["product_line_id"] == product_line_id]


def autograph_secured_count(store, card_set_id):
    """Sum of QuantityDelivered across all SigningSession.allocation_lines whose
    player_id is a player associated with this set.

    A set's associated players are the player_ids named by any allocation line
    that points at this card set; the delivered tally for a line counts once the
    stock has moved (prepared, shipped, completed)."""
    total = 0
    for session in store.all("signing_sessions"):
        if session["status"] in ("SCHEDULED", "CANCELLED"):
            continue
        for line in session["allocation_lines"]:
            if line["card_set_id"] == card_set_id:
                total += line["quantity_delivered"]
    return total


def quantity_produced(store, card_set_id, player_id):
    """QuantityProduced(card_set_id, player_id): the number of that player's
    cards actually produced against that card set as of the logical clock.

    A signing session's allocation line is the platform's record of which
    player's cards are drawn from which set; a line whose stock has been
    prepared or shipped counts as produced."""
    produced = 0
    for session in store.all("signing_sessions"):
        if session["status"] in ("SCHEDULED", "CANCELLED"):
            continue
        for line in session["allocation_lines"]:
            if line["card_set_id"] == card_set_id and line["player_id"] == player_id:
                produced += line["quantity_delivered"]
    return produced


def autograph_redemptions_outstanding(store, card_set_id):
    """Count of Redemption records for this set whose status is ISSUED or
    FULFILLED."""
    return sum(
        1
        for r in store.all("redemptions")
        if r["card_set_id"] == card_set_id and r["status"] in ("ISSUED", "FULFILLED")
    )


def quality_claim_count(store, card_set_id):
    return sum(
        1 for q in store.all("quality_claims") if q["card_set_id"] == card_set_id
    )


def settled_complaint_count(store, card_set_id):
    """Count of CollectorComplaint records for this set whose status is
    APPROVED (the counter tracks approved complaints despite its name)."""
    return sum(
        1
        for c in store.all("collector_complaints")
        if c["card_set_id"] == card_set_id and c["status"] == "APPROVED"
    )


def collector_notification_count(store, redemption_id):
    return sum(
        1
        for n in store.all("collector_notifications")
        if n["redemption_id"] == redemption_id
    )


def recompute_card_set_aggregates(store, card_set, now):
    """Refresh every aggregate on a card set.  A count refresh is a field write
    but is NOT a mutation of the set, so it does not bump version (PRD 2.5)."""
    if card_set is None:
        return
    card_set["autograph_secured_count"] = autograph_secured_count(store, card_set["id"])
    card_set["autograph_redemptions_outstanding"] = autograph_redemptions_outstanding(
        store, card_set["id"]
    )
    card_set["quality_claim_count"] = quality_claim_count(store, card_set["id"])
    card_set["settled_complaint_count"] = settled_complaint_count(store, card_set["id"])
    db.touch(card_set, now)


def recompute_redemption_aggregates(store, redemption, now):
    if redemption is None:
        return
    redemption["collector_notification_count"] = collector_notification_count(
        store, redemption["id"]
    )
    db.touch(redemption, now)


def recompute_sets_per_case(store, product_line, now):
    if product_line is None:
        return
    product_line["sets_per_case"] = (
        product_line["boxes_per_case"]
        * product_line["packs_per_box"]
        * product_line["cards_per_pack"]
    )
    db.touch(product_line, now)


def recompute_allocated_cards(store, product_line, now):
    """The per-set-then-sum tier-snapped card total (tier_snap_aggregate)."""
    import calc

    if product_line is None:
        return
    product_line["allocated_cards"] = calc.tier_snap_aggregate(store, product_line["id"])
    db.touch(product_line, now)


# ---------------------------------------------------------------------------
# Compound print-run status (PRD 2.12)
# ---------------------------------------------------------------------------

def frozen_decision(store, card_set_id):
    """The PrintRunDecision currently frozen for this set, if any."""
    for d in store.all("print_run_decisions"):
        if d["card_set_id"] == card_set_id and d["status"] == "APPROVED":
            return d
    return None


def derive_print_run_status(store, card_set):
    """UNDECIDED while no decision is frozen; LOCKED once one is; then
    DISCLOSED or UNDISCLOSED according to whether the frozen decision
    announced its quantity.

    The observable field therefore reads DISCLOSED or UNDISCLOSED once a
    decision is frozen -- LOCKED is the intermediate label the scaffold names
    for "a decision has been frozen".  `print_run_locked` below is the predicate
    the lock preconditions test against, so a frozen run satisfies them whether
    it is described as LOCKED, DISCLOSED or UNDISCLOSED.
    """
    decision = frozen_decision(store, card_set["id"])
    if decision is None:
        return "UNDECIDED"
    return "DISCLOSED" if decision["announced"] else "UNDISCLOSED"


def print_run_locked(store, card_set):
    """True when the set's print run is frozen.

    PRD 3.2 / 3.3 make production depend on the set's print run being "locked",
    and the scaffold expresses that as print_run_status == LOCKED.  Since a
    frozen run derives to DISCLOSED or UNDISCLOSED (PRD 2.12), the precondition
    is satisfied by any state other than UNDECIDED, i.e. by the existence of an
    APPROVED decision.  Requiring the literal LOCKED would make production
    unreachable.
    """
    return frozen_decision(store, card_set["id"]) is not None


def refresh_print_run_status(store, card_set, now):
    card_set["print_run_status"] = derive_print_run_status(store, card_set)
    db.touch(card_set, now)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

_DT_FIELDS = {
    "licenses": ("term_starts_on", "term_ends_on"),
    "product_lines": ("run_planned_on",),
    "card_sets": (),
    "pack_configurations": (),
    "signing_sessions": ("scheduled_on", "ship_date"),
    "artwork_approvals": ("submitted_on", "decided_on"),
    "print_run_decisions": ("proposed_on",),
    "redemptions": ("opened_on",),
    "collector_notifications": ("opened_on",),
    "distribution_allocations": (),
    "quality_claims": ("filed_on",),
    "collector_complaints": ("filed_on",),
}

_COMMON = ("created_at", "updated_at")


def serialize(collection, rec):
    """Render a record for the wire: datetimes to ISO-8601 UTC with three
    fractional digits, allocation lines passed through, no internal keys."""
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if value is None:
            out[key] = None
        elif key in _COMMON or key in _DT_FIELDS.get(collection, ()):
            out[key] = fmt_dt(value)
        else:
            out[key] = value
    return out