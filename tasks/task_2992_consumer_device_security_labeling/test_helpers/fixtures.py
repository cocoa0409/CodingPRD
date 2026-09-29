"""Composite setup helpers for the multi-step chains the API demands.

Every helper drives the public API only - there is no back door into server
state. Two conventions matter for callers:

* Reviewer separation. `approve_assessment` decides with `REVIEWER_USER_ID`
  while `publish_grant` publishes with `REVIEWER_2_USER_ID`, because the
  publication decision requires an acting reviewer whose identity differs from
  the backing assessment's `decided_by_user_id`.
* Assessment supersession. Opening a second assessment against the same product
  supersedes the first, so helpers that would open one accept an existing
  assessment instead of silently replacing it.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS, plus_days
from .test_users import (
    ADMIN_ADJUDICATE_USER_ID,
    ADMIN_NOTICE_USER_ID,
    ADMIN_USER_ID,
    REVIEWER_2_USER_ID,
    REVIEWER_USER_ID,
    make_admin_headers,
    make_lab_operator_headers,
    make_manufacturer_headers,
    make_retailer_headers,
    make_reviewer_headers,
)

ADMIN = make_admin_headers(ADMIN_USER_ID)
REVIEWER = make_reviewer_headers(REVIEWER_USER_ID)
PUBLISHER = make_reviewer_headers(REVIEWER_2_USER_ID)
NOTICE_ADMIN = make_admin_headers(ADMIN_NOTICE_USER_ID)
ADJUDICATE_ADMIN = make_admin_headers(ADMIN_ADJUDICATE_USER_ID)


def created(response) -> Dict[str, Any]:
    """Unwrap a setup write, accepting any 2xx with a readable failure message."""
    return get_success_data(response)


def read(response) -> Dict[str, Any]:
    """Unwrap a setup read, accepting any 2xx with a readable failure message."""
    return get_success_data(response)


# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------
def set_clock(instant: str, headers: Optional[Dict[str, str]] = None) -> str:
    read(api_client.set_clock(instant, headers or ADMIN))
    return instant


def reset_clock(headers: Optional[Dict[str, str]] = None) -> str:
    return set_clock(DEFAULT_CLOCK, headers)


def advance_clock_days(days: float, base: str = DEFAULT_CLOCK, headers=None) -> str:
    """Park the clock `days` after `base` and return the new instant."""
    return set_clock(plus_days(base, days), headers)


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return read(api_client.run_expiry_sweep(headers or ADMIN))


# --------------------------------------------------------------------------
# Context objects
# --------------------------------------------------------------------------
@dataclass
class Program:
    tier: Dict[str, Any]
    category: Dict[str, Any]
    criteria: List[Dict[str, Any]]

    @property
    def criteria_by_code(self) -> Dict[str, Dict[str, Any]]:
        return {c["criterion_code"]: c for c in self.criteria}

    def criterion_id(self, criterion_code: str) -> str:
        return self.criteria_by_code[criterion_code]["id"]


@dataclass
class Sponsor:
    manufacturer: Dict[str, Any]

    @property
    def id(self) -> str:
        return self.manufacturer["id"]

    @property
    def headers(self) -> Dict[str, str]:
        return make_manufacturer_headers(self.id)

    def refresh(self) -> Dict[str, Any]:
        self.manufacturer = read(api_client.get_manufacturer(self.id, ADMIN))
        return self.manufacturer


@dataclass
class Lab:
    test_lab: Dict[str, Any]

    @property
    def id(self) -> str:
        return self.test_lab["id"]

    @property
    def headers(self) -> Dict[str, str]:
        return make_lab_operator_headers(self.id)

    def refresh(self) -> Dict[str, Any]:
        self.test_lab = read(api_client.get_test_lab(self.id, ADMIN))
        return self.test_lab


@dataclass
class Store:
    retailer: Dict[str, Any]

    @property
    def id(self) -> str:
        return self.retailer["id"]

    @property
    def headers(self) -> Dict[str, str]:
        return make_retailer_headers(self.id)

    def refresh(self) -> Dict[str, Any]:
        self.retailer = read(api_client.get_retailer(self.id, ADMIN))
        return self.retailer


@dataclass
class Claim:
    """One product plus the assessment currently describing it."""
    program: Program
    sponsor: Sponsor
    product: Dict[str, Any]
    assessment: Dict[str, Any]
    responses: List[Dict[str, Any]] = field(default_factory=list)
    lab: Optional[Lab] = None
    engagement: Optional[Dict[str, Any]] = None

    @property
    def product_id(self) -> str:
        return self.product["id"]

    @property
    def assessment_id(self) -> str:
        return self.assessment["id"]

    def refresh_product(self) -> Dict[str, Any]:
        self.product = read(api_client.get_product(self.product_id, ADMIN))
        return self.product

    def refresh_assessment(self) -> Dict[str, Any]:
        self.assessment = read(api_client.get_assessment(self.assessment_id, ADMIN))
        return self.assessment


@dataclass
class Grant:
    claim: Claim
    label_grant: Dict[str, Any]
    registry_entry: Optional[Dict[str, Any]] = None

    @property
    def id(self) -> str:
        return self.label_grant["id"]

    @property
    def scannable_code(self) -> str:
        return self.label_grant["scannable_code"]

    def refresh(self) -> Dict[str, Any]:
        self.label_grant = read(api_client.get_label_grant(self.id, ADMIN))
        return self.label_grant


# --------------------------------------------------------------------------
# Program configuration
# --------------------------------------------------------------------------
def create_program(
    required_route: str = "SELF_ATTESTATION",
    tier_overrides: Optional[Dict[str, Any]] = None,
    category_overrides: Optional[Dict[str, Any]] = None,
    criteria: Optional[List[Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Program:
    """Tier + one ELIGIBLE category + the five-criterion catalogue.

    Under the default tier (`unverified_weight_factor` 0.60) a claim that
    self-declares conformance with all five criteria scores 80.80 provisionally
    and 100.00 once every lab-verifiable criterion passes the bench.
    """
    headers = headers or ADMIN
    if required_route == "THIRD_PARTY_TEST":
        tier_payload = f.create_third_party_tier_payload(**(tier_overrides or {}))
    else:
        tier_payload = f.create_program_tier_payload(**(tier_overrides or {}))
    tier = created(api_client.create_program_tier(tier_payload, headers))
    category = created(
        api_client.create_device_category(
            f.create_device_category_payload(tier["id"], **(category_overrides or {})),
            headers,
        )
    )
    catalogue = created(
        api_client.create_security_criteria(f.create_security_criteria_payload(criteria), headers)
    )
    return Program(tier=tier, category=category, criteria=list(catalogue))


def add_category(program: Program, headers=None, **overrides) -> Dict[str, Any]:
    """Another category under the same tier."""
    return created(
        api_client.create_device_category(
            f.create_device_category_payload(program.tier["id"], **overrides),
            headers or ADMIN,
        )
    )


def add_excluded_category(program: Program, headers=None, **overrides) -> Dict[str, Any]:
    return created(
        api_client.create_device_category(
            f.create_excluded_category_payload(program.tier["id"], **overrides),
            headers or ADMIN,
        )
    )


# --------------------------------------------------------------------------
# Participants
# --------------------------------------------------------------------------
def enrol_manufacturer(headers=None, **overrides) -> Sponsor:
    return Sponsor(
        created(api_client.create_manufacturer(f.create_manufacturer_payload(**overrides), headers or ADMIN))
    )


def enrol_large_manufacturer(headers=None, **overrides) -> Sponsor:
    return Sponsor(
        created(
            api_client.create_manufacturer(
                f.create_large_manufacturer_payload(**overrides), headers or ADMIN
            )
        )
    )


def register_lab(headers=None, **overrides) -> Lab:
    return Lab(created(api_client.create_test_lab(f.create_test_lab_payload(**overrides), headers or ADMIN)))


def register_retailer(acknowledge: bool = True, headers=None, **overrides) -> Store:
    """A retailer that has acknowledged the education materials by default.

    Acknowledgement is a precondition of creating any display authorization.
    """
    store = Store(created(api_client.create_retailer(f.create_retailer_payload(**overrides), headers or ADMIN)))
    if acknowledge:
        store.retailer = created(
            api_client.acknowledge_education(store.id, f.education_ack_payload(), store.headers)
        )
    return store


def register_product(program: Program, sponsor: Sponsor, category_id: Optional[str] = None, **overrides) -> Dict[str, Any]:
    return created(
        api_client.create_product(
            f.create_product_payload(sponsor.id, category_id or program.category["id"], **overrides),
            sponsor.headers,
        )
    )


# --------------------------------------------------------------------------
# Assessments
# --------------------------------------------------------------------------
def open_assessment(claim_program: Program, sponsor: Sponsor, product: Dict[str, Any]) -> Dict[str, Any]:
    """Open a DRAFT assessment against `product` at its current version."""
    return created(
        api_client.create_assessment(
            product["id"], f.open_assessment_payload(product["version"]), sponsor.headers
        )
    )


def attach_responses(
    program: Program,
    sponsor: Sponsor,
    assessment: Dict[str, Any],
    conformance: Optional[Dict[str, bool]] = None,
    codes: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """One response per catalogue criterion, covering all four practice areas.

    `conformance` overrides `self_declared_conformant` per criterion code; every
    unmentioned criterion is declared conformant.
    """
    conformance = conformance or {}
    selected = list(codes) if codes is not None else [c["criterion_code"] for c in program.criteria]
    items = [
        f.response_item(program.criterion_id(code), conformance.get(code, True))
        for code in selected
    ]
    return created(
        api_client.create_criterion_responses(
            assessment["id"], f.criterion_responses_payload(items), sponsor.headers
        )
    )


def draft_claim(
    program: Optional[Program] = None,
    sponsor: Optional[Sponsor] = None,
    conformance: Optional[Dict[str, bool]] = None,
    required_route: str = "SELF_ATTESTATION",
    product_overrides: Optional[Dict[str, Any]] = None,
    response_codes: Optional[Sequence[str]] = None,
) -> Claim:
    """Program, sponsor, product, DRAFT assessment and its criterion responses."""
    program = program or create_program(required_route)
    sponsor = sponsor or enrol_manufacturer()
    product = register_product(program, sponsor, **(product_overrides or {}))
    assessment = open_assessment(program, sponsor, product)
    responses = attach_responses(program, sponsor, assessment, conformance, response_codes)
    claim = Claim(program=program, sponsor=sponsor, product=product, assessment=assessment, responses=responses)
    claim.refresh_product()
    return claim


def submit_claim(claim: Claim) -> Dict[str, Any]:
    claim.assessment = created(api_client.submit_assessment(claim.assessment_id, claim.sponsor.headers))
    return claim.assessment


def decide_claim(claim: Claim, decision: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    claim.assessment = created(
        api_client.decide_assessment(claim.assessment_id, f.decide_payload(decision), headers or REVIEWER)
    )
    return claim.assessment


def submitted_claim(**kwargs) -> Claim:
    """A claim sitting at UNDER_REVIEW."""
    claim = draft_claim(**kwargs)
    submit_claim(claim)
    return claim


def approved_claim(
    program: Optional[Program] = None,
    sponsor: Optional[Sponsor] = None,
    conformance: Optional[Dict[str, bool]] = None,
    product_overrides: Optional[Dict[str, Any]] = None,
    reviewer_headers: Optional[Dict[str, str]] = None,
) -> Claim:
    """A SELF_ATTESTATION claim approved by `REVIEWER_USER_ID`.

    The decided score is 80.80 under the default catalogue and tier, which is
    exactly the tier's `min_overall_score`, so the approval clears the bar.
    """
    claim = submitted_claim(
        program=program,
        sponsor=sponsor,
        conformance=conformance,
        required_route="SELF_ATTESTATION",
        product_overrides=product_overrides,
    )
    decide_claim(claim, "APPROVED", reviewer_headers)
    claim.refresh_product()
    return claim


# --------------------------------------------------------------------------
# Bench testing
# --------------------------------------------------------------------------
def book_engagement(claim: Claim, lab: Lab, **overrides) -> Dict[str, Any]:
    engagement = created(
        api_client.create_test_engagement(
            f.create_test_engagement_payload(claim.assessment_id, lab.id, **overrides),
            claim.sponsor.headers,
        )
    )
    claim.lab = lab
    claim.engagement = engagement
    return engagement


def file_report(claim: Claim, failed_criterion_codes: Optional[Sequence[str]] = None, **overrides) -> Dict[str, Any]:
    assert claim.engagement is not None, "book_engagement first"
    claim.engagement = created(
        api_client.report_test_engagement(
            claim.engagement["id"],
            f.report_payload(list(failed_criterion_codes or []), **overrides),
            claim.lab.headers,
        )
    )
    claim.refresh_assessment()
    return claim.engagement


def tested_claim(
    program: Optional[Program] = None,
    sponsor: Optional[Sponsor] = None,
    lab: Optional[Lab] = None,
    conformance: Optional[Dict[str, bool]] = None,
    failed_criterion_codes: Optional[Sequence[str]] = None,
    engagement_overrides: Optional[Dict[str, Any]] = None,
) -> Claim:
    """A THIRD_PARTY_TEST claim whose bench report has landed (UNDER_REVIEW).

    Booking happens after submission so the engagement is never orphaned by the
    supersession rule, and the report writes the verified score set.
    """
    program = program or create_program("THIRD_PARTY_TEST")
    claim = submitted_claim(program=program, sponsor=sponsor, conformance=conformance,
                            required_route="THIRD_PARTY_TEST")
    book_engagement(claim, lab or register_lab(), **(engagement_overrides or {}))
    file_report(claim, failed_criterion_codes)
    return claim


def approved_tested_claim(**kwargs) -> Claim:
    """A THIRD_PARTY_TEST claim approved after a COMPLETED engagement."""
    reviewer_headers = kwargs.pop("reviewer_headers", None)
    claim = tested_claim(**kwargs)
    decide_claim(claim, "APPROVED", reviewer_headers)
    claim.refresh_product()
    return claim


# --------------------------------------------------------------------------
# Label grants, registry entries and publication
# --------------------------------------------------------------------------
def issue_grant(claim: Claim, headers: Optional[Dict[str, str]] = None) -> Grant:
    """Request the label grant: PENDING_REGISTRY on DRAFT."""
    label_grant = created(
        api_client.create_label_grant(
            f.create_label_grant_payload(claim.product_id, claim.assessment_id),
            headers or claim.sponsor.headers,
        )
    )
    return Grant(claim=claim, label_grant=label_grant)


def supply_registry_entry(grant: Grant, headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    grant.registry_entry = created(
        api_client.create_registry_entry(
            grant.id, f.registry_entry_payload(**overrides), headers or grant.claim.sponsor.headers
        )
    )
    return grant.registry_entry


def decide_publication(
    grant: Grant, publication_decision: str = "PUBLISHED", headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    grant.label_grant = created(
        api_client.decide_registry_publication(
            grant.id, f.publication_payload(publication_decision), headers or PUBLISHER
        )
    )
    return grant.label_grant


def pending_grant(claim: Optional[Claim] = None, with_entry: bool = True, **entry_overrides) -> Grant:
    """A grant at PENDING_REGISTRY/DRAFT, optionally already carrying its entry."""
    claim = claim or approved_claim()
    grant = issue_grant(claim)
    if with_entry:
        supply_registry_entry(grant, **entry_overrides)
    return grant


def published_grant(claim: Optional[Claim] = None, publisher_headers: Optional[Dict[str, str]] = None,
                    **entry_overrides) -> Grant:
    """A live label: ACTIVE on the grant dimension and PUBLISHED on the other."""
    grant = pending_grant(claim, with_entry=True, **entry_overrides)
    decide_publication(grant, "PUBLISHED", publisher_headers)
    grant.claim.refresh_product()
    return grant


def renew_grant(grant: Grant, assessment_id: Optional[str] = None,
                headers: Optional[Dict[str, str]] = None) -> Grant:
    """Renew against a fresh approved assessment, retiring the predecessor."""
    predecessor = grant.refresh()
    new_grant = created(
        api_client.create_renewal(
            grant.id,
            f.renewal_payload(assessment_id or grant.claim.assessment_id, predecessor["version"]),
            headers or grant.claim.sponsor.headers,
        )
    )
    return Grant(claim=grant.claim, label_grant=new_grant)


# --------------------------------------------------------------------------
# Retailer display authorizations
# --------------------------------------------------------------------------
def authorize_display(
    grant: Grant,
    store: Optional[Store] = None,
    channel: str = "IN_STORE",
    display_from: Optional[str] = None,
    display_until: Optional[str] = None,
    days_after_valid_from: float = 1,
    span_days: float = 10,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """A closed display window sitting wholly inside the grant's validity."""
    store = store or register_retailer()
    valid_from = grant.label_grant["valid_from"]
    start = display_from or plus_days(valid_from, days_after_valid_from)
    end = display_until or plus_days(start, span_days)
    return created(
        api_client.create_display_authorization(
            f.create_display_authorization_payload(store.id, grant.id, start, end, channel=channel, **overrides),
            headers or store.headers,
        )
    )


