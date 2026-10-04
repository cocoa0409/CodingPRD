"""GuideEdition routes (PRD 3.6): assembly, snapshot pinning at READY,
distribution with the print-copy waterfall."""
from decimal import Decimal

from flask import Blueprint

import calc
import helpers
import serialize
import shape
from authz import (LEAGUE_ADMIN, QUESTIONNAIRE_EDITOR, check_active_current,
                   require_roles)
from errors import (accessibility_grade_exceeded, contests_not_locked,
                    cycle_not_open, invalid_request, invalid_state,
                    language_unsupported, neutrality_review_outstanding,
                    stale_snapshot)
from helpers import base_entity, touch
from respond import listing, success
from store import store

bp = Blueprint("editions", __name__)

LANGUAGES = ("EN", "ES", "ZH", "VI", "TL")
CHANNELS = ("PRINT", "WEB", "PARTNER")
ACCESSIBILITY_FORMATS = ("STANDARD", "LARGE_PRINT", "SCREEN_READER")

EDITION_TRANSITIONS = {
    ("ASSEMBLING", "READY"),
    ("READY", "ASSEMBLING"),
    ("DISTRIBUTED", "RETIRED"),
}

CHANNEL_REQUEST_FIELDS = {"channel_code", "requested", "priority_tier"}


@bp.post("/election-cycles/<cid>/guide-editions")
def create_edition(cid):
    uid, role, volunteer = require_roles(QUESTIONNAIRE_EDITOR)
    b = shape.body()
    shape.no_extra(b, {"language_code", "channel", "accessibility_format"})
    language_code = shape.s_enum(b, "language_code", LANGUAGES)
    channel = shape.s_enum(b, "channel", CHANNELS)
    accessibility = shape.s_enum(b, "accessibility_format",
                                 ACCESSIBILITY_FORMATS)
    cycle = helpers.get_cycle(cid)
    if cycle["status"] != "OPEN":
        raise cycle_not_open()
    check_active_current(volunteer)
    edition = base_entity()
    edition.update({
        "cycle_id": cycle["id"],
        "language_code": language_code,
        "channel": channel,
        "accessibility_format": accessibility,
        "status": "ASSEMBLING",
        "snapshot_contest_ids": [],
        "pinned_questionnaire_versions": {},
        "estimated_page_count": None,
        "print_run_total": None,
        "allocations": [],
        "unallocated_copies": None,
    })
    store.editions[edition["id"]] = edition
    return success(serialize.edition_json(edition), status=201)


@bp.get("/election-cycles/<cid>/guide-editions")
def list_editions(cid):
    require_roles(LEAGUE_ADMIN, QUESTIONNAIRE_EDITOR)
    cycle = helpers.get_cycle(cid)
    limit, offset = shape.pagination_params()
    rows, total = helpers.page_of(
        helpers.editions_of_cycle(cycle["id"]), limit, offset)
    return listing([serialize.edition_json(e) for e in rows],
                   limit, offset, total)


@bp.get("/guide-editions/<eid>")
def read_edition(eid):
    require_roles(LEAGUE_ADMIN, QUESTIONNAIRE_EDITOR)
    return success(serialize.edition_json(helpers.get_edition(eid)))


def _contest_words(contest):
    """Word total feeding the page estimate (PRD 3.6)."""
    if contest["kind"] == "CANDIDATE_RACE":
        q = helpers.questionnaire_of_contest(contest["id"])
        if q is None:
            return 0
        total = 0
        for shell in helpers.shells_of_questionnaire(q["id"]):
            if shell["status"] != "SUBMITTED":
                continue
            for answer in shell["answers"]:
                total += calc.word_count(answer["text"], "STRICT")
        return total
    measure = helpers.measure_of_contest(contest["id"])
    if measure is None:
        return 0
    total = calc.word_count(measure["explanation_text"], "STRICT")
    for a in helpers.arguments_of_measure(measure["id"]):
        if a["status"] == "ACCEPTED":
            total += a["word_count"]
    return total


