"""
Composite setup builders for the Child Support Enforcement API test suite.

The harness restarts the service before every individual test, so every test
starts against an empty store and must build all of its own preconditions
through the API. These builders do exactly that, in tiers: the logical clock
first, then the two parties, then the case, then the paternity question, then
the order and its guideline worksheet, then the ledger, the employer registry
and the withholding channel, and finally the enforcement, interstate and
compromise postures that later tests need to start from.

Every builder drives the same public endpoints a caller would use, uses the
lenient ``get_success_data`` validator so that a setup failure reports the
error id it hit, and threads the real entity identifier into the headers of
every ownership-gated call it makes.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import CLOCK_START, CLOCK_START_DATE, HOME_STATE_CODE
from .test_users import (
    CASE_WORKER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    INTERSTATE_LIAISON_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    SUPERVISING_ATTORNEY_HEADERS,
    make_case_worker_headers,
    make_employer_agent_headers,
    make_noncustodial_party_headers,
    make_supervising_attorney_headers,
)

#: The guideline figure produced by the canonical income pair below: a custodial
#: income of 200,000 cents and an obligor income of 300,000 cents on a case with
#: two children combine to 500,000 cents, which selects the second band's
#: two-child rate of 0.25 for a basic obligation of 125,000 cents, apportioned
#: at a share ratio of 0.6000 to 75,000 cents.
CANONICAL_CP_INCOME_CENTS = 200000
CANONICAL_NCP_INCOME_CENTS = 300000
CANONICAL_GUIDELINE_CENTS = 75000


@dataclass
class Scenario:
    """Everything a composite builder created, so a test can reach any level."""

    custodial_party: Dict[str, Any] = field(default_factory=dict)
    noncustodial_party: Dict[str, Any] = field(default_factory=dict)
    case: Dict[str, Any] = field(default_factory=dict)
    paternity_action: Dict[str, Any] = field(default_factory=dict)
    order: Dict[str, Any] = field(default_factory=dict)
    employer: Dict[str, Any] = field(default_factory=dict)
    withholding_order: Dict[str, Any] = field(default_factory=dict)
    charges: List[Dict[str, Any]] = field(default_factory=list)
    payments: List[Dict[str, Any]] = field(default_factory=list)
    enforcement_action: Dict[str, Any] = field(default_factory=dict)
    interstate_referral: Dict[str, Any] = field(default_factory=dict)
    compromise_offer: Dict[str, Any] = field(default_factory=dict)
    modification_review: Dict[str, Any] = field(default_factory=dict)

    # -- convenience accessors ------------------------------------------
    @property
    def cp_id(self) -> str:
        return self.custodial_party["id"]

    @property
    def ncp_id(self) -> str:
        return self.noncustodial_party["id"]

    @property
    def case_id(self) -> str:
        return self.case["id"]

    @property
    def order_id(self) -> str:
        return self.order["id"]

    @property
    def employer_id(self) -> str:
        return self.employer["id"]

    @property
    def iwo_id(self) -> str:
        return self.withholding_order["id"]

    @property
    def ncp_headers(self) -> Dict[str, str]:
        """Headers for the obligor of this case, carrying its participant id."""
        return make_noncustodial_party_headers(self.ncp_id)

    @property
    def employer_headers(self) -> Dict[str, str]:
        """Headers for the payroll contact of this employer, carrying its id."""
        return make_employer_agent_headers(self.employer_id)

    # -- refreshers -----------------------------------------------------
    def reload_case(self) -> Dict[str, Any]:
        self.case = read_case(self.case_id)
        return self.case

    def reload_order(self) -> Dict[str, Any]:
        self.order = read_order(self.order_id)
        return self.order

    def reload_noncustodial_party(self) -> Dict[str, Any]:
        self.noncustodial_party = read_participant(self.ncp_id)
        return self.noncustodial_party

    def reload_employer(self) -> Dict[str, Any]:
        self.employer = read_employer(self.employer_id)
        return self.employer

    def reload_withholding_order(self) -> Dict[str, Any]:
        self.withholding_order = read_withholding_order(self.iwo_id)
        return self.withholding_order


# ===========================================================================
# Tier 0 — the logical clock
# ===========================================================================


def set_clock(to_iso8601: str) -> None:
    """Set the logical clock; only a `ProgramAdmin` may do this."""
    get_success_data(api_client.set_clock(f.clock_payload(to_iso8601), PROGRAM_ADMIN_HEADERS))


def reset_clock() -> None:
    """Pin the clock at the fixed instant the service starts from."""
    set_clock(CLOCK_START)


# ===========================================================================
# Tier 1 — plain reads
# ===========================================================================


def read_participant(participant_id: str) -> Dict[str, Any]:
    """Read a participant, which recomputes both risk variants."""
    return get_success_data(api_client.get_participant(participant_id, CASE_WORKER_HEADERS))


def read_case(case_id: str) -> Dict[str, Any]:
    """Read a case, which recomputes every derived money field."""
    return get_success_data(api_client.get_case(case_id, CASE_WORKER_HEADERS))


def read_order(order_id: str) -> Dict[str, Any]:
    """Read a support order."""
    return get_success_data(api_client.get_order(order_id, CASE_WORKER_HEADERS))


def read_employer(employer_id: str) -> Dict[str, Any]:
    """Read an employer."""
    return get_success_data(api_client.get_employer(employer_id, PROGRAM_ADMIN_HEADERS))


def read_withholding_order(iwo_id: str) -> Dict[str, Any]:
    """Read a withholding order."""
    return get_success_data(api_client.get_withholding_order(iwo_id, CASE_WORKER_HEADERS))


def read_charge(charge_id: str) -> Dict[str, Any]:
    """Read an obligation charge with its accrued interest."""
    return get_success_data(api_client.get_charge(charge_id, FINANCE_OFFICER_HEADERS))


def read_payment(payment_id: str) -> Dict[str, Any]:
    """Read a payment with its full allocation breakdown."""
    return get_success_data(api_client.get_payment(payment_id, FINANCE_OFFICER_HEADERS))


def read_paternity_action(paternity_action_id: str) -> Dict[str, Any]:
    """Read a paternity action."""
    return get_success_data(
        api_client.get_paternity_action(paternity_action_id, CASE_WORKER_HEADERS)
    )


def read_enforcement_action(enforcement_action_id: str) -> Dict[str, Any]:
    """Read an enforcement action."""
    return get_success_data(
        api_client.get_enforcement_action(enforcement_action_id, CASE_WORKER_HEADERS)
    )


def read_interstate_referral(interstate_referral_id: str) -> Dict[str, Any]:
    """Read an interstate referral."""
    return get_success_data(
        api_client.get_interstate_referral(interstate_referral_id, INTERSTATE_LIAISON_HEADERS)
    )


def read_compromise_offer(compromise_offer_id: str) -> Dict[str, Any]:
    """Read a compromise offer."""
    return get_success_data(
        api_client.get_compromise_offer(compromise_offer_id, FINANCE_OFFICER_HEADERS)
    )


def read_modification_review(modification_review_id: str) -> Dict[str, Any]:
    """Read a modification review."""
    return get_success_data(
        api_client.get_modification_review(modification_review_id, CASE_WORKER_HEADERS)
    )


def read_ledger(case_id: str, as_of_date: Optional[str] = None) -> Dict[str, Any]:
    """Read the computed case ledger, optionally valued at a past or future date."""
    params = {"as_of_date": as_of_date} if as_of_date else None
    return get_success_data(
        api_client.get_case_ledger(case_id, FINANCE_OFFICER_HEADERS, params)
    )


# ===========================================================================
# Tier 2 — participants
# ===========================================================================


def create_custodial_party(**overrides: Any) -> Dict[str, Any]:
    """Register the custodial party with a verified income figure."""
    return get_success_data(
        api_client.create_participant(f.custodial_party_payload(**overrides), CASE_WORKER_HEADERS)
    )


def create_noncustodial_party(**overrides: Any) -> Dict[str, Any]:
    """Register the obligor with a verified income figure."""
    return get_success_data(
        api_client.create_participant(
            f.noncustodial_party_payload(**overrides), CASE_WORKER_HEADERS
        )
    )


def record_locate_outcome(participant_id: str, outcome: str = "LOCATED", **overrides: Any) -> Dict[str, Any]:
    """Record the outcome of locate services on a participant."""
    return get_success_data(
        api_client.record_locate_result(
            participant_id, f.locate_result_payload(outcome, **overrides), CASE_WORKER_HEADERS
        )
    )


def patch_income(
    participant_id: str,
    monthly_gross_income_cents: int,
    income_verification_source: str = "VERIFIED_WAGE_RECORD",
    **overrides: Any,
) -> Dict[str, Any]:
    """Record a new income figure and its verification provenance."""
    return get_success_data(
        api_client.patch_participant_income(
            participant_id,
            f.income_patch_payload(
                monthly_gross_income_cents, income_verification_source, **overrides
            ),
            CASE_WORKER_HEADERS,
        )
    )


def create_located_parties(
    cp_overrides: Optional[Dict[str, Any]] = None,
    ncp_overrides: Optional[Dict[str, Any]] = None,
    locate_outcome: Optional[str] = "LOCATED",
) -> Dict[str, Dict[str, Any]]:
    """
    Register both parties and, unless told otherwise, record the obligor as
    `LOCATED` so that establishment work may begin.
    """
    cp = create_custodial_party(**(cp_overrides or {}))
    ncp = create_noncustodial_party(**(ncp_overrides or {}))
    if locate_outcome is not None:
        ncp = record_locate_outcome(ncp["id"], locate_outcome)
    return {"custodial_party": cp, "noncustodial_party": ncp}


# ===========================================================================
# Tier 3 — the case
# ===========================================================================


def open_case(
    custodial_party_id: str,
    noncustodial_party_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a IV-D case from a direct application unless told otherwise."""
    return get_success_data(
        api_client.create_case(
            f.case_payload(custodial_party_id, noncustodial_party_id, **overrides),
            CASE_WORKER_HEADERS,
        )
    )


