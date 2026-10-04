"""Year-fifteen exit events: planning, option notice, ROFR window, exercise."""

from flask import Blueprint, request

import calc
import clock
import errors
import response
import state
import store
import validate

bp = Blueprint("exits", __name__)

READ_EXITS = ("Underwriter", "AssetManager", "Investor", "PlatformAdmin")
WRITE_EXITS = ("Underwriter", "AssetManager")

ACTIONS = ("ISSUE_NOTICE", "OPEN_ROFR", "EXERCISE", "DECLINE", "CLOSE")
UNDERWRITER_ONLY = ("EXERCISE", "DECLINE")
DEFAULT_ROFR_WINDOW_DAYS = 90


def _exit_price(project):
    paid = [c for c in state.calls_of_project(project["id"]) if c["status"] == "PAID"]
    shortfall = [c for c in state.calls_of_project(project["id"])
                 if c["status"] in ("DEFICIENT", "ADJUSTED")]
    return calc.exit_option_price(project, paid, shortfall)


@bp.get("/projects/<project_id>/exit-events")
def list_exit_events(project_id):
    role, user_id = validate.authenticate(request)
    validate.require_role(role, READ_EXITS)
    project = validate.get_project(project_id)
    if role == "Investor" and not validate.investor_holds_fund(user_id, project["fund_id"]):
        errors.fail(errors.ERR_FORBIDDEN_SCOPE,
                    "An Investor may read only projects of funds it subscribes to.")
    rows = store.listing(store.exits, {"project_id": project_id,
                                       "status": request.args.get("status")})
    limit, offset = response.pagination_args(request)
    window, meta = response.paginate(rows, limit, offset)
    return response.array([store.public(e) for e in window], 200, meta)


@bp.post("/projects/<project_id>/exit-events")
def create_exit_event(project_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, WRITE_EXITS)
    payload = validate.body(request)
    exit_year = validate.non_negative(validate.as_int(payload, "exit_year"), "exit_year")
    notice_date = validate.as_datetime(payload, "rofr_notice_date")
    window_days = validate.as_int(payload, "rofr_window_days", required_field=False)
    if window_days is None:
        window_days = DEFAULT_ROFR_WINDOW_DAYS
    validate.non_negative(window_days, "rofr_window_days")
    deadline = validate.as_datetime(payload, "exercise_deadline")
    if clock._parse(deadline) < clock._parse(notice_date):
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "exercise_deadline must not be before rofr_notice_date.")

    project = validate.get_project(project_id)
    if project["status"] not in ("COMPLIANCE_PERIOD", "EXIT_ELIGIBLE"):
        errors.fail(errors.ERR_EXIT_NOT_ELIGIBLE,
                    "The project is not in its compliance or exit-eligible period.")

    expires = clock.fmt(clock.add_days(clock._parse(notice_date), window_days))

    # tier 8 — ROFR windows of the same project must not overlap.
    new_start = clock._parse(notice_date)
    new_end = clock._parse(expires)
    for other in state.exits_of_project(project_id):
        if other["status"] not in ("OPTION_NOTICE_ISSUED", "ROFR_WINDOW"):
            continue
        other_start = clock._parse(other["rofr_notice_date"])
        other_end = clock._parse(other["rofr_expires_at"])
        if new_start < other_end and other_start < new_end:
            errors.fail(errors.ERR_ROFR_WINDOW_OVERLAP,
                        "An open right-of-first-refusal window already overlaps this one.")

    price, cumulative = _exit_price(project)
    event = store.create(store.exits, {
        "project_id": project["id"],
        "exit_year": exit_year,
        "rofr_notice_date": notice_date,
        "rofr_window_days": window_days,
        "exercise_deadline": deadline,
        "option_price_cents": price,
        "rofr_expires_at": expires,
        "cumulative_distributions_cents": cumulative,
        "status": "PENDING",
    })
    return response.ok(store.public(event), 201)


