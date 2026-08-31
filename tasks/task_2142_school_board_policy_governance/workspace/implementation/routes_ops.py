"""Superintendent evaluation, manual publication, compliance sweep and clock."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import resp
import store
import validate as v
from errors import fail
from store import db, set_fields, touch

bp = Blueprint("ops", __name__)

EVAL_STATUSES = ["PLANNING", "GOALS_SET", "MIDYEAR_REVIEW", "SUMMATIVE_DRAFT",
                 "ADOPTED"]
ACTIONS = ["SET_GOALS", "MIDYEAR", "DRAFT_SUMMATIVE", "REOPEN", "ADOPT"]


# ---------------------------------------------------------------------------
# superintendent evaluation
# ---------------------------------------------------------------------------

@bp.post("/governance/superintendent-evaluations")
def create_evaluation():
    auth.authorize(["BoardClerk"])
    body = v.body()
    cycle_year = v.req_int(body, "cycle_year", 2020, 2100)
    window_start = v.req_dt(body, "window_start_date")
    window_end = v.req_dt(body, "window_end_date")
    midyear = v.req_dt(body, "midyear_checkpoint_date")
    goal_count = v.req_int(body, "goal_count", 1, 10)
    w_inst = v.req_number(body, "weight_instructional", 0, 1)
    w_fisc = v.req_number(body, "weight_fiscal", 0, 1)
    w_comm = v.req_number(body, "weight_community", 0, 1)
    w_gov = v.req_number(body, "weight_governance", 0, 1)

    if window_end <= window_start:
        fail("ERR_INVALID_REQUEST",
             "window_end_date must be strictly after window_start_date.")
    if not (window_start < midyear < window_end):
        fail("ERR_INVALID_REQUEST",
             "midyear_checkpoint_date must fall strictly inside the window.")

    total = (Decimal(str(w_inst)) + Decimal(str(w_fisc))
             + Decimal(str(w_comm)) + Decimal(str(w_gov)))
    if total != Decimal("1.00"):
        fail("ERR_WEIGHTS_NOT_NORMALIZED",
             "The four rubric weights must sum to exactly 1.00.")

    for e in db["evaluations"].values():
        if e["cycle_year"] == cycle_year:
            fail("ERR_DUPLICATE_EVALUATION_CYCLE",
                 "Cycle year %s already exists." % cycle_year)

    rec = store.create("evaluations", "SuperintendentEvaluation", {
        "cycle_year": cycle_year,
        "window_start_date": window_start,
        "window_end_date": window_end,
        "midyear_checkpoint_date": midyear,
        "goal_count": goal_count,
        "weight_instructional": w_inst,
        "weight_fiscal": w_fisc,
        "weight_community": w_comm,
        "weight_governance": w_gov,
        "status": "PLANNING",
        "reopen_count": 0,
        "rating_count": 0,
        "eligible_rater_count": 0,
        "midyear_formative_score": None,
        "summative_composite_score": None,
        "adopted_at": None,
    })
    return resp.created(store.serialize(rec))


@bp.get("/governance/superintendent-evaluations/<evaluation_id>")
def get_evaluation(evaluation_id):
    auth.authorize(auth.READ_ROLES_EVAL)
    rec = v.find("evaluations", evaluation_id)
    return resp.ok(store.serialize(rec))


@bp.post("/governance/superintendent-evaluations/<evaluation_id>/advance")
def advance_evaluation(evaluation_id):
    user_id, role = auth.authorize(["BoardPresident"])
    evaluation = v.find("evaluations", evaluation_id)
    body = v.body()
    action = v.req_enum(body, "action", ACTIONS)
    auth.enforce_president(user_id, role)

    status = evaluation["status"]
    expected = {
        "SET_GOALS": "PLANNING",
        "MIDYEAR": "GOALS_SET",
        "DRAFT_SUMMATIVE": "MIDYEAR_REVIEW",
        "REOPEN": "SUMMATIVE_DRAFT",
        "ADOPT": "SUMMATIVE_DRAFT",
    }[action]
    if status != expected:
        fail("ERR_EVALUATION_STAGE_INVALID",
             "Action %s is not available from status %s." % (action, status))

    if action == "SET_GOALS":
        if evaluation["goal_count"] < 1:
            fail("ERR_EVALUATION_STAGE_INVALID",
                 "At least one annual goal is required.")
        set_fields(evaluation, status="GOALS_SET")
    elif action == "MIDYEAR":
        if (evaluation["rating_count"] or 0) < 1:
            fail("ERR_NO_RATINGS_SUBMITTED", "No ratings have been submitted.")
        score = calc.midyear_formative_score(evaluation)
        if score is None:
            fail("ERR_NO_RATINGS_SUBMITTED",
                 "No eligible formative ratings were found.")
        set_fields(evaluation, status="MIDYEAR_REVIEW",
                   midyear_formative_score=score)
    elif action == "DRAFT_SUMMATIVE":
        set_fields(evaluation, status="SUMMATIVE_DRAFT")
    elif action == "REOPEN":
        set_fields(evaluation, status="GOALS_SET",
                   reopen_count=(evaluation["reopen_count"] or 0) + 1,
                   summative_composite_score=None)
    else:
        if (evaluation["rating_count"] or 0) < 1 \
                or (evaluation["eligible_rater_count"] or 0) < 1:
            fail("ERR_NO_RATINGS_SUBMITTED",
                 "No eligible ratings have been submitted.")
        score = calc.summative_composite_score(evaluation)
        if score is None:
            fail("ERR_NO_RATINGS_SUBMITTED",
                 "No eligible ratings were found for the summative composite.")
        set_fields(evaluation, status="ADOPTED",
                   summative_composite_score=score, adopted_at=store.now())

    touch(evaluation)
    return resp.ok(store.serialize(evaluation))


# ---------------------------------------------------------------------------
# evaluation ratings
# ---------------------------------------------------------------------------

@bp.post("/governance/evaluation-ratings")
def create_rating():
    user_id, role = auth.authorize(["BoardMember"])
    body = v.body()
    evaluation_id = v.req_id(body, "evaluation_id")
    member_id = v.req_id(body, "board_member_id")
    domain = v.req_enum(body, "domain", calc.DOMAINS)
    score = v.req_int(body, "score", 1, 5)
    comments = v.opt_str(body, "comments")

    evaluation = v.find("evaluations", evaluation_id)
    member = v.find("board_members", member_id)

    if member_id != user_id:
        fail("ERR_IDENTITY_MISMATCH",
             "A trustee may only submit a rating in their own name.")

    phase = "SUMMATIVE" if evaluation["status"] in ("SUMMATIVE_DRAFT", "ADOPTED") \
        else "FORMATIVE"

    for r in db["ratings"].values():
        if r["evaluation_id"] == evaluation_id \
                and r["board_member_id"] == member_id \
                and r["domain"] == domain and r["phase"] == phase:
            fail("ERR_DUPLICATE_RATING",
                 "This rubric domain has already been rated for this phase.")

    if member["status"] != "SEATED":
        fail("ERR_MEMBER_NOT_SEATED", "Only a seated trustee may submit a rating.")

    counted = (member["status"] == "SEATED"
               and member["term_end_date"] >= evaluation["window_end_date"])

    rec = store.create("ratings", "EvaluationRating", {
        "evaluation_id": evaluation_id,
        "board_member_id": member_id,
        "domain": domain,
        "score": score,
        "comments": comments,
        "submitted_at": store.now(),
        "phase": phase,
        "counted_in_summative": counted,
    })
    calc.recompute_evaluation_counters(evaluation)
    return resp.created(store.serialize(rec))


@bp.get("/governance/evaluation-ratings")
def list_ratings():
    auth.authorize(auth.READ_ROLES_EVAL)
    limit, offset = v.pagination()
    evaluation_id = v.query_str("evaluation_id")
    member_id = v.query_str("board_member_id")
    domain = v.query_enum("domain", calc.DOMAINS)
    items = store.sorted_rows("ratings")
    if evaluation_id is not None:
        items = [r for r in items if r["evaluation_id"] == evaluation_id]
    if member_id is not None:
        items = [r for r in items if r["board_member_id"] == member_id]
    if domain is not None:
        items = [r for r in items if r["domain"] == domain]
    page, total = v.paginate(items, limit, offset)
    return resp.listing([store.serialize(r) for r in page], limit, offset, total)


@bp.get("/governance/evaluation-ratings/<rating_id>")
def get_rating(rating_id):
    auth.authorize(auth.READ_ROLES_EVAL)
    rec = v.find("ratings", rating_id)
    return resp.ok(store.serialize(rec))


# ---------------------------------------------------------------------------
# manual publication
# ---------------------------------------------------------------------------

@bp.post("/governance/manual-publications")
def create_publication():
    auth.authorize(["PolicyAnalyst"])
    body = v.body()
    label = v.req_str(body, "publication_label")
    as_of = v.req_dt(body, "as_of_date")

    for p in db["publications"].values():
        if p["publication_label"] == label:
            fail("ERR_DUPLICATE_PUBLICATION_LABEL",
                 "Publication label %s already exists." % label)

    rec = store.create("publications", "ManualPublication", {
        "publication_label": label,
        "as_of_date": as_of,
        "status": "BUILDING",
        "certification_state": "PENDING",
        "pinned_entries": [],
        "entry_count": 0,
        "compliance_gap_count": 0,
        "published_at": None,
        "superseded_by_label": None,
    })
    return resp.created(store.serialize(rec))


@bp.get("/governance/manual-publications/<publication_id>")
def get_publication(publication_id):
    auth.authorize(auth.READ_ROLES_PUBLIC)
    rec = v.find("publications", publication_id)
    return resp.ok(store.serialize(rec))


@bp.post("/governance/manual-publications/<publication_id>/publish")
def publish_publication(publication_id):
    auth.authorize(["PolicyAnalyst"])
    pub = v.find("publications", publication_id)

    if pub["status"] != "BUILDING":
        fail("ERR_PUBLICATION_ALREADY_PUBLISHED",
             "Only an edition under construction may be published.")

    adopted = [p for p in db["policies"].values() if p["status"] == "ADOPTED"]
    if not adopted:
        fail("ERR_NO_ADOPTED_POLICIES", "No policy has been adopted yet.")

    calc.publication_snapshot(pub)
    return resp.ok(store.serialize(pub))


# ---------------------------------------------------------------------------
# compliance sweep
# ---------------------------------------------------------------------------

@bp.post("/governance/compliance-sweeps")
def compliance_sweep():
    auth.authorize(["BoardClerk", "LegalUpdateService"])
    now = store.now()

    mandates_marked = 0
    for m in list(db["mandates"].values()):
        if m["status"] in ("OPEN", "IN_PROGRESS") and now >= m["compliance_deadline"]:
            set_fields(m, status="OVERDUE")
            mandates_marked += 1

    waivers_expired = 0
    for w in list(db["waivers"].values()):
        if w["status"] == "GRANTED" and w.get("granted_end_date") is not None \
                and now >= w["granted_end_date"]:
            set_fields(w, status="EXPIRED")
            waivers_expired += 1
            policy = db["policies"].get(w["policy_id"])
            if policy is not None:
                calc.policy_scoped_recompute(policy)
            calc.withdraw_items_for_waiver(w)

    members_expired = 0
    for member in list(db["board_members"].values()):
        if member["status"] != "SEATED" or now < member["term_end_date"]:
            continue
        set_fields(member, status="TERM_EXPIRED")
        members_expired += 1
        affected = set()
        for a in db["assignments"].values():
            if a["board_member_id"] == member["id"] \
                    and a["status"] in ("ACTIVE", "RECUSED"):
                set_fields(a, status="REMOVED", removed_on=now)
                affected.add(a["committee_id"])
        for cid in affected:
            committee = db["committees"].get(cid)
            if committee is not None:
                calc.recompute_committee(committee)
        calc.recompute_member_counts(member)

    extra_marked, policies_recomputed = calc.sweep_scoped_recompute()
    mandates_marked += extra_marked

    publications_lapsed = 0
    for pub in db["publications"].values():
        if pub["status"] != "PUBLISHED":
            continue
        calc.recompute_publication(pub)
        if pub["certification_state"] == "LAPSED":
            publications_lapsed += 1

    return resp.ok({
        "mandates_marked_overdue": mandates_marked,
        "waivers_expired": waivers_expired,
        "members_term_expired": members_expired,
        "policies_recomputed": policies_recomputed,
        "publications_lapsed": publications_lapsed,
    })


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authorize(["BoardClerk"])
    body = v.body()
    target = v.req_dt(body, "to_iso8601")
    store.clock.set(target)
    return resp.ok({"current_utc": store.fmt_dt(store.now())})
