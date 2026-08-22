"""Claim intake, adjudication actions, service lines, remittances and events."""

from flask import Blueprint, g, request

from auth import CLAIM_READERS, endpoint, enforce_claim_scope, is_provider_rep
from envelope import created, ok
from errors import ApiError
from routes.common import filter_equals, filter_int_equals, render_list, resolve
from serializers import dump
from services.claims import create_claim, detect_duplicate
from services.events import append_event
from services.lifecycle import adjust, finalize, post_other_payer_payment, void
from services.lookup import member_of, plan_of_member
from services.pipeline import override_approve, override_deny, run_pass
from store import db, parse_date, sort_key_created
from validators import (
    body,
    check_interval,
    read_date,
    read_enum,
    read_int,
    read_string,
    require_fields,
)

bp = Blueprint("claims", __name__)

ADJUDICABLE_STATUSES = ("RECEIVED", "PENDED")
COB_POSTABLE_STATUSES = ("RECEIVED", "PENDED", "ADJUDICATED")
FINALIZABLE_STATUSES = ("ADJUDICATED", "DENIED")
DEFAULT_OVERRIDE_DENY_REASON = "DENY_MEDICAL_POLICY"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _read_line_payloads(payload):
    """Field well-formedness for the submitted lines array."""
    raw = payload.get("lines")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ApiError("ERR_INVALID_FIELD_VALUE", "lines must be an array.")
    out = []
    for element in raw:
        if not isinstance(element, dict):
            raise ApiError("ERR_INVALID_FIELD_VALUE", "each line must be an object.")
        require_fields(
            element,
            ["line_number", "procedure_code", "units", "billed_amount_cents", "service_date"],
        )
        out.append(
            {
                "line_number": read_int(element, "line_number", minimum=1, required=True),
                "procedure_code": read_string(element, "procedure_code", required=True),
                "modifier_code": read_string(element, "modifier_code"),
                "units": read_int(element, "units", minimum=1, required=True),
                "billed_amount_cents": read_int(
                    element, "billed_amount_cents", minimum=0, required=True
                ),
                "service_date": read_date(element, "service_date", required=True),
            }
        )
    return out


def _check_timely_filing(plan, statement_to_date):
    """Exactly timely_filing_days is accepted; only strictly greater is refused."""
    distance = (parse_date(db.clock_date()) - parse_date(statement_to_date)).days
    if distance > plan["timely_filing_days"]:
        raise ApiError("ERR_TIMELY_FILING_EXCEEDED")


def _check_claim_number_unique(claim_number):
    for existing in db.values("claims"):
        if existing["claim_number"] == claim_number:
            raise ApiError("ERR_DUPLICATE_CLAIM_NUMBER")


def _visible_claims():
    rows = db.values("claims")
    if is_provider_rep():
        rows = [row for row in rows if row["provider_id"] == g.user_id]
    return rows


