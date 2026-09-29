"""Composite setup helpers.

The test harness restarts the API server before every test, so every scenario
below is built from an empty database using only endpoints the PRD declares.
All business time is read from the logical clock, so each helper sets the clock
explicitly rather than relying on wall-clock time.

Identity threading matters here.  `CDESponsor` is the one entity-backed role:
its `X-User-ID` is the acting entity's `id`, so every ownership-gated call in
these helpers uses `make_cde_sponsor_headers(cde["id"])`.  The opaque roles
carry stable identifiers so that the values the server stamps
(`investor_user_id`, `sponsor_user_id`, `performed_by_user_id`) can be asserted
and, in the case of the two compliance reviewers, kept distinct.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .assertions import canonical_instant, parse_instant
from .constants import TEST_DEFAULTS
from .factories import (
    agency_report_payload,
    annual_certification_payload,
    annual_test_payload,
    close_investment_fund_payload,
    create_allocation_award_payload,
    create_cba_payload,
    create_cde_payload,
    create_census_tract_payload,
    create_investment_fund_payload,
    create_qalicb_payload,
    create_qei_payload,
    create_qlici_payload,
    cure_payload,
    eligibility_test_payload,
    job_report_payload,
    open_unwind_payload,
    principal_repayment_payload,
    reinvestment_payload,
    sign_allocation_agreement_payload,
)
from .test_users import (
    AGENCY_USER_ID,
    INVESTOR_DELTA_USER_ID,
    REVIEWER_ANNUAL_USER_ID,
    REVIEWER_ELIGIBILITY_USER_ID,
    SPONSOR_DELTA_USER_ID,
    make_agency_headers,
    make_cde_sponsor_headers,
    make_investor_headers,
    make_qalicb_sponsor_headers,
    make_reviewer_headers,
)

SETUP_CLOCK = TEST_DEFAULTS["CLOCK_AT_SETUP"]


# ---------------------------------------------------------------------------
# Instant arithmetic
# ---------------------------------------------------------------------------


def plus_days(instant: str, days: int) -> str:
    """The given instant advanced by whole days, in the PRD's wire format."""
    moment = parse_instant(instant) + timedelta(days=days)
    return canonical_instant(moment.isoformat().replace("+00:00", "Z"))


def plus_years(instant: str, years: int) -> str:
    """The given instant advanced by whole 365-day years."""
    return plus_days(instant, 365 * years)


def compliance_window_start(issued_at: str, compliance_year: int) -> str:
    """`window_start_at` for a compliance year: issued_at + 365 * (year - 1)."""
    return plus_days(issued_at, 365 * (compliance_year - 1))


def compliance_window_end(issued_at: str, compliance_year: int) -> str:
    """`window_end_at` for a compliance year: issued_at + 365 * year."""
    return plus_days(issued_at, 365 * compliance_year)


def option_window_open(issued_at: str) -> str:
    return plus_days(issued_at, 2555)


def option_window_close(issued_at: str) -> str:
    return plus_days(issued_at, 2555 + 90)


# ---------------------------------------------------------------------------
# Scenario container
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """Everything a scenario built and the headers needed to keep acting on it."""

    cde: Optional[dict] = None
    award: Optional[dict] = None
    tract: Optional[dict] = None
    qalicb: Optional[dict] = None
    eligibility_test: Optional[dict] = None
    cba: Optional[dict] = None
    fund: Optional[dict] = None
    qei: Optional[dict] = None
    qlici: Optional[dict] = None
    obligation: Optional[dict] = None
    unwind: Optional[dict] = None
    qlicis: List[dict] = field(default_factory=list)
    annual_tests: List[dict] = field(default_factory=list)
    tracts: List[dict] = field(default_factory=list)
    qalicbs: List[dict] = field(default_factory=list)
    extras: Dict[str, object] = field(default_factory=dict)

    # Identity headers
    agency_headers: dict = field(default_factory=make_agency_headers)
    investor_headers: dict = field(default_factory=make_investor_headers)
    sponsor_headers: dict = field(default_factory=make_qalicb_sponsor_headers)
    eligibility_reviewer_headers: dict = field(
        default_factory=lambda: make_reviewer_headers(REVIEWER_ELIGIBILITY_USER_ID)
    )
    annual_reviewer_headers: dict = field(
        default_factory=lambda: make_reviewer_headers(REVIEWER_ANNUAL_USER_ID)
    )

    @property
    def cde_headers(self) -> dict:
        """Headers for the allocatee itself, built from the live CDE id."""
        assert self.cde is not None, "scenario has no community development entity"
        return make_cde_sponsor_headers(self.cde["id"])

    @property
    def award_version(self) -> int:
        assert self.award is not None, "scenario has no allocation award"
        return self.award["version"]

    @property
    def issued_at(self) -> str:
        assert self.qei is not None, "scenario has no qualified equity investment"
        return self.qei["issued_at"]


