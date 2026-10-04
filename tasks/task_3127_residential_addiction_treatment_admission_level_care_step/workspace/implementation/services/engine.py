"""Shared clinical engine: placement, admission, discharge, changes, ops batch."""

from datetime import timedelta

from common import (
    base_fields,
    iso,
    level_rank,
    parse_iso,
    public,
    round_half_up,
    tier_rank,
    touch,
)
from db import STORE
from decimal import Decimal
from errors import ApiError
from services import calc, facility as facility_svc


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def facility_of(episode):
    return STORE.get("Facility", episode.get("_facility_id"))


def live_authorizations(episode):
    return STORE.where(
        "LevelOfCareAuthorization",
        lambda r: r.get("_episode_id") == episode["id"] and r.get("posture") not in ("DENIED", "EXPIRED"),
    )


def active_authorization(episode):
    """The episode's operative authorization: the most recently created live
    one, falling back to the newest authorization of any posture."""
    rows = STORE.where("LevelOfCareAuthorization", lambda r: r.get("_episode_id") == episode["id"])
    if not rows:
        return None
    live = [r for r in rows if r.get("posture") not in ("DENIED", "EXPIRED")]
    pool = live if live else rows
    pool.sort(key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0))
    return pool[-1]


def withdrawal_plan(episode):
    rows = STORE.where("WithdrawalManagementPlan", lambda r: r.get("_episode_id") == episode["id"])
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0))
    return rows[-1]


def active_treatment_plan(episode):
    rows = STORE.where(
        "TreatmentPlan",
        lambda r: r.get("_episode_id") == episode["id"] and r.get("status") == "ACTIVE",
    )
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0))
    return rows[-1]


def any_treatment_plan(episode):
    rows = STORE.where("TreatmentPlan", lambda r: r.get("_episode_id") == episode["id"])
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0))
    return rows[-1]


def active_continuing_care(episode):
    rows = STORE.where(
        "ContinuingCarePlan",
        lambda r: r.get("_episode_id") == episode["id"] and r.get("status") == "ACTIVE",
    )
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0))
    return rows[-1]


def session_rows(episode):
    return STORE.where("SessionAttendance", lambda r: r.get("_episode_id") == episode["id"])


def episode_bed(episode):
    """The bed currently occupied by this episode, if any."""
    for change in sorted(
        STORE.where("LevelOfCareChange", lambda r: r.get("_episode_id") == episode["id"]),
        key=lambda r: (r.get("created_at") or "", r.get("_created_seq") or 0),
        reverse=True,
    ):
        bed_id = change.get("bed_id")
        bed = STORE.get("Bed", bed_id) if bed_id else None
        if bed is not None and bed.get("status") == "OCCUPIED":
            return bed
    for auth in STORE.where("LevelOfCareAuthorization", lambda r: r.get("_episode_id") == episode["id"]):
        bed_id = auth.get("bed_id")
        bed = STORE.get("Bed", bed_id) if bed_id else None
        if bed is not None and bed.get("status") == "OCCUPIED":
            return bed
    return None


# ---------------------------------------------------------------------------
# Medical clearance derivation
# ---------------------------------------------------------------------------

def clearance_view(row, now):
    out = public(row)
    if row.get("status") == "CLEARED" and row.get("expires_at"):
        expires = parse_iso(row["expires_at"], "expires_at")
        hours, days = calc.clearance_windows(expires, now)
        out["window_hours_remaining"] = hours
        out["window_days_remaining"] = days
        out["effective_status"] = "CLEARED" if hours > 0 else "EXPIRED"
    else:
        out["window_hours_remaining"] = 0
        out["window_days_remaining"] = 0
        out["effective_status"] = row.get("status")
    return out


def clearance_effective(row, now):
    if row.get("status") == "CLEARED" and row.get("expires_at"):
        expires = parse_iso(row["expires_at"], "expires_at")
        hours, _ = calc.clearance_windows(expires, now)
        return hours, "CLEARED" if hours > 0 else "EXPIRED"
    return 0, row.get("status")


# ---------------------------------------------------------------------------
# Credential checks
# ---------------------------------------------------------------------------

