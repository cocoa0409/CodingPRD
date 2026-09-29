"""
Scenario builders.

The harness restarts the server before every single test, so each test opens on an empty
database with the logical clock at its epoch. Nothing can be shared between tests: every
precondition has to be built from scratch, through the public endpoints, in the order the
specification allows. That is what this module does.

The builders are layered:

* primitives — one call each, for the six reference entities and the clock;
* `build_world` — the reference data every clinical scenario needs, in one call;
* progression builders — `admitted_stay`, `discharged_stay`, `finalized_stay`, each
  reaching one further point along the lifecycle and returning everything the caller may
  want to assert on;
* accumulation builders — `file_required_notes`, `interrupt_and_return`,
  `progress_plan_to_liberation_eligible`, for the counters that only move by repetition;
* read helpers — `read_stay`, `sole_determination`, `sole_review`, `queries_of`, which
  re-read state after a cascade instead of trusting the response that triggered it.

Every builder asserts its own success, so a test that fails is failing on its own subject
and not on a silently broken precondition.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import ApiClient
from .constants import CLOCK_EPOCH, REQUIRED_DISCIPLINES
from .test_users import (
    ANALYST_HEADERS,
    INTAKE_HEADERS,
    NURSE_2_HEADERS,
    NURSE_HEADERS,
    OFFICER_HEADERS,
    make_attending_physician_headers,
)
from .types import (
    DischargeDisposition,
    ReviewOutcome,
)

Json = Dict[str, Any]


@dataclass
class World:
    """The reference data a clinical scenario is built on top of."""

    hospital: Json
    patient: Json
    physician: Json
    drg_rate: Json
    criteria_set: Json
    period: Json

    @property
    def hospital_id(self) -> str:
        return self.hospital["id"]

    @property
    def patient_id(self) -> str:
        return self.patient["id"]

    @property
    def patient_version(self) -> int:
        return self.patient["version"]

    @property
    def physician_id(self) -> str:
        return self.physician["id"]

    @property
    def physician_headers(self) -> Json:
        """Headers for the physician of record of this world."""
        return make_attending_physician_headers(self.physician["id"])

    @property
    def drg_rate_id(self) -> str:
        return self.drg_rate["id"]

    @property
    def criteria_set_id(self) -> str:
        return self.criteria_set["id"]

    @property
    def period_id(self) -> str:
        return self.period["id"]


@dataclass
class Admission:
    """A stay and everything upstream and downstream of it that a test may assert on."""

    world: World
    referral: Json
    stay: Json
    determination: Optional[Json] = None
    review: Optional[Json] = None
    queries: List[Json] = field(default_factory=list)

    @property
    def stay_id(self) -> str:
        return self.stay["id"]

    @property
    def referral_id(self) -> str:
        return self.referral["id"]

    @property
    def determination_id(self) -> str:
        assert self.determination is not None, "this stay has no determination yet"
        return self.determination["id"]

    @property
    def review_id(self) -> str:
        assert self.review is not None, "this stay has no denial-risk review yet"
        return self.review["id"]


# ── The logical clock ────────────────────────────────
def advance_clock(api: ApiClient, current_utc: str, headers: Optional[Json] = None) -> Json:
    """Move the logical clock forward and return the clock response."""
    response = api.set_clock(current_utc, headers=headers or OFFICER_HEADERS)
    return get_success_data(response, expected_status=200)


def clock_epoch() -> str:
    """The instant the clock reads before anybody sets it."""
    return CLOCK_EPOCH


# ── Reference-entity primitives ──────────────────────
def add_hospital(api: ApiClient, headers: Optional[Json] = None, **overrides: Any) -> Json:
    response = api.create_referring_hospital(
        factories.referring_hospital_payload(**overrides), headers=headers or OFFICER_HEADERS
    )
    return get_success_data(response, expected_status=201)


def add_patient(api: ApiClient, headers: Optional[Json] = None, **overrides: Any) -> Json:
    response = api.create_patient(
        factories.patient_payload(**overrides), headers=headers or OFFICER_HEADERS
    )
    return get_success_data(response, expected_status=201)


def add_physician(api: ApiClient, headers: Optional[Json] = None, **overrides: Any) -> Json:
    response = api.create_physician(
        factories.physician_payload(**overrides), headers=headers or OFFICER_HEADERS
    )
    return get_success_data(response, expected_status=201)


def suspend_physician(api: ApiClient, physician_id: str, headers: Optional[Json] = None) -> Json:
    response = api.set_credential_status(
        physician_id,
        factories.credential_status_payload("SUSPENDED"),
        headers=headers or OFFICER_HEADERS,
    )
    return get_success_data(response, expected_status=200)


def reinstate_physician(api: ApiClient, physician_id: str, headers: Optional[Json] = None) -> Json:
    response = api.set_credential_status(
        physician_id,
        factories.credential_status_payload("ACTIVE"),
        headers=headers or OFFICER_HEADERS,
    )
    return get_success_data(response, expected_status=200)


def add_drg_rate(api: ApiClient, headers: Optional[Json] = None, **overrides: Any) -> Json:
    response = api.create_drg_rate(
        factories.drg_rate_payload(**overrides), headers=headers or OFFICER_HEADERS
    )
    return get_success_data(response, expected_status=201)


def publish_criteria_set(api: ApiClient, headers: Optional[Json] = None, **overrides: Any) -> Json:
    response = api.create_criteria_set(
        factories.criteria_set_payload(**overrides), headers=headers or OFFICER_HEADERS
    )
    return get_success_data(response, expected_status=201)


def open_period(api: ApiClient, headers: Optional[Json] = None, **overrides: Any) -> Json:
    response = api.create_period(
        factories.period_payload(**overrides), headers=headers or OFFICER_HEADERS
    )
    return get_success_data(response, expected_status=201)


def close_period(api: ApiClient, period_id: str, headers: Optional[Json] = None) -> Json:
    response = api.close_period(period_id, headers=headers or OFFICER_HEADERS)
    return get_success_data(response, expected_status=200)


def recompute_shares(api: ApiClient, period_id: str, headers: Optional[Json] = None) -> Json:
    response = api.recompute_referral_shares(period_id, headers=headers or OFFICER_HEADERS)
    return get_success_data(response, expected_status=200)


def build_world(
    api: ApiClient,
    hospital: Optional[Json] = None,
    patient: Optional[Json] = None,
    physician: Optional[Json] = None,
    drg_rate: Optional[Json] = None,
    criteria_set: Optional[Json] = None,
    period: Optional[Json] = None,
    with_period: bool = True,
) -> World:
    """Register one of each reference entity and return their records.

    Each argument is a dict of field overrides for that entity, so a scenario that needs
    a colocated referral source or a shorter DRG changes only what it cares about:

        world = fixtures.build_world(api, hospital={"is_colocated": True})

    `with_period=False` leaves no cost reporting period open, which is how a test probes
    the no-open-period gate.
    """
    return World(
        hospital=add_hospital(api, **(hospital or {})),
        patient=add_patient(api, **(patient or {})),
        physician=add_physician(api, **(physician or {})),
        drg_rate=add_drg_rate(api, **(drg_rate or {})),
        criteria_set=publish_criteria_set(api, **(criteria_set or {})),
        period=open_period(api, **(period or {})) if with_period else {},
    )


# ── Reads ────────────────────────────────────────────
def read_hospital(api: ApiClient, hospital_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(
        api.get_referring_hospital(hospital_id, headers=headers or OFFICER_HEADERS)
    )


def read_patient(api: ApiClient, patient_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(api.get_patient(patient_id, headers=headers or OFFICER_HEADERS))


def read_period(api: ApiClient, period_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(api.get_period(period_id, headers=headers or OFFICER_HEADERS))


def read_criteria_set(api: ApiClient, criteria_set_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(
        api.get_criteria_set(criteria_set_id, headers=headers or OFFICER_HEADERS)
    )


def read_referral(api: ApiClient, referral_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(api.get_referral(referral_id, headers=headers or INTAKE_HEADERS))


def read_stay(api: ApiClient, stay_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(api.get_stay(stay_id, headers=headers or NURSE_HEADERS))


def read_plan(api: ApiClient, plan_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(api.get_weaning_plan(plan_id, headers=headers or NURSE_HEADERS))


def read_determination(api: ApiClient, determination_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(
        api.get_determination(determination_id, headers=headers or ANALYST_HEADERS)
    )


def read_review(api: ApiClient, review_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(api.get_review(review_id, headers=headers or OFFICER_HEADERS))


def read_query(api: ApiClient, query_id: str, headers: Optional[Json] = None) -> Json:
    return get_success_data(api.get_query(query_id, headers=headers or NURSE_HEADERS))


def determinations_of(api: ApiClient, stay_id: str, headers: Optional[Json] = None, **params: Any) -> List[Json]:
    """A stay's determinations, newest first, as the specification lists them."""
    data, _meta = validate_paginated(
        api.list_stay_determinations(stay_id, params=params or None, headers=headers or ANALYST_HEADERS)
    )
    return data


