"""The approval ladder: the guards that decide whether an event may be
sanctioned, and the order in which they fire."""
from test_helpers import (
    api_client,
    approve_application,
    approve_application_raw,
    create_application,
    create_prize_report_payload,
    current_store_version,
    file_report,
    file_report_raw,
    get_allocation,
    get_application,
    get_set_release,
    make_store_organizer_headers,
    mint_code,
    redeem_code,
    set_clock,
    setup_application,
    setup_completed_application,
    setup_release_context,
    transition_application,
    validate_error,
)


def test_approval_is_refused_while_the_cited_set_is_prerelease(api):
    """PRD §3.3: "The set release the event cites must have reached `RELEASED`;
    an event tied to a set that is still `ANNOUNCED` or merely in its
    `PRERELEASE` window is not yet legal to run and is rejected with
    `ERR_SET_NOT_STREET_LEGAL`."

    Design: Difficulty/cross_entity_state_dependency/release_must_reach_released_before_application_can_be_approved
    """
    store, set_release, fmt = setup_release_context(settle=False)
    application = create_application(store, set_release, fmt, tier="LOCAL")

    set_clock("2026-09-12T12:00:00Z")
    assert get_set_release(set_release["id"])["status"] == "PRERELEASE"

    refused = approve_application_raw(
        application["id"], current_store_version(store["id"])
    )
    validate_error(refused, "ERR_SET_NOT_STREET_LEGAL", expected_status=409)

    still = get_application(application["id"])
    assert still["status"] == "SUBMITTED"
    assert still["prize_allocation_id"] is None, "no pool is synthesized on refusal"


def test_the_identical_approval_succeeds_once_the_set_is_street_legal(api):
    """PRD §3.7: "When the logical clock reaches the `street_date`, the release
    moves from `PRERELEASE` to `RELEASED`, and four things happen together. Every
    `ACTIVE` format gains an epoch entry for this set release, moving the release
    to legal status in all of them. Every event application whose
    `set_release_id` names this release becomes eligible for approval, which is
    the gate the sanctioning workflow described earlier depends on."
    PRD §3.3: "The set release the event cites must have reached `RELEASED`; an
    event tied to a set that is still `ANNOUNCED` or merely in its `PRERELEASE`
    window is not yet legal to run and is rejected with
    `ERR_SET_NOT_STREET_LEGAL`."

    Design: Difficulty/cross_entity_state_dependency/release_must_reach_released_before_application_can_be_approved
    """
    store, set_release, fmt = setup_release_context(settle=False)
    application = create_application(store, set_release, fmt, tier="LOCAL")

    set_clock("2026-09-12T12:00:00Z")
    refused = approve_application_raw(
        application["id"], current_store_version(store["id"])
    )
    validate_error(refused, "ERR_SET_NOT_STREET_LEGAL", expected_status=409)

    set_clock("2026-09-18T00:00:00Z")
    assert get_set_release(set_release["id"])["status"] == "RELEASED"

    approved = approve_application(application["id"], store["id"])
    assert approved["status"] == "APPROVED"
    assert approved["prize_allocation_id"] is not None


def test_an_application_opted_into_its_reporting_window_cannot_be_approved(api):
    """PRD §3.3: "The application's own `prizing_report_status` must be `NOT_DUE`
    at the moment of approval, so an application that has already been opted into
    the reporting window cannot be approved — that rejection is
    `ERR_REPORTING_WINDOW_OPEN`."

    Design: Corner/errors/error_reporting_window_open_blocks_approval_after_option_in
    """
    store, _set_release, _fmt, application, _allocation = setup_application(
        tier="QUALIFIER", approve=False
    )
    transition_application(application["id"], "OPTION_IN").raise_for_status()
    assert get_application(application["id"])["prizing_report_status"] == "DUE"

    refused = approve_application_raw(
        application["id"], current_store_version(store["id"])
    )
    validate_error(refused, "ERR_REPORTING_WINDOW_OPEN", expected_status=409)


