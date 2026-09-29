"""Statistical evaluations and alternate source demonstrations."""
from flask import Blueprint

import calc
import common
import derive
import envelope
import shape
import store
from errors import ApiError
from guards import authenticate, require_discipline, require_license_active
from routes_monitoring import PARAMETERS
from routes_units import CODE_RE

bp = Blueprint("stats", __name__)

EVALUATION_SPEC = {
    "program_id": {"t": "id", "req": True},
    "compliance_well_id": {"t": "id", "req": True},
    "evaluation_code": {"t": "str", "req": True, "min": 3, "max": 20,
                        "re": CODE_RE},
    "parameter_code": {"t": "enum", "req": True, "vals": PARAMETERS},
    "retest_confirmed": {"t": "bool", "default": False},
}


@bp.post("/ccr/statistical-evaluations")
def create_evaluation():
    actor = authenticate(("StatisticalReviewer",))
    data = shape.read_body(EVALUATION_SPEC)
    retest = bool(data["retest_confirmed"])
    program = common.get_program(data["program_id"])
    well = common.get_well(data["compliance_well_id"])
    unit = common.get_unit(program["unit_id"])
    common.unique_code(store.statistical_evaluations, "evaluation_code",
                       data["evaluation_code"], "program_id", program["id"])
    require_license_active(actor)
    require_discipline(actor, common.D_STATS)
    common.unit_not_care_complete(unit)
    common.program_phase(program, ("DETECTION", "ASSESSMENT"))
    if well["well_status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_WELL_STATE", "The compliance well is not CERTIFIED.")
    if not program["network_certified"]:
        raise ApiError("ERR_NETWORK_NOT_CERTIFIED",
                       "The monitoring network is not certified.")
    if (well["unit_id"] != program["unit_id"]
            or well["well_role"] != "DOWNGRADIENT"):
        raise ApiError("ERR_RESULT_WELL_NOT_IN_PROGRAM",
                       "The compliance well is not a downgradient well of the "
                       "program's unit.")
    values = calc.background_values(program, data["parameter_code"], well["id"])
    if len(values) < calc.MIN_BACKGROUND_VALUES:
        raise ApiError("ERR_INSUFFICIENT_BACKGROUND_DATA",
                       "The background window yields too few values.")
    source, comparison_value = calc.comparison_measurement(
        program, data["parameter_code"], well["id"])
    if source is None:
        raise ApiError("ERR_NO_COMPLIANCE_MEASUREMENT",
                       "No validated round after the background window carries a "
                       "measurement for this well and parameter.")
    n, upper_limit, mean, stdev = calc.background_statistical_limit(program, values)
    determined_on = store.fmt_date(store.today())
    verdict = calc.statistical_verdict(data["parameter_code"], comparison_value,
                                       upper_limit, retest)
    record = {
        "program_id": program["id"],
        "compliance_well_id": well["id"],
        "reviewing_professional_id": actor.user_id,
        "asd_certifying_professional_id": None,
        "comparison_source_event_id": source["id"],
        "evaluation_code": data["evaluation_code"],
        "parameter_code": data["parameter_code"],
        "method_used": program["statistical_method"],
        "comparison_basis_used": program["comparison_basis"],
        "background_n": n,
        "background_mean": mean,
        "background_stdev": stdev,
        "background_upper_limit": upper_limit,
        "comparison_value": comparison_value,
        "verdict": verdict,
        "retest_confirmed": retest,
        "determined_on": determined_on,
        "status": "ISSUED",
        "asd_deadline_date": calc.asd_deadline_date(verdict, determined_on),
        "asd_submitted_on": None,
        "asd_decided_on": None,
        "asd_narrative": None,
    }
    store.stamp_new(record)
    store.statistical_evaluations[record["id"]] = record
    if verdict in ("SSI", "SSL_EXCEEDANCE") and program["phase"] == "DETECTION":
        program["phase"] = "ASSESSMENT"
        program["assessment_entered_on"] = determined_on
        program["sampling_frequency"] = "QUARTERLY"
        store.touch(program)
        derive.refresh_program(program)
        unit["ssi_notice_due_date"] = store.add_days(
            determined_on, calc.SSI_NOTICE_WINDOW_DAYS)
        store.touch(unit)
    elif verdict == "SSL_EXCEEDANCE" and program["phase"] == "ASSESSMENT":
        program["phase"] = "CORRECTIVE_ACTION"
        program["corrective_action_entered_on"] = determined_on
        program["sampling_frequency"] = "QUARTERLY"
        store.touch(program)
        derive.refresh_program(program)
    common.settle(unit)
    return envelope.created(derive.evaluation(record))


