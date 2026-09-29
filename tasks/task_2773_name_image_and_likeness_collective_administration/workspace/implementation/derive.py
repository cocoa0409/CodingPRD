"""Derived figures, ledger re-derivation, bubble-ups and cascades (PRD 2.10, 2.12)."""

import calc
import clock
import store

TERMINAL_LIFECYCLE = ("COMPLETED", "TERMINATED", "VOIDED")
COMMITTED_LIFECYCLE = ("DRAFT", "ACTIVE")
TERMINAL_DELIVERABLE = ("VERIFIED", "WAIVED", "FORFEITED")
OPEN_DELIVERABLE = ("PENDING", "SUBMITTED", "REJECTED")
DORMANT_COMMITMENT = ("PAUSED", "CANCELLED", "FULFILLED")


# --- row bookkeeping --------------------------------------------------------

def touch(row):
    row["updated_at"] = clock.now()


def bump(row):
    row["updated_at"] = clock.now()
    row["version"] = row["version"] + 1


# --- collection helpers -----------------------------------------------------

def donors_of_collective(collective_id):
    return store.ordered([d for d in store.donor_members.values()
                          if d["collective_id"] == collective_id])


def tiers_of_collective(collective_id):
    return store.ordered([t for t in store.membership_tiers.values()
                          if t["collective_id"] == collective_id])


def commitments_of_donor(donor_id):
    return store.ordered([c for c in store.commitments.values()
                          if c["donor_member_id"] == donor_id])


def contributions_of_donor(donor_id):
    return store.ordered([c for c in store.contributions.values()
                          if c["donor_member_id"] == donor_id])


def contributions_of_collective(collective_id):
    rows = []
    for c in store.contributions.values():
        donor = store.donor_members.get(c["donor_member_id"])
        if donor is not None and donor["collective_id"] == collective_id:
            rows.append(c)
    return store.ordered(rows)


def athletes_of_collective(collective_id):
    return store.ordered([a for a in store.athletes.values()
                          if a["collective_id"] == collective_id])


def contracts_of_collective(collective_id):
    return store.ordered([c for c in store.deal_contracts.values()
                          if c["collective_id"] == collective_id])


def contracts_of_athlete(athlete_id):
    return store.ordered([c for c in store.deal_contracts.values()
                          if c["athlete_id"] == athlete_id])


def deliverables_of_contract(contract_id):
    return store.ordered([d for d in store.deliverables.values()
                          if d["deal_contract_id"] == contract_id])


def releases_of_contract(contract_id):
    return store.ordered([r for r in store.payment_releases.values()
                          if r["deal_contract_id"] == contract_id])


def releases_of_collective(collective_id):
    rows = []
    for r in store.payment_releases.values():
        contract = store.deal_contracts.get(r["deal_contract_id"])
        if contract is not None and contract["collective_id"] == collective_id:
            rows.append(r)
    return store.ordered(rows)


def releases_of_athlete(athlete_id):
    rows = []
    for r in store.payment_releases.values():
        contract = store.deal_contracts.get(r["deal_contract_id"])
        if contract is not None and contract["athlete_id"] == athlete_id:
            rows.append(r)
    return store.ordered(rows)


# --- contract-level derived figures -----------------------------------------

def contract_released_total(contract):
    return sum(r["requested_amount_cents"] for r in releases_of_contract(contract["id"])
               if r["status"] == "RELEASED")


def contract_deliverable_value_total(contract):
    return sum(d["unit_value_cents"] for d in deliverables_of_contract(contract["id"])
               if d["status"] != "FORFEITED")


def deliverable_payout_eligible(deliverable, contract=None):
    if deliverable["status"] not in ("VERIFIED", "WAIVED"):
        return 0
    if contract is None:
        contract = store.deal_contracts.get(deliverable["deal_contract_id"])
    if contract is None:
        return 0
    if contract["deal_kind"] == "INDIVIDUAL":
        base = deliverable["unit_value_cents"]
    else:
        total = contract_deliverable_value_total(contract)
        base = 0 if total == 0 else calc.floor_div(
            contract["total_value_cents"] * deliverable["unit_value_cents"], total)
    return calc.payout_eligible(base, deliverable["late_flag"])


def deliverable_payout_basis(deliverable, contract=None):
    if contract is None:
        contract = store.deal_contracts.get(deliverable["deal_contract_id"])
    if contract is None:
        return None
    return "STRICT_UNIT_BASIS" if contract["deal_kind"] == "INDIVIDUAL" else "CONTRACT_SHARE_BASIS"


# --- collective ledger ------------------------------------------------------

