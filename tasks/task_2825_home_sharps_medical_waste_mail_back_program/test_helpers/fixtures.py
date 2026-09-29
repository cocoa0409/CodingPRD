"""Composite setup helpers.

Every test starts against an empty database, so each helper builds all of its
preconditions from scratch through the PRD's own endpoints. Helpers use the
lenient `get_success_data()` validator so a broken precondition reports itself as
a setup failure rather than as a confusing assertion failure.

The helpers thread a plain dict called the *scenario context* through the chain.
Keys accumulate as the chain advances:

    state_rule, packaging_spec, treatment_facility, sponsor, sponsorship_program,
    patient, enrollment, kits (list), kit, return_labels (list), return_label,
    shipments (list), shipment, non_conformance_event, destruction_certificate

Identity threading is mandatory: SponsorRepresentative calls always go through
`make_sponsor_representative_headers(sponsor["id"])` and Patient calls through
`make_patient_headers(patient["id"])`.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import DEFAULT_CLOCK_INSTANT
from .test_users import (
    DESTRUCTION_OFFICER_USER_ID,
    INTAKE_TECHNICIAN_USER_ID,
    TEST_USERS,
    make_destruction_officer_headers,
    make_intake_technician_headers,
    make_patient_headers,
    make_sponsor_representative_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api, to_iso8601: str = DEFAULT_CLOCK_INSTANT) -> dict:
    """Set the server's logical UTC clock (PRD 2.4)."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# --------------------------------------------------------------------------
# Single-entity creators
# --------------------------------------------------------------------------
def create_state_rule(api, **overrides) -> dict:
    return get_success_data(api.create_state_rule(f.state_rule_payload(**overrides), ADMIN))


def create_california_rule(api, **overrides) -> dict:
    """The baseline CONDITIONALLY_EXEMPT rule: mail-back permitted, 30.3 L cap,
    3-year retention, no manifest, 72-hour notification deadline."""
    defaults = dict(
        state_code="CA",
        household_sharps_classification="CONDITIONALLY_EXEMPT",
        mail_back_permitted=True,
        max_container_volume_liters=30.3,
        certificate_retention_years=3,
        requires_state_manifest=False,
        notification_deadline_hours=72,
    )
    defaults.update(overrides)
    return create_state_rule(api, **defaults)


def create_packaging_spec(api, **overrides) -> dict:
    return get_success_data(
        api.create_packaging_spec(f.packaging_spec_payload(**overrides), ADMIN)
    )


def create_treatment_facility(api, state_rule_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_treatment_facility(
            f.treatment_facility_payload(state_rule_id, **overrides), ADMIN
        )
    )


def create_sponsor(api, **overrides) -> dict:
    return get_success_data(api.create_sponsor(f.sponsor_payload(**overrides), ADMIN))


def create_sponsorship_program(api, sponsor_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_sponsorship_program(
            sponsor_id, f.sponsorship_program_payload(**overrides), ADMIN
        )
    )


def create_patient(api, state_rule_id: str, **overrides) -> dict:
    return get_success_data(api.create_patient(f.patient_payload(state_rule_id, **overrides), ADMIN))


def create_eligible_patient(api, state_rule_id: str, **overrides) -> dict:
    """Register a patient and approve their eligibility review, leaving the
    patient in ELIGIBLE."""
    patient = create_patient(api, state_rule_id, **overrides)
    return get_success_data(
        api.review_patient_eligibility(
            patient["id"], f.eligibility_review_payload("APPROVE"), ADMIN
        )
    )


def create_draft_enrollment(
    api, patient_id: str, sponsorship_program_id: str, **overrides
) -> dict:
    return get_success_data(
        api.create_enrollment(
            f.enrollment_payload(patient_id, sponsorship_program_id, **overrides), ADMIN
        )
    )


def create_active_enrollment(
    api, patient_id: str, sponsorship_program_id: str, sponsor_id: str, **overrides
) -> dict:
    """Draft the enrollment, submit it, and record the owning sponsor's APPROVE
    decision, leaving the enrollment ACTIVE and the patient ENROLLED."""
    enrollment = create_draft_enrollment(
        api, patient_id, sponsorship_program_id, **overrides
    )
    get_success_data(api.submit_enrollment(enrollment["id"], ADMIN))
    return get_success_data(
        api.record_sponsor_decision(
            enrollment["id"],
            f.sponsor_decision_payload("APPROVE"),
            make_sponsor_representative_headers(sponsor_id),
        )
    )


