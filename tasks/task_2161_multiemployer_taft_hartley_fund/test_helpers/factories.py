"""Payload factories — one per resource, carrying only client-supplied fields."""

from .constants import TEST_DEFAULTS as D


def _merged(base: dict, overrides: dict) -> dict:
    if overrides:
        base = dict(base)
        base.update(overrides)
    return base


def create_fund_payload(**overrides) -> dict:
    return _merged(
        {
            "name": D["FUND_NAME"],
            "ein": D["FUND_EIN"],
            "interest_rate_annual_bps": D["INTEREST_RATE_ANNUAL_BPS"],
            "ld_rate_bps": D["LD_RATE_BPS"],
            "ld_floor_cents": D["LD_FLOOR_CENTS"],
            "grace_days": D["GRACE_DAYS"],
            "hours_per_coverage_month": D["HOURS_PER_COVERAGE_MONTH"],
            "bank_cap_hours": D["BANK_CAP_HOURS"],
            "max_advance_coverage_months": D["MAX_ADVANCE_COVERAGE_MONTHS"],
            "eligibility_lag_months": D["ELIGIBILITY_LAG_MONTHS"],
            "accrual_method": D["ACCRUAL_METHOD"],
            "pool_prior_year_contributions_cents": list(
                D["POOL_PRIOR_YEAR_CONTRIBUTIONS_CENTS"]
            ),
            "total_uvb_cents": D["TOTAL_UVB_CENTS"],
        },
        overrides,
    )


def create_sister_fund_payload(**overrides) -> dict:
    return create_fund_payload(
        **_merged(
            {
                "name": D["SISTER_FUND_NAME"],
                "ein": D["SISTER_FUND_EIN"],
                "fund_role": "SISTER",
                "pool_prior_year_contributions_cents": [0, 0, 0, 0, 0],
            },
            overrides,
        )
    )


def create_employer_payload(fund_id: str, **overrides) -> dict:
    return _merged(
        {
            "fund_id": fund_id,
            "legal_name": D["EMPLOYER_NAME"],
            "ein": D["EMPLOYER_EIN"],
            "contribution_rate_millicents_per_hour": D[
                "CONTRIBUTION_RATE_MILLICENTS_PER_HOUR"
            ],
            "prior_year_contributions_cents": list(
                D["PRIOR_YEAR_CONTRIBUTIONS_CENTS"]
            ),
            "prior_year_base_units": list(D["PRIOR_YEAR_BASE_UNITS"]),
        },
        overrides,
    )


def create_participant_payload(fund_id: str, **overrides) -> dict:
    return _merged(
        {
            "fund_id": fund_id,
            "full_name": D["PARTICIPANT_NAME"],
            "ssn_last4": D["PARTICIPANT_SSN_LAST4"],
        },
        overrides,
    )


def create_trustee_payload(fund_id: str, appointing_party: str, **overrides) -> dict:
    return _merged(
        {
            "fund_id": fund_id,
            "full_name": f"{appointing_party.title()} Trustee",
            "appointing_party": appointing_party,
            "term_expires_on": D["TERM_EXPIRES_ON"],
        },
        overrides,
    )


def contribution_line_payload(
    participant_id: str,
    hours: float,
    gross_wages_cents: int = 400_000,
    work_classification: str = "JOURNEYMAN",
) -> dict:
    return {
        "participant_id": participant_id,
        "hours": hours,
        "gross_wages_cents": gross_wages_cents,
        "work_classification": work_classification,
    }


def create_contribution_report_payload(
    employer_id: str,
    work_period: str,
    expected_employer_version: int,
    lines: list,
    **overrides,
) -> dict:
    return _merged(
        {
            "employer_id": employer_id,
            "work_period": work_period,
            "expected_employer_version": expected_employer_version,
            "lines": lines,
        },
        overrides,
    )


def create_payroll_audit_payload(
    employer_id: str, period_start_month: str, period_end_month: str, **overrides
) -> dict:
    return _merged(
        {
            "employer_id": employer_id,
            "period_start_month": period_start_month,
            "period_end_month": period_end_month,
        },
        overrides,
    )


def audit_finding_payload(
    participant_id: str, work_period: str, unreported_hours: float
) -> dict:
    return {
        "participant_id": participant_id,
        "work_period": work_period,
        "unreported_hours": unreported_hours,
    }


def create_withdrawal_assessment_payload(
    employer_id: str,
    expected_fund_version: int,
    method: str = "PRESUMPTIVE",
    withdrawal_date: str = "2026-03-31",
    **overrides,
) -> dict:
    return _merged(
        {
            "employer_id": employer_id,
            "withdrawal_date": withdrawal_date,
            "method": method,
            "expected_fund_version": expected_fund_version,
        },
        overrides,
    )


def create_board_motion_payload(
    fund_id: str, subject_type: str, subject_ref_id: str, **overrides
) -> dict:
    return _merged(
        {
            "fund_id": fund_id,
            "subject_type": subject_type,
            "subject_ref_id": subject_ref_id,
        },
        overrides,
    )


def create_motion_vote_payload(motion_id: str, position: str, **overrides) -> dict:
    return _merged({"motion_id": motion_id, "position": position}, overrides)


def create_reciprocity_transfer_payload(
    participant_id: str,
    sister_fund_id: str,
    transfer_type: str,
    work_period: str,
    hours: float,
    amount_cents: int,
    **overrides,
) -> dict:
    return _merged(
        {
            "participant_id": participant_id,
            "sister_fund_id": sister_fund_id,
            "transfer_type": transfer_type,
            "work_period": work_period,
            "hours": hours,
            "amount_cents": amount_cents,
        },
        overrides,
    )
