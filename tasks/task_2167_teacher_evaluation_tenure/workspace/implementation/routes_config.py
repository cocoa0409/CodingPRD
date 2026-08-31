"""Policies, schools, educators, evaluators and calibration reviews."""
from datetime import timedelta
from decimal import Decimal

import calc
import services as svc
from auth import authenticate
from errors import err
from response import created, ok, paginated, pagination
from store import (S, D, clock_date, fmt_date, new_record, num, round_half_up,
                   sorted_records, touch)
from validation import (body, query_str, query_enum, v_date, v_enum, v_int, v_num, v_str)

ALL_ROLES = ("HrAdmin", "Evaluator", "Teacher", "AppealPanelist", "UnionRep")

POLICY_NUMBER_FIELDS = [
    # (name, default, minimum, maximum)
    ("observation_weight_pct", 60, 0, 100),
    ("growth_weight_pct", 40, 0, 100),
    ("planning_weight_pct", 22, 0, 100),
    ("environment_weight_pct", 23, 0, 100),
    ("instruction_weight_pct", 33, 0, 100),
    ("professionalism_weight_pct", 22, 0, 100),
    ("unannounced_multiplier", 1.10, None, None),
    ("informal_cap", 3.50, None, None),
    ("highly_effective_threshold", 3.50, None, None),
    ("effective_threshold", 2.50, None, None),
    ("developing_threshold", 1.50, None, None),
    ("calibration_drift_tolerance", 0.50, None, None),
]

POLICY_INT_FIELDS = [
    ("required_formal_count", 2, 1, None),
    ("required_informal_count", 1, 0, None),
    ("evidence_min_artifacts", 2, 0, None),
    ("remediation_days", 90, 0, None),
    ("max_plan_extension_days", 45, 0, None),
    ("appeal_window_days", 15, 0, None),
    ("tenure_required_years", 3, 0, None),
    ("tenure_min_consecutive_effective", 2, 0, None),
    ("min_days_between_formals", 10, 0, None),
    ("calibration_max_consecutive_failures", 2, 0, None),
    ("observation_stipend_cents", 12500, 0, None),
]


