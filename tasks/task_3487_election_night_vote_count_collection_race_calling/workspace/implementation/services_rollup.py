"""tabulation_rollup + outstanding_vote_estimate + county computed fields
(SCAFFOLD §1.3 / PRD §3.5). Only ACCEPTED reports ever enter the rollup."""
from clock import now as clock_now
from store import db
from util import round6


def linked_county_ids(contest_id):
    return [l["county_id"] for l in db["links"].values() if l["contest_id"] == contest_id]


def linked_counties(contest_id):
    out = []
    for cid in linked_county_ids(contest_id):
        c = db["counties"].get(cid)
        if c is not None:
            out.append(c)
    return out


def latest_accepted_per_county(contest_id):
    """Latest ACCEPTED report per linked county: greatest accepted_at, then
    greatest created_at, then insertion order (never id)."""
    latest = {}
    for r in db["reports"].values():
        if r["contest_id"] != contest_id or r["status"] != "ACCEPTED":
            continue
        k = r["county_id"]
        cur = latest.get(k)
        key = (r["accepted_at"], r["created_at"], r["_seq"])
        if cur is None or key > (cur["accepted_at"], cur["created_at"], cur["_seq"]):
            latest[k] = r
    return latest


def candidate_ranking(contest_id, totals):
    """Candidates of the contest ranked by total DESC, tie-break
    Candidate.created_at ASC (insertion order breaks remaining ties)."""
    cands = [c for c in db["candidates"].values() if c["contest_id"] == contest_id]
    cands.sort(key=lambda c: (-totals.get(c["id"], 0), c["created_at"], c["_seq"]))
    return cands


def compute_rollup(contest):
    """Full rollup for a contest record. Returns a dict of derived values."""
    cid = contest["id"]
    counties = linked_counties(cid)
    latest = latest_accepted_per_county(cid)

    totals = {}
    reported_precincts = 0
    for k, rep in latest.items():
        reported_precincts += rep["precincts_reporting"]
        for entry in rep["candidate_votes"]:
            cand = entry.get("candidate_id")
            totals[cand] = totals.get(cand, 0) + int(entry.get("votes", 0))

    total_votes = sum(totals.values())
    ranked = candidate_ranking(cid, totals)
    with_votes = [c for c in ranked if totals.get(c["id"], 0) > 0]
    if len(with_votes) >= 2:
        top = totals.get(ranked[0]["id"], 0)
        second = totals.get(ranked[1]["id"], 0)
        margin_pct = round6(top - second, max(total_votes, 1))
    else:
        margin_pct = 0.0

    all_complete = bool(counties) and all(
        (c["id"] in latest
         and latest[c["id"]]["precincts_reporting"] == c["expected_precincts"])
        for c in counties
    )

    outstanding, detail = compute_outstanding(contest, counties, latest, totals)

    return {
        "reported_precincts": reported_precincts,
        "total_votes": total_votes,
        "margin_pct": margin_pct,
        "candidate_totals": [(c, totals.get(c["id"], 0)) for c in ranked],
        "all_complete": all_complete,
        "outstanding_estimate": outstanding,
        "outstanding_detail": detail,
        "latest": latest,
    }


def compute_outstanding(contest, counties, latest, totals_by_candidate=None):
    """outstanding_vote_estimate: per linked county max(historical, survey),
    summed (PRD §3.5)."""
    total = 0
    detail = []
    for c in counties:
        rep = latest.get(c["id"])
        precincts_reported = rep["precincts_reporting"] if rep else 0
        votes_reported = rep["reported_total"] if rep else 0
        remaining = c["expected_precincts"] - precincts_reported
        if remaining < 0:
            remaining = 0
        historical = (c["expected_vote_total"] * remaining) // c["expected_precincts"]
        if c["survey_turnout_estimate"] is not None:
            survey = max(c["survey_turnout_estimate"] - votes_reported, 0)
        else:
            survey = historical
        outstanding = max(historical, survey)
        total += outstanding
        detail.append({
            "county_id": c["id"],
            "precincts_reported": precincts_reported,
            "votes_reported": votes_reported,
            "historical_estimate": historical,
            "survey_estimate": survey,
            "outstanding_estimate": outstanding,
        })
    detail.sort(key=lambda d: d["county_id"])
    return total, detail


def refresh_contest(contest, bump=False):
    """Recompute the contest's computed fields. tabulation_status moves
    between REPORTING and COMPLETE only on the event-driven recomputes
    (VoteReport ACCEPT/VOID — exactly the calls with bump=True, which are
    also the version-advancing writes of PRD §2.7). Read-time recomputes
    refresh the numeric rollup but never move the state dimension: the
    CERTIFICATION -> TABULATION recount reopen sets REPORTING deliberately,
    and the contest stays there until the next ACCEPT re-completes it.
    AWAITING advances only on first report creation, per the Contest state
    machine."""
    r = compute_rollup(contest)
    contest["reported_precincts"] = r["reported_precincts"]
    contest["total_votes"] = r["total_votes"]
    contest["margin_pct"] = r["margin_pct"]
    contest["outstanding_estimate"] = r["outstanding_estimate"]
    if bump:
        if contest["tabulation_status"] in ("REPORTING", "COMPLETE"):
            contest["tabulation_status"] = "COMPLETE" if r["all_complete"] else "REPORTING"
        contest["version"] += 1
        contest["updated_at"] = clock_now()
    return r


def county_computed(county):
    """County.reported_precincts / status (PRD §3.5 last paragraph): max
    precincts_reporting among latest ACCEPTED reports naming the county;
    status PENDING / REPORTING / COMPLETE."""
    cid = county["id"]
    any_accepted = any(
        r["county_id"] == cid and r["status"] == "ACCEPTED"
        for r in db["reports"].values()
    )
    if not any_accepted:
        return 0, "PENDING"
    best = 0
    complete = False
    for link in db["links"].values():
        if link["county_id"] != cid:
            continue
        latest = latest_accepted_per_county(link["contest_id"]).get(cid)
        if latest is None:
            continue
        best = max(best, latest["precincts_reporting"])
        if latest["precincts_reporting"] == county["expected_precincts"]:
            complete = True
    return best, ("COMPLETE" if complete else "REPORTING")
