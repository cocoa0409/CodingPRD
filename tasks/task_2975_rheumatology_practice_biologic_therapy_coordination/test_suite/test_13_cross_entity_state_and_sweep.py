"""Corner-case suite — sections `state_machines` and
`cross_cutting_complexity_layers`.

The cross-entity half of the state machines: the deferred reauthorization
calendar driving `funding_state` independently of `therapy_state`, the
conditional hold cascade that spares an administered dose, the authorization
intake that expires a sibling draft, the episode-revision optimistic
concurrency token, and the sweep's asymmetric deadline comparisons.

Every test in this module translates exactly one instance of those two
sections of SCAFFOLD_CORNER_DESIGN.yaml.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_client, assertions, constants, factories, fixtures
from test_helpers.api_errors import ApiErrorId


# --------------------------------------------------------------------------
# Shared preamble builders. Each one is a plain helper, not a fixture, so the
# clock parking and the ordering stay visible inside every test.
# --------------------------------------------------------------------------
PINNED_COVERAGE_WINDOW = {
    "approved_units": 6,
    "valid_from": constants.instant(2026, 8, 1),
    "valid_through": constants.instant(2027, 1, 28),
}


def _funded_active_episode():
    """An ACTIVE, AUTHORIZED IV episode whose approved authorization covers
    2026-08-01 through 2027-01-28 inclusive."""
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    return fixtures.active_episode(
        requested_units=6, determination_overrides=dict(PINNED_COVERAGE_WINDOW)
    )


# ==========================================================================
# authorization_expiry_lapses_funding_while_therapy_state_stays_active
# ==========================================================================
def test_sweep_lapses_funding_while_the_therapy_axis_stays_active():
    """One day past `valid_through` the sweep expires the authorization and
    lapses the episode's funding, yet the clinical axis and the patient's
    active-episode count do not move — `ACTIVE` x `LAPSED` is a legal state.

    PRD: "When the reauthorization sweep of §2.11 observes that the logical clock has passed an approved authorization's `valid_through`, that authorization moves `APPROVED → EXPIRED`, the episode's `funding_state` moves `AUTHORIZED → LAPSED`, and both revision counters increment by one; the sweep counts that pair in `authorizations_expired` and `episodes_lapsed`."
    PRD: "Neither axis constrains the other's representation: an episode may legitimately be `ACTIVE` while its funding is `LAPSED`, and it may be `HELD` while its funding is `AUTHORIZED`."
    Design: Corner/state_machines/authorization_expiry_lapses_funding_while_therapy_state_stays_active
    """
    scenario = _funded_active_episode()
    assert scenario.refresh_episode()["funding_state"] == "AUTHORIZED"

    fixtures.set_clock(constants.instant(2027, 1, 29))
    counters = fixtures.run_sweep()

    assert counters["authorizations_expired"] == 1, (
        f"expected authorizations_expired 1, got {counters['authorizations_expired']}"
    )
    assert counters["episodes_lapsed"] == 1, (
        f"expected episodes_lapsed 1, got {counters['episodes_lapsed']}"
    )
    assert counters["enrollments_reauth_pending"] == 0, (
        f"expected enrollments_reauth_pending 0, got {counters['enrollments_reauth_pending']}"
    )

    authorization = scenario.refresh_authorization()
    assert authorization["status"] == "EXPIRED", (
        f"expected the authorization EXPIRED, got {authorization['status']!r}"
    )
    episode = scenario.refresh_episode()
    assert episode["funding_state"] == "LAPSED", (
        f"expected funding_state LAPSED, got {episode['funding_state']!r}"
    )
    assert episode["therapy_state"] == "ACTIVE", (
        f"the therapy dimension did not move, got {episode['therapy_state']!r}"
    )
    assert scenario.refresh_patient()["active_episode_count"] == 1, (
        "a lapsed funding window does not remove the episode from the active count"
    )


def test_a_second_sweep_at_the_same_clock_reports_zeroes_and_moves_no_revision():
    """The sweep is idempotent: the repeat run against the same clock reports
    zeroes on all three counters and advances no revision counter anywhere.

    PRD: "The sweep is idempotent — running it twice against the same clock reports zeroes on the second run — and it is the only mechanism by which an authorization expires or an enrollment becomes due for renewal."
    Design: Corner/state_machines/authorization_expiry_lapses_funding_while_therapy_state_stays_active
    """
    scenario = _funded_active_episode()

    fixtures.set_clock(constants.instant(2027, 1, 29))
    fixtures.run_sweep()

    authorization_version = scenario.refresh_authorization()["version"]
    episode_version = scenario.refresh_episode()["version"]
    patient_version = scenario.refresh_patient()["version"]

    second = fixtures.run_sweep()

    assert second["authorizations_expired"] == 0, (
        f"expected authorizations_expired 0 on the second run, got {second['authorizations_expired']}"
    )
    assert second["episodes_lapsed"] == 0, (
        f"expected episodes_lapsed 0 on the second run, got {second['episodes_lapsed']}"
    )
    assert second["enrollments_reauth_pending"] == 0, (
        f"expected enrollments_reauth_pending 0 on the second run, "
        f"got {second['enrollments_reauth_pending']}"
    )
    assert scenario.refresh_authorization()["version"] == authorization_version
    assert scenario.refresh_episode()["version"] == episode_version
    assert scenario.refresh_patient()["version"] == patient_version


# ==========================================================================
# hold_cascade_conditionally_spares_administered_appointments
# ==========================================================================
def _held_after_one_administered_dose():
    """Two doses booked into the same chair against one ACTIVE enrollment; the
    first is administered at 2026-08-03T09:00Z, then the episode is held for
    SURGERY at 2026-08-05T00:00:00Z."""
    scenario = _funded_active_episode()
    fixtures.active_enrollment(scenario)

    first = fixtures.schedule_appointment(scenario, constants.instant(2026, 8, 3, 9, 0, 0))
    second = fixtures.schedule_appointment(scenario, constants.instant(2026, 8, 10, 9, 0, 0))

    fixtures.set_clock(constants.instant(2026, 8, 3, 9, 0, 0))
    administered = fixtures.administer_appointment(scenario, first["id"])

    fixtures.set_clock(constants.instant(2026, 8, 5))
    held = validate_success(
        api_client.hold_therapy_episode(
            scenario.episode_id, {"hold_reason": "SURGERY"}, scenario.rheum_headers
        )
    )
    return scenario, administered, second, held


def test_hold_cascade_cancels_only_the_still_scheduled_dose():
    """The cascade is conditional on appointment status: the administered dose
    keeps its `administered_at` and its money untouched while the scheduled one
    is cancelled with `THERAPY_HELD`.

    PRD: "Every appointment of the episode still in `SCHEDULED` is cancelled with `cancellation_reason` `THERAPY_HELD`; appointments already `ADMINISTERED` or already `CANCELLED` are untouched."
    PRD: "**Second**, the coverage tier is picked from the **gross** dose cost share: the program covers the whole amount when `dose_cost_share_cents` is strictly below 20,000 cents (two hundred dollars), covers 90 percent of it when the share is at least 20,000 cents but strictly below 100,000 cents (one thousand dollars), and covers 80 percent of it at or above 100,000 cents."
    Design: Corner/state_machines/hold_cascade_conditionally_spares_administered_appointments
    """
    scenario, administered, second, _held = _held_after_one_administered_dose()

    spared = scenario.refresh_appointment(administered["id"])
    assert spared["status"] == "ADMINISTERED", (
        f"the administered dose is untouched by the cascade, got {spared['status']!r}"
    )
    assertions.assert_instant_equals(
        spared["administered_at"], constants.instant(2026, 8, 3, 9, 0, 0), "administered_at"
    )
    assert spared["cancellation_reason"] is None, (
        f"the spared dose carries no cancellation_reason, got {spared['cancellation_reason']!r}"
    )
    assert spared["version"] == administered["version"], (
        f"the spared dose's version must not move: expected {administered['version']}, "
        f"got {spared['version']}"
    )
    assert spared["dose_sequence"] == 1
    assert spared["dose_cost_share_cents"] == 138_759
    assert spared["assistance_applied_cents"] == 111_007
    assert spared["patient_out_of_pocket_cents"] == 27_752

    cancelled = scenario.refresh_appointment(second["id"])
    assert cancelled["status"] == "CANCELLED", (
        f"the still-scheduled dose is cancelled by the cascade, got {cancelled['status']!r}"
    )
    assert cancelled["cancellation_reason"] == "THERAPY_HELD", (
        f"the cascade writes THERAPY_HELD, got {cancelled['cancellation_reason']!r}"
    )
    assert cancelled["dose_sequence"] == 2
    assert cancelled["dose_cost_share_cents"] == 56_259
    assert cancelled["assistance_applied_cents"] == 50_633
    assert cancelled["patient_out_of_pocket_cents"] == 5_626


def test_hold_cascade_releases_only_the_cancelled_dose_reservations():
    """Only the cancelled dose's unit and assistance dollars come back; the
    administered dose's consumed unit and used benefit stay spent.

    PRD: "Each cancellation releases one unit from its reserving authorization's `units_reserved` into that authorization's `units_remaining`, and releases that appointment's `assistance_applied_cents` from its reserving enrollment's `benefit_reserved_cents` into that enrollment's `benefit_remaining_cents`; every cancelled appointment's own `version` increments by one."
    PRD: "A `SURGERY` hold waits two weeks for a `TNFI` product, four weeks for an `IL6` product, one week for a `JAKI` product, six months — 180 days — for a `CD20` product, and four weeks for a `CTLA4` product."
    Design: Corner/state_machines/hold_cascade_conditionally_spares_administered_appointments
    """
    scenario, _administered, _second, held = _held_after_one_administered_dose()

    authorization = scenario.refresh_authorization()
    assertions.assert_unit_ledger(authorization, reserved=0, consumed=1, remaining=5)

    enrollment = scenario.refresh_enrollment()
    assertions.assert_money_ledger(
        enrollment, used=111_007, reserved=0, remaining=388_993
    )
    assert enrollment["status"] == "ACTIVE", (
        f"the refunded enrollment stays ACTIVE, got {enrollment['status']!r}"
    )

    assert held["therapy_state"] == "HELD"
    assert held["hold_reason"] == "SURGERY"
    assertions.assert_instant_equals(
        held["held_at"], constants.instant(2026, 8, 5), "held_at"
    )
    assert held["hold_count"] == 1
    assertions.assert_instant_equals(
        held["resume_not_before"], constants.instant(2026, 8, 19), "resume_not_before"
    )
    assert held["doses_administered"] == 1

    patient = scenario.refresh_patient()
    assert patient["administered_dose_total"] == 1
    assert patient["active_episode_count"] == 0, (
        "holding removes the episode from the patient's active count"
    )


# ==========================================================================
# creating_a_newer_authorization_expires_the_prior_draft_cross_entity
# ==========================================================================
def _two_authorization_intakes():
    """Two authorization intakes against the same `PLANNED` episode, six units
    then four, with no submission in between."""
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.planned_episode()
    first = fixtures.open_authorization(scenario, requested_units=6)
    second = fixtures.open_authorization(scenario, requested_units=4)
    return scenario, first, second


def test_a_second_intake_supersedes_the_prior_draft_across_entities():
    """The write reaches sideways into a sibling authorization: the earlier
    `DRAFT` is expired with a supersede note while the newcomer is born clean
    and the episode's funding stays at `PENDING_AUTH`.

    PRD: "Any earlier authorization of the same episode still sitting in `DRAFT` moves `DRAFT → EXPIRED`, records a supersede note in its `decision_reason`, and has its `version` incremented by one."
    PRD: "A new authorization is born in `status` `DRAFT` with `appeal_round` 0, `units_reserved` 0, `units_consumed` 0, an empty `unmet_step_therapy_classes` array, and `approved_units`, `units_remaining`, `decision_reason`, `determination_at`, `valid_from`, `valid_through`, `submitted_at` and `exception_attested_by_clinician_id` all null."
    Design: Corner/state_machines/creating_a_newer_authorization_expires_the_prior_draft_cross_entity
    """
    scenario, first, second = _two_authorization_intakes()

    superseded = scenario.refresh_authorization(first["id"])
    assert superseded["status"] == "EXPIRED", (
        f"the earlier draft is superseded, got {superseded['status']!r}"
    )
    assert superseded["decision_reason"] is not None, (
        "the supersede note must be recorded in the expired draft's decision_reason"
    )
    assert superseded["version"] == first["version"] + 1, (
        f"expected the superseded draft's version to advance to {first['version'] + 1}, "
        f"got {superseded['version']}"
    )

    newest = scenario.refresh_authorization(second["id"])
    assert newest["status"] == "DRAFT", (
        f"the newcomer stays DRAFT, got {newest['status']!r}"
    )
    assert newest["requested_units"] == 4
    assert newest["appeal_round"] == 0
    assert newest["units_reserved"] == 0
    assert newest["units_consumed"] == 0
    assert newest["approved_units"] is None
    assert newest["decision_reason"] is None

    episode = scenario.refresh_episode()
    assert episode["funding_state"] == "PENDING_AUTH", (
        f"a second intake leaves funding at PENDING_AUTH, got {episode['funding_state']!r}"
    )
    assert episode["therapy_state"] == "PLANNED"


def test_the_superseded_draft_can_no_longer_be_submitted_but_still_lists():
    """`EXPIRED` is terminal, so the superseded draft fails the submission
    state gate — yet it remains a readable row in the episode's list.

    PRD: "The status must be `DRAFT` or `DENIED`, else `ERR_AUTHORIZATION_STATE_INVALID`."
    Design: Corner/state_machines/creating_a_newer_authorization_expires_the_prior_draft_cross_entity
    """
    scenario, first, second = _two_authorization_intakes()

    response = api_client.submit_authorization(first["id"], fixtures.COORDINATOR)
    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_STATE_INVALID.value, 409)

    rows, meta = assertions.validate_list(
        api_client.list_authorizations(
            fixtures.ADMIN, params={"episode_id": scenario.episode_id}
        )
    )
    assert meta["total_count"] == 2, (
        f"both intakes survive as rows, expected total_count 2, got {meta['total_count']}"
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["status"] == "EXPIRED"
    assert by_id[second["id"]]["status"] == "DRAFT"


# ==========================================================================
# a_stale_expected_episode_version_blocks_the_authorization_write_until_a_refetch
# ==========================================================================
def _episode_with_a_stale_revision_token():
    """A PLANNED episode whose creation-time revision has been invalidated by
    an unrelated monitoring-lab write."""
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.planned_episode()
    stale_version = scenario.episode["version"]
    fixtures.file_monitoring_lab(scenario)
    return scenario, stale_version


def test_a_lab_invalidated_episode_token_is_refused_and_writes_nothing():
    """The concurrency token is the episode's live revision, so a monitoring
    panel filed by someone else invalidates it: the replay is refused and no
    authorization row and no funding transition survive the rejection.

    PRD: "Opening an authorization requires the non-optional field `expected_episode_version` in the request body, carrying the client's last observed `version` of the therapy episode named by `episode_id`."
    PRD: "If that number does not equal the episode's current `version`, the create is rejected with `ERR_STALE_EPISODE_VERSION` (HTTP 412)."
    PRD: "Every filed panel, whatever it grades and whatever the episode's state, refreshes the episode's `monitoring_status` and increments the episode's `version` by one."
    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_episode_version_blocks_the_authorization_write_until_a_refetch
    """
    scenario, stale_version = _episode_with_a_stale_revision_token()

    response = api_client.create_authorization(
        factories.create_authorization_payload(scenario.episode_id, stale_version, 6),
        fixtures.COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_STALE_EPISODE_VERSION.value, 412)

    _rows, meta = assertions.validate_list(
        api_client.list_authorizations(
            fixtures.COORDINATOR, params={"episode_id": scenario.episode_id}
        )
    )
    assert meta["total_count"] == 0, (
        f"a refused intake creates no authorization, got total_count {meta['total_count']}"
    )
    episode = scenario.refresh_episode()
    assert episode["funding_state"] == "UNFUNDED", (
        f"the refused intake left funding untouched at UNFUNDED, got {episode['funding_state']!r}"
    )
    assert episode["version"] == stale_version + 1, (
        f"only the monitoring-lab write moved the revision: expected {stale_version + 1}, "
        f"got {episode['version']}"
    )


def test_the_refetched_episode_revision_lets_the_same_write_through():
    """Re-reading the episode and spending the fresh revision admits the very
    same payload, which proves the block was the token and nothing else.

    PRD: "A new authorization is born in `status` `DRAFT` with `appeal_round` 0, `units_reserved` 0, `units_consumed` 0, an empty `unmet_step_therapy_classes` array, and `approved_units`, `units_remaining`, `decision_reason`, `determination_at`, `valid_from`, `valid_through`, `submitted_at` and `exception_attested_by_clinician_id` all null."
    PRD: "And the episode's `funding_state` is set to `PENDING_AUTH`, incrementing the episode's `version` by one — this is the transition `UNFUNDED → PENDING_AUTH` for a first request and `LAPSED → PENDING_AUTH` for a reauthorization after a coverage window has run out."
    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_episode_version_blocks_the_authorization_write_until_a_refetch
    """
    scenario, stale_version = _episode_with_a_stale_revision_token()

    refused = api_client.create_authorization(
        factories.create_authorization_payload(scenario.episode_id, stale_version, 6),
        fixtures.COORDINATOR,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_EPISODE_VERSION.value, 412)

    fresh_version = scenario.refresh_episode()["version"]
    assert fresh_version == stale_version + 1

    accepted = api_client.create_authorization(
        factories.create_authorization_payload(scenario.episode_id, fresh_version, 6),
        fixtures.COORDINATOR,
    )
    authorization = validate_success(accepted, 201)
    assert authorization["status"] == "DRAFT"
    assert authorization["requested_units"] == 6
    assert authorization["units_reserved"] == 0
    assert authorization["appeal_round"] == 0

    episode = scenario.refresh_episode()
    assert episode["funding_state"] == "PENDING_AUTH", (
        f"the accepted intake moves funding to PENDING_AUTH, got {episode['funding_state']!r}"
    )
    assert episode["monitoring_status"] == "CURRENT", (
        f"the benign panel left monitoring CURRENT, got {episode['monitoring_status']!r}"
    )


# ==========================================================================
# the_calendar_sweep_expires_on_strictly_after_but_flags_renewal_on_or_before
# ==========================================================================
def _coinciding_deadlines():
    """A plan whose `auth_validity_days` is 335 puts the authorization's
    `valid_through` and the copay card's `reauth_due_at` on the very same
    instant, 2027-07-02T00:00:00Z."""
    fixtures.set_clock(constants.CLOCK_DEFAULT)
    scenario = fixtures.planned_episode(
        plan_payload=factories.meridian_plan_payload(
            auth_validity_days=335, step_therapy_classes_required=[]
        )
    )
    episode_version = scenario.episode["version"]

    fixtures.open_authorization(scenario, requested_units=6)
    fixtures.submit_authorization(scenario)
    authorization = fixtures.approve_authorization(scenario, approved_units=6)

    enrollment = fixtures.active_enrollment(scenario, annual_benefit_cents=1_000_000)
    return scenario, episode_version, authorization, enrollment


def test_a_clock_sitting_exactly_on_both_deadlines_flags_renewal_but_expires_nothing():
    """At the instant that is both `valid_through` and `reauth_due_at`, expiry
    is strictly-after while renewal flagging is at-or-before, so the sweep
    reports {0, 0, 1} and the repeat reports zeroes.

    PRD: "When the sweep of §2.11 observes that the logical clock has reached or passed an active enrollment's `reauth_due_at`, that enrollment moves `ACTIVE → REAUTH_PENDING` and its `version` increments by one; the sweep counts each such enrollment in `enrollments_reauth_pending`."
    PRD: "It then writes `reauth_due_at` as `coverage_end` pulled back by 30 days, giving the counselor a month of lead time before coverage runs out."
    Design: Corner/cross_cutting_complexity_layers/the_calendar_sweep_expires_on_strictly_after_but_flags_renewal_on_or_before
    """
    scenario, _episode_version, authorization, enrollment = _coinciding_deadlines()

    assertions.assert_instant_equals(
        authorization["valid_through"], constants.instant(2027, 7, 2), "valid_through"
    )
    assertions.assert_instant_equals(
        enrollment["reauth_due_at"], constants.instant(2027, 7, 2), "reauth_due_at"
    )

    fixtures.set_clock(constants.instant(2027, 7, 2))
    first = fixtures.run_sweep()
    assert first["authorizations_expired"] == 0, (
        "expiry is strictly after valid_through, expected authorizations_expired 0, "
        f"got {first['authorizations_expired']}"
    )
    assert first["episodes_lapsed"] == 0, (
        f"expected episodes_lapsed 0, got {first['episodes_lapsed']}"
    )
    assert first["enrollments_reauth_pending"] == 1, (
        "renewal is flagged at or after reauth_due_at, expected "
        f"enrollments_reauth_pending 1, got {first['enrollments_reauth_pending']}"
    )

    second = fixtures.run_sweep()
    assert second["authorizations_expired"] == 0
    assert second["episodes_lapsed"] == 0
    assert second["enrollments_reauth_pending"] == 0, (
        f"the repeat run reports zeroes, got {second['enrollments_reauth_pending']}"
    )

    assert scenario.refresh_authorization()["status"] == "APPROVED"
    assert scenario.refresh_episode()["funding_state"] == "AUTHORIZED"
    assert scenario.refresh_enrollment()["status"] == "REAUTH_PENDING"


def test_one_day_later_the_same_authorization_expires_and_the_enrollment_is_not_recounted():
    """One day past the shared deadline the other half of the asymmetry fires:
    {1, 1, 0} — the enrollment is no longer `ACTIVE` and is not counted twice.

    PRD: "When the reauthorization sweep of §2.11 observes that the logical clock has passed an approved authorization's `valid_through`, that authorization moves `APPROVED → EXPIRED`, the episode's `funding_state` moves `AUTHORIZED → LAPSED`, and both revision counters increment by one; the sweep counts that pair in `authorizations_expired` and `episodes_lapsed`."
    PRD: "`units_remaining` is then set to `approved_units` less `units_reserved` less `units_consumed`, `determination_at` is stamped with the logical clock, `valid_from` defaults to the logical clock when the payload omits it, and `valid_through` defaults to `valid_from` advanced by the plan's `auth_validity_days` whole days."
    Design: Corner/cross_cutting_complexity_layers/the_calendar_sweep_expires_on_strictly_after_but_flags_renewal_on_or_before
    """
    scenario, episode_version, _authorization, _enrollment = _coinciding_deadlines()

    fixtures.set_clock(constants.instant(2027, 7, 2))
    fixtures.run_sweep()
    fixtures.run_sweep()

    fixtures.set_clock(constants.instant(2027, 7, 3))
    third = fixtures.run_sweep()
    assert third["authorizations_expired"] == 1, (
        f"expected authorizations_expired 1, got {third['authorizations_expired']}"
    )
    assert third["episodes_lapsed"] == 1, (
        f"expected episodes_lapsed 1, got {third['episodes_lapsed']}"
    )
    assert third["enrollments_reauth_pending"] == 0, (
        "the already-flagged enrollment is no longer ACTIVE, expected "
        f"enrollments_reauth_pending 0, got {third['enrollments_reauth_pending']}"
    )

    fourth = fixtures.run_sweep()
    assert fourth["authorizations_expired"] == 0
    assert fourth["episodes_lapsed"] == 0
    assert fourth["enrollments_reauth_pending"] == 0

    expired = scenario.refresh_authorization()
    assert expired["status"] == "EXPIRED", (
        f"expected the authorization EXPIRED, got {expired['status']!r}"
    )
    assert expired["approved_units"] == 6
    assert expired["units_remaining"] == 6, (
        f"expiry does not consume units, expected units_remaining 6, "
        f"got {expired['units_remaining']}"
    )

    episode = scenario.refresh_episode()
    assert episode["funding_state"] == "LAPSED", (
        f"expected funding_state LAPSED, got {episode['funding_state']!r}"
    )
    assert episode["version"] == episode_version + 3, (
        "PENDING_AUTH, AUTHORIZED and LAPSED are the only three funding moves: "
        f"expected version {episode_version + 3}, got {episode['version']}"
    )
