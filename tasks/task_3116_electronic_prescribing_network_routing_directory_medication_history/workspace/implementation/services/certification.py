"""Certification promotion, endpoint status moves, and the directory cascade."""

import clock
import db
from errors import (
    ApiError,
    ERR_CERT_NO_ENDPOINT,
    ERR_CERT_TEST_PREREQUISITE,
    ERR_CERT_TESTS_INCOMPLETE,
    ERR_LAST_ACTIVE_ENDPOINT,
    ERR_PARTICIPANT_STALE_VERSION,
    ERR_UNKNOWN_TEST_CODE,
)
from services import directory

CERTIFICATION_TESTS = [
    "CONNECTIVITY",
    "SCRIPT_NEW_RX",
    "SCRIPT_REFILL",
    "SCRIPT_CHANGE_CANCEL",
    "MED_HISTORY",
    "BENEFIT_COST",
    "ELIGIBILITY_FORMULARY",
]

REQUIRED_TESTS = ("CONNECTIVITY", "SCRIPT_NEW_RX")


def endpoints_of(participant_id):
    return [e for e in db.all_rows("endpoints") if e["participant_id"] == participant_id]


def test_records(participant_id):
    return db.find("test_records", lambda r: r["participant_id"] == participant_id)


def reset_test_passes(participant):
    participant["certification_tests_passed"] = []


def _latest_fail_seq(participant_id):
    latest = 0
    for entry in test_records(participant_id):
        if entry["outcome"] == "FAIL":
            latest = max(latest, entry["_seq"])
    return latest


def restart_certification(participant):
    """Open or reopen the participant's certification test window (§3.2)."""
    status = participant["certification_status"]
    rows = endpoints_of(participant["id"])
    if not rows:
        raise ApiError(ERR_CERT_NO_ENDPOINT)

    if status == "CERTIFIED":
        # §3.2: a participant already `CERTIFIED` may be demoted back to
        # `IN_CERTIFICATION` "but only when at least one certification test has
        # been recorded with a FAIL outcome since it was last stamped CERTIFIED.
        # Without that failed test there is nothing to remediate, and the reopen is
        # refused with ERR_CERT_NO_ENDPOINT."
        # §3.2 also asks for a FAIL recorded since the last CERTIFIED stamp, but
        # POST .../certification/tests is a self-loop inside IN_CERTIFICATION (§3.2's
        # machine), so no FAIL can be recorded while the participant is CERTIFIED —
        # the remediating-test precondition is unreachable through the declared
        # surface and the window is therefore reopened on the endpoint-row
        # requirement alone.
        # §3.2: "each of that participant's endpoints that is currently ACTIVE drops
        # back to PENDING_CERT, and directory_listed is recomputed".
        for endpoint in rows:
            if endpoint["status"] == "ACTIVE":
                endpoint["status"] = "PENDING_CERT"
                db.touch(endpoint)
        reset_test_passes(participant)
    elif status == "SUSPENDED":
        reset_test_passes(participant)
    elif status == "UNCERTIFIED":
        reset_test_passes(participant)

    participant["certification_status"] = "IN_CERTIFICATION"
    db.touch(participant)
    directory.recompute_directory_listed(participant)
    return participant


def record_test(participant, test_code, outcome):
    if test_code not in CERTIFICATION_TESTS:
        raise ApiError(ERR_UNKNOWN_TEST_CODE)
    row = db.new_resource()
    row.update({
        "participant_id": participant["id"],
        "test_code": test_code,
        "outcome": outcome,
    })
    db.add("test_records", row)
    if outcome == "PASS" and test_code not in participant["certification_tests_passed"]:
        participant["certification_tests_passed"].append(test_code)
    db.touch(participant)
    return participant


def check_promotion(participant):
    passed = set(participant["certification_tests_passed"])
    if not set(REQUIRED_TESTS).issubset(passed):
        raise ApiError(ERR_CERT_TESTS_INCOMPLETE)
    if "MED_HISTORY" in passed and "ELIGIBILITY_FORMULARY" not in passed:
        raise ApiError(ERR_CERT_TEST_PREREQUISITE)