def reviews_of(api: ApiClient, stay_id: str, headers: Optional[Json] = None, **params: Any) -> List[Json]:
    data, _meta = validate_paginated(
        api.list_stay_reviews(stay_id, params=params or None, headers=headers or OFFICER_HEADERS)
    )
    return data


def queries_of(api: ApiClient, headers: Optional[Json] = None, **params: Any) -> List[Json]:
    """Documentation queries, filtered by any of the declared query parameters."""
    data, _meta = validate_paginated(
        api.list_queries(params=params or None, headers=headers or NURSE_HEADERS)
    )
    return data


def notes_of(api: ApiClient, stay_id: str, headers: Optional[Json] = None, **params: Any) -> List[Json]:
    data, _meta = validate_paginated(
        api.list_idt_notes(stay_id, params=params or None, headers=headers or NURSE_HEADERS)
    )
    return data


def interruptions_of(api: ApiClient, stay_id: str, headers: Optional[Json] = None, **params: Any) -> List[Json]:
    data, _meta = validate_paginated(
        api.list_interruptions(stay_id, params=params or None, headers=headers or NURSE_HEADERS)
    )
    return data


def live_determination(api: ApiClient, stay_id: str) -> Optional[Json]:
    """The stay's one determination in DRAFT or FINAL, or None if it holds neither."""
    live = [d for d in determinations_of(api, stay_id) if d["status"] in ("DRAFT", "FINAL")]
    assert len(live) <= 1, "a stay may hold at most one live determination, found {}".format(
        len(live)
    )
    return live[0] if live else None


