"""Transitive cascades and lazy state discovery (PRD 2.8)."""

from calc import (COMMERCIAL_MINIMUM_CENTS, RISK_SUSPEND_THRESHOLD, currency_lapsed,
                  recompute_policy_ledger, recompute_risk_score, write_currency)
from clockmod import clock
from store import store, touch


# ---------------------------------------------------------------------------
# zone slot bookkeeping (PRD 2.10)
# ---------------------------------------------------------------------------

def release_zone_slot(authorization):
    zone = store.get("zones", authorization["zone_id"])
    if zone is None:
        return
    if zone["reserved_slot_count"] > 0:
        zone["reserved_slot_count"] -= 1
    touch(zone)


def reserve_zone_slot(zone):
    zone["reserved_slot_count"] += 1
    touch(zone)


# ---------------------------------------------------------------------------
# cascade: revoking one authorization
# ---------------------------------------------------------------------------

def cancel_flights_of_authorization(authorization):
    for flight in store.all("flights"):
        if flight.get("authorization_id") != authorization["id"]:
            continue
        if flight["status"] not in ("PLANNED", "PREFLIGHT_CLEARED"):
            continue
        flight["status"] = "CANCELLED"
        flight["cancellation_reason"] = "AUTHORIZATION_REVOKED"
        touch(flight)


def revoke_authorization(authorization, denial_reason=None):
    authorization["status"] = "REVOKED"
    if denial_reason is not None:
        authorization["denial_reason"] = denial_reason
    touch(authorization)
    release_zone_slot(authorization)
    cancel_flights_of_authorization(authorization)


# ---------------------------------------------------------------------------
# cascade: grounding one airframe
# ---------------------------------------------------------------------------

def revoke_authorizations_of_aircraft(aircraft):
    victims = [a for a in store.all("authorizations")
               if a["aircraft_id"] == aircraft["id"]
               and a["status"] in ("APPROVED", "ACTIVE")]
    for authorization in victims:
        revoke_authorization(authorization)


def ground_aircraft(aircraft, reason):
    aircraft["registration_status"] = "GROUNDED"
    aircraft["grounding_reason"] = reason
    touch(aircraft)
    revoke_authorizations_of_aircraft(aircraft)


# ---------------------------------------------------------------------------
# cascade: suspending a pilot (depth four)
# ---------------------------------------------------------------------------

def suspend_pilot(pilot, reason):
    pilot["status"] = "SUSPENDED"
    pilot["suspension_reason"] = reason
    touch(pilot)
    victims = [a for a in store.all("aircraft")
               if a["owner_pilot_id"] == pilot["id"]
               and a["registration_status"] == "REGISTERED"]
    for aircraft in victims:
        aircraft["registration_status"] = "GROUNDED"
        aircraft["grounding_reason"] = "OWNER_SUSPENDED"
        touch(aircraft)
    for aircraft in victims:
        revoke_authorizations_of_aircraft(aircraft)


def maybe_auto_suspend(pilot):
    """Automatic suspension at a recomputed risk score of 70 or more."""
    if pilot["risk_score"] >= RISK_SUSPEND_THRESHOLD \
            and pilot["status"] in ("CERTIFIED", "LAPSED"):
        suspend_pilot(pilot, "RISK_THRESHOLD_REACHED")
        return True
    return False


# ---------------------------------------------------------------------------
# cascade: revoking a pilot
# ---------------------------------------------------------------------------

def revoke_pilot(pilot, reason):
    pilot["status"] = "REVOKED"
    pilot["suspension_reason"] = reason
    touch(pilot)
    for cert in store.all("certifications"):
        if cert["pilot_id"] == pilot["id"] and \
                cert["status"] in ("ACTIVE", "SUPERSEDED", "EXPIRED"):
            cert["status"] = "REVOKED"
            touch(cert)
    for aircraft in store.all("aircraft"):
        if aircraft["owner_pilot_id"] == pilot["id"] and \
                aircraft["registration_status"] in ("PENDING_REGISTRATION",
                                                    "REGISTERED", "GROUNDED"):
            aircraft["registration_status"] = "DEREGISTERED"
            aircraft["grounding_reason"] = "OWNER_REVOKED"
            touch(aircraft)
    open_waiver_states = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED",
                          "CLEARED", "APPROVED")
    for waiver in store.all("waivers"):
        if waiver["pilot_id"] == pilot["id"] and waiver["status"] in open_waiver_states:
            waiver["status"] = "REVOKED"
            touch(waiver)


# ---------------------------------------------------------------------------
# cascade: insurance ledger erosion
# ---------------------------------------------------------------------------