def open_case_with_parties(
    clock: Optional[str] = CLOCK_START,
    cp_overrides: Optional[Dict[str, Any]] = None,
    ncp_overrides: Optional[Dict[str, Any]] = None,
    locate_outcome: Optional[str] = "LOCATED",
    **case_overrides: Any,
) -> Scenario:
    """
    Pin the clock, register both parties, locate the obligor and open the case.

    This is the base every deeper builder starts from.
    """
    if clock is not None:
        set_clock(clock)
    parties = create_located_parties(cp_overrides, ncp_overrides, locate_outcome)
    case = open_case(
        parties["custodial_party"]["id"],
        parties["noncustodial_party"]["id"],
        **case_overrides,
    )
    return Scenario(
        custodial_party=parties["custodial_party"],
        noncustodial_party=parties["noncustodial_party"],
        case=case,
    )


def refer_to_locate(case_id: str, locate_source: str = "FEDERAL_PLS") -> Dict[str, Any]:
    """Refer the obligor to locate services, driving the case into `LOCATE`."""
    return get_success_data(
        api_client.create_locate_referral(
            case_id, f.locate_referral_payload(locate_source), CASE_WORKER_HEADERS
        )
    )


def close_case(case_id: str, closed_reason: str = "CP_REQUEST") -> Dict[str, Any]:
    """Close a case; only a `SupervisingAttorney` may do this."""
    return get_success_data(
        api_client.close_case(
            case_id, f.closure_payload(closed_reason), SUPERVISING_ATTORNEY_HEADERS
        )
    )


