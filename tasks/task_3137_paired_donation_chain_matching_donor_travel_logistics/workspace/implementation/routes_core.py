"""Routes: logical clock, centers, donors, recipients, pairs."""

from flask import Blueprint, request

import constants as C
from db import store, parse_iso
from errors import (
    err_invalid_request,
    err_invalid_state,
    err_center_invalid_state,
    err_center_suspended,
    err_donor_not_cleared,
    err_donor_post_nephrectomy,
    err_recipient_not_listed,
    err_pair_not_incompatible,
    err_stale_version,
)
from middleware import (
    actor,
    get_body,
    req_field,
    opt_field,
    req_enum,
    opt_enum,
    paginate,
    get_or_404,
    require_center_match,
)
from response import success_response
from services import (
    abo_compatible,
    unacceptable_antigen_hit,
    apply_time_transitions,
    create_chain_break,
    recompute_reputation,
    recompute_donor_travel,
    recompute_all_active_chain_counts,
    serialize_center,
    serialize_donor,
    serialize_recipient,
    serialize_pair,
)

bp = Blueprint("core", __name__, url_prefix="/nkr")

ABO_TYPES = ("A", "B", "AB", "O")
DONOR_KINDS = ("PAIRED", "ALTRUISTIC", "BRIDGE")
CENTER_TIERS = ("STANDARD", "PREFERRED", "NATIONAL_HUB")
DISSOLUTION_REASONS = ("NONE", "RECIPIENT_TRANSPLANTED", "DONOR_WITHDRAWN", "MEDICAL_DECLINE", "CHAIN_BROKEN")


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    actor("_clock", "set_current_utc")
    body = get_body()
    to = req_field(body, "to_iso8601", str)
    try:
        dt = parse_iso(to)
    except Exception:
        raise err_invalid_request("to_iso8601 must be a valid ISO-8601 timestamp")
    store.set_clock(dt)
    apply_time_transitions()
    return success_response({"current_utc": store.now_iso()})


# ---------------------------------------------------------------------------
# Centers
# ---------------------------------------------------------------------------

@bp.route("/centers", methods=["POST"])
def create_center():
    actor("centers", None)
    body = get_body()
    center_code = req_field(body, "center_code", str)
    name = req_field(body, "name", str)
    region_code = req_field(body, "region_code", str)
    tier = req_enum(body, "tier", CENTER_TIERS)
    mcc = req_field(body, "max_concurrent_chains", int)
    rec = {
        "center_code": center_code,
        "name": name,
        "region_code": region_code,
        "tier": tier,
        "max_concurrent_chains": mcc,
        "participation_status": "ACTIVE",
        "failed_outcome_count": 0,
        "shipped_organ_count": 0,
        "probed_cold_ischemia_violations": 0,
        "reputation_score_bps": C.REPUTATION_BASE_BPS,
        "active_chain_count": 0,
    }
    store.insert(store.centers, rec)
    return success_response(serialize_center(rec), 201)


@bp.route("/centers", methods=["GET"])
def list_centers():
    actor("centers", None)
    rows = list(store.centers.values())
    region = request.args.get("region_code")
    status = request.args.get("participation_status")
    if region:
        rows = [r for r in rows if r["region_code"] == region]
    if status:
        rows = [r for r in rows if r["participation_status"] == status]
    page, meta = paginate(rows)
    return success_response([serialize_center(r) for r in page], 200, meta)


@bp.route("/centers/<center_id>", methods=["GET"])
def get_center(center_id):
    actor("centers", "get")
    c = get_or_404(store.centers, center_id)
    recompute_all_active_chain_counts()
    return success_response(serialize_center(c))


@bp.route("/centers/<center_id>/probate", methods=["POST"])
def probate_center(center_id):
    actor("centers", "probate")
    c = get_or_404(store.centers, center_id)
    if c["participation_status"] != "ACTIVE":
        raise err_center_invalid_state()
    if not (
        c["probed_cold_ischemia_violations"] >= C.PROBATION_CIT_VIOLATIONS
        or c["failed_outcome_count"] >= C.PROBATION_FAILURES
    ):
        raise err_center_invalid_state(
            "Probation thresholds not met"
        )
    c["participation_status"] = "PROBATION"
    store.touch(c)
    return success_response(serialize_center(c))