def authoring_credential_ok_soft(clinician, floor_tier):
    """True when the clinician's tier is at or above the given floor tier."""
    if clinician is None or floor_tier is None:
        return True
    return tier_rank(clinician.get("credential_tier")) >= tier_rank(floor_tier)


def authoring_credential_ok(clinician_id, facility, now):
    clinician = STORE.get("Clinician", clinician_id)
    if clinician is None:
        raise ApiError("ERR_CLINICIAN_NOT_FOUND")
    if tier_rank(clinician.get("credential_tier")) < tier_rank(facility.get("state_min_credential_tier")):
        raise ApiError("ERR_ASSESSOR_CREDENTIAL_INSUFFICIENT")
    credential = STORE.first(
        "ClinicianFacilityCredential",
        lambda r: r.get("clinician_id") == clinician_id and r.get("facility_id") == facility["id"],
    )
    if credential is None:
        raise ApiError("ERR_ASSESSOR_CREDENTIAL_INSUFFICIENT")
    effective = parse_iso(credential["effective_at"], "effective_at")
    expires = parse_iso(credential["expires_at"], "expires_at")
    if not (credential.get("status") == "ACTIVE" and effective <= now < expires):
        raise ApiError("ERR_ASSESSOR_CREDENTIAL_INSUFFICIENT")
    return clinician


# ---------------------------------------------------------------------------
# Episode placement
# ---------------------------------------------------------------------------

def place_episode(episode, assessment, now):
    episode["assigned_level"] = assessment.get("recommended_level")
    episode["clinical_status"] = "AWAITING_AUTHORIZATION"
    episode["updated_at"] = iso(now)
    episode["version"] = episode.get("version", 1) + 1


def clearances_all_cleared(episode, now):
    """True when every clearance currently recorded on the episode reads CLEARED."""
    rows = STORE.where("MedicalClearance", lambda r: r.get("_episode_id") == episode["id"])
    if not rows:
        return False
    for row in rows:
        _, effective = clearance_effective(row, now)
        if effective != "CLEARED":
            return False
    return True


def promote_to_awaiting_admission(clearance, now):
    """PRD §3.2: "Once every clearance on the episode still reads `CLEARED`, the
    episode advances from `AWAITING_AUTHORIZATION` to `AWAITING_ADMISSION`."

    Called from the approval path and from every clearance-clearing path, since the
    last of the two conditions to turn true is what actually advances the episode.
    """
    episode = STORE.get("TreatmentEpisode", clearance.get("_episode_id"))
    if episode is None or episode.get("clinical_status") != "AWAITING_AUTHORIZATION":
        return episode
    authorization = active_authorization(episode)
    if authorization is None or authorization.get("posture") != "APPROVED":
        return episode
    if not clearances_all_cleared(episode, now):
        return episode
    episode["clinical_status"] = "AWAITING_ADMISSION"
    episode["version"] = episode.get("version", 1) + 1
    episode["updated_at"] = iso(now)
    return episode


def supersede_other_assessments(episode, keep_id, now):
    for row in STORE.where(
        "ClinicalAssessment",
        lambda r: r.get("_episode_id") == episode["id"] and r.get("status") == "IN_PROGRESS" and r["id"] != keep_id,
    ):
        row["status"] = "SUPERSEDED"
        row["updated_at"] = iso(now)
        row["version"] = row.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------

