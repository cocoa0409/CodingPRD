"""Incident records, claims and the pet risk ledger (PRD §3.6)."""

import db
import domain
import validate
from errors import ApiError
from services import core


def create(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(
        body,
        required=["booking_id", "pet_id", "severity", "incident_type",
                  "claim_amount_cents"],
        optional=["override_reason"])
    booking = core.require_booking(body["booking_id"])
    pet = core.require_pet(body["pet_id"])
    if booking["store_id"] != store_id:
        raise ApiError("ERR_BOOKING_NOT_FOUND")
    if booking["pet_id"] != pet["id"]:
        raise ApiError("ERR_BOOKING_PET_MISMATCH")
    if body["claim_amount_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    validate.check_backdating(store, booking, pet)

    row = db.new_row()
    row.update({
        "store_id": store_id, "booking_id": booking["id"], "pet_id": pet["id"],
        "severity": body["severity"], "incident_type": body["incident_type"],
        "risk_points": domain.SEVERITY_POINTS[body["severity"]],
        "claim_amount_cents": int(body["claim_amount_cents"]),
        "payout_amount_cents": 0, "risk_points_lost": 0,
        "available_claimable_cents": int(body["claim_amount_cents"]),
        "override_reason": body.get("override_reason"),
        "claim_status": "UNREVIEWED",
    })
    db.add("incidents", row)
    core.recompute_pet_risk(pet, touch_row=False)
    db.touch(pet)
    core.recompute_incident_risk_index(store)
    db.touch(store)
    return row


def _load(store_id, incident_id):
    core.require_store(store_id)
    incident = core.require_incident(incident_id)
    if incident["store_id"] != store_id:
        raise ApiError("ERR_INCIDENT_NOT_FOUND")
    return incident


def begin_review(body, store_id, incident_id):
    store = core.require_store(store_id)
    incident = _load(store_id, incident_id)
    body = validate.shape(body, required=["expected_incident_version"], optional=[])
    validate.check_backdating(store, incident)
    if incident["claim_status"] != "UNREVIEWED":
        raise ApiError("ERR_INCIDENT_NOT_REVIEWABLE")
    booking = core.require_booking(incident["booking_id"])
    if booking["service_type"] != "GROOMING":
        raise ApiError("ERR_INCIDENT_BOOKING_TYPE_MISMATCH")
    validate.require_expected(body, incident["version"], "expected_incident_version")
    incident["claim_status"] = "UNDER_REVIEW"
    db.touch(incident)
    core.recompute_incident_risk_index(store)
    db.touch(store)
    return incident


def approve_claim(body, store_id, incident_id):
    store = core.require_store(store_id)
    incident = _load(store_id, incident_id)
    body = validate.shape(body, required=["expected_incident_version"],
                          optional=["override_reason"])
    validate.check_backdating(store, incident)
    if incident["claim_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INCIDENT_NOT_UNDER_REVIEW")
    cap = domain.INCIDENT_CLAIM_CAP[store["state_code"]]
    # PRD §3.6: "The claim amount must not exceed the cap set for the store's
    # state unless an override_reason is supplied as a non-empty string." The
    # override travels with the approval (and is still honoured if it was
    # recorded when the incident was filed).
    override = body.get("override_reason") or incident.get("override_reason")
    if incident["claim_amount_cents"] > cap and not (override or "").strip():
        raise ApiError("ERR_CLAIM_CAP_EXCEEDED")
    pet = core.require_pet(incident["pet_id"])
    if pet["status"] != "ACTIVE":
        raise ApiError("ERR_PET_ARCHIVED")
    validate.require_expected(body, incident["version"], "expected_incident_version")

    incident["payout_amount_cents"] = incident["claim_amount_cents"]
    incident["risk_points_lost"] = incident["risk_points"]
    incident["available_claimable_cents"] = 0
    incident["claim_status"] = "APPROVED"
    db.touch(incident)
    core.recompute_pet_risk(pet, touch_row=False)
    db.touch(pet)
    core.recompute_incident_risk_index(store)
    db.touch(store)
    return incident


def deny_claim(body, store_id, incident_id):
    store = core.require_store(store_id)
    incident = _load(store_id, incident_id)
    body = validate.shape(body, required=["expected_incident_version"], optional=[])
    validate.check_backdating(store, incident)
    if incident["claim_status"] not in ("UNREVIEWED", "UNDER_REVIEW"):
        raise ApiError("ERR_INCIDENT_NOT_DENIABLE")
    validate.require_expected(body, incident["version"], "expected_incident_version")
    incident["claim_status"] = "DENIED"
    db.touch(incident)
    pet = db.get("pets", incident["pet_id"])
    if pet is not None:
        core.recompute_pet_risk(pet, touch_row=False)
        db.touch(pet)
    core.recompute_incident_risk_index(store)
    db.touch(store)
    return incident


def return_to_queue(body, store_id, incident_id):
    validate.check_backdating()
    store = core.require_store(store_id)
    incident = _load(store_id, incident_id)
    body = validate.shape(body, required=["expected_incident_version"], optional=[])
    if incident["claim_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INCIDENT_NOT_UNDER_REVIEW")
    validate.require_expected(body, incident["version"], "expected_incident_version")
    incident["claim_status"] = "UNREVIEWED"
    db.touch(incident)
    core.recompute_incident_risk_index(store)
    db.touch(store)
    return incident


def claim_summary(store_id, incident_id):
    incident = _load(store_id, incident_id)
    return {
        "claim_amount_cents": incident["claim_amount_cents"],
        "payout_amount_cents": incident["payout_amount_cents"],
        "risk_points": incident["risk_points"],
        "risk_points_lost": incident["risk_points_lost"],
        "available_claimable_cents": incident["available_claimable_cents"]
        if incident["claim_status"] != "APPROVED" else 0,
    }