# --------------------------------------------------------------------------
# Read-back helpers
# --------------------------------------------------------------------------
def read_program(api, program_id: str) -> dict:
    return get_success_data(api.get_sponsorship_program(program_id, ADMIN))


def read_enrollment(api, enrollment_id: str) -> dict:
    return get_success_data(api.get_enrollment(enrollment_id, ADMIN))


def read_enrollment_version(api, enrollment_id: str) -> int:
    return read_enrollment(api, enrollment_id)["version"]


def read_patient(api, patient_id: str) -> dict:
    return get_success_data(api.get_patient(patient_id, ADMIN))


def read_kit(api, kit_id: str) -> dict:
    return get_success_data(api.get_kit(kit_id, ADMIN))


def read_return_label(api, return_label_id: str) -> dict:
    return get_success_data(api.get_return_label(return_label_id, ADMIN))


def read_shipment(api, shipment_id: str) -> dict:
    return get_success_data(api.get_shipment(shipment_id, ADMIN))


def read_treatment_facility(api, facility_id: str) -> dict:
    return get_success_data(api.get_treatment_facility(facility_id, ADMIN))


def read_non_conformance_event(api, event_id: str) -> dict:
    return get_success_data(api.get_non_conformance_event(event_id, ADMIN))


def read_destruction_certificate(api, certificate_id: str) -> dict:
    return get_success_data(api.get_destruction_certificate(certificate_id, ADMIN))


def read_ledger_entries(api, sponsorship_program_id: str) -> List[dict]:
    """Ledger entries for one program, in `sequence_no` ascending order."""
    return get_success_data(
        api.list_ledger_entries(
            ADMIN, {"sponsorship_program_id": sponsorship_program_id, "limit": 100}
        )
    )


def read_first_non_conformance_event(api, shipment_id: str) -> dict:
    events = get_success_data(
        api.list_shipment_non_conformance_events(shipment_id, ADMIN)
    )
    assert events, f"Setup expected a non-conformance event on shipment {shipment_id}"
    return events[0]


# --------------------------------------------------------------------------
# Tier 2: the program foundations every scenario needs
# --------------------------------------------------------------------------
def setup_program_foundations(
    api,
    *,
    clock: Optional[str] = DEFAULT_CLOCK_INSTANT,
    state_rule_overrides: Optional[dict] = None,
    packaging_spec_overrides: Optional[dict] = None,
    facility_overrides: Optional[dict] = None,
    sponsor_overrides: Optional[dict] = None,
    program_overrides: Optional[dict] = None,
    with_facility: bool = True,
) -> Dict[str, Any]:
    """Seed the regulatory and packaging catalogue plus one funded sponsorship
    program.

    Baseline: clock at 2026-08-01T00:00:00Z, the CA CONDITIONALLY_EXEMPT rule,
    packaging spec PS-A on USPS_PARCEL_SELECT_MAILBACK for UN3291_SHARPS_ONLY,
    treatment facility CA-TF-0001 with a 1000-unit daily intake capacity, and the
    NovaPen MANUFACTURER program NPD-2026 with a 500000-cent ceiling and a
    6000-cent per-kit allowance.
    """
    if clock is not None:
        set_clock(api, clock)
    ctx: Dict[str, Any] = {}
    ctx["state_rule"] = create_california_rule(api, **(state_rule_overrides or {}))
    ctx["packaging_spec"] = create_packaging_spec(api, **(packaging_spec_overrides or {}))
    if with_facility:
        ctx["treatment_facility"] = create_treatment_facility(
            api, ctx["state_rule"]["id"], **(facility_overrides or {})
        )
    ctx["sponsor"] = create_sponsor(api, **(sponsor_overrides or {}))
    ctx["sponsorship_program"] = create_sponsorship_program(
        api, ctx["sponsor"]["id"], **(program_overrides or {})
    )
    ctx["kits"] = []
    ctx["return_labels"] = []
    ctx["shipments"] = []
    return ctx


