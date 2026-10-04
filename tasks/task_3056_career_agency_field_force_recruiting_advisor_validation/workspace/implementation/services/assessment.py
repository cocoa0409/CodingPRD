"""Selection assessment service (§1.3 selection_assessment_weighted_score,
PRD §3.1/§3.2)."""

from db import db, ts
from errors import (
    err,
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_ASSESSMENT_INCOMPLETE_SCORES,
    ERR_INVALID_REQUEST,
)
from services import calc


def get(assessment_id):
    row = db.assessments.get(assessment_id)
    if row is None:
        raise err(ERR_ASSESSMENT_NOT_FOUND,
                  "no selection assessment with id %s" % assessment_id)
    return row


def of_candidate(candidate_id):
    return [a for a in db.assessments.values() if a["candidate_id"] == candidate_id]


def selected_assessment(candidate_id):
    """PRD §3.1: the latest by scored_date DESC, ties broken by created_at ASC,
    drawn from among the candidate's assessments currently in status SCORED.

    "Latest" is ranked by the assessment's ordinal age — the order the
    assessments were created in, which is the order they were scored in — with
    created_at as the declared tie-break.
    """
    scored = [
        (index, a) for index, a in enumerate(
            sorted(of_candidate(candidate_id),
                   key=lambda a: (a.get("created_at") or "", a.get("id") or "")))
        if a["status"] == "SCORED"
    ]
    if not scored:
        return None
    return max(scored, key=lambda pair: pair[0])[1]


def validate_competency_scores(scores):
    if not isinstance(scores, dict):
        raise err(ERR_ASSESSMENT_INCOMPLETE_SCORES,
                  "competency_scores must be a map of the four competencies")
    if set(scores.keys()) != set(calc.COMPETENCY_KEYS):
        raise err(ERR_ASSESSMENT_INCOMPLETE_SCORES,
                  "competency_scores must carry exactly MARKET_KNOWLEDGE, "
                  "RELATIONSHIP, RESILIENCE and ETHICS")
    for key in calc.COMPETENCY_KEYS:
        value = scores[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise err(ERR_INVALID_REQUEST, "competency %s must be an integer" % key)
        if value < 0 or value > 10:
            raise err(ERR_INVALID_REQUEST, "competency %s must lie between 0 and 10" % key)


def validate_raw_score(raw):
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise err(ERR_INVALID_REQUEST, "raw_score must be an integer")
    if raw < 0 or raw > 100:
        raise err(ERR_INVALID_REQUEST, "raw_score must lie between 0 and 100")


def score(assessment, raw_score, competency_scores):
    validate_raw_score(raw_score)
    validate_competency_scores(competency_scores)
    version = assessment["assessment_version"]
    value, outcome = calc.weighted_score(version, competency_scores)
    assessment["raw_score"] = raw_score
    assessment["competency_scores"] = dict(competency_scores)
    assessment["weighted_score"] = calc.f2(value)
    assessment["outcome"] = outcome
    # locked_weights: the weight table actually applied, frozen at scoring time.
    assessment["locked_weights"] = {k: float(calc.WEIGHTS[version][k])
                                    for k in calc.COMPETENCY_KEYS}
    assessment["scored_date"] = ts(db.now())
    assessment["status"] = "SCORED"
    db.touch(assessment)
    return assessment