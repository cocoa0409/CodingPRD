"""Composite preconditions.

The server starts each test against an empty store with the logical clock at its
2026-08-01T00:00:00Z default, so every precondition here is built by calling the same
public endpoints a real caller would. Setup calls go through ``get_success_data``, which
accepts any 2xx, so a fixture never hard-codes the 200-versus-201 split; the tests
themselves assert the status codes that matter.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .constants import (
    CLOSE_OUTCOME_CANCELLED,
    COVERAGE_ROLE_PRIMARY,
    DECISION_VERIFIED,
)
from .test_users import (
    make_admin_headers,
    make_coordinator_headers,
    make_liaison_headers,
    make_qc_reviewer_headers,
    make_recruiter_headers,
)
from .types import JsonObject


class Bundle(object):
    """A small attribute bag so a test can read ``bundle.student["id"]`` fluently."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __repr__(self):
        return "Bundle(%s)" % ", ".join(sorted(self.__dict__))


# ------------------------------------------------------------------- logical clock
def set_clock(client, to_iso8601: str) -> JsonObject:
    """Move the logical clock; the response reports the resulting clock as current_utc."""
    return get_success_data(client.set_clock(to_iso8601, make_admin_headers()))


# ---------------------------------------------------------------------- geography
def create_area(client, **overrides) -> JsonObject:
    return get_success_data(
        client.create_area(factories.area_payload(**overrides), make_admin_headers())
    )


def create_recruiter(client, **overrides) -> JsonObject:
    return get_success_data(
        client.create_recruiter(
            factories.recruiter_payload(**overrides), make_admin_headers()
        )
    )


def read_area(client, area_id) -> JsonObject:
    return get_success_data(client.get_area(area_id, make_admin_headers()))


def read_recruiter(client, recruiter_id) -> JsonObject:
    return get_success_data(client.get_recruiter(recruiter_id, make_admin_headers()))


def area_version(client, area_id) -> int:
    """Re-read the area to obtain the version an assignment create must echo back."""
    return read_area(client, area_id)["version"]


def create_assignment(client, recruiter_id, area_id, **overrides) -> JsonObject:
    """Place a coverage assignment, re-reading the area for the current version first."""
    version = area_version(client, area_id)
    payload = factories.assignment_payload(recruiter_id, area_id, version, **overrides)
    return get_success_data(client.create_assignment(payload, make_admin_headers()))


def cancel_assignment(client, assignment_id, reason="Recruiter reassigned.") -> JsonObject:
    return get_success_data(
        client.close_assignment(
            assignment_id,
            factories.assignment_close_payload(
                CLOSE_OUTCOME_CANCELLED, cancelled_reason=reason
            ),
            make_admin_headers(),
        )
    )


def area_and_recruiter(client, area_overrides=None, recruiter_overrides=None) -> Bundle:
    """One OPEN area and one ACTIVE recruiter -- the floor of almost every scenario."""
    area = create_area(client, **(area_overrides or {}))
    recruiter = create_recruiter(client, **(recruiter_overrides or {}))
    return Bundle(area=area, recruiter=recruiter)


# ------------------------------------------------------------------------ children
def create_student(client, recruiter_id, area_id, **overrides) -> JsonObject:
    return get_success_data(
        client.create_student(
            factories.student_payload(area_id, **overrides),
            make_recruiter_headers(recruiter_id),
        )
    )


def create_osy_student(client, recruiter_id, area_id, **overrides) -> JsonObject:
    return get_success_data(
        client.create_student(
            factories.osy_student_payload(area_id, **overrides),
            make_recruiter_headers(recruiter_id),
        )
    )


def read_student(client, student_id) -> JsonObject:
    return get_success_data(client.get_student(student_id, make_coordinator_headers()))


def student_version(client, student_id) -> int:
    """Re-read the child to obtain the version a plan create must echo back."""
    return read_student(client, student_id)["version"]


def read_assessment(client, student_id) -> JsonObject:
    return get_success_data(
        client.get_pfs_assessment(student_id, make_coordinator_headers())
    )


