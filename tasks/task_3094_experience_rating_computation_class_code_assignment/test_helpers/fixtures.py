"""Composite setup helpers.

Each helper builds a slice of PRD-declared state through the public API so
tests can focus on assertions. All helpers accept overrides for the values
tests need to control and use the lenient get_success_data() validator so a
setup failure surfaces as a clear "Setup failed" message.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_assigned_risk_enrollment_payload,
    create_assigned_risk_take_out_payload,
    create_bureau_payload,
    create_carrier_payload,
    create_class_assignment_payload,
    create_class_code_payload,
    create_employer_payload,
    create_experience_mod_sheet_payload,
    create_policy_payload,
    create_rating_table_payload,
    create_unit_stat_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_carrier_data_reporter_headers,
    make_employer_representative_headers,
    make_voluntary_carrier_representative_headers,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
ANALYST = TEST_USERS["bureau_analyst_headers"]
POOL_ADMIN = TEST_USERS["pool_administrator_headers"]


def _fail(step, response):
    raise AssertionError(
        f"Setup failed at {step}: {response.status_code} {response.text}"
    )


def _ok(step, response):
    try:
        return get_success_data(response)
    except Exception:
        _fail(step, response)


# ---------------------------------------------------------------------------
# Tier 1: base registry
# ---------------------------------------------------------------------------

def set_clock(current_utc):
    """Advance the logical clock."""
    _ok("set_clock", api_client.set_clock(current_utc, ADMIN))


def create_bureau(**overrides):
    """Register a bureau. Returns the bureau resource."""
    return _ok("create_bureau", api_client.create_bureau(create_bureau_payload(**overrides), ADMIN))


def create_carrier(**overrides):
    return _ok("create_carrier", api_client.create_carrier(create_carrier_payload(**overrides), ADMIN))


def create_employer(**overrides):
    return _ok("create_employer", api_client.create_employer(create_employer_payload(**overrides), ADMIN))


def create_class_code(**overrides):
    return _ok("create_class_code", api_client.create_class_code(create_class_code_payload(**overrides), ADMIN))


def create_rating_table(**overrides):
    return _ok("create_rating_table", api_client.create_rating_table(create_rating_table_payload(**overrides), ADMIN))


def create_and_promulgate_rating_table(**overrides):
    """Create a rating table and promulgate it. Returns the PROMULGATED table."""
    table = create_rating_table(**overrides)
    return _ok(
        "promulgate_rating_table",
        api_client.promulgate_rating_table(table["id"], ADMIN),
    )


def setup_bureau_carrier_employer(
    bureau_overrides=None,
    carrier_overrides=None,
    employer_overrides=None,
):
    """Bureau + one carrier + one employer. Returns (bureau, carrier, employer)."""
    bureau = create_bureau(**(bureau_overrides or {}))
    carrier = create_carrier(**(carrier_overrides or {}))
    employer = create_employer(**(employer_overrides or {}))
    return bureau, carrier, employer


# ---------------------------------------------------------------------------
# Tier 2: rated policy hierarchy
# ---------------------------------------------------------------------------

def setup_rated_policy(
    payroll_dollars=100000,
    policy_number="WC-1001",
    effective_date="2024-01-01",
    expiration_date="2025-01-01",
    rate_per_100_payroll_cents=250,
    elr_per_100_payroll_cents=150,
    d_ratio_bp=4000,
    rating_table_effective_date="2024-01-01",
    bureau_overrides=None,
    carrier_overrides=None,
    employer_overrides=None,
    policy_overrides=None,
):
    """Bureau + carrier + employer + class code + promulgated table + policy.

    Returns (bureau, carrier, employer, class_code, rating_table, policy).
    """
    bureau, carrier, employer = setup_bureau_carrier_employer(
        bureau_overrides=bureau_overrides,
        carrier_overrides=carrier_overrides,
        employer_overrides=employer_overrides,
    )
    class_code = create_class_code()
    table = create_and_promulgate_rating_table(
        effective_date=rating_table_effective_date,
        values=[
            {
                "class_code": class_code["code"],
                "rate_per_100_payroll_cents": rate_per_100_payroll_cents,
                "elr_per_100_payroll_cents": elr_per_100_payroll_cents,
                "d_ratio_bp": d_ratio_bp,
            }
        ],
    )
    payload = create_policy_payload(
        employer_id=employer["id"],
        carrier_id=carrier["id"],
        policy_number=policy_number,
        effective_date=effective_date,
        expiration_date=expiration_date,
        class_codes=[{"class_code": class_code["code"], "payroll_dollars": payroll_dollars}],
    )
    payload.update(policy_overrides or {})
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    policy = _ok("create_policy", api_client.create_policy(payload, reporter))
    return bureau, carrier, employer, class_code, table, policy


def create_report_for_policy(
    policy,
    carrier,
    payroll_dollars=100000,
    claim_lines=None,
    payroll_class_code="3632",
    correction_of_report_id=None,
    validate=True,
):
    """Create a unit statistical report on a policy and optionally validate it.

    Returns the report resource (VALIDATED when validate=True).
    """
    payload = create_unit_stat_report_payload(
        policy_id=policy["id"],
        payroll_lines=[{"class_code": payroll_class_code, "payroll_dollars": payroll_dollars}],
        claim_lines=claim_lines
        or [
            {
                "claim_number": "Q1",
                "claim_type": "MEDICAL",
                "incurred_cents": 50000,
                "paid_cents": 50000,
                "claim_status": "CLOSED",
                "state_code": "TX",
            }
        ],
    )
    if correction_of_report_id is not None:
        payload["correction_of_report_id"] = correction_of_report_id
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    report = _ok("create_unit_stat_report", api_client.create_unit_stat_report(payload, reporter))
    if validate:
        report = _ok(
            "validate_unit_stat_report",
            api_client.validate_unit_stat_report(report["id"], ANALYST),
        )
    return report


def get_employer(employer_id):
    return _ok("get_employer", api_client.get_employer(employer_id, ADMIN))


def create_sheet_for_employer(employer_id, rating_effective_date="2026-01-01"):
    """Create a DRAFT experience modification sheet for an employer.

    The employer's current version is re-read so the concurrency field is
    always fresh. Returns the sheet resource.
    """
    employer = get_employer(employer_id)
    return _ok(
        "create_experience_mod_sheet",
        api_client.create_experience_mod_sheet(
            create_experience_mod_sheet_payload(
                employer_id=employer_id,
                rating_effective_date=rating_effective_date,
                expected_employer_version=employer["version"],
            ),
            ANALYST,
        ),
    )


def setup_employer_with_validated_report(
    payroll_dollars=100000,
    claim_lines=None,
    employer_overrides=None,
    **policy_kwargs,
):
    """Bureau + carrier + employer + table + policy + VALIDATED report.

    Returns (bureau, carrier, employer, class_code, table, policy, report).
    """
    bureau, carrier, employer, class_code, table, policy = setup_rated_policy(
        payroll_dollars=payroll_dollars,
        employer_overrides=employer_overrides,
        **policy_kwargs,
    )
    report = create_report_for_policy(
        policy,
        carrier,
        payroll_dollars=payroll_dollars,
        claim_lines=claim_lines,
        payroll_class_code=class_code["code"],
    )
    return bureau, carrier, employer, class_code, table, policy, report


def setup_promulgated_sheet(
    payroll_dollars=100000,
    claim_lines=None,
    employer_overrides=None,
    **policy_kwargs,
):
    """Full lifecycle to a PROMULGATED sheet.

    Returns (bureau, carrier, employer, class_code, table, policy, report, sheet).
    """
    bureau, carrier, employer, class_code, table, policy, report = (
        setup_employer_with_validated_report(
            payroll_dollars=payroll_dollars,
            claim_lines=claim_lines,
            employer_overrides=employer_overrides,
            **policy_kwargs,
        )
    )
    sheet = create_sheet_for_employer(employer["id"])
    sheet = _ok(
        "promulgate_experience_mod_sheet",
        api_client.promulgate_experience_mod_sheet(sheet["id"], ANALYST),
    )
    return bureau, carrier, employer, class_code, table, policy, report, sheet


# ---------------------------------------------------------------------------
# Tier 3: class assignment lifecycle
# ---------------------------------------------------------------------------

def setup_assigned_class_assignment(employer_overrides=None, effective_date="2026-03-01"):
    """Employer + class code + ClassAssignment moved PENDING_INSPECTION -> ASSIGNED.

    Returns (bureau, employer, class_code, assignment).
    """
    bureau = create_bureau()
    employer = create_employer(**(employer_overrides or {}))
    class_code = create_class_code()
    assignment = _ok(
        "create_class_assignment",
        api_client.create_class_assignment(
            create_class_assignment_payload(
                employer_id=employer["id"],
                class_code_id=class_code["id"],
                effective_date=effective_date,
            ),
            ANALYST,
        ),
    )
    assignment = _ok(
        "assign_class_assignment",
        api_client.assign_class_assignment(assignment["id"], ANALYST),
    )
    return bureau, employer, class_code, assignment


def file_dispute(assignment, employer, reason="WRONG_CLASS"):
    """File a dispute on an assignment as the employer's representative."""
    return _ok(
        "create_class_assignment_dispute",
        api_client.create_class_assignment_dispute(
            {"class_assignment_id": assignment["id"], "reason": reason},
            make_employer_representative_headers(employer["id"]),
        ),
    )