# --------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts driven off a scenario context
# --------------------------------------------------------------------------
def add_enrolled_patient(
    api,
    ctx: Dict[str, Any],
    *,
    patient_overrides: Optional[dict] = None,
    enrollment_overrides: Optional[dict] = None,
    state_rule_id: Optional[str] = None,
    key: Optional[str] = None,
) -> Dict[str, Any]:
    """Register an eligible patient and drive their enrollment to ACTIVE, which
    cascades the patient ELIGIBLE -> ENROLLED.

    Returns a dict with `patient` and `enrollment`. When `key` is supplied the
    pair is also stored on the context under `patient_<key>` / `enrollment_<key>`;
    otherwise it lands on the context's primary `patient` / `enrollment` keys.
    """
    patient = create_eligible_patient(
        api,
        state_rule_id or ctx["state_rule"]["id"],
        **(patient_overrides or {}),
    )
    enrollment = create_active_enrollment(
        api,
        patient["id"],
        ctx["sponsorship_program"]["id"],
        ctx["sponsor"]["id"],
        **(enrollment_overrides or {}),
    )
    pair = {"patient": patient, "enrollment": enrollment}
    if key:
        ctx[f"patient_{key}"] = patient
        ctx[f"enrollment_{key}"] = enrollment
    else:
        ctx["patient"] = patient
        ctx["enrollment"] = enrollment
    return pair


