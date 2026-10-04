"""Prescription endpoints: submission, callback workflow, authorization, reopen."""

from flask import request

import db
import serializers
from errors import fail
from middleware import body, field
from routing import Arr, Obj, endpoint, resolve
from services import plans as plan_svc
from services.constants import (
    CALLBACK_ATTEMPT_CAP,
    DRUG_SCHEDULES,
    SCRIPT_SOURCES,
)


def _item_of(rx):
    return db.AUTOSHIP_ITEMS.get(rx.get("autoship_item_id"))


def _pet_of_item(item):
    plan = db.AUTOSHIP_PLANS.get(item.get("autoship_plan_id")) if item else None
    return db.PETS.get(plan.get("pet_id")) if plan else None


@endpoint(
    "/v1/prescriptions",
    ["POST"],
    ["Customer", "CustomerService", "PharmacyTechnician", "ClinicContact"],
    201,
)
def create_prescription(caller, ):
    payload = body()
    item_id = field(payload, "autoship_item_id")
    item = resolve(db.AUTOSHIP_ITEMS, item_id, "autoship item")
    prescriber_id = field(payload, "prescriber_id")
    vet = resolve(db.VETERINARIANS, prescriber_id, "veterinarian")

    script_source = field(payload, "script_source")
    if script_source not in SCRIPT_SOURCES:
        fail(
            "ERR_INVALID_REQUEST",
            "script_source must be UPLOADED_SCRIPT or WRITTEN_PRESCRIPTION.",
        )
    drug_schedule = field(payload, "drug_schedule")
    if drug_schedule not in DRUG_SCHEDULES:
        fail("ERR_INVALID_REQUEST", "drug_schedule is not a declared value.")

    script_document_id = payload.get("script_document_id")
    written_email = payload.get("written_prescriber_email_hash")
    if script_source == "UPLOADED_SCRIPT":
        if not script_document_id:
            fail("ERR_INVALID_REQUEST", "script_document_id is required for an uploaded script.")
    else:
        if not written_email:
            fail(
                "ERR_INVALID_REQUEST",
                "written_prescriber_email_hash is required for a written prescription.",
            )

    authorized_qty_total = payload.get("authorized_qty_total")
    if authorized_qty_total is None:
        fail("ERR_INVALID_REQUEST", "Field 'authorized_qty_total' is required.")
    if int(authorized_qty_total) < 1:
        fail("ERR_INVALID_REQUEST", "authorized_qty_total must be at least 1.")
    refills_authorized = payload.get("refills_authorized")
    if refills_authorized is None:
        fail("ERR_INVALID_REQUEST", "Field 'refills_authorized' is required.")
    if int(refills_authorized) < 0:
        fail("ERR_INVALID_REQUEST", "refills_authorized must be at least 0.")

    rx = db.mint(
        db.PRESCRIPTIONS,
        autoship_item_id=item["id"],
        prescriber_id=vet["id"],
        rx_status="PENDING_VERIFICATION",
        script_source=script_source,
        script_document_id=script_document_id,
        written_prescriber_email_hash=written_email,
        drug_schedule=drug_schedule,
        temperature_sensitive=bool(payload.get("temperature_sensitive", False)),
        authorized_qty_total=int(authorized_qty_total),
        authorized_qty_remaining=int(authorized_qty_total),
        refills_authorized=int(refills_authorized),
        refills_used=0,
        verification_expires_at=None,
        callback_attempt_count=0,
        recorded_by=caller.id,
    )
    item["verification_state"] = "UNVERIFIED"
    db.touch(item)
    return Obj(serializers.prescription(rx), 201)


@endpoint(
    "/v1/prescriptions",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ClinicContact", "ComplianceOfficer"],
)
def list_prescriptions(caller, ):
    # the automatic VERIFIED -> EXPIRED transition is evaluated on this read
    plan_svc.expiry_sweep()
    rows = db.ordered(db.PRESCRIPTIONS.values())
    item_id = request.args.get("autoship_item_id")
    status = request.args.get("rx_status")
    if item_id:
        rows = [r for r in rows if r.get("autoship_item_id") == item_id]
    if status:
        rows = [r for r in rows if r.get("rx_status") == status]
    return Arr([serializers.prescription(r) for r in rows])


@endpoint(
    "/v1/prescriptions/<rx_id>",
    ["GET"],
    ["Customer", "CustomerService", "PharmacyTechnician", "PharmacyManager", "ClinicContact", "ComplianceOfficer"],
)
def read_prescription(caller, rx_id):
    rx = resolve(db.PRESCRIPTIONS, rx_id, "prescription")
    return Obj(serializers.prescription(rx))


@endpoint(
    "/v1/prescriptions/<rx_id>/clinic-contacts",
    ["POST"],
    ["PharmacyTechnician", "PharmacyManager"],
)
def clinic_contact(caller, rx_id):
    rx = resolve(db.PRESCRIPTIONS, rx_id, "prescription")
    if rx.get("rx_status") not in ("PENDING_VERIFICATION", "VERIFICATION_IN_PROGRESS"):
        fail(
            "ERR_INVALID_STATE",
            "A callback attempt is only available while verification is pending or in progress.",
        )
    count = int(rx.get("callback_attempt_count", 0))
    if count >= CALLBACK_ATTEMPT_CAP:
        fail("ERR_INVALID_STATE", "The callback attempt cap has been reached.")

    item = _item_of(rx)
    if item is not None:
        db.touch(item)  # the parent item's version tracks its rx verification activity

    new_count = count + 1
    rx["callback_attempt_count"] = new_count

    if new_count >= CALLBACK_ATTEMPT_CAP:
        # third attempt: terminal failure plus the three-hop cascade
        rx["rx_status"] = "VERIFICATION_FAILED"
        rx["callback_attempt_count"] = CALLBACK_ATTEMPT_CAP
        db.touch(rx)
        plan_svc.verification_failure_cascade(rx)
    elif rx.get("rx_status") == "PENDING_VERIFICATION":
        rx["rx_status"] = "VERIFICATION_IN_PROGRESS"
        db.touch(rx)
    else:
        db.touch(rx)
        plan_svc.recompute_item_due_after_verification(rx)
    return Obj(serializers.prescription(rx))