def admit_episode(facility, episode, now, user_id=None):
    if episode.get("clinical_status") == "DISCHARGED":
        raise ApiError("ERR_ALREADY_DISCHARGED")
    if episode.get("clinical_status") != "AWAITING_ADMISSION":
        raise ApiError("ERR_EPISODE_NOT_AWAITING_ADMISSION")

    # PRD §2.7a places the facility *safety* rules after the state rules but ahead of
    # every clearance condition, so a frozen facility is refused before the clearance
    # and fiscal checks are looked at.
    if facility.get("facility_posture") == "FROZEN":
        raise ApiError("ERR_FACILITY_POSTURE_FROZEN")

    clearances = STORE.where("MedicalClearance", lambda r: r.get("_episode_id") == episode["id"])
    medical_cleared = False
    tb_cleared = False
    tb_raw_cleared = False
    tb_expires = None
    for row in clearances:
        _, effective = clearance_effective(row, now)
        if row.get("clearance_type") == "MEDICAL" and effective == "CLEARED":
            medical_cleared = True
        if row.get("clearance_type") == "TB_SCREEN":
            if row.get("status") == "CLEARED":
                tb_raw_cleared = True
                tb_expires = parse_iso(row["expires_at"], "expires_at")
            if effective == "CLEARED":
                tb_cleared = True
                tb_expires = parse_iso(row["expires_at"], "expires_at")

    # PRD §2.7a orders the business rules by kind: facility safety (frozen posture,
    # licensure, accreditation standing) runs before the clinical clearance rules,
    # because "Facility safety rules follow" the state rules.
    if facility.get("facility_posture") == "FROZEN":
        raise ApiError("ERR_FACILITY_POSTURE_FROZEN")

    if not (medical_cleared and tb_cleared):
        # PRD §3.3: the TB screen's expiry is exclusive, so a row whose raw status is
        # still CLEARED but whose window has closed is a *lapse* — reported as
        # ERR_MEDICAL_CLEARANCE_EXPIRED (HTTP 410) — rather than as a clearance that
        # was never cleared. That branch must be tested before the not-cleared one.
        if tb_raw_cleared and (tb_expires is None or not (tb_expires > now)):
            raise ApiError("ERR_MEDICAL_CLEARANCE_EXPIRED")
        raise ApiError("ERR_MEDICAL_CLEARANCE_NOT_CLEARED")
    if tb_expires is None or not (tb_expires > now):
        raise ApiError("ERR_MEDICAL_CLEARANCE_EXPIRED")

    plan = withdrawal_plan(episode)
    if plan is None or plan.get("status") != "ACTIVE":
        raise ApiError("ERR_WITHDRAWAL_MANAGEMENT_NOT_ACTIVE")

    treatment_plan = active_treatment_plan(episode)
    if treatment_plan is None:
        raise ApiError("ERR_TREATMENT_PLAN_NOT_ACTIVE")

    if not facility.get("licensed") or not facility_svc.has_accreditation_body(facility, now):
        raise ApiError("ERR_FACILITY_ACCREDITATION_INVALID")

    authorization = active_authorization(episode)
    if authorization is None:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    if int(authorization.get("days_remaining") or 0) <= 0:
        raise ApiError("ERR_AUTHORIZATION_DAYS_EXHAUSTED")

    held = authorization.get("bed_id")
    if held:
        bed = STORE.get("Bed", held)
        if row is None or bed.get("status") != "OCCUPIED":
            if row is None or row.get("_bed_held") is not True:
                raise ApiError("ERR_BED_NOT_HELD")

    episode["admitted_at"] = iso(now)
    episode["clinical_status"] = "IN_TREATMENT"
    episode["care_level_status"] = "ACTIVE"
    episode["version"] = episode.get("version", 1) + 1
    episode["updated_at"] = iso(now)
    return episode


# ---------------------------------------------------------------------------
# Discharge
# ---------------------------------------------------------------------------