def sole_determination(api: ApiClient, stay_id: str) -> Json:
    """The stay's live determination, asserting that exactly one exists."""
    determination = live_determination(api, stay_id)
    assert determination is not None, "stay {} holds no live determination".format(stay_id)
    return determination


def sole_review(api: ApiClient, stay_id: str) -> Json:
    """The stay's one live denial-risk review, asserting that exactly one exists."""
    reviews = [r for r in reviews_of(api, stay_id) if r["status"] != "VOIDED"]
    assert len(reviews) == 1, "expected one live review on stay {}, found {}".format(
        stay_id, len(reviews)
    )
    return reviews[0]


# ── Referral intake and screening ────────────────────
def create_referral(
    api: ApiClient,
    world: World,
    clinicals: Optional[Json] = None,
    patient_id: Optional[str] = None,
    patient_version: Optional[int] = None,
    hospital_id: Optional[str] = None,
    drg_rate_id: Optional[str] = None,
    headers: Optional[Json] = None,
    **overrides: Any
) -> Json:
    """Create a referral in `RECEIVED`, defaulting to this world's patient, source and DRG.

    `clinicals` replaces the five screening inputs wholesale; individual keyword overrides
    replace them one at a time, which is how a test leaves exactly one of them null.
    """
    payload = factories.referral_payload(
        patient_id if patient_id is not None else world.patient_id,
        hospital_id if hospital_id is not None else world.hospital_id,
        drg_rate_id if drg_rate_id is not None else world.drg_rate_id,
        patient_version if patient_version is not None else world.patient_version,
        clinicals=clinicals,
        **overrides
    )
    response = api.create_referral(payload, headers=headers or INTAKE_HEADERS)
    return get_success_data(response, expected_status=201)


