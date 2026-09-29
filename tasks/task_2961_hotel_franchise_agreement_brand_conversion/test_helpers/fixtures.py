"""Composite setup helpers.

The harness restarts the API before every individual test, so each test opens
against an empty database and every fixture here builds its world from
scratch through documented endpoints only.

Five tiers, from thinnest to thickest:

* Tier 1 - single-resource creators (``create_brand``, ``create_owner`` ...).
* Tier 2 - stage advancers (``start_review``, ``run_financial_review`` ...).
* Tier 3 - one application carried to a named review stage.
* Tier 4 - one agreement carried to a named lifecycle stage.
* Tier 5 - whole scenarios (fee ledger populated, plan defaulted, agreement
  terminated) assembled from the lower tiers.

Every helper takes ``**overrides`` where a caller might reasonably need to
perturb a payload, and every returned dict threads the real Owner id so
ownership-gated calls can be made with headers for the right owner.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import (
    CLOCK_ACCEPT,
    CLOCK_COMPLETE,
    CLOCK_DECEMBER_REPORT,
    CLOCK_DECISION,
    CLOCK_DRAFT,
    CLOCK_EXECUTE,
    CLOCK_INTAKE,
    CLOCK_NOVEMBER_REPORT,
    CLOCK_OPEN,
    CLOCK_REVIEW,
    CLOCK_SCOPE,
    CLOCK_VERIFY,
    DEFAULT_EFFECTIVE_DATE,
    THREE_LINE_SCOPE,
)
from .test_users import (
    BSD_HEADERS,
    FDM_DECIDER_HEADERS,
    FDM_HEADERS,
    QA_HEADERS,
    make_owner_headers,
)


# ─── Tier 1: clock and single-resource creators ──────────────────────

def set_clock(api: ApiClient, to_iso8601: str, headers: dict = None) -> str:
    """Move the server-held logical clock and return the instant it reports."""
    response = api.set_clock(
        factories.build_clock_payload(to_iso8601), headers or FDM_HEADERS
    )
    data = get_success_data(response)
    return data["current_utc"]


def create_brand(api: ApiClient, headers: dict = None, **overrides) -> dict:
    response = api.create_brand(
        factories.build_brand_payload(**overrides), headers or BSD_HEADERS
    )
    return get_success_data(response)


def create_solaris_brand(api: ApiClient, headers: dict = None, **overrides) -> dict:
    response = api.create_brand(
        factories.build_solaris_brand_payload(**overrides), headers or BSD_HEADERS
    )
    return get_success_data(response)


def create_existing_unit(api: ApiClient, brand_id: str, headers: dict = None, **overrides) -> dict:
    response = api.create_existing_unit(
        factories.build_existing_unit_payload(brand_id, **overrides), headers or BSD_HEADERS
    )
    return get_success_data(response)


def create_owner(api: ApiClient, headers: dict = None, **overrides) -> dict:
    response = api.create_owner(
        factories.build_owner_payload(**overrides), headers or FDM_HEADERS
    )
    return get_success_data(response)


def create_strong_owner(api: ApiClient, headers: dict = None, **overrides) -> dict:
    """Harbor Point Hospitality: STRONG on both capacity variants."""
    response = api.create_owner(
        factories.build_strong_owner_payload(**overrides), headers or FDM_HEADERS
    )
    return get_success_data(response)


def create_application(
    api: ApiClient, owner_id: str, brand_id: str, headers: dict = None, **overrides
) -> dict:
    response = api.create_application(
        factories.build_harbor_point_application_payload(owner_id, brand_id, **overrides),
        headers or FDM_HEADERS,
    )
    return get_success_data(response)


def change_unit_status(
    api: ApiClient, unit_id: str, to_status: str, reason: str = "Operational decision recorded.",
    headers: dict = None,
) -> dict:
    response = api.change_existing_unit_status(
        unit_id, factories.build_unit_status_payload(to_status, reason), headers or BSD_HEADERS
    )
    return get_success_data(response)


# ─── Tier 2: stage advancers ─────────────────────────────────────────

def start_review(api: ApiClient, application_id: str, headers: dict = None) -> dict:
    response = api.start_application_review(application_id, {}, headers or FDM_HEADERS)
    return get_success_data(response)


def run_financial_review(
    api: ApiClient,
    application_id: str,
    capacity_basis: str = "PORTFOLIO_ADJUSTED",
    reviewer_headers: dict = None,
    **overrides,
) -> dict:
    """Record the financial review.  The reviewer's identity is stored, and
    PRD §2.10 forbids that identity from later deciding the application, so
    the review and the decision are driven by two different managers."""
    response = api.record_financial_review(
        application_id,
        factories.build_financial_review_payload(capacity_basis, **overrides),
        reviewer_headers or FDM_HEADERS,
    )
    return get_success_data(response)


def run_impact_analysis(api: ApiClient, application_id: str, headers: dict = None, **payload) -> dict:
    response = api.run_impact_analysis(application_id, payload, headers or BSD_HEADERS)
    return get_success_data(response)


def finalize_impact(api: ApiClient, application_id: str, headers: dict = None, **payload) -> dict:
    response = api.finalize_impact(application_id, payload, headers or BSD_HEADERS)
    return get_success_data(response)


def file_claim(api: ApiClient, application_id: str, unit_id: str, headers: dict = None, **overrides) -> dict:
    response = api.file_encroachment_claim(
        application_id,
        factories.build_encroachment_claim_payload(unit_id, **overrides),
        headers or BSD_HEADERS,
    )
    return get_success_data(response)


def resolve_claim(api: ApiClient, claim_id: str, outcome: str, headers: dict = None, **overrides) -> dict:
    response = api.resolve_encroachment_claim(
        claim_id, factories.build_claim_resolution_payload(outcome, **overrides), headers or BSD_HEADERS
    )
    return get_success_data(response)


def decide_application(
    api: ApiClient, application_id: str, outcome: str = "APPROVE",
    decider_headers: dict = None, **overrides,
) -> dict:
    response = api.decide_application(
        application_id,
        factories.build_decision_payload(outcome, **overrides),
        decider_headers or FDM_DECIDER_HEADERS,
    )
    return get_success_data(response)


def draft_agreement(
    api: ApiClient, application_id: str, effective_date: str = DEFAULT_EFFECTIVE_DATE,
    headers: dict = None, **overrides,
) -> dict:
    response = api.draft_agreement(
        application_id,
        factories.build_agreement_payload(effective_date, **overrides),
        headers or FDM_HEADERS,
    )
    return get_success_data(response)


def read_application_version(api: ApiClient, application_id: str, headers: dict = None) -> int:
    """The version an execute call must echo back in expected_application_version."""
    data = get_success_data(api.get_application(application_id, headers or FDM_HEADERS))
    return data["version"]


def execute_agreement(
    api: ApiClient, agreement_id: str, application_id: str, headers: dict = None
) -> dict:
    version = read_application_version(api, application_id, headers)
    response = api.execute_agreement(
        agreement_id, factories.build_execute_payload(version), headers or FDM_HEADERS
    )
    return get_success_data(response)


def create_pip(api: ApiClient, agreement_id: str, headers: dict = None, **overrides) -> dict:
    response = api.create_pip(
        agreement_id, factories.build_pip_payload(**overrides), headers or BSD_HEADERS
    )
    return get_success_data(response)


def add_scope_line(api: ApiClient, pip_id: str, headers: dict = None, **overrides) -> dict:
    response = api.create_pip_item(
        pip_id, factories.build_pip_item_payload(**overrides), headers or BSD_HEADERS
    )
    return get_success_data(response)


def accept_pip(api: ApiClient, pip_id: str, owner_id: str, acknowledgement: str = "ACCEPTED_IN_FULL") -> dict:
    """Acceptance is owner-addressed, so the real Owner id must sign it."""
    response = api.accept_pip(
        pip_id, factories.build_pip_accept_payload(acknowledgement), make_owner_headers(owner_id)
    )
    return get_success_data(response)


def complete_item(api: ApiClient, item_id: str, owner_id: str, **overrides) -> dict:
    response = api.complete_pip_item(
        item_id, factories.build_item_completion_payload(**overrides), make_owner_headers(owner_id)
    )
    return get_success_data(response)


def verify_item(api: ApiClient, item_id: str, outcome: str = "VERIFY", headers: dict = None, **overrides) -> dict:
    response = api.verify_pip_item(
        item_id, factories.build_item_verification_payload(outcome, **overrides), headers or BSD_HEADERS
    )
    return get_success_data(response)


def request_extension(api: ApiClient, item_id: str, owner_id: str, requested_days: int = 30, **overrides) -> dict:
    response = api.request_pip_item_extension(
        item_id,
        factories.build_extension_request_payload(requested_days, **overrides),
        make_owner_headers(owner_id),
    )
    return get_success_data(response)


def decide_extension(api: ApiClient, item_id: str, outcome: str = "GRANT", headers: dict = None, **overrides) -> dict:
    response = api.decide_pip_item_extension(
        item_id, factories.build_extension_decision_payload(outcome, **overrides), headers or BSD_HEADERS
    )
    return get_success_data(response)


def run_compliance_sweep(api: ApiClient, pip_id: str, headers: dict = None) -> dict:
    response = api.run_compliance_sweep(pip_id, {}, headers or BSD_HEADERS)
    return get_success_data(response)


def climb_onboarding_ladders(api: ApiClient, agreement_id: str, headers: dict = None) -> dict:
    """Climb all five rungs in the only order the ladders allow (PRD §3.6):
    TRAINING COMPLETED, SYSTEMS PROVISIONED, SYSTEMS VALIDATED,
    CHANNEL TESTING, CHANNEL CONNECTED."""
    actor = headers or FDM_HEADERS
    latest = None
    for track, to_status in (
        ("TRAINING", "COMPLETED"),
        ("SYSTEMS", "PROVISIONED"),
        ("SYSTEMS", "VALIDATED"),
        ("CHANNEL", "TESTING"),
        ("CHANNEL", "CONNECTED"),
    ):
        response = api.advance_onboarding_milestone(
            agreement_id,
            factories.build_onboarding_milestone_payload(track, to_status),
            actor,
        )
        latest = get_success_data(response)
    return latest


def open_agreement(api: ApiClient, agreement_id: str, headers: dict = None) -> dict:
    response = api.open_agreement(agreement_id, {}, headers or BSD_HEADERS)
    return get_success_data(response)


def report_revenue(
    api: ApiClient, agreement_id: str, owner_id: str, period_month: str,
    gross_room_revenue: float, **overrides,
) -> dict:
    response = api.report_revenue(
        agreement_id,
        factories.build_revenue_report_payload(period_month, gross_room_revenue, **overrides),
        make_owner_headers(owner_id),
    )
    return get_success_data(response)


def score_inspection(api: ApiClient, agreement_id: str, inspector_headers: dict = None, **overrides) -> dict:
    response = api.create_qa_inspection(
        agreement_id, factories.build_qa_inspection_payload(**overrides), inspector_headers or QA_HEADERS
    )
    return get_success_data(response)


def submit_cure(api: ApiClient, inspection_id: str, owner_id: str, **overrides) -> dict:
    response = api.submit_inspection_cure(
        inspection_id, factories.build_cure_submission_payload(**overrides), make_owner_headers(owner_id)
    )
    return get_success_data(response)


def review_cure(api: ApiClient, inspection_id: str, outcome: str = "PASS",
                reviewer_headers: dict = None, **overrides) -> dict:
    """The reviewing inspector must not be the inspector who scored the
    inspection (PRD §2.10), so callers pass a second inspector's headers."""
    response = api.review_inspection_cure(
        inspection_id, factories.build_cure_review_payload(outcome, **overrides),
        reviewer_headers or QA_HEADERS,
    )
    return get_success_data(response)


