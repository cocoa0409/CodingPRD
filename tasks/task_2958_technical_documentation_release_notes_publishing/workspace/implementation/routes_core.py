"""Logical clock, release trains, writers, reviewers."""
from flask import Blueprint

import calc
from core import (
    D,
    all_of,
    base_record,
    by_seq,
    db,
    fail,
    fmt_date,
    must_get,
    ok,
    ok_list,
    page,
    public,
    public_list,
    r2,
    touch,
)
from validate import (
    authenticate,
    body,
    filters,
    pagination,
    v_date,
    v_enum,
    v_instant,
    v_int,
    v_num,
    v_str,
)

bp = Blueprint("core_routes", __name__)

ALL_BUT_READER = ("DocsLead", "Writer", "Reviewer", "LocalizationCoordinator", "SupportAnalyst")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("DocsLead",))
    data = body()
    current_utc = v_instant(data, "current_utc")
    if current_utc < db.clock:
        fail("ERR_CLOCK_BACKWARD", "The logical clock only moves forward.")
    db.clock = current_utc
    return ok({})


# ---------------------------------------------------------------------------
# Release trains
# ---------------------------------------------------------------------------
def train_out(train):
    return public(train)


@bp.post("/release-trains")
def create_train():
    authenticate(("DocsLead",))
    data = body()
    product_key = v_str(data, "product_key", 2, 12, charset=r"^[A-Z0-9]{2,12}$")
    version_label = v_str(data, "version_label", 1, 20)
    doc_freeze_date = v_date(data, "doc_freeze_date")
    ga_date = v_date(data, "ga_date")
    support_end_date = v_date(data, "support_end_date")
    cap = v_int(data, "localization_budget_cap_cents", low=0)

    if ga_date < doc_freeze_date or support_end_date <= ga_date:
        fail("ERR_INVALID_DATE_WINDOW",
             "Freeze, general-availability and end-of-support dates are misordered.")
    for existing in db.release_trains.values():
        if (existing["product_key"] == product_key
                and existing["version_label"] == version_label):
            fail("ERR_DUPLICATE_VERSION_LABEL",
                 "This product line already has a train with that version label.")

    train = base_record()
    train.update({
        "product_key": product_key,
        "version_label": version_label,
        "doc_freeze_date": fmt_date(doc_freeze_date),
        "ga_date": fmt_date(ga_date),
        "support_end_date": fmt_date(support_end_date),
        "localization_budget_cap_cents": cap,
        "status": "PLANNED",
        "plan_item_count": 0,
        "approved_plan_item_count": 0,
        "approved_topic_ratio": r2(D(1)),
        "doc_readiness_posture": "OPEN",
        "localization_committed_cents": 0,
        "eol_notice_posted": False,
    })
    db.release_trains[train["id"]] = train
    return ok(train_out(train), 201)


@bp.get("/release-trains/<train_id>")
def get_train(train_id):
    authenticate(ALL_BUT_READER)
    train = must_get("release_trains", train_id)
    return ok(train_out(train))