def test_opting_back_out_reopens_approval_for_the_same_application(api):
    """PRD §3.4: "Opting in moves `prizing_report_status` to `DUE` and is allowed
    from `SUBMITTED`, `APPROVED` or `COMPLETED`; opting out moves it back to
    `NOT_DUE` from the same three states."
    PRD §3.3: "The application's own `prizing_report_status` must be `NOT_DUE`
    at the moment of approval, so an application that has already been opted into
    the reporting window cannot be approved — that rejection is
    `ERR_REPORTING_WINDOW_OPEN`."

    Design: Corner/errors/error_reporting_window_open_blocks_approval_after_option_in
    """
    store, _set_release, _fmt, application, _allocation = setup_application(
        tier="QUALIFIER", approve=False
    )
    transition_application(application["id"], "OPTION_IN").raise_for_status()
    refused = approve_application_raw(
        application["id"], current_store_version(store["id"])
    )
    validate_error(refused, "ERR_REPORTING_WINDOW_OPEN", expected_status=409)

    transition_application(application["id"], "OPTION_OUT").raise_for_status()
    assert get_application(application["id"])["prizing_report_status"] == "NOT_DUE"

    approved = approve_application(application["id"], store["id"])
    assert approved["status"] == "APPROVED"


def test_championship_approval_without_a_digital_invitation_is_refused(api):
    """PRD §3.3: "A `CHAMPIONSHIP` event additionally requires an invitation
    already in hand — an unredeemed `DIGITAL` code redemption whose `status` is
    `AVAILABLE` and which is bound to this specific application. An approval
    attempted without one is rejected with `ERR_INVITATION_REQUIRED`."

    Design: Corner/errors/error_invitation_required_for_championship_without_digital_code
    """
    store, _set_release, _fmt, application, _allocation = setup_application(
        tier="CHAMPIONSHIP", approve=False, invitation=False
    )
    # A redeemed PHYSICAL card is on hand, but a physical code is not an invitation.
    mint_code(application["id"], redemption_code="CHM-P1", code_kind="PHYSICAL")
    redeem_code(application["id"], "CHM-P1", store["id"], code_kind="PHYSICAL")

    refused = approve_application_raw(
        application["id"], current_store_version(store["id"])
    )
    validate_error(refused, "ERR_INVITATION_REQUIRED", expected_status=422)

    still = get_application(application["id"])
    assert still["status"] == "SUBMITTED"
    assert still["prize_allocation_id"] is None


def test_the_available_digital_card_satisfies_the_invitation_once_redeemed(api):
    """PRD §3.11: "A digital redemption bound to an application is precisely what
    satisfies that application's championship invitation requirement at approval
    time."
    PRD §3.3: "A `CHAMPIONSHIP` event additionally requires an invitation already
    in hand — an unredeemed `DIGITAL` code redemption whose `status` is
    `AVAILABLE` and which is bound to this specific application."

    Design: Corner/errors/error_invitation_required_for_championship_without_digital_code
    """
    store, _set_release, _fmt, application, _allocation = setup_application(
        tier="CHAMPIONSHIP", approve=False, invitation=False
    )
    # Without any invitation the approval is refused, even though a redeemed
    # PHYSICAL card is on hand (a physical code is not an invitation).
    mint_code(application["id"], redemption_code="CHM-P2", code_kind="PHYSICAL")
    redeem_code(application["id"], "CHM-P2", store["id"], code_kind="PHYSICAL")
    refused = approve_application_raw(
        application["id"], current_store_version(store["id"])
    )
    validate_error(refused, "ERR_INVITATION_REQUIRED", expected_status=422)

    # An AVAILABLE DIGITAL redemption is itself the invitation in hand, so the
    # same approval then succeeds without the card being redeemed.
    mint_code(application["id"], redemption_code="CHM-D2", code_kind="DIGITAL")
    approved = approve_application(application["id"], store["id"])
    assert approved["status"] == "APPROVED"
    assert approved["prize_allocation_id"] is not None


