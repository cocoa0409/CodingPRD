"""The maintenance sweep and the logical clock."""
from datetime import timedelta

from flask import Blueprint

import calc
import clock
import db
import guards
import response
import services

bp = Blueprint("ops", __name__)


@bp.post("/citizen-science/maintenance-runs")
def maintenance_run():
    guards.authenticate(["ProgramAdmin"])
    now = clock.now()

    expired_certification_count = 0
    overdue_loan_count = 0
    exhausted_revision_count = 0
    released_publication_count = 0
    expired_grant_count = 0
    archived_campaign_count = 0

    # 1 — certifications expire
    for cert in db.all_rows(db.certifications):
        if cert["status"] == "CERTIFIED" and cert["expires_at"] is not None \
                and now >= cert["expires_at"]:
            cert["status"] = "EXPIRED"
            db.touch(cert)
            expired_certification_count += 1

    # 2 — loans fall overdue
    for loan in db.all_rows(db.loans):
        if loan["status"] == "ISSUED" and now >= loan["due_at"]:
            loan["status"] = "OVERDUE"
            db.touch(loan)
            overdue_loan_count += 1

    # 3 — exhausted revisions are cleared
    for observation in db.all_rows(db.observations):
        if observation["review_status"] == "NEEDS_REVISION" \
                and observation["revision_round"] >= calc.MAX_REVISION_ROUNDS:
            services.apply_rejection(observation)
            exhausted_revision_count += 1

    # 4 — matured embargoes release
    for publication in db.all_rows(db.publications):
        if publication["status"] == "EMBARGOED" and publication["embargo_until"] is not None \
                and now >= publication["embargo_until"]:
            services.release_publication(publication)
            released_publication_count += 1

    # 5 — grants expire
    for grant in db.all_rows(db.grants):
        if grant["status"] == "APPROVED" and now >= grant["expires_at"]:
            grant["status"] = "EXPIRED"
            grant["denied_reason"] = "GRANT_EXPIRED"
            db.touch(grant)
            partner = db.partners.get(grant["partner_id"])
            if partner is not None:
                partner["active_grant_count"] = max(0, partner["active_grant_count"] - 1)
                db.touch(partner)
            expired_grant_count += 1

    # 6 — campaigns archive
    today = now.date()
    for campaign in db.all_rows(db.campaigns):
        if campaign["status"] != "PUBLISHED":
            continue
        if campaign["_season_end"] + timedelta(days=calc.ARCHIVE_GRACE_DAYS) < today:
            campaign["status"] = "ARCHIVED"
            db.touch(campaign)
            archived_campaign_count += 1

    return response.object_response({
        "expired_certification_count": expired_certification_count,
        "overdue_loan_count": overdue_loan_count,
        "released_publication_count": released_publication_count,
        "expired_grant_count": expired_grant_count,
        "archived_campaign_count": archived_campaign_count,
        "exhausted_revision_count": exhausted_revision_count,
    })


@bp.post("/_clock/set_current_utc")
def set_clock():
    guards.authenticate(["ProgramAdmin"])
    body = guards.validate_body([
        {"name": "to_iso8601", "type": "datetime", "required": True},
    ])
    clock.set_now(body["to_iso8601"])
    return response.object_response({"current_utc": clock.now_iso()})