def run_accrual(case_id: str) -> Dict[str, Any]:
    """Post interest accrual up to the current logical clock date."""
    return get_success_data(
        api_client.create_accrual_run(case_id, f.accrual_run_payload(), FINANCE_OFFICER_HEADERS)
    )


# ===========================================================================
# Tier 4 — the paternity question
# ===========================================================================


def open_paternity_action(case_id: str, method: str = "PRESUMED_MARITAL") -> Dict[str, Any]:
    """Open the single paternity action of a case."""
    return get_success_data(
        api_client.create_paternity_action(
            case_id, f.paternity_action_payload(method), CASE_WORKER_HEADERS
        )
    )


def sign_acknowledgment(paternity_action_id: str, noncustodial_party_id: str) -> Dict[str, Any]:
    """Record the notarised acknowledgment, opening the rescission window."""
    return get_success_data(
        api_client.record_acknowledgment(
            paternity_action_id,
            f.acknowledgment_payload(noncustodial_party_id),
            CASE_WORKER_HEADERS,
        )
    )


def rescind_acknowledgment(paternity_action_id: str, noncustodial_party_id: str) -> Dict[str, Any]:
    """Rescind the acknowledgment as the obligor, whose id the headers carry."""
    return get_success_data(
        api_client.rescind_acknowledgment(
            paternity_action_id,
            f.rescission_payload(),
            make_noncustodial_party_headers(noncustodial_party_id),
        )
    )


