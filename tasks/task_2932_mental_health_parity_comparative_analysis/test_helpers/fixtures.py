"""Composite state builders.

The harness restarts the server before every individual test, so each test
begins against an empty database with the logical clock at its start value.
Every builder here therefore constructs the state it needs exclusively through
declared API endpoints — no direct storage access anywhere.

Builders come in five tiers:

  Tier 1  registration and the plan-year container
  Tier 2  the plan-design surface: classifications and limitation levels
  Tier 3  the NQTL inventory and its comparative-analysis lifecycle
  Tier 4  vendor production: requests, submissions and the evidence they create
  Tier 5  determinations, corrective action plans and the regulator cycle

Each builder returns the created resource dict, and the scenario builders
return a `Scenario` namespace holding every id and version a test may need.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    AppliedTo,
    BenefitCategory,
    CapDecisionOutcome,
    DeterminationOutcome,
    LimitationType,
    NetworkTier,
    NqtlType,
    ReviewOutcome,
    StringencyFinding,
    SubmissionType,
    TestBasis,
)
from .test_users import (
    OFFICER_USER_ID,
    OFFICER_USER_ID_ALT,
    make_administrator_headers,
    make_officer_headers,
    make_regulator_headers,
    make_sponsor_headers,
)


class Scenario(dict):
    """A dict whose keys are also readable as attributes."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - debugging aid
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


# ═══ Tier 1 — registration and the plan-year container ════════════════════════


