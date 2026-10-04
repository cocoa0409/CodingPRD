"""Settlement sign-on campaign, execution, and defendant deposits."""
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import db
import envelope
import errors
import serialize
import services
import validate

bp = Blueprint("settlement_flow", __name__, url_prefix="/multistate")

AG_ROLES = ("ParticipatingStateAG", "LeadStateAG")


@bp.route("/settlements/<settlement_id>/open-sign-on", methods=["POST"])
def open_sign_on(settlement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("CommitteeChair",))
    st = validate.get_settlement_or_404(settlement_id)
    if st["term_status"] != "TERMS_AGREED":
        raise errors.invalid_state("Settlement is not TERMS_AGREED")
    inv = db.investigations.get(st["investigation_id"])
    if inv is None or inv["phase"] != "SETTLEMENT_PENDING":
        raise errors.invalid_phase("Sign-on may open only while the investigation is SETTLEMENT_PENDING")
    now = db.now()
    st["sign_on_opened_at"] = now
    st["sign_on_deadline"] = now + timedelta(days=calc.SIGN_ON_WINDOW_DAYS)
    st["term_status"] = "SIGN_ON_OPEN"
    # Eligible set for the quorum is the ACTIVE participations as of open time.
    db.eligible_snapshots[st["id"]] = [
        p["state_office_id"] for p in services.active_participations_of(inv["id"])
    ]
    db.touch(st)
    return envelope.success_object(serialize.serialize("settlement", st))


@bp.route("/settlements/<settlement_id>/sign-ons", methods=["POST"])
def record_sign_on(settlement_id):
    role, uid = auth.authenticate()
    auth.require_roles(role, AG_ROLES)
    body = validate.body_json()
    decision = validate.req_enum(body, "decision", ("SIGNED", "DECLINED"))
    st = validate.get_settlement_or_404(settlement_id)
    # Rung 6 state gate -> rung 9 referential -> rung 10 temporal -> rung 11 duplicate.
    if st["term_status"] != "SIGN_ON_OPEN":
        raise errors.invalid_state("Settlement is not SIGN_ON_OPEN")
    if auth.active_participation(st["investigation_id"], uid) is None:
        raise errors.ApiError(
            "ERR_NOT_A_PARTICIPANT",
            422,
            "Caller office holds no ACTIVE participation in the settlement's investigation",
        )
    if db.now() > st["sign_on_deadline"]:
        raise errors.ApiError(
            "ERR_SIGN_ON_WINDOW_CLOSED", 422, "Sign-on attempted after sign_on_deadline"
        )
    for entry in st["sign_ons"]:
        if entry["state_office_id"] == uid:
            raise errors.ApiError(
                "ERR_DUPLICATE_SIGN_ON", 409, "Office already recorded a sign-on decision"
            )
    office = db.offices.get(uid)
    st["sign_ons"].append(
        {
            "state_office_id": uid,
            "state_code": office["state_code"] if office is not None else None,
            "decision": decision,
            "status": decision,
            "decided_at": db.now(),
            "_seq": db.next_seq(),
        }
    )
    db.touch(st)
    return envelope.success_object(serialize.serialize("settlement", st), 201)


def _collapse(st, inv):
    """SIGN_ON_OPEN -> COLLAPSED past deadline with quorum unmet: the
    investigation auto-returns to NEGOTIATION and the active-settlement
    pointer is cleared."""
    st["term_status"] = "COLLAPSED"
    db.touch(st)
    inv["phase"] = "NEGOTIATION"
    inv["active_settlement_id"] = None
    db.touch(inv)


