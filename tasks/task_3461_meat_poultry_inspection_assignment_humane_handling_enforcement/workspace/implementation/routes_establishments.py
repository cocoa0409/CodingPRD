"""Establishments (PRD §3.1): registration and single-read with derived scores."""
from flask import Blueprint

import calc
import store
from authz import require_roles
from envelope import get_body, success_object
from guards import establishment_or_404
from store import insert, stamp_new
from validate import SPECIES_ENUM, require_bool, require_string, require_string_array

bp = Blueprint("establishments", __name__)

ALL_ROLES = (
    "EstablishmentManager",
    "Inspector",
    "SupervisoryReviewer",
    "DistrictManager",
    "LabelOfficer",
    "RecallCoordinator",
    "ProgramAdministrator",
)


def establishment_view(establishment):
    """Attach the read-time computed fields (PRD §2.10)."""
    view = dict(establishment)
    est_id = establishment["id"]
    view["open_nr_count"] = calc.open_nr_count(est_id)
    view["suspension_count"] = calc.suspension_count(est_id)
    view["compliance_score"] = calc.compliance_score(est_id)
    view["enforcement_priority_score"] = calc.enforcement_priority_score(est_id)
    view["rolling_risk_score"] = calc.rolling_risk_score(est_id)
    view["lifetime_risk_score"] = calc.lifetime_risk_score(est_id)
    return view


@bp.post("/inspection/establishments")
def create_establishment():
    require_roles("ProgramAdministrator")
    body = get_body()
    name = require_string(body, "name")
    species_classes = require_string_array(body, "species_classes", members=SPECIES_ENUM, non_empty=True)
    slaughter_capable = require_bool(body, "slaughter_capable")

    establishment = {
        "name": name,
        "species_classes": list(species_classes),
        "slaughter_capable": slaughter_capable,
        "grant_status": "UNGRANTED",
        "inspection_status": "INACTIVE",
        "pathogen_category": None,
    }
    stamp_new(establishment)
    insert("establishments", establishment)
    return success_object(establishment_view(establishment), status=201)


@bp.get("/inspection/establishments/<est_id>")
def get_establishment(est_id):
    require_roles(*ALL_ROLES)
    establishment = establishment_or_404(est_id)
    return success_object(establishment_view(establishment))
