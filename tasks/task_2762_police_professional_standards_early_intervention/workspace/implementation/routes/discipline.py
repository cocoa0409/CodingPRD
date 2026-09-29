"""Adjudication, discipline, appeals and reinstatement."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import svc
from core import (
    ApiError,
    add_days,
    body,
    db,
    dump,
    endpoint,
    f_dt,
    f_enum,
    f_int,
    f_str,
    floor_days,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("discipline", __name__)


def _segregation_conflict(allegation):
    if g.user_id == allegation["subject_officer_id"]:
        return True
    investigation = svc.investigation_of(allegation["complaint_id"])
    if investigation is not None:
        if g.user_id == investigation.get("assigned_investigator_officer_id"):
            return True
    return False


# ---------------------------------------------------------------------------
# Adjudication
# ---------------------------------------------------------------------------
@bp.post("/allegations/<allegation_id>/disposition")
@endpoint("IACommander")
def dispose_allegation(allegation_id):
    allegation = svc.need_allegation(allegation_id)
    payload = body()
    # tier 4 -- schema
    disposition = f_enum(payload, "disposition", calc.COMMANDER_DISPOSITIONS)
    aggravator_count = f_int(
        payload, "aggravator_count", required=False, default=0, minimum=0, maximum=5
    )
    mitigator_count = f_int(
        payload, "mitigator_count", required=False, default=0, minimum=0, maximum=5
    )
    f_str(payload, "rationale", required=False)
    complaint = svc.need_complaint(allegation["complaint_id"])
    # tier 8 -- state legality
    if complaint["status"] != "ADJUDICATION":
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")
    if allegation["disposition"] != "PENDING":
        raise ApiError("ERR_ALLEGATION_ALREADY_DISPOSED")
    # tier 9 -- business safety
    if _segregation_conflict(allegation):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # tier 12 -- business constraints
    if disposition == "SUSTAINED":
        if not allegation["preponderance_met"]:
            raise ApiError("ERR_PREPONDERANCE_NOT_MET")
    elif disposition == "UNFOUNDED":
        if calc.D(allegation["evidence_weight_for"]) != 0:
            raise ApiError("ERR_DISPOSITION_NOT_SUPPORTED")
    elif disposition in ("EXONERATED", "POLICY_FAILURE"):
        if allegation["policy_compliant"] is not True:
            raise ApiError("ERR_DISPOSITION_NOT_SUPPORTED")

    allegation["disposition"] = disposition
    allegation["disposed_at"] = db.clock
    priors = calc.prior_sustained_allegations(
        allegation["subject_officer_id"], allegation["id"], allegation["disposed_at"]
    )
    allegation["prior_sustained_count_at_disposition"] = len(priors)
    touch(allegation)

    if disposition != "SUSTAINED":
        return respond_object(dump(allegation))

    officer = db.officers.get(allegation["subject_officer_id"])
    complaint["sustained_allegation_count"] += 1
    touch(complaint)
    tier_index = calc.prior_tier_index(len(priors))
    discipline = new_row(
        "Discipline",
        allegation_id=allegation["id"],
        officer_id=allegation["subject_officer_id"],
        offense_class=allegation["offense_class"],
        aggravator_count=aggravator_count,
        mitigator_count=mitigator_count,
        presumptive_prior_tier=tier_index,
        presumptive_days=calc.matrix_days(
            allegation["offense_class"], tier_index, aggravator_count, mitigator_count
        ),
        final_prior_tier=None,
        final_days=None,
        effective_days=0,
        status="PROPOSED",
        imposed_at=None,
        effective_date=None,
        appeal_deadline_at=None,
    )
    db.disciplines[discipline["id"]] = discipline
    if officer is not None:
        svc.append_activity_event(
            officer["id"],
            "COMPLAINT_SUSTAINED",
            "NA",
            allegation["disposed_at"],
            source_reference=allegation["id"],
            system_generated=True,
        )
        profile = svc.recompute_officer_eis(officer)
        if profile["alert_level"] != "NONE":
            svc.create_alert(officer, profile, "DISPOSITION_CASCADE")
        if allegation["allegation_type"] == "UNTRUTHFULNESS":
            disclosure = new_row(
                "CredibilityDisclosure",
                officer_id=officer["id"],
                source_allegation_id=allegation["id"],
                basis="UNTRUTHFULNESS_SUSTAINED",
                status="ACTIVE",
                retention_until=add_days(db.clock, calc.DISCLOSURE_RETENTION_DAYS),
                permanent_retention=True,
                release_count=0,
                last_released_at=None,
            )
            db.disclosures[disclosure["id"]] = disclosure
            svc.recompute_credibility_flag(officer)
    return respond_object(dump(allegation))


# ---------------------------------------------------------------------------
# Discipline reads
# ---------------------------------------------------------------------------
@bp.get("/disciplines/<discipline_id>")
@endpoint("IACommander", "AppealsOfficer", "OfficerRepresentative", "RecordsCustodian")
def read_discipline(discipline_id):
    return respond_object(dump(svc.need_discipline(discipline_id)))


@bp.get("/disciplines")
@endpoint("IACommander", "AppealsOfficer", "OfficerRepresentative", "RecordsCustodian")
def list_disciplines():
    allegation_id = q_str("allegation_id")
    officer_id = q_str("officer_id")
    status = q_enum("status", calc.DISCIPLINE_STATUSES)
    rows = sort_created(list(db.disciplines.values()))
    if allegation_id is not None:
        rows = [r for r in rows if r["allegation_id"] == allegation_id]
    if officer_id is not None:
        rows = [r for r in rows if r["officer_id"] == officer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows)


# ---------------------------------------------------------------------------
# Imposition
# ---------------------------------------------------------------------------
@bp.post("/disciplines/<discipline_id>/impose")
@endpoint("IACommander")
def impose_discipline(discipline_id):
    discipline = svc.need_discipline(discipline_id)
    payload = body()
    effective_date = f_dt(payload, "effective_date")
    aggravator_count = f_int(
        payload, "aggravator_count", required=False, minimum=0, maximum=5
    )
    mitigator_count = f_int(
        payload, "mitigator_count", required=False, minimum=0, maximum=5
    )
    allegation = svc.need_allegation(discipline["allegation_id"])
    complaint = svc.need_complaint(allegation["complaint_id"])
    officer = db.officers.get(discipline["officer_id"])
    # tier 8 -- state legality
    if discipline["status"] != "PROPOSED":
        raise ApiError("ERR_DISCIPLINE_STATE_INVALID")
    if allegation["disposition"] != "SUSTAINED":
        raise ApiError("ERR_DISCIPLINE_STATE_INVALID")
    if complaint["status"] not in ("ADJUDICATION", "CLOSED"):
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")
    if officer is not None and officer["employment_status"] == "SEPARATED":
        raise ApiError("ERR_OFFICER_SEPARATED")
    # tier 9 -- business safety
    if _segregation_conflict(allegation):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if aggravator_count is None:
        aggravator_count = discipline["aggravator_count"]
    if mitigator_count is None:
        mitigator_count = discipline["mitigator_count"]
    priors = calc.prior_sustained_allegations(
        discipline["officer_id"], allegation["id"], db.clock, imposed_only=True
    )
    final_tier = calc.prior_tier_index(len(priors))
    final_days = calc.matrix_days(
        discipline["offense_class"], final_tier, aggravator_count, mitigator_count
    )
    discipline["aggravator_count"] = aggravator_count
    discipline["mitigator_count"] = mitigator_count
    discipline["final_prior_tier"] = final_tier
    discipline["final_days"] = final_days
    discipline["effective_days"] = final_days
    discipline["effective_date"] = effective_date
    discipline["imposed_at"] = db.clock
    discipline["appeal_deadline_at"] = add_days(db.clock, calc.APPEAL_WINDOW_DAYS)
    discipline["status"] = "IMPOSED"
    touch(discipline)
    if officer is not None:
        officer["imposed_suspension_days_total"] += final_days
        if final_days >= 1 and officer["employment_status"] == "ACTIVE":
            officer["employment_status"] = "SUSPENDED"
            officer["suspension_end_date"] = add_days(effective_date, final_days)
        touch(officer)
    return respond_object(dump(discipline))


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------
@bp.post("/disciplines/<discipline_id>/appeals")
@endpoint("OfficerRepresentative")
def file_appeal(discipline_id):
    discipline = svc.need_discipline(discipline_id)
    payload = body()
    forum = f_enum(payload, "forum", calc.FORUMS)
    grounds = f_str(payload, "grounds")
    # tier 8 -- state legality
    if discipline["status"] != "IMPOSED":
        raise ApiError("ERR_DISCIPLINE_STATE_INVALID")
    # tier 11 -- temporal rules
    deadline = discipline.get("appeal_deadline_at")
    if deadline is None or db.clock > deadline:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")

    appeal = new_row(
        "Appeal",
        discipline_id=discipline["id"],
        forum=forum,
        grounds=grounds,
        filed_at=db.clock,
        days_to_file=floor_days(db.clock, discipline["imposed_at"]),
        status="FILED",
        outcome="PENDING",
        modified_days=None,
        heard_at=None,
        decided_at=None,
        hearing_notes=None,
    )
    db.appeals[appeal["id"]] = appeal
    discipline["status"] = "APPEALED"
    touch(discipline)
    return respond_object(dump(appeal), 201)


@bp.get("/appeals/<appeal_id>")
@endpoint("IACommander", "AppealsOfficer", "OfficerRepresentative", "RecordsCustodian")
def read_appeal(appeal_id):
    return respond_object(dump(svc.need_appeal(appeal_id)))


@bp.get("/appeals")
@endpoint("IACommander", "AppealsOfficer", "OfficerRepresentative", "RecordsCustodian")
def list_appeals():
    discipline_id = q_str("discipline_id")
    forum = q_enum("forum", calc.FORUMS)
    status = q_enum("status", calc.APPEAL_STATUSES)
    outcome = q_enum("outcome", calc.APPEAL_OUTCOMES)
    rows = sort_created(list(db.appeals.values()))
    if discipline_id is not None:
        rows = [r for r in rows if r["discipline_id"] == discipline_id]
    if forum is not None:
        rows = [r for r in rows if r["forum"] == forum]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    return paginate(rows)


@bp.post("/appeals/<appeal_id>/hear")
@endpoint("AppealsOfficer")
def hear_appeal(appeal_id):
    appeal = svc.need_appeal(appeal_id)
    payload = body()
    hearing_notes = f_str(payload, "hearing_notes", required=False)
    # tier 8 -- state legality
    if appeal["status"] != "FILED":
        raise ApiError("ERR_APPEAL_STATE_INVALID")
    appeal["status"] = "HEARD"
    appeal["heard_at"] = db.clock
    if hearing_notes is not None:
        appeal["hearing_notes"] = hearing_notes
    touch(appeal)
    return respond_object(dump(appeal))


def _create_reinstatement(appeal, reversed_days):
    reinstatement = new_row(
        "Reinstatement",
        appeal_id=appeal["id"],
        reversed_days=reversed_days,
        gross_back_pay_cents=None,
        interim_earnings_cents=0,
        net_back_pay_cents=None,
        interest_cents=None,
        total_award_cents=None,
        status="PENDING",
        effective_date=db.clock,
        finalized_at=None,
    )
    db.reinstatements[reinstatement["id"]] = reinstatement
    return reinstatement


@bp.post("/appeals/<appeal_id>/decide")
@endpoint("AppealsOfficer")
def decide_appeal(appeal_id):
    appeal = svc.need_appeal(appeal_id)
    payload = body()
    outcome = f_enum(payload, "outcome", calc.DECIDE_OUTCOMES)
    modified_days = f_int(payload, "modified_days", required=False)
    discipline = svc.need_discipline(appeal["discipline_id"])
    # tier 8 -- state legality
    if appeal["status"] != "HEARD":
        raise ApiError("ERR_APPEAL_STATE_INVALID")
    final_days = discipline.get("final_days") or 0
    # tier 12 -- business constraints
    if outcome == "MODIFIED":
        if modified_days is None or modified_days < 0 or modified_days >= final_days:
            raise ApiError("ERR_MODIFIED_DAYS_INVALID")

    appeal["status"] = "DECIDED"
    appeal["outcome"] = outcome
    appeal["decided_at"] = db.clock
    if outcome == "MODIFIED":
        appeal["modified_days"] = modified_days
    touch(appeal)
    officer = db.officers.get(discipline["officer_id"])

    if outcome == "UPHELD":
        discipline["status"] = "UPHELD"
        touch(discipline)
        return respond_object(dump(appeal))

    if outcome == "MODIFIED":
        discipline["status"] = "MODIFIED"
        discipline["effective_days"] = modified_days
        touch(discipline)
        if officer is not None:
            officer["imposed_suspension_days_total"] += modified_days - final_days
            touch(officer)
        _create_reinstatement(appeal, final_days - modified_days)
        return respond_object(dump(appeal))

    # OVERTURNED
    discipline["status"] = "OVERTURNED"
    discipline["effective_days"] = 0
    touch(discipline)
    if officer is not None:
        officer["imposed_suspension_days_total"] -= final_days
        if (
            officer["imposed_suspension_days_total"] == 0
            and officer["employment_status"] == "SUSPENDED"
        ):
            officer["employment_status"] = "ACTIVE"
            officer["suspension_end_date"] = None
        touch(officer)
    allegation = db.allegations.get(discipline["allegation_id"])
    if allegation is not None:
        allegation["disposition"] = "OVERTURNED_ON_APPEAL"
        touch(allegation)
        complaint = db.complaints.get(allegation["complaint_id"])
        if complaint is not None:
            complaint["sustained_allegation_count"] = max(
                0, complaint["sustained_allegation_count"] - 1
            )
            touch(complaint)
        for disclosure in svc.disclosures_of_allegation(allegation["id"]):
            if disclosure["status"] == "ACTIVE":
                disclosure["status"] = "EXPUNGED"
                touch(disclosure)
        if officer is not None:
            svc.recompute_credibility_flag(officer)
    _create_reinstatement(appeal, final_days)
    return respond_object(dump(appeal))


# ---------------------------------------------------------------------------
# Reinstatement
# ---------------------------------------------------------------------------
@bp.get("/appeals/<appeal_id>/reinstatements")
@endpoint("AppealsOfficer", "IACommander", "OfficerRepresentative", "RecordsCustodian")
def list_reinstatements(appeal_id):
    svc.need_appeal(appeal_id)
    status = q_enum("status", calc.REINSTATEMENT_STATUSES)
    rows = svc.reinstatements_of(appeal_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows)


@bp.post("/reinstatements/<reinstatement_id>/finalize")
@endpoint("AppealsOfficer")
def finalize_reinstatement(reinstatement_id):
    reinstatement = svc.need_reinstatement(reinstatement_id)
    payload = body()
    interim_earnings_cents = f_int(payload, "interim_earnings_cents")
    appeal = svc.need_appeal(reinstatement["appeal_id"])
    discipline = svc.need_discipline(appeal["discipline_id"])
    officer = db.officers.get(discipline["officer_id"])
    # tier 8 -- state legality
    if reinstatement["status"] != "PENDING":
        raise ApiError("ERR_REINSTATEMENT_ALREADY_FINALIZED")
    # tier 13 -- fiscal constraints
    if interim_earnings_cents < 0:
        raise ApiError("ERR_INVALID_INTERIM_EARNINGS")
    if officer is None or officer["annual_salary_cents"] <= 0:
        raise ApiError("ERR_SALARY_UNKNOWN")

    days_elapsed = floor_days(db.clock, discipline["imposed_at"])
    gross, net, interest, total = calc.back_pay(
        officer["annual_salary_cents"],
        reinstatement["reversed_days"],
        interim_earnings_cents,
        days_elapsed,
    )
    reinstatement["interim_earnings_cents"] = interim_earnings_cents
    reinstatement["gross_back_pay_cents"] = gross
    reinstatement["net_back_pay_cents"] = net
    reinstatement["interest_cents"] = interest
    reinstatement["total_award_cents"] = total
    reinstatement["status"] = "FINALIZED"
    reinstatement["finalized_at"] = db.clock
    touch(reinstatement)
    return respond_object(dump(reinstatement))