def read_agreement_version(api: ApiClient, agreement_id: str, headers: dict = None) -> int:
    """The version a consent decision must echo in expected_agreement_version."""
    data = get_success_data(api.get_agreement(agreement_id, headers or FDM_HEADERS))
    return data["version"]


# ─── Tier 3: an application carried to a named review stage ──────────

def setup_reviewable_application(
    api: ApiClient,
    brand_overrides: dict = None,
    owner_overrides: dict = None,
    application_overrides: dict = None,
    existing_units: list = None,
) -> dict:
    """Brand, optional incumbent units, a STRONG owner and one application
    already moved to UNDER_REVIEW.  Clock parked at 2026-08-01.

    Returns a ``world`` dict that every thicker fixture extends in place, so a
    test can read ``world["owner_id"]`` for owner headers and
    ``world["application"]`` for the latest application snapshot.
    """
    set_clock(api, CLOCK_INTAKE)
    brand = create_solaris_brand(api, **(brand_overrides or {}))
    units = []
    for unit_overrides in existing_units or []:
        units.append(create_existing_unit(api, brand["id"], **unit_overrides))
    owner = create_strong_owner(api, **(owner_overrides or {}))
    application = create_application(
        api, owner["id"], brand["id"], **(application_overrides or {})
    )
    application = start_review(api, application["id"])
    return {
        "brand": brand,
        "brand_id": brand["id"],
        "units": units,
        "owner": owner,
        "owner_id": owner["id"],
        "owner_headers": make_owner_headers(owner["id"]),
        "application": application,
        "application_id": application["id"],
    }