def discharge_episode(facility, episode, now):
    status = episode.get("clinical_status")
    if status == "DISCHARGED":
        raise ApiError("ERR_ALREADY_DISCHARGED")
    if status not in ("IN_TREATMENT", "COMPLETED"):
        raise ApiError("ERR_EPISODE_NOT_COMPLETED")

    if facility.get("facility_posture") == "FROZEN":
        raise ApiError("ERR_FACILITY_POSTURE_FROZEN")
    if not facility_svc.has_accreditation_body(facility, now):
        raise ApiError("ERR_FACILITY_ACCREDITATION_INVALID")

    plan = withdrawal_plan(episode)

    cc_plan = active_continuing_care(episode)
    if cc_plan is None:
        # PRD §3.7: the call "is refused with ERR_CONTINUING_CARE_PLAN_REQUIRED and
        # the episode performs no mutation at all". The release is deferred onto an
        # AWAITING_DISCHARGE change row and the bed is untouched here; the cycle's
        # hold and release legs both happen on the run, in stage seven.
        _defer_release(facility, episode, now)
        raise ApiError("ERR_CONTINUING_CARE_PLAN_REQUIRED")

    if plan is None or plan.get("status") not in ("MEDICALLY_STABLE", "ACTIVE"):
        raise ApiError("ERR_WITHDRAWAL_MANAGEMENT_NOT_ACTIVE")

    if status == "IN_TREATMENT":
        _defer_release(facility, episode, now)
        return episode

    if plan.get("status") != "MEDICALLY_STABLE":
        raise ApiError("ERR_WITHDRAWAL_MANAGEMENT_NOT_STABLE")
    if cc_plan.get("housing_selection_basis") != "EXPLICIT" and cc_plan.get("housing_id") is None:
        _activate_ranked(cc_plan, facility, now)

    author = STORE.get("Clinician", cc_plan.get("authorizing_clinician_id"))
    if author is None or tier_rank(author.get("credential_tier")) < tier_rank(calc.MIN_CREDENTIAL_TIER_FOR_DISCHARGE):
        raise ApiError("ERR_FACILITY_ACCREDITATION_INVALID")

    _materialize_contacts(episode, cc_plan, now)

    bed = episode_bed(episode)
    if bed is not None:
        schedule_bed_release(bed, now)

    episode["clinical_status"] = "DISCHARGED"
    episode["discharged_at"] = iso(now)
    episode["version"] = episode.get("version", 1) + 1
    episode["updated_at"] = iso(now)
    return episode


def schedule_bed_release(bed, now):
    bed["status"] = "CLEANING"
    bed["next_available_at"] = iso(now + timedelta(hours=int(bed.get("cleaning_turnaround_hours") or 0)))
    bed["version"] = bed.get("version", 1) + 1
    bed["updated_at"] = iso(now)


def schedule_bed_occupancy(bed, now):
    bed["status"] = "OCCUPIED"
    bed["next_available_at"] = None
    bed["version"] = bed.get("version", 1) + 1
    bed["updated_at"] = iso(now)


def _defer_release(facility, episode, now, bed=None):
    payer = None
    authorization = active_authorization(episode)
    if authorization is not None:
        payer = STORE.get("Payer", authorization.get("payer_id"))
    to_level = None
    if payer is not None:
        exclude = _funded_levels(episode)
        to_level = calc.next_covered_level(payer, episode.get("assigned_level"), exclude)
    row = base_fields("LevelOfCareChange")
    row["_facility_id"] = facility["id"]
    row["_episode_id"] = episode["id"]
    row["episode_id"] = episode["id"]
    row["facility_id"] = facility["id"]
    row["authorization_id"] = authorization["id"] if authorization else None
    if bed is None:
        bed = episode_bed(episode)
    row["bed_id"] = (bed or {}).get("id")
    row["from_level"] = episode.get("assigned_level")
    row["to_level"] = to_level
    row["change_type"] = "STEP_DOWN"
    row["effective_at"] = iso(now)
    row["retry_available_at"] = iso(now + timedelta(hours=24))
    row["status"] = "AWAITING_DISCHARGE"
    row["_created_seq"] = STORE.next_episode_seq(episode["id"])
    row["_step_up"] = False
    STORE.put("LevelOfCareChange", row)
    return row


def _funded_levels(episode):
    funded = set()
    for row in STORE.where("LevelOfCareChange", lambda r: r.get("_episode_id") == episode["id"]):
        if row.get("to_level"):
            funded.add(row["to_level"])
    return funded


def _materialize_contacts(episode, cc_plan, now):
    interval = int(cc_plan.get("alumni_contact_interval_days") or 0)
    required = int(cc_plan.get("alumni_contacts_required") or 0)
    existing = {r.get("attempt_number") for r in STORE.where("AlumniContact", lambda r: r.get("_episode_id") == episode["id"])}
    for attempt, scheduled in calc.alumni_schedule(now, interval, required):
        if attempt in existing:
            continue
        row = base_fields("AlumniContact")
        row["_facility_id"] = episode["_facility_id"]
        row["_episode_id"] = episode["id"]
        row["episode_id"] = episode["id"]
        row["facility_id"] = episode["_facility_id"]
        row["scheduled_for"] = iso(scheduled)
        row["attempt_number"] = attempt
        row["outcome"] = "PENDING"
        row["abstinent_at_contact"] = None
        row["record_filed_at"] = None
        row["recorded_by_user_id"] = None
        STORE.put("AlumniContact", row)


