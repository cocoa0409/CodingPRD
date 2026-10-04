"""Device minting, linking and the resale warranty reset.

Device carries two parallel state dimensions (SCAFFOLD.yaml section 1.2):
the activation_status pipeline and the independently toggled entitlement_lock
boolean.  Both are tracked here.
"""

import clock
import db
from db import LEGAL_SKUS
from errors import api_error
from services import calc
from services.common import (
    field_enum,
    field_int,
    field_str,
    reject_unknown,
)

ACTIVATION_STATES = (
    "UNASSIGNED", "DELIVERED", "LINKED", "ACTIVE", "LOCKED", "DECOMMISSIONED",
)


def create(membership, payload):
    reject_unknown(payload, {"hardware_sku", "serial"})
    hardware_sku = field_enum(payload, "hardware_sku", LEGAL_SKUS)
    serial = field_str(payload, "serial")

    # Serial is globally unique across all devices.
    for row in db.STORE["devices"].values():
        if row["serial"] == serial:
            raise api_error(
                "ERR_INVALID_REQUEST",
                "A device with serial '%s' already exists." % serial,
            )

    device = db.create("devices", {
        "membership_id": membership["id"] if membership is not None else None,
        "hardware_sku": hardware_sku,
        "serial": serial,
        "condition": "NEW",
        "certifying_device_id": None,
        "provenance_source": None,
        "activation_status": "UNASSIGNED",
        "entitlement_lock": True,
        "activated_at": None,
        "warranty_expires_at": None,
        "resale_cycle_count": 0,
        "total_workouts": 0,
        "content_access_allowed": False,
    })
    calc.recompute_device_entitlement(device)
    return device


def link(device, payload):
    reject_unknown(payload, {"serial", "membership_id", "expected_device_version"})

    expected = field_int(payload, "expected_device_version", required=True)
    if expected != device["version"]:
        raise api_error(
            "ERR_DEVICE_STALE_VERSION",
            "expected_device_version %d does not match the device's current version %d."
            % (expected, device["version"]),
        )

    serial = field_str(payload, "serial")
    membership_id = field_str(payload, "membership_id")
    membership = db.require("memberships", membership_id)

    if device["activation_status"] != "DELIVERED":
        raise api_error(
            "ERR_INVALID_STATE",
            "Only a DELIVERED device may be linked to a membership.",
        )
    if serial != device["serial"]:
        raise api_error(
            "ERR_DEVICE_SERIAL_MISMATCH",
            "The supplied serial does not match the device's registered serial.",
        )
    if membership["status"] not in ("PROVISIONAL", "ACTIVE", "REACTIVATED"):
        raise api_error(
            "ERR_INVALID_STATE",
            "The receiving membership must be PROVISIONAL, ACTIVE or REACTIVATED.",
        )

    device["membership_id"] = membership_id
    device["activation_status"] = "LINKED"
    device["activated_at"] = clock.now()
    calc.recompute_device_entitlement(device)
    db.touch(device)

    calc.recompute_stream_counters(membership)
    calc.recompute_posture(membership)
    db.touch(membership)
    return device


def warranty_reset(device):
    """POST /devices/{deviceId}/warranty-reset — the resale warranty window."""
    if device["activation_status"] != "ACTIVE":
        raise api_error(
            "ERR_INVALID_STATE",
            "A resale warranty reset requires the device to be ACTIVE.",
        )
    if device["provenance_source"] != "RESALE":
        raise api_error(
            "ERR_WARRANTY_RESET_NOT_ELIGIBLE",
            "A resale warranty reset requires provenance_source RESALE.",
        )

    device["warranty_expires_at"] = calc.resale_warranty(clock.now())
    device["resale_cycle_count"] = 1
    calc.recompute_device_entitlement(device)
    db.touch(device)
    return device


def decommission(device):
    device["activation_status"] = "DECOMMISSIONED"
    device["entitlement_lock"] = True
    calc.recompute_device_entitlement(device)
    db.touch(device)
    return device