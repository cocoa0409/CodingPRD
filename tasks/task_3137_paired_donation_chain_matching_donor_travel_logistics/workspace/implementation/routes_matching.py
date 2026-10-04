"""Routes: chain runs, chains, match offers, crossmatch reviews, slots."""

import uuid

from flask import Blueprint, request

import constants as C
from db import store, parse_iso, iso_z
from errors import (
    err_invalid_request,
    err_invalid_state,
    err_center_suspended,
    err_center_at_capacity,
    err_stale_version,
    err_review_deadline_passed,
    err_slot_taken,
    err_slot_overlap,
    err_slot_too_soon,
    err_pool_too_small,
    err_chain_locked,
    err_pending_offers,
    err_donor_not_cleared,
    err_recipient_not_listed,
    err_not_found,
)
from middleware import (
    actor,
    get_body,
    req_field,
    opt_field,
    req_enum,
    paginate,
    get_or_404,
    require_center_match,
)
from response import success_response
from services import (
    chain_offers,
    crossmatch_decision,
    recompute_all_active_chain_counts,
    recompute_chain_completion,
    run_chain_construction,
    serialize_chain_run,
    serialize_chain,
    serialize_offer,
    serialize_review,
    serialize_slot,
)

bp = Blueprint("matching", __name__, url_prefix="/nkr")


# ---------------------------------------------------------------------------
# Chain runs
# ---------------------------------------------------------------------------

@bp.route("/chain-runs", methods=["POST"])
def create_chain_run():
    actor("chain-runs", None)
    body = get_body()
    label = req_field(body, "run_label", str)
    rec = {
        "run_label": label,
        "started_at_utc": store.now_iso(),
        "run_state": "DRAFT",
        "algorithm_version": None,
        "candidate_pool_size": 0,
        "proposed_chain_count": 0,
    }
    store.insert(store.chain_runs, rec)
    return success_response(serialize_chain_run(rec), 201)


@bp.route("/chain-runs", methods=["GET"])
def list_chain_runs():
    actor("chain-runs", None)
    rows = list(store.chain_runs.values())
    v = request.args.get("run_state")
    if v is not None:
        rows = [r for r in rows if r["run_state"] == v]
    page, meta = paginate(rows)
    return success_response([serialize_chain_run(r) for r in page], 200, meta)


@bp.route("/chain-runs/<run_id>", methods=["GET"])
def get_chain_run(run_id):
    actor("chain-runs", "get")
    r = get_or_404(store.chain_runs, run_id)
    return success_response(serialize_chain_run(r))


@bp.route("/chain-runs/<run_id>/execute", methods=["POST"])
def execute_chain_run(run_id):
    actor("chain-runs", "execute")
    run = get_or_404(store.chain_runs, run_id)
    if run["run_state"] != "DRAFT":
        raise err_invalid_state()
    body = get_body()
    expected = body.get("expected_run_version")
    if expected is not None and expected != run["version"]:
        raise err_stale_version()
    pool_size = sum(1 for p in store.pairs.values() if p["pair_state"] == "IN_POOL")
    if pool_size < C.MIN_POOL_SIZE:
        raise err_pool_too_small()
    run["run_state"] = "EXECUTED"
    run["algorithm_version"] = C.CHAIN_ALGORITHM_VERSION
    run_chain_construction(run)
    store.touch(run)
    return success_response(serialize_chain_run(run))


@bp.route("/chain-runs/<run_id>/publish", methods=["POST"])
def publish_chain_run(run_id):
    actor("chain-runs", "publish")
    run = get_or_404(store.chain_runs, run_id)
    if run["run_state"] != "EXECUTED":
        raise err_invalid_state()
    run["run_state"] = "PUBLISHED"
    store.touch(run)
    for ch in store.chains.values():
        if ch["chain_run_id"] != run["id"] or ch["chain_state"] != "PROPOSED":
            continue
        ch["chain_state"] = "ACCEPTING"
        store.touch(ch)
        for o in chain_offers(ch["id"]):
            donor = store.donors.get(o["donor_id"])
            recipient = store.recipients.get(o["recipient_id"])
            if donor is not None and donor["chain_participation_state"] == "POOL":
                donor["chain_participation_state"] = "PROPOSED"
                store.touch(donor)
            if recipient is not None and recipient["chain_participation_state"] == "POOL":
                recipient["chain_participation_state"] = "PROPOSED"
                store.touch(recipient)
    return success_response(serialize_chain_run(run))


