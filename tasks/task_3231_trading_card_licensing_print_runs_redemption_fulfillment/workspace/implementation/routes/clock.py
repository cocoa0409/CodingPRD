"""Clock-driving capability (SCAFFOLD endpoints; PRD 2.4, 3.2, 3.9).

POST /_clock/set_current_utc advances or rewinds the server's logical clock.
It writes no business field, but advancing the clock past an artwork
approval's deadline is itself the event that expires that approval.
"""

from flask import jsonify, request

import db
import requtil
import response
from core import app
from common import serialize
from constants import fmt_dt
from middleware import authenticate, require_role


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    principal = authenticate(request.headers)
    require_role(principal, ["LicensingManager", "PlatformAdmin"])

    data = requtil.body()
    target = requtil.required_dt(data, "to_iso8601")
    now = target

    store = db.STORE
    store.clock = now

    # System-driven artwork expiry: any ArtworkApproval still in SUBMITTED whose
    # submitted_on + License.approval_window_days has been passed by the new
    # clock value moves to EXPIRED.  It advances the artwork's version and
    # deliberately leaves the parent card set's status exactly as it was.
    for approval in store.all("artwork_approvals"):
        if approval["status"] != "SUBMITTED":
            continue
        lic = store.get("licenses", approval["approver_id"])
        if lic is None:
            continue
        deadline = approval["submitted_on"] + _days(lic["approval_window_days"])
        if now > deadline:
            approval["status"] = "EXPIRED"
            db.bump(approval, now)

    return jsonify(response.ok_object({"current_utc": fmt_dt(now)})), 200


def _days(count):
    import datetime

    return datetime.timedelta(days=count)


def artwork_deadline(license_rec, submitted_on):
    return submitted_on + _days(license_rec["approval_window_days"])


# Imported by the artwork route module for the same deadline computation.
def serialize_approval(rec):
    return serialize("artwork_approvals", rec)