def issue_kit_for(
    api,
    ctx: Dict[str, Any],
    *,
    enrollment: Optional[dict] = None,
    container_size: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    """Issue a kit under an ACTIVE enrollment, echoing the enrollment's current
    `version` as the mandatory `expected_enrollment_version`."""
    enrollment = enrollment or ctx["enrollment"]
    version = read_enrollment_version(api, enrollment["id"])
    kit = get_success_data(
        api.issue_kit(
            enrollment["id"],
            f.kit_issuance_payload(version, container_size=container_size),
            headers or ADMIN,
        )
    )
    ctx.setdefault("kits", []).append(kit)
    ctx["kit"] = kit
    return kit


def acknowledge_kit(
    api, ctx: Dict[str, Any], *, kit: Optional[dict] = None, patient: Optional[dict] = None
) -> dict:
    """The patient confirms receipt, which begins the filling period."""
    kit = kit or ctx["kit"]
    patient = patient or ctx["patient"]
    updated = get_success_data(
        api.acknowledge_kit_receipt(kit["id"], make_patient_headers(patient["id"]))
    )
    ctx["kit"] = updated
    return updated


def seal_kit_for(
    api,
    ctx: Dict[str, Any],
    *,
    kit: Optional[dict] = None,
    patient: Optional[dict] = None,
    fill_units: int = 69,
    sealed_gross_weight_grams: int = 1400,
) -> dict:
    """The patient seals the filled container, declaring count and gross weight."""
    kit = kit or ctx["kit"]
    patient = patient or ctx["patient"]
    updated = get_success_data(
        api.seal_kit(
            kit["id"],
            f.seal_payload(fill_units, sealed_gross_weight_grams),
            make_patient_headers(patient["id"]),
        )
    )
    ctx["kit"] = updated
    return updated


def print_label_for(
    api,
    ctx: Dict[str, Any],
    *,
    kit: Optional[dict] = None,
    packaging_spec: Optional[dict] = None,
) -> dict:
    """Print a prepaid mail-back return label for a SEALED kit."""
    kit = kit or ctx["kit"]
    spec = packaging_spec or ctx["packaging_spec"]
    label = get_success_data(
        api.print_return_label(kit["id"], f.return_label_payload(spec["id"]), LOGISTICS)
    )
    ctx.setdefault("return_labels", []).append(label)
    ctx["return_label"] = label
    return label


def activate_label_for(
    api,
    ctx: Dict[str, Any],
    *,
    return_label: Optional[dict] = None,
    treatment_facility: Optional[dict] = None,
    scheduled_intake_date: str = "2026-08-10",
    declared_gross_weight_grams: int = 1400,
    **extra,
) -> dict:
    """Tender the parcel to the postal service, which creates the shipment."""
    label = return_label or ctx["return_label"]
    facility = treatment_facility or ctx["treatment_facility"]
    shipment = get_success_data(
        api.activate_return_label(
            label["id"],
            f.label_activation_payload(
                facility["id"],
                scheduled_intake_date=scheduled_intake_date,
                declared_gross_weight_grams=declared_gross_weight_grams,
                **extra,
            ),
            LOGISTICS,
        )
    )
    ctx.setdefault("shipments", []).append(shipment)
    ctx["shipment"] = shipment
    return shipment


def advance_transport(
    api, ctx: Dict[str, Any], event_type: str, *, shipment: Optional[dict] = None
) -> dict:
    """Record one carrier scan on the transport dimension."""
    shipment = shipment or ctx["shipment"]
    updated = get_success_data(
        api.record_transport_event(
            shipment["id"], f.transport_event_payload(event_type), LOGISTICS
        )
    )
    ctx["shipment"] = updated
    return updated


def deliver_shipment(api, ctx: Dict[str, Any], *, shipment: Optional[dict] = None) -> dict:
    """Walk the transport axis TENDERED -> IN_TRANSIT -> DELIVERED."""
    shipment = shipment or ctx["shipment"]
    advance_transport(api, ctx, "IN_TRANSIT", shipment=shipment)
    return advance_transport(api, ctx, "DELIVERED", shipment=shipment)


def screen_shipment(
    api,
    ctx: Dict[str, Any],
    *,
    shipment: Optional[dict] = None,
    outcome: str = "CONFORMING",
    observed_gross_weight_grams: int = 1520,
    reason_code: Optional[str] = None,
    technician_user_id: str = INTAKE_TECHNICIAN_USER_ID,
) -> dict:
    """Screen the delivered parcel; the acting identifier lands on the shipment
    as `screened_by_user_id`."""
    shipment = shipment or ctx["shipment"]
    updated = get_success_data(
        api.screen_shipment_conformance(
            shipment["id"],
            f.conformance_screening_payload(
                outcome, observed_gross_weight_grams, reason_code
            ),
            make_intake_technician_headers(technician_user_id),
        )
    )
    ctx["shipment"] = updated
    if outcome == "NON_CONFORMING":
        ctx["non_conformance_event"] = read_first_non_conformance_event(
            api, shipment["id"]
        )
    return updated


def notify_customer_for(
    api,
    ctx: Dict[str, Any],
    *,
    event: Optional[dict] = None,
    notification_channel: str = "EMAIL",
    technician_user_id: str = INTAKE_TECHNICIAN_USER_ID,
) -> dict:
    """Record the customer notification for a non-conforming shipment."""
    event = event or ctx["non_conformance_event"]
    updated = get_success_data(
        api.notify_customer(
            event["id"],
            f.notify_customer_payload(notification_channel),
            make_intake_technician_headers(technician_user_id),
        )
    )
    ctx["non_conformance_event"] = updated
    return updated


def remediate_for(
    api,
    ctx: Dict[str, Any],
    remediation_action: str,
    *,
    event: Optional[dict] = None,
    technician_user_id: str = INTAKE_TECHNICIAN_USER_ID,
) -> dict:
    """Resolve a notified non-conformance with a state-legal action."""
    event = event or ctx["non_conformance_event"]
    updated = get_success_data(
        api.remediate_non_conformance(
            event["id"],
            f.remediation_payload(remediation_action),
            make_intake_technician_headers(technician_user_id),
        )
    )
    ctx["non_conformance_event"] = updated
    return updated


def certify_destruction_for(
    api,
    ctx: Dict[str, Any],
    *,
    shipment: Optional[dict] = None,
    destroyed_units: int = 69,
    officer_user_id: str = DESTRUCTION_OFFICER_USER_ID,
) -> dict:
    """Issue the destruction certificate, settling the kit's final cost."""
    shipment = shipment or ctx["shipment"]
    certificate = get_success_data(
        api.issue_destruction_certificate(
            shipment["id"],
            f.destruction_certificate_payload(destroyed_units),
            make_destruction_officer_headers(officer_user_id),
        )
    )
    ctx["destruction_certificate"] = certificate
    return certificate


# --------------------------------------------------------------------------
# Tier 3 / 4 / 5: whole-chain shortcuts
# --------------------------------------------------------------------------
def setup_active_enrollment(
    api,
    *,
    patient_overrides: Optional[dict] = None,
    enrollment_overrides: Optional[dict] = None,
    **foundation_kwargs,
) -> Dict[str, Any]:
    """Foundations + one ENROLLED patient on an ACTIVE enrollment.

    The baseline patient is Dana Reyes in CA on INSULIN_PEN_NEEDLES at 14 sharps
    per week with a 30-day cadence and 5 authorized kits, which sizes every kit
    to ONE_QUART with `required_units` 69 and `provisional_cost_cents` 1465.
    """
    ctx = setup_program_foundations(api, **foundation_kwargs)
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides=patient_overrides,
        enrollment_overrides=enrollment_overrides,
    )
    return ctx