@endpoint(
    "/v1/prescriptions/<rx_id>/clinic-authorizations", ["POST"], ["ClinicContact"]
)
def clinic_authorization(caller, rx_id):
    rx = resolve(db.PRESCRIPTIONS, rx_id, "prescription")
    payload = body()

    vet = db.VETERINARIANS.get(rx.get("prescriber_id"))
    item = _item_of(rx)

    # Gate 1 (priority 6): state + prescriber eligibility + prescriber identity.
    if rx.get("rx_status") != "VERIFICATION_IN_PROGRESS":
        fail(
            "ERR_PRESCRIBER_NOT_VERIFIED",
            "The prescription must be VERIFICATION_IN_PROGRESS before it can be authorized.",
        )
    if vet is None or vet.get("vet_status") not in ("LISTED", "VETERINARIAN_VERIFIED"):
        fail(
            "ERR_PRESCRIBER_NOT_VERIFIED",
            "The prescriber does not hold an authorizing license status.",
        )
    if caller.id != rx.get("prescriber_id"):
        fail(
            "ERR_PRESCRIBER_NOT_VERIFIED",
            "The authorizing clinic contact does not resolve to this prescription's prescriber.",
        )

    # Gate 2 (priority 7): written-prescription email match.
    if rx.get("script_source") == "WRITTEN_PRESCRIPTION":
        declared = plan_svc.normalize_email(rx.get("written_prescriber_email_hash"))
        actual = plan_svc.normalize_email(vet.get("vet_email"))
        if declared != actual:
            fail(
                "ERR_PRESCRIBER_MISMATCH",
                "written_prescriber_email_hash does not match the prescriber's email.",
            )

    # Gate 3 (priority 8): segregation of duties.
    if caller.id == rx.get("recorded_by"):
        fail(
            "ERR_SUBMITTER_CANNOT_AUTHORIZE",
            "The authorizing identity must differ from the identity that recorded the submission.",
        )

    # Gate 4 (priority 9): controlled-substance registration for CII.
    if rx.get("drug_schedule") == "CII":
        pet = _pet_of_item(item)
        owner_state = pet.get("owner_state") if pet else None
        licensed_sites = [
            s
            for s in db.PHARMACY_SITES.values()
            if owner_state in (s.get("licensed_states") or [])
        ]
        if any(not s.get("csr_registered") for s in licensed_sites):
            fail(
                "ERR_CSR_AUTH_BLOCKED",
                "Every site licensed for the owning pet's state must hold a "
                "controlled-substance registration.",
            )

    # Gate 5 (priority 20, "only after those gates does the resolution check run").
    if rx.get("script_source") == "WRITTEN_PRESCRIPTION":
        declared = plan_svc.normalize_email(rx.get("written_prescriber_email_hash"))
        resolvable = any(
            plan_svc.normalize_email(v.get("vet_email")) == declared
            for v in db.VETERINARIANS.values()
        )
        if not resolvable:
            fail(
                "ERR_PRESCRIBER_NOT_FOUND",
                "written_prescriber_email_hash names no veterinarian.",
            )

    new_total = payload.get("authorized_qty_total")
    if new_total is not None:
        if int(new_total) < 1:
            fail("ERR_INVALID_REQUEST", "authorized_qty_total must be at least 1.")
        rx["authorized_qty_total"] = int(new_total)
        rx["authorized_qty_remaining"] = int(new_total)
    new_refills = payload.get("refills_authorized")
    if new_refills is not None:
        if int(new_refills) < 0:
            fail("ERR_INVALID_REQUEST", "refills_authorized must be at least 0.")
        rx["refills_authorized"] = int(new_refills)

    rx["rx_status"] = "VERIFIED"
    db.touch(rx)
    if vet.get("vet_status") == "LISTED":
        vet["vet_status"] = "VETERINARIAN_VERIFIED"
        db.touch(vet)
    plan_svc.recompute_item_due_after_verification(rx)
    plan_svc.verification_expiry_stamp(rx)
    if item is not None:
        item["verification_state"] = "VERIFIED"
        db.touch(item)
    return Obj(serializers.prescription(rx))


@endpoint("/v1/prescriptions/<rx_id>/reopen", ["POST"], ["PharmacyManager"])
def reopen_prescription(caller, rx_id):
    rx = resolve(db.PRESCRIPTIONS, rx_id, "prescription")
    if rx.get("rx_status") != "VERIFICATION_FAILED":
        fail("ERR_INVALID_STATE", "Only a VERIFICATION_FAILED prescription can be reopened.")
    rx["rx_status"] = "PENDING_VERIFICATION"
    rx["callback_attempt_count"] = 0
    db.touch(rx)
    item = _item_of(rx)
    if item is not None and item.get("verification_state") == "BLOCKED":
        item["verification_state"] = "UNVERIFIED"
        db.touch(item)
    return Obj(serializers.prescription(rx))