def screen_referral(api: ApiClient, referral_id: str, headers: Optional[Json] = None) -> Json:
    response = api.screen_referral(referral_id, headers=headers or INTAKE_HEADERS)
    return get_success_data(response, expected_status=200)


def submit_info(api: ApiClient, referral_id: str, headers: Optional[Json] = None, **fields: Any) -> Json:
    response = api.submit_referral_info(
        referral_id, factories.submit_info_payload(**fields), headers=headers or INTAKE_HEADERS
    )
    return get_success_data(response, expected_status=200)


def qualified_referral(
    api: ApiClient,
    world: World,
    clinicals: Optional[Json] = None,
    expected_track: str = "PMV",
    **overrides: Any
) -> Json:
    """A referral created and screened through to `CRITERIA_MET`, ready to admit."""
    referral = create_referral(api, world, clinicals=clinicals, **overrides)
    screened = screen_referral(api, referral["id"])
    assert screened["status"] == "CRITERIA_MET", (
        "expected a screened referral in CRITERIA_MET, got {!r} with track {!r} and "
        "missing_fields {!r}".format(
            screened["status"], screened.get("qualifying_track"), screened.get("missing_fields")
        )
    )
    assert screened["qualifying_track"] == expected_track, (
        "expected qualifying_track {!r}, got {!r}".format(
            expected_track, screened["qualifying_track"]
        )
    )
    return screened


# ── Admission ────────────────────────────────────────
def admit(
    api: ApiClient,
    referral_id: str,
    admitted_at: Optional[str] = None,
    override_reason: Optional[str] = None,
    headers: Optional[Json] = None,
) -> Json:
    """Admit a qualifying referral and return the new stay."""
    response = api.admit_referral(
        referral_id,
        factories.admit_payload(admitted_at=admitted_at, override_reason=override_reason),
        headers=headers or INTAKE_HEADERS,
    )
    return get_success_data(response, expected_status=201)


def admitted_stay(
    api: ApiClient,
    world: Optional[World] = None,
    clinicals: Optional[Json] = None,
    admitted_at: Optional[str] = None,
    override_reason: Optional[str] = None,
    expected_track: str = "PMV",
    **referral_overrides: Any
) -> Admission:
    """Reference data, a screened referral and an admitted stay, in one call.

    Passing an existing `world` reuses its reference data, which is how a scenario admits
    a second patient into the same period.
    """
    world = world if world is not None else build_world(api)
    referral = qualified_referral(
        api, world, clinicals=clinicals, expected_track=expected_track, **referral_overrides
    )
    stay = admit(
        api, referral["id"], admitted_at=admitted_at, override_reason=override_reason
    )
    return Admission(world=world, referral=referral, stay=stay)


# ── Interdisciplinary notes ──────────────────────────
def file_note(
    api: ApiClient,
    stay_id: str,
    discipline: str,
    headers: Optional[Json] = None,
    **overrides: Any
) -> Json:
    response = api.create_idt_note(
        stay_id,
        factories.idt_note_payload(discipline=discipline, **overrides),
        headers=headers or NURSE_HEADERS,
    )
    return get_success_data(response, expected_status=201)


def file_required_notes(
    api: ApiClient,
    stay_id: str,
    disciplines: Sequence[str] = REQUIRED_DISCIPLINES,
    headers: Optional[Json] = None,
) -> List[Json]:
    """File one note in each mandatory discipline, so `missing_discipline_count` is 0."""
    return [file_note(api, stay_id, discipline, headers=headers) for discipline in disciplines]


def refresh_progression_notes(
    api: ApiClient, stay_id: str, headers: Optional[Json] = None
) -> List[Json]:
    """File the two notes a tolerated trial requires, at the current logical instant."""
    return [
        file_note(api, stay_id, "RESPIRATORY_THERAPY", headers=headers),
        file_note(api, stay_id, "PHYSICIAN", headers=headers),
    ]


