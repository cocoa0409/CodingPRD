"""Option agreements: drafting, the negotiation loop, execution, extension,
exercise and withdrawal (PRD sections 3.5 - 3.7).

The rejection order inside every handler follows the ladder of PRD section 2.9
by rung number, not the order the narrative happens to mention the conditions
in: instrument expiry (rung 22) sits above generic state admissibility (rung
23), which in turn sits above segregation of duties (rung 25) and title
compliance (rung 26), and money (rung 41) is always last.
"""

from flask import Blueprint

import access
import calc
import cascades
import serializers as ser
import validation as v
from auth import (
    ALL_ROLES,
    LANDOWNER,
    LAND_AGENT,
    PORTFOLIO_MANAGER,
    acting_user_id,
    require,
)
from envelope import ok, ok_list
from errors import (
    ERR_EXTENSION_LIMIT_REACHED,
    ERR_INVALID_STATE,
    ERR_LANDOWNER_PAYMENT_HOLD,
    ERR_NEGOTIATION_ROUND_LIMIT,
    ERR_OPTION_EXPIRED,
    ERR_PARCEL_NOT_QUALIFIED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_PARCEL_VERSION,
    ERR_TITLE_CURATIVE_BLOCKING,
    bad_request,
    fail,
)
from store import db, insert, now, ordered, touch
from util import D, add_days

bp = Blueprint("options", __name__, url_prefix="/land-origination")

STRUCTURES = ("PER_ACRE", "ROYALTY_HYBRID")
ESCALATOR_MODES = ("SIMPLE", "COMPOUND")
MAX_OPTION_TERM_DAYS = 1825
MAX_ROYALTY_BPS = 2000
MAX_ESCALATOR_BPS = 1000
MAX_EXTENSIONS = 3
WITHDRAWABLE = ("DRAFT", "SENT", "COUNTERED", "REVISED", "ACCEPTED", "EXECUTED")


# ------------------------------------------------------------------- reads
@bp.get("/option-agreements/<option_id>")
@require(*ALL_ROLES)
def get_option(option_id):
    row = access.option(option_id)
    access.own(row["landowner_id"])
    return ok(ser.option_agreement(row))


@bp.get("/option-agreements")
@require(*ALL_ROLES)
def list_options():
    limit, offset = v.pagination()
    rows = ordered(db.options.values())
    rows = access.scope_rows(rows, lambda r: r["landowner_id"])
    rows = v.apply_filters(rows, [
        ("parcel_id", v.query_str("parcel_id")),
        ("landowner_id", v.query_str("landowner_id")),
        ("status", v.query_str("status")),
    ])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(ser.many(ser.option_agreement, page), limit, offset, total)


# ------------------------------------------------------------------ drafting
@bp.post("/option-agreements")
@require(LAND_AGENT)
def create_option():
    body = v.json_body()
    # Rung 3 outranks rung 4, so the counterparty resolves before the parcel,
    # and both existence rungs outrank the rung-14 shape pass below.
    owner_id = v.lookup_fk(body, "landowner_id")
    owner = access.landowner(owner_id) if owner_id else None
    parcel_id = v.lookup_fk(body, "parcel_id")
    parcel = access.parcel(parcel_id) if parcel_id else None

    v.req_fk(body, "landowner_id")
    v.req_fk(body, "parcel_id")
    term_days = v.req_int(body, "option_term_days", lo=1, hi=MAX_OPTION_TERM_DAYS)
    option_fee = v.req_int(body, "option_fee_per_acre_cents", lo=0)
    ext_allowed = v.req_int(body, "extension_count_allowed", lo=0, hi=MAX_EXTENSIONS)
    ext_fee = v.req_int(body, "extension_fee_per_acre_cents", lo=0)
    structure = v.req_enum(body, "rent_structure_type", STRUCTURES)
    base_rent = v.req_int(body, "base_rent_per_acre_cents", lo=0)
    royalty_bps = v.req_int(body, "royalty_rate_bps", lo=0, hi=MAX_ROYALTY_BPS)
    escalator_bps = v.req_int(body, "escalator_pct_bps", lo=0, hi=MAX_ESCALATOR_BPS)
    escalator_mode = v.req_enum(body, "escalator_mode", ESCALATOR_MODES)
    expected_version = v.req_int(body, "expected_parcel_version")

    if structure == "PER_ACRE" and royalty_bps != 0:
        bad_request("royalty_rate_bps must be 0 when rent_structure_type is "
                    "PER_ACRE.")
    if parcel["landowner_id"] != owner["id"]:
        bad_request("landowner_id is not the parcel's owner of record.")

    # Rung 19: the concurrency guard is the last objection before the write.
    if int(expected_version) != int(parcel["version"]):
        fail(ERR_STALE_PARCEL_VERSION)

    row = insert("options", {
        "parcel_id": parcel["id"],
        "landowner_id": owner["id"],
        "option_term_days": term_days,
        "option_fee_per_acre_cents": option_fee,
        "extension_count_allowed": ext_allowed,
        "extension_fee_per_acre_cents": ext_fee,
        "rent_structure_type": structure,
        "base_rent_per_acre_cents": base_rent,
        "royalty_rate_bps": royalty_bps,
        "escalator_pct_bps": escalator_bps,
        "escalator_mode": escalator_mode,
        "round_index": 0,
        "executed_at": None,
        "executed_by_user_id": None,
        "option_expiry_at": None,
        "extensions_used": 0,
        "total_option_paid_cents": 0,
        "exercised_at": None,
        "withdraw_reason": None,
        "status": "DRAFT",
    })
    # A draft bumps its concurrency parent (PRD section 2.7).
    touch(parcel)
    return ok(ser.option_agreement(row), 201)