def setup_reviewed_application(
    api: ApiClient,
    world: dict = None,
    capacity_basis: str = "PORTFOLIO_ADJUSTED",
    review_clock: str = CLOCK_REVIEW,
    finalize: bool = True,
    **setup_kwargs,
) -> dict:
    """Both review axes advanced: financial review recorded and the impact
    study run (and finalized unless ``finalize`` is false)."""
    world = world or setup_reviewable_application(api, **setup_kwargs)
    set_clock(api, review_clock)
    world["application"] = run_financial_review(
        api, world["application_id"], capacity_basis
    )
    world["application"] = run_impact_analysis(api, world["application_id"])
    if finalize:
        world["application"] = finalize_impact(api, world["application_id"])
    return world


def setup_approved_application(
    api: ApiClient,
    world: dict = None,
    decision_clock: str = CLOCK_DECISION,
    **setup_kwargs,
) -> dict:
    """An APPROVED application, decided on 2026-09-01 by a manager who is not
    the recorded financial reviewer."""
    world = world if world is not None else setup_reviewed_application(api, **setup_kwargs)
    set_clock(api, decision_clock)
    world["application"] = decide_application(api, world["application_id"], "APPROVE")
    return world


# ─── Tier 4: an agreement carried to a named lifecycle stage ─────────