# ── The weaning protocol ─────────────────────────────
def open_weaning_plan(
    api: ApiClient,
    stay_id: str,
    protocol_label: Optional[str] = None,
    vent_hours_total: Optional[float] = None,
    headers: Optional[Json] = None,
) -> Json:
    response = api.create_weaning_plan(
        stay_id,
        factories.weaning_plan_payload(
            protocol_label=protocol_label, vent_hours_total=vent_hours_total
        ),
        headers=headers or NURSE_HEADERS,
    )
    return get_success_data(response, expected_status=201)


def record_sbt(
    api: ApiClient,
    plan_id: str,
    outcome: str = "TOLERATED",
    sbt_hours: float = 2,
    vent_hours_since_last: float = 4,
    headers: Optional[Json] = None,
) -> Json:
    response = api.record_sbt(
        plan_id,
        factories.sbt_payload(
            outcome=outcome, sbt_hours=sbt_hours, vent_hours_since_last=vent_hours_since_last
        ),
        headers=headers or NURSE_HEADERS,
    )
    return get_success_data(response, expected_status=200)


def tolerated_sbt(
    api: ApiClient,
    stay_id: str,
    plan_id: str,
    sbt_hours: float = 2,
    vent_hours_since_last: float = 4,
) -> Json:
    """Refresh the two required notes, then record one tolerated trial.

    A tolerated record is gated on respiratory-therapy and physician notes filed at or
    after the plan's last progression, so the notes are re-filed on every call.
    """
    refresh_progression_notes(api, stay_id)
    return record_sbt(
        api,
        plan_id,
        outcome="TOLERATED",
        sbt_hours=sbt_hours,
        vent_hours_since_last=vent_hours_since_last,
    )


def failed_sbt(
    api: ApiClient, plan_id: str, sbt_hours: float = 1, vent_hours_since_last: float = 4
) -> Json:
    """A failed trial, which carries no documentation precondition."""
    return record_sbt(
        api,
        plan_id,
        outcome="FAILED",
        sbt_hours=sbt_hours,
        vent_hours_since_last=vent_hours_since_last,
    )


def close_plan(
    api: ApiClient, plan_id: str, outcome: str, physician_headers: Json
) -> Json:
    """Close a weaning plan; only a credentialed pulmonologist may do this."""
    response = api.close_weaning_plan(
        plan_id, factories.close_plan_payload(outcome=outcome), headers=physician_headers
    )
    return get_success_data(response, expected_status=200)


def liberation_eligible_plan(
    api: ApiClient, admission: Admission, vent_hours_since_last: float = 4
) -> Json:
    """A plan carried to `PROGRESSING` at step 2, where a `LIBERATED` close is legal."""
    plan = open_weaning_plan(api, admission.stay_id)
    tolerated_sbt(api, admission.stay_id, plan["id"], vent_hours_since_last=vent_hours_since_last)
    return tolerated_sbt(
        api, admission.stay_id, plan["id"], vent_hours_since_last=vent_hours_since_last
    )


def vent_dependent_plan(
    api: ApiClient,
    admission: Admission,
    seed_vent_hours: Optional[float] = None,
    vent_hours_since_last: float = 0,
) -> Json:
    """A plan closed `VENT_DEPENDENT` after the three trials that close requires.

    The seed is the plan's opening `vent_hours_total`, and the trials add
    `vent_hours_since_last` each, so a caller can land the cumulative total on an exact
    figure either side of the 96-hour variant boundary.
    """
    plan = open_weaning_plan(api, admission.stay_id, vent_hours_total=seed_vent_hours)
    for _ in range(3):
        failed_sbt(api, plan["id"], vent_hours_since_last=vent_hours_since_last)
    return close_plan(
        api, plan["id"], "VENT_DEPENDENT", admission.world.physician_headers
    )


# ── Interruptions and recombination ──────────────────
def interrupt(
    api: ApiClient,
    stay_id: str,
    destination: str = "HOME",
    left_at: Optional[str] = None,
    headers: Optional[Json] = None,
) -> Json:
    """Open an interruption window on an admitted stay."""
    response = api.interrupt_stay(
        stay_id,
        factories.interrupt_payload(destination=destination, left_at=left_at),
        headers=headers or NURSE_HEADERS,
    )
    return get_success_data(response, expected_status=201)


