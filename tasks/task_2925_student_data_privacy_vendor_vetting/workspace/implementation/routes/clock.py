"""The logical clock (PRD 2.4)."""
from flask import Blueprint

from core import auth, envelope, store, validate
from core.validate import F

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.actor("PrivacyOfficeAdmin")
    data = validate.body([F("current_utc", "instant")])
    # Setting the clock modifies no stored row and implies no sweep.
    store.set_clock(data["current_utc"])
    return envelope.ok({"current_utc": store.fmt_dt(store.clock())})
