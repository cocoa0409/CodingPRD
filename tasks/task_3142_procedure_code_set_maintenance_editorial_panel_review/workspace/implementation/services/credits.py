"""CEA credit award and the sponsoring society's derived balance.

PRD.md 3.5 (final paragraph) and SCAFFOLD.yaml `cea_credit_award` /
`sponsoring_society_credit_balance`:

    determination != APPROVED                  -> 0 credits
    determination == APPROVED                  -> 2.0 base
                                                  + 0.5 when organ_system_count == 1
                                                  + 0.5 when 0 < procedure_volume_threshold <= 10000
                                                  + 1.0 when clinical_evidence_tier == TIER_I
    stored rounded half up to 2 decimal places.

The society balance sums `cea_credits` across every change naming that society
whose determination is APPROVED; every other determination contributes 0, and a
change with no sponsoring society contributes to no society at all.
"""

import store
from money import Decimal, as_float, dec, round_half_up

BASE_CREDITS = dec("2.0")
ORGAN_SYSTEM_CREDITS = dec("0.5")
VOLUME_CREDITS = dec("0.5")
TIER_I_CREDITS = dec("1.0")
VOLUME_THRESHOLD_LOW = 10000
ORGAN_SYSTEM_SINGLE = 1


def cea_credit_award(change):
    """Recompute and store `cea_credits` on a change; return the value."""
    if change.get("determination") != "APPROVED":
        change["cea_credits"] = 0.0
        return change["cea_credits"]

    credits = BASE_CREDITS
    if _integer(change.get("organ_system_count")) == ORGAN_SYSTEM_SINGLE:
        credits = credits + ORGAN_SYSTEM_CREDITS
    volume = _integer(change.get("procedure_volume_threshold"))
    if volume is not None and 0 < volume <= VOLUME_THRESHOLD_LOW:
        credits = credits + VOLUME_CREDITS
    if change.get("clinical_evidence_tier") == "TIER_I":
        credits = credits + TIER_I_CREDITS
    change["cea_credits"] = as_float(round_half_up(credits, 2))
    return change["cea_credits"]


def _integer(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sponsoring_society_credit_balance(society_id):
    """Recompute the society's derived balance across its approved changes."""
    if society_id is None:
        return None
    society = store.societies.get(society_id)
    if society is None:
        return None
    total = Decimal("0")
    for change in store.code_changes.values():
        if change.get("society_id") != society_id:
            continue
        if change.get("determination") != "APPROVED":
            continue
        total = total + dec(change.get("cea_credits"))
    society["cea_credit_balance"] = as_float(round_half_up(total, 2))
    return society["cea_credit_balance"]


def recompute_for_change(change):
    """The cascade hop that every determination change performs: recompute the
    change's own credits and, when a society is named, that society's balance."""
    cea_credit_award(change)
    if change.get("society_id") is not None:
        sponsoring_society_credit_balance(change["society_id"])
    return change