def _ready_gates(edition, cycle):
    """The five READY gates in validation-ladder order (16, 33, 34, 36)."""
    contests = helpers.contests_of_cycle(cycle["id"])
    for contest in contests:
        measure = helpers.measure_of_contest(contest["id"])
        if measure is not None and measure["status"] in (
                "IN_NEUTRALITY_REVIEW", "REMANDED"):
            raise neutrality_review_outstanding()
    for jurisdiction in helpers.jurisdictions_of_cycle(cycle["id"]):
        if edition["language_code"] not in jurisdiction["supported_language_codes"]:
            raise language_unsupported()
    if edition["accessibility_format"] != "STANDARD":
        for contest in contests:
            measure = helpers.measure_of_contest(contest["id"])
            if measure is None or measure["status"] != "APPROVED_FOR_GUIDE":
                continue
            jurisdiction = helpers.jurisdiction_of_contest(contest)
            grade = (measure["grade_fk"] if jurisdiction["reading_level_metric"]
                     == "FLESCH_KINCAID" else measure["grade_smog"])
            if Decimal(repr(grade)) > calc.GRADE_THRESHOLD:
                raise accessibility_grade_exceeded()
    locked = [c for c in contests if c["status"] == "LOCKED"]
    if not locked:
        raise contests_not_locked(
            "READY requires at least one LOCKED contest of the cycle")
    return locked


@bp.post("/guide-editions/<eid>/transitions")
def transition_edition(eid):
    uid, role, volunteer = require_roles(QUESTIONNAIRE_EDITOR)
    b = shape.body()
    shape.no_extra(b, {"to"})
    to = shape.s_str(b, "to")
    edition = helpers.get_edition(eid)
    cycle = store.cycles[edition["cycle_id"]]
    if cycle["status"] != "OPEN":
        raise cycle_not_open()
    if (edition["status"], to) not in EDITION_TRANSITIONS:
        raise invalid_state("Cannot move a %s edition to %s"
                            % (edition["status"], to))
    check_active_current(volunteer)
    if to == "READY":
        locked = _ready_gates(edition, cycle)
        locked.sort(key=lambda c: (c["created_at"], c["_seq"]))
        edition["snapshot_contest_ids"] = [c["id"] for c in locked]
        pinned = {}
        for contest in locked:
            if contest["kind"] != "CANDIDATE_RACE":
                continue
            q = helpers.questionnaire_of_contest(contest["id"])
            if q is not None:
                pinned[contest["id"]] = q["version"]
        edition["pinned_questionnaire_versions"] = pinned
        edition["estimated_page_count"] = calc.guide_page_estimate(
            [_contest_words(c) for c in locked])
    elif to == "ASSEMBLING":
        # Re-opening clears the snapshot; the last estimate is retained.
        edition["snapshot_contest_ids"] = []
        edition["pinned_questionnaire_versions"] = {}
    edition["status"] = to
    touch(edition)
    return success(serialize.edition_json(edition))


@bp.post("/guide-editions/<eid>/distribute")
def distribute_edition(eid):
    uid, role, volunteer = require_roles(QUESTIONNAIRE_EDITOR)
    b = shape.body()
    shape.no_extra(b, {"print_run_total", "channel_requests"})
    print_run_total = shape.s_int(b, "print_run_total", minimum=1)
    raw_requests = shape.s_list(b, "channel_requests", non_empty=True)
    channel_requests = []
    for item in raw_requests:
        if not isinstance(item, dict):
            raise invalid_request("Each channel request must be an object")
        shape.no_extra(item, CHANNEL_REQUEST_FIELDS)
        channel_requests.append({
            "channel_code": shape.s_str(item, "channel_code"),
            "requested": shape.s_int(item, "requested", minimum=0),
            "priority_tier": shape.s_int(item, "priority_tier",
                                         minimum=1, maximum=3),
        })
    edition = helpers.get_edition(eid)
    if edition["status"] != "READY":
        raise invalid_state("Only a READY edition may be distributed")
    check_active_current(volunteer)
    for contest_id in edition["snapshot_contest_ids"]:
        contest = store.contests.get(contest_id)
        if contest is None or contest["status"] != "LOCKED":
            raise stale_snapshot()
    for contest_id, pinned_version in \
            edition["pinned_questionnaire_versions"].items():
        q = helpers.questionnaire_of_contest(contest_id)
        if q is None or q["version"] != pinned_version:
            raise stale_snapshot()
    allocations, unallocated = calc.print_copy_allocation(
        print_run_total, channel_requests)
    edition["allocations"] = allocations
    edition["unallocated_copies"] = unallocated
    edition["print_run_total"] = print_run_total
    edition["status"] = "DISTRIBUTED"
    touch(edition)
    return success(serialize.edition_json(edition))
