"""Shared lookups, counter recomputes, compliance gates, and cascades."""
from datetime import timedelta

import store
from calc import SITE_VISIT_MIN_GAP_DAYS, pipeline_credit
from clock import now_dt
from errors import raise_err
from util import touch

COUNTED_PARTICIPANT_STATUSES = ("CONSENTED", "RANDOMIZED_TREATMENT",
                                "RANDOMIZED_CONTROL")
SITE_TERMINAL = ("DECLINED", "WITHDRAWN", "COMPLETED")
STUDY_TERMINAL = ("COMPLETED", "TERMINATED")


def studies_of_contract(contract_id):
    return [s for s in store.studies.values() if s["contract_id"] == contract_id]


def plans_of_study(study_id):
    return [p for p in store.design_plans.values() if p["study_id"] == study_id]


def current_plan(study_id):
    """Latest-created non-SUPERSEDED design plan of the study, or None."""
    candidates = [p for p in plans_of_study(study_id)
                  if p["status"] != "SUPERSEDED"]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p["_seq"])


def protocols_of_study(study_id):
    return [p for p in store.irb_protocols.values()
            if p["study_id"] == study_id]


def sites_of_study(study_id):
    return [s for s in store.sites.values() if s["study_id"] == study_id]


def waves_of_study(study_id):
    return [w for w in store.waves.values() if w["study_id"] == study_id]


def participants_of_site(site_id):
    return [p for p in store.participants.values() if p["site_id"] == site_id]


def records_of_wave(wave_id):
    return [r for r in store.records.values() if r["wave_id"] == wave_id]


def records_of_participant(participant_id):
    return [r for r in store.records.values()
            if r["participant_id"] == participant_id]


def analysis_plans_of_study(study_id):
    return [a for a in store.analysis_plans.values()
            if a["study_id"] == study_id]


def latest_preregistered_plan(study_id):
    regs = [a for a in analysis_plans_of_study(study_id)
            if a["status"] == "PREREGISTERED"]
    if not regs:
        return None
    return max(regs, key=lambda a: a["_seq"])


def reports_of_study(study_id):
    return [r for r in store.reports.values() if r["study_id"] == study_id]


def study_has_published_report(study_id):
    return any(r["status"] == "PUBLISHED" for r in reports_of_study(study_id))


def activities_of_study(study_id):
    return [a for a in store.dissemination_activities.values()
            if a["study_id"] == study_id]


def recompute_projections(study):
    committed = 0
    pipeline = 0
    for s in sites_of_study(study["id"]):
        if s["status"] in ("RECRUITED", "ACTIVE"):
            committed += s["max_participants"]
            pipeline += s["max_participants"]
        else:
            pipeline += pipeline_credit(s["max_participants"], s["status"])
    plan = current_plan(study["id"])
    if plan is None:
        adequacy = "UNASSESSED"
    elif pipeline >= plan["required_total_n"]:
        adequacy = "ADEQUATE"
    else:
        adequacy = "UNDERPOWERED"
    if (study["committed_projected_n"] != committed
            or study["pipeline_projected_n"] != pipeline
            or study["sample_adequacy"] != adequacy):
        study["committed_projected_n"] = committed
        study["pipeline_projected_n"] = pipeline
        study["sample_adequacy"] = adequacy
        touch(study)


def recompute_enrollment(study):
    total = 0
    for s in sites_of_study(study["id"]):
        cnt = sum(1 for p in participants_of_site(s["id"])
                  if p["status"] in COUNTED_PARTICIPANT_STATUSES)
        if s["enrolled_count"] != cnt:
            s["enrolled_count"] = cnt
            touch(s)
        total += cnt
    if study["enrolled_total"] != total:
        study["enrolled_total"] = total
        touch(study)


def recompute_quarantine(study):
    wave_ids = {w["id"] for w in waves_of_study(study["id"])}
    cnt = sum(1 for r in store.records.values()
              if r["wave_id"] in wave_ids and r["status"] == "QUARANTINED")
    if study["quarantined_record_count"] != cnt:
        study["quarantined_record_count"] = cnt
        touch(study)


def recompute_burden(participant):
    total = sum(r["billed_minutes"]
                for r in records_of_participant(participant["id"])
                if r["status"] in ("RECEIVED", "VALIDATED", "LINKED"))
    if participant["burden_total_minutes"] != total:
        participant["burden_total_minutes"] = total
        touch(participant)


def irb_covering_protocol(study_id):
    """The APPROVED protocol whose half-open window covers now, or None."""
    now = now_dt()
    for p in protocols_of_study(study_id):
        if (p["status"] == "APPROVED" and p["approval_start"] is not None
                and p["approval_start"] <= now < p["approval_end"]):
            return p
    return None


def irb_ever_approved(study_id):
    return any(p["status"] in ("APPROVED", "EXPIRED")
               for p in protocols_of_study(study_id))


def require_irb_coverage(study_id):
    covering = irb_covering_protocol(study_id)
    if covering is not None:
        return covering
    if irb_ever_approved(study_id):
        raise_err("ERR_IRB_EXPIRED",
                  "Every approved IRB window of the study has passed")
    raise_err("ERR_NO_APPROVED_IRB",
              "No IRB protocol of the study has been approved")


def quarantine_records_of_participant(participant):
    for r in records_of_participant(participant["id"]):
        if r["status"] in ("RECEIVED", "VALIDATED"):
            r["status"] = "QUARANTINED"
            touch(r)
    recompute_burden(participant)


