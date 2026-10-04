"""Logical clock setting and the pinned epoch pass (calculations.epoch_pass_ordering).

Pinned order on every clock set:
  1. Effectuate APPROVED RuleProposals with effective_at <= now, ordered by
     effective_at ASC then created_at ASC; each effectuation runs the
     supersession cascade (target EFFECTIVE -> SUPERSEDED; OPEN/REFERRED
     referrals citing the target's rule_code get needs_rule_review = true).
  2. MunicipalProfessional CE transitions (QUALIFIED -> CE_DUE at ce_cycle_end;
     CE_DUE -> LAPSED at ce_grace_end), ordered by ce_cycle_end ASC then
     created_at ASC.
  3. Per-Organization late tally + posture recompute, organizations ordered by
     created_at ASC, applying the CLEAR -> WATCH PENDING-subscription rejection
     cascade.
"""
import store
import services
from errors import ApiError, ERR_CLOCK_REGRESSION


def set_clock(to_dt):
    """Advance the monotonic logical clock and run the epoch pass.

    Returns the number of state changes the pass applied (epoch_effects).
    A strictly backwards move is rejected; an equal instant is allowed.
    """
    current = store.now()
    if to_dt < current:
        raise ApiError(
            ERR_CLOCK_REGRESSION,
            "The logical clock is monotonic; to_iso8601 must be >= the current logical time.",
            422,
        )
    store.set_now(to_dt)
    return _epoch_pass(to_dt)


def _epoch_pass(now):
    effects = 0

    # 1. Rule proposal effectuation (+ supersession cascade).
    due = [
        p
        for p in store.rule_proposals.values()
        if p["status"] == "APPROVED"
        and p["effective_at"] is not None
        and p["effective_at"] <= now
    ]
    due.sort(key=lambda p: (p["effective_at"], p["created_at"]))
    for proposal in due:
        proposal["status"] = "EFFECTIVE"
        services.bump(proposal)
        effects += 1
        target_id = proposal["supersedes_proposal_id"]
        if target_id:
            target = store.rule_proposals.get(target_id)
            if target is not None and target["status"] == "EFFECTIVE":
                target["status"] = "SUPERSEDED"
                services.bump(target)
                effects += 1
                for ref in store.enforcement_referrals.values():
                    if (
                        ref["rule_code"] == target["rule_code"]
                        and ref["status"] in ("OPEN", "REFERRED")
                        and not ref["needs_rule_review"]
                    ):
                        ref["needs_rule_review"] = True
                        services.bump(ref)
                        effects += 1

    # 2. Municipal professional CE transitions.
    candidates = [
        m
        for m in store.professionals.values()
        if m["qualification_status"] in ("QUALIFIED", "CE_DUE")
    ]
    candidates.sort(key=lambda m: (m["ce_cycle_end"], m["created_at"]))
    for prof in candidates:
        while True:
            if (
                prof["qualification_status"] == "QUALIFIED"
                and prof["ce_cycle_end"] is not None
                and now >= prof["ce_cycle_end"]
            ):
                prof["qualification_status"] = "CE_DUE"
                services.recompute_may_transact(prof)
                services.bump(prof)
                effects += 1
                continue
            if (
                prof["qualification_status"] == "CE_DUE"
                and prof["ce_grace_end"] is not None
                and now >= prof["ce_grace_end"]
            ):
                prof["qualification_status"] = "LAPSED"
                prof["_lapsed_at"] = now
                services.recompute_may_transact(prof)
                services.bump(prof)
                effects += 1
                continue
            break

    # 3. Per-organization late tally + posture recompute.
    for org in sorted(store.organizations.values(), key=lambda o: o["created_at"]):
        effects += services.recompute_posture(org)

    return effects
