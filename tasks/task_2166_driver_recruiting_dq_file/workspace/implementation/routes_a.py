"""Routes: logical clock, carriers, driver applicants, driver applications."""
from datetime import timedelta

import calc
import domain
from core import (ALL_ROLES, DB, ROLE_RECRUITER, ROLE_SAFETY, actor_id, all_rows,
                  body, created, d, fail, fk, fmt_date, fmt_instant, listing,
                  must_get, new_row, now, ok, opt_enum, opt_int, opt_str,
                  pagination, parse_instant_or_none, qs, req_date, req_enum,
                  req_int, req_str, require_roles, serialize, set_now,
                  today, touch)

SAFETY_RATINGS = ("SATISFACTORY", "CONDITIONAL", "UNSATISFACTORY")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
CDL_CLASSES = ("CLASS_A", "CLASS_B", "CLASS_C")
POSITION_TYPES = ("OTR", "REGIONAL", "LOCAL")

APP_SCREENING_TERMINAL = ("SCREEN_FAILED",)
APP_QUAL_TERMINAL = ("HIRED", "DISQUALIFIED")


def filtered(collection, filters):
    rows = all_rows(collection)
    for key, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return rows


def page(rows):
    limit, offset = pagination()
    return listing([serialize(r) for r in rows], limit, offset)