def setup_issued_kit(
    api, *, container_size: Optional[str] = None, **kwargs
) -> Dict[str, Any]:
    """... through to a kit in ISSUED with its reservation booked."""
    ctx = setup_active_enrollment(api, **kwargs)
    issue_kit_for(api, ctx, container_size=container_size)
    return ctx


def setup_filling_kit(
    api, *, container_size: Optional[str] = None, **kwargs
) -> Dict[str, Any]:
    """... through to a kit acknowledged by the patient and ACTIVE_FILLING."""
    ctx = setup_issued_kit(api, container_size=container_size, **kwargs)
    acknowledge_kit(api, ctx)
    return ctx


def setup_sealed_kit(
    api,
    *,
    fill_units: int = 69,
    sealed_gross_weight_grams: int = 1400,
    container_size: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """... through to a SEALED kit carrying the patient's declared count/weight."""
    ctx = setup_filling_kit(api, container_size=container_size, **kwargs)
    seal_kit_for(
        api,
        ctx,
        fill_units=fill_units,
        sealed_gross_weight_grams=sealed_gross_weight_grams,
    )
    return ctx


def setup_printed_label(api, **kwargs) -> Dict[str, Any]:
    """... through to a PRINTED return label pinned to the packaging spec."""
    ctx = setup_sealed_kit(api, **kwargs)
    print_label_for(api, ctx)
    return ctx


def setup_tendered_shipment(
    api,
    *,
    scheduled_intake_date: str = "2026-08-10",
    declared_gross_weight_grams: int = 1400,
    activation_extra: Optional[dict] = None,
    **kwargs,
) -> Dict[str, Any]:
    """... through to an activated label and a TENDERED / UNSCREENED shipment."""
    ctx = setup_printed_label(api, **kwargs)
    activate_label_for(
        api,
        ctx,
        scheduled_intake_date=scheduled_intake_date,
        declared_gross_weight_grams=declared_gross_weight_grams,
        **(activation_extra or {}),
    )
    return ctx


def setup_delivered_shipment(api, **kwargs) -> Dict[str, Any]:
    """... through to a DELIVERED / UNSCREENED shipment with the kit RECEIVED."""
    ctx = setup_tendered_shipment(api, **kwargs)
    deliver_shipment(api, ctx)
    return ctx


def setup_screened_shipment(
    api,
    *,
    outcome: str = "CONFORMING",
    observed_gross_weight_grams: int = 1520,
    reason_code: Optional[str] = None,
    technician_user_id: str = INTAKE_TECHNICIAN_USER_ID,
    **kwargs,
) -> Dict[str, Any]:
    """... through to a screened shipment. On a NON_CONFORMING outcome the opened
    event lands on the context as `non_conformance_event`."""
    ctx = setup_delivered_shipment(api, **kwargs)
    screen_shipment(
        api,
        ctx,
        outcome=outcome,
        observed_gross_weight_grams=observed_gross_weight_grams,
        reason_code=reason_code,
        technician_user_id=technician_user_id,
    )
    return ctx


def setup_certifiable_shipment(api, **kwargs) -> Dict[str, Any]:
    """... through to DELIVERED + CONFORMING, which is ready to certify."""
    return setup_screened_shipment(api, outcome="CONFORMING", **kwargs)


def setup_notified_non_conformance(
    api,
    *,
    reason_code: str = "LOOSE_SHARPS_IN_BOX",
    notification_channel: str = "EMAIL",
    observed_gross_weight_grams: int = 1520,
    technician_user_id: str = INTAKE_TECHNICIAN_USER_ID,
    **kwargs,
) -> Dict[str, Any]:
    """... through to a non-conformance event in CUSTOMER_NOTIFIED, ready for a
    remediation decision."""
    ctx = setup_screened_shipment(
        api,
        outcome="NON_CONFORMING",
        observed_gross_weight_grams=observed_gross_weight_grams,
        reason_code=reason_code,
        technician_user_id=technician_user_id,
        **kwargs,
    )
    notify_customer_for(
        api,
        ctx,
        notification_channel=notification_channel,
        technician_user_id=technician_user_id,
    )
    return ctx


def setup_issued_certificate(
    api,
    *,
    destroyed_units: int = 69,
    officer_user_id: str = DESTRUCTION_OFFICER_USER_ID,
    **kwargs,
) -> Dict[str, Any]:
    """... through to an ISSUED destruction certificate and a DESTROYED kit."""
    ctx = setup_certifiable_shipment(api, **kwargs)
    certify_destruction_for(
        api, ctx, destroyed_units=destroyed_units, officer_user_id=officer_user_id
    )
    return ctx


# --------------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# --------------------------------------------------------------------------
def add_screened_kit_cycle(
    api,
    ctx: Dict[str, Any],
    *,
    outcome: str = "NON_CONFORMING",
    reason_code: Optional[str] = "MISSING_ABSORBENT",
    fill_units: int = 69,
    sealed_gross_weight_grams: int = 1400,
    observed_gross_weight_grams: int = 1520,
    scheduled_intake_date: str = "2026-08-10",
    technician_user_id: str = INTAKE_TECHNICIAN_USER_ID,
    screen: bool = True,
) -> Dict[str, Any]:
    """Run one whole custody cycle on an existing ACTIVE enrollment: issue,
    acknowledge, seal, print, activate, deliver and (optionally) screen.

    Each non-conforming cycle adds one weighted event to the patient's history,
    which is how a test walks `screening_risk_score` up to a chosen threshold.
    Returns a dict with the `kit`, `return_label` and `shipment` of this cycle.
    """
    kit = issue_kit_for(api, ctx)
    acknowledge_kit(api, ctx, kit=kit)
    seal_kit_for(
        api,
        ctx,
        kit=kit,
        fill_units=fill_units,
        sealed_gross_weight_grams=sealed_gross_weight_grams,
    )
    label = print_label_for(api, ctx, kit=kit)
    shipment = activate_label_for(
        api,
        ctx,
        return_label=label,
        scheduled_intake_date=scheduled_intake_date,
        declared_gross_weight_grams=sealed_gross_weight_grams,
    )
    deliver_shipment(api, ctx, shipment=shipment)
    if screen:
        screen_shipment(
            api,
            ctx,
            shipment=shipment,
            outcome=outcome,
            observed_gross_weight_grams=observed_gross_weight_grams,
            reason_code=reason_code,
            technician_user_id=technician_user_id,
        )
    return {"kit": read_kit(api, kit["id"]), "return_label": label, "shipment": shipment}


def setup_two_patient_program(
    api,
    *,
    first_patient_overrides: Optional[dict] = None,
    second_patient_overrides: Optional[dict] = None,
    first_enrollment_overrides: Optional[dict] = None,
    second_enrollment_overrides: Optional[dict] = None,
    **foundation_kwargs,
) -> Dict[str, Any]:
    """Foundations plus two ENROLLED patients funded by the same program, created
    in a known order so that `created_at` ascending processing is observable.

    The pairs land on the context as `patient_a`/`enrollment_a` (created first)
    and `patient_b`/`enrollment_b`.
    """
    ctx = setup_program_foundations(api, **foundation_kwargs)
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides=first_patient_overrides
        or {"full_name": "Dana Reyes", "contact_email": "dana@example.com"},
        enrollment_overrides=first_enrollment_overrides,
        key="a",
    )
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides=second_patient_overrides
        or {"full_name": "Ray Alonzo", "contact_email": "ray@example.com"},
        enrollment_overrides=second_enrollment_overrides,
        key="b",
    )
    return ctx
