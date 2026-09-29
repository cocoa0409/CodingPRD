"""Declared transitions, initial states, terminal lockdown and cascades.

Each test drives one machine across one declared edge — or attempts an edge the
specification does not declare — and reads back the side effects the transition
owns.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CYCLE_INVALID_STATE,
    ERR_ENGAGEMENT_INVALID_STATE,
    ERR_NO_VALIDATED_INPUT,
)
from test_helpers.constants import (
    CTRL_FILING_CONFIRMATION,
    CYCLE_CANCELLED,
    CYCLE_DRAFT,
    CYCLE_INPUTS_LOCKED,
    CYCLE_ON_HOLD,
    DECISION_UPHOLD,
    ENGAGEMENT_ACTIVE,
    ENGAGEMENT_DRAFT,
    ENGAGEMENT_REMEDIATION_REQUIRED,
    FILING_CONFIRMED,
    FILING_FILED,
    FILING_LATE,
    FILING_PENDING,
    FILING_RESPONSIBILITY_PROVIDER,
    FILING_TYPE_INCOME_TAX_WITHHOLDING,
    FILING_TYPE_SOCIAL_INSURANCE,
    HOLD_REASON_PROVIDER_PROBATION,
    INCIDENT_REMEDIATED,
    INPUT_FILE_RECEIVED,
    INPUT_FILE_SUPERSEDED,
    INPUT_FILE_VALIDATED,
    PENALTY_NONE,
    PENALTY_OWNER_CLIENT,
    PENALTY_OWNER_PROVIDER,
    PENALTY_WAIVED,
    PROVIDER_ACTIVE,
    PROVIDER_PROBATION,
    SCORE_VARIANT_ENGAGEMENT_TO_DATE,
    SEV1,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    CONTROLLER_HEADERS,
    OPS_HEADERS,
)

_FIRST_DECISION_CLOCK = "2026-08-02T08:00:00Z"
_FIRST_DECISION_INSTANT = "2026-08-02T08:00:00.000Z"
_REPLAY_CLOCK = "2026-08-03T08:00:00Z"
_FIRST_TERMS_REF = "DPA-DE-2026-01"
_SECOND_TERMS_REF = "DPA-DE-2026-02"
_SHARED_DUE_AT = "2026-09-10T23:59:59.999Z"


def _filings_page(api, cycle_id):
    return validate_paginated(api.list_filings(OPS_HEADERS, {"cycle_id": cycle_id}))


def test_residency_approval_moves_the_engagement_out_of_draft(api):
    """The auditor's APPROVE decision activates the engagement, persists the agreement
    reference and stamps the activation instant from the logical clock.

    PRD 3.2: "On `APPROVE`, the auditor must supply `residency_terms_ref`, a
    data-processing-agreement reference of 1 to 60 characters, which is persisted on the
    engagement; the engagement moves `DRAFT → ACTIVE`, `activated_at` is stamped with
    the current logical-clock instant, and the engaged provider's `service_score` is
    recomputed — under the `ENGAGEMENT_TO_DATE` variant, because a brand-new engagement
    has `closed_cycle_count` at 0."

    Design: Corner/state_machines/residency_approval_moves_engagement_draft_to_active
    """
    country = fx.create_country(
        api, required_filing_types=[FILING_TYPE_INCOME_TAX_WITHHOLDING]
    )
    provider = fx.create_provider(api)
    engagement = fx.create_engagement(api, country["id"], provider["id"])
    fx.set_clock(api, _FIRST_DECISION_CLOCK)

    response = api.residency_decision(
        engagement["id"], f.residency_approve_payload(_FIRST_TERMS_REF), AUDITOR_HEADERS
    )

    activated = validate_success(response)
    assert activated["status"] == ENGAGEMENT_ACTIVE, (
        f"the engagement is activated, got {activated['status']}"
    )
    assert activated["residency_terms_ref"] == _FIRST_TERMS_REF, (
        f"the agreement reference is persisted, got {activated['residency_terms_ref']!r}"
    )
    a.assert_instant_equals(
        activated["activated_at"], _FIRST_DECISION_INSTANT, "activated_at"
    )
    assert activated["transition_required"] is False, (
        f"a freshly activated engagement needs no transition, got {activated}"
    )

    scored = fx.read_provider(api, provider["id"])
    a.assert_provider_standing(
        scored,
        status=PROVIDER_ACTIVE,
        service_score=100.00,
        score_variant_applied=SCORE_VARIANT_ENGAGEMENT_TO_DATE,
    )


def test_lock_inputs_without_a_validated_extract_is_refused(api):
    """A cycle carrying only a received extract cannot end its input phase, and the
    refused lock mints no obligation at all.

    PRD 3.4: "Exactly one extract of the cycle must be in `VALIDATED`; if the cycle has
    no validated extract at all, the lock is rejected with `ERR_NO_VALIDATED_INPUT`
    (HTTP 409)."

    Design: Corner/state_machines/lock_inputs_missing_required_validated_extract_is_rejected
    """
    ctx = fx.setup_draft_cycle(api)
    extract = fx.submit_extract(api, ctx["cycle_id"])

    response = api.lock_inputs(ctx["cycle_id"], OPS_HEADERS)
    validate_error(response, ERR_NO_VALIDATED_INPUT, 409)

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_DRAFT)

    _, meta = _filings_page(api, ctx["cycle_id"])
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)

    country = fx.read_country(api, ctx["country_id"])
    assert country["open_filing_obligation_count"] == 0, (
        "nothing was minted, got "
        f"{country['open_filing_obligation_count']}"
    )

    extracts, _ = validate_paginated(
        api.list_cycle_input_files(ctx["cycle_id"], OPS_HEADERS)
    )
    unchanged = a.find_by(extracts, "id", extract["id"])
    assert unchanged["status"] == INPUT_FILE_RECEIVED, (
        f"the extract is still merely received, got {unchanged['status']}"
    )


def test_lock_inputs_mints_one_obligation_per_required_filing_type(api):
    """One lock request mints both of the country's obligations on a shared deadline,
    raises the country's live count by two and supersedes the extract left unvalidated.

    PRD 3.4: "It mints one statutory filing for every member of the country's
    `required_filing_types`, each opening in status `PENDING` with `responsibility`
    copied from the engagement's `filing_responsibility` and with a `due_at` resolved as
    described below. It increases the country profile's `open_filing_obligation_count`
    by the number of filings minted. It moves every extract of the cycle still sitting
    in `RECEIVED` to `SUPERSEDED`, since those extracts can now neither be validated nor
    resubmitted."

    PRD 3.4: "Each minted filing's `due_at` is resolved from calendar days, not working
    days: take the cycle's `pay_date`, add the country profile's
    `statutory_filing_deadline_days` as whole calendar days, and set the time of day to
    23:59:59.999Z."

    Design: Corner/state_machines/lock_inputs_mints_one_pending_filing_per_required_type
    """
    ctx = fx.setup_validated_extract(api)
    later = fx.submit_extract(
        api, ctx["cycle_id"], record_count=205, gross_declared_minor=10100000
    )

    cycle = fx.lock_inputs(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_INPUTS_LOCKED)

    filings, meta = _filings_page(api, ctx["cycle_id"])
    a.assert_pagination_meta(meta, expected_total=2, expected_has_more=False)
    income_tax = a.find_by(filings, "filing_type", FILING_TYPE_INCOME_TAX_WITHHOLDING)
    social = a.find_by(filings, "filing_type", FILING_TYPE_SOCIAL_INSURANCE)
    for filing in (income_tax, social):
        a.assert_field_values(
            filing,
            {
                "status": FILING_PENDING,
                "penalty_status": PENALTY_NONE,
                "responsibility": FILING_RESPONSIBILITY_PROVIDER,
            },
        )
        a.assert_instant_equals(filing["due_at"], _SHARED_DUE_AT, "due_at")

    country = fx.read_country(api, ctx["country_id"])
    assert country["open_filing_obligation_count"] == 2, (
        "both obligations are live, got "
        f"{country['open_filing_obligation_count']}"
    )

    extracts, _ = validate_paginated(
        api.list_cycle_input_files(ctx["cycle_id"], OPS_HEADERS)
    )
    assert a.find_by(extracts, "id", later["id"])["status"] == INPUT_FILE_SUPERSEDED, (
        "the extract left in RECEIVED is superseded by the lock"
    )
    assert (
        a.find_by(extracts, "id", ctx["input_file_id"])["status"] == INPUT_FILE_VALIDATED
    ), "the validated extract keeps backing the period"


def test_close_is_not_a_declared_transition_out_of_draft(api):
    """Closing is reachable only from a funded period, so a draft cycle refuses it and
    the engagement's delivery history is untouched.

    PRD 3.9: "The cycle must be in `FUNDED`; closing from any other status, including a
    cycle already `CLOSED`, is rejected with `ERR_CYCLE_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/draft_cycle_cannot_be_closed_before_it_is_funded
    """
    ctx = fx.setup_draft_cycle(api)

    response = api.close_cycle(ctx["cycle_id"], CONTROLLER_HEADERS)
    validate_error(response, ERR_CYCLE_INVALID_STATE, 409)

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_DRAFT)

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["closed_cycle_count"] == 0, (
        f"no period has closed, got {engagement['closed_cycle_count']}"
    )

    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        provider,
        status=PROVIDER_ACTIVE,
        score_variant_applied=SCORE_VARIANT_ENGAGEMENT_TO_DATE,
    )


def test_creation_leaves_every_machine_in_its_declared_initial_state(api):
    """Provider, engagement, cycle and extract each open in the state their machine
    declares, with no transition applied at creation.

    PRD 3.2: "A new engagement opens in `status` `DRAFT` with
    `treasury_committed_minor` at 0, `closed_cycle_count` at 0, `transition_required`
    false, and `activated_at`, `residency_terms_ref`, `transition_incoming_provider_id`,
    `transition_cutover_start_date`, `transition_cutover_end_date` and
    `transition_parallel_run_cycles` all null."

    PRD 3.4: "A submitted extract opens in `status` `RECEIVED` with `submitted_at`
    stamped from the logical clock, `rejection_code` null and `validated_record_count`
    at 0."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    country = fx.create_country(api)
    provider = fx.create_provider(api)
    a.assert_provider_standing(
        provider, status=PROVIDER_ACTIVE, service_score=100.00, open_penalty_minor=0
    )

    engagement = fx.create_engagement(api, country["id"], provider["id"])
    assert engagement["status"] == ENGAGEMENT_DRAFT, (
        f"a new engagement is inert, got {engagement['status']}"
    )
    a.assert_null_fields(engagement, ["activated_at", "residency_terms_ref"])
    assert engagement["transition_required"] is False, (
        f"transition_required opens false, got {engagement['transition_required']}"
    )

    fx.approve_residency(api, engagement["id"])
    cycle = fx.create_cycle(api, engagement["id"])
    a.assert_cycle_state(cycle, CYCLE_DRAFT)

    extract = fx.submit_extract(api, cycle["id"])
    assert extract["status"] == INPUT_FILE_RECEIVED, (
        f"a new extract is merely received, got {extract['status']}"
    )
    a.assert_null_fields(extract, ["rejection_code"])


def test_a_cancelled_cycle_accepts_no_further_transition(api):
    """Cancellation is terminal: neither a lock nor a second cancellation is available
    afterwards, and the period keeps its cancelled status.

    PRD 3.4: "The cycle must be in `DRAFT` — a cycle that is `ON_HOLD` or already past
    `DRAFT` is rejected with `ERR_CYCLE_INVALID_STATE` (HTTP 409)"

    PRD 3.9: "Cancellation is only available before the period has produced anything
    irreversible: the cycle's status must be `DRAFT`, `ON_HOLD` or `INPUTS_LOCKED`, no
    funding instruction of the cycle may be in `RELEASED`, and no filing of the cycle may
    be in `FILED`, `FILED_LATE` or `CONFIRMED`."

    Design: Corner/state_machines/cancelled_cycle_rejects_every_further_transition
    """
    ctx = fx.setup_validated_extract(api)
    cancelled = fx.cancel_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cancelled, CYCLE_CANCELLED)

    validate_error(
        api.lock_inputs(ctx["cycle_id"], OPS_HEADERS), ERR_CYCLE_INVALID_STATE, 409
    )
    validate_error(
        api.cancel_cycle(ctx["cycle_id"], f.cancel_payload(), OPS_HEADERS),
        ERR_CYCLE_INVALID_STATE,
        409,
    )

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_CANCELLED)

    _, meta = _filings_page(api, ctx["cycle_id"])
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)


def test_replaying_the_residency_decision_is_refused(api):
    """The decision is not idempotent: a second APPROVE on an active engagement is
    refused and neither the agreement reference nor the activation instant is rewritten.

    PRD 3.2: "A residency decision attempted on an engagement whose `status` is anything
    other than `DRAFT` is rejected with `ERR_ENGAGEMENT_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/second_residency_decision_on_the_same_engagement_is_rejected
    """
    country = fx.create_country(api)
    provider = fx.create_provider(api)
    engagement = fx.create_engagement(api, country["id"], provider["id"])
    fx.set_clock(api, _FIRST_DECISION_CLOCK)
    fx.approve_residency(api, engagement["id"], _FIRST_TERMS_REF)
    fx.set_clock(api, _REPLAY_CLOCK)

    response = api.residency_decision(
        engagement["id"],
        f.residency_approve_payload(_SECOND_TERMS_REF),
        AUDITOR_HEADERS,
    )
    validate_error(response, ERR_ENGAGEMENT_INVALID_STATE, 409)

    unchanged = fx.read_engagement(api, engagement["id"])
    assert unchanged["status"] == ENGAGEMENT_ACTIVE, (
        f"the engagement stays active, got {unchanged['status']}"
    )
    assert unchanged["residency_terms_ref"] == _FIRST_TERMS_REF, (
        "the first agreement reference survives, got "
        f"{unchanged['residency_terms_ref']!r}"
    )
    a.assert_instant_equals(
        unchanged["activated_at"], _FIRST_DECISION_INSTANT, "activated_at"
    )


def test_remediating_the_last_finding_bubbles_the_provider_back_to_active(api):
    """With every finding remediated the deduction disappears, so the provider and its
    engagement recover — but the held period is not released with them.

    PRD 3.8: "**Remediating** an incident is available from either `CONFIRMED` or
    `ESCALATED`, requires a `remediation_ref` of 1 to 60 characters which is persisted,
    and moves the incident to the terminal `REMEDIATED` with `weight_points` reset to
    0.00; `escalation_level` is retained for audit rather than reset."

    PRD 3.8: "When a provider returns to `ACTIVE` — because its recomputed score reached
    at least 55.00, or because a waived penalty brought `open_penalty_minor` back to
    100000 or less, with both conditions satisfied — every engagement of that provider
    sitting in `REMEDIATION_REQUIRED` that has no remaining incident in `CONFIRMED` or
    `ESCALATED` moves `REMEDIATION_REQUIRED → ACTIVE` with `transition_required` cleared
    to false. An engagement that still carries an unremediated finding stays in
    remediation even though its provider is healthy. And cycles already `ON_HOLD` are
    **not** released automatically by any of this; they wait for an explicit hold
    release."

    Design: Corner/state_machines/incident_remediation_bubbles_provider_and_engagement_back_to_active
    """
    ctx = fx.setup_draft_cycle(api)
    first = fx.confirmed_incident(api, ctx["engagement_id"], SEV1)
    second = fx.confirmed_incident(api, ctx["engagement_id"], SEV1)
    degraded = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        degraded, status=PROVIDER_PROBATION, service_score=50.00
    )

    fx.remediate_incident(api, first["id"], remediation_ref="RCA-2026-08-001")
    interim = fx.read_provider(api, ctx["provider_id"])
    a.assert_pct(interim["service_score"], 75.00, "service_score")

    response = api.remediate_incident(
        second["id"], f.remediate_payload("RCA-2026-08-002"), CONTROLLER_HEADERS
    )
    remediated = validate_success(response)
    assert remediated["status"] == INCIDENT_REMEDIATED, (
        f"the incident is remediated, got {remediated['status']}"
    )
    a.assert_pct(remediated["weight_points"], 0.00, "weight_points")

    recovered = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        recovered, status=PROVIDER_ACTIVE, service_score=100.00
    )

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["status"] == ENGAGEMENT_ACTIVE, (
        f"the engagement recovers with its provider, got {engagement['status']}"
    )
    assert engagement["transition_required"] is False, (
        f"transition_required is cleared, got {engagement['transition_required']}"
    )

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_ON_HOLD, HOLD_REASON_PROVIDER_PROBATION)


def test_probation_holds_only_the_draft_cycle_of_the_engagement(api):
    """The hold cascade is conditional on each period's own state: the draft period is
    held while the locked one carries on untouched.

    PRD 3.8: "When a provider becomes `PROBATION` or `SUSPENDED`, every engagement of
    that provider whose `status` is `ACTIVE` moves `ACTIVE → REMEDIATION_REQUIRED` and
    has its `transition_required` set to true, and every cycle of those engagements
    sitting in `DRAFT` moves `DRAFT → ON_HOLD` with `hold_reason` set to
    `PROVIDER_PROBATION` when the provider is on probation or `PROVIDER_SUSPENSION` when
    the provider is suspended."

    Design: Corner/state_machines/provider_probation_holds_only_the_draft_cycles_of_the_engagement
    """
    ctx = fx.setup_locked_cycle(api)
    september = validate_success(
        api.create_cycle(
            f.september_cycle_payload(
                ctx["engagement_id"], prior_cycle_id=ctx["cycle_id"]
            ),
            OPS_HEADERS,
        ),
        201,
    )
    fx.confirmed_incident(api, ctx["engagement_id"], SEV1)
    pending = fx.raise_incident(api, ctx["engagement_id"], SEV1)

    confirmed = validate_success(api.confirm_incident(pending["id"], CONTROLLER_HEADERS))
    a.assert_pct(confirmed["weight_points"], 25.00, "weight_points")

    provider = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        provider, status=PROVIDER_PROBATION, service_score=50.00
    )

    held = fx.read_cycle(api, september["id"])
    a.assert_cycle_state(held, CYCLE_ON_HOLD, HOLD_REASON_PROVIDER_PROBATION)

    running = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(running, CYCLE_INPUTS_LOCKED)

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["status"] == ENGAGEMENT_REMEDIATION_REQUIRED, (
        f"the engagement is in remediation, got {engagement['status']}"
    )
    assert engagement["transition_required"] is True, (
        f"transition_required is set, got {engagement['transition_required']}"
    )


def test_upholding_a_dispute_moves_the_whole_share_to_the_client(api):
    """The waiver preserves the total but hands it entirely to the client, and the
    provider's cleared exposure recovers a standing that penalty alone had degraded.

    PRD 3.7: "An `UPHOLD` decision moves `penalty_status` `DISPUTED → WAIVED`, which is
    terminal: the whole `provider_share_minor` is shifted into `client_share_minor` so
    that `total_penalty_minor` is preserved unchanged, `penalty_owner` becomes `CLIENT`,
    and the provider's `open_penalty_minor` decreases by the waived share — which, if the
    exposure falls back to 100000 or less, can recover the provider from `PROBATION` to
    `ACTIVE` and bubble that recovery back through its engagements."

    PRD 3.7: "The two evolve separately, and an action on one does not disturb the other
    unless this section says it does."

    Design: Corner/state_machines/penalty_waiver_moves_the_share_to_the_client_and_recovers_the_provider
    """
    ctx = fx.setup_results_approved_cycle(
        api,
        country_overrides={
            "required_filing_types": [FILING_TYPE_INCOME_TAX_WITHHOLDING]
        },
    )
    fx.set_clock(api, "2026-09-16T12:00:00Z")
    swept = fx.sweep_filings(api, ctx["cycle_id"])
    filing = a.find_by(swept, "filing_type", FILING_TYPE_INCOME_TAX_WITHHOLDING)
    a.assert_penalty_assessment(
        filing,
        late_days=6,
        base_penalty_minor=115000,
        surcharge_minor=23000,
        total_penalty_minor=138000,
        provider_share_minor=138000,
        client_share_minor=0,
        penalty_owner=PENALTY_OWNER_PROVIDER,
    )
    exposed = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        exposed,
        status=PROVIDER_PROBATION,
        service_score=100.00,
        open_penalty_minor=138000,
    )
    fx.open_penalty_dispute(api, filing["id"], ctx["provider_id"])

    response = api.penalty_dispute_decision(
        filing["id"], f.penalty_decision_payload(DECISION_UPHOLD), CONTROLLER_HEADERS
    )

    waived = validate_success(response)
    assert waived["penalty_status"] == PENALTY_WAIVED, (
        f"the penalty is waived, got {waived['penalty_status']}"
    )
    a.assert_penalty_assessment(
        waived,
        late_days=6,
        base_penalty_minor=115000,
        surcharge_minor=23000,
        total_penalty_minor=138000,
        provider_share_minor=0,
        client_share_minor=138000,
        penalty_owner=PENALTY_OWNER_CLIENT,
    )
    assert waived["status"] == FILING_LATE, (
        f"the lodgement dimension is untouched, got {waived['status']}"
    )

    recovered = fx.read_provider(api, ctx["provider_id"])
    a.assert_provider_standing(
        recovered,
        status=PROVIDER_ACTIVE,
        service_score=100.00,
        open_penalty_minor=0,
    )

    engagement = fx.read_engagement(api, ctx["engagement_id"])
    assert engagement["status"] == ENGAGEMENT_ACTIVE, (
        f"the recovery bubbles through the engagement, got {engagement['status']}"
    )
    assert engagement["transition_required"] is False, (
        f"transition_required is cleared, got {engagement['transition_required']}"
    )


def test_lodging_one_obligation_decrements_the_country_ledger_by_one(api):
    """Lodging one of two obligations takes the country's live count down by exactly
    one, and the later confirmation moves the cycle's counter without touching the ledger
    again.

    PRD 3.7: "A `PENDING` filing may only be lodged while the current logical clock is at
    or before its `due_at`, in which case it moves `PENDING → FILED`; once the clock has
    passed `due_at` the obligation must first be swept to `LATE`, and lodging a
    still-`PENDING` filing after its deadline is rejected with
    `ERR_FILING_INVALID_STATE` (HTTP 409)."

    PRD 3.7: "Confirmation increases the cycle's `filings_confirmed_count` by 1 and, at
    the moment every non-`VOIDED` filing of the cycle has reached `CONFIRMED`, mints the
    cycle's filing-confirmation control evidence as an audit evidence item with
    `control_ref` `CTRL_FILING_CONFIRMATION`; earlier confirmations mint nothing."

    Design: Corner/state_machines/filing_lodgement_syncs_the_country_open_obligation_ledger
    """
    ctx = fx.setup_results_approved_cycle(api)
    fx.set_clock(api, "2026-09-05T10:00:00Z")
    pending = fx.filings_of_cycle(api, ctx["cycle_id"], status=FILING_PENDING)
    assert len(pending) == 2, f"both obligations are still live, got {len(pending)}"
    target = pending[0]

    response = api.file_filing(
        target["id"], f.file_filing_payload("DE-SUB-0001"), ctx["provider_headers"]
    )

    filed = validate_success(response)
    a.assert_field_values(
        filed,
        {
            "status": FILING_FILED,
            "submission_ref": "DE-SUB-0001",
            "penalty_status": PENALTY_NONE,
        },
    )
    a.assert_instant_equals(filed["filed_at"], "2026-09-05T10:00:00.000Z", "filed_at")

    after_lodgement = fx.read_country(api, ctx["country_id"])
    assert after_lodgement["open_filing_obligation_count"] == 1, (
        "exactly one obligation is left live, got "
        f"{after_lodgement['open_filing_obligation_count']}"
    )

    confirmed = fx.confirm_filing(
        api, target["id"], confirmation_ref="DE-CONF-0001"
    )
    assert confirmed["status"] == FILING_CONFIRMED, (
        f"the filing is confirmed, got {confirmed['status']}"
    )

    after_confirmation = fx.read_country(api, ctx["country_id"])
    assert after_confirmation["open_filing_obligation_count"] == 1, (
        "confirmation does not touch the ledger again, got "
        f"{after_confirmation['open_filing_obligation_count']}"
    )

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    assert cycle["filings_confirmed_count"] == 1, (
        f"one filing is confirmed, got {cycle['filings_confirmed_count']}"
    )

    evidence = fx.evidence_of_cycle(
        api, ctx["cycle_id"], control_ref=CTRL_FILING_CONFIRMATION
    )
    assert evidence == [], (
        f"the confirmation control is not exercised yet, got {evidence}"
    )