def _execute(st, inv):
    now = db.now()
    st["executed_at"] = now
    for entry in st["sign_ons"]:
        if entry["status"] == "SIGNED":
            entry["status"] = "LOCKED"
    # Every ACTIVE participation with no recorded decision lapses.
    recorded = {e["state_office_id"] for e in st["sign_ons"]}
    silent = [
        p
        for p in services.active_participations_of(inv["id"])
        if p["state_office_id"] not in recorded
    ]
    silent.sort(key=lambda p: (p["created_at"], p["_seq"]))
    for p in silent:
        office = db.offices.get(p["state_office_id"])
        st["sign_ons"].append(
            {
                "state_office_id": p["state_office_id"],
                "state_code": office["state_code"] if office is not None else None,
                "decision": None,
                "status": "LAPSED",
                "decided_at": None,
                "_seq": db.next_seq(),
            }
        )
    # Final allocation variant over the LOCKED set only (PRD §2.7, §3.4).
    lead_cost, distributable = calc.lead_cost_and_distributable(
        st["monetary_total_cents"], st["restitution_reserve_cents"]
    )
    locked = sorted(
        (e for e in st["sign_ons"] if e["status"] == "LOCKED"),
        key=lambda e: (e["decided_at"], e["_seq"]),
    )
    items = []
    for entry in locked:
        office = db.offices.get(entry["state_office_id"])
        raw = calc.raw_basis_value(st, office) if office is not None else 0
        items.append(
            {
                "key": entry["state_code"],
                "office_id": entry["state_office_id"],
                "state_code": entry["state_code"],
                "raw": raw,
                "tie_dt": entry["decided_at"],
                "tie_seq": entry["_seq"],
            }
        )
    weights = calc.normalize_weights(items)
    for item in items:
        item["weight_bps"] = weights[item["key"]]
        part = auth.active_participation(inv["id"], item["office_id"])
        item["is_lead"] = part is not None and part["committee_role"] == "LEAD"
        lead_seq = part.get("_lead_seq") if part is not None else None
        item["lead_seq"] = lead_seq if lead_seq is not None else 10 ** 18
    lead_items = [it for it in items if it["is_lead"]]
    if lead_items:
        share_pool = distributable
        bonuses = calc.split_lead_bonus(lead_cost, lead_items)
    else:
        # No lead state signed: fold the entire lead pool back into the
        # distributable pool before share computation.
        share_pool = distributable + lead_cost
        bonuses = {}
    calc.compute_line_shares(share_pool, items)
    for item in items:
        bonus = bonuses.get(item["key"], 0)
        gross = item["share_cents"] + bonus
        line = db.new_entity(db.lines)
        line.update(
            {
                "settlement_id": st["id"],
                "state_office_id": item["office_id"],
                "state_code": item["state_code"],
                "basis_value_snapshot": item["raw"],
                "weight_bps": item["weight_bps"],
                "share_cents": item["share_cents"],
                "lead_bonus_cents": bonus,
                "gross_share_cents": gross,
                "disbursed_cents": 0,
                "reverted_cents": 0,
                "remaining_cents": gross,
                "status": "ELIGIBLE",
            }
        )
    st["distributable_cents"] = distributable
    st["lead_cost_cents"] = lead_cost
    st["term_status"] = "EXECUTED"
    db.touch(st)


@bp.route("/settlements/<settlement_id>/execute", methods=["POST"])
def execute_settlement(settlement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("CommitteeChair",))
    st = validate.get_settlement_or_404(settlement_id)
    if st["term_status"] != "SIGN_ON_OPEN":
        raise errors.invalid_state("Settlement is not SIGN_ON_OPEN")
    inv = db.investigations.get(st["investigation_id"])
    if inv is None or inv["phase"] != "SETTLEMENT_PENDING":
        raise errors.invalid_phase("Execution requires the investigation in SETTLEMENT_PENDING")
    signed_office_ids = [
        e["state_office_id"] for e in st["sign_ons"] if e["status"] in ("SIGNED", "LOCKED")
    ]
    eligible = db.eligible_snapshots.get(st["id"], [])
    met = calc.sign_on_quorum_met(st, eligible, signed_office_ids, db.offices)
    if not met:
        if db.now() <= st["sign_on_deadline"]:
            raise errors.ApiError(
                "ERR_QUORUM_NOT_MET",
                422,
                "Sign-on quorum is not met and the deadline has not passed; no state change",
            )
        _collapse(st, inv)
        return envelope.success_object(serialize.serialize("settlement", st))
    _execute(st, inv)
    return envelope.success_object(serialize.serialize("settlement", st))


@bp.route("/settlements/<settlement_id>/deposit", methods=["POST"])
def deposit(settlement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("DefendantCounsel",))
    body = validate.body_json()
    amount = validate.req_int(body, "amount_cents")
    st = validate.get_settlement_or_404(settlement_id)
    if st["term_status"] != "EXECUTED":
        raise errors.invalid_state("Deposits are lawful only on an EXECUTED settlement")
    if st["deposited_cents"] + amount > st["monetary_total_cents"]:
        raise errors.ApiError(
            "ERR_DEPOSIT_EXCEEDS_TOTAL",
            422,
            "Deposit would push deposited_cents past monetary_total_cents",
        )
    st["deposited_cents"] += amount
    if st["fund_status"] == "UNFUNDED":
        if st["deposited_cents"] == st["monetary_total_cents"]:
            st["fund_status"] = "FUNDED"
        elif st["deposited_cents"] > 0:
            st["fund_status"] = "PARTIALLY_FUNDED"
    elif st["fund_status"] == "PARTIALLY_FUNDED":
        if st["deposited_cents"] == st["monetary_total_cents"]:
            st["fund_status"] = "FUNDED"
    db.touch(st)
    return envelope.success_object(serialize.serialize("settlement", st))
