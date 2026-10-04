"""Ballot tallies, committee percentages and the meeting quorum derivation.

Sources: PRD.md 3.3, 3.4, 3.5 and SCAFFOLD.yaml `panel_weighted_vote_tally`,
`panel_vote_percent`, `committee_recommendation_vote`, `meeting_quorum_derivation`.

Included-ballot set (PRD.md 3.5): votes for the meeting whose vote is YES, NO
or ABSTAIN, whose change is still PANEL_REVIEW or DETERMINED, and which were
cast no later than the meeting's `conducted_at` when that instant is set, or no
later than the current logical clock instant when it is not.  Later ballots by
the same society on the same change supersede earlier ones: keep the greatest
`cast_at` per (society, change), ties broken by creation instant ascending.
"""

from clock import logical_now
from money import Decimal, as_float, dec, percent, round_half_up
import store

QUORUM_STATES = ("AGENDA_SET", "PANEL_REVIEW", "DETERMINED")
QUORUM_MINIMUM = 3
COMMITTEE_APPROVAL_PERCENT = dec("66.0000")
PANEL_APPROVAL_PERCENT = dec("66.00")
CITATION_APPROVAL_PERCENT = dec("66.6667")
CITATION_MODE_PERCENT = "66.6667"


def votes_carried_for(society, citation_mode):
    """`votes_carried` is the casting society's voting_seat_count as read at
    cast time; citation-only mode forces it to 1 for every ballot."""
    if citation_mode:
        return 1.0
    return float(dec(society.get("voting_seat_count") if society else 0))


def _included_votes(meeting_id, conducted_at, citation_mode):
    cutoff = conducted_at if conducted_at is not None else logical_now()
    rows = []
    for vote in store.editorial_votes.values():
        if vote.get("meeting_id") != meeting_id:
            continue
        if vote.get("vote") not in ("YES", "NO", "ABSTAIN"):
            continue
        change = store.code_changes.get(vote.get("change_id"))
        if change is None:
            continue
        if change.get("review_status") not in ("PANEL_REVIEW", "DETERMINED"):
            continue
        if vote.get("created_at") is not None and vote["created_at"] > cutoff:
            continue
        rows.append(vote)

    # Supersession: one ballot per (society, change).
    best = {}
    for vote in rows:
        key = (vote.get("society_id"), vote.get("change_id"))
        current = best.get(key)
        if current is None:
            best[key] = vote
            continue
        if _is_later(vote, current):
            best[key] = vote
    return list(best.values())


def _is_later(candidate, incumbent):
    """Order two ballots by (cast_at, created_at) ascending; the greater is the
    later one and supersedes the other (PRD.md 3.5: "the later ballot replaces
    the earlier one", with ties broken by creation instant).

    The logical clock is frozen between calls, so a superseding ballot can share
    both its `cast_at` and its `created_at` with the ballot it replaces; the
    insertion sequence is the final tie-break that keeps a later arrival later.
    """
    cand = (candidate.get("cast_at"), candidate.get("created_at"), candidate.get("_seq", 0))
    hold = (incumbent.get("cast_at"), incumbent.get("created_at"), incumbent.get("_seq", 0))
    return cand > hold


def panel_weighted_vote_tally(meeting):
    """Recompute and store the three weighted totals on the meeting."""
    citation_mode = bool(meeting.get("citation_mode"))
    included = _included_votes(meeting.get("id"), meeting.get("conducted_at"), citation_mode)

    yes = dec(0)
    no = dec(0)
    abstain = dec(0)
    for vote in included:
        carried = dec(vote.get("votes_carried"))
        if vote.get("vote") == "YES":
            yes = yes + carried
        elif vote.get("vote") == "NO":
            no = no + carried
        elif vote.get("vote") == "ABSTAIN":
            abstain = abstain + carried

    meeting["weighted_yes"] = as_float(round_half_up(yes, 2))
    meeting["weighted_no"] = as_float(round_half_up(no, 2))
    meeting["weighted_abstain"] = as_float(round_half_up(abstain, 2))
    return meeting


def panel_vote_percent(meeting):
    """Meeting-level support percentage, 2 decimals half up (PRD.md 3.5)."""
    yes = dec(meeting.get("weighted_yes"))
    no = dec(meeting.get("weighted_no"))
    total = yes + no
    if total <= 0:
        return None
    return percent(yes, total, 2)


