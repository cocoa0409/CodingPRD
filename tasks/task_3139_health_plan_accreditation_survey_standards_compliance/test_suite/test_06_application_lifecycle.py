"""Application lifecycle, evidence review cycle, withdraw and supersede
cascades (PRD §3.1, §3.3)."""
from test_helpers import (
    ApiErrorId,
    add_evidence,
    advance_to_survey_scheduling,
    begin_evidence_review,
    create_edition,
    create_plan,
    create_scope,
    create_application,
    get_app,
    get_success_data,
    make_accreditation_officer_headers,
    make_plan_coordinator_headers,
    make_platform_admin_headers,
    set_clock,
    setup_base,
    setup_evidence_review,
    submit_application,
    validate_error,
)
from test_helpers.fixtures import api_client


def _officer():
    return make_accreditation_officer_headers()


def _admin():
    return make_platform_admin_headers()


def test_evidence_reject_resubmit_cycle(api):
    """PRD §3.3: "A rejected item can be resubmitted by the plan's coordinator;
    resubmission requires the item to be `REJECTED` (otherwise
    `ERR_EVIDENCE_NOT_RESUBMITTABLE`) and the application to remain in
    `EVIDENCE_REVIEW`. Resubmitting moves the item back to `SUBMITTED`,
    increments `revision_count` by 1, resets `review_note` to null, and accepts
    an optional new `title`."

    Design: Difficulty/non_linear_state_machine/evidence_item_reject_resubmit_cycle
    """
    ctx = setup_evidence_review()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    ev = add_evidence(app_id, plan_id, ctx["elements"]["UM-1"], "UM policy")

    rejected = get_success_data(
        api_client.reject_evidence_item(ev["id"], {"review_note": "missing signature page"},
                                        _officer())
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["review_note"] == "missing signature page"

    resubmitted = get_success_data(
        api_client.resubmit_evidence_item(ev["id"], {"title": "UM policy v2"},
                                          make_plan_coordinator_headers(plan_id))
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1
    assert resubmitted["review_note"] is None
    assert resubmitted["title"] == "UM policy v2"

    accepted = get_success_data(
        api_client.accept_evidence_item(ev["id"], {}, _officer())
    )
    assert accepted["status"] == "ACCEPTED"


def test_evidence_cycle_can_repeat_before_terminal_accept(api):
    """PRD §3.3: "A rejected item can be resubmitted by the plan's coordinator"
    and "Resubmitting moves the item back to `SUBMITTED`, increments
    `revision_count` by 1" — a second reject/resubmit round increments the
    counter again.

    Design: Difficulty/non_linear_state_machine/evidence_item_reject_resubmit_cycle
    """
    ctx = setup_evidence_review()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    ev = add_evidence(app_id, plan_id, ctx["elements"]["UM-1"], "UM policy")

    for round_no in (1, 2):
        get_success_data(api_client.reject_evidence_item(
            ev["id"], {"review_note": f"round {round_no} gap"}, _officer()))
        resub = get_success_data(api_client.resubmit_evidence_item(
            ev["id"], {}, make_plan_coordinator_headers(plan_id)))
        assert resub["revision_count"] == round_no
        assert resub["review_note"] is None
        assert resub["status"] == "SUBMITTED"

    accepted = get_success_data(api_client.accept_evidence_item(ev["id"], {}, _officer()))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["revision_count"] == 2


def test_withdraw_cascade_voids_submitted_evidence(api):
    """PRD §3.3: "When an application is withdrawn from `DRAFT` or `SUBMITTED`,
    every evidence item still in `SUBMITTED` is voided automatically by the
    system (status becomes `VOIDED`)."

    Design: Difficulty/transitive_cascade/withdraw_cascade_evidence_voiding
    """
    ctx = setup_base()
    app = submit_application(ctx["app"]["id"], ctx["plan"]["id"])
    ev = add_evidence(app["id"], ctx["plan"]["id"], ctx["elements"]["UM-1"],
                      "UM policy pre-review")
    assert ev["status"] == "SUBMITTED"

    withdrawn = get_success_data(
        api_client.withdraw_application(app["id"], make_plan_coordinator_headers(ctx["plan"]["id"]))
    )
    assert withdrawn["status"] == "WITHDRAWN"

    ev_after = get_success_data(api_client.get_evidence_item(ev["id"], _officer()))
    assert ev_after["status"] == "VOIDED"

    r = api_client.withdraw_application(app["id"], make_plan_coordinator_headers(ctx["plan"]["id"]))
    validate_error(r, ApiErrorId.ERR_APPLICATION_INVALID_STATE)


def test_withdraw_cascade_voids_all_submitted_evidence_items(api):
    """PRD §3.3: "When an application is withdrawn from `DRAFT` or `SUBMITTED`,
    every evidence item still in `SUBMITTED` is voided automatically by the
    system (status becomes `VOIDED`)."

    Design: Difficulty/transitive_cascade/withdraw_cascade_evidence_voiding
    """
    ctx = setup_base()
    app = submit_application(ctx["app"]["id"], ctx["plan"]["id"])
    ev_a = add_evidence(app["id"], ctx["plan"]["id"], ctx["elements"]["UM-1"], "A")
    ev_b = add_evidence(app["id"], ctx["plan"]["id"], ctx["elements"]["UM-1"], "B")

    get_success_data(api_client.withdraw_application(
        app["id"], make_plan_coordinator_headers(ctx["plan"]["id"])))

    for ev in (ev_a, ev_b):
        after = get_success_data(api_client.get_evidence_item(ev["id"], _officer()))
        assert after["status"] == "VOIDED"


def test_supersede_cascade_withdraws_draft_application(api):
    """PRD §3.1: "Superseding moves the path edition to `SUPERSEDED`, increments
    its `version`, and cascades: every `AccreditationApplication` whose
    `standards_edition_id` equals this edition and whose status is still `DRAFT`
    is withdrawn by the system (status becomes `WITHDRAWN`, the application's
    `version` increments), and the withdrawal in turn voids every `SUBMITTED`
    evidence item on those applications (status becomes `VOIDED`)."

    Design: Difficulty/transitive_cascade/supersede_cascade_edition_application_evidence
    """
    set_clock()
    elements = [{"element_code": "UM-1", "category": "UM", "max_points": 4,
                 "is_must_pass": True, "evidence_required_count": 2}]
    edition, _ = create_edition(publish=True, elements=elements)
    plan = create_plan()
    scope = create_scope(plan["id"])
    app = create_application(plan["id"], scope["id"], edition["id"])
    assert app["status"] == "DRAFT"

    edition_2027, _ = create_edition(
        publish=True,
        elements=[{"element_code": "UM-1", "category": "UM", "max_points": 4,
                   "is_must_pass": True, "evidence_required_count": 1}],
        edition_year=2027,
        effective_from="2027-01-01T00:00:00Z",
        effective_until="2028-12-31T23:59:59Z",
    )

    superseded = get_success_data(api_client.supersede_standards_edition(
        edition["id"], {"superseded_by_edition_id": edition_2027["id"]}, _admin()))
    assert superseded["status"] == "SUPERSEDED"

    app_after = get_app(app["id"])
    assert app_after["status"] == "WITHDRAWN", (
        "cascade hop 2: the DRAFT application on the superseded edition is withdrawn"
    )
    ed2_after = get_success_data(api_client.get_standards_edition(edition_2027["id"], _admin()))
    assert ed2_after["status"] == "PUBLISHED"


def test_supersede_leaves_non_draft_applications_alone(api):
    """PRD §3.1: "every `AccreditationApplication` whose `standards_edition_id`
    equals this edition and whose status is still `DRAFT` is withdrawn by the
    system" — an application past DRAFT is not part of the cascade.

    Design: Difficulty/transitive_cascade/supersede_cascade_edition_application_evidence
    """
    set_clock()
    elements = [{"element_code": "UM-1", "category": "UM", "max_points": 4,
                 "is_must_pass": True, "evidence_required_count": 2}]
    edition, _ = create_edition(publish=True, elements=elements)
    plan = create_plan()
    scope = create_scope(plan["id"])
    app = create_application(plan["id"], scope["id"], edition["id"])
    app = submit_application(app["id"], plan["id"])
    assert app["status"] == "SUBMITTED"

    edition_2027, _ = create_edition(
        publish=True,
        elements=[{"element_code": "UM-1", "category": "UM", "max_points": 4,
                   "is_must_pass": True, "evidence_required_count": 1}],
        edition_year=2027,
        effective_from="2027-01-01T00:00:00Z",
        effective_until="2028-12-31T23:59:59Z",
    )
    get_success_data(api_client.supersede_standards_edition(
        edition["id"], {"superseded_by_edition_id": edition_2027["id"]}, _admin()))

    app_after = get_app(app["id"])
    assert app_after["status"] == "SUBMITTED"


def test_application_submit_from_submitted_returns_invalid_state(api):
    """PRD §3.3: "Submitting is one of the three OCC-guarded writes (see §2.6)
    and enforces four preconditions, evaluated in this order: the application
    must be in `DRAFT` (otherwise `ERR_APPLICATION_INVALID_STATE`); the
    `expected_application_version` must match the application's current
    `version` (otherwise `ERR_STALE_VERSION`)". PRD §2.5 item 6 lists optimistic
    concurrency before item 7 (state-machine preconditions).

    Design: Corner/state_machines/application_submit_from_submitted_returns_invalid_state
    """
    ctx = setup_base()
    plan_id = ctx["plan"]["id"]
    app = ctx["app"]
    submitted = submit_application(app["id"], plan_id)
    assert submitted["status"] == "SUBMITTED"

    # Replay with the pre-submit version: both the state precondition (§3.3
    # orders the DRAFT check first) and the OCC precondition (§2.5 orders item 6
    # before item 7) are violated; the PRD names both orderings, so either
    # error is a faithful resolution of the doubly-violated request.
    r_stale = api_client.submit_application(
        app["id"], {"expected_application_version": app["version"]},
        make_plan_coordinator_headers(plan_id))
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(
        r_stale, [ApiErrorId.ERR_STALE_VERSION, ApiErrorId.ERR_APPLICATION_INVALID_STATE])
    assert r_stale.status_code in (409, 412)

    # Replay with the current version: the state precondition then fires (409).
    current = get_app(app["id"])
    r_state = api_client.submit_application(
        app["id"], {"expected_application_version": current["version"]},
        make_plan_coordinator_headers(plan_id))
    validate_error(r_state, ApiErrorId.ERR_APPLICATION_INVALID_STATE)
    assert r_state.status_code == 409


def test_terminal_withdrawn_lockdown(api):
    """PRD §3.3: "Evidence assembly begins when an `AccreditationOfficer` begins
    evidence review, moving the application from `SUBMITTED` to
    `EVIDENCE_REVIEW` (wrong-state invocations return
    `ERR_APPLICATION_INVALID_STATE`)."

    Design: Corner/state_machines/terminal_withdrawn_lockdown
    """
    ctx = setup_base()
    plan_id = ctx["plan"]["id"]
    get_success_data(api_client.withdraw_application(
        ctx["app"]["id"], make_plan_coordinator_headers(plan_id)))

    r = api_client.begin_evidence_review(ctx["app"]["id"], _officer())
    validate_error(r, ApiErrorId.ERR_APPLICATION_INVALID_STATE)
    assert r.status_code == 409


def test_evidence_accept_from_accepted_rejected(api):
    """PRD §3.3: "Accept or reject on an item not in `SUBMITTED` is rejected
    with `ERR_EVIDENCE_NOT_REVIEWABLE`"."

    Design: Corner/state_machines/evidence_accept_from_accepted_rejected
    """
    ctx = setup_evidence_review()
    ev = add_evidence(ctx["app"]["id"], ctx["plan"]["id"], ctx["elements"]["UM-1"],
                      "UM policy")
    get_success_data(api_client.accept_evidence_item(ev["id"], {}, _officer()))

    r = api_client.reject_evidence_item(ev["id"], {"review_note": "late rejection"},
                                        _officer())
    validate_error(r, ApiErrorId.ERR_EVIDENCE_NOT_REVIEWABLE)
    assert r.status_code == 409