def setup_drafted_agreement(
    api: ApiClient,
    world: dict = None,
    effective_date: str = DEFAULT_EFFECTIVE_DATE,
    draft_clock: str = CLOCK_DRAFT,
    **setup_kwargs,
) -> dict:
    """A DRAFT license drafted on 2026-09-05 from the approved application."""
    world = world if world is not None else setup_approved_application(api, **setup_kwargs)
    set_clock(api, draft_clock)
    agreement = draft_agreement(api, world["application_id"], effective_date)
    world["agreement"] = agreement
    world["agreement_id"] = agreement["id"]
    return world


def setup_executed_agreement(
    api: ApiClient,
    world: dict = None,
    execute_clock: str = CLOCK_EXECUTE,
    **setup_kwargs,
) -> dict:
    """An EXECUTED license, executed on 2026-09-10 against the live
    application version."""
    world = world if world is not None else setup_drafted_agreement(api, **setup_kwargs)
    set_clock(api, execute_clock)
    world["agreement"] = execute_agreement(
        api, world["agreement_id"], world["application_id"]
    )
    return world


def setup_scoped_plan(
    api: ApiClient,
    world: dict = None,
    scope_lines: list = None,
    scope_clock: str = CLOCK_SCOPE,
    **setup_kwargs,
) -> dict:
    """A SCOPED improvement plan carrying ``scope_lines`` (the three-package
    conversion scope by default), created on 2026-09-12."""
    world = world if world is not None else setup_executed_agreement(api, **setup_kwargs)
    set_clock(api, scope_clock)
    plan = create_pip(api, world["agreement_id"])
    items = []
    for line in scope_lines if scope_lines is not None else THREE_LINE_SCOPE:
        items.append(add_scope_line(api, plan["id"], **line))
    world["plan"] = plan
    world["plan_id"] = plan["id"]
    world["items"] = items
    world["items_by_category"] = {item["category"]: item for item in items}
    return world