# ------------------------------------------------------------------ qualifying moves
def create_move(client, recruiter_id, student_id, **overrides) -> JsonObject:
    return get_success_data(
        client.create_move(
            factories.move_payload(student_id, **overrides),
            make_recruiter_headers(recruiter_id),
        )
    )


def adjudicate_move(client, move_id, decision=DECISION_VERIFIED) -> JsonObject:
    return get_success_data(
        client.adjudicate_move(
            move_id, factories.adjudicate_payload(decision), make_admin_headers()
        )
    )


def read_move(client, move_id) -> JsonObject:
    return get_success_data(client.get_move(move_id, make_admin_headers()))


def verified_move(client, recruiter_id, student_id, **overrides) -> JsonObject:
    """Record a move and carry it to VERIFIED so it counts toward priority scoring."""
    move = create_move(client, recruiter_id, student_id, **overrides)
    adjudicate_move(client, move["id"])
    return get_success_data(
        client.get_move(move["id"], make_admin_headers())
    )


# --------------------------------------------------------------- interview records
def file_interview(
    client, acting_recruiter_id, student_id, move_id, **overrides
) -> JsonObject:
    """File an INITIAL interview as ``acting_recruiter_id``.

    The acting recruiter is named separately from ``overrides`` so a test can put a
    ``recruiter_id`` key in the *body* -- which the server must ignore, because it
    "stamps `recruiter_id` from `X-User-ID`" -- without colliding with the header identity.
    """
    return get_success_data(
        client.create_interview(
            factories.interview_payload(student_id, move_id, **overrides),
            make_recruiter_headers(acting_recruiter_id),
        )
    )


def file_reinterview(
    client, acting_recruiter_id, student_id, move_id, coe_id, **overrides
) -> JsonObject:
    return get_success_data(
        client.create_interview(
            factories.reinterview_payload(student_id, move_id, coe_id, **overrides),
            make_recruiter_headers(acting_recruiter_id),
        )
    )


# ------------------------------------------------------------------- certificates
def draft_coe(client, recruiter_id, student_id, move_id, **overrides) -> JsonObject:
    return get_success_data(
        client.create_coe(
            factories.coe_payload(student_id, move_id, **overrides),
            make_recruiter_headers(recruiter_id),
        )
    )


def submit_coe(client, recruiter_id, coe_id) -> JsonObject:
    return get_success_data(
        client.submit_coe(coe_id, make_recruiter_headers(recruiter_id))
    )


def approve_coe(client, coe_id) -> JsonObject:
    return get_success_data(client.approve_coe(coe_id, make_admin_headers()))


def read_coe(client, coe_id) -> JsonObject:
    return get_success_data(client.get_coe(coe_id, make_admin_headers()))


def identified_child(client, **student_overrides) -> Bundle:
    """An area, a recruiter, a child, a VERIFIED move and its supporting interview."""
    base = area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    student = create_student(
        client, recruiter_id, base.area["id"], **student_overrides
    )
    move = verified_move(client, recruiter_id, student["id"])
    interview = file_interview(client, recruiter_id, student["id"], move["id"])
    return Bundle(
        area=base.area,
        recruiter=base.recruiter,
        student=student,
        move=move,
        interview=interview,
    )


def submitted_certificate(client, coe_overrides=None, **student_overrides) -> Bundle:
    """A child whose certificate has reached SUBMITTED, leaving them PENDING_DETERMINATION."""
    bundle = identified_child(client, **student_overrides)
    coe = draft_coe(
        client,
        bundle.recruiter["id"],
        bundle.student["id"],
        bundle.move["id"],
        **(coe_overrides or {})
    )
    submitted = submit_coe(client, bundle.recruiter["id"], coe["id"])
    bundle.coe = submitted
    return bundle


def certified_child(client, coe_overrides=None, **student_overrides) -> Bundle:
    """A child carried end to end to ELIGIBLE with one ACTIVE eligibility term."""
    bundle = submitted_certificate(
        client, coe_overrides=coe_overrides, **student_overrides
    )
    bundle.coe = approve_coe(client, bundle.coe["id"])
    terms, _ = _list(client.list_terms(make_admin_headers(), {"student_id": bundle.student["id"]}))
    bundle.term = terms[0] if terms else None
    return bundle


# --------------------------------------------------------------- quality control
def run_qc_selection(client) -> JsonObject:
    return get_success_data(client.run_qc_selection(make_admin_headers()))


def read_qc_review(client, review_id) -> JsonObject:
    return get_success_data(client.get_qc_review(review_id, make_admin_headers()))


def open_review_for(client, coe_id) -> JsonObject:
    rows, _ = _list(client.list_qc_reviews(make_admin_headers(), {"coe_id": coe_id}))
    return rows[0] if rows else None


def decide_review(client, reviewer_recruiter_id, review_id, payload) -> JsonObject:
    return get_success_data(
        client.decide_qc_review(
            review_id, payload, make_qc_reviewer_headers(reviewer_recruiter_id)
        )
    )


# ------------------------------------------------------------------------- terms
def sweep(client) -> JsonObject:
    return get_success_data(client.sweep_terms(make_admin_headers()))


def read_term(client, term_id) -> JsonObject:
    return get_success_data(client.get_term(term_id, make_admin_headers()))


def only_term_for(client, student_id) -> JsonObject:
    rows, _ = _list(client.list_terms(make_admin_headers(), {"student_id": student_id}))
    return rows[0] if rows else None


# ------------------------------------------------------------- national exchange
def open_transfer_request(client, student_id, **overrides) -> JsonObject:
    return get_success_data(
        client.create_transfer_request(
            factories.transfer_request_payload(student_id, **overrides),
            make_liaison_headers(),
        )
    )


def carry_transfer_to_received(client, request_id, matched_prior_student_id) -> JsonObject:
    """Drive a request through the matched branch and acknowledge the payload."""
    get_success_data(
        client.match_transfer_request(
            request_id,
            factories.match_payload(matched_prior_student_id),
            make_liaison_headers(),
        )
    )
    return get_success_data(
        client.receive_transfer_request(request_id, make_liaison_headers())
    )


# ----------------------------------------------------------------- service plans
def draft_plan(client, student_id, **overrides) -> JsonObject:
    version = student_version(client, student_id)
    return get_success_data(
        client.create_plan(
            factories.plan_payload(student_id, version, **overrides),
            make_coordinator_headers(),
        )
    )


def activate_plan(client, plan_id) -> JsonObject:
    return get_success_data(client.activate_plan(plan_id, make_coordinator_headers()))


def active_plan(client, student_id, **overrides) -> JsonObject:
    plan = draft_plan(client, student_id, **overrides)
    return activate_plan(client, plan["id"])


def read_plan(client, plan_id) -> JsonObject:
    return get_success_data(client.get_plan(plan_id, make_coordinator_headers()))


# ------------------------------------------------------------ delivered sessions
def post_delivery(client, plan_id, **overrides) -> JsonObject:
    return get_success_data(
        client.create_delivery(
            factories.delivery_payload(plan_id, **overrides), make_coordinator_headers()
        )
    )


def post_credit_delivery(client, plan_id, hours, credits, **overrides) -> JsonObject:
    return get_success_data(
        client.create_delivery(
            factories.credit_delivery_payload(plan_id, hours, credits, **overrides),
            make_coordinator_headers(),
        )
    )


def reverse_delivery(client, delivery_id) -> JsonObject:
    return get_success_data(
        client.reverse_delivery(delivery_id, make_coordinator_headers())
    )


def read_delivery(client, delivery_id) -> JsonObject:
    return get_success_data(client.get_delivery(delivery_id, make_coordinator_headers()))


# ------------------------------------------------------------------------ helpers
def _list(response):
    """Unwrap a list response during setup without asserting the pagination envelope."""
    body = response.json()
    assert response.status_code < 300, "setup list call failed: %s" % body
    return body.get("data", []), body.get("meta", {})


def list_rows(response):
    """Public alias of the setup list unwrapper, for preconditions built inside a test."""
    return _list(response)


PRIMARY = COVERAGE_ROLE_PRIMARY
