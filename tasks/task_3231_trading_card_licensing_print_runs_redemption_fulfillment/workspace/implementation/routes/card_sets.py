"""CardSet resource: creation, the review/approval chain, production, packout,
plus the nested child collections that hang off a set.
"""

import datetime

from flask import jsonify, request

import calc
import db
import requtil
import response
from core import app
from common import (
    license_in_force,
    license_of_card_set,
    license_of_product_line,
    recompute_allocated_cards,
    recompute_card_set_aggregates,
    recompute_license_counts,
    recompute_license_counts_for_line,
    recompute_sets_per_case,
    serialize,
    sets_under_line,
)
from constants import SET_TIERS
from errors import (
    ApiError,
    ERR_ARTWORK_APPROVAL_PENDING,
    ERR_ARTWORK_NOT_APPROVED,
    ERR_CARD_SET_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LICENSE_NOT_IN_FORCE,
    ERR_LICENSE_TERM_WINDOW_BREACH,
    ERR_PACK_CONFIG_MISSING,
    ERR_PRINT_RUN_NOT_ALLOWED,
    ERR_PRINT_RUN_NOT_LOCKED,
    ERR_PRINT_RUN_REQUIRED,
    ERR_PRODUCT_LINE_NOT_FOUND,
    ERR_PRODUCT_LINE_NOT_PACKED_OUT,
    ERR_PRODUCT_LINE_NOT_READY,
    ERR_PRODUCT_LINE_STATE_BLOCKED,
    ERR_REFERENCE_NOT_FOUND,
    ERR_RIGHTS_VERSION_MISMATCH,
    ERR_STALE_VERSION,
)
from middleware import authenticate, require_role

READ_ROLES = [
    "ProductManager",
    "ProductionPlanner",
    "QualityAnalyst",
    "RedemptionFulfilmentAnalyst",
    "PlatformAdmin",
]


def get_card_set(card_set_id):
    rec = db.STORE.get("card_sets", card_set_id)
    if rec is None:
        raise ApiError(
            ERR_CARD_SET_NOT_FOUND, "No CardSet exists with id %s" % card_set_id
        )
    return rec


def get_line(line_id):
    rec = db.STORE.get("product_lines", line_id)
    if rec is None:
        raise ApiError(
            ERR_PRODUCT_LINE_NOT_FOUND, "No ProductLine exists with id %s" % line_id
        )
    return rec


def _serialize(rec):
    store = db.STORE
    # print_run_status is recomputed on every read so a client can never
    # observe a stale value (PRD 2.12).
    rec["print_run_status"] = _derive(store, rec)
    return serialize("card_sets", rec)


def _derive(store, card_set):
    from common import frozen_decision

    decision = frozen_decision(store, card_set["id"])
    if decision is None:
        return "UNDECIDED"
    return "DISCLOSED" if decision["announced"] else "UNDISCLOSED"


def _require_license_in_force(card_set):
    store = db.STORE
    lic = license_of_card_set(store, card_set)
    if not license_in_force(lic, store.now()):
        raise ApiError(
            ERR_LICENSE_NOT_IN_FORCE,
            "The license behind this card set is not in force",
        )
    return lic


def _require_rights_pin(card_set):
    store = db.STORE
    lic = license_of_card_set(store, card_set)
    if lic is None or card_set["rights_pinned_version"] != lic["rights_version"]:
        raise ApiError(
            ERR_RIGHTS_VERSION_MISMATCH,
            "CardSet.rights_pinned_version does not equal License.rights_version",
        )
    return lic


def _require_rights_pin_for_approval(card_set):
    """The pin check as it applies to *approval*.

    PRD 3.1/2.8 state that a card set that has never been approved holds
    rights_pinned_version of 0, and that approval both requires
    rights_pinned_version == License.rights_version and captures the pin as its
    own side effect.  Those two readings cannot both hold for a first approval,
    because 0 never matches a live license -- enforcing the check
    unconditionally would make card-set approval unreachable and with it every
    downstream workflow.  The pin is therefore treated as binding only once it
    is meaningful: a set that already carries a non-zero pin must still match
    the live rights version, and an unpinned set captures the pin on approval.
    """
    store = db.STORE
    lic = license_of_card_set(store, card_set)
    if lic is None:
        return None
    if card_set["rights_pinned_version"] != 0:
        if card_set["rights_pinned_version"] != lic["rights_version"]:
            raise ApiError(
                ERR_RIGHTS_VERSION_MISMATCH,
                "CardSet.rights_pinned_version does not equal License.rights_version",
            )
    return lic


