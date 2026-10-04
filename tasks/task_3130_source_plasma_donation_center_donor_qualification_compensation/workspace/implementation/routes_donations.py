"""Routes: DonationVisit lifecycle, AdverseReaction, DonationUnit, LookBackCase."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import middleware
import response
import services as svc

bp = Blueprint("donations", __name__)


# ---------------------------------------------------------------------------
# DonationVisit scheduling
# ---------------------------------------------------------------------------
@bp.post("/donors/<donor_id>/donation-visits")
def schedule_donation(donor_id):
    middleware.require_roles("Phlebotomist")
    donor = svc.get_donor_or_404(donor_id)
    body = middleware.get_body()
    center_id = body.get("center_id")
    if not isinstance(center_id, str) or center_id == "":
        raise errors.err_invalid_request("center_id must be a non-empty string")
    screening_visit_id = body.get("screening_visit_id")
    if not isinstance(screening_visit_id, str) or screening_visit_id == "":
        raise errors.err_invalid_request("screening_visit_id must be a non-empty string")
    scheduled_for_raw = body.get("scheduled_for")
    sf = db.parse_dt(scheduled_for_raw)
    if sf is None:
        raise errors.err_invalid_request("scheduled_for must be an ISO 8601 datetime")
    with db.lock():
        # Body FK references resolve first (priority 4).
        center = svc.get_center(center_id)
        if center is None:
            raise errors.err_not_found("center_id does not resolve")
        screening = db.DB["screening_visits"].get(screening_visit_id)
        if screening is None:
            raise errors.err_not_found("screening_visit_id does not resolve")
        svc.assert_center_operational(center)
        if donor["donor_status"] not in ("APPLICANT", "QUALIFIED"):
            raise errors.err_donor_not_eligible()
        if (
            screening["donor_id"] != donor["id"]
            or screening["visit_status"] != "CLEARED"
            or svc.screening_consumed(screening["id"])
        ):
            raise errors.err_screening_not_cleared()
        if screening["center_id"] != center_id:
            raise errors.err_screening_center_mismatch()
        visit = {
            "id": db.next_id(),
            "donor_id": donor["id"],
            "center_id": center_id,
            "screening_visit_id": screening_visit_id,
            "scheduled_for": db.ts(sf),
            "_scheduled_for_dt": sf,
            "bed_index": None,
            "observation_chair_index": None,
            "programmed_volume_ml": None,
            "actual_volume_ml": None,
            "visit_status": "SCHEDULED",
            "compensation_payment_id": None,
            "_checkin_dt": None,
            "_collected_at_dt": None,
            "_observation_entered_dt": None,
        }
        db.stamp_new(visit)
        db.DB["donation_visits"][visit["id"]] = visit
    return response.success_object(svc.donation_visit_view(visit), status=201)


@bp.get("/donors/<donor_id>/donation-visits")
def list_donations(donor_id):
    middleware.require_roles(
        "PlatformAdmin", "ComplianceOfficer", "MedicalScreener", "Phlebotomist"
    )
    svc.get_donor_or_404(donor_id)
    limit, offset = response.parse_pagination(request.args)
    visit_status = request.args.get("visit_status")
    items = [v for v in db.DB["donation_visits"].values() if v["donor_id"] == donor_id]
    if visit_status is not None:
        items = [v for v in items if v["visit_status"] == visit_status]
    items.sort(key=lambda v: v["created_at"])
    page, total = response.paginate(items, limit, offset)
    return response.success_list(
        [svc.donation_visit_view(v) for v in page], limit, offset, total
    )


@bp.get("/donation-visits/<visit_id>")
def get_donation(visit_id):
    middleware.require_roles(
        "PlatformAdmin", "ComplianceOfficer", "MedicalScreener", "Phlebotomist"
    )
    visit = svc.get_donation_visit_or_404(visit_id)
    return response.success_object(svc.donation_visit_view(visit))


# ---------------------------------------------------------------------------
# DonationVisit pipeline transitions
# ---------------------------------------------------------------------------
@bp.post("/donation-visits/<visit_id>/check-in")
def check_in(visit_id):
    middleware.require_roles("Phlebotomist")
    visit = svc.get_donation_visit_or_404(visit_id)
    middleware.get_body()
    with db.lock():
        if visit["visit_status"] != "SCHEDULED":
            raise errors.err_visit_not_scheduled()
        center = svc.get_center(visit["center_id"])
        if center is not None:
            svc.assert_center_operational(center)
        donor = svc.get_donor(visit["donor_id"])
        if donor is None or donor["donor_status"] not in ("APPLICANT", "QUALIFIED"):
            raise errors.err_donor_not_eligible()
        if svc.active_deferral_for(donor["id"]) is not None:
            raise errors.err_donor_deferred()

        now = db.now()
        # Rolling frequency cap (SCAFFOLD 1.3 rolling_frequency_check).
        window_start = now - timedelta(days=svc.ROLLING_FREQUENCY_DAYS)
        recent = [
            v for v in svc.completed_visits_for_donor(donor["id"])
            if v.get("_collected_at_dt") is not None
            and window_start <= v["_collected_at_dt"] < now
        ]
        if len(recent) >= svc.FREQUENCY_MAX_PER_WINDOW:
            raise errors.err_frequency_limit()
        # Minimum inter-donation gap (SCAFFOLD 1.3 inter_donation_gap_check).
        completed = [
            v for v in svc.completed_visits_for_donor(donor["id"])
            if v.get("_collected_at_dt") is not None
        ]
        if completed:
            latest_collected = max(v["_collected_at_dt"] for v in completed)
            candidates = [
                v for v in completed if v["_collected_at_dt"] == latest_collected
            ]
            candidates.sort(key=lambda v: (v["created_at"], v["id"]))
            last = candidates[0]
            if now - last["_collected_at_dt"] < timedelta(
                hours=svc.MIN_INTER_DONATION_HOURS
            ):
                raise errors.err_inter_donation_gap()
        # Screening integrity.
        screening = db.DB["screening_visits"].get(visit["screening_visit_id"])
        if (
            screening is None
            or screening["visit_status"] != "CLEARED"
            or svc.screening_consumed(screening["id"], exclude_visit_id=visit["id"])
        ):
            raise errors.err_screening_not_cleared()
        # Bed capacity.
        if center is None:
            raise errors.err_not_found("center not found")
        bed = svc.assign_bed(center)
        if bed is None:
            raise errors.err_no_bed_available()
        # Active compensation schedule covering the check-in instant.
        schedule = svc.active_schedule_for(center["id"], now)
        if schedule is None:
            raise errors.err_no_active_comp_schedule()

        # Side effects.
        visit["visit_status"] = "IN_PROGRESS"
        visit["bed_index"] = bed
        visit["_checkin_dt"] = now
        exam = svc.sub_record_of_type(screening["id"], "PHYSICAL_EXAM")
        if exam is not None and isinstance(exam["payload"], dict):
            weight = exam["payload"].get("weight_kg")
            if isinstance(weight, (int, float)) and not isinstance(weight, bool):
                donor["weight_kg"] = weight
                db.touch(donor)
        visit["programmed_volume_ml"] = svc.plasma_volume_ml(donor["weight_kg"])

        payment = {
            "id": db.next_id(),
            "donation_visit_id": visit["id"],
            "donor_id": donor["id"],
            "center_id": center["id"],
            "schedule_id": schedule["id"],
            "base_cents": 0,
            "promo_cents": 0,
            "net_cents": 0,
            "payment_status": "PROVISIONAL",
            "variant": "PROVISIONAL",
            "variant_switched_at": None,
            "payment_issued_on": None,
            "_payment_issued_on_dt": None,
        }
        db.stamp_new(payment)
        db.DB["compensation_payments"][payment["id"]] = payment
        visit["compensation_payment_id"] = payment["id"]
        db.touch(visit)
        svc.recompute_payment(payment, visit, "PROVISIONAL")

        svc.write_snapshot(center["id"], "donation.check_in")
    return response.success_object(svc.donation_visit_view(visit))


@bp.post("/donation-visits/<visit_id>/complete-collection")
def complete_collection(visit_id):
    middleware.require_roles("Phlebotomist")
    visit = svc.get_donation_visit_or_404(visit_id)
    body = middleware.get_body()
    actual = body.get("actual_volume_ml")
    with db.lock():
        if visit["visit_status"] != "IN_PROGRESS":
            raise errors.err_visit_not_in_progress()
        center = svc.get_center(visit["center_id"])
        if center is not None:
            svc.assert_center_operational(center)
        chair = svc.assign_chair(center) if center is not None else None
        if chair is None:
            raise errors.err_no_observation_chair()
        if (
            not isinstance(actual, int)
            or isinstance(actual, bool)
            or actual <= 0
            or actual > visit["programmed_volume_ml"]
        ):
            raise errors.err_invalid_actual_volume()
        visit["visit_status"] = "OBSERVATION"
        visit["bed_index"] = None
        visit["observation_chair_index"] = chair
        visit["actual_volume_ml"] = actual
        visit["_observation_entered_dt"] = db.now()
        db.touch(visit)
        svc.write_snapshot(visit["center_id"], "donation.collection_complete")
    return response.success_object(svc.donation_visit_view(visit))


@bp.post("/donation-visits/<visit_id>/discharge")
def discharge(visit_id):
    middleware.require_roles("Phlebotomist")
    visit = svc.get_donation_visit_or_404(visit_id)
    middleware.get_body()
    with db.lock():
        if visit["visit_status"] != "OBSERVATION":
            raise errors.err_visit_not_observable()
        center = svc.get_center(visit["center_id"])
        if center is not None:
            svc.assert_center_operational(center)
        now = db.now()
        if now < visit["_observation_entered_dt"] + timedelta(
            minutes=svc.OBSERVATION_MINUTES
        ):
            raise errors.err_observation_too_early()

        donor = svc.get_donor(visit["donor_id"])
        visit["visit_status"] = "COMPLETED"
        visit["observation_chair_index"] = None
        visit["_collected_at_dt"] = now
        db.touch(visit)

        svc.create_unit(visit, donor, now)

        first_completion = donor["lifetime_donation_count"] == 0
        donor["lifetime_donation_count"] += 1
        if first_completion:
            donor["applicant_window_started_on"] = db.ts(now)
        db.touch(donor)

        promoted = False
        window_lapsed = False
        if donor["donor_status"] == "APPLICANT" and donor["lifetime_donation_count"] >= 2:
            anchor = db.parse_dt(donor["applicant_window_started_on"])
            if anchor is not None:
                delta = now - anchor
                if delta <= timedelta(days=svc.APPLICANT_WINDOW_DAYS):
                    svc.promote_donor_to_qualified(donor)
                    promoted = True
                else:
                    window_lapsed = True
        if (
            not promoted
            and donor["donor_status"] == "APPLICANT"
            and donor["applicant_window_started_on"] is not None
            and (
                window_lapsed
                or now - db.parse_dt(donor["applicant_window_started_on"])
                > timedelta(days=svc.APPLICANT_WINDOW_DAYS)
            )
        ):
            donor["applicant_window_started_on"] = db.ts(now)
            db.touch(donor)

        payment = db.DB["compensation_payments"].get(visit["compensation_payment_id"])
        if payment is not None:
            payment["variant"] = "FINAL"
            payment["variant_switched_at"] = db.ts(now)
            svc.recompute_payment(payment, visit, "FINAL")
            payment["payment_status"] = "FINALIZED"
            payment["payment_issued_on"] = db.ts(now)
            payment["_payment_issued_on_dt"] = now
            db.touch(payment)
            svc.recompute_ytd(donor["id"])

        svc.write_snapshot(visit["center_id"], "donation.completed")
    return response.success_object(svc.donation_visit_view(visit))


@bp.post("/donation-visits/<visit_id>/adverse-reactions")
def record_adverse_reaction(visit_id):
    middleware.require_roles("Phlebotomist")
    visit = svc.get_donation_visit_or_404(visit_id)
    body = middleware.get_body()
    severity = body.get("severity")
    if severity not in ("MILD", "MODERATE", "SEVERE"):
        raise errors.err_invalid_request("severity must be MILD, MODERATE, or SEVERE")
    reaction_code = body.get("reaction_code")
    if not isinstance(reaction_code, str) or reaction_code == "":
        raise errors.err_invalid_request("reaction_code must be a non-empty string")
    observed_at_raw = body.get("observed_at")
    observed_at = db.parse_dt(observed_at_raw)
    if observed_at is None:
        raise errors.err_invalid_request("observed_at must be an ISO 8601 datetime")
    notes = body.get("notes")
    if not isinstance(notes, str) or len(notes) < 10:
        raise errors.err_invalid_request("notes must be at least 10 characters")
    with db.lock():
        if visit["visit_status"] not in ("IN_PROGRESS", "OBSERVATION"):
            raise errors.err_visit_not_abortable()
        center = svc.get_center(visit["center_id"])
        if center is not None:
            svc.assert_center_operational(center)
        now = db.now()
        if observed_at > now:
            raise errors.err_invalid_request("observed_at must not be later than now")

        from_observation = visit["visit_status"] == "OBSERVATION"
        reaction = {
            "id": db.next_id(),
            "donation_visit_id": visit["id"],
            "severity": severity,
            "reaction_code": reaction_code,
            "observed_at": db.ts(observed_at),
            "notes": notes,
        }
        db.stamp_new(reaction)
        db.DB["adverse_reactions"][reaction["id"]] = reaction

        visit["visit_status"] = "ABORTED_REACTION"
        visit["bed_index"] = None
        visit["observation_chair_index"] = None
        db.touch(visit)

        donor = svc.get_donor(visit["donor_id"])
        if from_observation and visit["actual_volume_ml"] is not None and visit["actual_volume_ml"] > 0:
            svc.create_unit(visit, donor, now)

        payment = db.DB["compensation_payments"].get(visit["compensation_payment_id"])
        if payment is not None:
            schedule = db.DB["compensation_schedules"].get(payment["schedule_id"])
            checkin_dt = visit.get("_checkin_dt") or now
            abort_cents = svc.compute_abort_cents(
                donor["id"], schedule, visit, checkin_dt
            )
            payment["base_cents"] = abort_cents
            payment["promo_cents"] = 0
            payment["net_cents"] = abort_cents
            payment["variant"] = "FINAL"
            payment["variant_switched_at"] = db.ts(now)
            payment["payment_status"] = "FINALIZED"
            payment["payment_issued_on"] = db.ts(now)
            payment["_payment_issued_on_dt"] = now
            db.touch(payment)
            svc.recompute_ytd(donor["id"])

        if severity == "SEVERE":
            svc.auto_file_severe_deferral(donor, visit["center_id"], now)

        svc.write_snapshot(visit["center_id"], "donation.aborted_reaction")
    return response.success_object(svc.adverse_reaction_view(reaction), status=201)


@bp.get("/donation-visits/<visit_id>/adverse-reactions")
def list_adverse_reactions(visit_id):
    middleware.require_roles("PlatformAdmin", "ComplianceOfficer", "MedicalScreener")
    svc.get_donation_visit_or_404(visit_id)
    limit, offset = response.parse_pagination(request.args)
    items = [
        r for r in db.DB["adverse_reactions"].values()
        if r["donation_visit_id"] == visit_id
    ]
    items.sort(key=lambda r: r["created_at"])
    page, total = response.paginate(items, limit, offset)
    return response.success_list(
        [svc.adverse_reaction_view(r) for r in page], limit, offset, total
    )


@bp.get("/donation-visits/<visit_id>/compensation-payment")
def get_visit_payment(visit_id):
    middleware.require_roles("PlatformAdmin", "ComplianceOfficer", "Phlebotomist")
    visit = svc.get_donation_visit_or_404(visit_id)
    pid = visit.get("compensation_payment_id")
    payment = db.DB["compensation_payments"].get(pid) if pid else None
    items = [payment] if payment is not None else []
    return response.success_list(
        [svc.payment_view(p) for p in items], len(items) if items else 10, 0, len(items)
    )


# ---------------------------------------------------------------------------
# DonationUnit
# ---------------------------------------------------------------------------
@bp.get("/donation-units")
def list_units():
    middleware.require_roles("PlatformAdmin", "ComplianceOfficer", "MedicalScreener")
    limit, offset = response.parse_pagination(request.args)
    donor_id = request.args.get("donor_id")
    center_id = request.args.get("center_id")
    unit_status = request.args.get("unit_status")
    items = list(db.DB["donation_units"].values())
    if donor_id is not None:
        items = [u for u in items if u["donor_id"] == donor_id]
    if center_id is not None:
        items = [u for u in items if u["center_id"] == center_id]
    if unit_status is not None:
        items = [u for u in items if u["unit_status"] == unit_status]
    items.sort(key=lambda u: u["created_at"])
    page, total = response.paginate(items, limit, offset)
    return response.success_list([svc.unit_view(u) for u in page], limit, offset, total)


@bp.get("/donation-units/<unit_id>")
def get_unit(unit_id):
    middleware.require_roles("PlatformAdmin", "ComplianceOfficer", "MedicalScreener")
    unit = svc.get_unit_or_404(unit_id)
    return response.success_object(svc.unit_view(unit))


@bp.post("/donation-units/<unit_id>/release")
def release_unit(unit_id):
    middleware.require_roles("ComplianceOfficer")
    unit = svc.get_unit_or_404(unit_id)
    middleware.get_body()
    with db.lock():
        if unit["unit_status"] != "QUARANTINED":
            raise errors.err_unit_not_quarantined()
        center = svc.get_center(unit["center_id"])
        if center is not None:
            svc.assert_center_operational(center)
        donor = svc.get_donor(unit["donor_id"])
        if donor is None or donor["donor_status"] != "QUALIFIED":
            raise errors.err_donor_not_qualified()
        if svc.open_lookback_case_for(unit["donor_id"]) is not None:
            raise errors.err_lookback_open()
        unit["unit_status"] = "RELEASED"
        unit["released_at"] = db.ts()
        db.touch(unit)
        svc.write_snapshot(unit["center_id"], "unit.released")
    return response.success_object(svc.unit_view(unit))


# ---------------------------------------------------------------------------
# LookBackCase
# ---------------------------------------------------------------------------
@bp.get("/lookback-cases")
def list_lookback_cases():
    middleware.require_roles("PlatformAdmin", "ComplianceOfficer")
    limit, offset = response.parse_pagination(request.args)
    donor_id = request.args.get("donor_id")
    case_status = request.args.get("case_status")
    items = list(db.DB["lookback_cases"].values())
    if donor_id is not None:
        items = [c for c in items if c["donor_id"] == donor_id]
    if case_status is not None:
        items = [c for c in items if c["case_status"] == case_status]
    items.sort(key=lambda c: c["created_at"])
    page, total = response.paginate(items, limit, offset)
    return response.success_list(
        [svc.lookback_case_view(c) for c in page], limit, offset, total
    )


@bp.get("/lookback-cases/<case_id>")
def get_lookback_case(case_id):
    middleware.require_roles("PlatformAdmin", "ComplianceOfficer")
    case = svc.get_lookback_case_or_404(case_id)
    return response.success_object(svc.lookback_case_view(case))


@bp.post("/lookback-cases/<case_id>/resolve")
def resolve_lookback_case(case_id):
    middleware.require_roles("ComplianceOfficer")
    case = svc.get_lookback_case_or_404(case_id)
    body = middleware.get_body()
    resolution = body.get("resolution")
    if resolution not in ("DESTROY", "RELEASE"):
        raise errors.err_invalid_request("resolution must be DESTROY or RELEASE")
    rationale = body.get("resolution_rationale")
    if not isinstance(rationale, str) or len(rationale) < 20:
        raise errors.err_invalid_request(
            "resolution_rationale must be at least 20 characters"
        )
    with db.lock():
        if case["case_status"] != "UNITS_QUARANTINED":
            raise errors.err_lookback_not_ready()
        held = [
            u for u in db.DB["donation_units"].values()
            if u.get("lookback_case_id") == case["id"]
            and u["unit_status"] == "LOOKBACK_HOLD"
        ]
        now = db.now()
        if resolution == "DESTROY":
            svc.destroy_units_and_clawback(held, "REACTIVE_LOOKBACK")
            case["case_status"] = "RESOLVED_DESTROYED"
        else:
            donor = svc.get_donor(case["donor_id"])
            if donor is None or donor["donor_status"] != "QUALIFIED":
                raise errors.err_donor_not_qualified()
            for u in held:
                u["unit_status"] = "RELEASED"
                u["released_at"] = db.ts(now)
                db.touch(u)
            case["case_status"] = "RESOLVED_RELEASED"
        case["resolved_at"] = db.ts(now)
        db.touch(case)
    return response.success_object(svc.lookback_case_view(case))
