"""Derived-field recomputation and cascade discipline.

PRD section 2.4: recomputing a derived field is a mutation of the resource that
owns it.  PRD section 2.11: cascades run inside the same atomic operation and
every resource they touch is itself mutated (updated_at refreshed, version
bumped).

The helpers here recompute fields IN PLACE and never bump a version; the calling
route bumps each mutated resource exactly once per request.
"""

import db
import calc
from errors import ApiError


# --- collection helpers -----------------------------------------------------
def memberships_of_club(club_id):
    return [m for m in db.MEMBERSHIPS.values() if m["club_id"] == club_id]


def memberships_of_member(member_id):
    return [m for m in db.MEMBERSHIPS.values() if m["member_id"] == member_id]


def paths_of_membership(membership_id):
    return [p for p in db.PATHS.values() if p["membership_id"] == membership_id]


def paths_of_club(club_id):
    ids = {m["id"] for m in memberships_of_club(club_id)}
    return [p for p in db.PATHS.values() if p["membership_id"] in ids]


def completions_of_path(path_id):
    return [c for c in db.COMPLETIONS.values() if c["path_id"] == path_id]


def completions_of_club(club_id):
    return [c for c in db.COMPLETIONS.values() if c["club_id"] == club_id]


def assignments_of_meeting(meeting_id):
    return [a for a in db.ASSIGNMENTS.values() if a["meeting_id"] == meeting_id]


def entries_of_contest(contest_id):
    return [e for e in db.ENTRIES.values() if e["contest_id"] == contest_id]


def entries_of_club(club_id):
    return [e for e in db.ENTRIES.values() if e["club_id"] == club_id]


def terms_of_club(club_id):
    return [t for t in db.OFFICER_TERMS.values() if t["club_id"] == club_id]


def terms_of_membership(membership):
    return [
        t
        for t in db.OFFICER_TERMS.values()
        if t["club_id"] == membership["club_id"] and t["member_id"] == membership["member_id"]
    ]


def cycle_window(club, cutoff=None, cycle_scoped=True):
    """Rows belonging to the club's current cycle (optionally capped by cutoff).

    The cycle-close variant of every count includes only rows created at or
    before cycle_closed_at; the live variant counts every current row.

    ``cycle_scoped`` marks the counters whose own definition is anchored to the
    cycle's activity window ("meetings held this cycle", "this cycle's contest
    entries", ...).  The roster counters (paid_member_count, total_member_count,
    new_member_count_this_cycle, officer_trained_count) are defined purely by
    the row's current status/pointer -- PRD section 2.6 states no creation
    window for them -- so they never apply the cycle_opened_at floor; the
    live variant of the score "counts every current row" (PRD section 2.7).
    """
    start = club.get("cycle_opened_at") if cycle_scoped else None

    def in_window(row):
        created = row["created_at"]
        if start is not None and created < start:
            return False
        if cutoff is not None and created > cutoff:
            return False
        return True

    return in_window


# --- counters ---------------------------------------------------------------
def paid_member_count(club, cutoff=None):
    index = club["dues_cycle_index"]
    in_window = cycle_window(club, cutoff, cycle_scoped=False)
    return len(
        [
            m
            for m in memberships_of_club(club["id"])
            if m["dues_paid_through_cycle"] >= index and in_window(m)
        ]
    )


def total_member_count(club, cutoff=None):
    in_window = cycle_window(club, cutoff, cycle_scoped=False)
    return len(
        [
            m
            for m in memberships_of_club(club["id"])
            if m["status"] in ("PENDING", "ACTIVE") and in_window(m)
        ]
    )


def new_member_count(club, cutoff=None):
    """Memberships whose first paid cycle equals the club's current index.

    The first paid cycle of the current consecutive run is derived from the two
    declared fields: dues_paid_through_cycle - consecutive_cycles_paid + 1.
    """
    index = club["dues_cycle_index"]
    in_window = cycle_window(club, cutoff, cycle_scoped=False)
    count = 0
    for membership in memberships_of_club(club["id"]):
        paid_through = membership["dues_paid_through_cycle"]
        consecutive = membership.get("consecutive_cycles_paid", 0)
        if paid_through < 0 or consecutive < 1:
            continue
        if paid_through - consecutive + 1 == index and in_window(membership):
            count += 1
    return count


def officer_trained_count(club, cutoff=None):
    index = club["dues_cycle_index"]
    in_window = cycle_window(club, cutoff, cycle_scoped=False)
    return len(
        [
            t
            for t in terms_of_club(club["id"])
            if t["term_index"] == index
            and t["status"] in ("TRAINED", "COMPLETED")
            and in_window(t)
        ]
    )


def meetings_held_count(club, cutoff=None):
    in_window = cycle_window(club, cutoff)
    return len(
        [
            m
            for m in db.MEETINGS.values()
            if m["club_id"] == club["id"] and m["status"] == "HELD" and in_window(m)
        ]
    )


