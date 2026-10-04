"""Volunteer registry routes (PRD 3.1): register, read (lazy attestation),
self-service renewal, advocacy flag."""
from datetime import timedelta

from flask import Blueprint

import helpers
import serialize
import shape
from authz import (CHAPTER_COORDINATOR, FORUM_MODERATOR, LEAGUE_ADMIN,
                   NEUTRALITY_REVIEWER, QUESTIONNAIRE_EDITOR, check_active,
                   require_roles)
from errors import unauthorized_role
from helpers import base_entity, touch
from respond import success
from store import store

bp = Blueprint("volunteers", __name__)

CAPABILITIES = ("COORDINATOR", "EDITOR", "REVIEWER", "MODERATOR")
ATTESTATION_PERIOD = timedelta(days=90)
SELF_SERVICE_ROLES = (CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR,
                      NEUTRALITY_REVIEWER, FORUM_MODERATOR)


@bp.post("/volunteers")
def create_volunteer():
    require_roles(LEAGUE_ADMIN)
    b = shape.body()
    shape.no_extra(b, {"volunteer_name", "chapter_code", "roles",
                       "advocacy_flag"})
    volunteer_name = shape.s_str(b, "volunteer_name")
    chapter_code = shape.s_str(b, "chapter_code")
    roles = shape.s_enum_list(b, "roles", CAPABILITIES, non_empty=True)
    advocacy_flag = shape.s_bool(b, "advocacy_flag", required=False)
    volunteer = base_entity()
    volunteer.update({
        "volunteer_name": volunteer_name,
        "chapter_code": chapter_code,
        "roles": list(roles),
        "advocacy_flag": False if advocacy_flag is None else advocacy_flag,
        "attestation_expires_at": store.clock + ATTESTATION_PERIOD,
        "status": "ACTIVE",
    })
    store.volunteers[volunteer["id"]] = volunteer
    return success(serialize.volunteer_json(volunteer), status=201)


@bp.get("/volunteers/<vid>")
def read_volunteer(vid):
    require_roles(LEAGUE_ADMIN, *SELF_SERVICE_ROLES)
    return success(serialize.volunteer_json(helpers.get_volunteer(vid)))


@bp.post("/volunteers/<vid>/attest")
def attest_volunteer(vid):
    uid, role, acting = require_roles(*SELF_SERVICE_ROLES)
    b = shape.body()
    shape.no_extra(b, set())
    volunteer = helpers.get_volunteer(vid)
    if uid != volunteer["id"]:
        raise unauthorized_role("Attestation renewal is self-service only")
    # The cure path stays open to a LAPSED volunteer, but not to a
    # SUSPENDED one (band 10 has no attestation exception).
    check_active(acting)
    volunteer["attestation_expires_at"] = store.clock + ATTESTATION_PERIOD
    touch(volunteer)
    return success(serialize.volunteer_json(volunteer))


@bp.post("/volunteers/<vid>/flag-advocacy")
def flag_advocacy(vid):
    require_roles(LEAGUE_ADMIN)
    b = shape.body()
    shape.no_extra(b, {"advocacy_flag"})
    advocacy_flag = shape.s_bool(b, "advocacy_flag")
    volunteer = helpers.get_volunteer(vid)
    volunteer["advocacy_flag"] = advocacy_flag
    touch(volunteer)
    return success(serialize.volunteer_json(volunteer))
