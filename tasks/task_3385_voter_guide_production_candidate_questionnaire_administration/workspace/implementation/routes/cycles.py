"""ElectionCycle + Jurisdiction routes (PRD 3.1, 3.9)."""
from flask import Blueprint

import helpers
import serialize
import shape
from authz import (CHAPTER_COORDINATOR, LEAGUE_ADMIN, QUESTIONNAIRE_EDITOR,
                   require_roles)
from errors import (contests_not_locked, duplicate_fips, invalid_state,
                    no_distributed_edition, unresolved_incidents_exist)
from helpers import base_entity, touch
from respond import listing, success
from store import store

bp = Blueprint("cycles", __name__)

CYCLE_TRANSITIONS = {
    ("DRAFT", "OPEN"),
    ("OPEN", "PUBLISHED"),
    ("PUBLISHED", "ARCHIVED"),
}

LANGUAGES = ("EN", "ES", "ZH", "VI", "TL")
READING_METRICS = ("FLESCH_KINCAID", "SMOG")


def _cycle_referenced_volunteers(cycle_id):
    """Volunteers referenced by the cycle's activity (PRD 3.9): measure
    drafters, measure reviewers and forum moderators under its contests."""
    referenced = set()
    for contest in helpers.contests_of_cycle(cycle_id):
        measure = helpers.measure_of_contest(contest["id"])
        if measure is not None:
            referenced.add(measure["drafter_volunteer_id"])
            for review in helpers.reviews_of_measure(measure["id"]):
                referenced.add(review["reviewer_volunteer_id"])
        for forum in helpers.forums_of_contest(contest["id"]):
            referenced.add(forum["moderator_volunteer_id"])
    return referenced


@bp.post("/election-cycles")
def create_cycle():
    require_roles(LEAGUE_ADMIN)
    b = shape.body()
    shape.no_extra(b, {"cycle_name", "election_date"})
    cycle_name = shape.s_str(b, "cycle_name")
    election_date = shape.s_date(b, "election_date")
    cycle = base_entity()
    cycle.update({
        "cycle_name": cycle_name,
        "election_date": election_date,
        "status": "DRAFT",
    })
    store.cycles[cycle["id"]] = cycle
    return success(serialize.cycle_json(cycle), status=201)


@bp.get("/election-cycles/<cid>")
def read_cycle(cid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR)
    return success(serialize.cycle_json(helpers.get_cycle(cid)))


@bp.post("/election-cycles/<cid>/transitions")
def transition_cycle(cid):
    require_roles(LEAGUE_ADMIN)
    b = shape.body()
    shape.no_extra(b, {"to"})
    to = shape.s_str(b, "to")
    cycle = helpers.get_cycle(cid)
    if (cycle["status"], to) not in CYCLE_TRANSITIONS:
        raise invalid_state("Cannot move a %s cycle to %s" % (cycle["status"], to))
    if to == "PUBLISHED":
        contests = helpers.contests_of_cycle(cycle["id"])
        if not contests or any(c["status"] != "LOCKED" for c in contests):
            raise contests_not_locked(
                "Publishing requires at least one contest and every contest LOCKED")
        referenced = _cycle_referenced_volunteers(cycle["id"])
        for incident in store.incidents.values():
            if (incident["status"] == "REPORTED"
                    and incident["volunteer_id"] in referenced):
                raise unresolved_incidents_exist()
        if serialize.distributed_edition_count(cycle) < 1:
            raise no_distributed_edition()
    cycle["status"] = to
    touch(cycle)
    return success(serialize.cycle_json(cycle))


@bp.post("/election-cycles/<cid>/jurisdictions")
def create_jurisdiction(cid):
    require_roles(LEAGUE_ADMIN)
    b = shape.body()
    shape.no_extra(b, {"jurisdiction_name", "fips_code",
                       "supported_language_codes", "reading_level_metric"})
    jurisdiction_name = shape.s_str(b, "jurisdiction_name")
    fips_code = shape.s_str(b, "fips_code")
    language_codes = shape.s_enum_list(b, "supported_language_codes",
                                       LANGUAGES, non_empty=True)
    metric = shape.s_enum(b, "reading_level_metric", READING_METRICS)
    cycle = helpers.get_cycle(cid)
    for other in helpers.jurisdictions_of_cycle(cycle["id"]):
        if other["fips_code"] == fips_code:
            raise duplicate_fips()
    jurisdiction = base_entity()
    jurisdiction.update({
        "cycle_id": cycle["id"],
        "jurisdiction_name": jurisdiction_name,
        "fips_code": fips_code,
        "supported_language_codes": list(language_codes),
        "reading_level_metric": metric,
    })
    store.jurisdictions[jurisdiction["id"]] = jurisdiction
    return success(serialize.jurisdiction_json(jurisdiction), status=201)


@bp.get("/election-cycles/<cid>/jurisdictions")
def list_jurisdictions(cid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR)
    cycle = helpers.get_cycle(cid)
    limit, offset = shape.pagination_params()
    rows, total = helpers.page_of(
        helpers.jurisdictions_of_cycle(cycle["id"]), limit, offset)
    return listing([serialize.jurisdiction_json(j) for j in rows],
                   limit, offset, total)


@bp.get("/jurisdictions/<jid>")
def read_jurisdiction(jid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR)
    return success(serialize.jurisdiction_json(helpers.get_jurisdiction(jid)))