def apply_policy_ledger(policy, direction):
    """Recompute the ledger then run the derived coverage_status transition.

    ``direction`` is "erode" for a filing and "restore" for a closure or a
    withdrawal.
    """
    recompute_policy_ledger(policy)
    touch(policy)
    if direction == "erode":
        if policy["coverage_status"] == "ACTIVE" \
                and policy["remaining_coverage_cents"] < COMMERCIAL_MINIMUM_CENTS:
            policy["coverage_status"] = "INSUFFICIENT"
            touch(policy)
            cancel_flights_of_short_policy(policy)
    else:
        if policy["coverage_status"] == "INSUFFICIENT" \
                and policy["remaining_coverage_cents"] >= COMMERCIAL_MINIMUM_CENTS:
            policy["coverage_status"] = "ACTIVE"
            touch(policy)


def cancel_flights_of_short_policy(policy):
    """Only PLANNED commercial flights -- PREFLIGHT_CLEARED is left alone."""
    for flight in store.all("flights"):
        if flight.get("covering_policy_id") != policy["id"]:
            continue
        if flight["status"] != "PLANNED":
            continue
        if flight["operation_category"] != "COMMERCIAL":
            continue
        flight["status"] = "CANCELLED"
        flight["cancellation_reason"] = "COVERAGE_INSUFFICIENT"
        touch(flight)


# ---------------------------------------------------------------------------
# lazy state discovery (PRD 2.8)
# ---------------------------------------------------------------------------

def expire_modules_of_aircraft(aircraft):
    for module in store.all("modules"):
        if module["aircraft_id"] != aircraft["id"]:
            continue
        if module["status"] == "VERIFIED" and module.get("verified_until") is not None \
                and module["verified_until"] <= clock.now():
            module["status"] = "EXPIRED"
            touch(module)


def expire_authorization(authorization):
    if authorization is None:
        return
    if authorization["status"] == "APPROVED" \
            and authorization["window_end"] <= clock.now():
        authorization["status"] = "EXPIRED"
        touch(authorization)
        release_zone_slot(authorization)


def expire_tfrs_of_zone(zone):
    if zone is None:
        return
    for tfr in store.all("tfrs"):
        if tfr["zone_id"] != zone["id"]:
            continue
        if tfr["status"] == "ACTIVE" and tfr["effective_until"] <= clock.now():
            tfr["status"] = "EXPIRED"
            touch(tfr)


def lapse_pilot_if_stale(pilot):
    """A CERTIFIED pilot whose recomputed currency has run out moves to LAPSED."""
    if pilot["status"] != "CERTIFIED":
        return False
    if not currency_lapsed(pilot):
        return False
    write_currency(pilot)
    pilot["status"] = "LAPSED"
    touch(pilot)
    return True


def expire_policies_of_pilot(pilot_id):
    for policy in store.all("policies"):
        if policy["pilot_id"] != pilot_id:
            continue
        if policy["coverage_status"] in ("ACTIVE", "INSUFFICIENT") \
                and policy["effective_until"] <= clock.now():
            policy["coverage_status"] = "EXPIRED"
            touch(policy)


def active_verified_module(aircraft):
    """A module in VERIFIED whose validity still outlasts the current instant."""
    for module in store.all("modules"):
        if module["aircraft_id"] != aircraft["id"]:
            continue
        if module["status"] == "VERIFIED" and module.get("verified_until") is not None \
                and module["verified_until"] > clock.now():
            return module
    return None


def any_verified_module(aircraft):
    for module in store.all("modules"):
        if module["aircraft_id"] == aircraft["id"] and module["status"] == "VERIFIED":
            return module
    return None


def recompute_and_maybe_suspend(pilot):
    recompute_risk_score(pilot)
    touch(pilot)
    maybe_auto_suspend(pilot)


def check_remote_id(aircraft):
    """Rungs 20 and 21 (PRD 2.11, 3.3).

    Rung 20 measures presence over the modules that are VERIFIED or EXPIRED,
    because rung 20 enumerates only UNVERIFIED, VERIFICATION_PENDING,
    VERIFICATION_FAILED and the absence of any module row as its own failures --
    EXPIRED is deliberately absent from that list and falls through to rung 21.
    That is what keeps rung 21 reachable no matter whether the §2.8 lazy expiry
    has already run for this request: a module whose validity has run out yields
    ERR_REMOTE_ID_EXPIRED and never ERR_REMOTE_ID_NOT_VERIFIED. The expiry is
    applied here too, so it happens even though the call then fails.
    """
    from errors import ApiError
    if not aircraft.get("remote_id_required"):
        return
    present = [m for m in store.all("modules")
               if m["aircraft_id"] == aircraft["id"]
               and m["status"] in ("VERIFIED", "EXPIRED")]
    if not present:
        raise ApiError("ERR_REMOTE_ID_NOT_VERIFIED")
    live = [m for m in present
            if m["status"] == "VERIFIED" and m.get("verified_until") is not None
            and m["verified_until"] > clock.now()]
    if live:
        return
    for module in present:
        if module["status"] == "VERIFIED":
            module["status"] = "EXPIRED"
            touch(module)
    raise ApiError("ERR_REMOTE_ID_EXPIRED")