# ---------------------------------------------------------- negotiation loop
def _qualified(parcel):
    """Qualification tested at this instant, not as the draft remembered it."""
    if parcel is None or parcel["status"] != "QUALIFIED":
        return False
    return (D(parcel["buildable_acres"]) >= calc.MIN_BUILDABLE_ACRES
            and parcel["screening_tier"] in ("PRIORITY", "STANDARD")
            and int(parcel["blocking_curative_open_count"]) == 0)


def _apply_terms(row, body, allow_structure):
    """The seven counterable terms, plus rent_structure_type on a revision.

    Every omitted term keeps the value the agreement currently holds.
    """
    option_fee = v.opt_int(body, "option_fee_per_acre_cents", None, lo=0)
    ext_fee = v.opt_int(body, "extension_fee_per_acre_cents", None, lo=0)
    base_rent = v.opt_int(body, "base_rent_per_acre_cents", None, lo=0)
    royalty_bps = v.opt_int(body, "royalty_rate_bps", None, lo=0,
                            hi=MAX_ROYALTY_BPS)
    escalator_bps = v.opt_int(body, "escalator_pct_bps", None, lo=0,
                              hi=MAX_ESCALATOR_BPS)
    escalator_mode = v.opt_enum(body, "escalator_mode", ESCALATOR_MODES)
    term_days = v.opt_int(body, "option_term_days", None, lo=1,
                          hi=MAX_OPTION_TERM_DAYS)
    structure = None
    if allow_structure:
        structure = v.opt_enum(body, "rent_structure_type", STRUCTURES)

    effective_structure = structure or row["rent_structure_type"]
    effective_royalty = royalty_bps if royalty_bps is not None \
        else int(row["royalty_rate_bps"])
    if effective_structure == "PER_ACRE" and int(effective_royalty) != 0:
        bad_request("royalty_rate_bps must be 0 when rent_structure_type is "
                    "PER_ACRE.")

    for field, value in (
        ("option_fee_per_acre_cents", option_fee),
        ("extension_fee_per_acre_cents", ext_fee),
        ("base_rent_per_acre_cents", base_rent),
        ("royalty_rate_bps", royalty_bps),
        ("escalator_pct_bps", escalator_bps),
        ("escalator_mode", escalator_mode),
        ("option_term_days", term_days),
        ("rent_structure_type", structure),
    ):
        if value is not None:
            row[field] = value
    return row


def _expired(row):
    """Rung 22. option_expiry_at is null until execution, so this is a no-op
    on every pre-execution status."""
    expiry = row["option_expiry_at"]
    return expiry is not None and now() >= expiry


@bp.post("/option-agreements/<option_id>/send")
@require(LAND_AGENT)
def send_option(option_id):
    row = access.option(option_id)
    parcel = db.parcels.get(row["parcel_id"])

    if row["status"] not in ("DRAFT", "REVISED"):
        fail(ERR_INVALID_STATE)
    if not _qualified(parcel):
        fail(ERR_PARCEL_NOT_QUALIFIED)

    row["status"] = "SENT"
    touch(row)
    return ok(ser.option_agreement(row))


@bp.post("/option-agreements/<option_id>/counter")
@require(LANDOWNER)
def counter_option(option_id):
    row = access.option(option_id)
    access.own(row["landowner_id"])
    body = v.json_body()
    # Rung 14 shape work happens before any state rung.
    _apply_check = dict(row)
    _apply_terms(_apply_check, body, allow_structure=False)

    if row["status"] != "SENT":
        fail(ERR_INVALID_STATE)
    if int(row["round_index"]) >= calc.MAX_NEGOTIATION_ROUNDS:
        fail(ERR_NEGOTIATION_ROUND_LIMIT)

    _apply_terms(row, body, allow_structure=False)
    row["round_index"] = int(row["round_index"]) + 1
    row["status"] = "COUNTERED"
    touch(row)
    return ok(ser.option_agreement(row))


