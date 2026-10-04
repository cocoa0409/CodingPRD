"""CandidateFiling routes (PRD 3.2): record/list + verify/withdraw/
disqualify/refile with their shell cascades."""
from flask import Blueprint

import helpers
import serialize
import shape
import shells
from authz import (CHAPTER_COORDINATOR, LEAGUE_ADMIN, QUESTIONNAIRE_EDITOR,
                   check_active_current, require_roles)
from errors import (duplicate_filing_reference, filing_deadline_passed,
                    invalid_state)
from helpers import base_entity, touch
from respond import listing, success
from store import store

bp = Blueprint("filings", __name__)


@bp.post("/contests/<cid>/filings")
def create_filing(cid):
    uid, role, volunteer = require_roles(CHAPTER_COORDINATOR)
    b = shape.body()
    shape.no_extra(b, {"candidate_name", "party_label", "filing_reference"})
    candidate_name = shape.s_str(b, "candidate_name")
    party_label = shape.s_str(b, "party_label")
    filing_reference = shape.s_str(b, "filing_reference")
    contest = helpers.get_contest(cid)
    if contest["status"] != "FILING_OPEN":
        raise invalid_state("The contest is not FILING_OPEN")
    check_active_current(volunteer)
    if not store.clock <= contest["filing_deadline"]:
        raise filing_deadline_passed()
    for other in helpers.filings_of_contest(contest["id"]):
        if other["filing_reference"] == filing_reference:
            raise duplicate_filing_reference()
    filing = base_entity()
    filing.update({
        "contest_id": contest["id"],
        "candidate_name": candidate_name,
        "party_label": party_label,
        "filing_reference": filing_reference,
        "status": "FILED",
        "filed_at": store.clock,
        "verified_at": None,
        "withdrawal_count": 0,
    })
    store.filings[filing["id"]] = filing
    return success(serialize.filing_json(filing), status=201)


@bp.get("/contests/<cid>/filings")
def list_filings(cid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR)
    contest = helpers.get_contest(cid)
    limit, offset = shape.pagination_params()
    status_filter = shape.q("status")
    rows = helpers.filings_of_contest(contest["id"])
    if status_filter is not None:
        rows = [f for f in rows if f["status"] == status_filter]
    rows, total = helpers.page_of(rows, limit, offset)
    return listing([serialize.filing_json(f) for f in rows],
                   limit, offset, total)


@bp.post("/filings/<fid>/verify")
def verify_filing(fid):
    uid, role, volunteer = require_roles(CHAPTER_COORDINATOR)
    b = shape.body()
    shape.no_extra(b, set())
    filing = helpers.get_filing(fid)
    contest = store.contests[filing["contest_id"]]
    if filing["status"] != "FILED":
        raise invalid_state("Only a FILED filing may be verified")
    if contest["status"] not in ("FILING_OPEN", "QUESTIONNAIRE_PHASE"):
        raise invalid_state("The contest no longer accepts verifications")
    check_active_current(volunteer)
    filing["status"] = "VERIFIED"
    filing["verified_at"] = store.clock
    touch(filing)
    touch(contest)  # verification advances Contest.version (PRD 2.6)
    # Late verification while the questionnaire is ISSUED and in-window
    # still creates the candidate's INVITED shell.
    q = helpers.questionnaire_of_contest(contest["id"])
    if (q is not None and q["status"] == "ISSUED"
            and store.clock <= q["due_at"]
            and helpers.shell_of(q["id"], filing["id"]) is None):
        shells.create_shell(q, filing)
    return success(serialize.filing_json(filing))


@bp.post("/filings/<fid>/withdraw")
def withdraw_filing(fid):
    uid, role, volunteer = require_roles(CHAPTER_COORDINATOR)
    b = shape.body()
    shape.no_extra(b, set())
    filing = helpers.get_filing(fid)
    if filing["status"] not in ("FILED", "VERIFIED"):
        raise invalid_state("Only a FILED or VERIFIED filing may be withdrawn")
    check_active_current(volunteer)
    was_verified = filing["status"] == "VERIFIED"
    filing["status"] = "WITHDRAWN"
    filing["withdrawal_count"] += 1
    touch(filing)
    if was_verified:
        # A verified withdrawal recomputes the contest roster and hides the
        # candidate's response shell (PRD 3.2).
        touch(store.contests[filing["contest_id"]])
        shells.hide_shell_for_filing(filing)
    return success(serialize.filing_json(filing))


@bp.post("/filings/<fid>/disqualify")
def disqualify_filing(fid):
    uid, role, volunteer = require_roles(CHAPTER_COORDINATOR)
    b = shape.body()
    shape.no_extra(b, {"reason"})
    shape.s_str(b, "reason")
    filing = helpers.get_filing(fid)
    if filing["status"] != "VERIFIED":
        raise invalid_state("Only a VERIFIED filing may be disqualified")
    check_active_current(volunteer)
    filing["status"] = "DISQUALIFIED"
    touch(filing)
    touch(store.contests[filing["contest_id"]])
    shells.hide_shell_for_filing(filing)
    return success(serialize.filing_json(filing))


@bp.post("/filings/<fid>/refile")
def refile_filing(fid):
    uid, role, volunteer = require_roles(CHAPTER_COORDINATOR)
    b = shape.body()
    shape.no_extra(b, set())
    filing = helpers.get_filing(fid)
    if filing["status"] != "WITHDRAWN":
        raise invalid_state("Only a WITHDRAWN filing may be refiled")
    check_active_current(volunteer)
    contest = store.contests[filing["contest_id"]]
    q = helpers.questionnaire_of_contest(contest["id"])
    gate_open = (
        (contest["status"] == "FILING_OPEN"
         and store.clock <= contest["filing_deadline"])
        or (contest["status"] == "QUESTIONNAIRE_PHASE"
            and q is not None and q["status"] == "ISSUED"
            and store.clock <= q["due_at"])
    )
    if not gate_open:
        raise filing_deadline_passed()
    filing["status"] = "FILED"
    filing["filed_at"] = store.clock
    touch(filing)
    shells.restore_shell_for_filing(filing)
    return success(serialize.filing_json(filing))
