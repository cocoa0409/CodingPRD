"""Surveillance reviews, rating action events, compensation, look-backs, slots."""

from flask import Blueprint

from auth import authed
from db import db
import domain as dom
from errors import fail
from query import apply_filters, body, paginate
from response import created, listing, ok
from services import actions as action_service
from services import analysts as analyst_service
from services import compensation as compensation_service
from services import surveillance as surveillance_service

bp = Blueprint("surveillance", __name__)


# ---------------------------------------------------------------------------
# Surveillance reviews
# ---------------------------------------------------------------------------
@bp.route("/surveillance-reviews", methods=["POST"])
@authed("RatingAnalyst")
def create_review(actor):
    payload = body()
    entity_id = payload.get("rated_entity_id")
    if entity_id is None or entity_id not in db.rated_entities:
        fail("ERR_RESOURCE_NOT_FOUND")
    decision_id = payload.get("rating_decision_id")
    if decision_id is not None and decision_id not in db.rating_decisions:
        fail("ERR_RESOURCE_NOT_FOUND")
    row = surveillance_service.create(
        entity_id,
        decision_id,
        payload.get("review_type"),
        payload.get("review_due_at"),
    )
    return created(dom.surveillance_review(row))


@bp.route("/surveillance-reviews", methods=["GET"])
@authed("Any")
def list_reviews(actor):
    rows = apply_filters(
        list(db.surveillance_reviews.values()),
        ("rated_entity_id", "rating_decision_id", "review_status", "review_type"),
    )
    for row in rows:
        surveillance_service.refresh_on_read(row)
    window, limit, offset, total = paginate(rows)
    return listing([dom.surveillance_review(r) for r in window], limit, offset, total)


@bp.route("/surveillance-reviews/<surveillance_review_id>", methods=["GET"])
@authed("Any")
def get_review(actor, surveillance_review_id):
    row = db.surveillance_reviews.get(surveillance_review_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    surveillance_service.refresh_on_read(row)
    return ok(dom.surveillance_review(row))


@bp.route("/surveillance-reviews/<surveillance_review_id>/start", methods=["POST"])
@authed("RatingAnalyst")
def start_review(actor, surveillance_review_id):
    row = db.surveillance_reviews.get(surveillance_review_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    surveillance_service.refresh_on_read(row)
    return ok(dom.surveillance_review(surveillance_service.start(row)))


@bp.route("/surveillance-reviews/<surveillance_review_id>/complete", methods=["POST"])
@authed("RatingAnalyst")
def complete_review(actor, surveillance_review_id):
    row = db.surveillance_reviews.get(surveillance_review_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.surveillance_review(surveillance_service.complete(row)))


@bp.route("/surveillance-reviews/<surveillance_review_id>/reopen", methods=["POST"])
@authed("RatingAnalyst")
def reopen_review(actor, surveillance_review_id):
    row = db.surveillance_reviews.get(surveillance_review_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.surveillance_review(surveillance_service.reopen(row)))


# ---------------------------------------------------------------------------
# Rating action events
# ---------------------------------------------------------------------------
@bp.route("/rating-action-events", methods=["POST"])
@authed("RatingAnalyst")
def create_action_event(actor):
    payload = body()
    review_id = payload.get("surveillance_review_id")
    if review_id is None or review_id not in db.surveillance_reviews:
        fail("ERR_RESOURCE_NOT_FOUND")
    decision_id = payload.get("rating_decision_id")
    if decision_id is None or decision_id not in db.rating_decisions:
        fail("ERR_RESOURCE_NOT_FOUND")
    row = action_service.create(
        review_id,
        decision_id,
        payload.get("event_type"),
        payload.get("effective_at"),
        payload.get("target_grade"),
    )
    return created(dom.rating_action_event(row))


@bp.route("/rating-action-events", methods=["GET"])
@authed("Any")
def list_action_events(actor):
    rows = apply_filters(
        list(db.rating_action_events.values()),
        ("surveillance_review_id", "rating_decision_id", "event_status", "event_type"),
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.rating_action_event(r) for r in window], limit, offset, total)


@bp.route("/rating-action-events/<rating_action_event_id>", methods=["GET"])
@authed("Any")
def get_action_event(actor, rating_action_event_id):
    row = db.rating_action_events.get(rating_action_event_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_action_event(row))


@bp.route("/rating-action-events/<rating_action_event_id>/apply", methods=["POST"])
@authed("RatingAnalyst")
def apply_action_event(actor, rating_action_event_id):
    row = db.rating_action_events.get(rating_action_event_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_action_event(action_service.apply(row)))


@bp.route("/rating-action-events/<rating_action_event_id>/cancel", methods=["POST"])
@authed("RatingAnalyst")
def cancel_action_event(actor, rating_action_event_id):
    row = db.rating_action_events.get(rating_action_event_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.rating_action_event(action_service.cancel(row)))


# ---------------------------------------------------------------------------
# Compensation records
# ---------------------------------------------------------------------------
@bp.route("/compensation-records", methods=["POST"])
@authed("CompensationCommittee")
def create_compensation(actor):
    payload = body()
    analyst_id = payload.get("analyst_id")
    if analyst_id is None or analyst_id not in db.analysts:
        fail("ERR_RESOURCE_NOT_FOUND")
    row = compensation_service.create(
        analyst_id,
        payload.get("base_salary_cents"),
        payload.get("rating_accuracy_score"),
        payload.get("comp_period"),
    )
    return created(dom.compensation_record(row))


@bp.route("/compensation-records", methods=["GET"])
@authed("Any")
def list_compensation(actor):
    rows = apply_filters(
        list(db.compensation_records.values()), ("analyst_id", "status", "comp_period")
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.compensation_record(r) for r in window], limit, offset, total)


@bp.route("/compensation-records/<compensation_record_id>", methods=["GET"])
@authed("Any")
def get_compensation(actor, compensation_record_id):
    row = db.compensation_records.get(compensation_record_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.compensation_record(row))


@bp.route("/compensation-records/<compensation_record_id>/approve", methods=["POST"])
@authed("CompensationCommittee")
def approve_compensation(actor, compensation_record_id):
    row = db.compensation_records.get(compensation_record_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.compensation_record(compensation_service.approve(row)))


@bp.route("/compensation-records/<compensation_record_id>/pay", methods=["POST"])
@authed("CompensationCommittee")
def pay_compensation(actor, compensation_record_id):
    row = db.compensation_records.get(compensation_record_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.compensation_record(compensation_service.pay(row)))


@bp.route("/compensation-records/<compensation_record_id>/revise", methods=["POST"])
@authed("CompensationCommittee")
def revise_compensation(actor, compensation_record_id):
    row = db.compensation_records.get(compensation_record_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.compensation_record(compensation_service.revise(row)))


# ---------------------------------------------------------------------------
# Look-back reviews
# ---------------------------------------------------------------------------
@bp.route("/look-back-reviews", methods=["POST"])
@authed("ComplianceOfficer")
def create_lookback(actor):
    payload = body()
    analyst_id = payload.get("analyst_id")
    if analyst_id is None or analyst_id not in db.analysts:
        fail("ERR_RESOURCE_NOT_FOUND")
    entity_id = payload.get("departed_to_entity_id")
    if entity_id is None or entity_id not in db.rated_entities:
        fail("ERR_RESOURCE_NOT_FOUND")
    row = analyst_service.create_lookback(
        analyst_id,
        entity_id,
        payload.get("departure_date"),
        payload.get("lookback_period_months"),
    )
    return created(dom.look_back_review(row))


@bp.route("/look-back-reviews", methods=["GET"])
@authed("Any")
def list_lookbacks(actor):
    rows = apply_filters(
        list(db.look_back_reviews.values()),
        ("analyst_id", "departed_to_entity_id", "review_status"),
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.look_back_review(r) for r in window], limit, offset, total)


@bp.route("/look-back-reviews/<look_back_review_id>", methods=["GET"])
@authed("Any")
def get_lookback(actor, look_back_review_id):
    row = db.look_back_reviews.get(look_back_review_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.look_back_review(row))


@bp.route("/look-back-reviews/<look_back_review_id>/start", methods=["POST"])
@authed("ComplianceOfficer")
def start_lookback(actor, look_back_review_id):
    row = db.look_back_reviews.get(look_back_review_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.look_back_review(analyst_service.start_lookback(row)))


@bp.route("/look-back-reviews/<look_back_review_id>/close", methods=["POST"])
@authed("ComplianceOfficer")
def close_lookback(actor, look_back_review_id):
    row = db.look_back_reviews.get(look_back_review_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.look_back_review(analyst_service.close_lookback(row)))


# ---------------------------------------------------------------------------
# Review slots
# ---------------------------------------------------------------------------
@bp.route("/review-slots", methods=["POST"])
@authed("RatingAnalyst")
def create_slot(actor):
    payload = body()
    analyst_id = payload.get("analyst_id")
    if analyst_id is None or analyst_id not in db.analysts:
        fail("ERR_RESOURCE_NOT_FOUND")
    review_id = payload.get("surveillance_review_id")
    if review_id is None or review_id not in db.surveillance_reviews:
        fail("ERR_RESOURCE_NOT_FOUND")
    row = surveillance_service.create_slot(
        analyst_id, review_id, payload.get("slot_start"), payload.get("slot_end")
    )
    return created(dom.review_slot(row))


@bp.route("/review-slots", methods=["GET"])
@authed("Any")
def list_slots(actor):
    rows = apply_filters(
        list(db.review_slots.values()),
        ("analyst_id", "surveillance_review_id", "status"),
    )
    window, limit, offset, total = paginate(rows)
    return listing([dom.review_slot(r) for r in window], limit, offset, total)


@bp.route("/review-slots/<review_slot_id>", methods=["GET"])
@authed("Any")
def get_slot(actor, review_slot_id):
    row = db.review_slots.get(review_slot_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.review_slot(row))


@bp.route("/review-slots/<review_slot_id>/cancel", methods=["POST"])
@authed("RatingAnalyst")
def cancel_slot(actor, review_slot_id):
    row = db.review_slots.get(review_slot_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(dom.review_slot(surveillance_service.cancel_slot(row)))