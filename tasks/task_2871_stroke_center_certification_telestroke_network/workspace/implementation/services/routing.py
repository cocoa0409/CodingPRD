"""The telestroke routing selector (PRD 3.3).

A candidate's ``id`` value is never consulted for any purpose.
"""
import db
from constants import NEUROLOGIST_COOLDOWN_MIN


def _has_matching_grant(agreement, neurologist_id, requested_scope, now):
    for grant in agreement["proxy_credentials"]:
        if grant["neurologist_id"] != neurologist_id:
            continue
        if grant["status"] != "GRANTED":
            continue
        expires_at = db.parse_iso(grant["expires_at"])
        if expires_at is None or not expires_at > now:
            continue
        if (grant["privilege_scope"] == requested_scope
                or grant["privilege_scope"] == "CONSULT_AND_THROMBOLYSIS"):
            return True
    return False


def candidates(consult, agreement, case):
    center = db.get("centers", case["center_id"])
    now = db.now_dt()
    pool = []
    for neurologist in db.all_of("neurologists"):
        if neurologist["home_center_id"] != agreement["hub_center_id"]:
            continue
        if neurologist["on_call_state"] != "ON_CALL":
            continue
        if neurologist["active_consult_count"] >= neurologist["concurrent_consult_limit"]:
            continue
        if center is None or center["state_code"] not in neurologist["licensed_state_codes"]:
            continue
        if not _has_matching_grant(agreement, neurologist["id"],
                                   consult["requested_privilege_scope"], now):
            continue
        if neurologist["id"] in consult["excluded_neurologist_ids"]:
            continue
        if (not neurologist["board_certified"]
                and agreement["coverage_tier"] != "TIER_2_CONSULT_ONLY"):
            continue
        last_completed = neurologist["last_consult_completed_at"]
        if last_completed is not None:
            elapsed = db.floor_minutes(db.parse_iso(last_completed), now)
            if elapsed < NEUROLOGIST_COOLDOWN_MIN:
                continue
        pool.append(neurologist)
    return pool


def select(consult, agreement, case):
    pool = candidates(consult, agreement, case)
    if not pool:
        return None
    pool.sort(key=lambda n: (n["roster_rank"], n["active_consult_count"],
                             n["completed_consult_count"], n["created_at"], n["_seq"]))
    return pool[0]