def approved_level_completions_count(club, cutoff=None):
    """APPROVED completions at this club in the cycle at the member's path level."""
    in_window = cycle_window(club, cutoff)
    count = 0
    for completion in completions_of_club(club["id"]):
        if completion["status"] != "APPROVED" or not in_window(completion):
            continue
        path = db.PATHS.get(completion["path_id"])
        if path is None:
            continue
        if completion["level"] == calc.path_level_number(path["level"]):
            count += 1
    return count


def contest_participation_count(club, cutoff=None):
    in_window = cycle_window(club, cutoff)
    count = 0
    for entry in entries_of_club(club["id"]):
        contest = db.CONTESTS.get(entry["contest_id"])
        if contest is None or contest["contest_level"] != "CLUB":
            continue
        if in_window(entry):
            count += 1
    return count


def dcp_education_points(club, cutoff=None):
    """Per ACTIVE membership, its approved completions at this club, capped 2."""
    in_window = cycle_window(club, cutoff)
    total = 0
    for membership in memberships_of_club(club["id"]):
        if membership["status"] != "ACTIVE":
            continue
        per_membership = 0
        for completion in completions_of_club(club["id"]):
            if completion["status"] != "APPROVED":
                continue
            if completion["member_id"] != membership["member_id"]:
                continue
            if not in_window(completion):
                continue
            per_membership += 1
        total += min(calc.MEMBER_PER_MEMBERSHIP_CAP, per_membership)
    return total


# --- entity recomputation ---------------------------------------------------
def recompute_member(member):
    speeches = 0
    highest = 0
    for membership in memberships_of_member(member["id"]):
        for path in paths_of_membership(membership["id"]):
            for completion in completions_of_path(path["id"]):
                if completion["status"] != "APPROVED":
                    continue
                if completion["project_kind"] == "SPEECH":
                    speeches += 1
                if completion["level"] > highest:
                    highest = completion["level"]
    member["total_speeches_delivered"] = speeches
    member["highest_level_completed"] = highest


def recompute_path(path):
    speeches = 0
    projects = 0
    current = calc.path_level_number(path["level"])
    for completion in completions_of_path(path["id"]):
        if completion["status"] != "APPROVED":
            continue
        if completion["level"] != current:
            continue
        projects += 1
        if completion["project_kind"] == "SPEECH":
            speeches += 1
    path["approved_speeches_at_level"] = speeches
    path["approved_projects_at_level"] = projects


def recompute_membership(membership):
    """Recompute the member-scoped counters carried by one membership row."""
    club = db.CLUBS.get(membership["club_id"])
    in_window = cycle_window(club) if club else (lambda row: True)

    speeches = 0
    for completion in db.COMPLETIONS.values():
        if completion["member_id"] != membership["member_id"]:
            continue
        if completion["club_id"] != membership["club_id"]:
            continue
        if completion["status"] != "APPROVED" or completion["project_kind"] != "SPEECH":
            continue
        if in_window(completion):
            speeches += 1
    membership["speeches_delivered_this_cycle"] = speeches

    completed_roles = 0
    for assignment in db.ASSIGNMENTS.values():
        if assignment["member_id"] != membership["member_id"]:
            continue
        if assignment["status"] != "COMPLETED":
            continue
        if in_window(assignment):
            completed_roles += 1
    membership["roles_completed_this_cycle"] = completed_roles

    recompute_officer_role(membership)


def recompute_officer_role(membership):
    """Derived from the member's current ELECTED or TRAINED term at this club."""
    role = "NONE"
    for term in terms_of_membership(membership):
        if term["status"] in ("ELECTED", "TRAINED"):
            role = term["office"]
            break
    membership["officer_role"] = role


def recompute_meeting(meeting):
    filled = 0
    for assignment in assignments_of_meeting(meeting["id"]):
        if assignment["status"] in ("ASSIGNED", "COMPLETED", "NO_SHOW"):
            filled += 1
    meeting["filled_role_slots"] = filled


def recompute_contest(contest):
    entries = entries_of_contest(contest["id"])
    contest["entry_count"] = len([e for e in entries if e["status"] != "DISQUALIFIED"])
    contest["judged_entry_count"] = len(
        [e for e in entries if e["status"] in ("JUDGED", "ADVANCED", "ELIMINATED")]
    )