def _activate_ranked(plan, facility, now):
    active_by_house = {}
    for other in STORE.where("ContinuingCarePlan", lambda r: r.get("status") == "ACTIVE"):
        if other["id"] == plan["id"]:
            continue
        active_by_house[other.get("housing_id")] = active_by_house.get(other.get("housing_id"), 0) + 1
    pool = calc.ranked_housing_pool(facility, plan, active_by_house)
    if not pool:
        raise ApiError("ERR_HOUSING_POOL_EXHAUSTED")
    plan["housing_id"] = pool[0]["id"]


# ---------------------------------------------------------------------------
# Level-of-care changes
# ---------------------------------------------------------------------------

def change_branch(change):
    to_level = change.get("to_level")
    if to_level in ("ASAM_1_0", "ASAM_2_1"):
        return "PENDING_DISCHARGE_ORDER"
    if not change.get("bed_id"):
        return "PENDING_DISCHARGE_ORDER"
    if level_rank(to_level) < level_rank(change.get("from_level")):
        return "COMPLETED"
    return "PENDING_DISCHARGE_ORDER"


def complete_change(facility, change, now):
    if change.get("status") != "PLANNED":
        raise ApiError("ERR_CHANGE_NOT_PLANNED")
    effective = parse_iso(change["effective_at"], "effective_at")
    if effective > now:
        raise ApiError("ERR_CHANGE_NOT_DUE")

    authorization = STORE.get("LevelOfCareAuthorization", change.get("authorization_id"))
    if authorization is None:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    # PRD §3.6: the PENDING_DISCHARGE_ORDER branch also "moves to COMPLETED once its
    # target authorization is APPROVED, or is refused with ERR_AUTHORIZATION_NOT_APPROVED".
    if authorization.get("posture") != "APPROVED":
        raise ApiError("ERR_AUTHORIZATION_NOT_APPROVED")

    branch = change_branch(change)
    if branch == "PENDING_DISCHARGE_ORDER":
        change["status"] = "PENDING_DISCHARGE_ORDER"
        change["updated_at"] = iso(now)
        change["version"] = change.get("version", 1) + 1
        return change

    episode = STORE.get("TreatmentEpisode", change["_episode_id"])
    # Mark the branch before finalizing so the ledger moves can tell the two
    # completion branches apart (PRD §3.6 states the count increment on the
    # direct-COMPLETED branch only).
    change["status"] = "COMPLETED"
    _finalize_change(facility, change, episode, authorization, now)
    # Record the ops epoch the completion landed in so a later cancel can tell
    # whether a facility-ops run has intervened (ERR_EPOCH_STALE).
    change["_completed_epoch"] = facility.get("ops_epoch")
    change["updated_at"] = iso(now)
    change["version"] = change.get("version", 1) + 1
    return change


def _finalize_change(facility, change, episode, authorization, now):
    """Forward leg of the bed-night ledger. `change['bed_id']` names the
    TARGET bed; the source bed is whatever the episode currently holds."""
    target = STORE.get("Bed", change["bed_id"]) if change.get("bed_id") else None
    source = episode_bed(episode) if episode is not None else None
    if source is not None and target is not None and source["id"] == target["id"]:
        source = None
    if source is not None and source.get("status") == "OCCUPIED":
        schedule_bed_release(source, now)
    if target is not None and level_rank(change.get("to_level")) >= 2:
        if target.get("status") == "AVAILABLE":
            schedule_bed_occupancy(target, now)
    change["_source_bed_id"] = source["id"] if source is not None else None

    if episode is not None:
        snapshot = recompute_episode_revenue(episode)
        episode["assigned_level"] = change.get("to_level")
        episode["care_level_status"] = "STEPPED_DOWN"
        # PRD §3.6 states the increment on the second completion branch — the genuine
        # step-down onto a bed, which reaches COMPLETED directly from PLANNED. The
        # first branch passes through PENDING_DISCHARGE_ORDER and carries only the
        # care-level move; the allocation branch is the one that banks the count.
        if change.get("status") == "COMPLETED":
            episode["step_down_count"] = int(episode.get("step_down_count") or 0) + 1
        episode["revcap_pre_step_down_cents"] = snapshot
        episode["revcap_post_step_down_cents"] = snapshot
        episode["updated_at"] = iso(now)
    return change


