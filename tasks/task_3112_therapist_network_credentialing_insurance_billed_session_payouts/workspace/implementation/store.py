"""In-memory data store.  Every table is a dict keyed by id.

The store starts empty on every boot: nothing here is seeded or preloaded.
"""
from __future__ import annotations

from datetime import timedelta

from errors import fail
from util import UTC, ceil_hours, fmt_ts, new_id, now

TABLES = (
    "clinicians",
    "licenses",
    "malpractice_policies",
    "payers",
    "payer_rates",
    "payer_enrollments",
    "patients",
    "benefit_verifications",
    "sessions",
    "session_notes",
    "claims",
    "payout_batches",
    "payout_lines",
    "continuity_plans",
)

TABLES_MAP: dict[str, dict] = {name: {} for name in TABLES}

CONTINUITY_GRACE_DAYS = 30
CONTINUITY_EXTENSION_DAYS = 7
NEW_CLINICIAN_WINDOW_DAYS = 90
GEOGRAPHY_ACTIVATION = "2026-07-01T00:00:00Z"
SCHEDULING_BUFFER_MINUTES = 15

LICENSE_TYPES = {"LCSW", "LMFT", "LPC", "LMHC", "PSY_D", "PHD"}
MODALITIES = {"VIDEO", "PHONE", "IN_PERSON"}
SCHEDULES = {"WEEKLY", "BIWEEKLY", "SEMIMONTHLY"}
DENIAL_CODES = {
    "TIMELY_FILING",
    "NOT_COVERED",
    "MISSING_DOCUMENTATION",
    "AUTHORIZATION_REQUIRED",
    "DUPLICATE",
}
CONTINUITY_REASONS = {"OFFBOARDING", "CASELOAD_REBALANCE", "CLINICAL_CONFLICT"}


def reset() -> None:
    for name in TABLES:
        TABLES_MAP[name].clear()


def table(name: str) -> dict:
    return TABLES_MAP[name]


def create_row(name: str, **fields) -> dict:
    ts = fmt_ts(now())
    row = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    row.update(fields)
    TABLES_MAP[name][row["id"]] = row
    return row


def touch(row: dict) -> dict:
    """Refresh updated_at and advance version (PRD §2.6)."""
    row["updated_at"] = fmt_ts(now())
    row["version"] = int(row.get("version", 1)) + 1
    return row


def set_derived(row: dict, name: str, value) -> None:
    """Store a derived value without touching version/updated_at."""
    row[name] = value


# --------------------------------------------------------------- lookups


def get(name: str, row_id) -> dict | None:
    if not isinstance(row_id, str):
        return None
    return TABLES_MAP[name].get(row_id)


def require(name: str, row_id, error_id: str) -> dict:
    row = get(name, row_id)
    if row is None:
        raise fail(error_id)
    return row


def all_rows(name: str) -> list:
    return list(TABLES_MAP[name].values())


def rows_where(name: str, **criteria) -> list:
    out = []
    for row in TABLES_MAP[name].values():
        if all(row.get(k) == v for k, v in criteria.items()):
            out.append(row)
    return out


def sort_asc(rows: list) -> list:
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))


# --------------------------------------------------------------- derivations


def license_effective_status(row: dict) -> str:
    """PRD §3.1: FAILED, then EXPIRED, then VERIFIED, else UNVERIFIED."""
    expires_on = row.get("expires_on")
    if not isinstance(expires_on, str):
        return "UNVERIFIED"
    if row.get("verify_attempt_failed") and not row.get("reset_since_failure"):
        return "FAILED"
    if now_ts() >= expires_on:
        return "EXPIRED"
    if row.get("verified_at") is not None and now_ts() < expires_on:
        return "VERIFIED"
    return "UNVERIFIED"


def now_ts() -> str:
    return fmt_ts(now())


def now_instant():
    return now()