def recompute_club(club, cutoff=None):
    """Recompute every derived club counter.

    dcp_recognition_points is evaluated FIRST from the cycle_open_standing
    snapshot; good_standing_score is evaluated SECOND from those points and
    never feeds back into the same cycle's recognition points.
    """
    paid = paid_member_count(club, cutoff)
    total = total_member_count(club, cutoff)
    new_members = new_member_count(club, cutoff)
    trained = officer_trained_count(club, cutoff)
    meetings = meetings_held_count(club, cutoff)
    completions = approved_level_completions_count(club, cutoff)
    participation = contest_participation_count(club, cutoff)

    points = calc.dcp_points_from_parts(
        dcp_education_points(club, cutoff),
        new_members,
        paid,
        trained,
        participation,
        club.get("cycle_open_standing"),
    )
    score = calc.score_from_counts(paid, trained, completions, meetings, points)

    club["paid_member_count"] = paid
    club["total_member_count"] = total
    club["new_member_count_this_cycle"] = new_members
    club["officer_trained_count"] = trained
    club["meetings_held_this_cycle"] = meetings
    club["approved_level_completions_this_cycle"] = completions
    club["contest_participation_count"] = participation
    club["dcp_recognition_points"] = points
    club["dcp_tier"] = calc.dcp_tier(points)
    club["good_standing_score"] = score
    return club


def touch_club(club, cutoff=None):
    """Recompute the club's derived counters and bump it once."""
    recompute_club(club, cutoff)
    return db.touch(club)


def refresh_club(club):
    """Recompute the club once for an ordinary in-cycle mutation."""
    return touch_club(club)


# --- cascades ---------------------------------------------------------------
def suspend_path(path):
    if path["status"] != "ACTIVE":
        return False
    path["status"] = "SUSPENDED"
    db.touch(path)
    return True


def activate_path(path):
    if path["status"] != "SUSPENDED":
        return False
    path["status"] = "ACTIVE"
    db.touch(path)
    return True


def disqualify_entry(entry):
    if entry["status"] not in ("ENTERED", "JUDGED"):
        return False
    entry["status"] = "DISQUALIFIED"
    db.touch(entry)
    # PRD section 3.8: "A DISQUALIFIED entry stops counting toward the
    # contest's entry_count and judged_entry_count, both of which are
    # recomputed" -- including when the disqualification arrives through a
    # cascade (PRD section 2.11 recomputes the affected derived counters once
    # from the state the cascade left behind).
    contest = db.CONTESTS.get(entry["contest_id"])
    if contest is not None:
        recompute_contest(contest)
    return True


def disqualify_entries_for_member_club(member_id, club_id):
    for entry in db.ENTRIES.values():
        if entry["member_id"] == member_id and entry["club_id"] == club_id:
            disqualify_entry(entry)


def disqualify_entries_for_club(club_id):
    for entry in entries_of_club(club_id):
        disqualify_entry(entry)


def disqualify_entries_for_paths(paths):
    for path in paths:
        membership = db.MEMBERSHIPS.get(path["membership_id"])
        if membership is None:
            continue
        disqualify_entries_for_member_club(membership["member_id"], membership["club_id"])


def vacate_terms_for_membership(membership):
    """Every term of this membership at this club that is NOMINATED/ELECTED/TRAINED."""
    for term in terms_of_membership(membership):
        if term["status"] in ("NOMINATED", "ELECTED", "TRAINED"):
            term["status"] = "VACATED"
            db.touch(term)
    recompute_officer_role(membership)


def vacate_terms_for_club(club_id):
    for term in terms_of_club(club_id):
        if term["status"] in ("NOMINATED", "ELECTED", "TRAINED"):
            term["status"] = "VACATED"
            db.touch(term)


def complete_terms_below_index(club, new_index):
    """Step five of a cycle close: terms older than the new index complete."""
    touched_members = set()
    for term in terms_of_club(club["id"]):
        if term["term_index"] < new_index and term["status"] in ("ELECTED", "TRAINED"):
            term["status"] = "COMPLETED"
            db.touch(term)
            touched_members.add(term["member_id"])
    for member_id in touched_members:
        for membership in memberships_of_club(club["id"]):
            if membership["member_id"] == member_id:
                recompute_officer_role(membership)


# --- membership lifecycle cascades -----------------------------------------
def lapse_membership(membership, force_overdue=False):
    """Resolve a membership that lost its standing.

    The Membership ACTIVE -> LAPSED transition carries these side effects:
    dues_status becomes OVERDUE, its education paths suspend, those paths'
    contest entries are disqualified and its officer terms are vacated.  The
    cycle sweep only moves an invoice that is still ISSUED to OVERDUE (a PAID
    invoice for the closing cycle is left alone); a club-level suspension or
    revocation lapses the membership outright.
    """
    changed = False
    if force_overdue:
        if membership["dues_status"] != "OVERDUE":
            membership["dues_status"] = "OVERDUE"
            changed = True
    elif membership["dues_status"] == "ISSUED":
        membership["dues_status"] = "OVERDUE"
        changed = True
    if membership["status"] != "LAPSED":
        membership["status"] = "LAPSED"
        changed = True
    if changed:
        db.touch(membership)
    for path in paths_of_membership(membership["id"]):
        if suspend_path(path):
            disqualify_entries_for_member_club(membership["member_id"], membership["club_id"])
    vacate_terms_for_membership(membership)
    return changed