@bp.route("/chain-runs/<run_id>/supersede", methods=["POST"])
def supersede_chain_run(run_id):
    actor("chain-runs", "supersede")
    run = get_or_404(store.chain_runs, run_id)
    if run["run_state"] not in ("EXECUTED", "PUBLISHED"):
        raise err_invalid_state()
    for ch in store.chains.values():
        if ch["chain_run_id"] == run["id"] and ch["chain_state"] in (
            "LOCKED",
            "SCHEDULED",
            "EXECUTING",
            "COMPLETED",
        ):
            raise err_chain_locked()
    run["run_state"] = "SUPERSEDED"
    store.touch(run)
    for ch in store.chains.values():
        if ch["chain_run_id"] != run["id"]:
            continue
        if ch["chain_state"] in ("PROPOSED", "ACCEPTING"):
            ch["chain_state"] = "ABORTED"
            store.touch(ch)
        for o in chain_offers(ch["id"]):
            if o["offer_state"] in (
                "PENDING_CROSSMATCH",
                "CROSSMATCH_PASSED",
                "CENTER_ACCEPTED",
            ):
                o["offer_state"] = "OFFER_FAILED"
                o["offer_failure_reason"] = "CHAIN_BREAK_PROPAGATION"
                store.touch(o)
            donor = store.donors.get(o["donor_id"])
            recipient = store.recipients.get(o["recipient_id"])
            if donor is not None and donor["chain_participation_state"] == "PROPOSED":
                donor["chain_participation_state"] = "POOL"
                store.touch(donor)
            if recipient is not None and recipient["chain_participation_state"] == "PROPOSED":
                recipient["chain_participation_state"] = "POOL"
                store.touch(recipient)
        # revert pairs selected by this run back to IN_POOL
    for p in store.pairs.values():
        if p["pair_state"] == "IN_PROPOSED_CHAIN":
            # Only revert if the pair was part of this run's chains.
            in_run = any(
                o["chain_id"] in [c["id"] for c in store.chains.values() if c["chain_run_id"] == run["id"]]
                and (o["donor_id"] == p["donor_id"] or o["recipient_id"] == p["recipient_id"])
                for o in store.offers.values()
            )
            if in_run:
                p["pair_state"] = "IN_POOL"
                store.touch(p)
    return success_response(serialize_chain_run(run))


# ---------------------------------------------------------------------------
# Chains
# ---------------------------------------------------------------------------

