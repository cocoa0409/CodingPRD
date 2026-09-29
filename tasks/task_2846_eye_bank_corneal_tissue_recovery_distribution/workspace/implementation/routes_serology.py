"""Serology panels: draws, invalidation cascade and result posting."""

from flask import Blueprint

import auth
import calc
import cascade
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("serology", __name__)

SPECIMEN_TYPES = ("PRE_MORTEM", "POST_MORTEM")
MARKER_VALUES = ("NON_REACTIVE", "REACTIVE", "INDETERMINATE")
RULED_OUT_FROM = ("SCREENING", "CONSENT_OBTAINED", "APPROVED_FOR_RECOVERY", "DEFERRED")


@bp.post("/eye-bank/donors/<donor_id>/serology-panels")
def draw_panel(donor_id):
    auth.authenticate(("LabTechnician",))
    donor = validate.lookup("donors", donor_id)
    body = auth.body_dict()

    specimen_type = validate.req_enum(body, "specimen_type", SPECIMEN_TYPES)
    drawn_at = validate.req_dt(body, "drawn_at")
    hemodilution_pct = validate.req_decimal(body, "hemodilution_pct", 0, 100)
    expected = validate.req_int(body, "expected_donor_version")

    if expected != donor["version"]:
        raise ApiError(
            "ERR_STALE_DONOR_VERSION",
            "expected_donor_version %s does not match %s." % (expected, donor["version"]),
        )

    row = store.base_row()
    row.update(
        {
            "donor_id": donor_id,
            "specimen_type": specimen_type,
            "drawn_at": drawn_at,
            "hemodilution_pct": hemodilution_pct,
            "status": "DRAWN",
            "hiv_result": None,
            "hbv_result": None,
            "hcv_result": None,
            "syphilis_result": None,
            "overall_result": None,
            "resulted_at": None,
            "donor_version_after": donor["version"],
            "superseded_at": None,
        }
    )

    earlier = [
        p
        for p in store.DB["serology_panels"].values()
        if p["donor_id"] == donor_id and p["status"] in ("DRAWN", "RESULTED")
    ]
    for panel in store.by_created(earlier):
        panel["status"] = "INVALIDATED"
        panel["superseded_at"] = store.now()
        store.touch(panel)

    store.DB["serology_panels"][row["id"]] = row

    donor["serology_status"] = "PENDING"
    calc.recompute_screening_risk(donor)
    store.touch(donor)
    row["donor_version_after"] = donor["version"]

    return envelope.ok(serialize.serology_panel(row), 201)


@bp.get("/eye-bank/donors/<donor_id>/serology-panels")
def list_panels(donor_id):
    auth.authenticate(("EyeBankCoordinator", "LabTechnician", "MedicalDirector"))
    validate.lookup("donors", donor_id)
    rows = [p for p in store.DB["serology_panels"].values() if p["donor_id"] == donor_id]
    rows = store.sort_desc(rows, lambda r: r["drawn_at"])
    return envelope.nested_list(rows, serialize.serology_panel)


@bp.post("/eye-bank/serology-panels/<panel_id>/results")
def post_results(panel_id):
    auth.authenticate(("LabTechnician",))
    panel = validate.lookup("serology_panels", panel_id)
    body = auth.body_dict()

    hiv = validate.req_enum(body, "hiv_result", MARKER_VALUES)
    hbv = validate.req_enum(body, "hbv_result", MARKER_VALUES)
    hcv = validate.req_enum(body, "hcv_result", MARKER_VALUES)
    syphilis = validate.req_enum(body, "syphilis_result", MARKER_VALUES)

    if panel["status"] != "DRAWN":
        raise ApiError("ERR_PANEL_STATE_INVALID", "Only a DRAWN panel accepts results.")

    overall = calc.serology_overall_result(
        (hiv, hbv, hcv, syphilis), panel["hemodilution_pct"]
    )
    panel["hiv_result"] = hiv
    panel["hbv_result"] = hbv
    panel["hcv_result"] = hcv
    panel["syphilis_result"] = syphilis
    panel["overall_result"] = overall
    panel["status"] = "RESULTED"
    panel["resulted_at"] = store.now()
    store.touch(panel)

    donor = store.DB["donors"].get(panel["donor_id"])
    if donor is not None:
        donor["serology_status"] = calc.DONOR_SEROLOGY_FROM_OVERALL[overall]
        if overall == "REACTIVE" and donor["status"] in RULED_OUT_FROM:
            donor["status"] = "RULED_OUT"
        calc.recompute_screening_risk(donor)
        store.touch(donor)
        panel["donor_version_after"] = donor["version"]

        if overall == "REACTIVE" and donor["status"] == "RECOVERED":
            if not cascade.donor_has_live_investigation(donor["id"]):
                cascade.open_lookback_investigation(donor, "POSITIVE_RETEST", None)
                panel["donor_version_after"] = donor["version"]

    return envelope.ok(serialize.serology_panel(panel))
