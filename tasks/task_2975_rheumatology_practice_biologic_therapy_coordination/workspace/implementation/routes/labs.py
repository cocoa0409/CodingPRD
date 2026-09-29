"""PRD 3.6: periodic monitoring, toxicity grading and the automatic safety hold."""

from flask import Blueprint

import calculations as calc
import cascades
import constants as C
import serializers as S
from auth import acting_user_id, endpoint
from errors import fail
from response import created
from store import bump, db, stamp_new
from validation import q_enum, read_body, v_enum, v_instant, v_number, v_string

from .common import episode_or_404, paginate

bp = Blueprint("labs", __name__)


@bp.post("/monitoring-labs")
@endpoint(["InfusionNurse"])
def file_monitoring_lab():
    body = read_body()
    episode_id = v_string(body, "episode_id")
    panel_type = v_enum(body, "panel_type", C.PANEL_TYPES)
    collected_at = v_instant(body, "collected_at")
    alt_u_l = v_number(body, "alt_u_l", required=False, minimum=0, max_dp=1)
    neutrophil_k_ul = v_number(body, "neutrophil_k_ul", required=False, minimum=0, max_dp=2)
    wbc_k_ul = v_number(body, "wbc_k_ul", required=False, minimum=0, max_dp=2)

    episode = db.episodes.get(episode_id)
    if episode is None:
        fail("ERR_EPISODE_NOT_FOUND")

    alt_grade, anc_grade, abnormal_grade, triggers_hold = calc.lab_grades(
        alt_u_l, neutrophil_k_ul
    )

    row = {
        "episode_id": episode_id,
        "panel_type": panel_type,
        "collected_at": collected_at,
        "alt_u_l": alt_u_l,
        "wbc_k_ul": wbc_k_ul,
        "neutrophil_k_ul": neutrophil_k_ul,
        "alt_grade": alt_grade,
        "anc_grade": anc_grade,
        "abnormal_grade": abnormal_grade,
        "triggers_hold": triggers_hold,
        # Audit only: never resolved as a foreign key (PRD 3.6).
        "recorded_by_user_id": acting_user_id(),
    }
    stamp_new(row)
    db.monitoring_labs[row["id"]] = row

    # PRD 3.6: every filed panel refreshes the episode's monitoring_status --
    # which is derived on read -- and advances the episode's version by one.
    bump(episode)

    # A grade 3 or 4 panel interrupts an ACTIVE episode with no clinician in
    # the loop; a PLANNED, HELD or DISCONTINUED episode has nothing to stop.
    if triggers_hold and episode["therapy_state"] == "ACTIVE":
        patient = db.patients[episode["patient_id"]]
        cascades.enter_hold(episode, patient, "LAB_ABNORMALITY")

    return created(S.monitoring_lab_out(row))


@bp.get("/therapy-episodes/<episode_id>/monitoring-labs")
@endpoint(["Rheumatologist", "InfusionNurse", "RegistryAdmin", "PriorAuthCoordinator"])
def list_episode_monitoring_labs(episode_id):
    episode_or_404(episode_id)
    panel_type = q_enum("panel_type", C.PANEL_TYPES)
    rows = [
        lab
        for lab in db.monitoring_labs.values()
        if lab["episode_id"] == episode_id
        and (panel_type is None or lab["panel_type"] == panel_type)
    ]
    return paginate(rows, S.monitoring_lab_out)
