"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "REGION_CODE": "NE",
    "REGION_NAME": "Northeast",
    "DEALER_NAME": "Acme Motors",
    "DEALER_CODE": "ACME",
    "DEPT_NAME": "Sales",
    "DEPT_KIND": "SALES",
    "ADVISOR_NAME": "Joe",
    "EMPLOYEE_REF": "E1",
    "CUSTOMER_NAME": "Cust",
    "CUSTOMER_EMAIL": "c@x.com",
    "CUSTOMER_PHONE": "5551234567",
    "QS_CODE": "QS-A",
    "QS_QUESTIONS": [{"question_code": "q1", "prompt": "Satisfaction", "weight": 1}],
    "COMPARABILITY_FACTOR": 1.0,
    "PERIOD_START": "2026-09-01T00:00:00Z",
    "PERIOD_END": "2026-10-01T00:00:00Z",
    "TX_KIND": "SALE",
    "TX_COMPLETED_AT": "2026-09-05T00:00:00Z",
    "MARGIN_CENTS": 100000,
    "PLAN_TITLE": "Improve follow-up",
    "PLAN_ITEMS": [{"action": "coach staff", "owner": "GM", "due_date": "2026-11-01T00:00:00Z"}],
    "PLAN_DUE_DATE": "2026-12-01T00:00:00Z",
    "FLAG_KIND": "COACHING",
    "FLAG_EVIDENCE": "evidence summary",
    "APPEAL_REASON": "response contested",
}


def create_region_payload(**overrides) -> dict:
    defaults = {"code": DEFAULTS["REGION_CODE"], "name": DEFAULTS["REGION_NAME"]}
    defaults.update(overrides)
    return defaults


def create_dealer_payload(region_id, **overrides) -> dict:
    defaults = {
        "region_id": region_id,
        "name": DEFAULTS["DEALER_NAME"],
        "dealer_code": DEFAULTS["DEALER_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_department_payload(dealer_id, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "kind": DEFAULTS["DEPT_KIND"],
        "name": DEFAULTS["DEPT_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_advisor_payload(department_id, **overrides) -> dict:
    defaults = {
        "department_id": department_id,
        "name": DEFAULTS["ADVISOR_NAME"],
        "employee_ref": DEFAULTS["EMPLOYEE_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "email": DEFAULTS["CUSTOMER_EMAIL"],
        "phone": DEFAULTS["CUSTOMER_PHONE"],
    }
    defaults.update(overrides)
    return defaults


def create_question_set_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["QS_CODE"],
        "questions": list(DEFAULTS["QS_QUESTIONS"]),
        "comparability_factor": DEFAULTS["COMPARABILITY_FACTOR"],
    }
    defaults.update(overrides)
    return defaults


def create_wave_payload(question_set_id, **overrides) -> dict:
    defaults = {
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "question_set_id": question_set_id,
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(dealer_id, department_id, customer_id, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "department_id": department_id,
        "customer_id": customer_id,
        "kind": DEFAULTS["TX_KIND"],
        "completed_at": DEFAULTS["TX_COMPLETED_AT"],
        "margin_cents": DEFAULTS["MARGIN_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_response_answers(scores_by_code) -> dict:
    """scores_by_code: dict like {'q1': 8, 'q2': 9}."""
    return {
        "answers": [
            {"question_code": code, "score": score}
            for code, score in scores_by_code.items()
        ]
    }


def create_appeal_payload(response_id, expected_response_version, **overrides) -> dict:
    defaults = {
        "response_id": response_id,
        "reason": DEFAULTS["APPEAL_REASON"],
        "expected_response_version": expected_response_version,
    }
    defaults.update(overrides)
    return defaults


def create_flag_payload(dealer_id, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "kind": DEFAULTS["FLAG_KIND"],
        "evidence": DEFAULTS["FLAG_EVIDENCE"],
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(dealer_id, wave_id, expected_wave_version, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "wave_id": wave_id,
        "expected_wave_version": expected_wave_version,
    }
    defaults.update(overrides)
    return defaults


def create_action_plan_payload(dealer_id, wave_id, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "wave_id": wave_id,
        "title": DEFAULTS["PLAN_TITLE"],
        "items": list(DEFAULTS["PLAN_ITEMS"]),
        "due_date": DEFAULTS["PLAN_DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults
