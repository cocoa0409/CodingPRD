"""Route registration. Every route, its verb, its status code and its permitted
roles come from SCAFFOLD.yaml endpoints[] / roles[] and PRD section 4."""

from flask import request

import core
import middleware as mw
import serialize
from core import ApiError
from db import STORE
from runtime import CLOCK
from services import billing, calc, certification, common, learning, leagues, placement, streak


class ListResult:
    def __init__(self, items, meta):
        self.items = items
        self.meta = meta


# ---------------------------------------------------------------- helpers


def _body():
    data = request.get_json(force=True, silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError(core.ERR_INVALID_REQUEST, "The request body must be a JSON object.")
    return data


def _q(name, default=None):
    value = request.args.get(name)
    if value is None or value == "":
        return default
    return value


def _scope(actor, learner_id):
    """Learner actors are confined to their own records."""
    if actor["role"] == "Learner":
        if learner_id is None:
            return actor["user_id"]
        if learner_id != actor["user_id"]:
            raise ApiError(core.ERR_UNAUTHORIZED)
    return learner_id


def _owned(row, actor):
    """True when the acting learner owns the row."""
    if row is None:
        return False
    if actor["role"] != "Learner":
        return True
    owner = row.get("learner_id")
    if owner is None:
        owner = row.get("id")
    return owner == actor["user_id"]


def _sorted_rows(rows, field):
    return sorted(rows, key=lambda r: r.get(field) or "")


def _page(rows, serializer, field):
    limit_raw = _q("limit")
    offset_raw = _q("offset")
    ordered = _sorted_rows(rows, field)
    page, meta = core.paginate(ordered, limit_raw, offset_raw)
    return ListResult([serializer(r) for r in page], meta)


# ---------------------------------------------------------------- learners


def post_learners(actor, body, path, query):
    learner = learning.create_learner(body)
    return serialize.learner(learner, CLOCK)


def get_learner(actor, body, path, query):
    learner = common.learner_or_404(path["id"])
    if not _owned(learner, actor):
        raise ApiError(core.ERR_UNAUTHORIZED)
    return serialize.learner(learner, CLOCK)


def patch_learner(actor, body, path, query):
    learner = learning.patch_learner(path["id"], body, actor)
    return serialize.learner(learner, CLOCK)


# ---------------------------------------------------------------- course tree


def post_course_units(actor, body, path, query):
    return serialize.unit(learning.create_unit(body))


def get_unit_nodes(actor, body, path, query):
    common.unit_or_404(path["id"])
    rows = [n for n in STORE.lesson_nodes.values() if n["unit_id"] == path["id"]]
    limit_raw = _q("limit")
    offset_raw = _q("offset")
    ordered = sorted(rows, key=lambda n: n["node_index"])
    page, meta = core.paginate(ordered, limit_raw, offset_raw)
    return ListResult([serialize.node(n) for n in page], meta)


def post_unit_nodes(actor, body, path, query):
    return serialize.node(learning.create_node(path["id"], body))


def get_lesson_nodes(actor, body, path, query):
    rows = list(STORE.lesson_nodes.values())
    unit_id = _q("unit_id")
    if unit_id is not None:
        common.unit_or_404(unit_id)
        rows = [n for n in rows if n["unit_id"] == unit_id]
    prereq = _q("prerequisite_node_id")
    if prereq is not None:
        rows = [n for n in rows if n.get("prerequisite_node_id") == prereq]
    return _page(rows, serialize.node, "created_at")


def get_lesson_node(actor, body, path, query):
    return serialize.node(common.node_or_404(path["id"]))


def post_practice(actor, body, path, query):
    attempt = learning.submit_practice(path["id"], body, actor)
    return serialize.attempt(attempt)


def put_review(actor, body, path, query):
    node = learning.review_node(path["id"], body, actor)
    return serialize.node(node)


# ---------------------------------------------------------------- attempts


def get_attempts(actor, body, path, query):
    rows = list(STORE.practice_attempts.values())
    learner_id = _q("learner_id")
    if learner_id is not None:
        common.learner_or_404(learner_id)
        if not _owned({"learner_id": learner_id}, actor):
            raise ApiError(core.ERR_UNAUTHORIZED)
        rows = [a for a in rows if a["learner_id"] == learner_id]
    elif actor["role"] == "Learner":
        rows = [a for a in rows if a["learner_id"] == actor["user_id"]]
    node_id = _q("lesson_node_id")
    if node_id is not None:
        rows = [a for a in rows if a["lesson_node_id"] == node_id]
    return _page(rows, serialize.attempt, "recorded_at")


def get_attempt(actor, body, path, query):
    row = STORE.practice_attempts.get(path["id"])
    if row is None:
        raise ApiError(core.ERR_INVALID_REQUEST, "The named practice attempt does not exist.")
    if not _owned(row, actor):
        raise ApiError(core.ERR_UNAUTHORIZED)
    return serialize.attempt(row)


# ---------------------------------------------------------------- streaks


def get_streaks(actor, body, path, query):
    learner_id = _scope(actor, _q("learner_id"))
    rows = list(STORE.streak_states.values())
    if learner_id is not None:
        rows = [s for s in rows if s["learner_id"] == learner_id]
    return _page(rows, lambda r: serialize.streak(r, CLOCK), "created_at")


def post_freezes(actor, body, path, query):
    return serialize.streak(streak.set_freezes(path["id"], body, actor), CLOCK)


def post_repair(actor, body, path, query):
    return serialize.streak(streak.repair_streak(path["id"], body, actor), CLOCK)


# ---------------------------------------------------------------- families


def get_learner_memberships(actor, body, path, query):
    common.learner_or_404(path["id"])
    if not _owned({"learner_id": path["id"]}, actor):
        raise ApiError(core.ERR_UNAUTHORIZED)
    rows = [m for m in STORE.family_memberships.values() if m["member_learner_id"] == path["id"]]
    status = _q("status")
    if status is not None:
        rows = [m for m in rows if m["status"] == status]
    return _page(rows, serialize.membership, "created_at")


def get_subscription_memberships(actor, body, path, query):
    subscription = common.subscription_or_404(path["id"])
    if not _owned(subscription, actor):
        raise ApiError(core.ERR_UNAUTHORIZED)
    rows = [m for m in STORE.family_memberships.values() if m["subscription_id"] == path["id"]]
    status = _q("status")
    if status is not None:
        rows = [m for m in rows if m["status"] == status]
    return _page(rows, serialize.membership, "created_at")


def get_memberships(actor, body, path, query):
    rows = list(STORE.family_memberships.values())
    learner_id = _q("learner_id")
    if learner_id is not None:
        common.learner_or_404(learner_id)
        if not _owned({"learner_id": learner_id}, actor):
            raise ApiError(core.ERR_UNAUTHORIZED)
        rows = [m for m in rows if m["member_learner_id"] == learner_id]
    elif actor["role"] == "Learner":
        rows = [m for m in rows if m["member_learner_id"] == actor["user_id"]]
    status = _q("status")
    if status is not None:
        rows = [m for m in rows if m["status"] == status]
    return _page(rows, serialize.membership, "created_at")


# ---------------------------------------------------------------- placements


def post_placements(actor, body, path, query):
    return serialize.placement(placement.create_placement(body, actor))


def get_placements(actor, body, path, query):
    learner_id = _scope(actor, _q("learner_id"))
    rows = list(STORE.placement_tests.values())
    if learner_id is not None:
        rows = [t for t in rows if t["learner_id"] == learner_id]
    course_id = _q("course_id")
    if course_id is not None:
        common.unit_or_404(course_id)
        rows = [t for t in rows if t["course_id"] == course_id]
    return _page(rows, serialize.placement, "created_at")


def get_placement(actor, body, path, query):
    row = STORE.placement_tests.get(path["id"])
    if row is None:
        raise ApiError(core.ERR_PLACEMENT_NOT_ACTIVE)
    if not _owned(row, actor):
        raise ApiError(core.ERR_UNAUTHORIZED)
    return serialize.placement(row)


def put_placement(actor, body, path, query):
    return serialize.placement(placement.update_placement(path["id"], body, actor))


# ---------------------------------------------------------------- subscriptions


def get_subscriptions(actor, body, path, query):
    learner_id = _scope(actor, _q("learner_id"))
    rows = list(STORE.subscriptions.values())
    if learner_id is not None:
        rows = [s for s in rows if s["learner_id"] == learner_id]
    status = _q("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return _page(rows, lambda r: serialize.subscription(r, CLOCK), "created_at")


def get_subscription(actor, body, path, query):
    subscription = common.subscription_or_404(path["id"])
    if not _owned(subscription, actor):
        raise ApiError(core.ERR_UNAUTHORIZED)
    return serialize.subscription(subscription, CLOCK)


def post_subscriptions(actor, body, path, query):
    return serialize.subscription(billing.create_subscription(body, actor), CLOCK)


def put_subscription(actor, body, path, query):
    return serialize.subscription(billing.update_subscription(path["id"], body, actor), CLOCK)


# ---------------------------------------------------------------- leagues


def post_leagues(actor, body, path, query):
    return serialize.league(leagues.create_league(body, actor))


def put_league(actor, body, path, query):
    league = leagues.update_league(path["id"], body, actor)
    return serialize.league(league)


def get_league(actor, body, path, query):
    league = STORE.leagues.get(path["id"])
    if league is None:
        raise ApiError(core.ERR_INVALID_REQUEST, "The named league does not exist.")
    return serialize.league(league)


def get_league_standings(actor, body, path, query):
    if path["id"] not in STORE.leagues:
        raise ApiError(core.ERR_INVALID_REQUEST, "The named league does not exist.")
    rows = [s for s in STORE.league_standings.values() if s["league_id"] == path["id"]]
    return _page(rows, serialize.standing, "created_at")


def get_all_league_standings(actor, body, path, query):
    if path["id"] not in STORE.leagues:
        raise ApiError(core.ERR_INVALID_REQUEST, "The named league does not exist.")
    rows = [s for s in STORE.league_standings.values() if s["league_id"] == path["id"]]
    return _page(rows, serialize.standing, "created_at")


def get_standings(actor, body, path, query):
    rows = list(STORE.league_standings.values())
    league_id = _q("league_id")
    if league_id is not None:
        rows = [s for s in rows if s["league_id"] == league_id]
    learner_id = _scope(actor, _q("learner_id"))
    if learner_id is not None:
        rows = [s for s in rows if s["learner_id"] == learner_id]
    standing_id = _q("id")
    if standing_id is not None:
        rows = [s for s in rows if s["id"] == standing_id]
    return _page(rows, serialize.standing, "created_at")


def get_standing(actor, body, path, query):
    row = STORE.league_standings.get(path["id"])
    if row is None:
        raise ApiError(core.ERR_INVALID_REQUEST, "The named league standing does not exist.")
    if not _owned(row, actor):
        raise ApiError(core.ERR_UNAUTHORIZED)
    return serialize.standing(row)


# ---------------------------------------------------------------- certification


def post_exams(actor, body, path, query):
    return serialize.exam(certification.create_exam(body, actor))


def get_exams(actor, body, path, query):
    learner_id = _scope(actor, _q("learner_id"))
    rows = list(STORE.certification_exams.values())
    if learner_id is not None:
        rows = [e for e in rows if e["learner_id"] == learner_id]
    report_id = _q("report_id")
    if report_id is not None:
        rows = [e for e in rows if e.get("report_id") == report_id]
    status = _q("status")
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    return _page(rows, serialize.exam, "created_at")


def get_exam(actor, body, path, query):
    row = STORE.certification_exams.get(path["id"])
    if row is None:
        raise ApiError(core.ERR_INVALID_REQUEST, "The named certification exam does not exist.")
    if not _owned(row, actor):
        raise ApiError(core.ERR_UNAUTHORIZED)
    return serialize.exam(row)


def put_exam(actor, body, path, query):
    return serialize.exam(certification.update_exam(path["id"], body, actor))


def post_exam_reports(actor, body, path, query):
    return serialize.report(certification.create_report(path["id"], body, actor))


def get_reports(actor, body, path, query):
    rows = list(STORE.score_reports.values())
    exam_id = _q("exam_id")
    if exam_id is not None:
        rows = [r for r in rows if r["exam_id"] == exam_id]
    learner_id = _q("learner_id")
    if learner_id is not None:
        rows = [r for r in rows if r["learner_id"] == learner_id]
    institution = _q("institution_name")
    if institution is not None:
        rows = [r for r in rows if r["institution_name"] == institution]
    report_id = _q("id")
    if report_id is not None:
        rows = [r for r in rows if r["id"] == report_id]
    return _page(rows, serialize.report, "created_at")


def get_report(actor, body, path, query):
    row = STORE.score_reports.get(path["id"])
    if row is None:
        raise ApiError(core.ERR_INVALID_REQUEST, "The named score report does not exist.")
    return serialize.report(row)


# ---------------------------------------------------------------- offers


def post_offers(actor, body, path, query):
    learner_id = core.as_str(core.get_field(body, "learner_id"), "learner_id")
    learner = common.learner_or_404(learner_id)
    milestone_code = core.enum_check(
        core.get_field(body, "milestone_code"), core.VALID_MILESTONES, "milestone_code"
    )
    return serialize.offer(calc.issue_offer(learner, milestone_code, CLOCK), CLOCK)


def get_offers(actor, body, path, query):
    learner_id = _scope(actor, _q("learner_id"))
    rows = list(STORE.engagement_offers.values())
    if learner_id is not None:
        rows = [o for o in rows if o["learner_id"] == learner_id]
    return _page(rows, lambda r: serialize.offer(r, CLOCK), "created_at")


# ---------------------------------------------------------------- system


def post_clock(actor, body, path, query):
    to_iso = core.as_str(core.get_field(body, "to_iso8601"), "to_iso8601")
    CLOCK.set(core.parse_iso8601(to_iso))
    return {}


def post_events(actor, body, path, query):
    event_type = core.as_str(core.get_field(body, "event_type"), "event_type").strip().upper()
    if event_type == "STREAK_DAY_CLOSE":
        streak.streak_day_close(CLOCK)
    elif event_type == "SKILL_DECAY":
        calc.run_skill_decay_sweep(CLOCK)
    elif event_type == "SUBSCRIPTION_RENEWAL":
        billing.subscription_renewal(CLOCK)
    elif event_type == "LEAGUE_WEEK_CLOSE":
        leagues.league_week_close(CLOCK)
    elif event_type == "LEAGUE_WEEK_OPEN":
        leagues.league_week_open(CLOCK)
    elif event_type == "OFFER_EXPIRY":
        certification.offer_expiry(CLOCK)
    elif event_type == "EXAM_EXPIRY":
        certification.exam_expiry(CLOCK)
    else:
        raise ApiError(core.ERR_INVALID_REQUEST, "Unsupported event_type.")
    return {}


def post_payment_outcome(actor, body, path, query):
    return serialize.subscription(billing.payment_outcome(body), CLOCK)


def post_inject_gems(actor, body, path, query):
    return serialize.learner(billing.inject_gems(body), CLOCK)


# ---------------------------------------------------------------- registry

ROUTES = [
    ("POST", "/learners", "POST /learners", 201, post_learners),
    ("GET", "/learners/<id>", "GET /learners/{id}", 200, get_learner),
    ("PATCH", "/learners/<id>", "PATCH /learners/{id}", 200, patch_learner),
    ("POST", "/course-units", "POST /course-units", 201, post_course_units),
    ("GET", "/course-units/<id>/nodes", "GET /course-units/{id}/nodes", 200, get_unit_nodes),
    ("POST", "/course-units/<id>/nodes", "POST /course-units/{id}/nodes", 201, post_unit_nodes),
    ("GET", "/lesson-nodes", "GET /lesson-nodes", 200, get_lesson_nodes),
    ("GET", "/lesson-nodes/<id>", "GET /lesson-nodes/{id}", 200, get_lesson_node),
    ("POST", "/lesson-nodes/<id>/practice", "POST /lesson-nodes/{id}/practice", 201, post_practice),
    ("PUT", "/lesson-nodes/<id>/review", "PUT /lesson-nodes/{id}/review", 200, put_review),
    ("GET", "/practice-attempts", "GET /practice-attempts", 200, get_attempts),
    ("GET", "/practice-attempts/<id>", "GET /practice-attempts/{id}", 200, get_attempt),
    ("GET", "/streak-states", "GET /streak-states", 200, get_streaks),
    ("POST", "/streak-states/<id>/freezes", "POST /streak-states/{id}/freezes", 200, post_freezes),
    ("POST", "/streak-states/<id>/repair", "POST /streak-states/{id}/repair", 200, post_repair),
    ("GET", "/learners/<id>/family-memberships", "GET /learners/{id}/family-memberships", 200, get_learner_memberships),
    ("GET", "/subscriptions/<id>/family-memberships", "GET /subscriptions/{id}/family-memberships", 200, get_subscription_memberships),
    ("GET", "/family-memberships", "GET /family-memberships", 200, get_memberships),
    ("POST", "/placement-tests", "POST /placement-tests", 201, post_placements),
    ("GET", "/placement-tests", "GET /placement-tests", 200, get_placements),
    ("GET", "/placement-tests/<id>", "GET /placement-tests/{id}", 200, get_placement),
    ("PUT", "/placement-tests/<id>", "PUT /placement-tests/{id}", 200, put_placement),
    ("GET", "/subscriptions", "GET /subscriptions", 200, get_subscriptions),
    ("GET", "/subscriptions/<id>", "GET /subscriptions/{id}", 200, get_subscription),
    ("POST", "/subscriptions", "POST /subscriptions", 201, post_subscriptions),
    ("PUT", "/subscriptions/<id>", "PUT /subscriptions/{id}", 200, put_subscription),
    ("POST", "/leagues", "POST /leagues", 201, post_leagues),
    ("PUT", "/leagues/<id>", "PUT /leagues/{id}", 200, put_league),
    ("GET", "/leagues/<id>", "GET /leagues/{id}", 200, get_league),
    ("GET", "/leagues/<id>/standings", "GET /leagues/{id}/standings", 200, get_league_standings),
    ("GET", "/leagues/<id>/all-standings", "GET /leagues/{id}/all-standings", 200, get_all_league_standings),
    ("GET", "/league-standings", "GET /league-standings", 200, get_standings),
    ("GET", "/league-standings/<id>", "GET /league-standings/{id}", 200, get_standing),
    ("POST", "/certification-exams", "POST /certification-exams", 201, post_exams),
    ("GET", "/certification-exams", "GET /certification-exams", 200, get_exams),
    ("GET", "/certification-exams/<id>", "GET /certification-exams/{id}", 200, get_exam),
    ("PUT", "/certification-exams/<id>", "PUT /certification-exams/{id}", 200, put_exam),
    ("POST", "/certification-exams/<id>/reports", "POST /certification-exams/{id}/reports", 201, post_exam_reports),
    ("GET", "/score-reports", "GET /score-reports", 200, get_reports),
    ("GET", "/score-reports/<id>", "GET /score-reports/{id}", 200, get_report),
    ("POST", "/engagement-offers", "POST /engagement-offers", 201, post_offers),
    ("GET", "/engagement-offers", "GET /engagement-offers", 200, get_offers),
    ("POST", "/_clock/set_current_utc", "POST /_clock/set_current_utc", 200, post_clock),
    ("POST", "/_events/auto-transition", "POST /_events/auto-transition", 200, post_events),
    ("POST", "/_inject/payment_outcome", "POST /_inject/payment_outcome", 200, post_payment_outcome),
    ("POST", "/_inject/gems", "POST /_inject/gems", 200, post_inject_gems),
]


def register(app):
    for method, path, route_key, code, handler in ROUTES:
        endpoint = route_key.replace(" ", "_").replace("/", "_").replace("{", "").replace("}", "")
        app.add_url_rule(
            path,
            endpoint=endpoint,
            view_func=_make_view(route_key, handler, code),
            methods=[method],
        )


def _make_view(route_key, handler, code):
    def view(**path_params):
        actor = mw.authenticate(route_key)
        mw.require_learner_exists(actor)
        body = _body()
        result = handler(actor, body, path_params, request.args)
        if isinstance(result, ListResult):
            return core.envelope_array(result.items, result.meta), code
        return core.envelope_object(result), code

    view.__name__ = "view_" + route_key.replace(" ", "_").replace("/", "_")
    return view