def _reprice_for_level(episode, now):
    recompute_episode_revenue(episode)


def recompute_episode_revenue(episode):
    total = 0
    for row in session_rows(episode):
        if row.get("status") == "ATTENDED":
            total += int(row.get("billing_amount_cents") or 0)
    episode["therapy_revenue_cents"] = total
    episode["_revcap_current_cents"] = total
    return total


# ---------------------------------------------------------------------------
# Facility ops batch
# ---------------------------------------------------------------------------

def run_ops(facility, now):
    facility["ops_epoch"] = int(facility.get("ops_epoch") or 0) + 1
    # PRD §3.5: the run "advances the facility's ops_epoch by exactly 1 at the very
    # start ... and stamps last_ops_run_at with the logical now". Both are stamped
    # before any stage reads them, so the epoch every stage observes is the same.
    # Stage one's burn span nevertheless opens at the *previous* run's instant, so
    # the outgoing anchor is captured here and threaded into the burn.
    previous_ops_anchor = facility.get("last_ops_run_at")
    facility["last_ops_run_at"] = iso(now)

    # Stage 1 - burn the clock bucket and re-derive authorizations.
    for authorization in STORE.where("LevelOfCareAuthorization", lambda r: r.get("_facility_id") == facility["id"]):
        if authorization.get("posture") not in calc.NON_TERMINAL_POSTURES:
            continue
        _burn_authorization(facility, authorization, now, previous_ops_anchor)

    # Stage 2 - recompute compliance risk and posture. Runs BEFORE stage 3 so a
    # row that has silently lapsed but is still GRANTED is counted at the
    # expired rate; the following run then sees it as a missing class.
    facility_svc.recompute(facility, now)

    # Stage 3a - expire accreditations whose validity has closed.
    facility_svc.expire_due_accreditations(facility, now)

    # Stage 3b - release cleaned beds whose window has arrived.
    for bed in STORE.where("Bed", lambda r: r.get("_facility_id") == facility["id"]):
        if bed.get("status") != "CLEANING":
            continue
        next_at = bed.get("next_available_at")
        if next_at is None:
            continue
        if parse_iso(next_at, "next_available_at") <= now:
            bed["status"] = "AVAILABLE"
            bed["next_available_at"] = None
            bed["version"] = bed.get("version", 1) + 1
            bed["updated_at"] = iso(now)

    # Stage 4 - freeze plans and void the unattended schedule when the
    # facility's posture has landed at FROZEN. The compensating leg of the
    # attendance ledger: rows are rewritten, never deleted.
    if facility.get("facility_posture") == "FROZEN":
        for episode in STORE.where("TreatmentEpisode", lambda r: r.get("_facility_id") == facility["id"]):
            if episode.get("clinical_status") != "IN_TREATMENT":
                continue
            for plan in STORE.where(
                "TreatmentPlan",
                lambda r: r.get("_episode_id") == episode["id"] and r.get("status") == "ACTIVE",
            ):
                plan["status"] = "PENDING_COSIGN"
                plan["version"] = plan.get("version", 1) + 1
                plan["updated_at"] = iso(now)
            # The compensating leg of the attendance ledger: the forward rewrite
            # cancels the unattended rows and a replacement is scheduled for each, so
            # the row count and therapy_revenue_cents both land where they started.
            _void_scheduled_sessions(episode, now)

    # Stage 5 - promote step-down pressure.
    for authorization in STORE.where("LevelOfCareAuthorization", lambda r: r.get("_facility_id") == facility["id"]):
        if authorization.get("posture") != "CONCURRENT_REVIEW_DUE":
            continue
        episode = STORE.get("TreatmentEpisode", authorization.get("_episode_id"))
        if episode is None or episode.get("clinical_status") != "IN_TREATMENT":
            continue
        payer = STORE.get("Payer", authorization.get("payer_id"))
        interval = int((payer or {}).get("concurrent_review_interval_days") or 0)
        if int(authorization.get("days_remaining") or 0) > interval:
            continue
        plan = engine_plan_status(episode)
        if plan != "PENDING_COSIGN":
            continue
        authorization["posture"] = "STEP_DOWN_REQUIRED"
        authorization["version"] = authorization.get("version", 1) + 1
        authorization["updated_at"] = iso(now)
        if episode.get("care_level_status") == "ACTIVE":
            episode["care_level_status"] = "STEP_DOWN_PENDING"
            episode["version"] = episode.get("version", 1) + 1
            episode["updated_at"] = iso(now)

    # Stage five, second clause: "for every episode whose care_level_status is
    # STEP_DOWN_PENDING and whose current bed is OCCUPIED, that bed is released
    # into CLEANING, which decrements the facility's committed bed nights." This
    # runs after the promotion clause above, so an episode promoted in this same
    # run is released in this same run.
    for episode in STORE.where("TreatmentEpisode", lambda r: r.get("_facility_id") == facility["id"]):
        if episode.get("care_level_status") != "STEP_DOWN_PENDING":
            continue
        bed = episode_bed(episode)
        if bed is not None and bed.get("status") == "OCCUPIED":
            schedule_bed_release(bed, now)

    # Stage 6 - time out alumni contacts.
    for contact in STORE.where("AlumniContact", lambda r: r.get("_facility_id") == facility["id"]):
        if contact.get("outcome") != "PENDING":
            continue
        scheduled = contact.get("scheduled_for")
        if scheduled and parse_iso(scheduled, "scheduled_for") <= now:
            contact["outcome"] = "NO_CONTACT"
            contact["updated_at"] = iso(now)
            contact["version"] = contact.get("version", 1) + 1

    # Stage 5 - process pending level-of-care changes in (effective_at, created_at).
    pending = sorted(
        [r for r in STORE.where("LevelOfCareChange", lambda x: x.get("_facility_id") == facility["id"])
         if r.get("status") == "AWAITING_DISCHARGE"],
        key=lambda r: (r.get("effective_at") or "", r.get("created_at") or "", r.get("_created_seq") or 0),
    )
    for change in pending:
        retry_at = change.get("retry_available_at")
        if not retry_at or parse_iso(retry_at, "retry_available_at") > now:
            continue
        # PRD §3.7: "at the run where its retry_available_at has arrived it holds its
        # bed in CLEANING for the run instant, and on the following run the bed
        # returns to AVAILABLE and retry_available_at advances by a further 24 hours,
        # so the row keeps cycling without ever completing". PRD §3.5 renders the
        # release leg: "A change sitting at AWAITING_DISCHARGE whose bed is still
        # CLEANING returns that bed to AVAILABLE and advances the change's
        # retry_available_at by 24 hours, leaving the row in AWAITING_DISCHARGE so
        # that the next run may hold the bed again."
        bed = STORE.get("Bed", change.get("bed_id")) if change.get("bed_id") else None
        if bed is not None:
            if bed.get("status") == "CLEANING":
                bed["status"] = "AVAILABLE"
                bed["next_available_at"] = None
            elif bed.get("status") == "OCCUPIED" or bed.get("status") == "AVAILABLE":
                bed["status"] = "CLEANING"
                bed["next_available_at"] = None
            bed["version"] = bed.get("version", 1) + 1
            bed["updated_at"] = iso(now)
        change["retry_available_at"] = iso(now + timedelta(hours=24))
        change["updated_at"] = iso(now)
        change["version"] = change.get("version", 1) + 1

    touch(facility)
    return facility