def policy_status(row: dict) -> str:
    """PRD §3.1: PENDING before effective_on, ACTIVE up to expires_on, LAPSED after."""
    clock = now_instant()
    effective_on = row.get("_effective_on_dt")
    expires_on = row.get("_expires_on_dt")
    if effective_on is None or expires_on is None:
        return "PENDING"
    if clock < effective_on:
        return "PENDING"
    if clock >= expires_on:
        return "LAPSED"
    return "ACTIVE"


def benefit_status(row: dict) -> str:
    """PRD §3.3: UNVERIFIED with no snapshot, otherwise the newest snapshot's status.

    The specification states a snapshot reads VERIFIED until it 'ages out' but
    fixes no aging boundary anywhere in the document, so the newest snapshot's
    own status is what the patient reads.
    """
    snaps = [v for v in all_rows("benefit_verifications") if v.get("patient_id") == row["id"]]
    if not snaps:
        return "UNVERIFIED"
    newest = sorted(snaps, key=lambda v: (v.get("verified_at") or "", v.get("created_at") or ""))[-1]
    return newest.get("status") or "UNVERIFIED"


def v_date(row: dict):
    from util import parse_ts
    return parse_ts(row.get("verified_at")) or now_instant()


def enrolled_payer_count(clinician: dict) -> int:
    return len(
        [
            e
            for e in all_rows("payer_enrollments")
            if e.get("clinician_id") == clinician["id"] and e.get("status") == "EFFECTIVE"
        ]
    )


def billing_posture(clinician: dict) -> str:
    """PRD §2.4 fixed precedence: FROZEN, then GATED, then BILLABLE.

    §3.7 states that requesting offboarding 'drops billing_posture to GATED',
    so an OFFBOARDING clinician reads GATED rather than BILLABLE even while
    every license and policy is in order.
    """
    if clinician.get("status") in ("SUSPENDED", "OFFBOARDED"):
        return "FROZEN"
    if enrolled_payer_count(clinician) == 0:
        return "FROZEN"
    if clinician.get("status") == "OFFBOARDING":
        return "GATED"
    licenses = [r for r in all_rows("licenses") if r.get("clinician_id") == clinician["id"]]
    if not any(license_effective_status(r) == "VERIFIED" for r in licenses):
        return "GATED"
    policies = [r for r in all_rows("malpractice_policies") if r.get("clinician_id") == clinician["id"]]
    if not any(policy_status(r) == "ACTIVE" for r in policies):
        return "GATED"
    return "BILLABLE"


def refresh_posture(clinician: dict) -> str:
    posture = billing_posture(clinician)
    set_derived(clinician, "billing_posture", posture)
    # CREDENTIALING -> ACTIVE is a system transition driven by the posture itself.
    if clinician.get("status") == "CREDENTIALING" and posture == "BILLABLE":
        clinician["status"] = "ACTIVE"
    return posture


def refresh_all_postures() -> None:
    for clinician in all_rows("clinicians"):
        refresh_posture(clinician)


def active_patient_count(clinician: dict) -> int:
    return len(
        [
            p
            for p in all_rows("patients")
            if p.get("matched_clinician_id") == clinician["id"]
        ]
    )


def matched_patients(clinician: dict) -> list:
    return [p for p in all_rows("patients") if p.get("matched_clinician_id") == clinician["id"]]


