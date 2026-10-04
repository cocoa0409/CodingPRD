"""Routing-endpoint selection and the compound prescription derivations."""

import clock
import db
from errors import ApiError, ERR_NO_ROUTE_AVAILABLE
from services import directory

SERVICE_SET_MAP = {
    "NEW_RX": "NEW_RX",
    "REFILL_REQUEST": "REFILL_RX",
    "REFILL_RESPONSE": "REFILL_RX",
    "CHANGE_REQUEST": "CHANGE_CANCEL",
    "CHANGE_RESPONSE": "CHANGE_CANCEL",
    "CANCEL_REQUEST": "CHANGE_CANCEL",
    "CANCEL_RESPONSE": "CHANGE_CANCEL",
}

CONTROLLED_REQUIRES_STANDARD = "NCPDP_SCRIPT_2022011"

SERVICE_LEVEL_ORDINAL = {"ELIGIBLE_A": 0, "ELIGIBLE_B": 1, "ELIGIBLE_C": 2}
STATUS_ORDINAL = {"ACTIVE": 0, "DEGRADED": 1}

# Transaction types whose re-route must agree on the message standard.
STANDARD_AGREEMENT_TYPES = {"NEW_RX", "REFILL_RESPONSE", "CHANGE_RESPONSE", "CANCEL_RESPONSE"}

CONTROLLED_SCHEDULES = {"SCHEDULE_II", "SCHEDULE_III", "SCHEDULE_IV", "SCHEDULE_V"}
CRITICAL_SCHEDULES = {"SCHEDULE_II", "SCHEDULE_III"}


def service_set_for(transaction_type):
    return SERVICE_SET_MAP.get(transaction_type)


def failed_endpoint_ids(prescription_id):
    """Endpoints already tried with outcome UNDELIVERABLE or REJECTED."""
    return {
        a["target_endpoint_id"]
        for a in db.all_rows("routing_attempts")
        if a["prescription_id"] == prescription_id
        and a.get("target_endpoint_id")
        and a.get("outcome") in ("UNDELIVERABLE", "REJECTED")
    }


def degraded_endpoint_ids(participant_id):
    return {
        e["id"] for e in db.all_rows("endpoints")
        if e["participant_id"] == participant_id and e["status"] == "DEGRADED"
    }


def rank_key(endpoint, prescription):
    return (
        STATUS_ORDINAL.get(endpoint["status"], 9),
        0 if endpoint["message_standard"] == prescription["message_standard"] else 1,
        SERVICE_LEVEL_ORDINAL.get(endpoint["service_level"], 9),
        endpoint["sla_response_minutes"],
        -float(endpoint.get("reliability_ratio", 1.0)),
        endpoint["created_at"],
        endpoint.get("_seq", 0),
    )


def candidates(prescription, exclude_ids=()):
    """The selector's eligibility filter, ordered by its pinned rank key."""
    now = clock.get_clock()
    target_set = service_set_for(prescription["transaction_type"])
    exclude = set(exclude_ids)
    out = []
    for e in db.all_rows("endpoints"):
        if e["participant_id"] != prescription["receiving_pharmacy_id"]:
            continue
        if e["status"] not in ("ACTIVE", "DEGRADED"):
            continue
        if e["service_set"] != target_set:
            continue
        if not directory.in_window(e, now):
            continue
        if prescription.get("is_controlled") and e["message_standard"] != CONTROLLED_REQUIRES_STANDARD:
            continue
        if e["id"] in exclude:
            continue
        out.append(e)
    out.sort(key=lambda e: rank_key(e, prescription))
    return out


def select_endpoint(prescription, backup=False):
    """Pick the winner, or raise the selector's no-route error."""
    exclude = set()
    if backup:
        if prescription.get("routed_endpoint_id"):
            exclude.add(prescription["routed_endpoint_id"])
        exclude |= failed_endpoint_ids(prescription["id"])
        # §3.5: "the endpoint the attempt was sent to has just moved to `DEGRADED`" —
        # the backup selects from the endpoints that remained live, so a DEGRADED
        # endpoint may never receive a re-pointed attempt.
        # §3.5 excludes "the endpoint the order is currently pointed at and every
        # endpoint already tried with outcome UNDELIVERABLE or REJECTED".
        failed_standard = {
            a["target_endpoint_id"] for a in db.all_rows("routing_attempts")
            if a["prescription_id"] == prescription["id"]
            and a.get("target_endpoint_id")
        }
        exclude |= (degraded_endpoint_ids(prescription["receiving_pharmacy_id"])
                    | failed_standard)
    ranked = candidates(prescription, exclude)
    if not ranked:
        raise ApiError(ERR_NO_ROUTE_AVAILABLE)
    return ranked[0]


def has_live_endpoint_for_set(participant_id, service_set, exclude_ids=()):
    """§3.5: the ordinary entry to `FALLBACK_PENDING` is from `BACKUP_SELECTION`, "where
    no remaining endpoint in `ACTIVE` or `DEGRADED` exists" — a network with no reachable
    endpoint is the situation the fallback channel exists for, so a merely `DEGRADED`
    endpoint is not a reason to withhold it.
    """
    exclude = set(exclude_ids)
    return any(
        e["participant_id"] == participant_id
        and e["service_set"] == service_set
        and e["status"] == "ACTIVE"
        and e["id"] not in exclude
        for e in db.all_rows("endpoints")
    )


# --------------------------------------------------------------------------
# Compound prescription derivations
# --------------------------------------------------------------------------

def is_controlled_schedule(schedule):
    return schedule != "NON_CONTROLLED"


def has_active_consent(patient_id, scopes):
    if not patient_id:
        return False
    return any(
        c["patient_id"] == patient_id and c["status"] == "ACTIVE" and c["scope"] in scopes
        for c in db.all_rows("consents")
    )


def recompute_derived(prescription):
    prescription["is_controlled"] = is_controlled_schedule(prescription["controlled_schedule"])
    monitored = has_active_consent(prescription.get("patient_id"), ("MEDICATION_HISTORY",))
    prescription["monitored_under_consent"] = monitored
    if prescription["controlled_schedule"] in CRITICAL_SCHEDULES or monitored:
        prescription["significance"] = "CRITICAL"
    else:
        prescription["significance"] = "STANDARD"


def active_attempt_id(prescription_id):
    row = db.find_one(
        "routing_attempts",
        lambda a: a["prescription_id"] == prescription_id and a["outcome"] == "IN_PROGRESS",
    )
    return row["id"] if row else None


def refresh_prescription_views(prescription):
    """Re-derive the fields read off live attempt rows and the consent registry."""
    recompute_derived(prescription)
    prescription["active_routing_attempt_id"] = active_attempt_id(prescription["id"])


def open_route_attempt_count(participant_id):
    return sum(
        1
        for a in db.all_rows("routing_attempts")
        if a["outcome"] == "IN_PROGRESS"
        and _receiving_participant(a) == participant_id
    )


def _receiving_participant(attempt):
    prescription = db.get("prescriptions", attempt["prescription_id"])
    return prescription.get("receiving_pharmacy_id") if prescription else None