def order_genetic_test(paternity_action_id: str, collection_appointment_at: str) -> Dict[str, Any]:
    """Order genetic testing and schedule specimen collection."""
    return get_success_data(
        api_client.order_genetic_test(
            paternity_action_id,
            f.genetic_test_order_payload(collection_appointment_at),
            SUPERVISING_ATTORNEY_HEADERS,
        )
    )


def collect_specimen(paternity_action_id: str, chain_of_custody_ok: bool = True) -> Dict[str, Any]:
    """Record a specimen collection attempt and its chain-of-custody outcome."""
    return get_success_data(
        api_client.record_specimen_collection(
            paternity_action_id,
            f.specimen_collection_payload(chain_of_custody_ok),
            CASE_WORKER_HEADERS,
        )
    )


def record_genetic_result(paternity_action_id: str, genetic_probability_pct: float) -> Dict[str, Any]:
    """Record the probability of parentage, closing the paternity question."""
    return get_success_data(
        api_client.record_genetic_result(
            paternity_action_id,
            f.genetic_result_payload(genetic_probability_pct),
            SUPERVISING_ATTORNEY_HEADERS,
        )
    )


def establish_paternity_by_genetic_test(
    scenario: Scenario,
    appointment_at: str,
    collection_clock: str,
    genetic_probability_pct: float = 99.5,
) -> Scenario:
    """
    Walk the genetic track end to end: order the test, advance the clock to the
    appointment, collect a clean specimen and record the laboratory result.
    """
    action = open_paternity_action(scenario.case_id, "GENETIC_TEST")
    order_genetic_test(action["id"], appointment_at)
    set_clock(collection_clock)
    collect_specimen(action["id"], True)
    scenario.paternity_action = record_genetic_result(action["id"], genetic_probability_pct)
    scenario.reload_case()
    return scenario


# ===========================================================================
# Tier 5 — the support order
# ===========================================================================


def draft_order(case_id: str, **overrides: Any) -> Dict[str, Any]:
    """Draft a support order on a case whose paternity question is settled."""
    return get_success_data(
        api_client.create_order(case_id, f.order_payload(**overrides), CASE_WORKER_HEADERS)
    )


