"""Permit decisions and administrative appeals (PRD 3.8 and 3.9)."""

from flask import Blueprint

import auth
import calc
import constants as K
import derive
import envelope
from errors import ApiError
import find
import services
import store
from validate import bad, field, json_body, parse_body

bp = Blueprint("decisions", __name__)

DECISION_FIELDS = [
    field("decision_type", "enum", values=K.DECISION_TYPE),
    field("allotment_id", "str"),
    field("expected_allotment_version", "int"),
    field("nepa_level", "enum", values=K.NEPA_LEVEL),
    field("permit_id", "str", required=False, nullable=True, default=None),
    field("assessment_id", "str", required=False, nullable=True, default=None),
    field("adjustment_pct", "num", min=0, max=1, required=False, nullable=True,
          default=None),
    field("effective_date", "date", required=False, nullable=True, default=None),
    field("rationale", "str", required=False, nullable=True, default=None),
]

REVIEW_FIELDS = [field("nepa_findings_summary", "str")]

FINALIZE_FIELDS = [
    field("rationale", "str", required=False, nullable=True, default=None),
]

APPEAL_FIELDS = [
    field("appellant_permittee_id", "str"),
    field("stay_requested", "bool"),
    field("statement_of_reasons", "str", min_len=10, max_len=1000),
]

DECIDE_FIELDS = [
    field("appeal_outcome", "enum", values=K.APPEAL_OUTCOME),
    field("decision_rationale", "str", required=False, nullable=True, default=None),
]


def decision_state(message):
    raise ApiError("ERR_DECISION_STATE_INVALID", message)


def appeal_state(message):
    raise ApiError("ERR_APPEAL_STATE_INVALID", message)


def stayed(message):
    raise ApiError("ERR_DECISION_STAYED", message)


def allotment_of(decision):
    return store.get("allotments", decision["allotment_id"])


def take_effect(decision, allotment):
    """PRD 3.8: stamp the two snapshot fields, then cascade, then bump once."""
    decision["effective_date"] = store.clock_date().isoformat()
    decision["pre_decision_adjustment_pct"] = calc.pct4(
        allotment["stocking_adjustment_pct"])
    decision["decision_status"] = "EFFECTIVE"
    store.touch(decision)
    services.cascade_decision_effect(decision, allotment)
    store.touch(allotment)


def vacate(decision, allotment, run_cascade):
    decision["decision_status"] = "VACATED"
    store.touch(decision)
    if run_cascade:
        services.cascade_decision_vacatur(decision, allotment)
    store.touch(allotment)


@bp.post("/permit-decisions")
def author_decision():
    body = parse_body(json_body(), DECISION_FIELDS)
    kind = body["decision_type"]
    pct = body["adjustment_pct"]
    if kind == "STOCKING_ADJUSTMENT":
        if body["assessment_id"] is None:
            bad("assessment_id is required on a stocking adjustment")
        if pct is None:
            bad("adjustment_pct is required on a stocking adjustment")
        if pct <= 0 or pct > K.MAX_STOCKING_ADJUSTMENT_PCT:
            bad("adjustment_pct must be greater than 0 and at most 0.9")
    else:
        if body["permit_id"] is None:
            bad("permit_id is required on a %s decision" % kind)
        if pct is not None:
            bad("adjustment_pct is only permitted on a stocking adjustment")
    actor = auth.authenticate(["RangeSpecialist"])
    allotment = find.need("allotments", body["allotment_id"])
    permit = find.need_optional("permits", body["permit_id"])
    assessment = find.need_optional("assessments", body["assessment_id"])
    if body["expected_allotment_version"] != allotment["version"]:
        raise ApiError("ERR_STALE_ALLOTMENT_VERSION",
                       "the allotment has moved on since it was read")
    for other in store.rows("decisions"):
        if other["allotment_id"] == allotment["id"] \
                and other["decision_type"] == kind \
                and other["decision_status"] == "STAYED":
            stayed("a stayed decision of that type freezes this allotment")
    for other in store.rows("decisions"):
        if other["allotment_id"] == allotment["id"] \
                and other["decision_type"] == kind \
                and other["decision_status"] in ("DRAFT", "PROPOSED"):
            other["decision_status"] = "VACATED"
            store.touch(other)
    record = store.insert("decisions", {
        "allotment_id": allotment["id"],
        "permit_id": permit["id"] if permit else None,
        "assessment_id": assessment["id"] if assessment else None,
        "decision_type": kind,
        "adjustment_pct": calc.pct4(pct) if pct is not None else None,
        "pre_decision_adjustment_pct": None,
        "nepa_level": body["nepa_level"],
        "nepa_status": "PENDING",
        "nepa_findings_summary": None,
        "decision_status": "DRAFT",
        "authoring_officer_id": actor.user_id,
        "deciding_officer_id": None,
        "rationale": body["rationale"],
        "effective_date": (body["effective_date"].isoformat()
                           if body["effective_date"] else None),
    })
    store.touch(allotment)
    return envelope.created(derive.decision_json(record))


@bp.get("/permit-decisions")
def list_decisions():
    envelope.page_params()
    auth.any_operational()
    records = find.apply_filters(
        envelope.sort_default(store.rows("decisions")), [
            ("allotment_id", "allotment_id", "str"),
            ("permit_id", "permit_id", "str"),
            ("assessment_id", "assessment_id", "str"),
            ("decision_type", "decision_type", "str"),
            ("decision_status", "decision_status", "str"),
            ("nepa_status", "nepa_status", "str"),
        ])
    return envelope.paginate(records, derive.decision_json)


@bp.get("/permit-decisions/<decision_id>")
def get_decision(decision_id):
    auth.any_operational()
    record = find.need("decisions", decision_id)
    return envelope.ok(derive.decision_json(record))


@bp.post("/permit-decisions/<decision_id>/complete-environmental-review")
def complete_environmental_review(decision_id):
    body = parse_body(json_body(), REVIEW_FIELDS)
    auth.authenticate(["RangeSpecialist"])
    record = find.need("decisions", decision_id)
    if record["decision_status"] != "DRAFT" or record["nepa_status"] != "PENDING":
        decision_state("environmental review is only recorded on a DRAFT decision "
                       "whose review is still PENDING")
    record["nepa_findings_summary"] = body["nepa_findings_summary"]
    record["nepa_status"] = "COMPLETE"
    record["decision_status"] = "PROPOSED"
    store.touch(record)
    return envelope.ok(derive.decision_json(record))


@bp.post("/permit-decisions/<decision_id>/finalize")
def finalize_decision(decision_id):
    body = parse_body(json_body(), FINALIZE_FIELDS)
    actor = auth.authenticate(["AuthorizedOfficer"])
    record = find.need("decisions", decision_id)
    auth.require_segregation(actor, record["authoring_officer_id"],
                             "the signing officer may not be the author")
    if record["decision_status"] != "PROPOSED":
        decision_state("only a PROPOSED decision may be signed")
    rationale = body["rationale"]
    if rationale is None:
        rationale = record["rationale"]
    if record["nepa_status"] != "COMPLETE" \
            or not (record["nepa_findings_summary"] or "").strip():
        raise ApiError("ERR_ENVIRONMENTAL_REVIEW_INCOMPLETE",
                       "the environmental review is not complete")
    if record["nepa_level"] in K.NEPA_HEAVY_LEVELS and len(rationale or "") < 20:
        raise ApiError("ERR_ENVIRONMENTAL_REVIEW_INCOMPLETE",
                       "an EA or EIS decision requires a rationale of at least "
                       "20 characters")
    record["decision_status"] = "FINAL"
    record["deciding_officer_id"] = actor.user_id
    record["rationale"] = rationale
    store.touch(record)
    for appeal in store.rows("appeals"):
        if appeal["decision_id"] == record["id"] \
                and appeal["appeal_status"] == "REMANDED":
            appeal["appeal_status"] = "UNDER_REVIEW"
            store.touch(appeal)
    return envelope.ok(derive.decision_json(record))


@bp.post("/permit-decisions/<decision_id>/make-effective")
def make_decision_effective(decision_id):
    actor = auth.authenticate(["AuthorizedOfficer"])
    record = find.need("decisions", decision_id)
    auth.require_identity(actor, record["deciding_officer_id"],
                          "only the signing officer may put this decision "
                          "into effect")
    if record["decision_status"] == "STAYED":
        stayed("an appeal has frozen this decision")
    if record["decision_status"] != "FINAL":
        decision_state("only a FINAL decision may be put into effect")
    take_effect(record, allotment_of(record))
    return envelope.ok(derive.decision_json(record))


# ------------------------------------------------------------------- appeal cases


