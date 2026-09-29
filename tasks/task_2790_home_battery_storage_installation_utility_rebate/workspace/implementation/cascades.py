"""The four multi-hop cascades of PRD 2.9. Each hop is caused by the hop before it,
so a hop whose precondition fails stops the chain."""

import store
from calc import _stack_order_key, dec, final_basis, rebate_award
from common import CLAWBACK_SUSPENSION_THRESHOLD, kw


# --------------------------------------------------------------------------- #
# Shared: cancel pending participations and give the capacity back
# --------------------------------------------------------------------------- #

def _cancel_pending_participations(enrollment):
    performances = [
        performance
        for performance in store.rows("performances")
        if performance["byod_enrollment_id"] == enrollment["id"]
        and performance["status"] == "PENDING"
    ]
    for performance in performances:
        event = store.get("events", performance["dispatch_event_id"])
        if event is None or event["status"] != "SCHEDULED":
            continue
        performance["status"] = "CANCELLED"
        store.touch(performance)
        event["enrolled_pledged_kw"] = kw(
            dec(event["enrolled_pledged_kw"]) - dec(performance["pledged_kw_snapshot"])
        )
        store.touch(event)


def suspend_enrollments(system):
    """Suspend every ENROLLED enrollment of a bank and release its pending capacity."""
    enrollments = [
        enrollment
        for enrollment in store.rows("enrollments")
        if enrollment["battery_system_id"] == system["id"]
        and enrollment["status"] == "ENROLLED"
    ]
    for enrollment in enrollments:
        enrollment["status"] = "SUSPENDED"
        store.touch(enrollment)
        _cancel_pending_participations(enrollment)


def release_participations_for_withdrawal(enrollment):
    """Homeowner/installer withdrawal from an ENROLLED enrollment."""
    _cancel_pending_participations(enrollment)


# --------------------------------------------------------------------------- #
# Cascade A -- inspection FAIL recorded against a passed inspection
# --------------------------------------------------------------------------- #

def cascade_a(permit):
    system = store.get("battery_systems", permit["battery_system_id"])
    if system is None:
        return
    application = None
    for candidate in store.rows("applications"):
        if candidate["battery_system_id"] == system["id"] and candidate["status"] in (
            "APPROVED_TO_INSTALL",
            "PTO_GRANTED",
        ):
            application = candidate
            break
    if application is None:
        return

    was_pto = application["status"] == "PTO_GRANTED"
    application["status"] = "SUPPLEMENTAL_REVIEW"
    application["supplemental_round_count"] += 1
    application["approved_export_kw"] = None
    if was_pto:
        application["pto_granted_by_user_id"] = None
        application["pto_granted_at"] = None
    store.touch(application)

    if system["grid_status"] not in ("APPROVED_TO_INSTALL", "PTO_GRANTED"):
        return
    bank_was_pto = system["grid_status"] == "PTO_GRANTED"
    system["grid_status"] = "APPLICATION_SUBMITTED"
    store.touch(system)

    if bank_was_pto:
        suspend_enrollments(system)


# --------------------------------------------------------------------------- #
# Cascade B -- commissioning re-prices open claims
# --------------------------------------------------------------------------- #

def cascade_b(system):
    claims = [
        claim
        for claim in store.rows("claims")
        if claim["battery_system_id"] == system["id"]
        and claim["status"] in ("RESERVED", "SUBMITTED")
    ]
    for claim in sorted(claims, key=_stack_order_key):
        program = store.get("programs", claim["program_id"])
        if program is None:
            continue
        basis = final_basis(system)
        amount, _ceiling, _headroom = rebate_award(
            system, program, claim["export_commitment"], basis, exclude_claim_id=claim["id"]
        )
        reserved = int(claim["reserved_amount_cents"])
        final_amount = amount if amount < reserved else reserved
        claim["basis_kwh_final"] = basis
        claim["final_amount_cents"] = final_amount
        store.touch(claim)

        difference = reserved - final_amount
        if difference != 0:
            program["reserved_budget_cents"] -= difference
            program["remaining_budget_cents"] += difference
            store.touch(program)


# --------------------------------------------------------------------------- #
# Cascade C -- expansion supersedes the base bank
# --------------------------------------------------------------------------- #

def cascade_c(base_system):
    base_system["build_status"] = "SUPERSEDED"
    store.touch(base_system)
    suspend_enrollments(base_system)


# --------------------------------------------------------------------------- #
# Cascade D -- clawback suspends the installer and holds its open designs
# --------------------------------------------------------------------------- #

def cascade_d(claim, system):
    installer = store.get("installers", system["installer_id"]) if system else None
    if installer is None:
        return
    installer["clawback_count"] += 1
    suspended = installer["clawback_count"] >= CLAWBACK_SUSPENSION_THRESHOLD
    if suspended:
        installer["certification_status"] = "SUSPENDED"
    store.touch(installer)

    if not suspended:
        return
    for bank in store.rows("battery_systems"):
        if bank["installer_id"] != installer["id"]:
            continue
        if bank["build_status"] not in ("DESIGN_DRAFT", "DESIGN_LOCKED"):
            continue
        bank["build_status"] = "DESIGN_HOLD"
        store.touch(bank)