def calculate_order(order_id: str, drafted_by_user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Run the guideline worksheet. The caller's identifier is stamped as
    ``drafted_by_user_id``, which is the segregation-of-duties anchor.
    """
    headers = (
        make_case_worker_headers(drafted_by_user_id)
        if drafted_by_user_id
        else CASE_WORKER_HEADERS
    )
    return get_success_data(
        api_client.run_guideline_calculation(order_id, f.guideline_calculation_payload(), headers)
    )


def enter_order(order_id: str, decided_by_user_id: Optional[str] = None) -> Dict[str, Any]:
    """Enter the order at the guideline amount; a `SupervisingAttorney` act."""
    headers = (
        make_supervising_attorney_headers(decided_by_user_id)
        if decided_by_user_id
        else SUPERVISING_ATTORNEY_HEADERS
    )
    return get_success_data(api_client.enter_order(order_id, f.entry_payload(), headers))


def request_deviation(
    order_id: str, deviation_requested_cents: int, deviation_reason: str = "HARDSHIP"
) -> Dict[str, Any]:
    """Request a deviation from the guideline amount."""
    return get_success_data(
        api_client.request_deviation(
            order_id,
            f.deviation_request_payload(deviation_requested_cents, deviation_reason),
            CASE_WORKER_HEADERS,
        )
    )


def decide_deviation(
    order_id: str, decision: str, decided_by_user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Decide a requested deviation as an attorney other than the drafter."""
    headers = (
        make_supervising_attorney_headers(decided_by_user_id)
        if decided_by_user_id
        else SUPERVISING_ATTORNEY_HEADERS
    )
    return get_success_data(
        api_client.decide_deviation_findings(
            order_id, f.deviation_findings_payload(decision), headers
        )
    )


def vacate_order(order_id: str, vacate_reason: str = "CLERICAL_ERROR") -> Dict[str, Any]:
    """Vacate an order and reverse everything it produced."""
    return get_success_data(
        api_client.vacate_order(
            order_id, f.vacatur_payload(vacate_reason), SUPERVISING_ATTORNEY_HEADERS
        )
    )


def entered_order_on_case(case_id: str, **order_overrides: Any) -> Dict[str, Any]:
    """Draft, calculate and enter one order on an already-established case."""
    order = draft_order(case_id, **order_overrides)
    calculate_order(order["id"])
    return enter_order(order["id"])


def case_with_entered_order(
    clock: Optional[str] = CLOCK_START,
    cp_overrides: Optional[Dict[str, Any]] = None,
    ncp_overrides: Optional[Dict[str, Any]] = None,
    case_overrides: Optional[Dict[str, Any]] = None,
    order_overrides: Optional[Dict[str, Any]] = None,
    paternity_method: str = "PRESUMED_MARITAL",
) -> Scenario:
    """
    The canonical enforcement-ready starting point.

    Pins the clock, registers and locates both parties, opens the case, settles
    parentage on the marital presumption, then drafts, calculates and enters one
    `CURRENT_SUPPORT` order. With the default incomes the entered order carries
    a monthly obligation of 75,000 cents.
    """
    scenario = open_case_with_parties(
        clock=clock,
        cp_overrides=cp_overrides,
        ncp_overrides=ncp_overrides,
        **(case_overrides or {}),
    )
    scenario.paternity_action = open_paternity_action(scenario.case_id, paternity_method)
    scenario.order = entered_order_on_case(scenario.case_id, **(order_overrides or {}))
    scenario.reload_case()
    return scenario


# ===========================================================================
# Tier 6 — the ledger
# ===========================================================================


def post_charge(order_id: str, **overrides: Any) -> Dict[str, Any]:
    """Post an obligation charge against an entered order."""
    return get_success_data(
        api_client.post_charge(order_id, f.charge_payload(**overrides), FINANCE_OFFICER_HEADERS)
    )


def post_monthly_charge(order_id: str, month_start: str, **overrides: Any) -> Dict[str, Any]:
    """Post a charge covering exactly one calendar month."""
    return get_success_data(
        api_client.post_charge(
            order_id, f.monthly_charge_payload(month_start, **overrides), FINANCE_OFFICER_HEADERS
        )
    )


def post_monthly_charges(
    order_id: str, month_starts: List[str], **overrides: Any
) -> List[Dict[str, Any]]:
    """Post one monthly charge per month start, oldest first."""
    return [post_monthly_charge(order_id, start, **overrides) for start in month_starts]


def void_charge(charge_id: str) -> Dict[str, Any]:
    """Void an unpaid charge posted in error."""
    return get_success_data(
        api_client.void_charge(charge_id, f.voidance_payload(), FINANCE_OFFICER_HEADERS)
    )


def post_payment(case_id: str, amount_cents: int, source: str = "DIRECT_PAY", **overrides: Any) -> Dict[str, Any]:
    """Post a non-withholding collection on the case."""
    return get_success_data(
        api_client.post_payment(
            case_id, f.payment_payload(amount_cents, source, **overrides), FINANCE_OFFICER_HEADERS
        )
    )


def case_with_charges(
    month_starts: Optional[List[str]] = None,
    clock: Optional[str] = CLOCK_START,
    charge_overrides: Optional[Dict[str, Any]] = None,
    **scenario_kwargs: Any,
) -> Scenario:
    """
    An entered order carrying one monthly `CURRENT_SUPPORT` charge per month
    start. With the default incomes each charge defaults to 75,000 cents.
    """
    scenario = case_with_entered_order(clock=clock, **scenario_kwargs)
    starts = month_starts if month_starts is not None else [CLOCK_START_DATE]
    scenario.charges = post_monthly_charges(
        scenario.order_id, starts, **(charge_overrides or {})
    )
    scenario.reload_case()
    scenario.reload_order()
    return scenario


# ===========================================================================
# Tier 7 — the employer registry and the withholding channel
# ===========================================================================


def create_employer(state_code: str = HOME_STATE_CODE, **overrides: Any) -> Dict[str, Any]:
    """Register an employer; only a `ProgramAdmin` operates the registry."""
    return get_success_data(
        api_client.create_employer(
            f.employer_payload(state_code=state_code, **overrides), PROGRAM_ADMIN_HEADERS
        )
    )


def issue_withholding_order(
    order_id: str,
    employer_id: str,
    reported_disposable_income_cents: Optional[int] = None,
    expected_order_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Issue a withholding order, reading the parent order's current ``version``
    for the concurrency guard unless the caller supplies one.
    """
    version = (
        expected_order_version
        if expected_order_version is not None
        else read_order(order_id)["version"]
    )
    return get_success_data(
        api_client.issue_withholding_order(
            order_id,
            f.withholding_order_payload(
                employer_id, version, reported_disposable_income_cents, **overrides
            ),
            CASE_WORKER_HEADERS,
        )
    )


def serve_withholding_order(iwo_id: str) -> Dict[str, Any]:
    """Record service of the withholding order, starting the implementation clock."""
    return get_success_data(
        api_client.serve_withholding_order(iwo_id, f.service_payload(), CASE_WORKER_HEADERS)
    )


def amend_withholding_order(iwo_id: str, reported_disposable_income_cents: int) -> Dict[str, Any]:
    """Amend the reported disposable income and recompute the cap in place."""
    return get_success_data(
        api_client.amend_withholding_order(
            iwo_id,
            f.amendment_payload(reported_disposable_income_cents),
            CASE_WORKER_HEADERS,
        )
    )


def post_remittance(iwo_id: str, employer_id: str, amount_cents: int) -> Dict[str, Any]:
    """Post an employer remittance, presenting the employer's own id in the headers."""
    return get_success_data(
        api_client.post_remittance(
            iwo_id,
            f.remittance_payload(amount_cents),
            make_employer_agent_headers(employer_id),
        )
    )


def declare_lapse(iwo_id: str) -> Dict[str, Any]:
    """Record a missed remittance period; a `FinanceOfficer` act."""
    return get_success_data(
        api_client.declare_remittance_lapse(iwo_id, f.lapse_payload(), FINANCE_OFFICER_HEADERS)
    )


def terminate_withholding_order(
    iwo_id: str, terminated_reason: str = "EMPLOYMENT_ENDED"
) -> Dict[str, Any]:
    """Terminate a withholding order."""
    return get_success_data(
        api_client.terminate_withholding_order(
            iwo_id, f.iwo_termination_payload(terminated_reason), CASE_WORKER_HEADERS
        )
    )


def case_with_served_withholding_order(
    employer_state_code: str = HOME_STATE_CODE,
    reported_disposable_income_cents: Optional[int] = None,
    employer_overrides: Optional[Dict[str, Any]] = None,
    month_starts: Optional[List[str]] = None,
    **scenario_kwargs: Any,
) -> Scenario:
    """
    An entered order with its charges posted, an employer registered, and one
    withholding order issued and served on that employer.
    """
    scenario = case_with_charges(month_starts=month_starts, **scenario_kwargs)
    scenario.employer = create_employer(
        state_code=employer_state_code, **(employer_overrides or {})
    )
    scenario.withholding_order = issue_withholding_order(
        scenario.order_id,
        scenario.employer_id,
        reported_disposable_income_cents,
    )
    scenario.withholding_order = serve_withholding_order(scenario.iwo_id)
    scenario.reload_case()
    scenario.reload_employer()
    scenario.reload_order()
    return scenario


# ===========================================================================
# Tier 8 — enforcement remedies
# ===========================================================================


def propose_enforcement_action(
    case_id: str, action_type: str = "LICENSE_SUSPENSION", proposed_by_user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Propose an enforcement remedy; the caller's id becomes the audit anchor."""
    headers = (
        make_case_worker_headers(proposed_by_user_id)
        if proposed_by_user_id
        else CASE_WORKER_HEADERS
    )
    return get_success_data(
        api_client.propose_enforcement_action(
            case_id, f.enforcement_action_payload(action_type), headers
        )
    )


def send_enforcement_notice(enforcement_action_id: str) -> Dict[str, Any]:
    """Send the pre-deprivation notice, opening the contest window."""
    return get_success_data(
        api_client.send_enforcement_notice(
            enforcement_action_id, f.notice_payload(), CASE_WORKER_HEADERS
        )
    )


def contest_enforcement_action(
    enforcement_action_id: str,
    noncustodial_party_id: str,
    contest_grounds: str = "MISTAKE_OF_FACT",
) -> Dict[str, Any]:
    """Contest the remedy as the obligor, whose participant id the headers carry."""
    return get_success_data(
        api_client.contest_enforcement_action(
            enforcement_action_id,
            f.contest_payload(contest_grounds),
            make_noncustodial_party_headers(noncustodial_party_id),
        )
    )


def decide_enforcement_review(
    enforcement_action_id: str,
    review_decision: str = "UPHOLD",
    decided_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Decide a contested action as an attorney other than the proposer."""
    headers = (
        make_supervising_attorney_headers(decided_by_user_id)
        if decided_by_user_id
        else SUPERVISING_ATTORNEY_HEADERS
    )
    return get_success_data(
        api_client.decide_enforcement_review(
            enforcement_action_id, f.review_decision_payload(review_decision), headers
        )
    )


def activate_enforcement_action(enforcement_action_id: str) -> Dict[str, Any]:
    """Activate an uncontested remedy once the contest window has fully elapsed."""
    return get_success_data(
        api_client.activate_enforcement_action(
            enforcement_action_id, f.activation_payload(), CASE_WORKER_HEADERS
        )
    )


def release_enforcement_action(
    enforcement_action_id: str, release_reason: str = "PLAN_COMPLIANT"
) -> Dict[str, Any]:
    """Release an active remedy."""
    return get_success_data(
        api_client.release_enforcement_action(
            enforcement_action_id, f.release_payload(release_reason), SUPERVISING_ATTORNEY_HEADERS
        )
    )


def activate_remedy_uncontested(
    case_id: str,
    action_type: str,
    notice_clock: Optional[str] = None,
    proposed_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Propose a remedy, send notice, advance the clock strictly past the contest
    deadline, and activate it on the uncontested branch.
    """
    action = propose_enforcement_action(case_id, action_type, proposed_by_user_id)
    action = send_enforcement_notice(action["id"])
    deadline = action["contest_deadline_at"]
    set_clock(notice_clock or f.shift_instant(deadline, days=1))
    return activate_enforcement_action(action["id"])


# ===========================================================================
# Tier 9 — interstate referrals
# ===========================================================================


def draft_interstate_referral(case_id: str, **overrides: Any) -> Dict[str, Any]:
    """Draft a UIFSA transmittal; an `InterstateLiaison` act."""
    return get_success_data(
        api_client.create_interstate_referral(
            case_id, f.interstate_referral_payload(**overrides), INTERSTATE_LIAISON_HEADERS
        )
    )


def transmit_referral(interstate_referral_id: str) -> Dict[str, Any]:
    """Transmit an initiating referral and start the acknowledgment clock."""
    return get_success_data(
        api_client.transmit_referral(
            interstate_referral_id, f.transmittal_payload(), INTERSTATE_LIAISON_HEADERS
        )
    )


def register_referral(interstate_referral_id: str) -> Dict[str, Any]:
    """Register the referral and determine the controlling order."""
    return get_success_data(
        api_client.register_referral(
            interstate_referral_id, f.registration_payload(), INTERSTATE_LIAISON_HEADERS
        )
    )


def return_referral(
    interstate_referral_id: str, returned_reason: str = "NO_JURISDICTION"
) -> Dict[str, Any]:
    """Return the transmittal unworked and drop the interstate posture."""
    return get_success_data(
        api_client.return_referral(
            interstate_referral_id,
            f.referral_return_payload(returned_reason),
            INTERSTATE_LIAISON_HEADERS,
        )
    )


def register_responding_referral(
    case_id: str,
    other_state_code: str,
    child_home_state_code: str = HOME_STATE_CODE,
    transmittal_type: str = "ENFORCEMENT",
) -> Dict[str, Any]:
    """
    Draft a responding referral naming ``other_state_code`` and register it
    directly, which is the responding-state path out of `DRAFT`.
    """
    referral = draft_interstate_referral(
        case_id,
        direction="RESPONDING",
        other_state_code=other_state_code,
        child_home_state_code=child_home_state_code,
        transmittal_type=transmittal_type,
    )
    return register_referral(referral["id"])


# ===========================================================================
# Tier 10 — modification review
# ===========================================================================


def open_modification_review(
    order_id: str, trigger_type: str = "PARTY_REQUEST"
) -> Dict[str, Any]:
    """Open a modification review on an entered order."""
    return get_success_data(
        api_client.create_modification_review(
            order_id, f.modification_review_payload(trigger_type), CASE_WORKER_HEADERS
        )
    )


def screen_modification_review(modification_review_id: str) -> Dict[str, Any]:
    """Screen the review against the substantial-change test."""
    return get_success_data(
        api_client.screen_modification_review(
            modification_review_id, f.screening_payload(), CASE_WORKER_HEADERS
        )
    )


def supply_review_information(
    modification_review_id: str,
    participant_id: str,
    monthly_gross_income_cents: int,
    income_verification_source: str = "VERIFIED_WAGE_RECORD",
) -> Dict[str, Any]:
    """Supply the income information the screening asked for."""
    return get_success_data(
        api_client.supply_review_information(
            modification_review_id,
            f.review_information_payload(
                participant_id, monthly_gross_income_cents, income_verification_source
            ),
            CASE_WORKER_HEADERS,
        )
    )


def propose_successor_order(modification_review_id: str, effective_date: str) -> Dict[str, Any]:
    """Create the successor order carrying the recalculated guideline amount."""
    return get_success_data(
        api_client.create_proposed_order(
            modification_review_id,
            f.proposed_order_payload(effective_date),
            SUPERVISING_ATTORNEY_HEADERS,
        )
    )


# ===========================================================================
# Tier 11 — arrears compromise
# ===========================================================================


def create_compromise_offer(
    case_id: str,
    installment_count: int = 3,
    expected_case_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Build a compromise offer, reading the case's current ``version`` for the
    concurrency guard unless the caller supplies one.
    """
    version = (
        expected_case_version
        if expected_case_version is not None
        else read_case(case_id)["version"]
    )
    return get_success_data(
        api_client.create_compromise_offer(
            case_id,
            f.compromise_offer_payload(version, installment_count, **overrides),
            FINANCE_OFFICER_HEADERS,
        )
    )


def accept_compromise_offer(
    compromise_offer_id: str, noncustodial_party_id: str
) -> Dict[str, Any]:
    """Accept the offer as the obligor, whose participant id the headers carry."""
    return get_success_data(
        api_client.accept_compromise_offer(
            compromise_offer_id,
            f.offer_acceptance_payload(),
            make_noncustodial_party_headers(noncustodial_party_id),
        )
    )


def declare_compromise_default(compromise_offer_id: str) -> Dict[str, Any]:
    """Declare the plan in default, reinstating the waived interest."""
    return get_success_data(
        api_client.declare_compromise_default(
            compromise_offer_id, f.default_declaration_payload(), FINANCE_OFFICER_HEADERS
        )
    )


def pay_installment(
    case_id: str, compromise_offer_id: str, amount_cents: int
) -> Dict[str, Any]:
    """Post a compromise installment payment referencing its offer."""
    return get_success_data(
        api_client.post_payment(
            case_id,
            f.installment_payment_payload(amount_cents, compromise_offer_id),
            FINANCE_OFFICER_HEADERS,
        )
    )


def case_with_accepted_offer(
    installment_count: int = 3,
    month_starts: Optional[List[str]] = None,
    accrual_clock: Optional[str] = None,
    **scenario_kwargs: Any,
) -> Scenario:
    """
    An entered order with charges in arrears, an accrual run, and one compromise
    offer built and accepted by the obligor, which stays enforcement.
    """
    scenario = case_with_charges(month_starts=month_starts, **scenario_kwargs)
    if accrual_clock is not None:
        set_clock(accrual_clock)
    run_accrual(scenario.case_id)
    scenario.compromise_offer = create_compromise_offer(
        scenario.case_id, installment_count=installment_count
    )
    scenario.compromise_offer = accept_compromise_offer(
        scenario.compromise_offer["id"], scenario.ncp_id
    )
    scenario.reload_case()
    return scenario
