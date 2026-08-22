"""Musician engagements: reads and the decline cascade (CASCADE C)."""

from flask import Blueprint, request

from db import db
from domain import (created_key, engagements_of_service, recompute_readiness,
                    serialize, touch, unlock_programming)
from errors import raise_err
from middleware import endpoint, own
from response import ok, ok_list
from validate import paginate

bp = Blueprint("engagements", __name__)


def get_engagement_or_404(engagement_id):
    engagement = db.engagements.get(engagement_id)
    if engagement is None:
        raise_err("ERR_ENGAGEMENT_NOT_FOUND")
    return engagement


@bp.route("/orchestra/engagements/<engagement_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager", "Musician"])
def read_engagement(engagement_id):
    return ok(serialize(get_engagement_or_404(engagement_id)))


@bp.route("/orchestra/engagements", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager", "Musician"])
def list_engagements():
    service_id = request.args.get("service_id")
    musician_id = request.args.get("musician_id")
    status = request.args.get("status")
    records = []
    for engagement in db.engagements.values():
        if service_id is not None and engagement["service_id"] != service_id:
            continue
        if musician_id is not None and engagement["musician_id"] != musician_id:
            continue
        if status is not None and engagement["status"] != status:
            continue
        records.append(engagement)
    items, limit, offset, total = paginate(records, serialize)
    return ok_list(items, limit, offset, total)


@bp.route("/orchestra/engagements/<engagement_id>/decline", methods=["POST"])
@endpoint(["Musician"])
def decline_engagement(engagement_id):
    engagement = get_engagement_or_404(engagement_id)        # rung 3
    own(engagement["musician_id"], "Musician")               # rung 5
    if engagement["status"] != "CONFIRMED":                  # rung 7
        raise_err("ERR_ENGAGEMENT_NOT_CONFIRMED")
    service = db.services.get(engagement["service_id"])
    if service is None or service["status"] not in ("DRAFT", "PUBLISHED"):
        raise_err("ERR_SERVICE_NOT_PUBLISHED")

    # ledger discipline first: only an engagement that was actually charged
    # is refunded a service credit
    if engagement["provisional_pay_cents"] is not None:
        musician = db.musicians.get(engagement["musician_id"])
        if musician is not None:
            with touch(musician):
                musician["services_charged_ytd"] -= 1
                musician["ytd_earnings_cents"] -= engagement["provisional_pay_cents"]

    with touch(engagement):
        engagement["status"] = "DECLINED"

    understaffed = False
    with touch(service):
        # hop 1
        service["confirmed_engagement_count"] -= 1
        # hop 2
        if (service["status"] == "PUBLISHED"
                and service["confirmed_engagement_count"] < service["minimum_complement"]):
            understaffed = True
            service["compliance_status"] = "UNDERSTAFFED"
            remaining = 0
            for other in sorted(engagements_of_service(service["id"]), key=created_key):
                if other["status"] == "CONFIRMED" and other["provisional_pay_cents"] is not None:
                    remaining += other["provisional_pay_cents"]
            service["provisional_service_cost_cents"] = remaining

    concert = db.concerts.get(service["concert_id"])
    if concert is not None:
        with touch(concert):
            # hop 3
            recompute_readiness(concert)
            # hop 4
            if understaffed:
                unlock_programming(concert)

    return ok(serialize(engagement))