def test_a_declined_physical_card_does_not_serve_as_the_invitation(api):
    """PRD §3.3: "A `CHAMPIONSHIP` event additionally requires an invitation
    already in hand — an unredeemed `DIGITAL` code redemption whose `status` is
    `AVAILABLE` and which is bound to this specific application. An approval
    attempted without one is rejected with `ERR_INVITATION_REQUIRED`."
    PRD §3.11: "a card that has been declined is no longer in the `AVAILABLE`
    state that the approval precondition demands."

    Design: Corner/errors/error_invitation_required_for_championship_without_digital_code
    """
    store, _set_release, _fmt, application, _allocation = setup_application(
        tier="CHAMPIONSHIP", approve=False, invitation=False
    )
    mint_code(application["id"], redemption_code="CHM-P3", code_kind="PHYSICAL")
    declined = api_client.redeem_code(
        application["id"],
        {"redemption_code": "CHM-P3", "code_kind": "PHYSICAL", "action": "DECLINE"},
        make_store_organizer_headers(store["id"]),
    )
    declined.raise_for_status()

    refused = approve_application_raw(
        application["id"], current_store_version(store["id"])
    )
    validate_error(refused, "ERR_INVITATION_REQUIRED", expected_status=422)


def test_a_refused_report_filing_is_a_missing_reference_not_a_duplicate(api):
    """PRD §3.6: "Filing a second report against an application that already has
    one is rejected with `ERR_PRIZE_REPORT_ALREADY_FILED`, which is a permanent
    condition rather than a transient one."
    PRD §2.11: "The first reference that does not resolve to an existing row ends
    the request with `ERR_NOT_FOUND`; references later in the order are never
    reached."

    Design: Difficulty/priority_pair_validation_conflict/unknown_allocation_outranks_already_filed_report
    """
    store, _set_release, _fmt, application, allocation = setup_completed_application(
        tier="QUALIFIER"
    )
    report = file_report(
        application["id"], allocation["id"], store["id"],
        unclaimed_tp=6, reported_headcount=31,
    )
    assert report["unclaimed_tp"] == 6

    # The body names an allocation that resolves to nothing, so reference
    # resolution ends the request before the already-filed rule is reached.
    refused = file_report_raw(
        application["id"], store["id"],
        create_prize_report_payload(
            "00000000-0000-4000-8000-000000000000",
            unclaimed_tp=6, reported_headcount=31,
        ),
    )
    validate_error(refused, "ERR_NOT_FOUND", expected_status=404)


def test_the_first_report_still_stands_after_the_refused_second_filing(api):
    """PRD §3.6: "it adds the report's `unclaimed_tp` to the parent pool's
    `total_restored_tp`, which lifts the conserved invariant by exactly that
    amount"
    PRD §2.11: "The first reference that does not resolve to an existing row ends
    the request with `ERR_NOT_FOUND`; references later in the order are never
    reached."

    Design: Difficulty/priority_pair_validation_conflict/unknown_allocation_outranks_already_filed_report
    """
    store, _set_release, _fmt, application, allocation = setup_completed_application(
        tier="QUALIFIER"
    )
    report = file_report(
        application["id"], allocation["id"], store["id"],
        unclaimed_tp=6, reported_headcount=31,
    )

    refused = file_report_raw(
        application["id"], store["id"],
        create_prize_report_payload(
            "00000000-0000-4000-8000-000000000000",
            unclaimed_tp=6, reported_headcount=31,
        ),
    )
    validate_error(refused, "ERR_NOT_FOUND", expected_status=404)

    assert get_allocation(allocation["id"])["total_restored_tp"] == 6, (
        "the refused filing restores nothing"
    )
    row = get_application(application["id"])
    assert row["status"] == "REPORTED"
    assert row["prize_report_id"] == report["id"]