def register(app):
    # ------------------------------------------------------------- policies
    @app.post("/evaluation-policies")
    def create_policy():
        authenticate(("HrAdmin",))
        data = body()
        fields = {"school_year": v_str(data, "school_year")}
        for name, default, minimum, maximum in POLICY_NUMBER_FIELDS:
            fields[name] = v_num(data, name, required=False, default=default,
                                 minimum=minimum, maximum=maximum)
        for name, default, minimum, maximum in POLICY_INT_FIELDS:
            fields[name] = v_int(data, name, required=False, default=default,
                                 minimum=minimum, maximum=maximum)
        if D(fields["observation_weight_pct"]) + D(fields["growth_weight_pct"]) != Decimal(100):
            raise err("ERR_INVALID_REQUEST",
                      "observation_weight_pct and growth_weight_pct must sum to 100.")
        domain_total = (D(fields["planning_weight_pct"]) + D(fields["environment_weight_pct"])
                        + D(fields["instruction_weight_pct"])
                        + D(fields["professionalism_weight_pct"]))
        if domain_total != Decimal(100):
            raise err("ERR_INVALID_REQUEST", "The four rubric domain weights must sum to 100.")
        record = new_record(**fields)
        S.policies[record["id"]] = record
        return created(svc.ser_policy(record))

    @app.get("/evaluation-policies/<policy_id>")
    def read_policy(policy_id):
        authenticate(ALL_ROLES)
        record = S.policies.get(policy_id)
        if record is None:
            raise err("ERR_RESOURCE_NOT_FOUND")
        return ok(svc.ser_policy(record))

    # -------------------------------------------------------------- schools
    @app.post("/schools")
    def create_school():
        authenticate(("HrAdmin",))
        data = body()
        record = new_record(
            name=v_str(data, "name"),
            code=v_str(data, "code"),
            level=v_enum(data, "level", ("ELEMENTARY", "MIDDLE", "HIGH")),
            evaluation_budget_allocated_cents=v_int(
                data, "evaluation_budget_allocated_cents", required=False,
                default=100000, minimum=0),
            evaluation_budget_committed_cents=0,
        )
        S.schools[record["id"]] = record
        return created(svc.ser_school(record))

    @app.get("/schools/<school_id>")
    def read_school(school_id):
        authenticate(ALL_ROLES)
        record = S.schools.get(school_id)
        if record is None:
            raise err("ERR_RESOURCE_NOT_FOUND")
        return ok(svc.ser_school(record))

    # ------------------------------------------------------------ educators
    @app.post("/educators")
    def create_educator():
        authenticate(("HrAdmin",))
        data = body()
        school_id = v_str(data, "school_id")
        employee_number = v_str(data, "employee_number")
        full_name = v_str(data, "full_name")
        v_date(data, "service_start_date")
        if school_id not in S.schools:
            raise err("ERR_RESOURCE_NOT_FOUND")
        for educator in S.educators.values():
            if educator["employee_number"] == employee_number:
                raise err("ERR_DUPLICATE_EMPLOYEE_NUMBER")
        record = new_record(
            school_id=school_id,
            employee_number=employee_number,
            full_name=full_name,
            service_start_date=data["service_start_date"],
            tenure_status="PROBATIONARY",
            last_composite_rating=None,
            tenure_recommended_by_user_id=None,
        )
        S.educators[record["id"]] = record
        return created(svc.ser_educator(record))

    @app.get("/educators/<educator_id>")
    def read_educator(educator_id):
        authenticate(ALL_ROLES)
        record = S.educators.get(educator_id)
        if record is None:
            raise err("ERR_EDUCATOR_NOT_FOUND")
        return ok(svc.ser_educator(record))

    @app.get("/educators")
    def list_educators():
        authenticate(("HrAdmin", "Evaluator", "AppealPanelist", "UnionRep"))
        school_id = query_str("school_id")
        tenure_status = query_enum(
            "tenure_status",
            ("PROBATIONARY", "RECOMMENDED", "TENURED", "DENIED", "NON_RENEWED"))
        items = sorted_records(S.educators.values())
        if school_id is not None:
            items = [i for i in items if i["school_id"] == school_id]
        if tenure_status is not None:
            items = [i for i in items if i["tenure_status"] == tenure_status]
        return paginated(items, svc.ser_educator)

    @app.post("/educators/<educator_id>/tenure-recommendation")
    def tenure_recommendation(educator_id):
        user_id, _role = authenticate(("HrAdmin",))
        data = body()
        recommendation = v_enum(data, "recommendation", ("RECOMMEND", "NON_RENEW"))
        educator = S.educators.get(educator_id)
        if educator is None:
            raise err("ERR_EDUCATOR_NOT_FOUND")
        svc.recompute_educator_rating(educator)
        if educator["tenure_status"] != "PROBATIONARY":
            raise err("ERR_TENURE_STATE_INVALID")
        if recommendation == "NON_RENEW":
            if educator["last_composite_rating"] not in ("INEFFECTIVE", "DEVELOPING"):
                raise err("ERR_TENURE_STATE_INVALID",
                          "A non-renewal requires an INEFFECTIVE or DEVELOPING last rating.")
            educator["tenure_status"] = "NON_RENEWED"
            touch(educator)
            return ok(svc.ser_educator(educator))
        policy = svc.policy_for_educator(educator_id)
        eligible = policy is not None
        if eligible:
            eligible = (
                svc.completed_service_years(educator) >= int(policy["tenure_required_years"])
                and svc.consecutive_effective_years(educator_id)
                >= int(policy["tenure_min_consecutive_effective"])
                and svc.tenure_track_hold(educator) is False
            )
        if not eligible:
            raise err("ERR_TENURE_NOT_ELIGIBLE")
        educator["tenure_status"] = "RECOMMENDED"
        educator["tenure_recommended_by_user_id"] = user_id
        touch(educator)
        return ok(svc.ser_educator(educator))

    @app.post("/educators/<educator_id>/tenure-decision")
    def tenure_decision(educator_id):
        user_id, _role = authenticate(("HrAdmin",))
        data = body()
        decision = v_enum(data, "decision", ("GRANT", "DENY"))
        educator = S.educators.get(educator_id)
        if educator is None:
            raise err("ERR_EDUCATOR_NOT_FOUND")
        if educator["tenure_recommended_by_user_id"] is not None \
                and user_id == educator["tenure_recommended_by_user_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES")
        if educator["tenure_status"] != "RECOMMENDED":
            raise err("ERR_TENURE_STATE_INVALID")
        educator["tenure_status"] = "TENURED" if decision == "GRANT" else "DENIED"
        touch(educator)
        return ok(svc.ser_educator(educator))

    # ----------------------------------------------------------- evaluators
    @app.post("/evaluators")
    def create_evaluator():
        authenticate(("HrAdmin",))
        data = body()
        record = new_record(
            full_name=v_str(data, "full_name"),
            certification_status="PROVISIONAL",
            certification_expires_on=None,
            consecutive_failed_calibrations=0,
            passed_calibration_count=0,
            calibration_drift_rolling=Decimal("0.00"),
            calibration_drift_anchor=Decimal("0.00"),
        )
        S.evaluators[record["id"]] = record
        return created(svc.ser_evaluator(record))

    @app.get("/evaluators/<evaluator_id>")
    def read_evaluator(evaluator_id):
        authenticate(ALL_ROLES)
        record = S.evaluators.get(evaluator_id)
        if record is None:
            raise err("ERR_EVALUATOR_NOT_FOUND")
        return ok(svc.ser_evaluator(record))

    # -------------------------------------------------- calibration reviews
    @app.post("/calibration-reviews")
    def create_calibration():
        authenticate(("HrAdmin",))
        data = body()
        evaluator_id = v_str(data, "evaluator_id")
        anchor_lesson_code = v_str(data, "anchor_lesson_code")
        anchor_score = v_num(data, "anchor_score", minimum=1.00, maximum=4.00)
        evaluator_score = v_num(data, "evaluator_score", minimum=1.00, maximum=4.00)
        if evaluator_id not in S.evaluators:
            raise err("ERR_EVALUATOR_NOT_FOUND")
        deviation = round_half_up(abs(D(evaluator_score) - D(anchor_score)), 2)
        record = new_record(
            evaluator_id=evaluator_id,
            anchor_lesson_code=anchor_lesson_code,
            anchor_score=anchor_score,
            evaluator_score=evaluator_score,
            deviation=deviation,
            outcome="PENDING",
            sequence_index=None,
        )
        S.calibrations[record["id"]] = record
        return created(svc.ser_calibration(record))

    @app.get("/evaluators/<evaluator_id>/calibration-reviews")
    def list_calibrations(evaluator_id):
        authenticate(("HrAdmin", "Evaluator", "AppealPanelist"))
        outcome = query_enum("outcome", ("PENDING", "PASS", "FAIL"))
        pagination()
        if evaluator_id not in S.evaluators:
            raise err("ERR_EVALUATOR_NOT_FOUND")
        items = svc.calibrations_of_evaluator(evaluator_id)
        if outcome is not None:
            items = [i for i in items if i["outcome"] == outcome]
        return paginated(items, svc.ser_calibration)

    @app.post("/calibration-reviews/<review_id>/decide")
    def decide_calibration(review_id):
        authenticate(("HrAdmin",))
        data = body()
        policy_id = v_str(data, "policy_id")
        review = S.calibrations.get(review_id)
        if review is None:
            raise err("ERR_RESOURCE_NOT_FOUND")
        policy = S.policies.get(policy_id)
        if policy is None:
            raise err("ERR_RESOURCE_NOT_FOUND")
        if review["outcome"] != "PENDING":
            raise err("ERR_INVALID_REQUEST", "The calibration review has already been decided.")
        evaluator = S.evaluators.get(review["evaluator_id"])
        tolerance = D(policy["calibration_drift_tolerance"])
        outcome = "PASS" if D(review["deviation"]) <= tolerance else "FAIL"
        review["outcome"] = outcome
        decided = [r for r in svc.calibrations_of_evaluator(review["evaluator_id"])
                   if r["outcome"] in ("PASS", "FAIL")]
        position = 1
        for index, item in enumerate(decided):
            if item["id"] == review["id"]:
                position = index + 1
                break
        review["sequence_index"] = position
        touch(review)

        rolling, anchor = calc.calibration_drift(decided)
        evaluator["calibration_drift_rolling"] = rolling
        evaluator["calibration_drift_anchor"] = anchor
        if outcome == "PASS":
            evaluator["consecutive_failed_calibrations"] = 0
            evaluator["passed_calibration_count"] += 1
        else:
            evaluator["consecutive_failed_calibrations"] += 1

        expiry = fmt_date(clock_date() + timedelta(days=calc.CERTIFICATION_TERM_DAYS))
        status = evaluator["certification_status"]
        suspended = False
        if status == "PROVISIONAL":
            if outcome == "PASS" and rolling <= tolerance:
                evaluator["certification_status"] = "CERTIFIED"
                evaluator["certification_expires_on"] = expiry
        elif status == "CERTIFIED":
            if outcome == "FAIL":
                threshold = int(policy["calibration_max_consecutive_failures"])
                if evaluator["consecutive_failed_calibrations"] >= threshold:
                    evaluator["certification_status"] = "SUSPENDED"
                    evaluator["certification_expires_on"] = None
                    suspended = True
            else:
                evaluator["certification_expires_on"] = expiry
        elif status == "SUSPENDED":
            if outcome == "PASS" and rolling <= tolerance:
                evaluator["certification_status"] = "CERTIFIED"
                evaluator["certification_expires_on"] = expiry
        touch(evaluator)
        if suspended:
            svc.suspend_evaluator_cascade(evaluator)
        return ok(svc.ser_calibration(review))