@bp.post("/permit-decisions/<decision_id>/appeals")
def file_appeal(decision_id):
    body = parse_body(json_body(), APPEAL_FIELDS)
    actor = auth.authenticate(["Permittee"])
    if body["appellant_permittee_id"] != actor.user_id:
        raise ApiError("ERR_UNAUTHORIZED",
                       "an appeal may only be filed in the appellant's own name")
    decision = find.need("decisions", decision_id)
    if decision["decision_status"] not in ("FINAL", "EFFECTIVE"):
        decision_state("only a FINAL or EFFECTIVE decision may be appealed")
    granted = bool(body["stay_requested"]) and decision["decision_status"] == "FINAL"
    record = store.insert("appeals", {
        "decision_id": decision["id"],
        "appellant_permittee_id": actor.user_id,
        "statement_of_reasons": body["statement_of_reasons"],
        "stay_requested": bool(body["stay_requested"]),
        "stay_granted": granted,
        "appeal_status": "FILED",
        "adjudicator_id": None,
        "appeal_outcome": None,
        "decision_rationale": None,
        "remand_count": 0,
    })
    if granted:
        decision["decision_status"] = "STAYED"
        store.touch(decision)
    return envelope.created(derive.appeal_json(record))


@bp.get("/appeal-cases")
def list_appeals():
    envelope.page_params()
    actor = auth.any_operational()
    records = envelope.sort_default(store.rows("appeals"))
    records = auth.scope_permittee_rows(
        actor, records, lambda row: row["appellant_permittee_id"])
    records = find.apply_filters(records, [
        ("decision_id", "decision_id", "str"),
        ("appellant_permittee_id", "appellant_permittee_id", "str"),
        ("appeal_status", "appeal_status", "str"),
        ("stay_granted", "stay_granted", "bool"),
    ])
    return envelope.paginate(records, derive.appeal_json)


@bp.get("/appeal-cases/<appeal_id>")
def get_appeal(appeal_id):
    actor = auth.any_operational()
    record = find.need("appeals", appeal_id)
    auth.require_own(actor, record["appellant_permittee_id"])
    return envelope.ok(derive.appeal_json(record))


@bp.post("/appeal-cases/<appeal_id>/docket")
def docket_appeal(appeal_id):
    actor = auth.authenticate(["AppealsAdjudicator"])
    record = find.need("appeals", appeal_id)
    if record["appeal_status"] != "FILED":
        appeal_state("only a FILED appeal may be docketed")
    record["appeal_status"] = "UNDER_REVIEW"
    record["adjudicator_id"] = actor.user_id
    store.touch(record)
    return envelope.ok(derive.appeal_json(record))


@bp.post("/appeal-cases/<appeal_id>/decide")
def decide_appeal(appeal_id):
    body = parse_body(json_body(), DECIDE_FIELDS)
    actor = auth.authenticate(["AppealsAdjudicator"])
    record = find.need("appeals", appeal_id)
    decision = store.get("decisions", record["decision_id"])
    auth.require_identity(actor, record["adjudicator_id"],
                          "only the docketing adjudicator may decide this appeal")
    if decision is not None:
        auth.require_segregation(actor, decision["deciding_officer_id"],
                                 "the adjudicator may not be the deciding officer")
        auth.require_segregation(actor, decision["authoring_officer_id"],
                                 "the adjudicator may not be the authoring officer")
    if record["appeal_status"] != "UNDER_REVIEW":
        appeal_state("only an appeal UNDER_REVIEW may be decided")
    outcome = body["appeal_outcome"]
    if outcome == "REMAND" and record["remand_count"] >= K.MAX_APPEAL_REMANDS:
        raise ApiError("ERR_APPEAL_REMAND_LIMIT_EXCEEDED",
                       "this appeal has already been remanded twice")
    record["appeal_outcome"] = outcome
    if body["decision_rationale"] is not None:
        record["decision_rationale"] = body["decision_rationale"]
    if outcome == "REMAND":
        record["appeal_status"] = "REMANDED"
        record["remand_count"] += 1
        store.touch(record)
        if decision is not None and decision["decision_status"] in ("FINAL",
                                                                    "STAYED"):
            decision["decision_status"] = "PROPOSED"
            decision["deciding_officer_id"] = None
            decision["rationale"] = None
            store.touch(decision)
        return envelope.ok(derive.appeal_json(record))
    record["stay_granted"] = False
    if outcome == "AFFIRM":
        record["appeal_status"] = "AFFIRMED"
    elif outcome == "DISMISS":
        record["appeal_status"] = "DISMISSED"
    else:
        record["appeal_status"] = "REVERSED"
    store.touch(record)
    if decision is None:
        return envelope.ok(derive.appeal_json(record))
    allotment = allotment_of(decision)
    if outcome in ("AFFIRM", "DISMISS"):
        if decision["decision_status"] == "STAYED" and allotment is not None:
            take_effect(decision, allotment)
    elif decision["decision_status"] == "EFFECTIVE":
        vacate(decision, allotment, True)
    elif decision["decision_status"] == "STAYED":
        vacate(decision, allotment, False)
    return envelope.ok(derive.appeal_json(record))