# ---------------------------------------------------------------------------
# Primitive setup steps
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str) -> dict:
    """Move the logical clock; this mutates no business record."""
    return get_success_data(api.set_clock(to_iso8601, make_agency_headers()))


def create_cde(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_cde(create_cde_payload(**overrides), make_agency_headers())
    )


def create_award(api: ApiClient, cde: dict, **overrides) -> dict:
    return get_success_data(
        api.create_allocation_award(
            create_allocation_award_payload(cde["id"], **overrides),
            make_agency_headers(),
        )
    )


def sign_award(api: ApiClient, cde: dict, award: dict, **overrides) -> dict:
    return get_success_data(
        api.sign_allocation_agreement(
            award["id"],
            sign_allocation_agreement_payload(**overrides),
            make_cde_sponsor_headers(cde["id"]),
        )
    )


def create_tract(api: ApiClient, **overrides) -> dict:
    return get_success_data(
        api.create_census_tract(
            create_census_tract_payload(**overrides), make_agency_headers()
        )
    )


def create_qalicb(
    api: ApiClient,
    tract: dict,
    sponsor_user_id: str = SPONSOR_DELTA_USER_ID,
    **overrides,
) -> dict:
    return get_success_data(
        api.create_qalicb(
            create_qalicb_payload(tract["id"], **overrides),
            make_qalicb_sponsor_headers(sponsor_user_id),
        )
    )


def run_eligibility_test(
    api: ApiClient,
    qalicb: dict,
    reviewer_user_id: str = REVIEWER_ELIGIBILITY_USER_ID,
    **overrides,
) -> dict:
    return get_success_data(
        api.run_eligibility_test(
            qalicb["id"],
            eligibility_test_payload(**overrides),
            make_reviewer_headers(reviewer_user_id),
        )
    )


def create_cba(api: ApiClient, cde: dict, qalicb: dict, award: dict, **overrides) -> dict:
    return get_success_data(
        api.create_community_benefits_agreement(
            create_cba_payload(qalicb["id"], award["id"], **overrides),
            make_cde_sponsor_headers(cde["id"]),
        )
    )


def create_fund(
    api: ApiClient, investor_user_id: str = INVESTOR_DELTA_USER_ID, **overrides
) -> dict:
    return get_success_data(
        api.create_investment_fund(
            create_investment_fund_payload(**overrides),
            make_investor_headers(investor_user_id),
        )
    )


def close_fund(
    api: ApiClient,
    fund: dict,
    investor_user_id: str = INVESTOR_DELTA_USER_ID,
    **overrides,
) -> dict:
    return get_success_data(
        api.close_investment_fund(
            fund["id"],
            close_investment_fund_payload(**overrides),
            make_investor_headers(investor_user_id),
        )
    )


def issue_qei(
    api: ApiClient, cde: dict, award: dict, fund: dict, **overrides
) -> dict:
    expected_version = overrides.pop(
        "expected_allocation_award_version", award["version"]
    )
    return get_success_data(
        api.create_qei(
            create_qei_payload(award["id"], fund["id"], expected_version, **overrides),
            make_cde_sponsor_headers(cde["id"]),
        )
    )


def deploy_qlici(
    api: ApiClient, cde: dict, qei: dict, qalicb: dict, **overrides
) -> dict:
    return get_success_data(
        api.create_qlici(
            create_qlici_payload(qei["id"], qalicb["id"], **overrides),
            make_cde_sponsor_headers(cde["id"]),
        )
    )


