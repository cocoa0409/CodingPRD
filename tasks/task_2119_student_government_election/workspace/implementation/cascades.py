"""The named cascades and the pinned certification order.

  * the four-hop disqualification cascade      (PRD 3.5)
  * the three-hop petition-void cascade        (PRD 3.3)
  * the three-hop officer-transition cascade   (PRD 3.9)
  * certification_evaluation_order STEP 1..6   (PRD 3.8)

Every hop is mandatory, every hop completes inside the single request that
triggered it, and every resource a hop touches receives a fresh updated_at and
an incremented version (PRD 2.9).
"""
import calc
import constants
import db
import lookup


# ===========================================================================
# shared hops
# ===========================================================================
def void_active_lines(candidacy):
    """Hop 3 of the compliance cascade / the withdrawal side effect.

    Every ACTIVE BallotLine naming the candidacy is voided and the parent
    ballot's active_line_count falls by one for each line voided.
    """
    touched_ballots = []
    for line in lookup.lines_of_candidacy(candidacy["id"]):
        if line["status"] != "ACTIVE":
            continue
        ballot = db.store.ballots.get(line["ballot_id"])
        db.set_fields(line, status="VOIDED")
        if ballot is not None:
            db.set_fields(ballot, active_line_count=max(0, ballot["active_line_count"] - 1))
            touched_ballots.append(ballot)
    return touched_ballots


def disqualify(candidacy, reason):
    """Hop 2 + hop 3: the candidacy is disqualified and its lines are voided."""
    db.set_fields(candidacy, status="DISQUALIFIED", disqualified_reason=reason)
    return void_active_lines(candidacy)


def flag_ballot_integrity(election, ballots):
    """Hop 4: a line was voided on a ballot that had already been locked."""
    if not any(b["status"] in ("LOCKED", "PUBLISHED", "CLOSED") for b in ballots):
        return False
    db.set_fields(election, ballot_integrity_status="RECOUNT_REQUIRED")
    if election["status"] == "CERTIFIED":
        db.set_fields(election, status="TALLYING",
                      certified_by_user_id=None, certified_at=None)
    return True


def compliance_cascade(case):
    """Hops 2 through 4 after a case has been scored and upheld."""
    candidacy = db.store.candidacies.get(case["candidacy_id"])
    election = db.store.elections.get(case["election_id"])
    if candidacy is None:
        return
    calc.recompute_penalty_total(candidacy)
    if candidacy["penalty_points_total"] < constants.DISQUALIFICATION_POINT_THRESHOLD:
        return
    if candidacy["status"] not in ("ELIGIBLE", "ON_BALLOT"):
        return
    ballots = disqualify(
        candidacy,
        "Penalty points total %d reached the disqualification threshold of %d."
        % (candidacy["penalty_points_total"], constants.DISQUALIFICATION_POINT_THRESHOLD),
    )
    if election is not None:
        flag_ballot_integrity(election, ballots)


def petition_void_cascade(candidacy):
    """Hops 2 and 3 after the signature counters have been recomputed."""
    office = db.store.offices.get(candidacy["office_id"])
    if office is None:
        return
    if candidacy["status"] != "ELIGIBLE":
        return
    if candidacy["petition_signature_valid_count"] >= office["required_signature_count"]:
        return
    db.set_fields(candidacy, status="PETITION_DEFICIENT")
    for member in db.by_seq(list(db.store.candidacies.values())):
        if member["slate_leader_candidacy_id"] == candidacy["id"] and member["status"] == "ELIGIBLE":
            db.set_fields(member, status="SLATE_SUSPENDED")


# ===========================================================================
# certification_evaluation_order — STEP 1 through STEP 6 (PRD 3.8)
# ===========================================================================
def snapshot_ballot(election):
    """The ballot of this election whose round equals the current round."""
    rows = [b for b in lookup.ballots_of(election["id"])
            if b["round"] == election["current_round"] and b["status"] != "VOIDED"]
    if not rows:
        return None
    return rows[-1]