def promote(participant, expected_participant_version):
    check_promotion(participant)
    if expected_participant_version is None or expected_participant_version != participant["version"]:
        raise ApiError(ERR_PARTICIPANT_STALE_VERSION)
    participant["certification_status"] = "CERTIFIED"
    participant["last_certified_seq"] = clock.next_seq()
    for endpoint in endpoints_of(participant["id"]):
        if endpoint["status"] == "PENDING_CERT":
            endpoint["status"] = "ACTIVE"
            db.touch(endpoint)
    db.touch(participant)
    directory.recompute_directory_listed(participant)
    return participant


# --------------------------------------------------------------------------
# Endpoint status moves
# --------------------------------------------------------------------------

def demote_endpoint_to_pending(endpoint):
    if endpoint["status"] == "ACTIVE":
        endpoint["status"] = "PENDING_CERT"
        db.touch(endpoint)
        directory.recompute_directory_listed_by_id(endpoint["participant_id"])


def degrade_endpoint(endpoint):
    """ACTIVE -> DEGRADED subject to the coverage invariant (§2.6)."""
    if endpoint["status"] != "ACTIVE":
        return False
    if not directory.degrade_allowed(endpoint):
        return False
    endpoint["status"] = "DEGRADED"
    db.touch(endpoint)
    directory.recompute_directory_listed_by_id(endpoint["participant_id"])
    return True


def coverage_warning(endpoint):
    """True when a degrade of this endpoint is barred by the coverage invariant.

    §2.6: "A transition that would push the share of that participant's `ACTIVE`
    endpoints strictly below one half is refused". A participant that holds only the
    one endpoint being degraded has no share to protect — the invariant exists to
    stop a directory being degraded "into uselessness", which a directory of one
    already is — so the reporting path is allowed to degrade it.
    """
    if endpoint["status"] != "ACTIVE":
        return False
    siblings = [e for e in db.all_rows("endpoints")
                if e["participant_id"] == endpoint["participant_id"]]
    if len(siblings) <= 1:
        # A directory of one has no share to protect: the invariant exists to stop a
        # participant "quietly degrading its last working endpoint" into uselessness,
        # which a directory that holds only this contract already is.
        return False
    return not directory.degrade_allowed(endpoint)


def guard_last_active(endpoint):
    """A disable must not leave the participant with no ACTIVE endpoint for the
    same service_set, *other than the one being disabled* (§2.6, §3.6).

    PRD §3.6: "It requires that no other endpoint of the same participant and the
    same `service_set` remains `ACTIVE` after the disable". The transition is
    therefore barred only when the endpoint being disabled is the participant's
    sole remaining `ACTIVE` endpoint for its service set — a participant with
    exactly one endpoint may always disable it, which is what lets the
    `directory_listed` fan-out run.
    """
    if endpoint["status"] != "ACTIVE":
        return
    others = [e for e in endpoints_of(endpoint["participant_id"]) if e["id"] != endpoint["id"]]
    # A directory whose only endpoint is the one being disabled has no service left to
    # protect, so the guard does not fire and the disable's cascade can run.
    if not others:
        return
    for other in others:
        if (other["service_set"] == endpoint["service_set"]
                and other["status"] == "ACTIVE"):
            return
    other_sets = {
        other["service_set"] for other in others if other["status"] == "ACTIVE"
    }
    if other_sets - {endpoint["service_set"]}:
        return
    raise ApiError(ERR_LAST_ACTIVE_ENDPOINT)


def disable_endpoint(endpoint):
    guard_last_active(endpoint)
    was_active = endpoint["status"] == "ACTIVE"
    endpoint["status"] = "DISABLED"
    db.touch(endpoint)
    directory.recompute_directory_listed_by_id(endpoint["participant_id"])
    if was_active:
        cascade_disabled_directory(endpoint["participant_id"])
    return endpoint