def repay_principal(
    api: ApiClient, cde: dict, qlici: dict, amount_cents: int
) -> dict:
    return get_success_data(
        api.repay_principal(
            qlici["id"],
            principal_repayment_payload(amount_cents),
            make_cde_sponsor_headers(cde["id"]),
        )
    )


def reinvest(
    api: ApiClient,
    cde: dict,
    obligation: dict,
    target_qlici: dict,
    amount_cents: int,
) -> dict:
    return get_success_data(
        api.reinvest(
            obligation["id"],
            reinvestment_payload(target_qlici["id"], amount_cents),
            make_cde_sponsor_headers(cde["id"]),
        )
    )


def run_annual_test(
    api: ApiClient,
    qei: dict,
    compliance_year: int,
    reviewer_user_id: str = REVIEWER_ANNUAL_USER_ID,
) -> dict:
    return get_success_data(
        api.run_annual_test(
            qei["id"],
            annual_test_payload(compliance_year),
            make_reviewer_headers(reviewer_user_id),
        )
    )


def cure_qei(
    api: ApiClient, cde: dict, qei: dict, qalicb: dict, principal_cents: int
) -> dict:
    return get_success_data(
        api.cure_qei(
            qei["id"],
            cure_payload(qalicb["id"], principal_cents),
            make_cde_sponsor_headers(cde["id"]),
        )
    )


def file_job_report(
    api: ApiClient,
    cba: dict,
    period_start_at: str,
    period_end_at: str,
    sponsor_user_id: str = SPONSOR_DELTA_USER_ID,
    **overrides,
) -> dict:
    return get_success_data(
        api.file_job_report(
            cba["id"],
            job_report_payload(period_start_at, period_end_at, **overrides),
            make_qalicb_sponsor_headers(sponsor_user_id),
        )
    )


def certify_community_benefits(
    api: ApiClient,
    cba: dict,
    certification_year: int,
    window_start_at: str,
    window_end_at: str,
    reviewer_user_id: str = REVIEWER_ANNUAL_USER_ID,
) -> dict:
    return get_success_data(
        api.certify_community_benefits(
            cba["id"],
            annual_certification_payload(
                certification_year, window_start_at, window_end_at
            ),
            make_reviewer_headers(reviewer_user_id),
        )
    )


def file_agency_report(api: ApiClient, cde: dict, award: dict, report_year: int) -> dict:
    return get_success_data(
        api.file_agency_report(
            award["id"],
            agency_report_payload(report_year),
            make_cde_sponsor_headers(cde["id"]),
        )
    )


def open_unwind(
    api: ApiClient, cde: dict, qei: dict, call_holder_user_id: str
) -> dict:
    return get_success_data(
        api.open_unwind_transaction(
            qei["id"],
            open_unwind_payload(call_holder_user_id),
            make_cde_sponsor_headers(cde["id"]),
        )
    )


# ---------------------------------------------------------------------------
# Re-reads
# ---------------------------------------------------------------------------


def read_cde(api: ApiClient, cde_id: str) -> dict:
    return get_success_data(api.get_cde(cde_id, make_agency_headers()))


def read_award(api: ApiClient, award_id: str) -> dict:
    return get_success_data(api.get_allocation_award(award_id, make_agency_headers()))


def read_tract(api: ApiClient, tract_id: str) -> dict:
    return get_success_data(api.get_census_tract(tract_id, make_agency_headers()))


def read_qalicb(api: ApiClient, qalicb_id: str) -> dict:
    return get_success_data(api.get_qalicb(qalicb_id, make_agency_headers()))


def read_fund(api: ApiClient, fund_id: str) -> dict:
    return get_success_data(api.get_investment_fund(fund_id, make_agency_headers()))


def read_qei(api: ApiClient, qei_id: str) -> dict:
    return get_success_data(api.get_qei(qei_id, make_agency_headers()))


def read_qlici(api: ApiClient, qlici_id: str) -> dict:
    return get_success_data(api.get_qlici(qlici_id, make_agency_headers()))


