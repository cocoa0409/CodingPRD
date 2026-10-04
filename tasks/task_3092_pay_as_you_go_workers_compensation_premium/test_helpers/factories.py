"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Test Employer Co",
    "FEIN": "10-0000001",
    "CONTACT_EMAIL": "ops@example.test",
    "HOME_STATE": "CA",
    "POLICY_EFFECTIVE": "2026-09-01T00:00:00Z",
    "POLICY_EXPIRY": "2027-09-01T00:00:00Z",
    "EXPERIENCE_MOD": 1.0,
    "ESTIMATED_PAYROLL": 1000000,
    "WEEK_START": "2026-09-01T00:00:00Z",
    "WEEK_END": "2026-09-08T00:00:00Z",
}


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "fein": DEFAULTS["FEIN"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "home_state": DEFAULTS["HOME_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_state_rating_table_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
        "monopolistic": False,
        "per_capita_admin_fee_cents": 250,
        "expense_constant_cents": 30000,
        "min_payroll_threshold_cents": 10000,
        "state_minimum_premium_cents": 50000,
        "ot_basis": "NET",
        "class_rates": [{"class_code": "8810", "rate_per_100_cents": 125}],
        "max_payroll_per_executive_cents": 250000,
    }
    defaults.update(overrides)
    return defaults


def class_code_entry(state_code="CA", class_code="8810",
                     estimated_annual_payroll_cents=DEFAULTS["ESTIMATED_PAYROLL"],
                     **overrides) -> dict:
    entry = {
        "state_code": state_code,
        "class_code": class_code,
        "estimated_annual_payroll_cents": estimated_annual_payroll_cents,
    }
    entry.update(overrides)
    return entry


def create_policy_payload(employer_id, policy_number="WC-TEST-001",
                          class_codes=None, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "policy_number": policy_number,
        "effective_date": DEFAULTS["POLICY_EFFECTIVE"],
        "expiry_date": DEFAULTS["POLICY_EXPIRY"],
        "experience_mod": DEFAULTS["EXPERIENCE_MOD"],
        "class_codes": class_codes if class_codes is not None
        else [class_code_entry()],
    }
    defaults.update(overrides)
    return defaults


def payroll_line(state_code="CA", class_code="8810",
                 gross_wages_cents=10000000, ot_premium_cents=0,
                 severance_cents=0, executive_wages_cents=0, headcount=1,
                 **overrides) -> dict:
    line = {
        "state_code": state_code,
        "class_code": class_code,
        "gross_wages_cents": gross_wages_cents,
        "ot_premium_cents": ot_premium_cents,
        "severance_cents": severance_cents,
        "executive_wages_cents": executive_wages_cents,
        "headcount": headcount,
    }
    line.update(overrides)
    return line


def create_payroll_report_payload(policy_id, idempotency_key,
                                  period_start=DEFAULTS["WEEK_START"],
                                  period_end=DEFAULTS["WEEK_END"],
                                  lines=None, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "period_start": period_start,
        "period_end": period_end,
        "idempotency_key": idempotency_key,
        "lines": lines if lines is not None else [payroll_line()],
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(policy_id, policy_class_code_id,
                           requested_class_code="8812",
                           effective_from=DEFAULTS["POLICY_EFFECTIVE"],
                           **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "policy_class_code_id": policy_class_code_id,
        "requested_class_code": requested_class_code,
        "effective_from": effective_from,
    }
    defaults.update(overrides)
    return defaults


def create_tax_filing_payload(policy_id, state_code="CA", quarter="2026Q3",
                              period_start="2026-07-01T00:00:00Z",
                              period_end="2026-10-01T00:00:00Z",
                              reported_wages_cents=0, source="SUI",
                              **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "state_code": state_code,
        "quarter": quarter,
        "period_start": period_start,
        "period_end": period_end,
        "reported_wages_cents": reported_wages_cents,
        "source": source,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(policy_id,
                         period_start="2026-09-01T00:00:00Z",
                         period_end="2026-10-01T00:00:00Z",
                         **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults
