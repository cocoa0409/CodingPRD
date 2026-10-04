"""Test-driving routes: the logical clock, payment settlement and citations.

PRD §2.7 and §3.14: these are mounted at the server root rather than under the
`/car-share` prefix and are reserved to PlatformAdmin (except citation
validation, which PodOperator may also call).
"""

from flask import Blueprint

import middleware as mw
from response import ok, created
from services import accounts as svc

bp = Blueprint("testing", __name__)


def register(app):
    app.register_blueprint(bp)


@bp.post("/_clock/set_current_utc")
def set_clock():
    mw.authenticate(("PlatformAdmin",))
    data = mw.body()
    svc.set_clock(data, mw)
    return ok({})


@bp.post("/_payments/simulate")
def simulate_payment():
    mw.authenticate(("PlatformAdmin",))
    data = mw.body()
    svc.simulate_payment(data, mw)
    return ok({})


@bp.post("/_citations/issue")
def issue_citation():
    mw.authenticate(("PlatformAdmin",))
    data = mw.body()
    row = svc.issue_citation(data, mw)
    return created({}, response_type="object")


@bp.post("/car-share/citations/<citation_id>/validate-signature")
def validate_signature(citation_id):
    mw.authenticate(("PodOperator", "PlatformAdmin"))
    data = mw.body()
    svc.validate_signature(citation_id, data, mw)
    return ok({})