@bp.post("/exit-events/<exit_event_id>/exercise")
def exercise_exit(exit_event_id):
    role, _ = validate.authenticate(request)
    validate.require_role(role, WRITE_EXITS)
    payload = validate.body(request)
    action = validate.as_string(payload, "action").strip().upper()
    if action not in ACTIONS:
        errors.fail(errors.ERR_INVALID_REQUEST, "action must be one of %s." % ", ".join(ACTIONS))
    if action in UNDERWRITER_ONLY and role != "Underwriter":
        errors.fail(errors.ERR_FORBIDDEN, "Only an Underwriter may exercise or decline the option.")

    event = validate.get_exit_event(exit_event_id)
    project = validate.get_project(event["project_id"])
    fund = validate.get_fund(project["fund_id"])
    developer = validate.get_developer(project["developer_id"])
    status = event["status"]

    if action == "ISSUE_NOTICE":
        if status != "PENDING":
            errors.fail(errors.ERR_EXIT_EVENT_NOT_PENDING,
                        "An option notice may only issue from PENDING.")
        if project["status"] not in ("COMPLIANCE_PERIOD", "EXIT_ELIGIBLE"):
            errors.fail(errors.ERR_EXIT_NOT_ELIGIBLE,
                        "The project is not in its compliance or exit-eligible period.")
        if clock._parse(event["exercise_deadline"]) < clock._parse(event["rofr_notice_date"]):
            errors.fail(errors.ERR_EXIT_WINDOW_INVERTED,
                        "exercise_deadline is before rofr_notice_date.")
        expires = clock.fmt(clock.add_days(clock._parse(event["rofr_notice_date"]),
                                           int(event["rofr_window_days"])))
        if clock._parse(expires) > clock._parse(event["exercise_deadline"]):
            errors.fail(errors.ERR_EXIT_WINDOW_INVERTED,
                        "rofr_expires_at falls after exercise_deadline.")
        price, cumulative = _exit_price(project)
        event["rofr_expires_at"] = expires
        event["option_price_cents"] = price
        event["cumulative_distributions_cents"] = cumulative
        event["status"] = "OPTION_NOTICE_ISSUED"
        store.touch(event)
        return response.ok(store.public(event), 200)

    if action == "OPEN_ROFR":
        if status != "OPTION_NOTICE_ISSUED":
            errors.fail(errors.ERR_EXIT_EVENT_NOT_PENDING,
                        "The ROFR window may only open from OPTION_NOTICE_ISSUED.")
        new_start = clock._parse(event["rofr_notice_date"])
        new_end = clock._parse(event["rofr_expires_at"])
        for other in state.exits_of_project(project["id"]):
            if other["id"] == event["id"] or other["status"] != "ROFR_WINDOW":
                continue
            other_start = clock._parse(other["rofr_notice_date"])
            other_end = clock._parse(other["rofr_expires_at"])
            if new_start < other_end and other_start < new_end:
                errors.fail(errors.ERR_ROFR_WINDOW_OVERLAP,
                            "An open right-of-first-refusal window already overlaps this one.")
        event["status"] = "ROFR_WINDOW"
        store.touch(event)
        return response.ok(store.public(event), 200)

    if action == "EXERCISE":
        if status != "ROFR_WINDOW":
            errors.fail(errors.ERR_EXIT_EVENT_NOT_PENDING,
                        "The option may only be exercised from ROFR_WINDOW.")
        state.recompute_developer(developer["id"])
        if developer["status"] != "ELIGIBLE" or state.developer_distressed_count(developer["id"]) >= 1:
            errors.fail(errors.ERR_DEVELOPER_NOT_ELIGIBLE_FOR_EXIT,
                        "The developer is not eligible to exercise the option.")
        if clock.now() > clock._parse(event["rofr_expires_at"]):
            errors.fail(errors.ERR_ROFR_WINDOW_EXPIRED,
                        "The right-of-first-refusal window has expired.")
        price, cumulative = _exit_price(project)
        event["option_price_cents"] = price
        event["cumulative_distributions_cents"] = cumulative
        event["status"] = "EXERCISED"
        store.touch(event)
        return response.ok(store.public(event), 200)

    if action == "DECLINE":
        if status not in ("OPTION_NOTICE_ISSUED", "ROFR_WINDOW"):
            errors.fail(errors.ERR_EXIT_EVENT_NOT_PENDING,
                        "The option may only be declined from an open notice.")
        event["status"] = "DECLINED"
        store.touch(event)
        if project["status"] in ("EXIT_ELIGIBLE", "COMPLIANCE_PERIOD"):
            project["status"] = "COMPLIANCE_PERIOD"
            store.touch(project)
        state.recompute_project(project["id"])
        state.recompute_fund(fund["id"])
        state.recompute_developer(developer["id"])
        return response.ok(store.public(event), 200)

    # CLOSE
    if status not in ("EXERCISED", "DECLINED"):
        errors.fail(errors.ERR_EXIT_EVENT_NOT_PENDING,
                    "An exit event may only be closed from EXERCISED or DECLINED.")
    event["status"] = "CLOSED"
    store.touch(event)
    if status == "EXERCISED":
        project["status"] = "EXITED"
        project.pop("_pre_distress_status", None)
        store.touch(project)
        for guarantee in state.guarantees_of_project(project["id"]):
            if guarantee["status"] in ("ACTIVE", "DRAWN", "DISCHARGED"):
                guarantee["status"] = "RELEASED"
                store.touch(guarantee)
    state.recompute_project(project["id"])
    state.recompute_fund(fund["id"])
    state.recompute_developer(developer["id"])
    return response.ok(store.public(event), 200)
