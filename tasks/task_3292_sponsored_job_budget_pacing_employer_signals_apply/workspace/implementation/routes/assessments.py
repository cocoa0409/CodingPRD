"""Screening assessment creation."""

from flask import Blueprint

import auth
import validations as V
from db import store
from models import assessment_view, create
from response import ok

bp = Blueprint("assessments", __name__)

QUESTION_KINDS = ("BOOLEAN", "SINGLE_CHOICE", "NUMERIC")


@bp.post("/assessments")
def create_assessment():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("Employer",))
    data = V.body()
    V.require_fields(data, ["job_posting_id", "questions", "pass_threshold"])
    posting_id = V.require_string(data, "job_posting_id")
    questions = V.require_array(data, "questions")
    threshold = V.require_int(data, "pass_threshold")

    posting = V.get("job_posting", posting_id)
    auth.require_ownership(actor_id, role, "job posting", "Employer", posting["employer_id"])

    # Tier 6: assessment shape — the array must be non-empty, each question
    # well-formed, and the threshold must not exceed the required-question count.
    from errors import ERR_UNSUPPORTED_ASSESSMENT_QUESTIONS, fail

    if len(questions) == 0:
        fail(ERR_UNSUPPORTED_ASSESSMENT_QUESTIONS,
             "An assessment must carry at least one screening question.")
    normalized = []
    for question in questions:
        if not isinstance(question, dict):
            fail(ERR_UNSUPPORTED_ASSESSMENT_QUESTIONS,
                 "Each question must be an object with prompt, kind and required.")
        prompt = question.get("prompt")
        kind = question.get("kind")
        required = question.get("required")
        if not isinstance(prompt, str) or prompt.strip() == "":
            fail(ERR_UNSUPPORTED_ASSESSMENT_QUESTIONS,
                 "Each question needs a non-empty prompt.")
        if kind not in QUESTION_KINDS:
            fail(ERR_UNSUPPORTED_ASSESSMENT_QUESTIONS,
                 "Question kind must be one of BOOLEAN, SINGLE_CHOICE, NUMERIC.")
        if not isinstance(required, bool):
            fail(ERR_UNSUPPORTED_ASSESSMENT_QUESTIONS,
                 "Each question needs a boolean required flag.")
        normalized.append({"prompt": prompt, "kind": kind, "required": required})

    if threshold < 0:
        fail(ERR_UNSUPPORTED_ASSESSMENT_QUESTIONS,
             "pass_threshold must not be negative.")
    required_count = sum(1 for question in normalized if question["required"])
    if threshold > required_count:
        fail(ERR_UNSUPPORTED_ASSESSMENT_QUESTIONS,
             "pass_threshold exceeds the number of required questions.")

    assessment = create(
        "assessments",
        job_posting_id=posting["id"],
        questions=normalized,
        pass_threshold=threshold,
        status="PUBLISHED",
    )
    return ok(assessment_view(assessment), 201)


def score_answers(assessment, answers):
    """Correctly answered required questions, per the assessment's shape.

    An answer is correct when the supplied boolean matches the question's
    requirement, or when a NUMERIC/SINGLE_CHOICE question is answered.
    """
    if answers is None:
        return 0
    if isinstance(answers, dict):
        lookup = answers
    elif isinstance(answers, list):
        lookup = {}
        for item in answers:
            if isinstance(item, dict):
                prompt = item.get("prompt")
                if prompt is not None:
                    lookup[prompt] = item.get("answer", item.get("value"))
    else:
        from errors import ERR_INVALID_REQUEST, fail
        fail(ERR_INVALID_REQUEST, "assessment_answers must be an array or object.")

    score = 0
    for index, question in enumerate(assessment["questions"]):
        if not question.get("required"):
            continue
        key = question["prompt"]
        answer = lookup.get(key)
        if answer is None:
            answer = lookup.get(index)
        if answer is None:
            continue
        if question["kind"] == "BOOLEAN":
            if answer is True or answer == "true" or answer == "True" or answer == 1:
                score += 1
        elif question["kind"] == "NUMERIC":
            if isinstance(answer, (int, float)) and not isinstance(answer, bool):
                score += 1
            elif isinstance(answer, str) and answer.strip() != "":
                score += 1
        else:  # SINGLE_CHOICE
            if isinstance(answer, str) and answer.strip() != "":
                score += 1
            elif answer is not None and not isinstance(answer, bool):
                score += 1
    return score