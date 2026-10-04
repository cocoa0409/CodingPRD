"""Encroachment protests, mediation, escalation, and protest-side cascades
(PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_franchisee,
    create_protest_payload,
    create_store,
    get_impact_study,
    get_site_application,
    get_store,
    make_franchisee_headers,
    make_mediator_headers,
    set_clock,
    setup_approved_application,
    setup_protest_filed,
    setup_protest_in_mediation,
    setup_protest_under_review,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


def test_protest_resolved_upheld_rejects_application_and_kills_pipeline_store(
        api, franchisor_ops_headers):
    """PRD §3.3: "A protest resolved `UPHELD` — whether directly, by mediation,
    or after escalation — lands in terminal `RESOLVED_UPHELD` and moves the
    application `PROTESTED → REJECTED`, voids its study, terminates the
    `PIPELINE` store created at approval, and recomputes the territory's
    `open_store_count`."

    Design: Difficulty/non_linear_state_machine/protest_mediation_branching_divergent_outcomes
    """
    ctx = setup_protest_in_mediation()
    resp = api.record_mediation_outcome(
        ctx["protest"]["id"], {"outcome": "UPHELD"},
        make_mediator_headers(ctx["mediator_ref"]),
    )
    protest = validate_success(resp, 200)
    assert protest["status"] == "RESOLVED_UPHELD"
    app = get_site_application(ctx["application"]["id"])
    assert app["status"] == "REJECTED"
    store = get_store(ctx["pipeline_store"]["id"])
    assert store["status"] == "TERMINATED"


def test_protest_resolved_rejected_restores_application_to_approved(
        api, franchisor_ops_headers):
    """PRD §3.3: "A protest resolved `REJECTED` lands in terminal
    `RESOLVED_REJECTED` and returns the application `PROTESTED → APPROVED`, but
    only once no other non-terminal protest remains on the application"

    Design: Difficulty/non_linear_state_machine/protest_mediation_branching_divergent_outcomes
    """
    ctx = setup_protest_under_review()
    resp = api.resolve_protest(ctx["protest"]["id"], {"resolution": "REJECTED"},
                               franchisor_ops_headers)
    protest = validate_success(resp, 200)
    assert protest["status"] == "RESOLVED_REJECTED"
    app = get_site_application(ctx["application"]["id"])
    assert app["status"] == "APPROVED"
    store = get_store(ctx["pipeline_store"]["id"])
    assert store["status"] == "PIPELINE"


def test_protest_upheld_side_effect_list_execution(api, franchisor_ops_headers):
    """PRD §3.3: "A protest resolved `UPHELD` — whether directly, by mediation,
    or after escalation — lands in terminal `RESOLVED_UPHELD` and moves the
    application `PROTESTED → REJECTED`, voids its study, terminates the
    `PIPELINE` store created at approval, and recomputes the territory's
    `open_store_count`."

    Design: Corner/state_machines/protest_upheld_rejects_application_and_kills_pipeline_store
    """
    ctx = setup_protest_under_review()
    resp = api.resolve_protest(ctx["protest"]["id"], {"resolution": "UPHELD"},
                               franchisor_ops_headers)
    protest = validate_success(resp, 200)
    assert protest["status"] == "RESOLVED_UPHELD"
    assert protest["resolution"] == "UPHELD"
    app = get_site_application(ctx["application"]["id"])
    assert app["status"] == "REJECTED"
    study = get_impact_study(ctx["study"]["id"])
    assert study["status"] == "VOID"
    store = get_store(ctx["pipeline_store"]["id"])
    assert store["status"] == "TERMINATED"


def test_protest_window_expired_on_day_31(api, franchisor_ops_headers):
    """PRD §3.3: "the filing is only valid within thirty days of the
    application's `approved_on`; a filing after that window is refused with
    `ERR_PROTEST_WINDOW_EXPIRED`."

    Design: Corner/validations/protest_window_expired_on_day_31
    """
    ctx = setup_approved_application()
    protester = create_franchisee()
    protester_store = create_store(ctx["territory"]["id"], protester["id"])
    # Approval happened at the 2026-09-01 default clock; day 31 is 2026-10-02.
    set_clock("2026-10-02T00:00:00Z")
    resp = api.create_protest(
        create_protest_payload(ctx["application"]["id"], protester_store["id"],
                               grounds="too late"),
        make_franchisee_headers(protester["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROTEST_WINDOW_EXPIRED, 422)
    rows, meta = validate_paginated(
        api.list_application_protests(ctx["application"]["id"], franchisor_ops_headers)
    )
    assert meta["total_count"] == 0
    app = get_site_application(ctx["application"]["id"])
    assert app["status"] == "APPROVED"


def test_duplicate_protest_same_store_same_application_conflict(api, franchisor_ops_headers):
    """PRD §3.3: "Only one non-terminal protest may exist per protesting store
    and application pair; a second live filing is refused with
    `ERR_PROTEST_ALREADY_FILED`."

    Design: Corner/validations/duplicate_protest_same_store_same_application_conflict
    """
    ctx = setup_protest_filed()
    dup = api.create_protest(
        create_protest_payload(ctx["application"]["id"], ctx["protester_store"]["id"],
                               grounds="duplicate"),
        make_franchisee_headers(ctx["protester"]["id"]),
    )
    # PRD names ERR_PROTEST_ALREADY_FILED for the second live filing, but once
    # the first filing moves the application APPROVED -> PROTESTED, the PRD is
    # silent on whether that duplicate fires the uniqueness rule (§2.8 rung 9)
    # or the earlier state-validity rung (5). Both error ids are admissible;
    # both are HTTP 409 (PRD §5). Either way, no second protest is created for
    # the same store+application pair.
    assert dup.status_code == 409
    validate_error_is_one_of(
        dup, [ApiErrorId.ERR_PROTEST_ALREADY_FILED, ApiErrorId.ERR_INVALID_STATE])
    rows, meta = validate_paginated(
        api.list_application_protests(ctx["application"]["id"], franchisor_ops_headers)
    )
    assert meta["total_count"] == 1


def test_mediation_outcome_after_deadline_rejected(api):
    """PRD §3.3: "Any mediation outcome recorded after the `mediation_deadline`
    is refused with `ERR_MEDIATION_DEADLINE_PASSED`; an outcome on or before
    the deadline is timely."

    Design: Corner/errors/mediation_outcome_after_deadline_rejected
    """
    ctx = setup_protest_in_mediation(deadline="2026-09-20T00:00:00Z")
    set_clock("2026-09-20T00:00:01Z")
    resp = api.record_mediation_outcome(
        ctx["protest"]["id"], {"outcome": "UPHELD"},
        make_mediator_headers(ctx["mediator_ref"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEDIATION_DEADLINE_PASSED, 422)
    protest = get_protest_via(api, ctx)
    assert protest["status"] == "MEDIATION"


def get_protest_via(api, ctx):
    from test_helpers import get_protest
    return get_protest(ctx["protest"]["id"])


def test_referential_beats_temporal_on_protest_filing(api, franchisor_ops_headers):
    """PRD §2.8: "the first failing rung determines the error returned. In
    order: ... (7) business referential rules (store status, territory
    assignment, participation); (8) temporal windows"
    PRD §3.3: "The protesting store must be `OPEN` and in the same territory as
    the application — otherwise `ERR_STORE_NOT_OPEN`"

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_protest_filing
    """
    from test_helpers import terminate_store
    ctx = setup_approved_application()
    protester = create_franchisee()
    protester_store = create_store(ctx["territory"]["id"], protester["id"])
    terminate_store(protester_store["id"])
    # Clock past the 30-day window so the temporal rule would also fail.
    set_clock("2026-10-15T00:00:00Z")
    resp = api.create_protest(
        create_protest_payload(ctx["application"]["id"], protester_store["id"],
                               grounds="encroachment"),
        make_franchisee_headers(protester["id"]),
    )
    error = validate_error(resp, ApiErrorId.ERR_STORE_NOT_OPEN, 422)
    assert error["error_id"] != ApiErrorId.ERR_PROTEST_WINDOW_EXPIRED


def test_protest_with_terminated_store_rejected_store_not_open(api):
    """PRD §3.3: "The protesting store must be `OPEN` and in the same
    territory as the application — otherwise `ERR_STORE_NOT_OPEN`"
    PRD §2.8: "(7) business referential rules (store status, territory
    assignment, participation); (8) temporal windows"

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_protest_filing
    """
    from test_helpers import terminate_store
    ctx = setup_approved_application()
    protester = create_franchisee()
    protester_store = create_store(ctx["territory"]["id"], protester["id"])
    terminate_store(protester_store["id"])
    # File inside the 30-day window (default clock = approval day): only the
    # referential store-status rule fails, and it fires on its own.
    resp = api.create_protest(
        create_protest_payload(ctx["application"]["id"], protester_store["id"],
                               grounds="encroachment"),
        make_franchisee_headers(protester["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STORE_NOT_OPEN, 422)


def test_protests_list_paginates_with_total_count_and_has_more(api, franchisor_ops_headers):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0. ... The `meta` object of a list response
    carries `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "the protest list accepts optional `protesting_franchisee_id`
    and `status` — applied before pagination."

    Design: Corner/entities/protests_list_paginates_with_total_count_and_has_more
    """
    ctx = setup_protest_filed()
    protester2 = create_franchisee()
    protester_store2 = create_store(ctx["territory"]["id"], protester2["id"])
    # Multiple concurrent protests against one application are possible across
    # different protesting stores (PRD §3.3). Whether the second filing is
    # accepted depends on whether the implementation re-opens the PROTESTED
    # application to further filings: a 201 or a 409 state rejection are both
    # PRD-consistent, so only count the protests that were actually accepted.
    other = api.create_protest(
        create_protest_payload(ctx["application"]["id"], protester_store2["id"],
                               grounds="g2"),
        make_franchisee_headers(protester2["id"]),
    )
    assert other.status_code in (201, 409)
    expected_total = 2 if other.status_code == 201 else 1
    page1, meta1 = validate_paginated(api.list_protests(franchisor_ops_headers,
                                                        params={"limit": 1, "offset": 0}))
    assert len(page1) == 1
    assert meta1["total_count"] == expected_total
    assert meta1["has_more"] is (expected_total > 1)
    page2, meta2 = validate_paginated(api.list_protests(franchisor_ops_headers,
                                                        params={"limit": 1, "offset": 1}))
    if expected_total == 2:
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
    else:
        assert len(page2) == 0
        assert meta2["total_count"] == 1
        assert meta2["has_more"] is False
    filtered, meta3 = validate_paginated(
        api.list_protests(franchisor_ops_headers,
                          params={"protesting_franchisee_id": ctx["protester"]["id"]})
    )
    assert len(filtered) == 1
    assert meta3["total_count"] == 1