@bp.get("/release-trains")
def list_trains():
    authenticate(ALL_BUT_READER)
    limit, offset = pagination()
    f = filters("product_key", "status")
    rows = all_of("release_trains")
    rows.sort(key=lambda r: r["_seq"], reverse=True)
    if f["product_key"] is not None:
        rows = [r for r in rows if r["product_key"] == f["product_key"]]
    if f["status"] is not None:
        rows = [r for r in rows if r["status"] == f["status"]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


@bp.post("/release-trains/<train_id>/advance")
def advance_train(train_id):
    authenticate(("DocsLead",))
    data = body()
    target_status = v_enum(data, "target_status", calc.TRAIN_SPINE)
    train = must_get("release_trains", train_id)

    current = train["status"]
    index = calc.TRAIN_SPINE.index(current)
    successor = calc.TRAIN_SPINE[index + 1] if index + 1 < len(calc.TRAIN_SPINE) else None
    if successor is None or target_status != successor:
        fail("ERR_RELEASE_TRAIN_INVALID_ADVANCE",
             "A release train advances only to the immediate successor of its status.")

    if target_status == "GA":
        published = [s for s in db.doc_set_versions.values()
                     if s["release_train_id"] == train["id"] and s["status"] == "PUBLISHED"]
        if not published:
            fail("ERR_DOC_SET_NOT_PUBLISHED",
                 "No documentation set of this train has been published.")
    if target_status == "END_OF_LIFE":
        from core import parse_date
        if db.today() < parse_date(train["support_end_date"]):
            fail("ERR_SUPPORT_END_DATE_NOT_REACHED",
                 "The end-of-support date has not been reached.")

    if target_status == "END_OF_LIFE":
        from flows import end_of_life_cascade
        end_of_life_cascade(train)
    else:
        train["status"] = target_status
        calc.recompute_train(train)
    touch(train)
    return ok(train_out(train))


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
@bp.post("/writers")
def create_writer():
    authenticate(("DocsLead",))
    data = body()
    person_key = v_str(data, "person_key", 3, 40)
    full_name = v_str(data, "full_name", 1, 120)
    seniority_tier = v_enum(data, "seniority_tier", ("ASSOCIATE", "SENIOR", "PRINCIPAL"))
    capacity_points = v_num(data, "capacity_points", low=0, exclusive_low=True)
    status = v_enum(data, "status", ("ACTIVE", "ON_LEAVE"), required=False) or "ACTIVE"

    for existing in db.writers.values():
        if existing["person_key"] == person_key:
            fail("ERR_DUPLICATE_PERSON_KEY", "That person key is already on the writer roster.")

    writer = base_record()
    writer.update({
        "person_key": person_key,
        "full_name": full_name,
        "seniority_tier": seniority_tier,
        "capacity_points": capacity_points,
        "status": status,
        "committed_load_points": r2(D(0)),
        "assignment_count": 0,
    })
    db.writers[writer["id"]] = writer
    return ok(public(writer), 201)


@bp.get("/writers/<writer_id>")
def get_writer(writer_id):
    authenticate(("DocsLead", "Writer"))
    writer = must_get("writers", writer_id)
    return ok(public(writer))


@bp.get("/writers")
def list_writers():
    authenticate(("DocsLead",))
    limit, offset = pagination()
    f = filters("status", "seniority_tier")
    rows = all_of("writers")
    if f["status"] is not None:
        rows = [r for r in rows if r["status"] == f["status"]]
    if f["seniority_tier"] is not None:
        rows = [r for r in rows if r["seniority_tier"] == f["seniority_tier"]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


@bp.get("/writers/<writer_id>/revisions")
def list_writer_revisions(writer_id):
    authenticate(("DocsLead", "Writer"))
    limit, offset = pagination()
    must_get("writers", writer_id)
    rows = by_seq([r for r in db.source_revisions.values()
                   if r["author_writer_id"] == writer_id])
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


# ---------------------------------------------------------------------------
# Reviewers
# ---------------------------------------------------------------------------
@bp.post("/reviewers")
def create_reviewer():
    authenticate(("DocsLead",))
    data = body()
    person_key = v_str(data, "person_key", 3, 40)
    full_name = v_str(data, "full_name", 1, 120)
    discipline = v_enum(data, "discipline", ("ENGINEERING", "PRODUCT"))

    for existing in db.reviewers.values():
        if existing["person_key"] == person_key:
            fail("ERR_DUPLICATE_PERSON_KEY", "That person key is already on the reviewer roster.")

    reviewer = base_record()
    reviewer.update({
        "person_key": person_key,
        "full_name": full_name,
        "discipline": discipline,
        "open_signoff_count": 0,
    })
    db.reviewers[reviewer["id"]] = reviewer
    return ok(public(reviewer), 201)


@bp.get("/reviewers/<reviewer_id>")
def get_reviewer(reviewer_id):
    authenticate(("DocsLead", "Reviewer"))
    reviewer = must_get("reviewers", reviewer_id)
    return ok(public(reviewer))


@bp.get("/reviewers")
def list_reviewers():
    authenticate(("DocsLead", "Reviewer"))
    limit, offset = pagination()
    f = filters("discipline")
    rows = all_of("reviewers")
    if f["discipline"] is not None:
        rows = [r for r in rows if r["discipline"] == f["discipline"]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)
