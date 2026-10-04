"""Pet endpoints."""

import clock
import db
import serializers
from errors import fail
from middleware import body, field
from routing import Arr, Obj, endpoint, resolve
from services import plans as plan_svc
from services.constants import REFUND_DESTINATIONS, SPECIES_VALUES


def _validate_species(species):
    if species not in SPECIES_VALUES:
        fail("ERR_INVALID_REQUEST", "species must be one of DOG, CAT, HORSE, BIRD.")


@endpoint("/v1/pets", ["POST"], ["Customer", "CustomerService"], 201)
def create_pet(caller, ):
    payload = body()
    pet_name = field(payload, "pet_name")
    species = field(payload, "species")
    breed = field(payload, "breed")
    weight_kg = payload.get("weight_kg")
    owner_state = field(payload, "owner_state")
    if weight_kg is None:
        fail("ERR_INVALID_REQUEST", "Field 'weight_kg' is required.")
    _validate_species(species)
    row = db.mint(
        db.PETS,
        pet_name=pet_name,
        species=species,
        breed=breed,
        weight_kg=weight_kg,
        owner_state=owner_state,
        pet_status="ACTIVE",
        passed_at=None,
        pet_lifecycle_state="ALIVE",
        compassionate_review_id=None,
        registered_by=caller.id,
    )
    return Obj(serializers.pet(row), 201)


@endpoint("/v1/pets", ["GET"], ["Customer", "CustomerService", "PharmacyTechnician", "ComplianceOfficer"])
def list_pets(caller, ):
    rows = db.ordered(db.PETS.values())
    pet_status = _q("pet_status")
    review_id = _q("compassionate_review_id")
    if pet_status:
        rows = [r for r in rows if r.get("pet_status") == pet_status]
    if review_id:
        rows = [r for r in rows if r.get("compassionate_review_id") == review_id]
    if caller.is_customer:
        rows = [r for r in rows if r["id"] == caller.id or r.get("registered_by") == caller.id]
    return Arr([serializers.pet(r) for r in rows])


@endpoint("/v1/pets/<pet_id>", ["GET"], ["Customer", "CustomerService", "PharmacyTechnician", "ComplianceOfficer"])
def read_pet(caller, pet_id):
    row = resolve(db.PETS, pet_id, "pet")
    if caller.is_customer and not (row["id"] == caller.id or row.get("registered_by") == caller.id):
        # ownership is not observable: an unowned pet is reported as absent
        fail("ERR_RESOURCE_NOT_FOUND", "No pet exists with id %s." % pet_id)
    return Obj(serializers.pet(row))


@endpoint("/v1/pets/<pet_id>/weights", ["POST"], ["Customer", "CustomerService"])
def record_weight(caller, pet_id):
    pet = resolve(db.PETS, pet_id, "pet")
    if caller.is_customer and pet["id"] != caller.id:
        fail("ERR_RESOURCE_NOT_FOUND", "No pet exists with id %s." % pet_id)
    payload = body()
    weight_kg = payload.get("weight_kg")
    if weight_kg is None:
        fail("ERR_INVALID_REQUEST", "Field 'weight_kg' is required.")
    pet["weight_kg"] = weight_kg
    plan_svc.recompute_pet_items(pet["id"])
    plan_svc.recompute_pet_plans(pet["id"])
    return Obj(serializers.pet(pet))


@endpoint("/v1/pets/<pet_id>/passings", ["POST"], ["Customer", "CustomerService"])
def report_passing(caller, pet_id):
    pet = resolve(db.PETS, pet_id, "pet")
    if caller.is_customer and pet["id"] != caller.id:
        fail("ERR_RESOURCE_NOT_FOUND", "No pet exists with id %s." % pet_id)

    # state gate: the governing transition's from: value must be the current one
    if pet.get("pet_status") != "ACTIVE":
        fail("ERR_INVALID_STATE", "The pet is not ACTIVE.")

    payload = body()
    refund_destination = field(payload, "refund_destination")
    if refund_destination not in REFUND_DESTINATIONS:
        fail("ERR_INVALID_REQUEST", "refund_destination must be WALLET or ORIGINAL_PAYMENT.")

    pet["pet_status"] = "PASSED"
    pet["passed_at"] = clock.iso(clock.current())

    plan_ids = {
        p["id"] for p in db.AUTOSHIP_PLANS.values() if p.get("pet_id") == pet["id"]
    }
    affected_shipment_id = plan_svc.park_in_transit_work(plan_ids)

    review = db.mint(
        db.COMPASSIONATE_REVIEWS,
        pet_id=pet["id"],
        affected_shipment_id=affected_shipment_id,
        review_status="OPEN",
        refund_destination=refund_destination,
        refunded_amount_cents=0,
        recorded_by=caller.id,
    )
    pet["compassionate_review_id"] = review["id"]

    plan_svc.compassionate_cancel_plans(pet["id"])
    pet["pet_lifecycle_state"] = serializers.pet_lifecycle_state(pet)
    return Obj(serializers.pet(pet))


def _q(name):
    from flask import request

    return request.args.get(name)