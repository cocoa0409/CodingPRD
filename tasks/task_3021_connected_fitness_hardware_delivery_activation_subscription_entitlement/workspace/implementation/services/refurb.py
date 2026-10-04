"""RefurbBatch: certification lineage, pricing, listing and the resale minting."""

import clock
import db
from errors import api_error
from services import calc
from services.common import (
    field_bool,
    field_enum,
    field_str,
    reject_unknown,
)

GRADES = ("A", "B", "C")
GRADE_FRACTION = {"A": 0.60, "B": 0.50, "C": 0.40}


def _is_resale_originated(device):
    return device["provenance_source"] == "RESALE"


def _source_is_eligible(device):
    """A source is eligible when DECOMMISSIONED or already resale-originated."""
    return device["activation_status"] == "DECOMMISSIONED" or _is_resale_originated(device)


def open_batch(payload):
    reject_unknown(
        payload,
        {"source_device_id", "certification_grade", "performance_resale_enabled"},
    )
    source_device_id = field_str(payload, "source_device_id")
    certification_grade = field_enum(payload, "certification_grade", GRADES)
    performance_resale_enabled = field_bool(
        payload, "performance_resale_enabled", required=False, default=False
    )

    source = db.require("devices", source_device_id)
    if not _source_is_eligible(source):
        raise api_error(
            "ERR_CERTIFYING_DEVICE_NOT_ELIGIBLE",
            "The refurbishment source device is neither DECOMMISSIONED nor itself resale-originated.",
        )

    batch = db.create("refurb_batches", {
        "source_device_id": source_device_id,
        "performance_resale_enabled": performance_resale_enabled,
        "certification_grade": certification_grade,
        "inspected_at": clock.now(),
        "status": "INSPECTING",
        "sold_device_id": None,
        "certification_chain_depth": 0,
        "resale_price_cents": None,
        "library_availability": "AVAILABLE",
    })

    # The chain depth is computed immediately and both its bound and its cycle
    # guard are enforced here.
    batch["certification_chain_depth"] = calc.certification_chain(batch)
    recompute_library_availability(batch)
    return batch


def certify(batch, payload):
    reject_unknown(payload, {"certification_grade"})
    if batch["status"] == "SOLD":
        raise api_error(
            "ERR_ALREADY_TERMINAL",
            "The refurbishment batch has been sold and admits no further transition.",
        )
    if batch["status"] != "INSPECTING":
        raise api_error("ERR_INVALID_STATE", "Only an INSPECTING batch may be certified.")

    grade = field_enum(
        payload, "certification_grade", GRADES,
        required=False, default=batch["certification_grade"],
    )
    source = db.require("devices", batch["source_device_id"])

    # Certification runs the chain-depth calculation again and enforces both its
    # bound and its cycle guard.
    depth = calc.certification_chain(batch)

    list_price = db.SKU_LIST_PRICE_CENTS.get(source["hardware_sku"])
    batch["certification_grade"] = grade
    batch["status"] = "CERTIFIED"
    if list_price is not None:
        batch["resale_price_cents"] = calc.round_half_up(list_price * calc._dec(GRADE_FRACTION[grade]))
    # A lower-grade unit is never sold as a performance model.
    if grade in ("B", "C"):
        batch["performance_resale_enabled"] = False
    batch["certification_chain_depth"] = depth
    recompute_library_availability(batch)
    db.touch(batch)
    return batch


def list_batch(batch):
    if batch["status"] == "SOLD":
        raise api_error(
            "ERR_ALREADY_TERMINAL",
            "The refurbishment batch has been sold and admits no further transition.",
        )
    if batch["status"] != "CERTIFIED":
        raise api_error("ERR_INVALID_STATE", "Only a CERTIFIED batch may be listed.")
    if not (batch["performance_resale_enabled"] is False or batch["certification_grade"] == "A"):
        raise api_error(
            "ERR_INVALID_STATE",
            "The batch configuration does not admit listing.",
        )
    batch["status"] = "LISTED"
    recompute_library_availability(batch)
    db.touch(batch)
    return batch


def sell(batch, payload):
    reject_unknown(payload, {"buying_membership_id"})
    buying_membership_id = field_str(payload, "buying_membership_id")

    if batch["status"] == "SOLD":
        raise api_error(
            "ERR_ALREADY_TERMINAL",
            "The refurbishment batch has been sold and admits no further attempt.",
        )
    if batch["status"] != "LISTED":
        raise api_error("ERR_INVALID_STATE", "Only a LISTED batch may be sold.")

    membership = db.require("memberships", buying_membership_id)
    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    if membership["posture"] not in ("OPEN", "RESTRICTED"):
        raise api_error(
            "ERR_POSTURE_RESTRICTED",
            "A FROZEN buying membership may not purchase a refurbished unit.",
        )

    source = db.require("devices", batch["source_device_id"])

    # The SKU of the minted refurbished unit.  REFURB_* SKUs are only legal on
    # a resale-originated device, so a non-BIKE/TREAD source keeps its own SKU
    # rather than being transmuted into a refurbishment SKU.
    if batch["performance_resale_enabled"] is False:
        minted_sku = "ROWER"
    else:
        minted_sku = {
            "BIKE": "REFURB_BIKE",
            "TREAD": "REFURB_TREAD",
        }.get(source["hardware_sku"], source["hardware_sku"])

    instant = clock.now()
    minted = db.create("devices", {
        "membership_id": membership["id"],
        "hardware_sku": minted_sku,
        # A promise: a device minted by a resale activation is never eligible
        # for the resale-only warranty reset.
        "serial": "REFURB-" + db.new_id(),
        "condition": "REFURBISHED",
        "certifying_device_id": batch["source_device_id"],
        "provenance_source": "RESALE",
        "activation_status": "ACTIVE",
        "entitlement_lock": False,
        "activated_at": instant,
        # Warranty reset on resale: a fresh 90-day window anchored on the sale.
        "warranty_expires_at": calc.resale_warranty(instant),
        "resale_cycle_count": 1,
        "total_workouts": 0,
        "content_access_allowed": False,
    })
    calc.recompute_device_entitlement(minted)

    batch["status"] = "SOLD"
    batch["sold_device_id"] = minted["id"]
    recompute_library_availability(batch)
    db.touch(batch)

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    calc.recompute_device_entitlement(minted)
    return batch


# Library availability is available while the batch is INSPECTING, CERTIFIED
# or LISTED; a batch is only un-listable once it has left that window.
AVAILABLE_STATUSES = ("INSPECTING", "CERTIFIED", "LISTED")


def recompute_library_availability(batch):
    batch["library_availability"] = (
        "AVAILABLE" if batch["status"] in AVAILABLE_STATUSES else "UNAVAILABLE"
    )
    return batch["library_availability"]