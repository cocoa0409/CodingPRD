"""The logical clock: the only source of 'now' anywhere in the system."""
from flask import Blueprint

import envelope
import fields
import store
from fields import T, auth, body, validate
from services import calc, cascade

bp = Blueprint("clock", __name__)

SET_CLOCK = [T("current_utc")]

SCORE_KEYS = (
    "quality_score", "timeliness_score", "satisfaction_score", "composite_score",
    "lifetime_composite_score", "rolling_event_count", "rolling_no_show_count",
    "removal_eligible",
)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(fields.ALL_ROLES)
    data = validate(body(), SET_CLOCK)
    store.set_now(data["current_utc"])

    expired = 0
    suspended = 0
    credentials = [c for c in store.all_rows("installer_credentials")
                   if c["verification_status"] == "VERIFIED"]
    credentials.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for credential in credentials:
        if credential["license_expires_on"] > store.now():
            continue
        credential["verification_status"] = "EXPIRED"
        store.touch(credential)
        expired += 1
        installer = store.get("installers", credential["installer_id"])
        if installer is None:
            continue
        installer["verified_credential_count"] = len([
            c for c in store.all_rows("installer_credentials")
            if c["installer_id"] == installer["id"] and c["verification_status"] == "VERIFIED"
        ])
        if cascade.suspend_if_unlicensed(installer):
            suspended += 1
        store.touch(installer)

    rescored = 0
    for installer in store.all_rows("installers"):
        before = tuple(installer.get(key) for key in SCORE_KEYS)
        status_before = installer["status"]
        calc.rescore(installer)
        calc.probation_transition(installer)
        after = tuple(installer.get(key) for key in SCORE_KEYS)
        if before != after or status_before != installer["status"]:
            store.touch(installer)
        rescored += 1

    return envelope.raw({
        "current_utc": store.now(),
        "credentials_expired_count": expired,
        "installers_suspended_count": suspended,
        "installers_rescored_count": rescored,
    })


@bp.get("/_clock")
def read_clock():
    auth(fields.ALL_ROLES)
    return envelope.raw({"current_utc": store.now()})