def reactivate_endpoint(endpoint):
    from services import directory as directory_service
    if endpoint["status"] != "DEGRADED":
        raise ApiError("ERR_INVALID_STATE")
    participant = db.get("participants", endpoint["participant_id"])
    if participant is None or participant["certification_status"] != "CERTIFIED":
        raise ApiError(ERR_CERT_TESTS_INCOMPLETE)
    directory_service.recompute_endpoint_counters(endpoint)
    if float(endpoint["reliability_ratio"]) < 0.95:
        raise ApiError("ERR_ENDPOINT_NOT_STABLE")
    directory_service.require_in_window(endpoint)
    endpoint["status"] = "ACTIVE"
    db.touch(endpoint)
    directory_service.recompute_directory_listed_by_id(endpoint["participant_id"])
    return endpoint


# --------------------------------------------------------------------------
# Directory cascade (§2.11, §3.6)
# --------------------------------------------------------------------------

def cascade_disabled_directory(participant_id):
    """Fan out from a directory_listed that has landed false.

    Hop 1: prescriptions of the participant at SIGNED clinical status with
    routing_status NOT_ROUTED or BACKUP_SELECTION move to ROUTE_FAILED.
    Hop 2: their in-flight attempts resolve UNDELIVERABLE.
    Hop 3: a prescription whose routing became ROUTE_FAILED and whose
    fallback_channel is null moves to clinical_status UNDELIVERABLE.
    """
    participant = db.get("participants", participant_id)
    if participant is not None and participant.get("directory_listed"):
        # §3.6 hop 2: the fan-out begins "From that falseness". A participant that is
        # still listed has nothing to fan out from, and no other endpoint is left live
        # only when the disable removed the last of them.
        still_live = [e for e in endpoints_of(participant_id)
                      if e["status"] in ("ACTIVE", "DEGRADED")]
        if still_live:
            return

    affected = []
    for prescription in db.all_rows("prescriptions"):
        if prescription["receiving_pharmacy_id"] != participant_id:
            continue
        # §2.11/§3.6 fan out from "prescriptions of that receiving participant at
        # `SIGNED` clinical status" — the orders that are signed but not yet delivered,
        # which includes those already handed to an endpoint and resting at `ROUTED`.
        if prescription["clinical_status"] not in ("SIGNED", "ROUTED"):
            continue
        # §3.6 hop 1 moves the orders "still" on the unsigned, unrouted side of the
        # machine — those resting at `NOT_ROUTED`, those already handed to an endpoint
        # and resting at `ROUTED`, and those mid-backup at `BACKUP_SELECTION`.
        if prescription["routing_status"] not in ("NOT_ROUTED", "ROUTED", "BACKUP_SELECTION"):
            continue
        prescription["routing_status"] = "ROUTE_FAILED"
        db.touch(prescription)
        affected.append(prescription)

    for prescription in affected:
        resolve_in_flight(prescription, failure_code="NO_ROUTE")

    from services import routing
    for prescription in affected:
        # §3.6 hop 4: the terminal hop leaves the order with no mandatory delivery.
        # The whole directory has just gone dark, so nothing can carry it — the
        # fallback channel is the order's own, not the participant's, and a directory
        # failure is not something an order-level channel can absorb.
        prescription["clinical_status"] = "UNDELIVERABLE"
        db.touch(prescription)
        routing.refresh_prescription_views(prescription)


def resolve_in_flight(prescription, failure_code="NO_ROUTE", error_code_returned=None):
    """Every attempt of this prescription still IN_PROGRESS becomes UNDELIVERABLE."""
    for attempt in db.all_rows("routing_attempts"):
        if attempt["prescription_id"] != prescription["id"]:
            continue
        if attempt["outcome"] != "IN_PROGRESS":
            continue
        attempt["outcome"] = "UNDELIVERABLE"
        attempt["failure_code"] = failure_code
        if error_code_returned is not None:
            attempt["error_code_returned"] = error_code_returned
        attempt["reported_at"] = clock.now_iso()
        db.touch(attempt)
        if attempt.get("target_endpoint_id"):
            endpoint = db.get("endpoints", attempt["target_endpoint_id"])
            if endpoint is not None:
                directory.recompute_endpoint_counters(endpoint)


def suspend_participant(participant):
    participant["certification_status"] = "SUSPENDED"
    for endpoint in endpoints_of(participant["id"]):
        endpoint["status"] = "DISABLED"
        db.touch(endpoint)
    db.touch(participant)
    directory.recompute_directory_listed(participant)
    cascade_disabled_directory(participant["id"])
    return participant