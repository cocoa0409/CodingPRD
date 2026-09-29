"""Revenue reporting: the royalty waterfall in both its variants (PRD 3.9)."""

from flask import Blueprint, request

from calc import MAX_REVENUE_LINES, final_settlement, provisional_settlement
from envelope import created, success
from errors import ApiError
from guards import (
    ALL_ROLES,
    ROLE_PUBLISHER_FINANCE,
    agreement_of_statement,
    begin,
    body,
    find_agreement,
    find_statement,
    require_party,
)
from ledger import recompute_ledger, statements_of
from listing import matches, paged
from serializers import statement as ser_statement
from store import db, lock, new_id, now_iso, stamp_new, touch
from validation import Field, bad, paging

bp = Blueprint("royalties", __name__)

REVENUE_ELIGIBLE = ("ACTIVE", "COMPLETED")

STATEMENT_FIELDS = (
    Field("agreement_id", "string", required=True),
    Field("period_label", "string", required=True, pattern=r"^[0-9]{4}-Q[1-4]$"),
    Field("revenue_lines", "array", required=True, max_items=MAX_REVENUE_LINES),
    Field("recoupable_cost_cents", "int", default=0, min=0),
    Field("expected_agreement_version", "int", required=True),
)


def _revenue_lines(raw_lines):
    """Structural shape of one revenue line (rule 6), in submitted order."""
    lines = []
    seen = set()
    for entry in raw_lines:
        if not isinstance(entry, dict):
            bad("Every entry of 'revenue_lines' must be an object.")
        code = entry.get("platform_code")
        if not isinstance(code, str) or code.strip() == "":
            bad("Every revenue line needs a non-blank 'platform_code'.")
        if code in seen:
            bad("'platform_code' must be unique within the statement.")
        seen.add(code)
        gross = entry.get("gross_cents")
        returns = entry.get("returns_cents")
        for name, value in (("gross_cents", gross), ("returns_cents", returns)):
            if isinstance(value, bool) or not isinstance(value, int):
                bad("Revenue line field '%s' must be an integer." % name)
            if value < 0:
                bad("Revenue line field '%s' must not be negative." % name)
        if returns > gross:
            bad("A revenue line's 'returns_cents' may not exceed its 'gross_cents'.")
        lines.append(
            {"platform_code": code, "gross_cents": gross, "returns_cents": returns}
        )
    return lines


def _finalized(agreement):
    rows = [s for s in statements_of(agreement) if s["state"] == "FINALIZED"]
    rows.sort(key=lambda s: (s["finalized_at"], s["created_at"], s["_seq"]))
    return rows


@bp.post("/royalty-statements")
def create_statement():
    actor = begin([ROLE_PUBLISHER_FINANCE])
    _, data = body(STATEMENT_FIELDS)
    lines = _revenue_lines(data["revenue_lines"])
    period = data["period_label"]
    with lock:
        # Rule 19: statement creation resolves agreement_id.
        agreement = find_agreement(data["agreement_id"])
        require_party(actor, agreement)
        # Rule 21: the second of the two OCC endpoints.
        if data["expected_agreement_version"] != agreement["version"]:
            raise ApiError("ERR_STALE_AGREEMENT_VERSION")
        finalized = _finalized(agreement)
        # Rule 43: a settled period is closed for good.
        if any(s["period_label"] == period for s in finalized):
            raise ApiError("ERR_PERIOD_ALREADY_FINALIZED")
        # Rule 63: the label may not regress behind the last finalized period.
        if finalized and period < finalized[-1]["period_label"]:
            raise ApiError("ERR_PERIOD_OUT_OF_ORDER")
        # Rule 64: revenue eligibility is deliberately below the two above.
        if agreement["status"] not in REVENUE_ELIGIBLE:
            raise ApiError("ERR_AGREEMENT_NOT_REVENUE_ELIGIBLE")

        settlement = provisional_settlement(agreement, lines, data["recoupable_cost_cents"])
        row = {
            "id": new_id(),
            "agreement_id": agreement["id"],
            "period_label": period,
            "revenue_lines": lines,
            "recoupable_cost_cents": data["recoupable_cost_cents"],
            "final_royalty_payable_cents": None,
            "state": "DRAFT",
            "finalized_at": None,
        }
        row.update(settlement)
        stamp_new(row)

        # Cascade: an earlier draft for the same period is superseded and can
        # never be finalized afterwards.
        for other in statements_of(agreement):
            if other["state"] == "DRAFT" and other["period_label"] == period:
                other["state"] = "SUPERSEDED"
                touch(other)
        db.statements[row["id"]] = row
        touch(agreement)
        return created(ser_statement(row))


@bp.get("/royalty-statements/<sid>")
def read_statement(sid):
    actor = begin(ALL_ROLES)
    with lock:
        stmt = find_statement(sid)
        require_party(actor, agreement_of_statement(stmt))
        return success(ser_statement(stmt))


@bp.get("/development-agreements/<aid>/royalty-statements")
def list_statements(aid):
    actor = begin(ALL_ROLES)
    paging(request.args)
    with lock:
        agreement = find_agreement(aid)
        require_party(actor, agreement)
        rows = [
            row for row in statements_of(agreement)
            if matches(row, request.args, ("state", "period_label"))
        ]
        return paged(rows, request.args, ser_statement)


@bp.post("/royalty-statements/<sid>/finalize")
def finalize_statement(sid):
    actor = begin([ROLE_PUBLISHER_FINANCE])
    with lock:
        stmt = find_statement(sid)
        agreement = agreement_of_statement(stmt)
        require_party(actor, agreement)
        # Rule 42, then rule 43, then rule 64: statement identity before
        # agreement eligibility.
        if stmt["state"] != "DRAFT":
            raise ApiError("ERR_STATEMENT_NOT_DRAFT")
        if any(
            s["period_label"] == stmt["period_label"] for s in _finalized(agreement)
        ):
            raise ApiError("ERR_PERIOD_ALREADY_FINALIZED")
        if agreement["status"] not in REVENUE_ELIGIBLE:
            raise ApiError("ERR_AGREEMENT_NOT_REVENUE_ELIGIBLE")

        result = final_settlement(agreement, stmt)
        payable = result["final_royalty_payable_cents"]
        # Ledger posting, in the declared order. The provisional fields stay
        # untouched so the two variants remain comparable.
        agreement["advance_recouped_cents"] = result["cum_recoup_applied_cents"]
        stmt["final_royalty_payable_cents"] = payable
        stmt["state"] = "FINALIZED"
        stmt["finalized_at"] = now_iso()
        agreement["royalties_paid_to_date_cents"] += payable
        # Step 2 rides on the ledger recompute: unrecouped_advance_cents is
        # advance_disbursed_cents less the recouped figure, floored at zero, and
        # RECOUPING becomes RECOUPED the moment it reaches 0.
        recompute_ledger(agreement)
        if (
            agreement["recoupment_state"] == "RECOUPING"
            and agreement["unrecouped_advance_cents"] == 0
        ):
            agreement["recoupment_state"] = "RECOUPED"
        touch(stmt)
        touch(agreement)
        return success(ser_statement(stmt))