def setup_accepted_plan(
    api: ApiClient,
    world: dict = None,
    accept_clock: str = CLOCK_ACCEPT,
    **setup_kwargs,
) -> dict:
    """The owner accepts the plan on 2026-10-05, which stamps every scope
    line's due date from the priority and category day budgets.

    Acceptance is the point at which PRD §3.7 stamps ``base_due_date`` and
    ``due_date`` on every line -- before it, "a line has no due date until the
    plan is accepted".  The snapshots cached by :func:`setup_scoped_plan` were
    taken at creation time and therefore still carry null deadlines, so they
    are re-read here and the world's item views replaced with the accepted
    ones.  Callers that only need an ``id`` are unaffected; callers that read a
    deadline get the stamped value rather than the stale pre-acceptance null.
    """
    world = world if world is not None else setup_scoped_plan(api, **setup_kwargs)
    set_clock(api, accept_clock)
    world["plan"] = accept_pip(api, world["plan_id"], world["owner_id"])
    accepted = get_success_data(
        api.list_pip_items(world["plan_id"], BSD_HEADERS, {"limit": 100})
    )
    by_id = {item["id"]: item for item in accepted}
    cached = world.get("items")
    if cached:
        # Keep the creation order the scoping fixture recorded.
        world["items"] = [by_id.get(item["id"], item) for item in cached]
    else:
        world["items"] = accepted
    world["items_by_category"] = {item["category"]: item for item in world["items"]}
    return world


def setup_open_agreement(
    api: ApiClient,
    world: dict = None,
    open_clock: str = CLOCK_OPEN,
    **setup_kwargs,
) -> dict:
    """An OPEN hotel: the life-safety line verified, all five onboarding rungs
    climbed and the opening recorded on 2026-11-01.

    The default three-package scope carries exactly one CRITICAL line and it
    is the LIFE_SAFETY one, so verifying it clears both safety gates.
    """
    world = world if world is not None else setup_accepted_plan(api, **setup_kwargs)
    life_safety = world["items_by_category"]["LIFE_SAFETY"]
    set_clock(api, CLOCK_COMPLETE)
    complete_item(api, life_safety["id"], world["owner_id"])
    set_clock(api, CLOCK_VERIFY)
    world["items_by_category"]["LIFE_SAFETY"] = verify_item(api, life_safety["id"], "VERIFY")
    climb_onboarding_ladders(api, world["agreement_id"])
    set_clock(api, open_clock)
    world["agreement"] = open_agreement(api, world["agreement_id"])
    return world


# ─── Tier 5: whole scenarios ─────────────────────────────────────────

def setup_agreement_with_two_revenue_periods(
    api: ApiClient,
    world: dict = None,
    first_period: tuple = ("2026-11", 320000.16),
    second_period: tuple = ("2026-12", 480000.16),
    **setup_kwargs,
) -> dict:
    """An OPEN hotel with two surviving revenue periods on the ledger.

    At the default royalty 5.25 and marketing 2.50 the two months assess
    47000.01 and 78000.02 - 47000.01, so the ledger totals are the exact sums
    of the two rounded period lines.
    """
    world = world if world is not None else setup_open_agreement(api, **setup_kwargs)
    set_clock(api, CLOCK_NOVEMBER_REPORT)
    world["agreement"] = report_revenue(
        api, world["agreement_id"], world["owner_id"], first_period[0], first_period[1]
    )
    set_clock(api, CLOCK_DECEMBER_REPORT)
    world["agreement"] = report_revenue(
        api, world["agreement_id"], world["owner_id"], second_period[0], second_period[1]
    )
    return world


def setup_defaulted_plan(
    api: ApiClient,
    world: dict = None,
    sweep_clock: str = "2026-11-20T00:00:00Z",
    **setup_kwargs,
) -> dict:
    """An accepted plan whose CRITICAL life-safety line has gone past its
    2026-11-19 due date, swept on 2026-11-20.

    The escalation drives the plan to DEFAULTED and the license's compliance
    axis to DEFAULT_NOTICE with the transfer block raised, while the license
    status itself stays EXECUTED.
    """
    world = world if world is not None else setup_accepted_plan(api, **setup_kwargs)
    set_clock(api, sweep_clock)
    world["plan"] = run_compliance_sweep(api, world["plan_id"])
    world["agreement"] = get_success_data(
        api.get_agreement(world["agreement_id"], FDM_HEADERS)
    )
    return world


def file_refinance_request(
    api: ApiClient, world: dict, lender_name: str = "Cascade Mezzanine Capital"
) -> dict:
    """A REFINANCE consent request, which needs a lender name and no proposed
    owner, filed by the owner of record."""
    response = api.file_transfer_request(
        world["agreement_id"],
        factories.build_refinance_request_payload(lender_name),
        make_owner_headers(world["owner_id"]),
    )
    request = get_success_data(response)
    world["transfer_request"] = request
    world["transfer_request_id"] = request["id"]
    return request


