"""ParentReport endpoints: filing, queue deadline and disposition cascades."""

from flask import Blueprint, request

from core import auth, clock, constants as C, envelope, store
from core.errors import fail
from services import calc, cascades, views

from .common import api, resolve

bp = Blueprint("trust", __name__)

DISPOSITION_ACTIONS = ("DISMISS", "UPHOLD_WARNING", "UPHOLD_MORE_SEVERE")


@bp.post("/outschool/class-reports")
@api(["Parent", "PlatformAdmin"])
def create_report(role, user_id):
    data = auth.body()
    for name in ("teacher_id", "class_listing_id"):
        if auth.is_blank(data.get(name)):
            fail("ERR_MISSING_REQUIRED_FIELD", "Field %r is required" % (name,))
    teacher = store.find("teachers", data["teacher_id"])
    if teacher is None:
        fail("ERR_REFERENTIAL_INTEGRITY", "The referenced teacher does not exist")
    listing = store.find("listings", data["class_listing_id"])
    if listing is None:
        fail("ERR_REFERENTIAL_INTEGRITY", "The referenced class listing does not exist")
    auth.require_fields(data, ["reported_by_user_id", "severity", "category"])
    severity = auth.require_enum(data, "severity", C.SEVERITIES)
    category = auth.require_enum(data, "category", C.CATEGORIES)

    filed = [
        r for r in store.all_of("reports")
        if r["class_listing_id"] == listing["id"]
        and r["reported_by_user_id"] == data["reported_by_user_id"]
    ]
    if len(filed) >= C.REPORT_MAX_PER_SECTION:
        fail("ERR_REPORT_WINDOW_CLOSED", "This parent has reached the report cap for the listing")

    report = store.make_record(
        "reports",
        teacher_id=teacher["id"],
        class_listing_id=listing["id"],
        reported_by_user_id=data["reported_by_user_id"],
        severity=severity,
        category=category,
        severity_weight=calc.severity_weight(category, severity),
        status="OPEN",
        disposition=None,
    )
    report["_internal"]["open_period_index"] = clock.period()
    store.touch(teacher)
    return envelope.Result(201, views.report_out(report))


@bp.get("/outschool/class-reports/<report_id>")
@api(["Parent", "PlatformAdmin"])
def get_report(role, user_id, report_id):
    report = resolve("reports", report_id, "ParentReport")
    return envelope.Result(200, views.report_out(report))


@bp.get("/outschool/class-reports")
@api(["Parent", "PlatformAdmin"])
def list_reports(role, user_id):
    items = store.by_created(store.all_of("reports"))
    for field in ("teacher_id", "class_listing_id", "status"):
        value = request.args.get(field)
        if value:
            items = [x for x in items if x.get(field) == value]
    return envelope.paged([views.report_out(x) for x in items], request.args)


@bp.post("/outschool/class-reports/<report_id>/disposition")
@api(["PlatformAdmin"])
def dispose_report(role, user_id, report_id):
    report = resolve("reports", report_id, "ParentReport")
    data = auth.body()
    action = data.get("action")
    if action is not None and action not in (
        "START_REVIEW",
        "DISMISS",
        "UPHOLD_WARNING",
        "UPHOLD_MORE_SEVERE",
    ):
        fail("ERR_INVALID_ENUM_VALUE", "action must be START_REVIEW, DISMISS, UPHOLD_WARNING or UPHOLD_MORE_SEVERE")

    if action in DISPOSITION_ACTIONS and report["status"] == "OPEN":
        opened = report["_internal"].get("open_period_index", 0)
        if clock.period() - opened > C.REPORT_SLA_PERIODS:
            fail("ERR_REPORT_SLA_EXPIRED", "The report has sat in OPEN beyond 14 periods")

    if action == "START_REVIEW":
        if report["status"] not in ("OPEN", "RESOLVED"):
            fail("ERR_INVALID_STATE", "This report may not be moved into review")
        report["status"] = "UNDER_REVIEW"
        store.touch(report)
        store.touch(store.find("teachers", report["teacher_id"]))
        return envelope.Result(200, views.report_out(report))

    if action == "DISMISS":
        if report["status"] != "UNDER_REVIEW":
            fail("ERR_INVALID_STATE", "Only a report under review may be dismissed")
        report["status"] = "RESOLVED"
        report["disposition"] = "DISMISSED"
        store.touch(report)
        return envelope.Result(200, views.report_out(report))

    if action in ("UPHOLD_WARNING", "UPHOLD_MORE_SEVERE"):
        if report["status"] != "UNDER_REVIEW":
            fail("ERR_INVALID_STATE", "Only a report under review may be upheld")
        if action == "UPHOLD_WARNING":
            report["status"] = "RESOLVED"
            report["disposition"] = "WARNING"
        else:
            report["status"] = "CLOSED"
            report["disposition"] = "MORE_SEVERE"
        store.touch(report)
        teacher = store.find("teachers", report["teacher_id"])
        if teacher is not None:
            cascades.apply_risk_cascade(teacher)
        return envelope.Result(200, views.report_out(report))

    fail("ERR_MISSING_REQUIRED_FIELD", "Field 'action' is required")