def activate_membership(membership):
    """PENDING/LAPSED -> ACTIVE, lifting every suspended path back up."""
    if membership["status"] == "ACTIVE":
        return False
    membership["status"] = "ACTIVE"
    for path in paths_of_membership(membership["id"]):
        activate_path(path)
    return True


# --- cycle close ------------------------------------------------------------
def close_cycle(club, supplied_opened_at, supplied_closed_at):
    """The five ordered steps of POST /toastmasters/clubs/{id}/close-cycle.

    Returns the club.  The caller bumps the club's version exactly once.
    """
    now = db.utcnow()
    closed_at = supplied_closed_at or now
    old_index = club["dues_cycle_index"]

    # step 1 - sweep the closing cycle
    for membership in memberships_of_club(club["id"]):
        if membership["dues_paid_through_cycle"] < old_index:
            lapse_membership(membership)

    # step 2 - recognition points, cycle-close variant, from the state above
    recompute_club(club, cutoff=closed_at)

    # step 3 - score and posture, then the charter consequences
    score = club["good_standing_score"]
    previous_posture = club["good_standing"]
    posture = calc.posture_from_score(score)
    club["good_standing"] = posture

    # Posture-driven cascade: an entry whose club is no longer GOOD is out.
    if posture != "GOOD":
        disqualify_entries_for_club(club["id"])
    if posture == "NOT_IN_GOOD_STANDING" and club["coaching_status"] == "NONE":
        club["coaching_status"] = "FLAGGED"
    if posture == "GOOD" and previous_posture == "NOT_IN_GOOD_STANDING":
        for visit in db.VISITS.values():
            if (
                visit["club_id"] == club["id"]
                and visit["visit_kind"] == "CLUB_COACH"
                and visit["status"] == "COMPLETED"
            ):
                club["coaching_status"] = "COACHED"
                break

    if club["charter_status"] in ("CHARTERED", "SUSPENDED"):
        if score < calc.REVOKE_BELOW:
            club["charter_status"] = "REVOKED"
            for membership in memberships_of_club(club["id"]):
                lapse_membership(membership, force_overdue=True)
            vacate_terms_for_club(club["id"])
        elif score < calc.PROBATION_MIN and club["charter_status"] == "CHARTERED":
            club["charter_status"] = "SUSPENDED"
            for membership in memberships_of_club(club["id"]):
                if membership["status"] == "ACTIVE":
                    lapse_membership(membership, force_overdue=True)

    # step 4 - advance the clock and issue the next invoice
    club["dues_cycle_index"] = old_index + 1
    club["cycle_opened_at"] = supplied_opened_at or now
    club["cycle_closed_at"] = closed_at
    club["cycle_open_standing"] = club["good_standing"]
    for membership in memberships_of_club(club["id"]):
        if membership["status"] not in ("PENDING", "ACTIVE"):
            continue
        if membership["dues_status"] in ("PAID", "VOID"):
            membership["dues_status"] = "ISSUED"
        membership["quoted_total_cents"] = calc.dues_quote_total_cents(membership, club)
        db.touch(membership)

    # step 5 - age the term and the governance schedule
    complete_terms_below_index(club, club["dues_cycle_index"])
    for visit in db.VISITS.values():
        if visit["club_id"] != club["id"] or visit["status"] != "SCHEDULED":
            continue
        if visit["scheduled_at"] < closed_at:
            visit["status"] = "MISSED"
            db.touch(visit)
            if (
                visit["visit_kind"] == "CLUB_COACH"
                and club["good_standing"] in ("PROBATION", "NOT_IN_GOOD_STANDING")
            ):
                club["coaching_status"] = "FLAGGED"
    if (
        club["good_standing"] in ("PROBATION", "NOT_IN_GOOD_STANDING")
        and club["coaching_status"] == "NONE"
    ):
        club["coaching_status"] = "FLAGGED"

    # The counters recomputed in step two are frozen for the closing cycle and
    # reported on the club until the next close (PRD section 2.7), so the club
    # is deliberately NOT recomputed again against the newly opened cycle.
    return club


# --- shared guards ----------------------------------------------------------
def require_membership_paid_active(membership, club):
    """Priority 18: the membership must be ACTIVE and paid through this cycle."""
    if membership["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE")
    if membership["dues_paid_through_cycle"] < club["dues_cycle_index"]:
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE")


def require_club_good_standing(club):
    """Priority 17: GOOD posture for contest entry and level advancement."""
    if club["good_standing"] != "GOOD":
        raise ApiError("ERR_CLUB_NOT_IN_GOOD_STANDING")