def engine_plan_status(episode):
    plan = any_treatment_plan(episode)
    return plan.get("status") if plan else None


def _void_scheduled_sessions(episode, now):
    """Rewrite every SCHEDULED session row to CANCELLED and schedule a
    replacement for each, carrying the new plan's version. Rows are never
    deleted, so the attendance ledger's count is conserved."""
    for row in STORE.where(
        "SessionAttendance",
        lambda r: r.get("_episode_id") == episode["id"] and r.get("status") == "SCHEDULED",
    ):
        row["status"] = "CANCELLED"
        row["billing_amount_cents"] = 0
        row["version"] = row.get("version", 1) + 1
        row["updated_at"] = iso(now)

        replacement = base_fields("SessionAttendance")
        replacement.update({
            "episode_id": episode["id"],
            "_episode_id": episode["id"],
            "facility_id": episode["_facility_id"],
            "_facility_id": episode["_facility_id"],
            "service_id": row.get("service_id"),
            "clinician_id": row.get("clinician_id"),
            "scheduled_at": row.get("scheduled_at"),
            "duration_minutes": row.get("duration_minutes"),
            "attended": False,
            "status": "SCHEDULED",
            "billing_amount_cents": 0,
            "replaces_session_id": row["id"],
            "plan_version": None,
            "_created_seq": STORE.next_episode_seq(episode["id"]),
        })
        STORE.put("SessionAttendance", replacement)