def withdraw_participant(participant, reason):
    participant["status"] = "WITHDRAWN"
    participant["withdrawal_reason"] = reason
    touch(participant)
    quarantine_records_of_participant(participant)


def withdraw_site_cascade(site, study):
    for p in participants_of_site(site["id"]):
        if p["status"] not in ("COMPLETED", "WITHDRAWN"):
            withdraw_participant(p, "SITE_WITHDRAWN")
    recompute_enrollment(study)
    recompute_quarantine(study)
    recompute_projections(study)


def terminate_study_cascade(study):
    study["status"] = "TERMINATED"
    touch(study)
    for site in sites_of_study(study["id"]):
        if site["status"] in SITE_TERMINAL:
            continue
        site["status"] = "WITHDRAWN"
        touch(site)
        for p in participants_of_site(site["id"]):
            if p["status"] not in ("COMPLETED", "WITHDRAWN"):
                withdraw_participant(p, "CONTRACT_TERMINATED")
    for w in waves_of_study(study["id"]):
        if w["status"] in ("PLANNED", "OPEN", "SUSPENDED"):
            w["status"] = "CANCELLED"
            touch(w)
    for r in reports_of_study(study["id"]):
        if r["status"] in ("DRAFT", "SUBMITTED", "PEER_REVIEWED", "REVISION"):
            r["status"] = "CANCELLED"
            touch(r)
    for a in activities_of_study(study["id"]):
        if a["status"] == "PLANNED":
            a["status"] = "CANCELLED"
            touch(a)
    recompute_enrollment(study)
    recompute_quarantine(study)
    recompute_projections(study)


def maybe_lock_plan(study, plan=None):
    """Lock the AGENCY_APPROVED plan once a site is RECRUITED/ACTIVE.

    PRD §3.2: an APPROVED decision continues "the plan" (the decided plan)
    immediately to LOCKED when a site is already RECRUITED/ACTIVE — so the
    agency-decision endpoint passes the decided plan explicitly. At other
    trigger sites (site MOU signing) the target is the study's plan that is
    in AGENCY_APPROVED status, not merely the latest-created live plan.
    """
    if plan is None:
        approved = [p for p in plans_of_study(study["id"])
                    if p["status"] == "AGENCY_APPROVED"]
        if not approved:
            return
        plan = max(approved, key=lambda p: p["_seq"])
    if plan["status"] != "AGENCY_APPROVED":
        return
    if any(s["status"] in ("RECRUITED", "ACTIVE")
           for s in sites_of_study(study["id"])):
        plan["status"] = "LOCKED"
        touch(plan)
        if study["status"] == "DESIGN":
            study["status"] = "RECRUITMENT"
            touch(study)


def maybe_complete_study(study):
    """DISSEMINATION -> COMPLETED the moment both exit conditions hold."""
    if study["status"] != "DISSEMINATION":
        return
    contract = store.contracts.get(study["contract_id"])
    finals = sum(1 for r in reports_of_study(study["id"])
                 if r["status"] == "PUBLISHED" and r["report_type"] == "FINAL")
    has_completed_activity = any(a["status"] == "COMPLETED"
                                 for a in activities_of_study(study["id"]))
    if finals >= contract["deliverable_report_count"] and has_completed_activity:
        study["status"] = "COMPLETED"
        touch(study)
        for site in sites_of_study(study["id"]):
            if site["status"] == "ACTIVE":
                site["status"] = "COMPLETED"
                touch(site)
                for p in participants_of_site(site["id"]):
                    if p["status"] in COUNTED_PARTICIPANT_STATUSES:
                        p["status"] = "COMPLETED"
                        touch(p)
        recompute_enrollment(study)
        recompute_projections(study)


def evaluate_irb_expiry():
    """Expire APPROVED protocols whose window ended; fire suspension cascade."""
    now = now_dt()
    for proto in list(store.irb_protocols.values()):
        if (proto["status"] == "APPROVED"
                and proto["approval_end"] is not None
                and now >= proto["approval_end"]):
            proto["status"] = "EXPIRED"
            touch(proto)
            study = store.studies.get(proto["study_id"])
            if study is None:
                continue
            for w in waves_of_study(study["id"]):
                if w["status"] == "OPEN":
                    w["status"] = "SUSPENDED"
                    touch(w)
                    for r in records_of_wave(w["id"]):
                        if r["status"] in ("RECEIVED", "VALIDATED"):
                            r["status"] = "QUARANTINED"
                            touch(r)
                            participant = store.participants.get(
                                r["participant_id"])
                            if participant is not None:
                                recompute_burden(participant)
            recompute_quarantine(study)


def visit_window_conflict(study_id, site_id, open_dt, close_dt):
    """Overlap or < SITE_VISIT_MIN_GAP_DAYS gap vs other non-CANCELLED visits."""
    min_gap = timedelta(days=SITE_VISIT_MIN_GAP_DAYS)
    for w in waves_of_study(study_id):
        if (w["wave_type"] != "SITE_VISIT" or w["site_id"] != site_id
                or w["status"] == "CANCELLED"):
            continue
        ws, we = w["open_at"], w["close_at"]
        if open_dt < we and ws < close_dt:
            return True
        if close_dt <= ws and (ws - close_dt) < min_gap:
            return True
        if we <= open_dt and (open_dt - we) < min_gap:
            return True
    return False