def read_obligation(api: ApiClient, obligation_id: str) -> dict:
    return get_success_data(
        api.get_reinvestment_obligation(obligation_id, make_agency_headers())
    )


def read_cba(api: ApiClient, cba_id: str) -> dict:
    return get_success_data(
        api.get_community_benefits_agreement(cba_id, make_agency_headers())
    )


def read_unwind(api: ApiClient, unwind_id: str) -> dict:
    return get_success_data(
        api.get_unwind_transaction(unwind_id, make_agency_headers())
    )


def list_qlicis_of(api: ApiClient, qei_id: str) -> List[dict]:
    body = api.list_qlicis(make_agency_headers(), params={"qei_id": qei_id, "limit": 100})
    return get_success_data(body)


def open_obligation_of(api: ApiClient, qei_id: str) -> dict:
    """The oldest still-open reinvestment obligation of an investment."""
    rows = get_success_data(
        api.list_reinvestment_obligations(
            make_agency_headers(),
            params={"qei_id": qei_id, "status": "OPEN", "limit": 100},
        )
    )
    assert rows, f"expected an OPEN reinvestment obligation on investment {qei_id}"
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------


def setup_active_award(
    api: ApiClient,
    *,
    clock: str = SETUP_CLOCK,
    certification_suffix: int = 101,
    cde_overrides: Optional[dict] = None,
    award_overrides: Optional[dict] = None,
    sign: bool = True,
) -> Scenario:
    """Certify an entity, announce its award and sign the allocation agreement.

    With `sign=False` the award is left in `ANNOUNCED`.
    """
    set_clock(api, clock)
    cde = create_cde(
        api,
        certification_number=f"CDE-2869-{certification_suffix}",
        **(cde_overrides or {}),
    )
    award = create_award(api, cde, **(award_overrides or {}))
    if sign:
        award = sign_award(api, cde, award)
    return Scenario(cde=cde, award=award)


def setup_certified_project_company(
    api: ApiClient,
    scenario: Scenario,
    *,
    tract_overrides: Optional[dict] = None,
    qalicb_overrides: Optional[dict] = None,
    sponsor_user_id: str = SPONSOR_DELTA_USER_ID,
    eligibility_overrides: Optional[dict] = None,
    reviewer_user_id: str = REVIEWER_ELIGIBILITY_USER_ID,
) -> Scenario:
    """Register a tract, register a business inside it and certify the business."""
    tract = create_tract(api, **(tract_overrides or {}))
    qalicb = create_qalicb(
        api, tract, sponsor_user_id=sponsor_user_id, **(qalicb_overrides or {})
    )
    test = run_eligibility_test(
        api, qalicb, reviewer_user_id=reviewer_user_id, **(eligibility_overrides or {})
    )
    scenario.tract = tract
    scenario.qalicb = qalicb
    scenario.eligibility_test = test
    scenario.tracts.append(tract)
    scenario.qalicbs.append(qalicb)
    scenario.qalicb = read_qalicb(api, qalicb["id"])
    return scenario


def setup_funded_fund(
    api: ApiClient,
    scenario: Scenario,
    *,
    investor_user_id: str = INVESTOR_DELTA_USER_ID,
    fund_overrides: Optional[dict] = None,
    close: bool = True,
) -> Scenario:
    """Form the investment fund and, unless told otherwise, close it."""
    fund = create_fund(api, investor_user_id, **(fund_overrides or {}))
    if close:
        overrides = fund_overrides or {}
        fund = close_fund(
            api,
            fund,
            investor_user_id,
            equity_received_cents=overrides.get(
                "equity_contribution_cents",
                TEST_DEFAULTS["FUND_EQUITY_CONTRIBUTION_CENTS"],
            ),
            leverage_received_cents=overrides.get(
                "leverage_loan_principal_cents",
                TEST_DEFAULTS["FUND_LEVERAGE_LOAN_PRINCIPAL_CENTS"],
            ),
        )
    scenario.fund = fund
    return scenario


# ---------------------------------------------------------------------------
# Tier 2 and 3: the whole deal, from certification through deployment
# ---------------------------------------------------------------------------