def register(app):
    # -----------------------------------------------------------------
    # Logical clock
    # -----------------------------------------------------------------
    @app.post("/_clock/set_current_utc")
    def clock_set():
        require_roles(ALL_ROLES)
        payload = body()
        raw = req_str(payload, "to_iso8601")
        parsed = parse_instant_or_none(raw)
        if parsed is None:
            fail("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 instant.")
        set_now(parsed)
        domain.clock_sweep()
        return ok({"current_utc": fmt_instant(now())})

    @app.get("/_clock")
    def clock_get():
        require_roles(ALL_ROLES)
        return ok({"current_utc": fmt_instant(now())})

    # -----------------------------------------------------------------
    # Carrier
    # -----------------------------------------------------------------
    @app.post("/carriers")
    def carrier_create():
        require_roles([ROLE_SAFETY])
        payload = body()
        legal_name = req_str(payload, "legal_name")
        dot_number = req_str(payload, "dot_number")
        if len(dot_number) < 1 or len(dot_number) > 12:
            fail("ERR_VALIDATION", "dot_number must be 1-12 characters.")
        open_requisitions = req_int(payload, "open_requisitions", minimum=0)
        safety_rating = opt_enum(payload, "safety_rating", SAFETY_RATINGS,
                                 "SATISFACTORY")
        mvr_validity_days = opt_int(payload, "mvr_validity_days", minimum=1,
                                    default=365)
        review_interval = opt_int(payload, "annual_review_interval_days",
                                  minimum=1, default=365)
        review_grace = opt_int(payload, "annual_review_grace_days", minimum=0,
                               default=30)
        mvr_threshold = opt_int(payload, "mvr_point_threshold", minimum=1,
                                default=7)
        rehire_cooldown = opt_int(payload, "rehire_cooldown_days", minimum=0,
                                  default=180)
        medical_grace = opt_int(payload, "medical_cert_grace_days", minimum=0,
                                default=15)
        for existing in all_rows("carriers"):
            if existing["dot_number"] == dot_number:
                fail("ERR_DUPLICATE_DOT_NUMBER", "dot_number already registered.")
        carrier = new_row("carriers", {
            "legal_name": legal_name,
            "dot_number": dot_number,
            "safety_rating": safety_rating,
            "open_requisitions": open_requisitions,
            "filled_requisitions": 0,
            "mvr_validity_days": mvr_validity_days,
            "annual_review_interval_days": review_interval,
            "annual_review_grace_days": review_grace,
            "mvr_point_threshold": mvr_threshold,
            "rehire_cooldown_days": rehire_cooldown,
            "medical_cert_grace_days": medical_grace,
            "deficiency_ratio": 0.0,
            "posture": "OPEN",
        })
        for key, value in calc.carrier_posture(carrier).items():
            carrier[key] = value
        return created(serialize(carrier))

    @app.get("/carriers/<carrier_id>")
    def carrier_read(carrier_id):
        require_roles(ALL_ROLES)
        carrier = must_get("carriers", carrier_id)
        for key, value in calc.carrier_posture(carrier).items():
            carrier[key] = value
        return ok(serialize(carrier))

    @app.get("/carriers")
    def carrier_list():
        require_roles(ALL_ROLES)
        limit, offset = pagination()
        rows = all_rows("carriers")
        for carrier in rows:
            for key, value in calc.carrier_posture(carrier).items():
                carrier[key] = value
        posture = qs("posture")
        if posture is not None:
            rows = [r for r in rows if r["posture"] == posture]
        return listing([serialize(r) for r in rows], limit, offset)

    @app.patch("/carriers/<carrier_id>")
    def carrier_patch(carrier_id):
        require_roles([ROLE_SAFETY])
        carrier = must_get("carriers", carrier_id)
        payload = body()
        expected = req_int(payload, "expected_carrier_version")
        open_requisitions = opt_int(payload, "open_requisitions", minimum=0)
        safety_rating = opt_enum(payload, "safety_rating", SAFETY_RATINGS)
        if expected != carrier["version"]:
            fail("ERR_STALE_VERSION", "expected_carrier_version does not match.")
        if open_requisitions is not None:
            carrier["open_requisitions"] = open_requisitions
        if safety_rating is not None:
            carrier["safety_rating"] = safety_rating
        touch(carrier)
        domain.recompute_carrier(carrier)
        return ok(serialize(carrier))

    # -----------------------------------------------------------------
    # DriverApplicant
    # -----------------------------------------------------------------
    @app.post("/driver-applicants")
    def applicant_create():
        require_roles([ROLE_RECRUITER])
        payload = body()
        carrier = fk(payload, "carrier_id", "carriers")
        if carrier is None:
            req_str(payload, "carrier_id")
            fail("ERR_VALIDATION", "carrier_id must be a valid identifier.")
        full_name = req_str(payload, "full_name")
        date_of_birth = req_date(payload, "date_of_birth")
        email = req_str(payload, "email")
        cdl_number = req_str(payload, "cdl_number")
        cdl_state = req_str(payload, "cdl_state")
        if len(cdl_state) != 2 or not cdl_state.isalpha() or not cdl_state.isupper():
            fail("ERR_VALIDATION", "cdl_state must be two uppercase letters.")
        cdl_class = req_enum(payload, "cdl_class", CDL_CLASSES)
        experience_months = req_int(payload, "experience_months", minimum=0)
        for existing in all_rows("driver_applicants"):
            if (existing["carrier_id"] == carrier["id"]
                    and existing["email"] == email):
                fail("ERR_DUPLICATE_DOT_NUMBER", "email already used at this carrier.")
        applicant = new_row("driver_applicants", {
            "carrier_id": carrier["id"],
            "full_name": full_name,
            "date_of_birth": fmt_date(date_of_birth),
            "email": email,
            "cdl_number": cdl_number,
            "cdl_state": cdl_state,
            "cdl_class": cdl_class,
            "experience_months": experience_months,
            "cdl_downgrade_risk": "NO_CERTIFICATE",
            "governing_medical_cert_expires_on": None,
            "rehire_eligibility": "ELIGIBLE",
            "outstanding_clawback_cents": 0,
        })
        return created(serialize(applicant))

    @app.get("/driver-applicants/<applicant_id>")
    def applicant_read(applicant_id):
        require_roles(ALL_ROLES)
        applicant = must_get("driver_applicants", applicant_id)
        domain.refresh_applicant_silent(applicant)
        return ok(serialize(applicant))

    @app.get("/driver-applicants")
    def applicant_list():
        require_roles(ALL_ROLES)
        rows = filtered("driver_applicants", {
            "carrier_id": qs("carrier_id"),
            "rehire_eligibility": qs("rehire_eligibility"),
            "cdl_downgrade_risk": qs("cdl_downgrade_risk"),
        })
        return page(rows)

    # -----------------------------------------------------------------
    # DriverApplication
    # -----------------------------------------------------------------
    def duplicate_active(applicant_id, carrier_id, exclude_id=None):
        for existing in all_rows("driver_applications"):
            if existing["applicant_id"] != applicant_id:
                continue
            if existing["carrier_id"] != carrier_id:
                continue
            if existing["id"] == exclude_id:
                continue
            if existing["qualification_status"] not in APP_QUAL_TERMINAL:
                return True
        return False

    @app.post("/driver-applications")
    def application_create():
        require_roles([ROLE_RECRUITER])
        payload = body()
        applicant = fk(payload, "applicant_id", "driver_applicants")
        prior = fk(payload, "prior_application_id", "driver_applications",
                   required=False)
        if applicant is None:
            req_str(payload, "applicant_id")
            fail("ERR_VALIDATION", "applicant_id must be a valid identifier.")
        position_type = req_enum(payload, "position_type", POSITION_TYPES)
        if duplicate_active(applicant["id"], applicant["carrier_id"]):
            fail("ERR_DUPLICATE_ACTIVE_APPLICATION",
                 "Applicant already holds a non-terminal application at this carrier.")
        carrier = domain.carrier_of_applicant(applicant)
        verdict = calc.rehire_eligibility(applicant, carrier)["rehire_eligibility"]
        if verdict != "ELIGIBLE":
            fail("ERR_REHIRE_INELIGIBLE", "Applicant is not re-hire eligible.")
        application = new_row("driver_applications", {
            "applicant_id": applicant["id"],
            "carrier_id": applicant["carrier_id"],
            "prior_application_id": prior["id"] if prior else None,
            "position_type": position_type,
            "screening_status": "DRAFT",
            "qualification_status": "NOT_STARTED",
            "revision_round": 0,
            "submitted_at": None,
            "recruiter_user_id": None,
            "verified_coverage_days": 0,
            "gap_days_unexplained": calc.LOOKBACK_DAYS,
            "disqualifying_reason": None,
        })
        return created(serialize(application))

    @app.get("/driver-applications/<application_id>")
    def application_read(application_id):
        require_roles(ALL_ROLES)
        application = must_get("driver_applications", application_id)
        return ok(serialize(application))

    @app.get("/driver-applications")
    def application_list():
        require_roles(ALL_ROLES)
        rows = filtered("driver_applications", {
            "applicant_id": qs("applicant_id"),
            "carrier_id": qs("carrier_id"),
            "prior_application_id": qs("prior_application_id"),
            "screening_status": qs("screening_status"),
            "qualification_status": qs("qualification_status"),
        })
        return page(rows)

    @app.post("/driver-applications/<application_id>/submit")
    def application_submit(application_id):
        require_roles([ROLE_RECRUITER])
        application = must_get("driver_applications", application_id)
        if application["screening_status"] in APP_SCREENING_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Application screening is already terminal.")
        if application["qualification_status"] in APP_QUAL_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Application is already terminal.")
        if application["screening_status"] != "DRAFT":
            fail("ERR_INVALID_STATE", "Application is not in DRAFT.")
        applicant = domain.applicant_of_application(application)
        carrier = domain.carrier_of_application(application)
        verdict = calc.rehire_eligibility(applicant, carrier)["rehire_eligibility"]
        if verdict != "ELIGIBLE":
            fail("ERR_REHIRE_INELIGIBLE", "Applicant is not re-hire eligible.")
        posture = calc.carrier_posture(carrier)["posture"]
        if posture not in ("OPEN", "RESTRICTED"):
            fail("ERR_CARRIER_POSTURE_BLOCKED", "Carrier posture blocks submission.")
        application["screening_status"] = "SUBMITTED"
        application["qualification_status"] = "IN_PROGRESS"
        application["submitted_at"] = fmt_instant(now())
        application["recruiter_user_id"] = actor_id()
        touch(application)
        dq_file = domain.create_dq_file(application)
        domain.set_document(dq_file, "APPLICATION_FORM", "PRESENT",
                            effective_on=fmt_date(today()))
        domain.recompute_file(dq_file)
        domain.recompute_review(dq_file)
        domain.recompute_coverage(application)
        return ok(serialize(application))

    @app.post("/driver-applications/<application_id>/request-info")
    def application_request_info(application_id):
        require_roles([ROLE_SAFETY])
        application = must_get("driver_applications", application_id)
        payload = body()
        req_str(payload, "reason")
        if application["screening_status"] in APP_SCREENING_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Application screening is already terminal.")
        if application["screening_status"] != "SCREENING":
            fail("ERR_INVALID_STATE", "Application is not in SCREENING.")
        if application["revision_round"] >= 3:
            fail("ERR_INVALID_STATE", "The revision round budget is exhausted.")
        application["screening_status"] = "INFO_REQUESTED"
        touch(application)
        return ok(serialize(application))

    @app.post("/driver-applications/<application_id>/resubmit-info")
    def application_resubmit_info(application_id):
        require_roles([ROLE_RECRUITER])
        application = must_get("driver_applications", application_id)
        payload = body()
        req_str(payload, "response_note")
        if application["screening_status"] in APP_SCREENING_TERMINAL:
            fail("ERR_ALREADY_TERMINAL", "Application screening is already terminal.")
        if application["screening_status"] != "INFO_REQUESTED":
            fail("ERR_INVALID_STATE", "Application is not in INFO_REQUESTED.")
        if application["revision_round"] >= 3:
            fail("ERR_INVALID_STATE", "The revision round budget is exhausted.")
        application["screening_status"] = "SCREENING"
        application["revision_round"] += 1
        touch(application)
        return ok(serialize(application))

    @app.post("/driver-applications/<application_id>/disqualify")
    def application_disqualify(application_id):
        require_roles([ROLE_SAFETY])
        application = must_get("driver_applications", application_id)
        payload = body()
        reason = req_str(payload, "reason")
        if (application["screening_status"] in APP_SCREENING_TERMINAL
                or application["qualification_status"] in APP_QUAL_TERMINAL):
            fail("ERR_ALREADY_TERMINAL", "Application is already terminal.")
        if application["screening_status"] not in ("SUBMITTED", "SCREENING",
                                                   "INFO_REQUESTED"):
            fail("ERR_INVALID_STATE", "Application cannot be disqualified from here.")
        application["screening_status"] = "SCREEN_FAILED"
        touch(application)
        domain.cascade_disqualify(application, reason)
        return ok(serialize(application))

    @app.post("/driver-applications/<application_id>/reapply")
    def application_reapply(application_id):
        require_roles([ROLE_RECRUITER])
        prior = must_get("driver_applications", application_id)
        payload = body()
        expected = req_int(payload, "expected_application_version")
        position_type = req_enum(payload, "position_type", POSITION_TYPES)
        if expected != prior["version"]:
            fail("ERR_STALE_VERSION", "expected_application_version does not match.")
        if duplicate_active(prior["applicant_id"], prior["carrier_id"]):
            fail("ERR_DUPLICATE_ACTIVE_APPLICATION",
                 "Applicant already holds a non-terminal application at this carrier.")
        touch(prior)
        application = new_row("driver_applications", {
            "applicant_id": prior["applicant_id"],
            "carrier_id": prior["carrier_id"],
            "prior_application_id": prior["id"],
            "position_type": position_type,
            "screening_status": "DRAFT",
            "qualification_status": "NOT_STARTED",
            "revision_round": 0,
            "submitted_at": None,
            "recruiter_user_id": None,
            "verified_coverage_days": 0,
            "gap_days_unexplained": calc.LOOKBACK_DAYS,
            "disqualifying_reason": None,
        })
        return created(serialize(application))

    @app.get("/driver-applications/<application_id>/employment-coverage")
    def application_coverage(application_id):
        require_roles(ALL_ROLES)
        application = must_get("driver_applications", application_id)
        variant = qs("variant") or "strict_verified"
        if variant not in calc.VARIANTS_COVERAGE:
            fail("ERR_VALIDATION", "variant is not a declared member.")
        return ok(calc.employment_coverage(application, variant))
