"""Cross-cutting layers: optimistic concurrency on two different parents, and the
immediacy of the consistency model.

The two version guards use different fields, different parents and different
errors, and both are checked against the live stored version rather than a
monotonic floor. The third test shows that a single mutating response already
carries every side effect of the transition it performed.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_STALE_CYCLE_VERSION,
    ERR_STALE_ENGAGEMENT_VERSION,
)
from test_helpers.constants import (
    CYCLE_INPUTS_LOCKED,
    ENGAGEMENT_ACTIVE,
    ENGAGEMENT_TRANSITION_PLANNED,
    FILING_PENDING,
    FILING_TYPE_INCOME_TAX_WITHHOLDING,
    FILING_TYPE_SOCIAL_INSURANCE,
    GTN_CLEARED,
    INPUT_FILE_VALIDATED,
)
from test_helpers.test_users import CONTROLLER_HEADERS, OPS_HEADERS

_AUGUST_CUTOFF = "2026-08-26T17:00:00.000Z"


def test_stale_expected_cycle_version_on_run_creation_is_refused_then_retried(api):
    """The version captured before the lock is exactly one behind, so the run is refused;
    the freshly read version succeeds and immediately makes that value stale in turn.

    PRD 2.7: "If that value does not equal the cycle's current stored `version`, the
    request is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412) and nothing at all is
    written — no run is created, no earlier run is superseded, and the cycle is
    untouched."

    PRD 2.7: "A matching request succeeds and increments the cycle's `version` by 1, so
    any later request built on the pre-submission read is itself rejected."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_cycle_version_on_run_creation_is_refused_then_retried
    """
    ctx = fx.setup_validated_extract(api)
    assert ctx["cycle"]["version"] == 1, (
        f"a freshly opened cycle is at version 1, got {ctx['cycle']['version']}"
    )
    # PRD 3.4 writes `input_submitter_user_id` onto the cycle when the extract is
    # submitted, and PRD 2.4 increments `version` by exactly 1 on every mutation
    # of that row, so the live pre-lock version is 2.
    version_before_the_lock = fx.read_cycle(api, ctx["cycle_id"])["version"]
    assert version_before_the_lock == 2, (
        "the extract submission mutated the cycle to version 2, got "
        f"{version_before_the_lock}"
    )
    locked = fx.lock_inputs(api, ctx["cycle_id"])
    assert locked["version"] == 3, (
        f"the lock increments the version to 3, got {locked['version']}"
    )

    stale = api.create_gtn_run(
        f.gtn_run_payload(
            ctx["cycle_id"], ctx["input_file_id"], version_before_the_lock
        ),
        ctx["provider_headers"],
    )
    validate_error(stale, ERR_STALE_CYCLE_VERSION, 412)

    runs, meta = validate_paginated(
        api.list_gtn_runs(CONTROLLER_HEADERS, {"cycle_id": ctx["cycle_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert runs == [], f"nothing at all was written, got {runs}"
    untouched = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_common_fields(untouched, expected_version=3)
    a.assert_cycle_state(untouched, CYCLE_INPUTS_LOCKED)

    fresh_body = f.gtn_run_payload(
        ctx["cycle_id"], ctx["input_file_id"], locked["version"]
    )
    accepted = validate_success(
        api.create_gtn_run(fresh_body, ctx["provider_headers"]), 201
    )
    assert accepted["status"] == GTN_CLEARED, (
        f"the matching request is accepted, got {accepted['status']}"
    )
    after = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_common_fields(after, expected_version=4)

    replay = api.create_gtn_run(fresh_body, ctx["provider_headers"])
    validate_error(replay, ERR_STALE_CYCLE_VERSION, 412)
    a.assert_common_fields(fx.read_cycle(api, ctx["cycle_id"]), expected_version=4)


def test_stale_expected_engagement_version_on_transition_plan_is_refused(api):
    """The second version guard names a different parent and a different error: the
    version read at creation is stale once the residency decision lands, and no plan
    field is written until the live version is presented.

    PRD 2.7: "If it does not equal the engagement's current stored `version`, the request
    is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412) and no plan field changes."

    PRD 3.8: "A written plan moves the engagement to `TRANSITION_PLANNED` and populates
    the four plan fields from the request: `transition_incoming_provider_id` from
    `incoming_provider_id`, `transition_cutover_start_date` as the inclusive first date of
    the cutover window, `transition_cutover_end_date` as the exclusive last date of that
    window, and `transition_parallel_run_cycles` from `parallel_run_cycles`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_engagement_version_on_transition_plan_is_refused
    """
    country = fx.create_country(
        api, required_filing_types=[FILING_TYPE_INCOME_TAX_WITHHOLDING]
    )
    incumbent = fx.create_provider(api)
    incoming = fx.create_rival_provider(api)
    engagement = fx.create_engagement(api, country["id"], incumbent["id"])
    version_at_creation = engagement["version"]
    assert version_at_creation == 1, (
        f"a freshly formed engagement is at version 1, got {version_at_creation}"
    )
    activated = fx.approve_residency(api, engagement["id"])
    assert activated["status"] == ENGAGEMENT_ACTIVE, (
        f"the approval activates the engagement, got {activated['status']}"
    )
    a.assert_common_fields(activated, expected_version=2)

    stale = api.transition_plan(
        engagement["id"],
        f.transition_plan_payload(incoming["id"], version_at_creation),
        CONTROLLER_HEADERS,
    )
    validate_error(stale, ERR_STALE_ENGAGEMENT_VERSION, 412)

    untouched = fx.read_engagement(api, engagement["id"])
    assert untouched["status"] == ENGAGEMENT_ACTIVE, (
        f"the engagement is still active, got {untouched['status']}"
    )
    a.assert_null_fields(
        untouched,
        [
            "transition_incoming_provider_id",
            "transition_cutover_start_date",
            "transition_cutover_end_date",
            "transition_parallel_run_cycles",
        ],
    )
    a.assert_common_fields(untouched, expected_version=2)

    planned = validate_success(
        api.transition_plan(
            engagement["id"],
            f.transition_plan_payload(incoming["id"], activated["version"]),
            CONTROLLER_HEADERS,
        )
    )
    assert planned["status"] == ENGAGEMENT_TRANSITION_PLANNED, (
        f"the matching request writes the plan, got {planned['status']}"
    )
    a.assert_field_values(
        planned,
        {
            "transition_incoming_provider_id": incoming["id"],
            "transition_cutover_start_date": "2026-10-01",
            "transition_cutover_end_date": "2026-11-01",
            "transition_parallel_run_cycles": 1,
        },
    )
    a.assert_common_fields(planned, expected_version=3)


def test_lock_inputs_response_already_carries_every_side_effect(api):
    """Consistency is immediate: the single lock response reports the new status, the
    resolved cutoff and the incremented version, and the obligations it minted are
    visible to the very next read.

    PRD 3.4: "A successful lock does four things beyond moving the cycle `DRAFT →
    INPUTS_LOCKED`. It mints one statutory filing for every member of the country's
    `required_filing_types`, each opening in status `PENDING` with `responsibility` copied
    from the engagement's `filing_responsibility` and with a `due_at` resolved as
    described below. It increases the country profile's `open_filing_obligation_count` by
    the number of filings minted."

    PRD 2.4: "and `version`, an integer that starts at 1 on creation and increases by
    exactly 1 on every mutation of that row."

    Design: Corner/consistency_model/lock_inputs_response_shows_every_side_effect_immediately
    """
    ctx = fx.setup_validated_extract(api)
    country_before = fx.read_country(api, ctx["country_id"])
    assert country_before["required_filing_types"] == [
        FILING_TYPE_INCOME_TAX_WITHHOLDING,
        FILING_TYPE_SOCIAL_INSURANCE,
    ], f"the country requires two filings, got {country_before['required_filing_types']}"
    assert country_before["open_filing_obligation_count"] == 0, (
        f"no obligation is live yet, got {country_before['open_filing_obligation_count']}"
    )
    assert ctx["input_file"]["status"] == INPUT_FILE_VALIDATED, (
        f"the cycle carries a validated extract, got {ctx['input_file']['status']}"
    )

    locked = validate_success(api.lock_inputs(ctx["cycle_id"], OPS_HEADERS))

    a.assert_cycle_state(locked, CYCLE_INPUTS_LOCKED)
    a.assert_instant_equals(locked["input_cutoff_at"], _AUGUST_CUTOFF, "input_cutoff_at")
    # Version 3: creation (1), the extract submission's write of
    # `input_submitter_user_id` onto the cycle (2), and the lock itself (3).
    a.assert_common_fields(locked, expected_version=3)

    filings, meta = validate_paginated(
        api.list_filings(OPS_HEADERS, {"cycle_id": ctx["cycle_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=2, expected_has_more=False)
    for filing in filings:
        assert filing["status"] == FILING_PENDING, (
            f"a freshly minted obligation is PENDING, got {filing['status']}"
        )

    country_after = fx.read_country(api, ctx["country_id"])
    assert country_after["open_filing_obligation_count"] == 2, (
        "the counter rose by the number minted, got "
        f"{country_after['open_filing_obligation_count']}"
    )