def return_from_interruption(
    api: ApiClient, interruption_id: str, headers: Optional[Json] = None
) -> Json:
    """Record the patient's return at the current logical instant."""
    response = api.return_interruption(interruption_id, headers=headers or NURSE_HEADERS)
    return get_success_data(response, expected_status=200)


def interrupt_and_return(
    api: ApiClient,
    stay_id: str,
    left_at: str,
    returned_at: str,
    destination: str = "HOME",
) -> Json:
    """One complete interruption: leave at one instant, return at a later one.

    The return is stamped from the logical clock, so the clock is advanced to
    `returned_at` before the return is recorded.
    """
    event = interrupt(api, stay_id, destination=destination, left_at=left_at)
    advance_clock(api, returned_at)
    return return_from_interruption(api, event["id"])


def recombine(
    api: ApiClient,
    readmission_stay_id: str,
    parent_stay_id: str,
    headers: Optional[Json] = None,
) -> Json:
    """Fold a readmission back into an earlier discharged stay of the same patient."""
    response = api.recombine_stay(
        readmission_stay_id,
        factories.recombine_payload(parent_stay_id),
        headers=headers or OFFICER_HEADERS,
    )
    return get_success_data(response, expected_status=200)


# ── Discharge and the four-level cascade ─────────────
def discharge(
    api: ApiClient,
    stay_id: str,
    discharge_disposition: str = DischargeDisposition.HOME,
    estimated_cost_cents: int = 1000000,
    headers: Optional[Json] = None,
) -> Json:
    """Discharge an admitted stay, which also runs the four-level cascade."""
    response = api.discharge_stay(
        stay_id,
        factories.discharge_payload(
            discharge_disposition=discharge_disposition,
            estimated_cost_cents=estimated_cost_cents,
        ),
        headers=headers or NURSE_HEADERS,
    )
    return get_success_data(response, expected_status=200)


def collect_cascade(api: ApiClient, admission: Admission) -> Admission:
    """Re-read the determination, review and queries a discharge cascade produced."""
    admission.stay = read_stay(api, admission.stay_id)
    admission.determination = live_determination(api, admission.stay_id)
    admission.review = sole_review(api, admission.stay_id)
    admission.queries = queries_of(api, stay_id=admission.stay_id)
    return admission


def discharged_stay(
    api: ApiClient,
    world: Optional[World] = None,
    admission: Optional[Admission] = None,
    discharge_disposition: str = DischargeDisposition.HOME,
    estimated_cost_cents: int = 1000000,
    file_notes: bool = True,
    **admission_kwargs: Any
) -> Admission:
    """An admitted stay carried through discharge, with the cascade's output collected.

    `file_notes` files one note in each mandatory discipline before the discharge, so the
    denial-risk score carries no missing-discipline points; a test probing those points
    passes `file_notes=False`.
    """
    admission = (
        admission if admission is not None else admitted_stay(api, world, **admission_kwargs)
    )
    if file_notes:
        file_required_notes(api, admission.stay_id)
    admission.stay = discharge(
        api,
        admission.stay_id,
        discharge_disposition=discharge_disposition,
        estimated_cost_cents=estimated_cost_cents,
    )
    return collect_cascade(api, admission)


# ── Pricing, review resolution and finalization ──────
def reprice(
    api: ApiClient,
    stay_id: str,
    expected_stay_version: int,
    recalculation_reason: str = "Coding review re-priced the stay.",
    override_drg_rate_id: Optional[str] = None,
    headers: Optional[Json] = None,
) -> Json:
    """Re-price a discharged stay, superseding any draft determination on it."""
    response = api.reprice_stay(
        stay_id,
        factories.reprice_payload(
            expected_stay_version,
            recalculation_reason=recalculation_reason,
            override_drg_rate_id=override_drg_rate_id,
        ),
        headers=headers or ANALYST_HEADERS,
    )
    return get_success_data(response, expected_status=201)


