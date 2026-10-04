from clock import iso_now, new_id

# Roles recognized by the system.
ROLES = {
    "PlatformAdmin",
    "OpsManager",
    "Supervisor",
    "Agent",
    "QualityAnalyst",
    "KnowledgeManager",
    "SecurityOfficer",
    "BillingAnalyst",
}


def _base(common=True):
    rec = {"id": new_id(), "created_at": iso_now()}
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = iso_now()
    if "version" in rec:
        rec["version"] += 1


def make_contract(data):
    rec = _base()
    rec.update({
        "agency_name": data["agency_name"],
        "measurement_tz": data["measurement_tz"],
        "cap_absolutes": data["cap_absolutes"],
        "status": "DRAFT",
        "withheld_cents_cum": 0,
        "cure_periods_used": 0,
    })
    return rec


def make_service_level(data):
    rec = _base()
    rec.update({
        "contract_id": data["contract_id"],
        "program_code": data["program_code"],
        "metric": data["metric"],
        "target": data["target"],
        "cap_pct_of_gross": data["cap_pct_of_gross"],
        "remedy_fee_cents": data["remedy_fee_cents"],
        "effective_from": data["effective_from"],
        "status": "DRAFT",
    })
    return rec


def make_agent(data):
    rec = _base()
    rec.update({
        "full_name": data["full_name"],
        "languages": list(data["languages"]),
        "employment_status": "ACTIVE",
    })
    return rec


def make_certification(agent_id, program_code, training_course_id, valid_until):
    rec = _base(common=False)
    rec.update({
        "agent_id": agent_id,
        "program_code": program_code,
        "training_course_id": training_course_id,
        "valid_until": valid_until,
        "invalidated_at": None,
        "invalidated_by_article_id": None,
    })
    return rec


def make_course_completion(training_course_id, agent_id, completed_at):
    rec = _base(common=False)
    rec.update({
        "training_course_id": training_course_id,
        "agent_id": agent_id,
        "completed_at": completed_at,
    })
    return rec


def make_queue(data):
    rec = _base()
    rec.update({
        "contract_id": data["contract_id"],
        "program_code": data["program_code"],
        "language_code": data["language_code"],
        "overflow_queue_id": data.get("overflow_queue_id"),
        "queue_type": data["queue_type"],
        "specialty_tag": data.get("specialty_tag"),
        "status": "OPEN",
    })
    return rec


def make_call(data):
    rec = _base()
    rec.update({
        "contract_id": data["contract_id"],
        "program_code": data["program_code"],
        "language_code": data["language_code"],
        "required_specialty": data.get("required_specialty"),
        "enqueued_at": data["enqueued_at"],
        "status": "WAITING",
        "queue_id": None,
        "agent_id": None,
        "assigned_via": None,
        "route_depth": 0,
        "answered_at": None,
        "ended_at": None,
        "abandoned_at": None,
        "answer_seconds": None,
        "talk_seconds": None,
        "handled_by_agent_id": None,
    })
    return rec


def make_quality_review(data, total_score):
    rec = _base()
    rec.update({
        "call_id": data["call_id"],
        "accuracy_score": data["accuracy_score"],
        "compliance_score": data["compliance_score"],
        "total_score": total_score,
        "accuracy_weight": data.get("accuracy_weight", 0.5),
        "status": "SUBMITTED",
        "final": False,
    })
    return rec


def make_coaching_plan(agent_id, trigger, due_date):
    rec = _base()
    rec.update({
        "agent_id": agent_id,
        "trigger": trigger,
        "due_date": due_date,
        "status": "OPEN",
    })
    return rec


def make_knowledge_article(data):
    rec = _base()
    rec.update({
        "program_code": data["program_code"],
        "title": data["title"],
        "body": data["body"],
        "effective_at": data["effective_at"],
        "status": "DRAFT",
    })
    return rec


def make_training_course(data):
    rec = _base()
    rec.update({
        "program_code": data["program_code"],
        "knowledge_article_id": data.get("knowledge_article_id"),
        "required": data.get("required", True),
    })
    return rec


def make_surge_window(data, initial_status):
    rec = _base()
    rec.update({
        "contract_id": data["contract_id"],
        "program_code": data["program_code"],
        "surge_type": data["surge_type"],
        "starts_on": data["starts_on"],
        "ends_on": data["ends_on"],
        "expected_volume_factor": data["expected_volume_factor"],
        "status": initial_status,
    })
    return rec


def make_incident(data, reported_at):
    rec = _base()
    rec.update({
        "contract_id": data["contract_id"],
        "severity": data["severity"],
        "category": data["category"],
        "occurred_at": data["occurred_at"],
        "reported_at": reported_at,
        "description": data["description"],
        "status": "OPEN",
    })
    return rec


def make_invoice(data, preparer_user_id):
    rec = _base()
    rec.update({
        "contract_id": data["contract_id"],
        "period": data["period"],
        "status": "DRAFT",
        "gross_cents": None,
        "withheld_cents": 0,
        "net_cents": None,
        "auto_review": False,
        "preparer_user_id": preparer_user_id,
    })
    return rec


def make_invoice_line(invoice_id, service_level_id, metric):
    rec = _base()
    rec.update({
        "invoice_id": invoice_id,
        "service_level_id": service_level_id,
        "metric": metric,
        "measured_value": None,
        "staffing_actual": 0,
        "staffing_target": 0,
        "compliant": True,
        "withheld_cents": 0,
    })
    return rec


def make_cure_period(invoice_line_id, opened_at, deadline, remedy_fee_cents):
    rec = _base()
    rec.update({
        "invoice_line_id": invoice_line_id,
        "status": "PENDING",
        "opened_at": opened_at,
        "deadline": deadline,
        "remedy_fee_cents": remedy_fee_cents,
    })
    return rec