def collective_settled_net(collective_id):
    """Sum of net_amount_cents over the collective's SETTLED contributions (PRD 2.10).

    A REFUNDED row has already left the SETTLED set, so it simply drops out of the
    sum: that is exactly what PRD 3.5 means when it says a refund "reduces the
    collective's settled_net_funds_cents by that row's net_amount_cents".
    """
    total = 0
    for c in contributions_of_collective(collective_id):
        if c["status"] == "SETTLED":
            total += c["net_amount_cents"]
    return total


def collective_released_total(collective_id):
    return sum(r["requested_amount_cents"] for r in releases_of_collective(collective_id)
               if r["status"] == "RELEASED")


def collective_reversed_total(collective_id):
    return sum(r["requested_amount_cents"] for r in releases_of_collective(collective_id)
               if r["status"] == "REVERSED")


def collective_committed_unreleased(collective_id):
    total = 0
    for contract in contracts_of_collective(collective_id):
        if contract["lifecycle_status"] in COMMITTED_LIFECYCLE:
            total += contract["total_value_cents"] - contract_released_total(contract)
    return max(0, total)


def sync_collective(collective):
    """Re-derive the four ledger figures and funding_posture, persisting both."""
    settled = collective_settled_net(collective["id"])
    released = collective_released_total(collective["id"])
    reversed_total = collective_reversed_total(collective["id"])
    committed = collective_committed_unreleased(collective["id"])
    posture = calc.funding_posture(settled, released, committed)
    changed = (
        collective["settled_net_funds_cents"] != settled
        or collective["released_total_cents"] != released
        or collective["reversed_total_cents"] != reversed_total
        or collective["committed_unreleased_cents"] != committed
        or collective["funding_posture"] != posture
    )
    collective["settled_net_funds_cents"] = settled
    collective["released_total_cents"] = released
    collective["reversed_total_cents"] = reversed_total
    collective["committed_unreleased_cents"] = committed
    collective["funding_posture"] = posture
    if changed:
        touch(collective)


def designated_pool(collective_id, designation):
    """Unreleased settled net funds carrying one designation."""
    settled = sum(c["net_amount_cents"] for c in contributions_of_collective(collective_id)
                  if c["status"] == "SETTLED" and c["designation"] == designation)
    drawn = 0
    for r in releases_of_collective(collective_id):
        if r["status"] != "RELEASED":
            continue
        contract = store.deal_contracts.get(r["deal_contract_id"])
        if contract is not None and contract["funding_designation"] == designation:
            drawn += r["requested_amount_cents"]
    return settled - drawn


def has_settled_designation(collective_id, designation):
    for c in contributions_of_collective(collective_id):
        if c["status"] == "SETTLED" and c["designation"] == designation:
            return True
    return False


# --- donor member -----------------------------------------------------------

def sync_donor_lifetime(donor):
    rows = [c for c in contributions_of_donor(donor["id"]) if c["status"] == "SETTLED"]
    settled = sum(c["net_amount_cents"] for c in rows)
    deductible = sum(c["deductible_amount_cents"] for c in rows)
    if donor["lifetime_settled_cents"] != settled or donor["lifetime_deductible_cents"] != deductible:
        donor["lifetime_settled_cents"] = settled
        donor["lifetime_deductible_cents"] = deductible
        touch(donor)


def activate_donor(donor):
    """A settled contribution moves PROSPECT or LAPSED to ACTIVE."""
    if donor["status"] in ("PROSPECT", "LAPSED"):
        donor["status"] = "ACTIVE"
        touch(donor)


def maybe_lapse_donor(donor):
    """ACTIVE -> LAPSED when the donor holds commitments and none of them is live."""
    if donor["status"] != "ACTIVE":
        return
    rows = commitments_of_donor(donor["id"])
    if not rows:
        return
    if all(c["status"] in DORMANT_COMMITMENT for c in rows):
        donor["status"] = "LAPSED"
        touch(donor)


def tier_active_commitment_count(tier):
    count = 0
    for donor in donors_of_collective(tier["collective_id"]):
        if donor["membership_tier_id"] != tier["id"]:
            continue
        for c in commitments_of_donor(donor["id"]):
            if c["status"] in ("ACTIVE", "PAST_DUE"):
                count += 1
    return count


# --- deductibility attribution ----------------------------------------------

