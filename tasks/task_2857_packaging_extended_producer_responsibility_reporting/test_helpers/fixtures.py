"""Composite setup helpers.

The harness restarts the API server before every individual test, so each test
starts against an empty database. Everything these helpers need is therefore
built from scratch through the endpoints the PRD declares, in the order the PRD
requires: state program, reporting period, producer, stock keeping unit with
components, activation, obligation determination, registration, organisation,
fee schedule, publication, membership, approval, fee payment, report, lines and
submission.

Ownership is threaded explicitly: a `ProducerComplianceOfficer` header always
carries the `Producer.id` it acts for and a `ProAdministrator` header always
carries the `Pro.id`, so distinct owners never share an identity.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    ADMIN_FEE_BPS_HIGH_BREADTH,
    ADMIN_FEE_BPS_HIGH_DEEP,
    ADMIN_FEE_BPS_LOW,
    BASE_MEMBERSHIP_FEE_CENTS,
    BREADTH_REVENUE_THRESHOLD_USD,
    BREADTH_TONNAGE_THRESHOLD_KG,
    DEEP_REVENUE_THRESHOLD_USD,
    DEEP_TONNAGE_THRESHOLD_KG,
    GLASS_ONLY_RATES,
    REGISTRATION_DEADLINE_DEFAULT,
    TIERED_MATERIAL_RATES,
)
from .test_users import (
    REGULATOR_HEADERS,
    make_pro_administrator_headers,
    make_producer_compliance_officer_headers,
)
from .types import (
    EcoModPolicy,
    FeeRoundingOrder,
    ObligationBasis,
)


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------
def officer(producer: Dict[str, Any]) -> Dict[str, str]:
    """Headers of the compliance officer of one producer."""
    return make_producer_compliance_officer_headers(producer["id"])


def admin(pro: Dict[str, Any]) -> Dict[str, str]:
    """Headers of the administrator of one organisation."""
    return make_pro_administrator_headers(pro["id"])


def set_clock(client: ApiClient, instant: str) -> None:
    """Move the logical UTC clock; this mutates no business row."""
    get_success_data(client.set_clock(instant, REGULATOR_HEADERS))


# ---------------------------------------------------------------------------
# Tier 1 — single entities
# ---------------------------------------------------------------------------
def make_state_program(client: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_state_program(f.state_program_payload(**kwargs), REGULATOR_HEADERS),
        201,
    )


def make_breadth_program(
    client: ApiClient, state_code: str = "CA", **overrides: Any
) -> Dict[str, Any]:
    """An ENTITY_LEVEL / BONUS_MALUS / PER_LINE_THEN_SUM program with low thresholds."""
    kwargs: Dict[str, Any] = dict(
        state_code=state_code,
        obligation_basis=ObligationBasis.ENTITY_LEVEL,
        eco_mod_policy=EcoModPolicy.BONUS_MALUS,
        fee_rounding_order=FeeRoundingOrder.PER_LINE_THEN_SUM,
        small_producer_revenue_threshold_usd=BREADTH_REVENUE_THRESHOLD_USD,
        small_producer_tonnage_threshold_kg=BREADTH_TONNAGE_THRESHOLD_KG,
        exempt_product_categories=[],
        verification_required_threshold_kg=3000,
        registration_deadline=REGISTRATION_DEADLINE_DEFAULT,
    )
    kwargs.update(overrides)
    return make_state_program(client, **kwargs)


def make_deep_ca_program(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A GROUP_LEVEL / BONUS_MALUS / PER_LINE_THEN_SUM program."""
    kwargs: Dict[str, Any] = dict(
        state_code="CA",
        obligation_basis=ObligationBasis.GROUP_LEVEL,
        eco_mod_policy=EcoModPolicy.BONUS_MALUS,
        fee_rounding_order=FeeRoundingOrder.PER_LINE_THEN_SUM,
        small_producer_revenue_threshold_usd=DEEP_REVENUE_THRESHOLD_USD,
        small_producer_tonnage_threshold_kg=DEEP_TONNAGE_THRESHOLD_KG,
        exempt_product_categories=["MEDICAL_DEVICE"],
        verification_required_threshold_kg=3000,
        registration_deadline=REGISTRATION_DEADLINE_DEFAULT,
    )
    kwargs.update(overrides)
    return make_state_program(client, **kwargs)