ASD_SUBMISSION_SPEC = {
    "submitted_on": {"t": "date", "req": True},
    "asd_narrative": {"t": "str", "req": True, "min": 1},
    "certifying_professional_id": {"t": "id", "req": True},
}


@bp.post("/ccr/statistical-evaluations/<evaluation_id>/asd-submission")
def asd_submission(evaluation_id):
    authenticate(("ComplianceOfficer",))
    data = shape.read_body(ASD_SUBMISSION_SPEC)
    evaluation = common.get_evaluation(evaluation_id)
    program = common.get_program(evaluation["program_id"])
    unit = common.get_unit(program["unit_id"])
    common.get_body_professional(data["certifying_professional_id"])
    common.unit_not_care_complete(unit)
    if evaluation["status"] not in ("ISSUED", "ASD_REJECTED"):
        raise ApiError("ERR_INVALID_EVALUATION_STATE",
                       "The evaluation does not accept a demonstration.")
    if evaluation["verdict"] not in ("SSI", "SSL_EXCEEDANCE"):
        raise ApiError("ERR_INVALID_EVALUATION_STATE",
                       "The evaluation's verdict does not admit a demonstration.")
    common.segregation(data["certifying_professional_id"],
                       evaluation["reviewing_professional_id"])
    if (evaluation["asd_deadline_date"] is None
            or data["submitted_on"] > evaluation["asd_deadline_date"]):
        raise ApiError("ERR_ASD_WINDOW_EXPIRED",
                       "The alternate source demonstration window has expired.")
    evaluation["status"] = "ASD_UNDER_REVIEW"
    evaluation["asd_submitted_on"] = data["submitted_on"]
    evaluation["asd_narrative"] = data["asd_narrative"]
    evaluation["asd_certifying_professional_id"] = data["certifying_professional_id"]
    store.touch(evaluation)
    common.settle(unit)
    return envelope.ok(derive.evaluation(evaluation))


ASD_DECISION_SPEC = {
    "decision": {"t": "enum", "req": True, "vals": ("ACCEPT", "REJECT")},
    "decided_on": {"t": "date", "req": True},
}


@bp.post("/ccr/statistical-evaluations/<evaluation_id>/asd-decision")
def asd_decision(evaluation_id):
    authenticate(("Regulator",))
    data = shape.read_body(ASD_DECISION_SPEC)
    evaluation = common.get_evaluation(evaluation_id)
    program = common.get_program(evaluation["program_id"])
    unit = common.get_unit(program["unit_id"])
    common.unit_not_care_complete(unit)
    if evaluation["status"] != "ASD_UNDER_REVIEW":
        raise ApiError("ERR_INVALID_EVALUATION_STATE",
                       "The evaluation is not under review.")
    evaluation["asd_decided_on"] = data["decided_on"]
    if data["decision"] == "REJECT":
        evaluation["status"] = "ASD_REJECTED"
        store.touch(evaluation)
        common.settle(unit)
        return envelope.ok(derive.evaluation(evaluation))
    evaluation["status"] = "ASD_ACCEPTED"
    evaluation["verdict"] = "NO_SSI_ALTERNATE_SOURCE"
    store.touch(evaluation)
    if program["phase"] in ("ASSESSMENT", "CORRECTIVE_ACTION"):
        if program["phase"] == "CORRECTIVE_ACTION":
            program["corrective_action_entered_on"] = None
        program["phase"] = "DETECTION"
        program["sampling_frequency"] = "SEMIANNUAL"
        program["assessment_entered_on"] = None
        store.touch(program)
        derive.refresh_program(program)
        unit["ssi_notice_due_date"] = None
        store.touch(unit)
    common.settle(unit)
    return envelope.ok(derive.evaluation(evaluation))
