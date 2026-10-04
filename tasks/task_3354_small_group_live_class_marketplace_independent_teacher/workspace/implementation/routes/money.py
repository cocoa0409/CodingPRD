"""TeacherPayout endpoints: accrual, per-section fees and the settlement pipeline."""

from flask import Blueprint, request

from core import auth, clock, constants as C, envelope, store
from core.errors import fail
from services import calc, views

from .common import api, resolve

bp = Blueprint("money", __name__)

ACTIONS = ("SEND", "PAY", "APPROVE", "VOID")


@bp.post("/outschool/teachers/<teacher_id>/payouts")
@api(["Teacher", "PlatformAdmin"])
def create_payout(role, user_id, teacher_id):
    teacher = resolve("teachers", teacher_id, "Teacher")
    auth.require_teacher_owner(role, user_id, teacher["id"])
    data = auth.body()
    start_raw = data.get("period_start")
    end_raw = data.get("period_end")
    start = clock.try_parse_datetime(start_raw)
    end = clock.try_parse_datetime(end_raw)
    if start is None or end is None:
        auth.require_fields(data, ["period_start", "period_end", "expected_teacher_version"])
        fail("ERR_PAYOUT_PERIOD_OVERLAP", "period_start and period_end must be ISO 8601 instants")
    if not (start < end):
        fail("ERR_PAYOUT_PERIOD_OVERLAP", "period_end must be strictly after period_start")

    mine = [p for p in store.all_of("payouts") if p["teacher_id"] == teacher["id"]]
    for other in mine:
        if other["status"] == "VOIDED":
            continue
        same_fingerprint = (
            other["period_start_raw"] == start_raw
            and other["period_end_raw"] == end_raw
            and other["status"] == "REQUESTED"
        )
        if same_fingerprint:
            continue
        if other["period_start_dt"] < end and start < other["period_end_dt"]:
            fail("ERR_PAYOUT_PERIOD_OVERLAP", "Another non-voided payout of this teacher overlaps the period")

    version = data.get("expected_teacher_version")
    if auth.is_blank(version):
        auth.require_fields(data, ["expected_teacher_version"])
    for other in mine:
        if (
            other["status"] == "REQUESTED"
            and other["period_start_raw"] == start_raw
            and other["period_end_raw"] == end_raw
        ):
            if version != teacher["version"]:
                fail("ERR_DUPLICATE_PAYOUT_PERIOD", "This period was already requested")
            store.touch(other)
            return envelope.Result(200, views.payout_out(other))

    if version != teacher["version"]:
        fail("ERR_STALE_VERSION", "expected_teacher_version does not match the teacher's current version")

    figures = calc.gross_and_fee(teacher, start, end)
    payout = store.make_record(
        "payouts",
        teacher_id=teacher["id"],
        expected_teacher_version=version,
        period_start_raw=start_raw,
        period_end_raw=end_raw,
        period_start_dt=start,
        period_end_dt=end,
        status="REQUESTED",
        gross_earnings_cents=figures["gross_earnings_cents"],
        fee_rate_applied=figures["fee_rate_applied"],
        platform_fee_cents=figures["platform_fee_cents"],
        net_payout_cents=figures["net_payout_cents"],
        approval_status="not_required",
        tax_document_status=None,
        refund_period_index=None,
        teacher_liability_cents=0,
        platform_fee_reversed_cents=0,
    )
    store.touch(teacher)
    payout["tax_document_status"] = calc.tax_document_status(
        calc.lifetime_net_earnings(teacher["id"])
    )
    return envelope.Result(201, views.payout_out(payout))


@bp.get("/outschool/teacher-payouts/<payout_id>")
@api(["Teacher", "PlatformAdmin"])
def get_payout(role, user_id, payout_id):
    payout = resolve("payouts", payout_id, "TeacherPayout")
    return envelope.Result(200, views.payout_out(payout))


@bp.get("/outschool/teacher-payouts")
@api(["Teacher", "PlatformAdmin"])
def list_payouts(role, user_id):
    items = store.by_created(store.all_of("payouts"))
    for field in ("teacher_id", "status"):
        value = request.args.get(field)
        if value:
            items = [x for x in items if x.get(field) == value]
    return envelope.paged([views.payout_out(x) for x in items], request.args)


@bp.post("/outschool/teacher-payouts/<payout_id>/transition")
@api(["PlatformAdmin"])
def transition_payout(role, user_id, payout_id):
    payout = resolve("payouts", payout_id, "TeacherPayout")
    data = auth.body()
    action = data.get("action")
    if action is not None and action not in ACTIONS:
        fail("ERR_INVALID_ENUM_VALUE", "action must be SEND, PAY, APPROVE or VOID")
    if payout["status"] == "PAID":
        fail("ERR_PAYOUT_ALREADY_PAID", "This payout has already been paid")
    if payout["status"] == "VOIDED":
        fail("ERR_INVALID_STATE", "This payout has been voided")
    teacher = store.find("teachers", payout["teacher_id"])

    if action == "SEND":
        if payout["status"] != "REQUESTED":
            fail("ERR_INVALID_STATE", "Only a REQUESTED payout may be sent")
        if payout["approval_status"] == "pending_approval":
            fail("ERR_PAYOUT_CAP_EXCEEDED", "This payout is held for approval")
        if payout["tax_document_status"] != "ON_FILE":
            fail("ERR_TAX_DOC_MISSING", "The payout's tax document status is not ON_FILE")
        cap = calc.approval_cap_figures(payout)
        if (
            calc.payout_net_after_refunds(payout) + cap["already_approved_sent_cents"]
            > C.PAYOUT_APPROVAL_CAP_CENTS
        ):
            payout["approval_status"] = "pending_approval"
            store.touch(payout)
            fail("ERR_PAYOUT_CAP_EXCEEDED", "The payout would exceed the approval cap")
        payout["approval_status"] = "not_required"
        payout["status"] = "SENT"
        store.touch(payout)
        return envelope.Result(200, views.payout_out(payout))

    if action == "PAY":
        if payout["status"] != "SENT":
            fail("ERR_INVALID_STATE", "Only a SENT payout may be paid")
        payout["status"] = "PAID"
        store.touch(payout)
        store.touch(teacher)
        return envelope.Result(200, views.payout_out(payout))

    if action == "APPROVE":
        if payout["status"] != "FAILED":
            fail("ERR_INVALID_STATE", "Only a FAILED payout may be approved")
        if payout["approval_status"] != "pending_approval":
            fail("ERR_PAYOUT_NOT_APPROVED", "This payout is not awaiting approval")
        payout["approval_status"] = "approved"
        payout["status"] = "PAID"
        store.touch(payout)
        store.touch(teacher)
        return envelope.Result(200, views.payout_out(payout))

    if action == "VOID":
        if payout["status"] not in ("REQUESTED", "SENT", "FAILED"):
            fail("ERR_INVALID_STATE", "This payout may not be voided")
        payout["status"] = "VOIDED"
        store.touch(payout)
        store.touch(teacher)
        return envelope.Result(200, views.payout_out(payout))

    fail("ERR_MISSING_REQUIRED_FIELD", "Field 'action' is required")