def issue_query(
    api: ApiClient,
    review_id: str,
    query_type: str = "IDT_PARTICIPATION",
    prompt_text: str = "Document the interdisciplinary participation for this stay.",
    headers: Optional[Json] = None,
) -> Json:
    response = api.issue_query(
        review_id,
        factories.issue_query_payload(query_type=query_type, prompt_text=prompt_text),
        headers=headers or NURSE_HEADERS,
    )
    return get_success_data(response, expected_status=201)


def answer_query(
    api: ApiClient,
    query_id: str,
    physician_headers: Json,
    response_text: str = "Participation of all four disciplines is documented in the chart.",
) -> Json:
    """Answer an issued query as the physician of record."""
    response = api.answer_query(
        query_id,
        factories.answer_query_payload(response_text=response_text),
        headers=physician_headers,
    )
    return get_success_data(response, expected_status=200)


def close_query(api: ApiClient, query_id: str, headers: Optional[Json] = None) -> Json:
    """Close an answered query; the closing nurse must differ from the issuing one."""
    response = api.close_query(query_id, headers=headers or NURSE_2_HEADERS)
    return get_success_data(response, expected_status=200)


def rescore(api: ApiClient, review_id: str, headers: Optional[Json] = None) -> Json:
    response = api.rescore_review(review_id, headers=headers or OFFICER_HEADERS)
    return get_success_data(response, expected_status=200)


def resolve_review(
    api: ApiClient,
    review_id: str,
    outcome: str = ReviewOutcome.CLEARED,
    resolution_note: str = "Documentation reviewed and accepted.",
    headers: Optional[Json] = None,
) -> Json:
    """Clear or escalate a review, which is what unblocks finalization."""
    response = api.resolve_review(
        review_id,
        factories.resolve_review_payload(outcome=outcome, resolution_note=resolution_note),
        headers=headers or OFFICER_HEADERS,
    )
    return get_success_data(response, expected_status=200)


def finalize(api: ApiClient, determination_id: str, headers: Optional[Json] = None) -> Json:
    """Accept a draft determination; the caller must differ from whoever priced it."""
    response = api.finalize_determination(
        determination_id, headers=headers or ANALYST_HEADERS
    )
    return get_success_data(response, expected_status=200)


def void(
    api: ApiClient,
    determination_id: str,
    void_reason: str = "AUDIT_CORRECTION",
    headers: Optional[Json] = None,
) -> Json:
    """Reverse a draft or final determination."""
    response = api.void_determination(
        determination_id, factories.void_payload(void_reason), headers=headers or ANALYST_HEADERS
    )
    return get_success_data(response, expected_status=200)


def clear_review_for_finalize(api: ApiClient, admission: Admission) -> Json:
    """Resolve the stay's review so its determination may be finalized.

    A `CLEARED` resolution is only legal from `OPEN` with a band below `HIGH`, so a review
    the cascade escalated into `QUERIES_ISSUED` is resolved as `ESCALATED` instead —
    either outcome unblocks finalization.
    """
    review = sole_review(api, admission.stay_id)
    outcome = (
        ReviewOutcome.CLEARED
        if review["status"] == "OPEN" and review["risk_band"] != "HIGH"
        else ReviewOutcome.ESCALATED
    )
    resolved = resolve_review(api, review["id"], outcome=outcome)
    admission.review = resolved
    return resolved


def finalized_stay(
    api: ApiClient,
    world: Optional[World] = None,
    admission: Optional[Admission] = None,
    estimated_cost_cents: int = 1000000,
    finalize_headers: Optional[Json] = None,
    **discharge_kwargs: Any
) -> Admission:
    """A stay discharged, its review resolved and its determination in `FINAL`.

    The cascade prices the stay with `priced_by_user_id` `SYSTEM`, so any analyst may
    finalize it without tripping the segregation-of-duties rule.
    """
    admission = (
        admission
        if admission is not None
        else discharged_stay(
            api, world, estimated_cost_cents=estimated_cost_cents, **discharge_kwargs
        )
    )
    clear_review_for_finalize(api, admission)
    admission.determination = finalize(
        api, sole_determination(api, admission.stay_id)["id"], headers=finalize_headers
    )
    admission.stay = read_stay(api, admission.stay_id)
    return admission
