"""Panel selection, assignment unwinding and capacity accounting (PRD 3.7)."""
from store import db, sorted_records, touch


def assignments_of(claim_id):
    return sorted_records(
        [a for a in db.counsel_assignments.values() if a["claim_id"] == claim_id]
    )


def assignments_of_firm(firm_id):
    return sorted_records(
        [a for a in db.counsel_assignments.values() if a["counsel_firm_id"] == firm_id]
    )


def live_assignment(claim_id):
    for assignment in assignments_of(claim_id):
        if assignment["assignment_status"] == "ASSIGNED":
            return assignment
    return None


def eligible_pool(claim):
    """Firms that pass every eligibility gate, ranked by the pinned sort."""
    pool = []
    for firm in sorted_records(list(db.counsel_firms.values())):
        if firm["panel_status"] != "ACTIVE":
            continue
        if claim["venue_code"] not in firm["admitted_venue_codes"]:
            continue
        if claim["allegation_category"] not in firm["allegation_specialties"]:
            continue
        if claim["insured_id"] in firm["conflict_insured_ids"]:
            continue
        if firm["open_assignment_count"] >= firm["max_concurrent_assignments"]:
            continue
        if firm["id"] in claim["excluded_counsel_firm_ids"]:
            continue
        pool.append(firm)
    ranked = sorted(
        pool,
        key=lambda f: (
            -int(f["quality_score"]),
            f["blended_hourly_rate"],
            f["created_at"],
            f["_seq"],
        ),
    )
    return ranked


def release_capacity(firm):
    firm["open_assignment_count"] = max(0, int(firm["open_assignment_count"]) - 1)
    touch(firm)


def exclude_firm_from_claim(claim, firm_id):
    if firm_id not in claim["excluded_counsel_firm_ids"]:
        claim["excluded_counsel_firm_ids"] = list(claim["excluded_counsel_firm_ids"]) + [
            firm_id
        ]


def unwind_removed_firm(firm):
    """Panel removal replaces every live assignment the firm holds."""
    stamp = db.logical_now()
    for assignment in assignments_of_firm(firm["id"]):
        if assignment["assignment_status"] != "ASSIGNED":
            continue
        assignment["assignment_status"] = "REPLACED"
        assignment["closed_at"] = stamp
        touch(assignment)
        release_capacity(firm)
        claim = db.claims.get(assignment["claim_id"])
        if claim is not None:
            exclude_firm_from_claim(claim, firm["id"])
            claim["counsel_reassignment_required"] = True
            touch(claim)


def close_assignments_on_resolution(claim):
    stamp = db.logical_now()
    for assignment in assignments_of(claim["id"]):
        if assignment["assignment_status"] != "ASSIGNED":
            continue
        assignment["assignment_status"] = "CLOSED"
        assignment["closed_at"] = stamp
        touch(assignment)
        firm = db.counsel_firms.get(assignment["counsel_firm_id"])
        if firm is not None:
            release_capacity(firm)