@bp.post("/option-agreements/<option_id>/revise")
@require(LAND_AGENT)
def revise_option(option_id):
    row = access.option(option_id)
    body = v.json_body()
    _apply_check = dict(row)
    _apply_terms(_apply_check, body, allow_structure=True)

    if row["status"] != "COUNTERED":
        fail(ERR_INVALID_STATE)

    _apply_terms(row, body, allow_structure=True)
    row["status"] = "REVISED"
    touch(row)
    return ok(ser.option_agreement(row))


@bp.post("/option-agreements/<option_id>/accept")
@require(LANDOWNER)
def accept_option(option_id):
    row = access.option(option_id)
    access.own(row["landowner_id"])

    if _expired(row):
        fail(ERR_OPTION_EXPIRED)
    if row["status"] != "SENT":
        fail(ERR_INVALID_STATE)

    row["status"] = "ACCEPTED"
    touch(row)
    return ok(ser.option_agreement(row))


# ------------------------------------------- execution and the fee ledger
def _mint(agreement, payment_kind, direction, amount_cents, acres_basis):
    """Append one immutable ledger row (no updated_at, no version)."""
    return insert("payments", {
        "option_agreement_id": agreement["id"],
        "sequence_no": cascades.next_sequence_no(agreement["id"]),
        "payment_kind": payment_kind,
        "ledger_direction": direction,
        "amount_cents": int(amount_cents),
        "acres_basis": acres_basis,
    }, common_fields=False)


def _settle_owner(owner):
    """Re-derive the owner's signed balance, then resynchronise the posture.

    Both land in a single version bump on the landowner row.
    """
    changed_total = cascades.recompute_landowner_total(owner)
    cascades.sync_landowner_posture(owner, also_changed=changed_total)


@bp.post("/option-agreements/<option_id>/execute")
@require(PORTFOLIO_MANAGER)
def execute_option(option_id):
    row = access.option(option_id)
    parcel = db.parcels.get(row["parcel_id"])
    owner = db.landowners.get(row["landowner_id"])

    if _expired(row):
        fail(ERR_OPTION_EXPIRED)
    if row["status"] != "ACCEPTED":
        fail(ERR_INVALID_STATE)
    # ERR_PARCEL_NOT_QUALIFIED is scoped to the send action only, so an
    # unqualified parcel here is a plain state objection.
    if parcel is None or parcel["status"] != "QUALIFIED":
        fail(ERR_INVALID_STATE)
    if owner is not None and owner["payment_hold"]:
        fail(ERR_LANDOWNER_PAYMENT_HOLD)

    executed_at = now()
    row["status"] = "EXECUTED"
    row["executed_at"] = executed_at
    row["executed_by_user_id"] = acting_user_id()
    row["option_expiry_at"] = add_days(executed_at, int(row["option_term_days"]))

    # Option fees are always priced on deeded acreage, never on buildable.
    gross_acres = D(parcel["gross_acres"])
    _mint(row, "INITIAL_OPTION_FEE", "DEBIT_DEVELOPER",
          calc.initial_option_fee_cents(row["option_fee_per_acre_cents"],
                                        gross_acres),
          gross_acres)
    cascades.recompute_agreement_total(row)
    touch(row)

    parcel["status"] = "OPTIONED"
    touch(parcel)
    _settle_owner(owner)
    return ok(ser.option_agreement(row))


@bp.post("/option-agreements/<option_id>/extend")
@require(PORTFOLIO_MANAGER)
def extend_option(option_id):
    row = access.option(option_id)
    parcel = db.parcels.get(row["parcel_id"])
    owner = db.landowners.get(row["landowner_id"])

    if _expired(row):
        fail(ERR_OPTION_EXPIRED)
    if row["status"] != "EXECUTED":
        fail(ERR_INVALID_STATE)
    # Deal structure outranks money (PRD section 2.9).
    if int(row["extensions_used"]) >= int(row["extension_count_allowed"]):
        fail(ERR_EXTENSION_LIMIT_REACHED)
    if owner is not None and owner["payment_hold"]:
        fail(ERR_LANDOWNER_PAYMENT_HOLD)

    index = int(row["extensions_used"]) + 1
    row["extensions_used"] = index
    row["option_expiry_at"] = add_days(row["option_expiry_at"],
                                       calc.EXTENSION_TERM_DAYS)

    gross_acres = D(parcel["gross_acres"]) if parcel is not None else D("0.00")
    _mint(row, "EXTENSION_FEE", "DEBIT_DEVELOPER",
          calc.extension_fee_cents(row["extension_fee_per_acre_cents"],
                                   gross_acres, index),
          gross_acres)
    cascades.recompute_agreement_total(row)
    touch(row)
    _settle_owner(owner)
    return ok(ser.option_agreement(row))


