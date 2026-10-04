"""PolicyIncident routes (PRD 3.8): report, list, adjudicate, and the
three-link compliance cascade on substantiation."""
from flask import Blueprint

import helpers
import serialize
import shape
from authz import (CHAPTER_COORDINATOR, LEAGUE_ADMIN, check_active_current,
                   require_roles)
from errors import invalid_request, invalid_state
from helpers import base_entity, touch
from respond import listing, success
from store import store

bp = Blueprint("incidents", __name__)

INCIDENT_TYPES = ("PARTISAN_STATEMENT", "ADVOCACY_ROLE_CONFLICT",
                  "MODERATOR_BIAS", "QUESTIONNAIRE_SLANT")


@bp.post("/incidents")
def create_incident():
    uid, role, volunteer = require_roles(CHAPTER_COORDINATOR)
    b = shape.body()
    shape.no_extra(b, {"volunteer_id", "incident_type", "description"})
    volunteer_id = shape.s_str(b, "volunteer_id")
    incident_type = shape.s_enum(b, "incident_type", INCIDENT_TYPES)
    description = shape.s_str(b, "description")
    check_active_current(volunteer)
    if volunteer_id not in store.volunteers:
        raise invalid_request("Field 'volunteer_id' does not reference a Volunteer")
    incident = base_entity()
    incident.update({
        "volunteer_id": volunteer_id,
        "incident_type": incident_type,
        "description": description,
        "status": "REPORTED",
        "corrective_action": None,
        "resolved_at": None,
    })
    store.incidents[incident["id"]] = incident
    return success(serialize.incident_json(incident), status=201)


@bp.get("/volunteers/<vid>/incidents")
def list_incidents(vid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR)
    volunteer = helpers.get_volunteer(vid)
    limit, offset = shape.pagination_params()
    rows, total = helpers.page_of(
        helpers.incidents_of_volunteer(volunteer["id"]), limit, offset)
    return listing([serialize.incident_json(i) for i in rows],
                   limit, offset, total)


def _compliance_cascade(volunteer):
    """The substantiation cascade (PRD 3.8): suspend the volunteer,
    quarantine their measures, cancel their forums, revert affected
    ballot-measure contests. Candidate races are never reverted."""
    volunteer["status"] = "SUSPENDED"
    touch(volunteer)
    quarantined = []
    for measure in store.measures.values():
        if (measure["drafter_volunteer_id"] == volunteer["id"]
                and measure["status"] in ("DRAFTING", "IN_NEUTRALITY_REVIEW",
                                          "APPROVED_FOR_GUIDE")):
            measure["status"] = "REMANDED"
            touch(measure)
            quarantined.append(measure)
    for forum in store.forums.values():
        if (forum["moderator_volunteer_id"] == volunteer["id"]
                and forum["status"] in ("PLANNED", "CONFIRMED")):
            forum["status"] = "CANCELLED"
            touch(forum)
    for measure in quarantined:
        contest = store.contests.get(measure["contest_id"])
        if contest is not None and contest["status"] in ("GUIDE_READY",
                                                         "LOCKED"):
            contest["status"] = "QUESTIONNAIRE_PHASE"
            touch(contest)


@bp.post("/incidents/<iid>/transitions")
def transition_incident(iid):
    require_roles(LEAGUE_ADMIN)
    b = shape.body()
    shape.no_extra(b, {"to", "corrective_action"})
    to = shape.s_str(b, "to")
    corrective_action = shape.s_str(b, "corrective_action", required=False)
    if to == "SUBSTANTIATED" and (corrective_action is None
                                  or corrective_action == ""):
        raise invalid_request(
            "corrective_action is required when substantiating an incident")
    incident = helpers.get_incident(iid)
    if incident["status"] != "REPORTED" or to not in ("SUBSTANTIATED",
                                                      "DISMISSED"):
        raise invalid_state("Cannot move a %s incident to %s"
                            % (incident["status"], to))
    incident["status"] = to
    incident["resolved_at"] = store.clock
    if to == "SUBSTANTIATED":
        incident["corrective_action"] = corrective_action
        _compliance_cascade(store.volunteers[incident["volunteer_id"]])
    touch(incident)
    return success(serialize.incident_json(incident))