def motion_carried(meeting):
    """Carried when the support percentage clears the floor for the meeting's
    mode and the combined weighted total is positive.

    Default mode (PRD.md 3.5): the threshold is 66.00 percent, evaluated at 2
    decimals.

    Citation-only mode (PRD.md 3.5): the threshold is the exact two-thirds
    floor of 66.6667 percent, evaluated at 4 decimals, which is the reading the
    PRD's own worked tallies require -- a seat tally of 22 to 11 approves,
    while a seat tally of 21 to 11 does not.  (The same paragraph also says the
    floor is enforced by truncating the weighted percentage to three decimals
    before comparing it with 66.667; that truncation cannot coexist with the
    worked tallies, since 22 to 11 is exactly two-thirds of 33 and so resolves
    to 66.6667, which the truncation would refuse.  The explicit tallies are
    the observable contract and are what is implemented here.)
    """
    yes = dec(meeting.get("weighted_yes"))
    no = dec(meeting.get("weighted_no"))
    if yes + no <= 0:
        return False
    exact = yes / (yes + no) * Decimal(100)

    if bool(meeting.get("citation_mode")):
        return dec(round_half_up(exact, 4)) >= CITATION_APPROVAL_PERCENT
    return dec(round_half_up(exact, 2)) >= PANEL_APPROVAL_PERCENT


def committee_recommendation_vote(yes_votes, no_votes):
    """yes/(yes+no)*100, 4 decimals half up; abstentions and absences excluded
    from the denominator entirely."""
    yes = dec(yes_votes)
    no = dec(no_votes)
    total = yes + no
    if total <= 0:
        return None
    return percent(yes, total, 4)


def committee_recommendation_status(vote_percent):
    if vote_percent is None:
        return "DEEMED_NOT_RECOMMENDED"
    return "RECOMMENDED" if dec(vote_percent) >= COMMITTEE_APPROVAL_PERCENT \
        else "DEEMED_NOT_RECOMMENDED"


def quorum_present(meeting_id):
    """True only while at least three *distinct* CodeChange rows carry this
    meeting's id with review_status AGENDA_SET, PANEL_REVIEW or DETERMINED
    (PRD.md 3.4)."""
    distinct = set()
    for change in store.code_changes.values():
        if change.get("meeting_id") != meeting_id:
            continue
        if change.get("review_status") not in QUORUM_STATES:
            continue
        distinct.add(change.get("id"))
    return len(distinct) >= QUORUM_MINIMUM


def recompute_quorum(meeting):
    if meeting is None:
        return None
    meeting["quorum_present"] = quorum_present(meeting.get("id"))
    return meeting["quorum_present"]


def meeting_society_seats(meeting_id):
    """Seat weights for the societies that count toward this meeting's quorum.

    The interested-party conflict guard (PRD.md 3.5) compares a public
    comment's commenter against "one of the seats counting toward the meeting's
    quorum", i.e. the societies seated on the changes docketed at the meeting.
    """
    seats = set()
    for change in store.code_changes.values():
        if change.get("meeting_id") != meeting_id:
            continue
        if change.get("review_status") not in QUORUM_STATES:
            continue
        if change.get("society_id"):
            seats.add(change["society_id"])
    return seats


def outside_cast_share(meeting):
    """Weighted share of the affirmative vote cast from outside the seated
    societies (PRD.md 3.5).  Ballots are attributed through their casting
    society; a ballot whose society is not seated on any docketed change is an
    outside cast."""
    citation_mode = bool(meeting.get("citation_mode"))
    included = _included_votes(meeting.get("id"), meeting.get("conducted_at"), citation_mode)
    seated = meeting_society_seats(meeting.get("id"))
    total_yes = dec(0)
    outside_yes = dec(0)
    for vote in included:
        if vote.get("vote") != "YES":
            continue
        carried = dec(vote.get("votes_carried"))
        total_yes = total_yes + carried
        if vote.get("society_id") not in seated:
            outside_yes = outside_yes + carried
    if total_yes <= 0:
        return None
    return percent(outside_yes, total_yes, 4)