def session_length_minutes(session: dict) -> int:
    start = session.get("_start_dt")
    end = session.get("_end_dt")
    if start is None or end is None:
        return 0
    return int((end - start).total_seconds() // 60)


def open_slot_count(clinician: dict) -> int:
    """Unbooked availability in whole hours (PRD §2.5, §3.1).

    §3.1 pins the arithmetic and the unit: "an `open_slot_count` derived from
    the availability blocks that were supplied — full minutes divided by 60,
    rounding up, so an availability of 90 minutes counts as 2 whole hours."  A
    600-minute block therefore reads 10, and §2.5's "whole-minute arithmetic and
    a ceiling" is the same operation described from the other side: the leftover
    partial hour is not rounded away, it becomes a whole hour of capacity.
    §3.7 depends on the same unit when it requires `open_slot_count` to be 0
    before offboarding can be requested.
    """
    total = 0
    for block in clinician.get("availability_blocks") or []:
        try:
            total += max(0, int(block["end_minute"]) - int(block["start_minute"]))
        except (KeyError, TypeError, ValueError):
            continue
    consumed = 0
    for session in all_rows("sessions"):
        if session.get("clinician_id") != clinician["id"]:
            continue
        if not session.get("slot_consumed"):
            continue
        consumed += session_length_minutes(session)
    return ceil_hours(max(0, total - consumed))


def visit_count_year(patient: dict) -> int:
    return len(
        [
            s
            for s in all_rows("sessions")
            if s.get("patient_id") == patient["id"] and s.get("status") == "COMPLETED"
        ]
    )


def continuity_plan_count(clinician: dict) -> int:
    return len(
        [
            p
            for p in all_rows("continuity_plans")
            if p.get("clinician_id") == clinician["id"] and p.get("status") != "COMPLETED"
        ]
    )


def new_clinician_threshold(clinician: dict):
    from util import parse_ts

    onboarded = parse_ts(clinician.get("onboarded_at"))
    if onboarded is None:
        return None
    return onboarded + timedelta(days=NEW_CLINICIAN_WINDOW_DAYS)


def reify(clinician: dict) -> dict:
    """Refresh every derived field on a clinician row before serialisation."""
    refresh_posture(clinician)
    set_derived(clinician, "active_patient_count", active_patient_count(clinician))
    set_derived(clinician, "open_slot_count", open_slot_count(clinician))
    set_derived(clinician, "enrolled_payer_count", enrolled_payer_count(clinician))
    set_derived(clinician, "payout_balance_cents", payout_balance_cents(clinician))
    set_derived(clinician, "continuity_plan_count", continuity_plan_count(clinician))
    return clinician


def payout_balance_cents(clinician: dict) -> int:
    total = 0
    for line in all_rows("payout_lines"):
        if line.get("clinician_id") != clinician["id"]:
            continue
        status = line.get("line_status")
        if status == "PAID":
            total += int(line.get("net_cents") or 0)
        elif status == "CLAWED_BACK":
            total += int(line.get("adjustment_cents") or 0)
    return total


def line_for_session(session_id: str):
    for line in all_rows("payout_lines"):
        if session_id in (line.get("session_ids") or []):
            return line
    return None


def newest_line(clinician_id: str):
    lines = [l for l in all_rows("payout_lines") if l.get("clinician_id") == clinician_id]
    if not lines:
        return None
    return sorted(lines, key=lambda l: (l.get("created_at") or "", l.get("id") or ""))[-1]


def newest_payable_line(clinician_id: str):
    lines = [
        l
        for l in all_rows("payout_lines")
        if l.get("clinician_id") == clinician_id and l.get("line_status") in ("PENDING", "PAID")
    ]
    if not lines:
        return None
    return sorted(lines, key=lambda l: (l.get("created_at") or "", l.get("id") or ""))[-1]


def notes_for(session_id: str) -> list:
    return sort_asc([n for n in all_rows("session_notes") if n.get("session_id") == session_id])


def newest_note(session_id: str):
    notes = notes_for(session_id)
    return notes[-1] if notes else None


def snapshots_for(patient_id: str) -> list:
    rows = [v for v in all_rows("benefit_verifications") if v.get("patient_id") == patient_id]
    return sorted(rows, key=lambda r: (r.get("verified_at") or "", r.get("created_at") or ""))


def newest_verified_snapshot(patient_id: str):
    for row in reversed(snapshots_for(patient_id)):
        if row.get("status") == "VERIFIED":
            return row
    return None


def enrollment_covers(clinician_id: str, payer_id: str, service_start):
    """Returns (enrollment, 'ok'|'outside'|'none')."""
    from util import parse_ts

    covering = []
    for row in all_rows("payer_enrollments"):
        if row.get("clinician_id") != clinician_id or row.get("payer_id") != payer_id:
            continue
        if row.get("status") != "EFFECTIVE":
            continue
        eff_from = parse_ts(row.get("effective_from"))
        eff_to = parse_ts(row.get("effective_to"))
        if eff_from is None:
            continue
        if service_start < eff_from:
            continue
        if eff_to is not None and service_start >= eff_to:
            continue
        covering.append(row)
    if covering:
        return covering[0], "ok"
    for row in all_rows("payer_enrollments"):
        if row.get("clinician_id") != clinician_id or row.get("payer_id") != payer_id:
            continue
        if row.get("status") not in ("EFFECTIVE",):
            continue
        eff_from = parse_ts(row.get("effective_from"))
        eff_to = parse_ts(row.get("effective_to"))
        if eff_from is None:
            continue
        if service_start < eff_from or (eff_to is not None and service_start >= eff_to):
            return row, "outside"
    return None, "none"


def resync() -> None:
    """Clock-driven reconciliation (PRD §2.10, §3.1, §3.2, §3.7)."""
    clock = now_instant()

    for enrollment in all_rows("payer_enrollments"):
        if enrollment.get("status") != "EFFECTIVE":
            continue
        payer = get("payers", enrollment.get("payer_id"))
        if payer is not None and payer.get("status") in ("SUSPENDED_AT_PAYER", "TERMINATED"):
            enrollment["status"] = "SUSPENDED"
            touch(enrollment)

    for clinician in all_rows("clinicians"):
        refresh_posture(clinician)

    for clinician in all_rows("clinicians"):
        posture = clinician.get("billing_posture")
        if posture != "FROZEN":
            continue
        for session in all_rows("sessions"):
            if session.get("clinician_id") != clinician["id"]:
                continue
            if session.get("status") in ("REQUESTED", "SCHEDULED"):
                session["status"] = "CANCELLED"
                set_derived(session, "slot_consumed", False)
                touch(session)
        set_derived(clinician, "open_slot_count", open_slot_count(clinician))

    from util import parse_ts

    for plan in all_rows("continuity_plans"):
        if plan.get("status") not in ("PENDING", "DECLINED"):
            continue
        deadline = parse_ts(plan.get("reassignment_deadline"))
        if deadline is None:
            continue
        if clock < deadline:
            continue
        plan["status"] = "ESCALATED"
        touch(plan)
        patient = get("patients", plan.get("patient_id"))
        if patient is not None:
            patient["swap_requested"] = True

    for clinician in all_rows("clinicians"):
        if clinician.get("status") == "OFFBOARDING" and active_patient_count(clinician) == 0:
            finalize_offboarding(clinician)


def finalize_offboarding(clinician: dict) -> None:
    clinician["status"] = "OFFBOARDED"
    set_derived(clinician, "billing_posture", "FROZEN")
    set_derived(clinician, "active_patient_count", active_patient_count(clinician))
    set_derived(clinician, "open_slot_count", open_slot_count(clinician))
    set_derived(clinician, "continuity_plan_count", continuity_plan_count(clinician))
    for plan in all_rows("continuity_plans"):
        if plan.get("clinician_id") != clinician["id"]:
            continue
        if plan.get("status") == "PENDING":
            plan["status"] = "ESCALATED"
            touch(plan)
            patient = get("patients", plan.get("patient_id"))
            if patient is not None:
                patient["swap_requested"] = True
    for session in all_rows("sessions"):
        if session.get("clinician_id") != clinician["id"]:
            continue
        if session.get("status") in ("REQUESTED", "SCHEDULED"):
            session["status"] = "CANCELLED"
            set_derived(session, "slot_consumed", False)
            touch(session)
    touch(clinician)