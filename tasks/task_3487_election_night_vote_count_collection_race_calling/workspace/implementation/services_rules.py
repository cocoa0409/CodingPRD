"""qc_deviation_check, call_certainty_evaluation, stringer_reliability_score,
and the assignment overlap/selector rules (SCAFFOLD §1.3 / PRD §3.3-3.6)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import db
from util import round6, parse_date, SIX_PLACES
import services_rollup as rollup

# qc_deviation_check constants (SCAFFOLD §1.3)
QC_VOTE_DEVIATION_PCT = 0.40
QC_SWING_PCT = 0.25

# stringer_reliability_score constants
NO_SHOW_PENALTY = 25
VOIDED_PENALTY = 10
ACCEPTED_CREDIT = 2
SCORE_FLOOR = 0
SCORE_CAP = 100
RECENT_WINDOW_DAYS = 365
RECENT_DEFAULT_EVAL_DATE = "2026-09-01"

# recount filing threshold (SCAFFOLD §1.5 / PRD §3.7), inclusive
RECOUNT_MARGIN_THRESHOLD = 0.005


def qc_check(contest, county, candidate_votes):
    """Runs at VoteReport creation and resubmit. Returns
    (reported_total, deviation_ratio, swing_deviation, flagged)."""
    reported_total = sum(int(e["votes"]) for e in candidate_votes)
    deviation_ratio = round6(
        abs(reported_total - county["expected_vote_total"]),
        county["expected_vote_total"],
    )
    swing = None
    if county["historical_dem_share"] is not None and reported_total > 0:
        dem_votes = 0
        has_dem = False
        for c in db["candidates"].values():
            if c["contest_id"] == contest["id"] and c["party"] == "DEM":
                has_dem = True
                for e in candidate_votes:
                    if e["candidate_id"] == c["id"]:
                        dem_votes += int(e["votes"])
        if has_dem:
            reported_dem_share = Decimal(dem_votes) / Decimal(max(reported_total, 1))
            swing = float(
                abs(reported_dem_share - Decimal(str(county["historical_dem_share"])))
                .quantize(SIX_PLACES, rounding=ROUND_HALF_UP)
            )
    flagged = (
        deviation_ratio > QC_VOTE_DEVIATION_PCT
        or (swing is not None and swing > QC_SWING_PCT)
    )
    return reported_total, deviation_ratio, swing, flagged


def certainty_passes(contest, winner_candidate_id):
    """call_certainty_evaluation (PRD §3.6): certainty that no trailing
    candidate can catch up on the outstanding vote — never a projection."""
    r = rollup.refresh_contest(contest, bump=False)
    totals = {c["id"]: v for c, v in r["candidate_totals"]}
    ranked = [c for c, _ in r["candidate_totals"]]
    outstanding = r["outstanding_estimate"]
    seats = contest["seats"]
    w_total = totals.get(winner_candidate_id, 0)

    if contest["contest_type"] == "BALLOT_MEASURE" or seats == 1:
        # Single-seat rule: W strictly ahead of every other candidate even
        # after the whole outstanding vote breaks against W.
        for cand in ranked:
            if cand["id"] == winner_candidate_id:
                continue
            if not (w_total > totals.get(cand["id"], 0) + outstanding):
                return False
        return True

    # Multi-seat: V_next is the total one rank below the last winning rank.
    with_votes = [c for c in ranked if totals.get(c["id"], 0) > 0]
    if len(with_votes) < seats + 1:
        return w_total > 0
    v_next = totals.get(ranked[seats]["id"], 0)  # ranked is 0-indexed; index s == rank s+1
    rank_of_w = next(
        (i + 1 for i, c in enumerate(ranked) if c["id"] == winner_candidate_id),
        len(ranked) + 1,
    )
    return w_total > v_next + outstanding and rank_of_w <= seats


def _reliability(stringer, variant, eval_date):
    """score = clamp(100 - 25*no_shows - 10*voided + 2*accepted, 0, 100) over
    the variant's event window (PRD §3.3)."""
    no_shows = accepted = voided = 0
    cutoff = None
    if variant == "RECENT_FORM" and eval_date is not None:
        cutoff = eval_date - timedelta(days=RECENT_WINDOW_DAYS)
    for ev in stringer["reliability_events"]:
        if variant == "RECENT_FORM":
            edate = parse_date(db["events"][ev["event_id"]]["event_date"])
            if eval_date is None or not (edate > cutoff):
                continue
        if ev["kind"] == "no_show":
            no_shows += 1
        elif ev["kind"] == "accepted":
            accepted += 1
        elif ev["kind"] == "voided":
            voided += 1
    score = 100 - NO_SHOW_PENALTY * no_shows - VOIDED_PENALTY * voided + ACCEPTED_CREDIT * accepted
    return max(SCORE_FLOOR, min(SCORE_CAP, score))


def stringer_scores_for_read(stringer):
    """Bare roster read: RECENT_FORM evaluated against the greatest event_date
    among the stringer's assignments, else the fixed default 2026-09-01."""
    dates = [
        parse_date(db["events"][a["event_id"]]["event_date"])
        for a in db["assignments"].values()
        if a["stringer_id"] == stringer["id"] and a["event_id"] in db["events"]
    ]
    eval_date = max(dates) if dates else parse_date(RECENT_DEFAULT_EVAL_DATE)
    return (
        _reliability(stringer, "CAREER", None),
        _reliability(stringer, "RECENT_FORM", eval_date),
    )


def reliability_for_event(stringer, event):
    """Selector ranking: RECENT_FORM evaluated against the event being
    selected for (PRD §3.3)."""
    eval_date = parse_date(event["event_date"])
    return _reliability(stringer, event["stringer_selection_mode"], eval_date)


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end


def has_overlap(stringer_id, window_start, window_end):
    """True when the stringer holds a SCHEDULED/ACTIVE assignment whose
    half-open window overlaps the requested one."""
    for a in db["assignments"].values():
        if a["stringer_id"] != stringer_id:
            continue
        if a["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if windows_overlap(a["window_start"], a["window_end"], window_start, window_end):
            return True
    return False


def auto_select_stringer(event, window_start, window_end):
    """Eligible pool: rostered stringers with no overlapping SCHEDULED/ACTIVE
    assignment; ranked by the event's reliability variant DESC, tie-break
    Stringer.created_at ASC. Returns the chosen record or None."""
    pool = [
        s for s in db["stringers"].values()
        if not has_overlap(s["id"], window_start, window_end)
    ]
    if not pool:
        return None
    pool.sort(key=lambda s: (-reliability_for_event(s, event), s["created_at"], s["_seq"]))
    return pool[0]


def active_assignment_for(stringer_id, county_id, event_id):
    """Collection authority: an ACTIVE assignment covering exactly this
    stringer, county, and event (PRD §3.4)."""
    for a in db["assignments"].values():
        if (a["stringer_id"] == stringer_id
                and a["county_id"] == county_id
                and a["event_id"] == event_id
                and a["status"] == "ACTIVE"):
            return a
    return None


def feed_covers(event_id, state_code):
    """A FeedSource of the event whose state_codes contains the county's
    state_code (PRD §3.4)."""
    for f in db["feeds"].values():
        if f["event_id"] == event_id and state_code in f["state_codes"]:
            return f
    return None