def run_tally(election):
    ballot = snapshot_ballot(election)

    # ---- STEP 1 — freeze slate membership from the ballot-lock snapshot ----
    snapshot = list(ballot.get("_snapshot") or []) if ballot is not None else []
    frozen_ids = [entry["id"] for entry in snapshot]
    for entry in snapshot:
        candidacy = db.store.candidacies.get(entry["id"])
        if candidacy is None:
            continue
        root = entry["leader"] or entry["id"]
        members = [other["id"] for other in snapshot
                   if other["id"] == root or other["leader"] == root]
        db.set_fields(candidacy, slate_snapshot_member_ids=members)

    # ---- STEP 2 — FINAL spend over the frozen membership -------------------
    for candidacy_id in frozen_ids:
        candidacy = db.store.candidacies.get(candidacy_id)
        if candidacy is None:
            continue
        db.set_fields(candidacy, spending_final_cents=calc.final_spend(candidacy))

    # ---- STEP 3 — re-score every UPHELD case at the certification basis ----
    affected = {}
    for case in db.by_seq(list(db.store.compliance_cases.values())):
        if case["election_id"] != election["id"] or case["status"] != "UPHELD":
            continue
        calc.score_case(case, at_certification=True)
        affected[case["candidacy_id"]] = True
    for candidacy_id in affected:
        candidacy = db.store.candidacies.get(candidacy_id)
        if candidacy is not None:
            calc.recompute_penalty_total(candidacy)

    # ---- STEP 4 — the disqualification sweep -------------------------------
    for candidacy in lookup.candidacies_of(election["id"]):
        if candidacy["status"] != "ON_BALLOT":
            continue
        if candidacy["penalty_points_total"] < constants.DISQUALIFICATION_POINT_THRESHOLD:
            continue
        disqualify(
            candidacy,
            "Penalty points total %d reached the disqualification threshold of %d."
            % (candidacy["penalty_points_total"], constants.DISQUALIFICATION_POINT_THRESHOLD),
        )

    # ---- STEP 5 — raw counting --------------------------------------------
    round_votes = [v for v in lookup.votes_of(election["id"])
                   if v["round"] == election["current_round"] and v["status"] == "CAST"]

    for office in lookup.offices_of(election["id"]):
        marks = []
        for vote in round_votes:
            for mark in vote["selections"]:
                if isinstance(mark, dict) and mark.get("office_id") == office["id"]:
                    marks.append(mark)
                    break
        ballots_cast_for_office = len(marks)
        abstain = sum(1 for m in marks if m.get("candidacy_id") is None)

        office_candidacies = lookup.candidacies_of_office(office["id"])
        raw_by_candidacy = {}
        for candidacy in office_candidacies:
            raw = sum(1 for m in marks if m.get("candidacy_id") == candidacy["id"])
            raw_by_candidacy[candidacy["id"]] = raw

        invalidated = sum(raw_by_candidacy[c["id"]] for c in office_candidacies
                          if c["status"] == "DISQUALIFIED")
        valid = ballots_cast_for_office - abstain - invalidated

        db.set_fields(
            office,
            abstain_votes_count=abstain,
            invalidated_votes_count=invalidated,
            valid_votes_count=valid,
        )
        for candidacy in office_candidacies:
            raw = raw_by_candidacy[candidacy["id"]]
            certified = 0 if candidacy["status"] == "DISQUALIFIED" else raw
            db.set_fields(candidacy, raw_votes_count=raw, certified_votes_count=certified)

    # ---- STEP 6 — outcomes -------------------------------------------------
    runoff_offices = 0
    for office in lookup.offices_of(election["id"]):
        denominator_provisional = (office["valid_votes_count"]
                                   + office["abstain_votes_count"]
                                   + office["invalidated_votes_count"])
        office_candidacies = lookup.candidacies_of_office(office["id"])
        for candidacy in office_candidacies:
            db.set_fields(
                candidacy,
                provisional_share_pct=calc.pct2(candidacy["raw_votes_count"],
                                                denominator_provisional),
                certified_share_pct=calc.pct2(candidacy["certified_votes_count"],
                                              office["valid_votes_count"]),
            )
        contenders = calc.ranked([c for c in office_candidacies if c["status"] == "ON_BALLOT"])
        leader = contenders[0] if contenders else None
        if leader is not None and leader["certified_share_pct"] >= election["runoff_threshold_pct"]:
            db.set_fields(office, status="DECIDED")
        else:
            db.set_fields(office, status="RUNOFF_REQUIRED")
            runoff_offices += 1

    for referendum in lookup.referenda_of(election["id"]):
        if referendum["drafting_status"] != "ON_BALLOT":
            continue
        yes = no = abstain = 0
        for vote in round_votes:
            for mark in vote["selections"]:
                if not isinstance(mark, dict):
                    continue
                if mark.get("referendum_id") != referendum["id"]:
                    continue
                choice = mark.get("choice")
                if choice == "YES":
                    yes += 1
                elif choice == "NO":
                    no += 1
                elif choice == "ABSTAIN":
                    abstain += 1
                break
        decisive = yes + no
        approval = calc.pct2(yes, decisive)
        if election["turnout_pct"] < election["quorum_pct"]:
            outcome = "QUORUM_NOT_MET"
        elif decisive == 0:
            outcome = "FAILED"
        elif approval >= referendum["approval_threshold_pct"]:
            outcome = "PASSED"
        else:
            outcome = "FAILED"
        db.set_fields(referendum, yes_votes_count=yes, no_votes_count=no,
                      abstain_votes_count=abstain, approval_pct=approval,
                      outcome_status=outcome)

    db.set_fields(election, runoff_required_office_count=runoff_offices)
    db.set_fields(election, status="TALLYING")
    db.touch(election)