@bp.route("/centers/<center_id>/suspend", methods=["POST"])
def suspend_center(center_id):
    actor("centers", "suspend")
    c = get_or_404(store.centers, center_id)
    if c["participation_status"] not in ("ACTIVE", "PROBATION"):
        raise err_center_invalid_state()
    body = get_body()
    expected = body.get("expected_center_version")
    if expected is not None and expected != c["version"]:
        raise err_stale_version()
    c["participation_status"] = "SUSPENDED"
    store.touch(c)
    # Cascade: reserved slots released; CENTER_ACCEPTED offers roll back;
    # PENDING_CROSSMATCH / CROSSMATCH_PASSED offers fail.
    for slot in store.slots.values():
        if slot["center_id"] == c["id"] and slot["slot_state"] == "RESERVED":
            slot["slot_state"] = "RELEASED"
            slot["reserved_for_chain_id"] = None
            slot["reserved_for_offer_id"] = None
            slot["simultaneous_group_id"] = None
            store.touch(slot)
    for offer in store.offers.values():
        at_center = (
            offer["donor_center_id"] == c["id"] or offer["recipient_center_id"] == c["id"]
        )
        if not at_center:
            continue
        if offer["offer_state"] == "CENTER_ACCEPTED":
            offer["offer_state"] = "CROSSMATCH_PASSED"
            store.touch(offer)
        if offer["offer_state"] in ("PENDING_CROSSMATCH", "CROSSMATCH_PASSED"):
            offer["offer_state"] = "OFFER_FAILED"
            offer["offer_failure_reason"] = "CHAIN_BREAK_PROPAGATION"
            store.touch(offer)
    recompute_all_active_chain_counts()
    return success_response(serialize_center(c))


@bp.route("/centers/<center_id>/reinstate", methods=["POST"])
def reinstate_center(center_id):
    actor("centers", "reinstate")
    c = get_or_404(store.centers, center_id)
    if c["participation_status"] == "PROBATION":
        if not (
            c["probed_cold_ischemia_violations"] < C.PROBATION_CIT_VIOLATIONS
            and c["failed_outcome_count"] < C.PROBATION_FAILURES
        ):
            raise err_center_invalid_state("Reinstatement thresholds not met")
    elif c["participation_status"] == "SUSPENDED":
        for ch in store.chains.values():
            if ch["chain_state"] not in ("LOCKED", "SCHEDULED", "EXECUTING"):
                continue
            involved = ch.get("starts_at_center_id") == c["id"] or any(
                o["chain_id"] == ch["id"]
                and (o["donor_center_id"] == c["id"] or o["recipient_center_id"] == c["id"])
                for o in store.offers.values()
            )
            if involved:
                raise err_center_invalid_state(
                    "Center is referenced by an active chain"
                )
    else:
        raise err_center_invalid_state()
    c["participation_status"] = "ACTIVE"
    store.touch(c)
    return success_response(serialize_center(c))


# ---------------------------------------------------------------------------
# Donors
# ---------------------------------------------------------------------------

def _donor_from_body(body):
    external_ref = req_field(body, "external_ref", str)
    home_center_id = req_field(body, "home_center_id", str)
    get_or_404(store.centers, home_center_id)
    abo_type = req_enum(body, "abo_type", ABO_TYPES)
    hla_a = req_field(body, "hla_a", str)
    hla_b = req_field(body, "hla_b", str)
    hla_drb1 = req_field(body, "hla_drb1", str)
    kdri = req_field(body, "kdri_score", int)
    if kdri < 20 or kdri > 250:
        raise err_invalid_request("kdri_score must be 20..250")
    age = req_field(body, "age_at_registration", int)
    if age < 18:
        raise err_invalid_request("age_at_registration must be >= 18")
    donor_kind = req_enum(body, "donor_kind", DONOR_KINDS)
    return {
        "external_ref": external_ref,
        "home_center_id": home_center_id,
        "abo_type": abo_type,
        "hla_a": hla_a,
        "hla_b": hla_b,
        "hla_drb1": hla_drb1,
        "kdri_score": kdri,
        "age_at_registration": age,
        "donor_kind": donor_kind,
        "medical_status": "CLEARED",
        "surgery_state": "PRE_SURGERY",
        "chain_participation_state": "POOL",
        "protection_policy_id": None,
        "priority_waitlist_status": "NONE",
        "traveled_distance_miles": 0,
        "complications_recorded": 0,
    }