def displayed_grant(claim: Optional[Claim] = None, store: Optional[Store] = None,
                    channel: str = "IN_STORE") -> Dict[str, Any]:
    """Returns `{"grant": Grant, "store": Store, "authorization": dict}`."""
    grant = published_grant(claim)
    store = store or register_retailer()
    authorization = authorize_display(grant, store, channel=channel)
    store.refresh()
    return {"grant": grant, "store": store, "authorization": authorization}


# --------------------------------------------------------------------------
# Misuse enforcement
# --------------------------------------------------------------------------
def open_case(
    sponsor: Sponsor,
    reported_scannable_code: str = "ZZ-NO-SUCH-CD000",
    violation_type: str = "UNAUTHORIZED_DISPLAY",
    violation_line_items: Optional[List[Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Open a case at OPENED/NONE.

    The default `reported_scannable_code` resolves to no grant, which is the
    `UNAUTHORIZED_DISPLAY` shape; pass a real `scannable_code` together with
    `EXPIRED_LABEL_DISPLAY` or `FALSE_CLAIM` for the registry-backed shapes.
    """
    return created(
        api_client.create_enforcement_case(
            f.create_enforcement_case_payload(
                sponsor.id, reported_scannable_code, violation_type, violation_line_items, **overrides
            ),
            headers or ADMIN,
        )
    )


def issue_notice(case: Dict[str, Any], headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    return created(api_client.issue_case_notice(case["id"], f.notice_payload(**overrides), headers or NOTICE_ADMIN))


def refer_to_lab(case: Dict[str, Any], lab: Lab, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return created(api_client.refer_case_to_lab(case["id"], f.lab_referral_payload(lab.id), headers or ADMIN))


def adjudicate(case: Dict[str, Any], outcome: str = "UPHELD",
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Adjudicate with an administrator other than the one who noticed it."""
    return created(
        api_client.adjudicate_case(case["id"], f.adjudicate_payload(outcome), headers or ADJUDICATE_ADMIN)
    )


def noticed_case(
    sponsor: Optional[Sponsor] = None,
    reported_scannable_code: str = "ZZ-NO-SUCH-CD000",
    violation_type: str = "UNAUTHORIZED_DISPLAY",
    violation_line_items: Optional[List[Dict[str, Any]]] = None,
    notice_headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """A case at NOTICE_ISSUED/NONE, ready for adjudication."""
    sponsor = sponsor or enrol_manufacturer()
    case = open_case(sponsor, reported_scannable_code, violation_type, violation_line_items, **overrides)
    return issue_notice(case, notice_headers)


def upheld_case(
    sponsor: Optional[Sponsor] = None,
    reported_scannable_code: str = "ZZ-NO-SUCH-CD000",
    violation_type: str = "UNAUTHORIZED_DISPLAY",
    violation_line_items: Optional[List[Dict[str, Any]]] = None,
    notice_headers: Optional[Dict[str, str]] = None,
    adjudicate_headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """A case at ADJUDICATED_UPHELD/ASSESSED with its penalty struck."""
    case = noticed_case(
        sponsor, reported_scannable_code, violation_type, violation_line_items, notice_headers, **overrides
    )
    return adjudicate(case, "UPHELD", adjudicate_headers)


def pay_penalty(case: Dict[str, Any], sponsor: Sponsor, headers: Optional[Dict[str, str]] = None,
                **overrides) -> Dict[str, Any]:
    return created(
        api_client.pay_penalty(case["id"], f.penalty_payment_payload(**overrides), headers or sponsor.headers)
    )


def vacate(case: Dict[str, Any], headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    """Vacate with an administrator other than the one who adjudicated it."""
    return created(api_client.vacate_case(case["id"], f.vacate_payload(**overrides), headers or ADMIN))


# --------------------------------------------------------------------------
# Recognition surveys
# --------------------------------------------------------------------------
def record_survey(headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    return created(
        api_client.create_recognition_survey(f.create_recognition_survey_payload(**overrides), headers or ADMIN)
    )


def program_evaluation(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return read(api_client.get_program_evaluation(headers or ADMIN))