# ===========================================================================
# the certification fork (PRD 3.8)
# ===========================================================================
def _elect(candidacy, office):
    db.set_fields(
        candidacy,
        status="ELECTED",
        term_start_date=office["term_start_date"],
        term_end_date=office["term_end_date"],
        transition_status="PENDING",
    )


def certify_arm_a(election, user_id):
    """Fork arm A — runoff_required_office_count == 0."""
    for office in lookup.offices_of(election["id"]):
        contenders = calc.ranked([c for c in lookup.candidacies_of_office(office["id"])
                                  if c["status"] == "ON_BALLOT"])
        winners = contenders[:office["seat_count"]]
        winner_ids = {c["id"] for c in winners}
        for candidacy in winners:
            _elect(candidacy, office)
        for candidacy in contenders:
            if candidacy["id"] not in winner_ids:
                db.set_fields(candidacy, status="ELIMINATED")
        elected = sum(1 for c in lookup.candidacies_of_office(office["id"])
                      if c["status"] == "ELECTED")
        db.set_fields(office, status="DECIDED", filled_seat_count=elected)

    db.set_fields(election, status="CERTIFIED",
                  certified_by_user_id=user_id, certified_at=db.now())
    db.touch(election)


def runoff_qualifiers(office):
    """Top (seat_count + 1) by rank, plus every candidacy tied on
    certified_votes_count with the last of them — ties all advance."""
    contenders = calc.ranked([c for c in lookup.candidacies_of_office(office["id"])
                              if c["status"] == "ON_BALLOT"])
    cutoff = office["seat_count"] + 1
    qualifiers = contenders[:cutoff]
    if len(contenders) > cutoff and qualifiers:
        boundary = qualifiers[-1]["certified_votes_count"]
        for candidacy in contenders[cutoff:]:
            if candidacy["certified_votes_count"] == boundary:
                qualifiers.append(candidacy)
            else:
                break
    return contenders, qualifiers


def certify_arm_b(election):
    """Fork arm B — runoff_required_office_count >= 1.

    No officer transition is opened and no certification identity is stamped.
    """
    for office in lookup.offices_of(election["id"]):
        if office["status"] != "RUNOFF_REQUIRED":
            continue
        contenders, qualifiers = runoff_qualifiers(office)
        qualifier_ids = {c["id"] for c in qualifiers}
        for candidacy in qualifiers:
            db.set_fields(candidacy, status="RUNOFF_QUALIFIED")
        for candidacy in contenders:
            if candidacy["id"] not in qualifier_ids:
                db.set_fields(candidacy, status="ELIMINATED")

    db.set_fields(election, status="RUNOFF_SCHEDULED")
    db.touch(election)


# ===========================================================================
# the officer-transition cascade (PRD 3.9)
# ===========================================================================
def run_transition_checkpoint(election):
    now = db.now()

    # The delinquent set is decided against the state at the head of the
    # checkpoint: an alternate promoted by hop 3 opens its own transition at
    # PENDING and is not itself lapsed by the same sweep.
    delinquent = []
    for candidacy in lookup.candidacies_of(election["id"]):
        if candidacy["transition_status"] != "PENDING":
            continue
        office = db.store.offices.get(candidacy["office_id"])
        if office is None:
            continue
        term_start = candidacy.get("term_start_date")
        if term_start is None or not now > term_start:
            continue
        if candidacy["training_modules_completed"] >= office["required_training_modules"]:
            continue
        delinquent.append(candidacy)

    for candidacy in delinquent:
        office = db.store.offices.get(candidacy["office_id"])

        # hop 1 — lapse the delinquent officer
        db.set_fields(candidacy, transition_status="LAPSED")
        # hop 2 — vacate the seat
        if candidacy["status"] == "ELECTED":
            db.set_fields(candidacy, status="VACATED")
            db.set_fields(office, filled_seat_count=max(0, office["filled_seat_count"] - 1))
            if office["status"] == "DECIDED":
                db.set_fields(office, status="VACANT_SEAT")
        # hop 3 — promote the ranking alternate
        alternates = calc.ranked([c for c in lookup.candidacies_of_office(office["id"])
                                  if c["status"] == "ELIMINATED"])
        if alternates:
            alternate = alternates[0]
            _elect(alternate, office)
            db.set_fields(office, filled_seat_count=office["filled_seat_count"] + 1)
            if office["status"] == "VACANT_SEAT":
                db.set_fields(office, status="DECIDED")

    # the same checkpoint closes the cycle
    elected = [c for c in lookup.candidacies_of(election["id"]) if c["status"] == "ELECTED"]
    offices = lookup.offices_of(election["id"])
    all_active = all(c["transition_status"] == "ACTIVE" for c in elected)
    term_starts = [o["term_start_date"] for o in offices if o["term_start_date"] is not None]
    reached = bool(term_starts) and now >= max(term_starts)
    if election["status"] == "CERTIFIED" and all_active and reached:
        db.set_fields(election, status="CLOSED")
    db.touch(election)
