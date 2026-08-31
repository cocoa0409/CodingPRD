"""Appeals and union grievances."""
from decimal import Decimal

import calc
import services as svc
from auth import authenticate
from errors import err
from response import created, ok, paginated
from store import S, D, new_record, now, round_half_up, sorted_records, touch
from validation import body, query_enum, query_str, v_enum, v_num, v_str

APPEAL_ROLES = ("HrAdmin", "Teacher", "AppealPanelist", "UnionRep", "Evaluator")
APPEAL_STATUSES = ("FILED", "UNDER_REVIEW", "UPHELD", "MODIFIED", "REMANDED")
GRIEVANCE_ROLES = ("HrAdmin", "UnionRep", "Teacher")
GRIEVANCE_STATUSES = ("FILED", "SUSTAINED", "DENIED", "WITHDRAWN")


def register(app):
    # ---------------------------------------------------------------- appeals
    @app.post("/appeals")
    def file_appeal():
        user_id, _role = authenticate(("Teacher",))
        data = body()
        cycle_id = v_str(data, "cycle_id")
        grounds = v_enum(data, "grounds", ("PROCEDURAL", "EVIDENTIARY", "SCORING"))
        statement = v_str(data, "statement")
        cycle = S.cycles.get(cycle_id)
        if cycle is None:
            raise err("ERR_CYCLE_NOT_FOUND")
        if user_id != cycle["educator_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER")
        if cycle["status"] != "FINALIZED" or cycle["dispute_state"] != "NONE":
            raise err("ERR_CYCLE_STATE_INVALID")
        deadline = cycle["appeal_deadline"]
        if deadline is None or now() > deadline:
            raise err("ERR_APPEAL_WINDOW_CLOSED")
        record = new_record(
            cycle_id=cycle_id,
            educator_id=cycle["educator_id"],
            grounds=grounds,
            statement=statement,
            status="FILED",
            panelist_evaluator_id=None,
            adjusted_composite=None,
            decided_at=None,
        )
        S.appeals[record["id"]] = record
        cycle["dispute_state"] = "APPEALED"
        touch(cycle)
        return created(svc.ser_appeal(record))

    @app.get("/appeals/<appeal_id>")
    def read_appeal(appeal_id):
        authenticate(APPEAL_ROLES)
        record = S.appeals.get(appeal_id)
        if record is None:
            raise err("ERR_APPEAL_NOT_FOUND")
        return ok(svc.ser_appeal(record))

    @app.get("/appeals")
    def list_appeals():
        authenticate(APPEAL_ROLES)
        cycle_id = query_str("cycle_id")
        educator_id = query_str("educator_id")
        panelist_evaluator_id = query_str("panelist_evaluator_id")
        status = query_enum("status", APPEAL_STATUSES)
        items = sorted_records(S.appeals.values())
        if cycle_id is not None:
            items = [i for i in items if i["cycle_id"] == cycle_id]
        if educator_id is not None:
            items = [i for i in items if i["educator_id"] == educator_id]
        if panelist_evaluator_id is not None:
            items = [i for i in items if i["panelist_evaluator_id"] == panelist_evaluator_id]
        if status is not None:
            items = [i for i in items if i["status"] == status]
        return paginated(items, svc.ser_appeal)

    @app.post("/appeals/<appeal_id>/review")
    def review_appeal(appeal_id):
        user_id, _role = authenticate(("AppealPanelist",))
        appeal = S.appeals.get(appeal_id)
        if appeal is None:
            raise err("ERR_APPEAL_NOT_FOUND")
        for observation in svc.observations_of_cycle(appeal["cycle_id"]):
            if observation["status"] in ("SUBMITTED", "ACCEPTED") \
                    and observation["evaluator_id"] == user_id:
                raise err("ERR_SEGREGATION_OF_DUTIES")
        if appeal["status"] != "FILED":
            raise err("ERR_APPEAL_STATE_INVALID")
        evaluator = S.evaluators.get(user_id)
        if evaluator is None or evaluator["certification_status"] != "CERTIFIED":
            raise err("ERR_EVALUATOR_NOT_CERTIFIED")
        appeal["status"] = "UNDER_REVIEW"
        appeal["panelist_evaluator_id"] = user_id
        touch(appeal)
        return ok(svc.ser_appeal(appeal))

    @app.post("/appeals/<appeal_id>/decide")
    def decide_appeal(appeal_id):
        user_id, _role = authenticate(("AppealPanelist",))
        data = body()
        outcome = v_enum(data, "outcome", ("UPHELD", "MODIFIED", "REMANDED"))
        adjusted = v_num(data, "adjusted_composite", required=False, default=None,
                         minimum=1.00, maximum=4.00)
        if outcome == "MODIFIED" and adjusted is None:
            raise err("ERR_INVALID_REQUEST", "adjusted_composite is required for a MODIFIED outcome.")
        if outcome != "MODIFIED" and adjusted is not None:
            raise err("ERR_INVALID_REQUEST",
                      "adjusted_composite must be absent unless the outcome is MODIFIED.")
        appeal = S.appeals.get(appeal_id)
        if appeal is None:
            raise err("ERR_APPEAL_NOT_FOUND")
        if appeal["panelist_evaluator_id"] is not None \
                and user_id != appeal["panelist_evaluator_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER")
        if appeal["status"] != "UNDER_REVIEW":
            raise err("ERR_APPEAL_STATE_INVALID")
        cycle = S.cycles.get(appeal["cycle_id"])
        policy = svc.policy_of_cycle(cycle) if cycle else None
        appeal["status"] = outcome
        appeal["decided_at"] = now()
        if outcome == "MODIFIED":
            appeal["adjusted_composite"] = adjusted
        touch(appeal)

        cycle["dispute_state"] = "APPEAL_RESOLVED"
        if outcome == "MODIFIED":
            score = round_half_up(D(adjusted), 2)
            cycle["composite_score"] = score
            cycle["composite_rating"] = calc.band(score, policy)
            svc.recompute_educator_rating(S.educators.get(cycle["educator_id"]))
            if cycle["composite_rating"] != "INEFFECTIVE":
                svc.void_open_plans_of_cycle(cycle)
        elif outcome == "REMANDED":
            svc.revert_cycle_to_scoring(cycle)
        touch(cycle)
        return ok(svc.ser_appeal(appeal))

    # ------------------------------------------------------------ grievances
    @app.post("/grievances")
    def file_grievance():
        authenticate(("UnionRep",))
        data = body()
        appeal_id = v_str(data, "appeal_id")
        article_code = v_enum(data, "article_code", ("ART_12_EVALUATION", "ART_14_DISCIPLINE"))
        appeal = S.appeals.get(appeal_id)
        if appeal is None:
            raise err("ERR_APPEAL_NOT_FOUND")
        if appeal["status"] != "UPHELD":
            raise err("ERR_APPEAL_NOT_EXHAUSTED")
        cycle = S.cycles.get(appeal["cycle_id"])
        if cycle is None or cycle["dispute_state"] != "APPEAL_RESOLVED":
            raise err("ERR_CYCLE_STATE_INVALID")
        record = new_record(
            appeal_id=appeal_id,
            educator_id=appeal["educator_id"],
            article_code=article_code,
            status="FILED",
            remedy="NONE",
        )
        S.grievances[record["id"]] = record
        cycle["dispute_state"] = "GRIEVED"
        touch(cycle)
        return created(svc.ser_grievance(record))

    @app.get("/grievances/<grievance_id>")
    def read_grievance(grievance_id):
        authenticate(GRIEVANCE_ROLES)
        record = S.grievances.get(grievance_id)
        if record is None:
            raise err("ERR_RESOURCE_NOT_FOUND")
        return ok(svc.ser_grievance(record))

    @app.get("/grievances")
    def list_grievances():
        authenticate(GRIEVANCE_ROLES)
        appeal_id = query_str("appeal_id")
        educator_id = query_str("educator_id")
        status = query_enum("status", GRIEVANCE_STATUSES)
        items = sorted_records(S.grievances.values())
        if appeal_id is not None:
            items = [i for i in items if i["appeal_id"] == appeal_id]
        if educator_id is not None:
            items = [i for i in items if i["educator_id"] == educator_id]
        if status is not None:
            items = [i for i in items if i["status"] == status]
        return paginated(items, svc.ser_grievance)

    @app.post("/grievances/<grievance_id>/decide")
    def decide_grievance(grievance_id):
        _user_id, role = authenticate(("HrAdmin", "UnionRep"))
        data = body()
        outcome = v_enum(data, "outcome", ("SUSTAIN", "DENY", "WITHDRAW"))
        remedy = v_enum(data, "remedy", ("NONE", "RATING_VACATED", "PLAN_VOIDED"),
                        required=False, default=None)
        if role == "UnionRep" and outcome != "WITHDRAW":
            raise err("ERR_UNAUTHORIZED", "A UnionRep may only withdraw a grievance.")
        if role == "HrAdmin" and outcome == "WITHDRAW":
            raise err("ERR_UNAUTHORIZED", "Only a UnionRep may withdraw a grievance.")
        if outcome == "SUSTAIN" and remedy not in ("RATING_VACATED", "PLAN_VOIDED"):
            raise err("ERR_INVALID_REQUEST",
                      "A sustained grievance requires a RATING_VACATED or PLAN_VOIDED remedy.")
        grievance = S.grievances.get(grievance_id)
        if grievance is None:
            raise err("ERR_RESOURCE_NOT_FOUND")
        if grievance["status"] != "FILED":
            raise err("ERR_GRIEVANCE_STATE_INVALID")
        appeal = S.appeals.get(grievance["appeal_id"])
        cycle = S.cycles.get(appeal["cycle_id"]) if appeal else None
        if outcome == "SUSTAIN":
            grievance["status"] = "SUSTAINED"
            grievance["remedy"] = remedy
        elif outcome == "DENY":
            grievance["status"] = "DENIED"
        else:
            grievance["status"] = "WITHDRAWN"
        touch(grievance)
        if cycle is not None:
            cycle["dispute_state"] = "GRIEVANCE_RESOLVED"
            if outcome == "SUSTAIN" and remedy == "RATING_VACATED":
                if cycle["status"] == "FINALIZED":
                    svc.revert_cycle_to_scoring(cycle)
                else:
                    svc.void_open_plans_of_cycle(cycle)
            elif outcome == "SUSTAIN" and remedy == "PLAN_VOIDED":
                svc.void_open_plans_of_cycle(cycle)
            touch(cycle)
        return ok(svc.ser_grievance(grievance))