@bp.route("/donors", methods=["POST"])
def create_donor():
    actor("donors", None)
    body = get_body()
    rec = _donor_from_body(body)
    store.insert(store.donors, rec)
    return success_response(serialize_donor(rec), 201)


@bp.route("/donors", methods=["GET"])
def list_donors():
    actor("donors", None)
    rows = list(store.donors.values())
    for param in ("home_center_id", "medical_status", "donor_kind", "chain_participation_state", "protection_policy_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    page, meta = paginate(rows)
    return success_response([serialize_donor(r) for r in page], 200, meta)


@bp.route("/donors/<donor_id>", methods=["GET"])
def get_donor(donor_id):
    actor("donors", "get")
    d = get_or_404(store.donors, donor_id)
    recompute_donor_travel(d)
    return success_response(serialize_donor(d))


def _fail_offers_referencing_donor(donor_id):
    for o in store.offers.values():
        if o["donor_id"] == donor_id and o["offer_state"] in (
            "PENDING_CROSSMATCH",
            "CROSSMATCH_PASSED",
            "CENTER_ACCEPTED",
        ):
            o["offer_state"] = "OFFER_FAILED"
            o["offer_failure_reason"] = "DONOR_UNAVAILABLE"
            store.touch(o)


def _donor_break_if_active(donor, trigger_kind):
    """If the donor is in an active (LOCKED/SCHEDULED/EXECUTING) chain, emit a break."""
    from services import _find_offer_for_donor_in_chain

    prior = donor["chain_participation_state"]
    offer = _find_offer_for_donor_in_chain(donor["id"])
    if offer is not None:
        chain = store.chains[offer["chain_id"]]
        create_chain_break(chain, offer, trigger_kind)
        if prior == "COMMITTED":
            donor["chain_participation_state"] = "BROKEN"
        else:
            donor["chain_participation_state"] = "WITHDRAWN"
    else:
        # Donor in PROPOSED/ACCEPTING chain: fail pending offers only.
        _fail_offers_referencing_donor(donor["id"])
        if donor["chain_participation_state"] not in ("COMPLETED", "BROKEN"):
            donor["chain_participation_state"] = "WITHDRAWN"


@bp.route("/donors/<donor_id>/medical-hold", methods=["POST"])
def donor_medical_hold(donor_id):
    actor("donors", "medical-hold")
    d = get_or_404(store.donors, donor_id)
    if d["medical_status"] != "CLEARED":
        raise err_invalid_state()
    if d["surgery_state"] == "NEPHRECTOMY_DONE":
        raise err_donor_post_nephrectomy()
    d["medical_status"] = "ON_HOLD"
    _fail_offers_referencing_donor(d["id"])
    store.touch(d)
    return success_response(serialize_donor(d))


@bp.route("/donors/<donor_id>/medical-release", methods=["POST"])
def donor_medical_release(donor_id):
    actor("donors", "medical-release")
    d = get_or_404(store.donors, donor_id)
    if d["medical_status"] != "ON_HOLD":
        raise err_invalid_state()
    d["medical_status"] = "CLEARED"
    store.touch(d)
    return success_response(serialize_donor(d))


@bp.route("/donors/<donor_id>/withdraw", methods=["POST"])
def donor_withdraw(donor_id):
    actor("donors", "withdraw")
    d = get_or_404(store.donors, donor_id)
    if d["medical_status"] not in ("CLEARED", "ON_HOLD"):
        raise err_invalid_state()
    if d["surgery_state"] == "NEPHRECTOMY_DONE":
        raise err_donor_post_nephrectomy()
    d["medical_status"] = "WITHDRAWN"
    _donor_break_if_active(d, "DONOR_WITHDRAWAL")
    # Dissolve any pair still open for this donor.
    for p in store.pairs.values():
        if p["donor_id"] == d["id"] and p["pair_state"] in ("VERIFIED", "IN_POOL", "IN_PROPOSED_CHAIN"):
            p["pair_state"] = "DISSOLVED"
            p["dissolution_reason"] = "DONOR_WITHDRAWN"
            store.touch(p)
    store.touch(d)
    return success_response(serialize_donor(d))


@bp.route("/donors/<donor_id>/deceased", methods=["POST"])
def donor_deceased(donor_id):
    actor("donors", "deceased")
    d = get_or_404(store.donors, donor_id)
    if d["medical_status"] == "DECEASED":
        raise err_invalid_state()
    d["medical_status"] = "DECEASED"
    _donor_break_if_active(d, "DONOR_DECEASED")
    store.touch(d)
    return success_response(serialize_donor(d))


@bp.route("/donors/<donor_id>/complete-nephrectomy", methods=["POST"])
def donor_complete_nephrectomy(donor_id):
    user_id, role = actor("donors", "complete-nephrectomy")
    d = get_or_404(store.donors, donor_id)
    center = get_or_404(store.centers, d["home_center_id"])
    if center["participation_status"] == "SUSPENDED":
        raise err_center_suspended()
    if d["medical_status"] != "CLEARED":
        raise err_donor_not_cleared()
    require_center_match(user_id, role, d["home_center_id"])
    if d["surgery_state"] != "SURGERY_SCHEDULED":
        raise err_invalid_state()

    d["surgery_state"] = "NEPHRECTOMY_DONE"
    d["chain_participation_state"] = "COMPLETED"
    d["priority_waitlist_status"] = "ELIGIBLE"
    store.touch(d)
    nephrectomy_ts = d["updated_at"]
    d["nephrectomy_completed_at_utc"] = nephrectomy_ts

    # Mint DonorProtectionPolicy.
    policy = {
        "donor_id": d["id"],
        "policy_state": "ACTIVE",
        "covered_complication_max_cents": C.COMPLICATION_COVER_CENTS,
        "covered_lost_wages_max_cents": C.LOST_WAGES_COVER_CENTS,
        "complications_paid_cents": 0,
        "lost_wages_paid_cents": 0,
        "travel_reimbursed_cents": 0,
        "priority_kidney_claim_available": True,
    }
    store.insert(store.policies, policy)
    d["protection_policy_id"] = policy["id"]

    # Advance the offer referencing this donor.
    for o in store.offers.values():
        if o["donor_id"] == d["id"] and o["offer_state"] == "SCHEDULED":
            o["offer_state"] = "DONOR_SURGERY_DONE"
            store.touch(o)
    # Consume reserved NEPHRECTOMY_OR slots at the donor center for the chain.
    for slot in store.slots.values():
        if (
            slot["slot_state"] == "RESERVED"
            and slot["center_id"] == d["home_center_id"]
            and slot["room_kind"] == "NEPHRECTOMY_OR"
            and slot.get("reserved_for_offer_id")
            and store.offers.get(slot["reserved_for_offer_id"], {}).get("donor_id") == d["id"]
        ):
            slot["slot_state"] = "CONSUMED"
            slot["consumed_at_utc"] = store.now_iso()
            store.touch(slot)
    return success_response(serialize_donor(d))


@bp.route("/donors/<donor_id>/fail-preop", methods=["POST"])
def donor_fail_preop(donor_id):
    actor("donors", "fail-preop")
    d = get_or_404(store.donors, donor_id)
    if d["surgery_state"] not in ("PRE_SURGERY", "SURGERY_SCHEDULED"):
        raise err_invalid_state()
    d["surgery_state"] = "FAILED_PREOP"
    from services import _find_offer_for_donor_in_chain

    offer = _find_offer_for_donor_in_chain(d["id"])
    if offer is not None:
        chain = store.chains[offer["chain_id"]]
        create_chain_break(chain, offer, "SURGERY_ABORTED")
    else:
        _fail_offers_referencing_donor(d["id"])
    store.touch(d)
    return success_response(serialize_donor(d))


# ---------------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------------

@bp.route("/recipients", methods=["POST"])
def create_recipient():
    actor("recipients", None)
    body = get_body()
    external_ref = req_field(body, "external_ref", str)
    home_center_id = req_field(body, "home_center_id", str)
    get_or_404(store.centers, home_center_id)
    abo_type = req_enum(body, "abo_type", ABO_TYPES)
    cpra = req_field(body, "cpra_percent", int)
    if cpra < 0 or cpra > 100:
        raise err_invalid_request("cpra_percent must be 0..100")
    ua = opt_field(body, "unacceptable_antigens", list, [])
    paired_donor_id = opt_field(body, "paired_donor_id", str, None)
    if paired_donor_id is not None:
        get_or_404(store.donors, paired_donor_id)
    rec = {
        "external_ref": external_ref,
        "home_center_id": home_center_id,
        "abo_type": abo_type,
        "cpra_percent": cpra,
        "unacceptable_antigens": ua,
        "medical_status": "LISTED",
        "chain_participation_state": "POOL",
        "paired_donor_id": paired_donor_id,
        "listed_at_utc": store.now_iso(),
        "transplant_completed_at_utc": None,
        "priority_boost_active": False,
        # Recipient HLA profile fields default to empty loci when not supplied.
        "hla_a": opt_field(body, "hla_a", str, ""),
        "hla_b": opt_field(body, "hla_b", str, ""),
        "hla_drb1": opt_field(body, "hla_drb1", str, ""),
    }
    store.insert(store.recipients, rec)
    # Priority enrollment: a prior donor who registers as a recipient.
    if paired_donor_id is not None:
        pass
    donor_same = None
    for dd in store.donors.values():
        if dd["external_ref"] == external_ref and dd["surgery_state"] == "NEPHRECTOMY_DONE":
            donor_same = dd
            break
    if donor_same is not None and donor_same.get("priority_waitlist_status") == "ELIGIBLE":
        donor_same["priority_waitlist_status"] = "ENROLLED"
        rec["priority_boost_active"] = True
    return success_response(serialize_recipient(rec), 201)


@bp.route("/recipients", methods=["GET"])
def list_recipients():
    actor("recipients", None)
    rows = list(store.recipients.values())
    for param in ("home_center_id", "medical_status", "chain_participation_state", "paired_donor_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    pb = request.args.get("priority_boost_active")
    if pb is not None:
        want = pb.lower() == "true"
        rows = [r for r in rows if bool(r.get("priority_boost_active")) == want]
    page, meta = paginate(rows)
    return success_response([serialize_recipient(r) for r in page], 200, meta)


@bp.route("/recipients/<recipient_id>", methods=["GET"])
def get_recipient(recipient_id):
    actor("recipients", "get")
    r = get_or_404(store.recipients, recipient_id)
    return success_response(serialize_recipient(r))


def _fail_offers_referencing_recipient(recipient_id):
    for o in store.offers.values():
        if o["recipient_id"] == recipient_id and o["offer_state"] in (
            "PENDING_CROSSMATCH",
            "CROSSMATCH_PASSED",
            "CENTER_ACCEPTED",
        ):
            o["offer_state"] = "OFFER_FAILED"
            o["offer_failure_reason"] = "DONOR_UNAVAILABLE"
            store.touch(o)


@bp.route("/recipients/<recipient_id>/medical-hold", methods=["POST"])
def recipient_medical_hold(recipient_id):
    actor("recipients", "medical-hold")
    r = get_or_404(store.recipients, recipient_id)
    if r["medical_status"] != "LISTED":
        raise err_invalid_state()
    r["medical_status"] = "ON_HOLD"
    _fail_offers_referencing_recipient(r["id"])
    store.touch(r)
    return success_response(serialize_recipient(r))


@bp.route("/recipients/<recipient_id>/medical-release", methods=["POST"])
def recipient_medical_release(recipient_id):
    actor("recipients", "medical-release")
    r = get_or_404(store.recipients, recipient_id)
    if r["medical_status"] != "ON_HOLD":
        raise err_invalid_state()
    r["medical_status"] = "LISTED"
    store.touch(r)
    return success_response(serialize_recipient(r))


def _dissolve_pair_medical(recipient_id):
    for p in store.pairs.values():
        if p["recipient_id"] == recipient_id and p["pair_state"] in (
            "REGISTERED",
            "VERIFIED",
            "IN_POOL",
            "IN_PROPOSED_CHAIN",
        ):
            p["pair_state"] = "DISSOLVED"
            p["dissolution_reason"] = "MEDICAL_DECLINE"
            store.touch(p)


@bp.route("/recipients/<recipient_id>/withdraw", methods=["POST"])
def recipient_withdraw(recipient_id):
    actor("recipients", "withdraw")
    r = get_or_404(store.recipients, recipient_id)
    if r["medical_status"] not in ("LISTED", "ON_HOLD"):
        raise err_invalid_state()
    r["medical_status"] = "WITHDRAWN"
    if r["chain_participation_state"] != "TRANSPLANTED":
        r["chain_participation_state"] = "WITHDRAWN"
    _dissolve_pair_medical(r["id"])
    _fail_offers_referencing_recipient(r["id"])
    store.touch(r)
    return success_response(serialize_recipient(r))


@bp.route("/recipients/<recipient_id>/deceased", methods=["POST"])
def recipient_deceased(recipient_id):
    actor("recipients", "deceased")
    r = get_or_404(store.recipients, recipient_id)
    if r["medical_status"] == "DECEASED":
        raise err_invalid_state()
    r["medical_status"] = "DECEASED"
    _dissolve_pair_medical(r["id"])
    _fail_offers_referencing_recipient(r["id"])
    store.touch(r)
    return success_response(serialize_recipient(r))


@bp.route("/recipients/<recipient_id>/complete-transplant", methods=["POST"])
def recipient_complete_transplant(recipient_id):
    user_id, role = actor("recipients", "complete-transplant")
    r = get_or_404(store.recipients, recipient_id)
    center = get_or_404(store.centers, r["home_center_id"])
    if center["participation_status"] == "SUSPENDED":
        raise err_center_suspended()
    require_center_match(user_id, role, r["home_center_id"])
    if r["medical_status"] != "LISTED":
        raise err_invalid_state()
    if r["chain_participation_state"] != "COMMITTED":
        from errors import err_recipient_not_committed

        raise err_recipient_not_committed()
    # Find ORGAN_SHIPPED offer for this recipient.
    offer = None
    for o in store.offers.values():
        if o["recipient_id"] == r["id"] and o["offer_state"] == "ORGAN_SHIPPED":
            offer = o
            break
    if offer is None:
        # distinguish COLD_ISCHEMIA_VIOLATION: an offer whose shipment violated
        from errors import err_organ_not_arrived, err_cold_ischemia_violation

        for o in store.offers.values():
            if o["recipient_id"] == r["id"]:
                sh = next(
                    (s for s in store.shipments.values() if s["match_offer_id"] == o["id"]),
                    None,
                )
                if sh is not None and sh.get("cold_ischemia_violation"):
                    raise err_cold_ischemia_violation()
        raise err_organ_not_arrived()
    from errors import err_organ_not_arrived, err_cold_ischemia_violation

    shipment = next(
        (s for s in store.shipments.values() if s["match_offer_id"] == offer["id"]), None
    )
    if shipment is None or shipment["shipment_state"] != "DELIVERED":
        raise err_organ_not_arrived()
    if shipment.get("cold_ischemia_violation"):
        raise err_cold_ischemia_violation()

    offer["offer_state"] = "TRANSPLANT_COMPLETED"
    store.touch(offer)
    r["medical_status"] = "TRANSPLANTED"
    r["chain_participation_state"] = "TRANSPLANTED"
    r["transplant_completed_at_utc"] = store.now_iso()
    store.touch(r)

    chain = store.chains.get(offer["chain_id"])
    if chain is not None:
        from services import recompute_chain_completion

        recompute_chain_completion(chain)
        store.touch(chain)
    # Release pair.
    for p in store.pairs.values():
        if p["recipient_id"] == r["id"] and p["pair_state"] in ("LOCKED", "IN_PROPOSED_CHAIN", "IN_POOL"):
            p["pair_state"] = "RELEASED"
            p["dissolution_reason"] = "RECIPIENT_TRANSPLANTED"
            store.touch(p)
    # Consume TRANSPLANT_OR slots reserved for this offer.
    for slot in store.slots.values():
        if (
            slot["slot_state"] == "RESERVED"
            and slot.get("reserved_for_offer_id") == offer["id"]
            and slot["room_kind"] == "TRANSPLANT_OR"
        ):
            slot["slot_state"] = "CONSUMED"
            slot["consumed_at_utc"] = store.now_iso()
            store.touch(slot)
    recompute_all_active_chain_counts()
    return success_response(serialize_recipient(r))


# ---------------------------------------------------------------------------
# Pairs
# ---------------------------------------------------------------------------

@bp.route("/pairs", methods=["POST"])
def create_pair():
    actor("pairs", None)
    body = get_body()
    donor_id = req_field(body, "donor_id", str)
    recipient_id = req_field(body, "recipient_id", str)
    registered_center_id = req_field(body, "registered_center_id", str)
    get_or_404(store.donors, donor_id)
    get_or_404(store.recipients, recipient_id)
    get_or_404(store.centers, registered_center_id)
    rec = {
        "donor_id": donor_id,
        "recipient_id": recipient_id,
        "pair_state": "REGISTERED",
        "registered_center_id": registered_center_id,
        "entered_pool_at_utc": None,
        "dissolution_reason": "NONE",
    }
    store.insert(store.pairs, rec)
    # Link recipient.paired_donor_id when unset.
    recipient = store.recipients[recipient_id]
    if recipient.get("paired_donor_id") is None:
        recipient["paired_donor_id"] = donor_id
        store.touch(recipient)
    return success_response(serialize_pair(rec), 201)


@bp.route("/pairs", methods=["GET"])
def list_pairs():
    actor("pairs", None)
    rows = list(store.pairs.values())
    for param in ("donor_id", "recipient_id", "registered_center_id", "pair_state"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    page, meta = paginate(rows)
    return success_response([serialize_pair(r) for r in page], 200, meta)


@bp.route("/pairs/<pair_id>", methods=["GET"])
def get_pair(pair_id):
    actor("pairs", "get")
    p = get_or_404(store.pairs, pair_id)
    return success_response(serialize_pair(p))


@bp.route("/pairs/<pair_id>/verify", methods=["POST"])
def verify_pair(pair_id):
    actor("pairs", "verify")
    p = get_or_404(store.pairs, pair_id)
    donor = get_or_404(store.donors, p["donor_id"])
    recipient = get_or_404(store.recipients, p["recipient_id"])
    if donor["medical_status"] != "CLEARED":
        raise err_donor_not_cleared()
    if recipient["medical_status"] != "LISTED":
        raise err_recipient_not_listed()
    if p["pair_state"] != "REGISTERED":
        raise err_invalid_state()
    p["pair_state"] = "VERIFIED"
    store.touch(p)
    return success_response(serialize_pair(p))


@bp.route("/pairs/<pair_id>/enter-pool", methods=["POST"])
def enter_pool(pair_id):
    actor("pairs", "enter-pool")
    p = get_or_404(store.pairs, pair_id)
    donor = get_or_404(store.donors, p["donor_id"])
    recipient = get_or_404(store.recipients, p["recipient_id"])
    if p["pair_state"] != "VERIFIED":
        raise err_invalid_state()
    body = get_body()
    opt_in = bool(body.get("compatible_pair_opt_in")) if isinstance(body.get("compatible_pair_opt_in"), bool) else False
    abo_incompatible = not abo_compatible(donor, recipient)
    antigen_sensitized = unacceptable_antigen_hit(donor, recipient)
    bypass = donor["donor_kind"] == "PAIRED" and opt_in
    if not (abo_incompatible or antigen_sensitized or bypass):
        raise err_pair_not_incompatible()
    p["pair_state"] = "IN_POOL"
    p["entered_pool_at_utc"] = store.now_iso()
    store.touch(p)
    donor["chain_participation_state"] = "POOL"
    store.touch(donor)
    recipient["chain_participation_state"] = "POOL"
    store.touch(recipient)
    return success_response(serialize_pair(p))


@bp.route("/pairs/<pair_id>/dissolve", methods=["POST"])
def dissolve_pair(pair_id):
    actor("pairs", "dissolve")
    p = get_or_404(store.pairs, pair_id)
    if p["pair_state"] not in ("VERIFIED", "IN_POOL"):
        raise err_invalid_state()
    body = get_body()
    reason = opt_enum(body, "dissolution_reason", DISSOLUTION_REASONS, "NONE")
    p["pair_state"] = "DISSOLVED"
    p["dissolution_reason"] = reason
    store.touch(p)
    return success_response(serialize_pair(p))