# --------------------------------------------- exercise: originate the lease
def _new_lease(agreement, parcel, exercise_notice_reference, term_start):
    """The security snapshot is sized once, here, and never restated."""
    acre_basis = D(parcel["buildable_acres"])
    gross, admin_rate, loading, total = calc.decommissioning_security(acre_basis)
    return insert("leases", {
        "option_agreement_id": agreement["id"],
        "parcel_id": agreement["parcel_id"],
        "landowner_id": agreement["landowner_id"],
        "exercise_notice_reference": exercise_notice_reference,
        "term_start_date": term_start,
        "term_years": calc.LEASE_TERM_YEARS,
        "acre_basis_at_exercise": acre_basis,
        "gross_security_cents": gross,
        "admin_rate_bps": admin_rate,
        "admin_loading_cents": loading,
        "total_security_required_cents": total,
        "security_posted_cents": 0,
        "memo_submitted_at": None,
        "recorded_at": None,
        "recording_instrument_no": None,
        "last_paid_invoice_year": 0,
        "rent_status": "PENDING_FIRST_RENT",
        "recording_status": "UNRECORDED",
    })


@bp.post("/option-agreements/<option_id>/exercise")
@require(PORTFOLIO_MANAGER)
def exercise_option(option_id):
    row = access.option(option_id)
    body = v.json_body()
    reference = v.req_str(body, "exercise_notice_reference", min_len=1,
                          max_len=60)
    parcel = db.parcels.get(row["parcel_id"])
    owner = db.landowners.get(row["landowner_id"])

    if _expired(row):
        fail(ERR_OPTION_EXPIRED)
    if row["status"] != "EXECUTED":
        fail(ERR_INVALID_STATE)
    if parcel is None or parcel["status"] != "OPTIONED":
        fail(ERR_INVALID_STATE)
    # A consent revoked mid-option can quietly push the parcel under the floor.
    if D(parcel["buildable_acres"]) < calc.MIN_BUILDABLE_ACRES:
        fail(ERR_INVALID_STATE)
    if acting_user_id() == row["executed_by_user_id"]:
        fail(ERR_SEGREGATION_OF_DUTIES)
    if int(parcel["blocking_curative_open_count"]) > 0:
        fail(ERR_TITLE_CURATIVE_BLOCKING)
    if owner is not None and owner["payment_hold"]:
        fail(ERR_LANDOWNER_PAYMENT_HOLD)

    exercised_at = now()
    row["status"] = "EXERCISED"
    row["exercised_at"] = exercised_at
    touch(row)

    # The parcel deliberately stays OPTIONED until the memorandum is recorded.
    lease = _new_lease(row, parcel, reference, exercised_at)
    return ok(ser.lease(lease), 201)


# -------------------------------------------------------------- withdrawal
@bp.post("/option-agreements/<option_id>/withdraw")
@require(LAND_AGENT, PORTFOLIO_MANAGER)
def withdraw_option(option_id):
    row = access.option(option_id)
    body = v.json_body()
    reason = v.req_str(body, "withdraw_reason", min_len=1)
    refund = v.opt_bool(body, "refund_extension_fees", False)

    if row["status"] not in WITHDRAWABLE:
        fail(ERR_INVALID_STATE)

    was_executed = row["status"] == "EXECUTED"
    parcel = db.parcels.get(row["parcel_id"])
    owner = db.landowners.get(row["landowner_id"])

    if was_executed and refund and int(row["extensions_used"]) > 0:
        # Exactly one reversal row, summing this agreement's EXTENSION_FEE rows
        # in created_at ascending order and nothing else.
        refundable = 0
        for payment in cascades.agreement_payments(row["id"]):
            if payment["payment_kind"] == "EXTENSION_FEE":
                refundable += int(payment["amount_cents"])
        _mint(row, "REFUND_REVERSAL", "CREDIT_DEVELOPER", refundable, D("0.00"))

    row["status"] = "WITHDRAWN"
    row["withdraw_reason"] = reason
    cascades.recompute_agreement_total(row)
    touch(row)

    if was_executed:
        # The land is released without any acreage or screening field moving.
        if parcel is not None and parcel["status"] == "OPTIONED":
            parcel["status"] = "QUALIFIED"
            touch(parcel)
        _settle_owner(owner)
    return ok(ser.option_agreement(row))