def file_transfer_request(api: ApiClient, world: dict, proposed_owner_id: str,
                          request_type: str = "TRANSFER") -> dict:
    """A TRANSFER or CHANGE_OF_CONTROL request, which needs a proposed owner
    and must not carry a lender name."""
    response = api.file_transfer_request(
        world["agreement_id"],
        factories.build_transfer_request_payload(
            request_type, proposed_owner_id=proposed_owner_id
        ),
        make_owner_headers(world["owner_id"]),
    )
    request = get_success_data(response)
    world["transfer_request"] = request
    world["transfer_request_id"] = request["id"]
    return request


def setup_inspection_in_cure(
    api: ApiClient,
    world: dict = None,
    inspection_clock: str = "2027-02-01T00:00:00Z",
    inspector_headers: dict = None,
    **overrides,
) -> dict:
    """An OPEN hotel whose latest inspection graded below PASS, so the
    inspection sits in CURE_PENDING and the compliance axis in CURE_PERIOD."""
    world = world if world is not None else setup_open_agreement(api)
    set_clock(api, inspection_clock)
    scores = {
        "cleanliness_score": 60,
        "condition_score": 60,
        "brand_standard_score": 60,
        "guest_experience_score": 60,
        "critical_defect_count": 0,
        "life_safety_defect": False,
    }
    scores.update(overrides)
    inspection = score_inspection(
        api, world["agreement_id"], inspector_headers or QA_HEADERS, **scores
    )
    world.setdefault("inspections", []).append(inspection)
    world["inspection"] = inspection
    world["inspection_id"] = inspection["id"]
    return world


def run_failing_cure_cycle(
    api: ApiClient,
    world: dict,
    inspection_clock: str,
    scoring_headers: dict,
    reviewing_headers: dict,
    cure_clock: str = None,
) -> dict:
    """One full fail-then-fail cycle: score below PASS, the owner submits a
    cure, and a second inspector fails the review, advancing the consecutive
    failure counter by one."""
    set_clock(api, inspection_clock)
    inspection = score_inspection(
        api,
        world["agreement_id"],
        scoring_headers,
        cleanliness_score=55,
        condition_score=55,
        brand_standard_score=55,
        guest_experience_score=55,
        critical_defect_count=0,
        life_safety_defect=False,
    )
    if cure_clock:
        set_clock(api, cure_clock)
    submit_cure(api, inspection["id"], world["owner_id"])
    inspection = review_cure(api, inspection["id"], "FAIL", reviewing_headers)
    world.setdefault("inspections", []).append(inspection)
    world["inspection"] = inspection
    world["inspection_id"] = inspection["id"]
    world["agreement"] = get_success_data(
        api.get_agreement(world["agreement_id"], FDM_HEADERS)
    )
    return world


def setup_termination_pending_agreement(
    api: ApiClient,
    world: dict = None,
    cause: str = "MUTUAL",
    terminate_clock: str = "2027-03-01T00:00:00Z",
    **setup_kwargs,
) -> dict:
    """A TERMINATION_PENDING license: terminated on 2027-03-01, which opens
    the thirty-day de-identification window to 2027-03-31 and sets the
    post-termination obligations to OPEN."""
    world = (
        world
        if world is not None
        else setup_agreement_with_two_revenue_periods(api, **setup_kwargs)
    )
    set_clock(api, terminate_clock)
    response = api.terminate_agreement(
        world["agreement_id"], factories.build_termination_payload(cause), BSD_HEADERS
    )
    world["agreement"] = get_success_data(response)
    return world


def certify_de_identification(api: ApiClient, world: dict, items_completed=None) -> dict:
    response = api.certify_de_identification(
        world["agreement_id"],
        factories.build_de_identification_payload(items_completed),
        make_owner_headers(world["owner_id"]),
    )
    world["agreement"] = get_success_data(response)
    return world["agreement"]


def create_second_owner(api: ApiClient, **overrides) -> dict:
    """A second, distinct Owner row - used wherever the PRD requires two
    different owners (a proposed transferee, or a cross-owner access check).
    Its own id must be threaded into its own headers."""
    payload = {
        "legal_name": "Cascade Harbor Holdings LLC",
        "contact_email": "cfo@cascadeharbor.example",
        "liquid_assets_amount": 6_000_000.00,
        "net_worth_amount": 18_000_000.00,
        "credit_score": 780,
        "existing_units_count": 2,
    }
    payload.update(overrides)
    response = api.create_owner(payload, FDM_HEADERS)
    return get_success_data(response)