def _burn_authorization(facility, authorization, now, previous_ops_anchor=None):
    episode = STORE.get("TreatmentEpisode", authorization.get("_episode_id"))
    if episode is None:
        return
    anchor = previous_ops_anchor
    if anchor is None:
        anchor = episode.get("admitted_at")
    if anchor is None:
        start = now
    else:
        start = parse_iso(anchor, "last_ops_run_at")
    admitted = episode.get("admitted_at")
    if admitted is not None:
        admitted_dt = parse_iso(admitted, "admitted_at")
        if admitted_dt > start:
            start = admitted_dt

    authorized_days = int(authorization.get("authorized_days") or 0)
    elapsed = calc.whole_days_in_intersection(start, now, start, now)
    days_used = min(authorized_days, int(authorization.get("days_used") or 0) + elapsed)
    days_remaining = max(0, authorized_days - days_used)
    authorization["days_used"] = days_used
    authorization["days_remaining"] = days_remaining

    payer = STORE.get("Payer", authorization.get("payer_id"))
    interval = int((payer or {}).get("concurrent_review_interval_days") or 0)

    if days_remaining == 0 and episode.get("clinical_status") == "IN_TREATMENT":
        authorization["posture"] = "EXHAUSTED"
        # PRD §3.6: "the payer's coverage map is forced to promote the next covered
        # lower level, the episode's care_level_status becomes STEP_DOWN_PENDING, and
        # the episode's treatment plan is superseded in the same moment."
        push = calc.next_covered_level(payer, authorization.get("granted_level"), _funded_levels(episode))
        if push is not None:
            authorization["coverage_forced_level"] = push
        if episode.get("care_level_status") == "ACTIVE":
            episode["care_level_status"] = "STEP_DOWN_PENDING"
            episode["version"] = episode.get("version", 1) + 1
            episode["updated_at"] = iso(now)
        for plan in STORE.where(
            "TreatmentPlan",
            lambda r: r.get("_episode_id") == episode["id"] and r.get("status") == "ACTIVE",
        ):
            plan["status"] = "SUPERSEDED"
            plan["version"] = plan.get("version", 1) + 1
            plan["updated_at"] = iso(now)
    elif days_remaining == 0:
        authorization["posture"] = "EXHAUSTED"
    elif days_remaining <= interval:
        authorization["posture"] = "CONCURRENT_REVIEW_DUE"

    _refresh_urgency(authorization, episode)
    authorization["updated_at"] = iso(now)
    authorization["version"] = authorization.get("version", 1) + 1


def _refresh_urgency(authorization, episode):
    plan = withdrawal_plan(episode) if episode is not None else None
    status = plan.get("status") if plan else None
    authorization["urgency_score"] = calc.urgency_variant_a(authorization, status)


def recompute_authorization_urgency(episode):
    for authorization in STORE.where("LevelOfCareAuthorization", lambda r: r.get("_episode_id") == episode["id"]):
        if authorization.get("posture") in ("PENDING", "DENIED", "EXPIRED"):
            continue
        _refresh_urgency(authorization, episode)