def _artwork_for(store, card_set_id):
    return [a for a in store.all("artwork_approvals") if a["card_set_id"] == card_set_id]


def _license_active_across(store, lic, card_set_id, now):
    """PRD 2.7: the license must have been continuously ACTIVE across
    [ArtworkApproval.submitted_on, now].  A license suspended at any point
    inside that window, then reactivated, fails."""
    from common import license_active_across

    approvals = _artwork_for(store, card_set_id)
    if not approvals:
        return True
    start = min(a["submitted_on"] for a in approvals)
    return license_active_across(lic, start, now)


@app.route("/api/card-sets", methods=["POST"])
def create_card_set():
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager"])

    data = requtil.body()
    product_line_id = requtil.required_str(data, "product_line_id")
    set_name = requtil.required_str(data, "set_name")
    set_tier = requtil.required_enum(data, "set_tier", SET_TIERS)
    announced = requtil.required_bool(data, "announced")
    serial_numbered = requtil.required_bool(data, "serial_numbered")
    autograph_planned_count = requtil.required_int(data, "autograph_planned_count")
    print_run_quantity = requtil.optional_int(data, "print_run_quantity", 0)
    if print_run_quantity is None:
        print_run_quantity = 0

    store = db.STORE
    if not store.exists("product_lines", product_line_id):
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND,
            "product_line_id %s does not resolve" % product_line_id,
        )

    now = store.now()
    rec = db.record("card_sets", {
        "product_line_id": product_line_id,
        "set_name": set_name,
        "set_tier": set_tier,
        "rights_pinned_version": 0,
        "print_run_quantity": print_run_quantity,
        "announced": announced,
        "serial_numbered": serial_numbered,
        "print_run_status": "UNDECIDED",
        "autograph_planned_count": autograph_planned_count,
        "autograph_secured_count": 0,
        "autograph_redemptions_outstanding": 0,
        "quality_claim_count": 0,
        "settled_complaint_count": 0,
        "status": "DRAFT",
    }, now)
    store.insert("card_sets", rec)
    line = store.get("product_lines", product_line_id)
    recompute_allocated_cards(store, line, now)
    # PRD 3.1: "set_count is the number of card sets, in any status whatsoever,
    # whose parent product line names this license."  A newly created DRAFT set
    # is already such a set, so the license counters are reconciled by traversal
    # here too.
    recompute_license_counts_for_line(store, line, now)
    return jsonify(response.ok_object(serialize("card_sets", rec))), 201