def setup_issued_investment(
    api: ApiClient,
    *,
    clock: str = SETUP_CLOCK,
    certification_suffix: int = 101,
    cde_overrides: Optional[dict] = None,
    award_overrides: Optional[dict] = None,
    tract_overrides: Optional[dict] = None,
    qalicb_overrides: Optional[dict] = None,
    sponsor_user_id: str = SPONSOR_DELTA_USER_ID,
    eligibility_overrides: Optional[dict] = None,
    with_cba: bool = True,
    cba_overrides: Optional[dict] = None,
    investor_user_id: str = INVESTOR_DELTA_USER_ID,
    fund_overrides: Optional[dict] = None,
    qei_overrides: Optional[dict] = None,
) -> Scenario:
    """Everything up to and including a live qualified equity investment.

    Certify entity -> announce award -> sign agreement -> register tract ->
    register business -> certify business -> bind the benefits agreement ->
    form fund -> close fund -> issue the investment.
    """
    scenario = setup_active_award(
        api,
        clock=clock,
        certification_suffix=certification_suffix,
        cde_overrides=cde_overrides,
        award_overrides=award_overrides,
    )
    setup_certified_project_company(
        api,
        scenario,
        tract_overrides=tract_overrides,
        qalicb_overrides=qalicb_overrides,
        sponsor_user_id=sponsor_user_id,
        eligibility_overrides=eligibility_overrides,
    )
    if with_cba:
        scenario.cba = create_cba(
            api,
            scenario.cde,
            scenario.qalicb,
            scenario.award,
            **(cba_overrides or {}),
        )
    setup_funded_fund(
        api,
        scenario,
        investor_user_id=investor_user_id,
        fund_overrides=fund_overrides,
    )
    scenario.award = read_award(api, scenario.award["id"])
    scenario.qei = issue_qei(
        api,
        scenario.cde,
        scenario.award,
        scenario.fund,
        **(qei_overrides or {}),
    )
    scenario.award = read_award(api, scenario.award["id"])
    scenario.fund = read_fund(api, scenario.fund["id"])
    return scenario


def setup_deployed_investment(
    api: ApiClient,
    *,
    qlici_overrides: Optional[dict] = None,
    **kwargs,
) -> Scenario:
    """A live investment with one sub-allocation already placed.

    By default the placement is 85000000 cents against a net deployable amount
    of 95000000, so the direct-tracing measurement sits at 89.47 percent.
    """
    scenario = setup_issued_investment(api, **kwargs)
    qlici = deploy_qlici(
        api,
        scenario.cde,
        scenario.qei,
        scenario.qalicb,
        **(qlici_overrides or {}),
    )
    scenario.qlici = qlici
    scenario.qlicis.append(qlici)
    scenario.qei = read_qei(api, scenario.qei["id"])
    scenario.award = read_award(api, scenario.award["id"])
    scenario.qalicb = read_qalicb(api, scenario.qalicb["id"])
    return scenario


def add_project_company(
    api: ApiClient,
    scenario: Scenario,
    *,
    tract_overrides: Optional[dict] = None,
    qalicb_overrides: Optional[dict] = None,
    sponsor_user_id: str = SPONSOR_DELTA_USER_ID,
    eligibility_overrides: Optional[dict] = None,
    with_cba: bool = True,
    cba_overrides: Optional[dict] = None,
) -> dict:
    """Register, certify and (optionally) bind a second business to the award."""
    tract = create_tract(api, **(tract_overrides or {}))
    qalicb = create_qalicb(
        api, tract, sponsor_user_id=sponsor_user_id, **(qalicb_overrides or {})
    )
    run_eligibility_test(api, qalicb, **(eligibility_overrides or {}))
    if with_cba:
        create_cba(api, scenario.cde, qalicb, scenario.award, **(cba_overrides or {}))
    qalicb = read_qalicb(api, qalicb["id"])
    scenario.tracts.append(tract)
    scenario.qalicbs.append(qalicb)
    return qalicb