def file_mod_appeal(sheet, employer, reason="dispute"):
    """File a modification appeal as the employer's representative."""
    return _ok(
        "create_mod_appeal",
        api_client.create_mod_appeal(
            {"mod_sheet_id": sheet["id"], "reason": reason},
            make_employer_representative_headers(employer["id"]),
        ),
    )


def review_mod_appeal(appeal_id):
    return _ok("review_mod_appeal", api_client.review_mod_appeal(appeal_id, ANALYST))


# ---------------------------------------------------------------------------
# Tier 4: assigned risk pool
# ---------------------------------------------------------------------------

def setup_active_enrollment(
    premium_cents=500000,
    quota_cents=10000000,
    effective_date="2026-01-01",
    expiration_date="2026-12-31",
    bureau_overrides=None,
):
    """Bureau + pool carrier + voluntary carrier + employer + ACTIVE enrollment.

    Returns (bureau, pool_carrier, voluntary_carrier, employer, enrollment).
    The enrollment resource returned is the post-assign version.
    """
    bureau = create_bureau(**(bureau_overrides or {}))
    pool_carrier = create_carrier(
        naic_number="10002",
        legal_name="Pool Carrier One",
        assigned_risk_quota_cents=quota_cents,
    )
    voluntary_carrier = create_carrier(
        naic_number="10003",
        legal_name="Voluntary Carrier Two",
        assigned_risk_quota_cents=1000000,
    )
    employer = create_employer(
        fein="75-1000003", legal_name="Capitol Fasteners", state_code="TX"
    )
    enrollment = _ok(
        "create_assigned_risk_enrollment",
        api_client.create_assigned_risk_enrollment(
            create_assigned_risk_enrollment_payload(
                employer_id=employer["id"],
                effective_date=effective_date,
                expiration_date=expiration_date,
                estimated_annual_premium_cents=premium_cents,
            ),
            POOL_ADMIN,
        ),
    )
    enrollment = _ok(
        "assign_assigned_risk_enrollment",
        api_client.assign_assigned_risk_enrollment(
            enrollment["id"], {"carrier_id": pool_carrier["id"]}, POOL_ADMIN
        ),
    )
    return bureau, pool_carrier, voluntary_carrier, employer, enrollment


def file_take_out(enrollment, voluntary_carrier, exit_date="2026-07-01"):
    """File a take-out against an ACTIVE enrollment. Returns the take-out."""
    return _ok(
        "create_assigned_risk_take_out",
        api_client.create_assigned_risk_take_out(
            create_assigned_risk_take_out_payload(
                enrollment_id=enrollment["id"],
                voluntary_carrier_id=voluntary_carrier["id"],
                exit_date=exit_date,
                expected_enrollment_version=enrollment["version"],
            ),
            make_voluntary_carrier_representative_headers(voluntary_carrier["id"]),
        ),
    )
