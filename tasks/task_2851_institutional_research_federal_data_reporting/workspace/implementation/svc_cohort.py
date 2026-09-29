"""CohortDefinition headcounts, the two rate variants and the exclusion cascade."""
from db import CASCADE_JUSTIFICATION, SYSTEM_ACTOR, store, touch
from svc_common import members_of, publications_of
from svc_pub import create_restatement, supersede_submitted
from util import D, num1


def recompute_cohort(cohort):
    """calculations.cohort_rate_variants. The caller owns the single version bump."""
    members = members_of(cohort["id"])
    initial = len(members)
    excluded = len([m for m in members if m["exclusion_status"] == "APPROVED"])
    adjusted = initial - excluded
    completers = len([m for m in members if m["outcome"] == "COMPLETED_150"])
    retained = len([m for m in members
                    if m["outcome"] in ("COMPLETED_150", "STILL_ENROLLED")])
    cohort["initial_count"] = initial
    cohort["exclusion_count"] = excluded
    cohort["adjusted_count"] = adjusted
    cohort["completers_count"] = completers
    cohort["retained_count"] = retained

    if cohort["cohort_type"] == "GRAD_RATE_150":
        fed_num = len([m for m in members
                       if m["exclusion_status"] != "APPROVED"
                       and m["outcome"] == "COMPLETED_150"])
        rank_num = completers
    else:
        fed_num = len([m for m in members
                       if m["exclusion_status"] != "APPROVED"
                       and m["outcome"] in ("COMPLETED_150", "STILL_ENROLLED")])
        rank_num = retained

    cohort["federal_rate_pct"] = None if adjusted == 0 else \
        num1(D(fed_num) / D(adjusted) * D(100))
    cohort["ranking_rate_pct"] = None if initial == 0 else \
        num1(D(rank_num) / D(initial) * D(100))


def rate_divergence_pp(cohort):
    """Difference of the two ALREADY-ROUNDED variants (PRD 3.6)."""
    federal = cohort.get("federal_rate_pct")
    ranking = cohort.get("ranking_rate_pct")
    if federal is None or ranking is None:
        return None
    return num1(D(federal) - D(ranking))


def matching_publications(cohort):
    """PUBLISHED figures bound to this cohort by metric key and cycle, created_at ASC."""
    matches = []
    for component in store.components.values():
        if component["cycle_id"] != cohort["cycle_id"]:
            continue
        for pub in publications_of(component["id"]):
            if pub["metric_key"] != cohort["publication_metric_key"]:
                continue
            if pub["publication_status"] != "PUBLISHED":
                continue
            matches.append(pub)
    matches.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    return matches


def cascade_exclusion_decision(cohort):
    """L3/L4 of PRD 2.7 rule 3 — LOCKED cohorts only."""
    if cohort["status"] != "LOCKED":
        return
    for pub in matching_publications(cohort):
        pub["publication_status"] = "RESTATEMENT_PENDING"
        touch(pub)
        supersede_submitted(pub)
        create_restatement(pub, cohort.get("federal_rate_pct"), CASCADE_JUSTIFICATION,
                           SYSTEM_ACTOR, "CASCADE")