@bp.route("/chains", methods=["GET"])
def list_chains():
    actor("chains", None)
    rows = list(store.chains.values())
    for param in ("chain_state", "chain_run_id", "starts_at_center_id", "starter_donor_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    page, meta = paginate(rows)
    return success_response([serialize_chain(r) for r in page], 200, meta)


@bp.route("/chains/<chain_id>", methods=["GET"])
def get_chain(chain_id):
    actor("chains", "get")
    ch = get_or_404(store.chains, chain_id)
    recompute_chain_completion(ch)
    return success_response(serialize_chain(ch))


@bp.route("/chains/<chain_id>/lock", methods=["POST"])
def lock_chain(chain_id):
    actor("chains", "lock")
    ch = get_or_404(store.chains, chain_id)
    if ch["chain_state"] != "ACCEPTING":
        raise err_invalid_state()
    offers = chain_offers(ch["id"])
    if not all(o["offer_state"] == "CENTER_ACCEPTED" for o in offers):
        raise err_pending_offers()
    body = get_body()
    expected = body.get("expected_chain_version")
    if expected is not None and expected != ch["version"]:
        raise err_stale_version()
    ch["chain_state"] = "LOCKED"
    store.touch(ch)
    for o in offers:
        donor = store.donors.get(o["donor_id"])
        recipient = store.recipients.get(o["recipient_id"])
        if donor is not None and donor["chain_participation_state"] == "PROPOSED":
            donor["chain_participation_state"] = "LOCKED"
            store.touch(donor)
        if recipient is not None and recipient["chain_participation_state"] == "PROPOSED":
            recipient["chain_participation_state"] = "LOCKED"
            store.touch(recipient)
        # pair -> LOCKED
        for p in store.pairs.values():
            if p["recipient_id"] == o["recipient_id"] and p["pair_state"] == "IN_PROPOSED_CHAIN":
                p["pair_state"] = "LOCKED"
                store.touch(p)
    return success_response(serialize_chain(ch))


@bp.route("/chains/<chain_id>/schedule", methods=["POST"])
def schedule_chain(chain_id):
    actor("chains", "schedule")
    ch = get_or_404(store.chains, chain_id)
    if ch["chain_state"] != "LOCKED":
        raise err_invalid_state()
    body = get_body()
    expected = body.get("expected_chain_version")
    if expected is not None and expected != ch["version"]:
        raise err_stale_version()
    scheduled_date = req_field(body, "scheduled_date", str)
    try:
        parse_iso(scheduled_date)
    except Exception:
        raise err_invalid_request("scheduled_date must be ISO-8601")
    slot_ids = req_field(body, "slot_ids", list)
    slots = []
    for sid in slot_ids:
        if not isinstance(sid, str):
            raise err_invalid_request("slot_ids must be strings")
        slots.append(get_or_404(store.slots, sid))

    # Suspended-center guard for participating centers.
    offers = chain_offers(ch["id"])
    participating_center_ids = set()
    for o in offers:
        participating_center_ids.add(o["donor_center_id"])
        participating_center_ids.add(o["recipient_center_id"])
    participating_center_ids.add(ch.get("starts_at_center_id"))
    for cid in participating_center_ids:
        c = store.centers.get(cid)
        if c is not None and c["participation_status"] == "SUSPENDED":
            raise err_center_suspended()

    # Validate slots: OPEN, lead time, overlap (existing + within request), room kinds.
    now = store.now()
    lead = now.timestamp() + C.MIN_SCHEDULE_LEAD_HOURS * 3600
    seen_intervals = {}
    for slot in slots:
        if slot["slot_state"] != "OPEN":
            raise err_slot_taken()
        start = parse_iso(slot["slot_start_utc"])
        end = parse_iso(slot["slot_end_utc"])
        if start.timestamp() < lead:
            raise err_slot_too_soon()
        # Overlap against persisted RESERVED/CONSUMED slots at same center.
        for other in store.slots.values():
            if other["id"] == slot["id"]:
                continue
            if other["center_id"] != slot["center_id"]:
                continue
            if other["slot_state"] not in ("RESERVED", "CONSUMED"):
                continue
            os_ = parse_iso(other["slot_start_utc"])
            oe = parse_iso(other["slot_end_utc"])
            if start < oe and os_ < end:
                raise err_slot_overlap()
        # Overlap within the request's own slot set at the same center.
        for (oc, os_, oe) in seen_intervals.get(slot["center_id"], []):
            if start < oe and os_ < end:
                raise err_slot_overlap()
        seen_intervals.setdefault(slot["center_id"], []).append((slot["center_id"], start, end))

    # Every offer must get at least one slot at both donor and recipient centers.
    per_offer = {o["id"]: {"donor": 0, "recipient": 0} for o in offers}
    if len(slots) == 2 * len(offers):
        # Positional mapping: slot[2i] = donor center of offer i, slot[2i+1] = recipient.
        for i, o in enumerate(offers):
            ds, rs = slots[2 * i], slots[2 * i + 1]
            if ds["center_id"] == o["donor_center_id"]:
                per_offer[o["id"]]["donor"] += 1
            if rs["center_id"] == o["recipient_center_id"]:
                per_offer[o["id"]]["recipient"] += 1
    else:
        # Greedy mapping by center.
        remaining = list(slots)
        for o in offers:
            for s in list(remaining):
                if s["center_id"] == o["donor_center_id"]:
                    per_offer[o["id"]]["donor"] += 1
                    remaining.remove(s)
                    break
            for s in list(remaining):
                if s["center_id"] == o["recipient_center_id"]:
                    per_offer[o["id"]]["recipient"] += 1
                    remaining.remove(s)
                    break
    for oid, counts in per_offer.items():
        if counts["donor"] < 1 or counts["recipient"] < 1:
            raise err_invalid_request(
                "Every offer requires a slot at both donor and recipient centers"
            )

    # Capacity check.
    recompute_all_active_chain_counts()
    for cid in participating_center_ids:
        c = store.centers.get(cid)
        if c is None:
            continue
        if c["active_chain_count"] >= c["max_concurrent_chains"]:
            raise err_center_at_capacity()

    # Reserve slots atomically.
    group_id = str(uuid.uuid4())
    if len(slots) == 2 * len(offers):
        slot_offer_map = {slots[2 * i]["id"]: offers[i]["id"] for i in range(len(offers))}
        slot_offer_map.update({slots[2 * i + 1]["id"]: offers[i]["id"] for i in range(len(offers))})
    else:
        # rebuild greedy assignment
        slot_offer_map = {}
        remaining = list(slots)
        for o in offers:
            for s in list(remaining):
                if s["center_id"] == o["donor_center_id"] and s["id"] not in slot_offer_map:
                    slot_offer_map[s["id"]] = o["id"]
                    remaining.remove(s)
                    break
            for s in list(remaining):
                if s["center_id"] == o["recipient_center_id"] and s["id"] not in slot_offer_map:
                    slot_offer_map[s["id"]] = o["id"]
                    remaining.remove(s)
                    break
    for slot in slots:
        slot["slot_state"] = "RESERVED"
        slot["reserved_for_chain_id"] = ch["id"]
        slot["reserved_for_offer_id"] = slot_offer_map.get(slot["id"])
        slot["simultaneous_group_id"] = group_id
        store.touch(slot)

    ch["chain_state"] = "SCHEDULED"
    ch["scheduled_date"] = scheduled_date
    store.touch(ch)
    for o in offers:
        if o["offer_state"] == "CENTER_ACCEPTED":
            o["offer_state"] = "SCHEDULED"
            store.touch(o)
        donor = store.donors.get(o["donor_id"])
        recipient = store.recipients.get(o["recipient_id"])
        if donor is not None:
            if donor["surgery_state"] == "PRE_SURGERY":
                donor["surgery_state"] = "SURGERY_SCHEDULED"
            donor["chain_participation_state"] = "COMMITTED"
            store.touch(donor)
        if recipient is not None:
            recipient["chain_participation_state"] = "COMMITTED"
            store.touch(recipient)
    recompute_all_active_chain_counts()
    return success_response(serialize_chain(ch))


@bp.route("/chains/<chain_id>/start-execution", methods=["POST"])
def start_execution(chain_id):
    actor("chains", "start-execution")
    ch = get_or_404(store.chains, chain_id)
    if ch["chain_state"] != "SCHEDULED":
        raise err_invalid_state()
    offers = chain_offers(ch["id"])
    if offers:
        first = store.donors.get(offers[0]["donor_id"])
        if first is None or first["surgery_state"] != "SURGERY_SCHEDULED":
            raise err_invalid_state("First donor not in SURGERY_SCHEDULED")
    ch["chain_state"] = "EXECUTING"
    store.touch(ch)
    return success_response(serialize_chain(ch))


# ---------------------------------------------------------------------------
# Match offers + crossmatch reviews
# ---------------------------------------------------------------------------

@bp.route("/match-offers", methods=["GET"])
def list_offers():
    actor("match-offers", None)
    rows = list(store.offers.values())
    for param in ("chain_id", "donor_id", "recipient_id", "donor_center_id", "recipient_center_id", "offer_state"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    page, meta = paginate(rows)
    return success_response([serialize_offer(r) for r in page], 200, meta)


@bp.route("/match-offers/<offer_id>", methods=["GET"])
def get_offer(offer_id):
    actor("match-offers", "get")
    o = get_or_404(store.offers, offer_id)
    return success_response(serialize_offer(o))


@bp.route("/match-offers/<offer_id>/crossmatch-review", methods=["POST"])
def crossmatch_review(offer_id):
    user_id, role = actor("match-offers", "crossmatch-review")
    o = get_or_404(store.offers, offer_id)
    recipient_center = get_or_404(store.centers, o["recipient_center_id"])
    if recipient_center["participation_status"] != "ACTIVE":
        raise err_center_suspended()
    donor = get_or_404(store.donors, o["donor_id"])
    if donor["medical_status"] != "CLEARED":
        raise err_donor_not_cleared()
    recipient = get_or_404(store.recipients, o["recipient_id"])
    if recipient["medical_status"] != "LISTED":
        raise err_recipient_not_listed()
    require_center_match(user_id, role, o["recipient_center_id"])
    if o["offer_state"] != "PENDING_CROSSMATCH":
        raise err_invalid_state()
    if store.now() >= parse_iso(o["crossmatch_deadline_utc"]):
        raise err_review_deadline_passed()
    body = get_body()
    virtual_result = req_enum(body, "virtual_result", ("NEGATIVE", "WEAK_POSITIVE", "STRONG_POSITIVE", "INDETERMINATE"))
    flow = req_field(body, "flow_cytometry_channel_shift", int)
    if flow < 0 or flow > 1024:
        raise err_invalid_request("flow_cytometry_channel_shift must be 0..1024")
    mfi = req_field(body, "dsa_mfi_max", int)
    if mfi < 0 or mfi > 30000:
        raise err_invalid_request("dsa_mfi_max must be 0..30000")
    notes = opt_field(body, "review_notes", str, None)
    decision = crossmatch_decision(virtual_result, mfi)
    review = {
        "match_offer_id": o["id"],
        "reviewer_center_id": o["recipient_center_id"],
        "virtual_result": virtual_result,
        "flow_cytometry_channel_shift": flow,
        "dsa_mfi_max": mfi,
        "decision": decision,
        "decided_at_utc": store.now_iso(),
        "review_notes": notes,
    }
    store.insert(store.reviews, review)
    if decision == "PASS":
        o["offer_state"] = "CROSSMATCH_PASSED"
    else:
        o["offer_state"] = "CROSSMATCH_FAILED"
        o["offer_failure_reason"] = "CROSSMATCH_POSITIVE"
        # Failed offer cannot proceed; chain aborts.
        ch = store.chains.get(o["chain_id"])
        if ch is not None and ch["chain_state"] in ("PROPOSED", "ACCEPTING"):
            ch["chain_state"] = "ABORTED"
            store.touch(ch)
            for other in chain_offers(ch["id"]):
                if other["id"] != o["id"] and other["offer_state"] in (
                    "PENDING_CROSSMATCH",
                    "CROSSMATCH_PASSED",
                ):
                    other["offer_state"] = "OFFER_FAILED"
                    other["offer_failure_reason"] = "CHAIN_BREAK_PROPAGATION"
                    store.touch(other)
    store.touch(o)
    return success_response(serialize_review(review))


@bp.route("/match-offers/<offer_id>/center-accept", methods=["POST"])
def center_accept(offer_id):
    user_id, role = actor("match-offers", "center-accept")
    o = get_or_404(store.offers, offer_id)
    recipient_center = get_or_404(store.centers, o["recipient_center_id"])
    donor_center = get_or_404(store.centers, o["donor_center_id"])
    if recipient_center["participation_status"] != "ACTIVE":
        raise err_center_suspended()
    if donor_center["participation_status"] != "ACTIVE":
        raise err_center_suspended()
    require_center_match(user_id, role, o["recipient_center_id"])
    if o["offer_state"] != "CROSSMATCH_PASSED":
        raise err_invalid_state()
    if store.now() >= parse_iso(o["center_accept_deadline_utc"]):
        raise err_review_deadline_passed()
    o["offer_state"] = "CENTER_ACCEPTED"
    o["accepted_at_utc"] = store.now_iso()
    store.touch(o)
    return success_response(serialize_offer(o))


@bp.route("/match-offers/<offer_id>/center-decline", methods=["POST"])
def center_decline(offer_id):
    user_id, role = actor("match-offers", "center-decline")
    o = get_or_404(store.offers, offer_id)
    require_center_match(user_id, role, o["recipient_center_id"])
    if o["offer_state"] != "CROSSMATCH_PASSED":
        raise err_invalid_state()
    o["offer_state"] = "OFFER_FAILED"
    o["offer_failure_reason"] = "CENTER_DECLINE"
    store.touch(o)
    return success_response(serialize_offer(o))


# ---------------------------------------------------------------------------
# Crossmatch review reads
# ---------------------------------------------------------------------------

@bp.route("/crossmatch-reviews", methods=["GET"])
def list_reviews():
    actor("crossmatch-reviews", None)
    rows = list(store.reviews.values())
    for param in ("match_offer_id", "reviewer_center_id", "decision"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    page, meta = paginate(rows)
    return success_response([serialize_review(r) for r in page], 200, meta)


@bp.route("/crossmatch-reviews/<review_id>", methods=["GET"])
def get_review(review_id):
    actor("crossmatch-reviews", "get")
    r = get_or_404(store.reviews, review_id)
    return success_response(serialize_review(r))


# ---------------------------------------------------------------------------
# Surgery schedule slots
# ---------------------------------------------------------------------------

ROOM_KINDS = ("NEPHRECTOMY_OR", "TRANSPLANT_OR", "BACK_OR")


@bp.route("/slots", methods=["POST"])
def create_slot():
    actor("slots", None)
    body = get_body()
    center_id = req_field(body, "center_id", str)
    get_or_404(store.centers, center_id)
    start_s = req_field(body, "slot_start_utc", str)
    end_s = req_field(body, "slot_end_utc", str)
    room_kind = req_enum(body, "room_kind", ROOM_KINDS)
    try:
        start = parse_iso(start_s)
        end = parse_iso(end_s)
    except Exception:
        raise err_invalid_request("slot timestamps must be ISO-8601")
    if not (start < end):
        raise err_invalid_request("slot_start_utc must be before slot_end_utc")
    if (end - start).total_seconds() < C.SLOT_MIN_HOURS * 3600:
        raise err_invalid_request("slot duration below SLOT_MIN_HOURS")
    # Overlap guard also applies on creation against RESERVED/CONSUMED slots.
    for other in store.slots.values():
        if other["center_id"] != center_id:
            continue
        if other["slot_state"] not in ("RESERVED", "CONSUMED"):
            continue
        os_ = parse_iso(other["slot_start_utc"])
        oe = parse_iso(other["slot_end_utc"])
        if start < oe and os_ < end:
            raise err_slot_overlap()
    rec = {
        "center_id": center_id,
        "slot_start_utc": iso_z(start),
        "slot_end_utc": iso_z(end),
        "room_kind": room_kind,
        "slot_state": "OPEN",
        "reserved_for_chain_id": None,
        "reserved_for_offer_id": None,
        "simultaneous_group_id": None,
        "consumed_at_utc": None,
    }
    store.insert(store.slots, rec)
    return success_response(serialize_slot(rec), 201)


@bp.route("/slots", methods=["GET"])
def list_slots():
    actor("slots", None)
    rows = list(store.slots.values())
    for param in ("center_id", "slot_state", "reserved_for_chain_id", "reserved_for_offer_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    page, meta = paginate(rows)
    return success_response([serialize_slot(r) for r in page], 200, meta)


@bp.route("/slots/<slot_id>", methods=["GET"])
def get_slot(slot_id):
    actor("slots", "get")
    s = get_or_404(store.slots, slot_id)
    return success_response(serialize_slot(s))


@bp.route("/slots/<slot_id>/release", methods=["POST"])
def release_slot(slot_id):
    actor("slots", "release")
    s = get_or_404(store.slots, slot_id)
    if s["slot_state"] != "RESERVED":
        raise err_invalid_state()
    ch = store.chains.get(s.get("reserved_for_chain_id"))
    if ch is not None and ch["chain_state"] in ("EXECUTING", "COMPLETED"):
        raise err_chain_locked()
    s["slot_state"] = "RELEASED"
    s["reserved_for_chain_id"] = None
    s["reserved_for_offer_id"] = None
    s["simultaneous_group_id"] = None
    store.touch(s)
    return success_response(serialize_slot(s))
