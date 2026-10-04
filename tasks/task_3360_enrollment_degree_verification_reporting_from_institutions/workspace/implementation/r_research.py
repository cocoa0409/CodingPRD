"""Aggregate research data services (PRD §3.9): request + generate with the
pinned computation order (opt-out exclusion -> k-anonymity gate -> completers
-> census-variant exclusion -> both rates).
"""
from datetime import timedelta

from flask import Blueprint

import calc
import db
from auth import ROLE_ANALYST, ROLE_CLEARINGHOUSE_OPS, authenticate, require_role
from core import (
    ERR_COHORT_TOO_SMALL,
    ERR_DATASET_NOT_FOUND,
    ERR_INSTITUTION_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_VALIDATION,
    get_body,
    ok_object,
    raise_err,
    req_date,
    req_str,
)

bp = Blueprint("research", __name__)


@bp.route("/research-datasets", methods=["POST"])
def create_dataset():
    caller = authenticate()
    require_role(caller, ROLE_ANALYST)
    data = get_body()
    scope_id = req_str(data, "scope_institution_id")
    cohort_start = req_date(data, "cohort_term_start")
    cohort_end = req_date(data, "cohort_term_end")
    if db.store.institutions.get(scope_id) is None:
        raise_err(ERR_INSTITUTION_NOT_FOUND, "institution not found")
    if cohort_end < cohort_start:
        raise_err(ERR_VALIDATION, "cohort_term_end must not precede cohort_term_start")
    ds = db.new_entity(
        {
            "scope_institution_id": scope_id,
            "created_by_analyst_id": caller.user_id,
            "cohort_term_start": cohort_start,
            "cohort_term_end": cohort_end,
            "status": "REQUESTED",
            "cohort_size": None,
            "completer_count": None,
            "adjusted_cohort_size": None,
            "completion_rate_census": None,
            "completion_rate_adjusted": None,
            "generated_at": None,
        }
    )
    db.store.datasets[ds["id"]] = ds
    return ok_object(db.serialize(ds), 201)


@bp.route("/research-datasets/<did>/generate", methods=["POST"])
def generate_dataset(did):
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS)
    ds = db.store.datasets.get(did)
    if ds is None:
        raise_err(ERR_DATASET_NOT_FOUND, "research dataset not found")
    if ds["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, "only a REQUESTED dataset can be generated")

    now = db.now()
    scope = ds["scope_institution_id"]
    start = ds["cohort_term_start"]
    end = ds["cohort_term_end"]

    # Cohort: distinct students with an ACCEPTED (non-SUPERSEDED) entry at the
    # scope institution whose term_start is in the window (boundaries inclusive).
    entries = [
        e
        for e in db.store.entries.values()
        if e["institution_id"] == scope
        and e["entry_status"] == "ACCEPTED"
        and start <= e["term_start"] <= end
    ]
    member_ids = []
    seen = set()
    for e in db.sorted_created(entries):
        if e["student_id"] not in seen:
            seen.add(e["student_id"])
            member_ids.append(e["student_id"])

    # Minus students with a RESEARCH_OPT_OUT in effect at generation time.
    members = [
        sid
        for sid in member_ids
        if not calc.has_active_directive(sid, "RESEARCH_OPT_OUT", now)
    ]
    cohort_size = len(members)

    # k-anonymity gate.
    if cohort_size < calc.K_ANONYMITY_MIN:
        raise_err(ERR_COHORT_TOO_SMALL, "cohort after opt-out exclusion is below K_ANONYMITY_MIN(10)")

    # Completers: SEALED degree at the scope institution, conferred within
    # [cohort_term_start, cohort_term_end + COMPLETION_LAG_DAYS] inclusive.
    lag_end = end + timedelta(days=calc.COMPLETION_LAG_DAYS)
    member_set = set(members)
    completer_count = 0
    for sid in members:
        if any(
            d["student_id"] == sid
            and d["institution_id"] == scope
            and d["status"] == "SEALED"
            and start <= d["conferred_on"] <= lag_end
            for d in db.store.degrees.values()
        ):
            completer_count += 1

    # Adjusted denominator: drop members whose latest in-window entry's
    # census_status_code is WITHDRAWN.
    withdrawn = 0
    for sid in members:
        own = [e for e in entries if e["student_id"] == sid]
        own.sort(key=lambda e: (e["term_start"], e["_seq"]))
        if own and own[-1]["census_status_code"] == "WITHDRAWN":
            withdrawn += 1
    adjusted_cohort_size = cohort_size - withdrawn

    ds["cohort_size"] = cohort_size
    ds["completer_count"] = completer_count
    ds["adjusted_cohort_size"] = adjusted_cohort_size
    # Identical numerator in both variants; 4 decimals, round_half_up.
    ds["completion_rate_census"] = calc.round4(completer_count, cohort_size)
    ds["completion_rate_adjusted"] = calc.round4(completer_count, adjusted_cohort_size)
    ds["generated_at"] = now
    ds["status"] = "GENERATED"
    db.touch(ds)
    return ok_object(db.serialize(ds))