def add_sub_allocation(
    api: ApiClient, scenario: Scenario, qalicb: dict, **qlici_overrides
) -> dict:
    """Place a further sub-allocation from the scenario's investment."""
    qlici = deploy_qlici(api, scenario.cde, scenario.qei, qalicb, **qlici_overrides)
    scenario.qlicis.append(qlici)
    scenario.qei = read_qei(api, scenario.qei["id"])
    scenario.award = read_award(api, scenario.award["id"])
    return qlici


# ---------------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# ---------------------------------------------------------------------------


def advance_compliance_years(
    api: ApiClient,
    scenario: Scenario,
    through_year: int,
    *,
    from_year: int = 1,
    reviewer_user_id: str = REVIEWER_ANNUAL_USER_ID,
) -> List[dict]:
    """Run the annual test for each year in turn, moving the clock to each window end.

    The clock lands on `issued_at` advanced by 365 days times the year, which is
    that year's `window_end_at`.
    """
    issued_at = scenario.qei["issued_at"]
    tests = []
    for year in range(from_year, through_year + 1):
        set_clock(api, compliance_window_end(issued_at, year))
        tests.append(run_annual_test(api, scenario.qei, year, reviewer_user_id))
    scenario.annual_tests.extend(tests)
    scenario.qei = read_qei(api, scenario.qei["id"])
    scenario.award = read_award(api, scenario.award["id"])
    return tests


def setup_at_risk_investment(
    api: ApiClient,
    *,
    principal_cents: int = 30_000_000,
    certification_suffix: int = 101,
    **kwargs,
) -> Scenario:
    """An investment that failed its first annual test and is now `AT_RISK`.

    A placement of 30000000 against a net deployable amount of 95000000 leaves
    the direct-tracing measurement at 31.58 percent, well below the 85.00
    threshold, so the first annual test fails and opens a cure deadline 180 days
    after the clock.
    """
    scenario = setup_deployed_investment(
        api,
        certification_suffix=certification_suffix,
        qlici_overrides={"principal_cents": principal_cents},
        **kwargs,
    )
    advance_compliance_years(api, scenario, 1)
    return scenario


def setup_open_reinvestment_obligation(
    api: ApiClient,
    *,
    repayment_clock: str = "2026-12-01T00:00:00.000Z",
    repay_cents: Optional[int] = None,
    certification_suffix: int = 101,
    **kwargs,
) -> Scenario:
    """A fully repaid sub-allocation, and therefore one `OPEN` obligation.

    Full repayment is the compensating action for deployment: it returns the
    investment's uninvested cash to its exact pre-deployment value and opens a
    reinvestment obligation for the amount just returned.
    """
    scenario = setup_deployed_investment(
        api, certification_suffix=certification_suffix, **kwargs
    )
    amount = (
        repay_cents
        if repay_cents is not None
        else scenario.qlici["outstanding_principal_cents"]
    )
    set_clock(api, repayment_clock)
    repay_principal(api, scenario.cde, scenario.qlici, amount)
    scenario.obligation = open_obligation_of(api, scenario.qei["id"])
    scenario.qei = read_qei(api, scenario.qei["id"])
    scenario.qlici = read_qlici(api, scenario.qlici["id"])
    return scenario