def attribute_deductibility(donor, variant):
    """Allocate the donor's annual ceiling across their qualifying rows.

    Returns the signed sum of the per-row changes this pass produced.
    """
    collective = store.collectives.get(donor["collective_id"])
    year = clock.tax_year()
    rows = [c for c in contributions_of_donor(donor["id"])
            if c["status"] == "SETTLED" and clock.tax_year(c["received_at"]) == year]
    delta = 0
    if collective is None or not collective["charitable_deduction_enabled"]:
        for row in rows:
            if row["deductible_amount_cents"] != 0:
                delta -= row["deductible_amount_cents"]
                row["deductible_amount_cents"] = 0
                touch(row)
        return delta
    if variant == "YEAR_END_RECOMPUTE":
        walk = sorted(rows, key=lambda r: (r["received_at"], r["sequence_no"]))
    else:
        walk = sorted(rows, key=lambda r: r["sequence_no"])
    remaining = calc.deductible_ceiling(donor["annual_agi_cents"], donor["donor_kind"])
    for row in walk:
        assigned = min(row["net_amount_cents"], remaining)
        remaining -= assigned
        if row["deductible_amount_cents"] != assigned or row["deduction_variant"] != variant:
            delta += assigned - row["deductible_amount_cents"]
            row["deductible_amount_cents"] = assigned
            row["deduction_variant"] = variant
            touch(row)
    return delta


# --- athlete ----------------------------------------------------------------

def athlete_annual_committed(athlete_id):
    return sum(c["total_value_cents"] for c in contracts_of_athlete(athlete_id)
               if c["lifecycle_status"] in COMMITTED_LIFECYCLE)


def athlete_tax_year_figures(athlete_id):
    year = clock.tax_year()
    gross = 0
    withheld = 0
    for r in releases_of_athlete(athlete_id):
        if r["status"] != "RELEASED" or r["released_at"] is None:
            continue
        if clock.tax_year(r["released_at"]) != year:
            continue
        gross += r["requested_amount_cents"]
        withheld += r["withholding_amount_cents"]
    return gross, withheld


def athlete_tax_form_required(athlete):
    gross, _ = athlete_tax_year_figures(athlete["id"])
    return calc.tax_form_required(gross, athlete["tax_person_kind"])


# --- contract bubble-ups and cascades ---------------------------------------

def resync_payment_status(contract):
    """Recompute the payment dimension from the contract's released total."""
    if contract["payment_status"] == "CLAWBACK_DUE":
        return
    released = contract_released_total(contract)
    if released == 0:
        new_status = "UNPAID"
    elif released >= contract["total_value_cents"]:
        new_status = "FULLY_PAID"
    else:
        new_status = "PARTIALLY_PAID"
    if contract["payment_status"] != new_status:
        contract["payment_status"] = new_status
        touch(contract)


def maybe_complete_contract(contract):
    """ACTIVE -> COMPLETED once every deliverable is terminal and the money is in."""
    if contract["lifecycle_status"] != "ACTIVE":
        return
    if contract["payment_status"] != "FULLY_PAID":
        return
    rows = deliverables_of_contract(contract["id"])
    if not rows:
        return
    if not all(d["status"] in TERMINAL_DELIVERABLE for d in rows):
        return
    contract["lifecycle_status"] = "COMPLETED"
    touch(contract)
    collective = store.collectives.get(contract["collective_id"])
    if collective is not None:
        sync_collective(collective)


def forfeit_open_deliverables(contract):
    for deliverable in deliverables_of_contract(contract["id"]):
        if deliverable["status"] in OPEN_DELIVERABLE:
            deliverable["status"] = "FORFEITED"
            touch(deliverable)


def void_queued_releases(contract):
    for release in releases_of_contract(contract["id"]):
        if release["status"] == "QUEUED":
            release["status"] = "VOIDED"
            touch(release)


def terminate_contract(contract, reason):
    """DRAFT/ACTIVE -> TERMINATED with the forfeit, void and clawback cascade."""
    contract["lifecycle_status"] = "TERMINATED"
    contract["termination_reason"] = reason
    bump(contract)
    forfeit_open_deliverables(contract)
    void_queued_releases(contract)
    released = contract_released_total(contract)
    earned = 0
    for deliverable in deliverables_of_contract(contract["id"]):
        if deliverable["status"] in ("VERIFIED", "WAIVED"):
            earned += deliverable_payout_eligible(deliverable, contract)
    collective = store.collectives.get(contract["collective_id"])
    ruleset = collective["association_ruleset"] if collective is not None else "NCAA_2024"
    amount = calc.clawback_amount(released, earned, reason, ruleset)
    contract["clawback_amount_cents"] = amount
    if amount > 0:
        contract["payment_status"] = "CLAWBACK_DUE"
    if collective is not None:
        sync_collective(collective)


def void_contract(contract):
    """DRAFT -> VOIDED on the second disclosure return."""
    contract["lifecycle_status"] = "VOIDED"
    forfeit_open_deliverables(contract)
    void_queued_releases(contract)
    collective = store.collectives.get(contract["collective_id"])
    if collective is not None:
        sync_collective(collective)


def release_payment(release, contract, collective):
    """QUEUED -> RELEASED with all four release-time consequences."""
    release["status"] = "RELEASED"
    release["released_at"] = clock.now()
    touch(release)
    resync_payment_status(contract)
    if collective is not None:
        sync_collective(collective)
    maybe_complete_contract(contract)
