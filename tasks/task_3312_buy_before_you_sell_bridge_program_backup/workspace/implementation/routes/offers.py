"""Backup-offer routes (PRD 3.6)."""

from flask import Blueprint

from constants import ROLES
from routes import endpoint, json_body, query_params
from services import offers
from services.lookup import get_backup_offer
from store import db

bp = Blueprint("offers", __name__)

COORDINATOR = ROLES[0]
HOMEOWNER = ROLES[2]


@bp.post("/knock/backup-offers")
@endpoint([COORDINATOR], status=201)
def draft(actor):
    return offers.create_offer(json_body(), actor)


@bp.get("/knock/backup-offers")
@endpoint([COORDINATOR])
def list_offers(actor):
    params = query_params()
    records = db.all("backup_offers")
    for field in ("departing_property_id", "bridge_program_id", "status"):
        value = params.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return db.sorted_by_created(records), params


@bp.get("/knock/backup-offers/<offer_id>")
@endpoint([COORDINATOR, HOMEOWNER])
def read(actor, offer_id):
    return get_backup_offer(offer_id)


@bp.post("/knock/backup-offers/<offer_id>/issue")
@endpoint([COORDINATOR])
def issue(actor, offer_id):
    return offers.issue_offer(offer_id, actor)


@bp.post("/knock/backup-offers/<offer_id>/extend")
@endpoint([COORDINATOR])
def extend(actor, offer_id):
    return offers.extend_offer(offer_id, actor)


@bp.post("/knock/backup-offers/<offer_id>/exercise")
@endpoint([COORDINATOR])
def exercise(actor, offer_id):
    return offers.exercise_offer(offer_id, json_body(), actor)