@app.route("/api/card-sets", methods=["GET"])
def list_card_sets():
    principal = authenticate(request.headers)
    require_role(
        principal,
        ["ProductManager", "ProductionPlanner", "QualityAnalyst", "PlatformAdmin"],
    )

    store = db.STORE
    items = list(store.all("card_sets"))
    product_line_id = requtil.filter_value("product_line_id")
    set_tier = requtil.filter_value("set_tier")
    status = requtil.filter_value("status")
    print_run_status = requtil.filter_value("print_run_status")
    if product_line_id is not None:
        items = [s for s in items if s["product_line_id"] == product_line_id]
    if set_tier is not None:
        items = [s for s in items if s["set_tier"] == set_tier]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if print_run_status is not None:
        items = [s for s in items if _derive(store, s) == print_run_status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(response.paginate([_serialize(s) for s in items], request.args)), 200


@app.route("/api/card-sets/<card_set_id>", methods=["GET"])
def get_card_set_route(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    return jsonify(response.ok_object(_serialize(get_card_set(card_set_id)))), 200


@app.route("/api/card-sets/<card_set_id>/submit", methods=["POST"])
def submit_card_set(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager"])

    store = db.STORE
    now = store.now()
    rec = get_card_set(card_set_id)

    _require_license_in_force(rec)

    line = get_line(rec["product_line_id"])
    if line["status"] != "READY_FOR_APPROVAL":
        raise ApiError(
            ERR_PRODUCT_LINE_NOT_READY, "The parent product line is not READY_FOR_APPROVAL"
        )

    approvals = _artwork_for(store, card_set_id)
    if not any(a["status"] == "APPROVED" for a in approvals):
        raise ApiError(
            ERR_ARTWORK_NOT_APPROVED, "This card set has no APPROVED artwork"
        )
    if any(a["status"] == "SUBMITTED" for a in approvals):
        raise ApiError(
            ERR_ARTWORK_APPROVAL_PENDING,
            "This card set still has artwork awaiting a decision",
        )

    if rec["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Card set is not DRAFT")

    rec["status"] = "UNDER_REVIEW"
    db.bump(rec, now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/card-sets/<card_set_id>/return-to-draft", methods=["POST"])
def return_to_draft(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager"])

    store = db.STORE
    now = store.now()
    rec = get_card_set(card_set_id)
    # PRD 3.1/3.2: the source state is UNDER_REVIEW, but PRD 2.8 also names
    # return-to-draft as the recovery path that re-pins an *APPROVED* set whose
    # rights pin went stale after a suspension or expiry: "those sets will be
    # refused at every subsequent mutation until they are returned to draft and
    # approved again".  The rollback is therefore available from APPROVED as
    # well as UNDER_REVIEW.  A set in any other status (DRAFT, IN_PRODUCTION,
    # PACKED_OUT) is refused.
    if rec["status"] not in ("UNDER_REVIEW", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE, "Card set is not UNDER_REVIEW")

    rec["status"] = "DRAFT"
    db.bump(rec, now)

    # Every SUBMITTED artwork approval for this set is rejected.
    for approval in _artwork_for(store, card_set_id):
        if approval["status"] == "SUBMITTED":
            approval["status"] = "REJECTED"
            db.touch(approval, now)

    # PRD 2.9: "a value that moves backwards (a set rolled out of approval ...)
    # immediately lowers the counter rather than leaving a stale increment
    # behind."  approved_set_count is recomputed by traversal.
    recompute_license_counts_for_line(store, get_line(rec["product_line_id"]), now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/card-sets/<card_set_id>/approve", methods=["POST"])
def approve_card_set(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager"])

    store = db.STORE
    now = store.now()
    rec = get_card_set(card_set_id)

    data = requtil.body()
    expected = requtil.required_int(data, "expected_card_set_version")

    # Ordered sequence (PRD 3.9): stale version, licence in force, continuous
    # activeness window, rights pin, then the tier rule.
    if expected != rec["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_card_set_version does not match the card set's version",
        )

    lic = _require_license_in_force(rec)
    if not _license_active_across(store, lic, card_set_id, now):
        raise ApiError(
            ERR_LICENSE_TERM_WINDOW_BREACH,
            "The license was not continuously ACTIVE across the artwork window",
        )
    _require_rights_pin_for_approval(rec)

    tier = rec["set_tier"]
    if tier == "BASE" and rec["print_run_quantity"] < 1:
        raise ApiError(
            ERR_PRINT_RUN_REQUIRED, "A BASE set requires a print_run_quantity of at least 1"
        )
    if tier in ("INSERT", "PREMIUM") and rec["print_run_quantity"] != 0:
        raise ApiError(
            ERR_PRINT_RUN_NOT_ALLOWED,
            "An INSERT or PREMIUM set must carry a print_run_quantity of 0",
        )

    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Card set is not UNDER_REVIEW")

    rec["status"] = "APPROVED"
    rec["rights_pinned_version"] = lic["rights_version"]
    db.bump(rec, now)

    db.bump(lic, now)
    recompute_license_counts(store, lic["id"], now)
    recompute_sets_per_case(store, get_line(rec["product_line_id"]), now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/card-sets/<card_set_id>/start-production", methods=["POST"])
def start_set_production(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductionPlanner"])

    store = db.STORE
    now = store.now()
    rec = get_card_set(card_set_id)

    from common import print_run_locked

    if not print_run_locked(store, rec):
        raise ApiError(
            ERR_PRINT_RUN_NOT_LOCKED, "CardSet.print_run_status is not LOCKED"
        )
    _require_rights_pin(rec)
    line = get_line(rec["product_line_id"])
    if line["status"] not in ("READY_FOR_APPROVAL", "APPROVED", "IN_PRODUCTION"):
        raise ApiError(
            ERR_PRODUCT_LINE_STATE_BLOCKED,
            "The parent product line is in a status that forbids this transition",
        )
    if rec["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Card set is not APPROVED")

    rec["status"] = "IN_PRODUCTION"
    db.bump(rec, now)
    recompute_card_set_aggregates(store, rec, now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/card-sets/<card_set_id>/pack-out", methods=["POST"])
def pack_out_card_set(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductionPlanner"])

    store = db.STORE
    now = store.now()
    rec = get_card_set(card_set_id)

    line = get_line(rec["product_line_id"])
    if line["status"] != "PACKED_OUT":
        raise ApiError(
            ERR_PRODUCT_LINE_NOT_PACKED_OUT, "The parent product line is not PACKED_OUT"
        )
    has_published = any(
        p["card_set_id"] == card_set_id and p["status"] == "PUBLISHED"
        for p in store.all("pack_configurations")
    )
    if not has_published:
        raise ApiError(
            ERR_PACK_CONFIG_MISSING, "This card set has no PUBLISHED pack configuration"
        )
    if rec["status"] != "IN_PRODUCTION":
        raise ApiError(ERR_INVALID_STATE, "Card set is not IN_PRODUCTION")

    rec["status"] = "PACKED_OUT"
    db.bump(rec, now)

    # Float every FULFILLED redemption under this set to CLOSED.
    for redemption in store.all("redemptions"):
        if redemption["card_set_id"] == card_set_id and redemption["status"] == "FULFILLED":
            redemption["status"] = "CLOSED"
            db.touch(redemption, now)

    recompute_card_set_aggregates(store, rec, now)
    recompute_allocated_cards(store, line, now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/card-sets/<card_set_id>/approval-chain", methods=["GET"])
def approval_chain(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager", "LicensingManager", "PlatformAdmin"])
    store = db.STORE
    rec = get_card_set(card_set_id)
    line = get_line(rec["product_line_id"])
    lic = store.get("licenses", line["license_id"])
    if lic is None:
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "The parent license does not resolve"
        )
    return jsonify(response.ok_object({
        "card_set": serialize("card_sets", rec),
        "product_line": serialize("product_lines", line),
        "license": serialize("licenses", lic),
    })), 200


# --- nested child collections ------------------------------------------------

@app.route("/api/card-sets/<card_set_id>/pack-configurations", methods=["GET"])
def list_set_pack_configs(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductManager", "ProductionPlanner", "PlatformAdmin"])
    get_card_set(card_set_id)
    store = db.STORE
    items = [p for p in store.all("pack_configurations") if p["card_set_id"] == card_set_id]
    status = requtil.filter_value("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(
        response.paginate([serialize("pack_configurations", p) for p in items], request.args)
    ), 200


@app.route("/api/card-sets/<card_set_id>/print-run-decisions", methods=["GET"])
def list_set_print_run_decisions(card_set_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductionPlanner", "ProductManager", "PlatformAdmin"])
    get_card_set(card_set_id)
    store = db.STORE
    items = [d for d in store.all("print_run_decisions") if d["card_set_id"] == card_set_id]
    status = requtil.filter_value("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(
        response.paginate([serialize("print_run_decisions", d) for d in items], request.args)
    ), 200


@app.route("/api/card-sets/<card_set_id>/print-run-summary", methods=["GET"])
def print_run_summary(card_set_id):
    principal = authenticate(request.headers)
    require_role(
        principal,
        ["ProductionPlanner", "ProductManager", "QualityAnalyst", "PlatformAdmin"],
    )
    store = db.STORE
    rec = get_card_set(card_set_id)
    from common import frozen_decision

    decision = frozen_decision(store, card_set_id)
    return jsonify(response.ok_object({
        "print_run_status": _derive(store, rec),
        "print_run_quantity": rec["print_run_quantity"],
        "announced": rec["announced"],
        "frozen_decision": serialize("print_run_decisions", decision) if decision else None,
    })), 200