# --------------------------------------------------------------------------
# intake
# --------------------------------------------------------------------------
@bp.post("/adjudication/claims")
@endpoint(["ClaimsIntake", "ProviderRep"])
def submit_claim():
    payload = body()
    # 4 -- body foreign keys
    if payload.get("member_id") is not None:
        member = resolve("members", payload["member_id"], "ERR_MEMBER_NOT_FOUND")
    else:
        member = None
    if payload.get("provider_id") is not None:
        resolve("providers", payload["provider_id"], "ERR_PROVIDER_NOT_FOUND")
    # 5 -- provider scoping
    if is_provider_rep() and payload.get("provider_id") is not None:
        if payload["provider_id"] != g.user_id:
            raise ApiError("ERR_PROVIDER_SCOPE_VIOLATION")
    # 6 -- required fields
    require_fields(payload, ["claim_number", "member_id", "provider_id"])
    # 7 -- field well-formedness
    claim_number = read_string(payload, "claim_number", required=True)
    statement_from_date = read_date(payload, "statement_from_date")
    statement_to_date = read_date(payload, "statement_to_date")
    check_interval("statement_to_date", statement_from_date, statement_to_date)
    other_payer_paid_cents = read_int(payload, "other_payer_paid_cents", minimum=0)
    line_payloads = _read_line_payloads(payload)
    # 12 -- at least one service line
    if not line_payloads:
        raise ApiError("ERR_CLAIM_NO_LINES")

    plan = plan_of_member(member)
    effective_to = statement_to_date or max(l["service_date"] for l in line_payloads)
    # 15 -- timely filing
    _check_timely_filing(plan, effective_to)
    # 16 -- the member must have coverage on file
    if not any(c["member_id"] == member["id"] for c in db.values("member_coverages")):
        raise ApiError("ERR_MEMBER_NO_COVERAGE")
    # 17 -- uniqueness
    _check_claim_number_unique(claim_number)
    # 18 -- the other payer may not exceed the billed charges
    total_billed = sum(l["billed_amount_cents"] for l in line_payloads)
    if other_payer_paid_cents is not None and other_payer_paid_cents > total_billed:
        raise ApiError("ERR_OTHER_PAYER_EXCEEDS_BILLED")

    claim = create_claim(
        claim_number,
        member["id"],
        payload["provider_id"],
        line_payloads,
        statement_from_date,
        statement_to_date,
        other_payer_paid_cents,
    )

    duplicate = detect_duplicate(claim)
    if duplicate is not None:
        claim["status"] = "DUPLICATE_REJECTED"
        claim["duplicate_of_claim_id"] = duplicate["id"]
        claim["deny_reason_code"] = "DENY_DUPLICATE"
        append_event(
            claim,
            "DUPLICATE_REJECT",
            "RECEIVED",
            "DUPLICATE_REJECTED",
            "DENY_DUPLICATE",
            g.role,
            g.user_id,
            pass_number=0,
        )
    else:
        append_event(claim, "INTAKE", None, "RECEIVED", None, g.role, g.user_id, pass_number=0)
    return created(dump("claim", claim))


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------
@bp.get("/adjudication/claims/<claim_id>")
@endpoint(CLAIM_READERS)
def get_claim(claim_id):
    claim = resolve("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    enforce_claim_scope(claim)
    return ok(dump("claim", claim))


@bp.get("/adjudication/claims")
@endpoint(CLAIM_READERS)
def list_claims():
    rows = _visible_claims()
    rows = filter_equals(rows, "member_id", request.args.get("member_id"))
    rows = filter_equals(rows, "provider_id", request.args.get("provider_id"))
    rows = filter_equals(rows, "coverage_id", request.args.get("coverage_id"))
    rows = filter_equals(rows, "original_claim_id", request.args.get("original_claim_id"))
    rows = filter_equals(rows, "duplicate_of_claim_id", request.args.get("duplicate_of_claim_id"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    rows = filter_equals(rows, "claim_type", request.args.get("claim_type"))
    return render_list("claim", rows)


# --------------------------------------------------------------------------
# adjudication actions
# --------------------------------------------------------------------------
@bp.post("/adjudication/claims/<claim_id>/adjudicate")
@endpoint(["ClaimsExaminer"])
def adjudicate_claim(claim_id):
    claim = resolve("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] not in ADJUDICABLE_STATUSES:
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    run_pass(claim, g.role, g.user_id)
    return ok(dump("claim", claim))


@bp.post("/adjudication/claims/<claim_id>/override")
@endpoint(["MedicalDirector"])
def override_claim(claim_id):
    claim = resolve("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    payload = body()
    require_fields(payload, ["decision"])
    decision = read_enum(payload, "decision", ("APPROVE", "DENY"), required=True)
    override_reason_code = read_string(payload, "override_reason_code")
    if claim["status"] != "PENDED":
        raise ApiError("ERR_CLAIM_NOT_PENDED")
    if g.user_id == claim["last_adjudicated_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if decision == "APPROVE":
        override_approve(claim, g.role, g.user_id)
    else:
        override_deny(
            claim,
            override_reason_code or DEFAULT_OVERRIDE_DENY_REASON,
            g.role,
            g.user_id,
        )
    return ok(dump("claim", claim))


@bp.post("/adjudication/claims/<claim_id>/finalize")
@endpoint(["ClaimsExaminer"])
def finalize_claim(claim_id):
    claim = resolve("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] not in FINALIZABLE_STATUSES:
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    finalize(claim, g.role, g.user_id)
    return ok(dump("claim", claim))


@bp.post("/adjudication/claims/<claim_id>/void")
@endpoint(["ClaimsExaminer"])
def void_claim(claim_id):
    claim = resolve("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    payload = body()
    read_string(payload, "void_reason_code")
    if claim["status"] != "FINALIZED":
        raise ApiError("ERR_CLAIM_NOT_FINALIZED")
    void(claim, g.role, g.user_id)
    return ok(dump("claim", claim))


@bp.post("/adjudication/claims/<claim_id>/adjustments")
@endpoint(["ClaimsExaminer"])
def adjust_claim(claim_id):
    original = resolve("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    payload = body()
    require_fields(payload, ["claim_number"])
    claim_number = read_string(payload, "claim_number", required=True)
    read_string(payload, "adjustment_reason_code")
    line_payloads = _read_line_payloads(payload)
    # An adjustment claim cannot itself be adjusted.
    if original["status"] != "FINALIZED" or original["claim_type"] != "ORIGINAL":
        raise ApiError("ERR_CLAIM_NOT_FINALIZED")
    if not line_payloads:
        raise ApiError("ERR_CLAIM_NO_LINES")

    member = member_of(original)
    plan = plan_of_member(member)
    statement_to_date = max(l["service_date"] for l in line_payloads)
    _check_timely_filing(plan, statement_to_date)
    _check_claim_number_unique(claim_number)

    adjust(original, g.role, g.user_id)
    replacement = create_claim(
        claim_number,
        original["member_id"],
        original["provider_id"],
        line_payloads,
        None,
        None,
        None,
        claim_type="ADJUSTMENT",
        original_claim_id=original["id"],
    )
    return created(dump("claim", replacement))


@bp.post("/adjudication/claims/<claim_id>/other-payer-payment")
@endpoint(["ClaimsIntake"])
def post_other_payer(claim_id):
    claim = resolve("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    payload = body()
    require_fields(payload, ["other_payer_paid_cents", "expected_claim_version"])
    amount = read_int(payload, "other_payer_paid_cents", minimum=0, required=True)
    expected = read_int(payload, "expected_claim_version", required=True)
    if claim["status"] not in COB_POSTABLE_STATUSES:
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    if expected != claim["version"]:
        raise ApiError("ERR_STALE_CLAIM_VERSION")
    if amount > claim["total_billed_cents"]:
        raise ApiError("ERR_OTHER_PAYER_EXCEEDS_BILLED")
    post_other_payer_payment(claim, amount, g.role, g.user_id)
    return ok(dump("claim", claim))


# --------------------------------------------------------------------------
# ClaimLine reads
# --------------------------------------------------------------------------
@bp.get("/adjudication/claim-lines/<line_id>")
@endpoint(CLAIM_READERS)
def get_claim_line(line_id):
    line = resolve("claim_lines", line_id, "ERR_CLAIM_LINE_NOT_FOUND")
    return ok(dump("claim_line", line))


@bp.get("/adjudication/claim-lines")
@endpoint(CLAIM_READERS)
def list_claim_lines():
    visible_claim_ids = {claim["id"] for claim in _visible_claims()}
    rows = [l for l in db.values("claim_lines") if l["claim_id"] in visible_claim_ids]
    rows = filter_equals(rows, "claim_id", request.args.get("claim_id"))
    rows = filter_equals(rows, "authorization_id", request.args.get("authorization_id"))
    rows = filter_equals(rows, "line_status", request.args.get("line_status"))
    return render_list(
        "claim_line", rows, sort_key=lambda l: (l["line_number"], l["created_at"], l["_seq"])
    )


# --------------------------------------------------------------------------
# RemittanceAdvice and AdjudicationEvent reads
# --------------------------------------------------------------------------
@bp.get("/adjudication/claims/<claim_id>/remittances")
@endpoint(CLAIM_READERS)
def list_remittances(claim_id):
    claim = resolve("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    enforce_claim_scope(claim)
    rows = [r for r in db.values("remittance_advices") if r["claim_id"] == claim["id"]]
    rows = filter_equals(rows, "status", request.args.get("status"))
    return render_list(
        "remittance_advice", rows, sort_key=lambda r: (_desc_str(r["created_at"]), -r["_seq"])
    )


@bp.get("/adjudication/claims/<claim_id>/events")
@endpoint(CLAIM_READERS)
def list_events(claim_id):
    claim = resolve("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    enforce_claim_scope(claim)
    rows = [e for e in db.values("adjudication_events") if e["claim_id"] == claim["id"]]
    rows = filter_int_equals(rows, "pass_number", request.args.get("pass_number"))
    rows = filter_equals(rows, "event_type", request.args.get("event_type"))
    return render_list("adjudication_event", rows, sort_key=sort_key_created)


class _DescStr:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __lt__(self, other):
        return self.value > other.value

    def __eq__(self, other):
        return self.value == other.value


def _desc_str(value):
    return _DescStr(value)