def register_administrator(
    api: ApiClient, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Register the servicing TPA (a PlanSponsor capability)."""
    response = api.create_administrator(
        f.administrator_payload(**overrides), headers or make_sponsor_headers()
    )
    return get_success_data(response)


def open_plan_year(
    api: ApiClient,
    administrator_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a plan year under a registered administrator."""
    response = api.create_plan_year(
        f.plan_year_payload(administrator_id, **overrides), headers or make_sponsor_headers()
    )
    return get_success_data(response)


def registered_plan(api: ApiClient, **plan_year_overrides: Any) -> Scenario:
    """Tier 1 scenario: one administrator and one OPEN plan year under it."""
    admin = register_administrator(api)
    plan_year = open_plan_year(api, admin["id"], **plan_year_overrides)
    return Scenario(
        admin=admin,
        admin_id=admin["id"],
        admin_headers=make_administrator_headers(admin["id"]),
        plan_year=plan_year,
        plan_year_id=plan_year["id"],
        py_version=plan_year["version"],
        sponsor_headers=make_sponsor_headers(),
        officer_headers=make_officer_headers(),
        officer_alt_headers=make_officer_headers(OFFICER_USER_ID_ALT),
        regulator_headers=make_regulator_headers(),
    )


# ═══ Tier 2 — the plan-design surface ═════════════════════════════════════════


def create_classification(
    api: ApiClient,
    plan_year_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create one benefit classification under a plan year."""
    response = api.create_classification(
        plan_year_id, f.classification_payload(**overrides), headers or make_sponsor_headers()
    )
    return get_success_data(response)


def add_limitation(
    api: ApiClient,
    classification_id: str,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record one treatment-limitation level on a classification."""
    response = api.create_treatment_limitation(
        classification_id, payload, headers or make_sponsor_headers()
    )
    return get_success_data(response)


def add_limitations(
    api: ApiClient,
    classification_id: str,
    payloads: Iterable[Dict[str, Any]],
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Record several limitation levels, in the order supplied."""
    return [add_limitation(api, classification_id, p, headers) for p in payloads]


def run_parity_test(
    api: ApiClient,
    classification_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Run one quantitative parity test on a classification."""
    response = api.create_parity_test(
        classification_id, f.parity_test_payload(**overrides), headers or make_sponsor_headers()
    )
    return get_success_data(response)


def classified_plan(
    api: ApiClient,
    benefit_category: str = BenefitCategory.OUTPATIENT,
    network_tier: str = NetworkTier.IN_NETWORK,
    **classification_overrides: Any,
) -> Scenario:
    """Tier 2 scenario: a plan year with one benefit classification."""
    scenario = registered_plan(api)
    classification = create_classification(
        api,
        scenario.plan_year_id,
        benefit_category=benefit_category,
        network_tier=network_tier,
        **classification_overrides,
    )
    scenario.classification = classification
    scenario.classification_id = classification["id"]
    return scenario


def plan_with_ms_baseline(
    api: ApiClient,
    rows: Optional[Sequence[Dict[str, Any]]] = None,
    **classification_overrides: Any,
) -> Scenario:
    """Tier 2 scenario: a classification carrying a medical/surgical baseline.

    The default baseline is a two-row population — a 30-level row carrying
    5,000,000 cents over 400 claims and a 0-level row carrying 1,500,000 cents
    over 100 claims — against which a mental-health level of 30 passes.
    """
    scenario = classified_plan(api, **classification_overrides)
    baseline = (
        list(rows)
        if rows is not None
        else [
            f.ms_limitation(30, 5000000, 400),
            f.ms_limitation(0, 1500000, 100),
            f.mh_limitation(30, 800000, 90),
        ]
    )
    scenario.limitations = add_limitations(api, scenario.classification_id, baseline)
    return scenario


# ═══ Tier 3 — the NQTL inventory and its comparative analyses ═════════════════


def inventory_item(
    api: ApiClient,
    plan_year_id: str,
    classification_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Inventory one nonquantitative treatment limitation."""
    response = api.create_nqtl_item(
        f.nqtl_item_payload(plan_year_id, classification_id, **overrides),
        headers or make_sponsor_headers(),
    )
    return get_success_data(response)


def read_item(api: ApiClient, nqtl_item_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read an NQTL item — also how a client obtains its current version."""
    return get_success_data(api.get_nqtl_item(nqtl_item_id, headers or make_sponsor_headers()))


def read_plan_year(api: ApiClient, plan_year_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_plan_year(plan_year_id, headers or make_sponsor_headers()))


def read_administrator(
    api: ApiClient, administrator_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.get_administrator(administrator_id, headers or make_sponsor_headers())
    )


def read_classification(
    api: ApiClient, classification_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.get_classification(classification_id, headers or make_sponsor_headers())
    )


def read_analysis(
    api: ApiClient, analysis_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.get_analysis(analysis_id, headers or make_sponsor_headers()))


def read_vendor_request(
    api: ApiClient, vendor_request_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.get_vendor_request(vendor_request_id, headers or make_sponsor_headers())
    )


def read_submission(
    api: ApiClient, submission_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.get_data_submission(submission_id, headers or make_sponsor_headers())
    )


def read_cap(api: ApiClient, cap_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_corrective_action_plan(cap_id, headers or make_sponsor_headers())
    )


def read_regulator_request(
    api: ApiClient, request_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.get_regulator_request(request_id, headers or make_sponsor_headers())
    )


def item_version(api: ApiClient, nqtl_item_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    return read_item(api, nqtl_item_id, headers)["version"]


def plan_year_version(api: ApiClient, plan_year_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    return read_plan_year(api, plan_year_id, headers)["version"]


def draft_analysis(
    api: ApiClient,
    nqtl_item_id: str,
    expected_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft a comparative analysis, re-reading the item version when not given."""
    actor = headers or make_sponsor_headers()
    version = expected_version if expected_version is not None else item_version(api, nqtl_item_id, actor)
    response = api.create_analysis(
        f.analysis_payload(nqtl_item_id, version, **overrides), actor
    )
    return get_success_data(response)


def submit_analysis(
    api: ApiClient, analysis_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.submit_analysis(analysis_id, {}, headers or make_sponsor_headers()))


def review_analysis(
    api: ApiClient,
    analysis_id: str,
    outcome: str = ReviewOutcome.CERTIFIED,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Review a submitted analysis as a ComplianceOfficer other than its author."""
    return get_success_data(
        api.review_analysis(
            analysis_id,
            f.review_payload(outcome=outcome, **overrides),
            headers or make_officer_headers(OFFICER_USER_ID_ALT),
        )
    )


def reopen_analysis(
    api: ApiClient, analysis_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(api.reopen_analysis(analysis_id, {}, headers or make_sponsor_headers()))


def inventoried_item(
    api: ApiClient,
    nqtl_type: str = NqtlType.PRIOR_AUTHORIZATION,
    applied_to: str = AppliedTo.MENTAL_HEALTH_SUD_ONLY,
    **classification_overrides: Any,
) -> Scenario:
    """Tier 3 scenario: a plan year, a classification and one INVENTORIED item."""
    scenario = classified_plan(api, **classification_overrides)
    item = inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        nqtl_type=nqtl_type,
        applied_to=applied_to,
    )
    scenario.item = item
    scenario.item_id = item["id"]
    scenario.item_version = item["version"]
    return scenario


def item_with_draft_analysis(
    api: ApiClient,
    factor_count: int = 2,
    evidentiary_standard_count: int = 1,
    **item_overrides: Any,
) -> Scenario:
    """Tier 3 scenario: an item whose analysis sits in DRAFT."""
    scenario = inventoried_item(api, **item_overrides)
    analysis = draft_analysis(
        api,
        scenario.item_id,
        scenario.item_version,
        factor_count=factor_count,
        evidentiary_standard_count=evidentiary_standard_count,
    )
    scenario.analysis = analysis
    scenario.analysis_id = analysis["id"]
    return scenario


def item_with_submitted_analysis(
    api: ApiClient,
    factor_count: int = 2,
    evidentiary_standard_count: int = 1,
    **item_overrides: Any,
) -> Scenario:
    """Tier 3 scenario: an item in ANALYSIS_SUBMITTED behind a SUBMITTED analysis."""
    scenario = item_with_draft_analysis(
        api,
        factor_count=factor_count,
        evidentiary_standard_count=evidentiary_standard_count,
        **item_overrides,
    )
    scenario.analysis = submit_analysis(api, scenario.analysis_id)
    return scenario


# ═══ Tier 4 — vendor production and the as-applied evidence ═══════════════════


def issue_vendor_request(
    api: ApiClient,
    administrator_id: str,
    plan_year_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Issue a contractual production request, opening a production window."""
    response = api.create_vendor_request(
        f.vendor_request_payload(administrator_id, plan_year_id, **overrides),
        headers or make_sponsor_headers(),
    )
    return get_success_data(response)


def produce_submission(
    api: ApiClient,
    vendor_request_id: str,
    payload: Dict[str, Any],
    administrator_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Produce one as-applied data set — an Administrator-only capability."""
    if headers is None:
        assert administrator_id is not None, "produce_submission needs an administrator identity"
        headers = make_administrator_headers(administrator_id)
    return get_success_data(api.create_data_submission(vendor_request_id, payload, headers))


def escalate(
    api: ApiClient, vendor_request_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.escalate_vendor_request(vendor_request_id, {}, headers or make_sponsor_headers())
    )


def advance_clock(
    api: ApiClient, current_utc: str, headers: Optional[Dict[str, str]] = None
) -> Any:
    """Move the logical clock forward and return the inline recomputation report."""
    return get_success_data(
        api.set_clock(f.clock_payload(current_utc), headers or make_sponsor_headers())
    )


def with_denial_rate_evidence(
    api: ApiClient,
    scenario: Scenario,
    mh_denials: int = 300,
    mh_adjudicated_claims: int = 1000,
    ms_denials: int = 100,
    ms_adjudicated_claims: int = 1000,
    requested_item_count: int = 1,
    **request_overrides: Any,
) -> Scenario:
    """Attach a validated DENIAL_RATES submission to the scenario's classification.

    The default counters — 300 of 1,000 against 100 of 1,000 — publish a
    disparity ratio of 3.0000 and a true `as_applied_flag`.
    """
    request = issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=requested_item_count,
        requested_submission_types=[SubmissionType.DENIAL_RATES],
        **request_overrides,
    )
    submission = produce_submission(
        api,
        request["id"],
        f.denial_rate_submission_payload(
            scenario.classification_id,
            mh_denials=mh_denials,
            mh_adjudicated_claims=mh_adjudicated_claims,
            ms_denials=ms_denials,
            ms_adjudicated_claims=ms_adjudicated_claims,
        ),
        scenario.admin_id,
    )
    scenario.vendor_request = request
    scenario.vendor_request_id = request["id"]
    scenario.submission = submission
    scenario.submission_id = submission["id"]
    return scenario


def with_network_composition_evidence(
    api: ApiClient,
    scenario: Scenario,
    mh_in_network_provider_pct: float = 0.30,
    ms_in_network_provider_pct: float = 0.58,
    requested_item_count: int = 1,
    **request_overrides: Any,
) -> Scenario:
    """Attach a validated NETWORK_COMPOSITION submission (gap 0.2800 by default)."""
    request = issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        requested_item_count=requested_item_count,
        requested_submission_types=[SubmissionType.NETWORK_COMPOSITION],
        **request_overrides,
    )
    submission = produce_submission(
        api,
        request["id"],
        f.network_composition_submission_payload(
            scenario.classification_id,
            mh_in_network_provider_pct=mh_in_network_provider_pct,
            ms_in_network_provider_pct=ms_in_network_provider_pct,
        ),
        scenario.admin_id,
    )
    scenario.network_request = request
    scenario.network_submission = submission
    return scenario


# ═══ Tier 5 — determinations, corrective action and the regulator cycle ═══════


def record_determination(
    api: ApiClient,
    nqtl_item_id: str,
    plan_year_id: str,
    outcome: str = DeterminationOutcome.VIOLATION,
    expected_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record a parity determination, re-reading the plan-year version if needed."""
    actor = headers or make_officer_headers()
    version = (
        expected_version
        if expected_version is not None
        else plan_year_version(api, plan_year_id, actor)
    )
    response = api.create_determination(
        nqtl_item_id, f.determination_payload(outcome, version, **overrides), actor
    )
    return get_success_data(response)


def draft_cap(
    api: ApiClient,
    nqtl_item_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft a corrective action plan against an item in VIOLATION."""
    response = api.create_corrective_action_plan(
        f.cap_payload(nqtl_item_id, **overrides), headers or make_officer_headers()
    )
    return get_success_data(response)


def decide_cap(
    api: ApiClient,
    cap_id: str,
    outcome: str = CapDecisionOutcome.APPROVED,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Decide a drafted plan as an officer other than the determining one."""
    return get_success_data(
        api.decide_corrective_action_plan(
            cap_id,
            f.cap_decision_payload(outcome=outcome, **overrides),
            headers or make_officer_headers(OFFICER_USER_ID_ALT),
        )
    )


def close_cap(
    api: ApiClient,
    cap_id: str,
    outcome: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.close_corrective_action_plan(
            cap_id,
            f.cap_closure_payload(outcome=outcome, **overrides),
            headers or make_officer_headers(OFFICER_USER_ID_ALT),
        )
    )


def open_regulator_request(
    api: ApiClient,
    plan_year_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a regulator request, which freezes the plan-design surface."""
    response = api.create_regulator_request(
        f.regulator_request_payload(plan_year_id, **overrides), headers or make_regulator_headers()
    )
    return get_success_data(response)


def respond_to_regulator(
    api: ApiClient, request_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.respond_regulator_request(
            request_id, f.respond_payload(**overrides), headers or make_sponsor_headers()
        )
    )


def adjudicate_regulator_request(
    api: ApiClient, request_id: str, outcome: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.adjudicate_regulator_request(
            request_id,
            f.adjudicate_payload(outcome=outcome, **overrides),
            headers or make_regulator_headers(),
        )
    )


# ─── Composite tier-5 scenarios ───────────────────────────────────────────────


def item_awaiting_determination(
    api: ApiClient,
    nqtl_type: str = NqtlType.PRIOR_AUTHORIZATION,
    applied_to: str = AppliedTo.MENTAL_HEALTH_SUD_ONLY,
    mh_denials: int = 300,
    mh_adjudicated_claims: int = 1000,
    ms_denials: int = 100,
    ms_adjudicated_claims: int = 1000,
    factor_count: int = 2,
    evidentiary_standard_count: int = 1,
    stringency_operation_finding: str = StringencyFinding.MORE_STRINGENT_MH,
    **classification_overrides: Any,
) -> Scenario:
    """An item in ANALYSIS_SUBMITTED with validated as-applied evidence behind it.

    The evidence is produced before the analysis is drafted so that the analysis
    create carries the item version the submission cascade left behind.
    """
    scenario = inventoried_item(
        api, nqtl_type=nqtl_type, applied_to=applied_to, **classification_overrides
    )
    with_denial_rate_evidence(
        api,
        scenario,
        mh_denials=mh_denials,
        mh_adjudicated_claims=mh_adjudicated_claims,
        ms_denials=ms_denials,
        ms_adjudicated_claims=ms_adjudicated_claims,
    )
    analysis = draft_analysis(
        api,
        scenario.item_id,
        factor_count=factor_count,
        evidentiary_standard_count=evidentiary_standard_count,
        stringency_operation_finding=stringency_operation_finding,
    )
    scenario.analysis = submit_analysis(api, analysis["id"])
    scenario.analysis_id = analysis["id"]
    return scenario


def item_with_certified_analysis(
    api: ApiClient,
    mh_denials: int = 137,
    mh_adjudicated_claims: int = 1919,
    ms_denials: int = 71,
    ms_adjudicated_claims: int = 1913,
    applied_to: str = AppliedTo.BOTH,
    certifier: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Scenario:
    """An item whose analysis has been CERTIFIED by an officer other than the author.

    The default counters — 137 of 1,919 against 71 of 1,913 — publish a
    disparity ratio of 1.9235, which keeps a PRIOR_AUTHORIZATION item applied to
    both sides below the stringency flag threshold.
    """
    scenario = item_awaiting_determination(
        api,
        applied_to=applied_to,
        mh_denials=mh_denials,
        mh_adjudicated_claims=mh_adjudicated_claims,
        ms_denials=ms_denials,
        ms_adjudicated_claims=ms_adjudicated_claims,
        **overrides,
    )
    scenario.analysis = review_analysis(
        api,
        scenario.analysis_id,
        ReviewOutcome.CERTIFIED,
        certifier or make_officer_headers(OFFICER_USER_ID_ALT),
    )
    return scenario


def item_in_violation(
    api: ApiClient,
    determiner: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Scenario:
    """An item driven to VIOLATION, with the plan year moved to REMEDIATION.

    The determination is recorded by `user-officer-01` unless a different actor
    is supplied, so that `user-officer-02` remains available to decide the
    corrective action plan without tripping approver independence.
    """
    scenario = item_awaiting_determination(api, **overrides)
    scenario.determiner_headers = determiner or make_officer_headers(OFFICER_USER_ID)
    scenario.item = record_determination(
        api,
        scenario.item_id,
        scenario.plan_year_id,
        DeterminationOutcome.VIOLATION,
        headers=scenario.determiner_headers,
    )
    return scenario


def item_with_approved_cap(
    api: ApiClient,
    remedy_type: Optional[str] = None,
    affected_claims_count: int = 880,
    average_claim_cents: int = 3125,
    **overrides: Any,
) -> Scenario:
    """An item in VIOLATION with one APPROVED corrective action plan booked."""
    scenario = item_in_violation(api, **overrides)
    cap_kwargs: Dict[str, Any] = {
        "affected_claims_count": affected_claims_count,
        "average_claim_cents": average_claim_cents,
    }
    if remedy_type is not None:
        cap_kwargs["remedy_type"] = remedy_type
    cap = draft_cap(api, scenario.item_id, **cap_kwargs)
    scenario.cap = decide_cap(api, cap["id"], CapDecisionOutcome.APPROVED)
    scenario.cap_id = cap["id"]
    return scenario


def plan_under_regulator_review(api: ApiClient, **overrides: Any) -> Scenario:
    """A plan year moved to UNDER_REGULATOR_REVIEW by an open regulator request."""
    scenario = inventoried_item(api, **overrides)
    request = open_regulator_request(
        api, scenario.plan_year_id, requested_nqtl_types=[scenario.item["nqtl_type"]]
    )
    scenario.regulator_request = request
    scenario.regulator_request_id = request["id"]
    return scenario