def setup_investment_with_two_sub_allocations(
    api: ApiClient,
    *,
    first_principal_cents: int = 40_000_000,
    second_principal_cents: int = 30_000_000,
    certification_suffix: int = 101,
    **kwargs,
) -> Scenario:
    """One investment funding two certified businesses under the same award."""
    scenario = setup_deployed_investment(
        api,
        certification_suffix=certification_suffix,
        qlici_overrides={"principal_cents": first_principal_cents},
        **kwargs,
    )
    second = add_project_company(
        api,
        scenario,
        tract_overrides={"tract_code": "28049000200"},
        qalicb_overrides={"legal_name": "Echo Works LLC"},
        sponsor_user_id="sponsor-echo",
    )
    add_sub_allocation(
        api, scenario, second, principal_cents=second_principal_cents
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 5: the end of the compliance period
# ---------------------------------------------------------------------------


def setup_completed_compliance_period(
    api: ApiClient, *, certification_suffix: int = 101, **kwargs
) -> Scenario:
    """An investment that has passed all seven annual tests.

    The default placement of 85000000 against a net deployable amount of
    95000000 keeps the direct-tracing measurement at 89.47 percent, so every
    year passes and the investment stays `COMPLIANT`.
    """
    scenario = setup_deployed_investment(
        api, certification_suffix=certification_suffix, **kwargs
    )
    advance_compliance_years(api, scenario, 7)
    return scenario


def setup_open_option_window(
    api: ApiClient,
    *,
    call_holder_user_id: str = SPONSOR_DELTA_USER_ID,
    certification_suffix: int = 101,
    **kwargs,
) -> Scenario:
    """Seven passed annual tests, then an opened and priced option window.

    The clock is left at `option_window_open_at`, which is the investment's
    `issued_at` advanced by 2555 days.
    """
    scenario = setup_completed_compliance_period(
        api, certification_suffix=certification_suffix, **kwargs
    )
    set_clock(api, option_window_open(scenario.qei["issued_at"]))
    scenario.unwind = open_unwind(
        api, scenario.cde, scenario.qei, call_holder_user_id
    )
    scenario.qei = read_qei(api, scenario.qei["id"])
    return scenario


def setup_exercised_put(
    api: ApiClient,
    *,
    investor_user_id: str = INVESTOR_DELTA_USER_ID,
    certification_suffix: int = 101,
    **kwargs,
) -> Scenario:
    """An option window opened and the put exercised by its holder."""
    from .factories import exercise_option_payload

    scenario = setup_open_option_window(
        api,
        investor_user_id=investor_user_id,
        certification_suffix=certification_suffix,
        **kwargs,
    )
    scenario.unwind = get_success_data(
        api.exercise_option(
            scenario.unwind["id"],
            exercise_option_payload("PUT"),
            make_investor_headers(investor_user_id),
        )
    )
    return scenario


# ---------------------------------------------------------------------------
# Multi-entity variants
# ---------------------------------------------------------------------------


def setup_two_awards_one_entity(
    api: ApiClient,
    *,
    clock: str = SETUP_CLOCK,
    certification_suffix: int = 101,
    first_award_overrides: Optional[dict] = None,
    second_award_overrides: Optional[dict] = None,
) -> Scenario:
    """One certified entity holding two signed awards in different award years."""
    scenario = setup_active_award(
        api,
        clock=clock,
        certification_suffix=certification_suffix,
        award_overrides=first_award_overrides,
    )
    second = create_award(
        api,
        scenario.cde,
        award_year=2027,
        **(second_award_overrides or {}),
    )
    second = sign_award(api, scenario.cde, second)
    scenario.extras["second_award"] = second
    scenario.cde = read_cde(api, scenario.cde["id"])
    return scenario


def setup_two_entities(
    api: ApiClient,
    *,
    clock: str = SETUP_CLOCK,
    first_suffix: int = 101,
    second_suffix: int = 102,
) -> Scenario:
    """Two certified entities, each holding one signed award of its own."""
    scenario = setup_active_award(
        api, clock=clock, certification_suffix=first_suffix
    )
    other_cde = create_cde(
        api,
        legal_name="Bayou Delta CDE",
        certification_number=f"CDE-2869-{second_suffix}",
    )
    other_award = create_award(api, other_cde)
    other_award = sign_award(api, other_cde, other_award)
    scenario.extras["other_cde"] = other_cde
    scenario.extras["other_award"] = other_award
    return scenario


def setup_severe_and_moderate_tracts(api: ApiClient) -> Scenario:
    """Two registered tracts: one in the `SEVERE` tier and one in `MODERATE`."""
    set_clock(api, SETUP_CLOCK)
    severe = create_tract(
        api,
        tract_code="28049000100",
        poverty_rate_pct=32.00,
        mfi_ratio_pct=55.00,
        unemployment_ratio=1.80,
    )
    moderate = create_tract(
        api,
        tract_code="28049000200",
        poverty_rate_pct=22.00,
        mfi_ratio_pct=78.00,
        unemployment_ratio=1.10,
    )
    scenario = Scenario()
    scenario.tracts = [severe, moderate]
    scenario.tract = severe
    scenario.extras["severe_tract"] = severe
    scenario.extras["moderate_tract"] = moderate
    return scenario