def make_deep_or_program(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """An ENTITY_LEVEL / DISCOUNT_ONLY / SUM_THEN_ROUND program."""
    kwargs: Dict[str, Any] = dict(
        state_code="OR",
        obligation_basis=ObligationBasis.ENTITY_LEVEL,
        eco_mod_policy=EcoModPolicy.DISCOUNT_ONLY,
        fee_rounding_order=FeeRoundingOrder.SUM_THEN_ROUND,
        small_producer_revenue_threshold_usd=DEEP_REVENUE_THRESHOLD_USD,
        small_producer_tonnage_threshold_kg=DEEP_TONNAGE_THRESHOLD_KG,
        exempt_product_categories=[],
        verification_required_threshold_kg=100000,
        registration_deadline=REGISTRATION_DEADLINE_DEFAULT,
    )
    kwargs.update(overrides)
    return make_state_program(client, **kwargs)


def make_reporting_period(
    client: ApiClient, state_program_id: str, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_reporting_period(
            state_program_id, f.reporting_period_payload(**kwargs), REGULATOR_HEADERS
        ),
        201,
    )


def make_producer(client: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_producer(f.producer_payload(**kwargs), REGULATOR_HEADERS), 201
    )


def make_pro(client: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(client.create_pro(f.pro_payload(**kwargs), REGULATOR_HEADERS), 201)


# ---------------------------------------------------------------------------
# Tier 2 — stock keeping units and obligation determination
# ---------------------------------------------------------------------------
def make_sku_with_components(
    client: ApiClient,
    producer: Dict[str, Any],
    components: Optional[List[Dict[str, Any]]] = None,
    activate: bool = True,
    **sku_kwargs: Any,
) -> Dict[str, Any]:
    """Create a unit, append its components one at a time and optionally activate."""
    headers = officer(producer)
    sku = get_success_data(
        client.create_sku(f.sku_payload(producer["id"], **sku_kwargs), headers), 201
    )
    for component in components if components is not None else [f.component_payload()]:
        sku = get_success_data(
            client.add_sku_component(sku["id"], component, headers), 200
        )
    if activate:
        sku = get_success_data(client.activate_sku(sku["id"], None, headers), 200)
    return sku


def glass_mini_sku(client: ApiClient, producer: Dict[str, Any], **sku_kwargs: Any) -> Dict[str, Any]:
    """One 50.00 g READILY_RECYCLABLE GLASS component; 110 units weigh 5.500 kg."""
    kwargs: Dict[str, Any] = dict(units_sold_annual_estimate=110)
    kwargs.update(sku_kwargs)
    return make_sku_with_components(
        client,
        producer,
        components=[f.component_payload(material_type="GLASS", unit_weight_grams=50.0)],
        **kwargs,
    )


def determine_obligation(client: ApiClient, producer: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        client.determine_obligation(producer["id"], None, REGULATOR_HEADERS), 200
    )


def determined_producer(
    client: ApiClient,
    components: Optional[List[Dict[str, Any]]] = None,
    sku_kwargs: Optional[Dict[str, Any]] = None,
    extra_skus: Optional[List[Dict[str, Any]]] = None,
    **producer_kwargs: Any,
) -> Dict[str, Any]:
    """A producer with one or more ACTIVE units and a fresh obligation determination.

    Returns {"producer": ..., "sku": ..., "extra_skus": [...]} with the producer
    re-read after the determination so its rollup and role are the current ones.

    Every unit named in `extra_skus` is created and activated *before* the single
    determination, because the determination may only be run while the producer is
    in `DRAFT` and activating a unit afterwards would only mark the determination
    stale.  Each entry is a `make_sku_with_components` keyword mapping, e.g.
    `{"components": [...], "name": "Pouch F", "units_sold_annual_estimate": 10000}`.
    """
    producer = make_producer(client, **producer_kwargs)
    sku = make_sku_with_components(
        client, producer, components=components, **(sku_kwargs or {})
    )
    extras: List[Dict[str, Any]] = []
    for spec in extra_skus or []:
        spec = dict(spec)
        extras.append(
            make_sku_with_components(
                client, producer, components=spec.pop("components", None), **spec
            )
        )
    producer = determine_obligation(client, producer)
    return {"producer": producer, "sku": sku, "extra_skus": extras}


# ---------------------------------------------------------------------------
# Tier 3 — fee schedules and registrations
# ---------------------------------------------------------------------------
def make_fee_schedule(
    client: ApiClient, pro: Dict[str, Any], state_program_id: str, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_fee_schedule(
            f.fee_schedule_payload(pro["id"], state_program_id, **kwargs), admin(pro)
        ),
        201,
    )


def read_pro_version(client: ApiClient, pro: Dict[str, Any]) -> int:
    return get_success_data(client.get_pro(pro["id"], admin(pro)), 200)["version"]


def publish_fee_schedule(
    client: ApiClient, pro: Dict[str, Any], schedule: Dict[str, Any]
) -> Dict[str, Any]:
    """Read the organisation's current version and publish under that version."""
    pro_version = read_pro_version(client, pro)
    return get_success_data(
        client.publish_fee_schedule(
            schedule["id"], f.publish_payload(pro_version), admin(pro)
        ),
        200,
    )


def published_fee_schedule(
    client: ApiClient, pro: Dict[str, Any], state_program_id: str, **kwargs: Any
) -> Dict[str, Any]:
    schedule = make_fee_schedule(client, pro, state_program_id, **kwargs)
    return publish_fee_schedule(client, pro, schedule)


def make_registration(
    client: ApiClient, producer: Dict[str, Any], state_program_id: str
) -> Dict[str, Any]:
    return get_success_data(
        client.create_registration(
            f.registration_payload(producer["id"], state_program_id), officer(producer)
        ),
        201,
    )


def submit_registration(
    client: ApiClient, producer: Dict[str, Any], registration: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(
        client.submit_registration(registration["id"], None, officer(producer)), 200
    )


def accept_registration(client: ApiClient, registration: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        client.decide_registration(
            registration["id"], f.decision_payload("ACCEPT"), REGULATOR_HEADERS
        ),
        200,
    )


def active_registration(
    client: ApiClient, producer: Dict[str, Any], state_program_id: str
) -> Dict[str, Any]:
    """Create, submit and accept a registration, returning the ACTIVE row."""
    registration = make_registration(client, producer, state_program_id)
    submit_registration(client, producer, registration)
    return accept_registration(client, registration)


# ---------------------------------------------------------------------------
# Tier 4 — memberships, reports and lines
# ---------------------------------------------------------------------------
def read_registration_version(
    client: ApiClient, producer: Dict[str, Any], registration_id: str
) -> int:
    return get_success_data(
        client.get_registration(registration_id, officer(producer)), 200
    )["version"]


def apply_for_membership(
    client: ApiClient,
    producer: Dict[str, Any],
    registration: Dict[str, Any],
    pro: Dict[str, Any],
    schedule: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply under optimistic concurrency on the registration's current version."""
    version = read_registration_version(client, producer, registration["id"])
    return get_success_data(
        client.create_membership(
            f.membership_payload(registration["id"], pro["id"], schedule["id"], version),
            officer(producer),
        ),
        201,
    )


def approve_membership(
    client: ApiClient, pro: Dict[str, Any], membership: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(
        client.decide_membership(
            membership["id"], f.decision_payload("APPROVE"), admin(pro)
        ),
        200,
    )


def pay_membership_fee(
    client: ApiClient,
    pro: Dict[str, Any],
    membership: Dict[str, Any],
    amount_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Pay exactly the assessed fee unless the caller names a different amount."""
    amount = membership["membership_fee_cents"] if amount_cents is None else amount_cents
    return get_success_data(
        client.record_fee_payment(membership["id"], f.fee_payment_payload(amount), admin(pro)),
        200,
    )


def paid_membership(
    client: ApiClient,
    producer: Dict[str, Any],
    registration: Dict[str, Any],
    pro: Dict[str, Any],
    schedule: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply, approve and pay the assessed fee exactly; returns the PAID row."""
    membership = apply_for_membership(client, producer, registration, pro, schedule)
    membership = approve_membership(client, pro, membership)
    return pay_membership_fee(client, pro, membership)


def make_report(
    client: ApiClient,
    producer: Dict[str, Any],
    registration: Dict[str, Any],
    period: Dict[str, Any],
) -> Dict[str, Any]:
    return get_success_data(
        client.create_report(
            f.report_payload(registration["id"], period["id"]), officer(producer)
        ),
        201,
    )


def add_line(
    client: ApiClient,
    producer: Dict[str, Any],
    report: Dict[str, Any],
    sku: Dict[str, Any],
    units_sold: int,
) -> Dict[str, Any]:
    return get_success_data(
        client.add_report_line(
            report["id"], f.report_line_payload(sku["id"], units_sold), officer(producer)
        ),
        201,
    )


def submit_report(
    client: ApiClient, producer: Dict[str, Any], report: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(client.submit_report(report["id"], None, officer(producer)), 200)


def assess_report(
    client: ApiClient, pro: Dict[str, Any], report: Dict[str, Any], variant: str
) -> Dict[str, Any]:
    return get_success_data(
        client.assess_report(report["id"], f.assess_payload(variant), admin(pro)), 200
    )


def issue_invoice(
    client: ApiClient,
    pro: Dict[str, Any],
    report: Dict[str, Any],
    membership: Dict[str, Any],
) -> Dict[str, Any]:
    return get_success_data(
        client.create_invoice(f.invoice_payload(report["id"], membership["id"]), admin(pro)),
        201,
    )


def assign_engagement(
    client: ApiClient,
    report: Dict[str, Any],
    verifier_user_id: str,
    fieldwork_start: str = "2026-08-05",
    fieldwork_end: str = "2026-08-10",
    regulator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_engagement(
            f.engagement_payload(
                report["id"], verifier_user_id, fieldwork_start, fieldwork_end
            ),
            regulator_headers or REGULATOR_HEADERS,
        ),
        201,
    )


def start_engagement(
    client: ApiClient, engagement: Dict[str, Any], verifier_headers: Dict[str, str]
) -> Dict[str, Any]:
    return get_success_data(
        client.start_engagement(engagement["id"], None, verifier_headers), 200
    )


def issue_opinion(
    client: ApiClient,
    engagement: Dict[str, Any],
    verifier_headers: Dict[str, str],
    opinion: str,
    findings_note: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.issue_opinion(
            engagement["id"], f.opinion_payload(opinion, findings_note), verifier_headers
        ),
        200,
    )


def verify_report(
    client: ApiClient,
    report: Dict[str, Any],
    verifier_user_id: str,
    verifier_headers: Dict[str, str],
    fieldwork_start: str = "2026-08-05",
    fieldwork_end: str = "2026-08-10",
) -> Dict[str, Any]:
    """Assign, start and issue an UNQUALIFIED opinion so the report reaches VERIFIED."""
    engagement = assign_engagement(
        client, report, verifier_user_id, fieldwork_start, fieldwork_end
    )
    start_engagement(client, engagement, verifier_headers)
    return issue_opinion(client, engagement, verifier_headers, "UNQUALIFIED")


# ---------------------------------------------------------------------------
# Tier 5 — whole chains
# ---------------------------------------------------------------------------
def _build_chain(
    client: ApiClient,
    program: Dict[str, Any],
    period_kwargs: Dict[str, Any],
    producer_kwargs: Dict[str, Any],
    sku_components: Optional[List[Dict[str, Any]]],
    sku_kwargs: Dict[str, Any],
    schedule_kwargs: Dict[str, Any],
    pro_kwargs: Dict[str, Any],
    line_units: Optional[int],
    with_membership: bool,
    with_report: bool,
    submit: bool,
    extra_skus: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    period = make_reporting_period(client, program["id"], **period_kwargs)
    built = determined_producer(
        client,
        components=sku_components,
        sku_kwargs=sku_kwargs,
        extra_skus=extra_skus,
        **producer_kwargs,
    )
    producer, sku = built["producer"], built["sku"]
    registration = active_registration(client, producer, program["id"])
    pro = make_pro(client, **pro_kwargs)
    schedule = published_fee_schedule(client, pro, program["id"], **schedule_kwargs)

    chain: Dict[str, Any] = {
        "program": program,
        "period": period,
        "producer": producer,
        "sku": sku,
        "extra_skus": built["extra_skus"],
        "registration": registration,
        "pro": pro,
        "schedule": schedule,
        "membership": None,
        "report": None,
        "line": None,
        "officer_headers": officer(producer),
        "admin_headers": admin(pro),
    }
    if not with_membership:
        return chain
    chain["membership"] = paid_membership(client, producer, registration, pro, schedule)
    if not with_report:
        return chain
    report = make_report(client, producer, registration, period)
    chain["report"] = report
    if line_units is not None:
        chain["line"] = add_line(client, producer, report, sku, line_units)
    if submit:
        chain["report"] = submit_report(client, producer, report)
    return chain


def base_ca_chain(
    client: ApiClient,
    state_code: str = "CA",
    program_overrides: Optional[Dict[str, Any]] = None,
    period_overrides: Optional[Dict[str, Any]] = None,
    producer_overrides: Optional[Dict[str, Any]] = None,
    sku_components: Optional[List[Dict[str, Any]]] = None,
    sku_overrides: Optional[Dict[str, Any]] = None,
    schedule_overrides: Optional[Dict[str, Any]] = None,
    pro_overrides: Optional[Dict[str, Any]] = None,
    line_units: Optional[int] = 110,
    with_membership: bool = True,
    with_report: bool = True,
    submit: bool = True,
    extra_skus: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """The standard chain at the default clock instant of 2026-08-01T00:00:00Z.

    One ENTITY_LEVEL / BONUS_MALUS / PER_LINE_THEN_SUM program, one open period,
    one obligated producer with a single 50.00 g GLASS component, an ACTIVE
    registration, a published GLASS-only schedule at 9 cents per kilogram, a PAID
    membership and one submitted report of 110 units weighing 5.500 kg.
    """
    program = make_breadth_program(client, state_code=state_code, **(program_overrides or {}))
    period_kwargs: Dict[str, Any] = dict(
        period_label=f"{state_code}-2026-H1",
        data_start="2026-07-01",
        data_end="2027-01-01",
        submission_open="2026-07-01T00:00:00Z",
        submission_deadline="2026-12-31T23:59:59Z",
        correction_window_days=30,
    )
    period_kwargs.update(period_overrides or {})
    producer_kwargs: Dict[str, Any] = dict(
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        brand_owner_flag=True,
        contact_email="compliance@northlake.example",
    )
    producer_kwargs.update(producer_overrides or {})
    sku_kwargs: Dict[str, Any] = dict(
        name="Sparkling Water 750ml",
        product_category="BEVERAGE",
        units_sold_annual_estimate=110,
    )
    sku_kwargs.update(sku_overrides or {})
    schedule_kwargs: Dict[str, Any] = dict(
        effective_from="2026-01-01",
        effective_to=None,
        membership_fee_cents=BASE_MEMBERSHIP_FEE_CENTS,
        admin_fee_bps_low=ADMIN_FEE_BPS_LOW,
        admin_fee_bps_high=ADMIN_FEE_BPS_HIGH_BREADTH,
        material_rates=[dict(row) for row in GLASS_ONLY_RATES],
    )
    schedule_kwargs.update(schedule_overrides or {})
    return _build_chain(
        client,
        program,
        period_kwargs,
        producer_kwargs,
        sku_components
        if sku_components is not None
        else [f.component_payload(material_type="GLASS", unit_weight_grams=50.0)],
        sku_kwargs,
        schedule_kwargs,
        dict(pro_overrides or {}),
        line_units,
        with_membership,
        with_report,
        submit,
        extra_skus=extra_skus,
    )


def deep_ca_chain(
    client: ApiClient,
    program_overrides: Optional[Dict[str, Any]] = None,
    period_overrides: Optional[Dict[str, Any]] = None,
    producer_overrides: Optional[Dict[str, Any]] = None,
    sku_components: Optional[List[Dict[str, Any]]] = None,
    sku_overrides: Optional[Dict[str, Any]] = None,
    schedule_overrides: Optional[Dict[str, Any]] = None,
    pro_overrides: Optional[Dict[str, Any]] = None,
    line_units: Optional[int] = 110,
    with_membership: bool = True,
    with_report: bool = True,
    submit: bool = True,
    extra_skus: Optional[List[Dict[str, Any]]] = None,
    clock: Optional[str] = "2026-09-01T00:00:00Z",
) -> Dict[str, Any]:
    """The deep chain: a GROUP_LEVEL CA program at a clock of 2026-09-01T00:00:00Z.

    The period CA-2026-H2 opens on 2026-08-15T00:00:00Z and closes on
    2026-09-30T23:59:59Z, so the clock sits inside the submission window.
    """
    if clock is not None:
        set_clock(client, clock)
    program = make_deep_ca_program(client, **(program_overrides or {}))
    period_kwargs: Dict[str, Any] = dict(
        period_label="CA-2026-H2",
        data_start="2026-07-01",
        data_end="2027-01-01",
        submission_open="2026-08-15T00:00:00Z",
        submission_deadline="2026-09-30T23:59:59Z",
        correction_window_days=30,
    )
    period_kwargs.update(period_overrides or {})
    producer_kwargs: Dict[str, Any] = dict(
        legal_name="Cascade Stewardship Foods",
        annual_gross_revenue_usd=8000000,
        brand_owner_flag=True,
        contact_email="epr@cascade.example",
    )
    producer_kwargs.update(producer_overrides or {})
    sku_kwargs: Dict[str, Any] = dict(
        name="Sparkling Water 750ml",
        product_category="BEVERAGE",
        units_sold_annual_estimate=110,
    )
    sku_kwargs.update(sku_overrides or {})
    schedule_kwargs: Dict[str, Any] = dict(
        effective_from="2026-07-01",
        effective_to=None,
        membership_fee_cents=BASE_MEMBERSHIP_FEE_CENTS,
        admin_fee_bps_low=ADMIN_FEE_BPS_LOW,
        admin_fee_bps_high=ADMIN_FEE_BPS_HIGH_DEEP,
        material_rates=[dict(row) for row in GLASS_ONLY_RATES],
    )
    schedule_kwargs.update(schedule_overrides or {})
    return _build_chain(
        client,
        program,
        period_kwargs,
        producer_kwargs,
        sku_components
        if sku_components is not None
        else [f.component_payload(material_type="GLASS", unit_weight_grams=50.0)],
        sku_kwargs,
        schedule_kwargs,
        dict(pro_overrides or {}),
        line_units,
        with_membership,
        with_report,
        submit,
        extra_skus=extra_skus,
    )


def tiered_rates() -> List[Dict[str, Any]]:
    """All four materials with their banded rates."""
    return [dict(row) for row in TIERED_MATERIAL_RATES]
