"""State machine edges: opening states, terminal states, lazy expiry and posture recomputation."""

from test_helpers import (
    CLOCK_EPOCH,
    PERMIT_OFFICE,
    PERMIT_OFFICE_USER_ID,
    PM,
    UTILITY,
    ApiErrorId,
    api_client,
    assert_build_zone,
    assert_cents,
    assert_crew_load,
    assert_install_appointment,
    assert_instant_equals,
    assert_instant_is_null,
    assert_mdu_agreement,
    assert_permit_application,
    assert_pole_attachment_request,
    assert_preorder,
    assert_total_count,
    list_ledger_for_preorder,
    make_appointment,
    make_crew,
    make_mdu_owner_headers,
    make_permit,
    make_pole_request,
    make_preorder,
    make_subscriber_headers,
    owner_response_payload,
    permit_application_payload,
    permit_decision_payload,
    read_account,
    read_appointment,
    read_crew,
    read_preorder,
    read_zone,
    record_outcome,
    set_clock,
    setup_campaign_with_zone,
    setup_completed_bury_appointment,
    setup_mdu_address_with_agreement,
    setup_serviceable_address,
    validate_error,
    validate_success,
)

AGREEMENT_EXPIRY = "2026-08-15T00:00:00Z"
PERMIT_EXPIRY_AFTER_120_DAYS = "2026-11-29T00:00:00Z"
RESTORATION_DUE_BY = "2026-10-12T11:00:00Z"
FOLLOWUP_COMPLETION = "2026-10-06T10:00:00Z"


def test_a_new_permit_application_opens_in_draft_with_every_decision_column_null():
    """Opening an application is not submitting it, so nothing about a review is stamped yet.

    PRD 3.5: "The application opens in status `DRAFT` with `submission_round` 0 and
    `approved_at`, `expires_at`, `rejection_reason` and `reviewer_user_id` all null, and opening
    it recomputes the zone's `readiness_posture`."

    Design: Corner/state_machines/permit_application_starts_in_draft
    """
    base = setup_campaign_with_zone(zone_overrides={"required_permit_types": ["ROW"]})

    response = api_client.create_permit_application(
        permit_application_payload(base["zone"]["id"]), PM
    )

    application = validate_success(response, 201)
    assert_permit_application(application)
    assert application["status"] == "DRAFT", application["status"]
    assert application["submission_round"] == 0, application["submission_round"]
    assert application["approved_at"] is None, application["approved_at"]
    assert application["expires_at"] is None, application["expires_at"]
    assert application["rejection_reason"] is None, application["rejection_reason"]
    assert application["reviewer_user_id"] is None, application["reviewer_user_id"]
    assert application["valid_days"] == 120, application["valid_days"]
    assert application["max_resubmissions"] == 2, application["max_resubmissions"]

    zone = read_zone(base["zone"]["id"])
    assert_build_zone(zone)
    assert zone["readiness_posture"] == "BLOCKED", zone["readiness_posture"]


def test_deciding_a_draft_permit_application_is_refused_as_a_state_error():
    """The office is asked to approve a paper that was never filed, so the review cannot start.

    PRD 3.5: "Deciding a `DRAFT` application, or submitting one that is `APPROVED` or `EXPIRED`,
    is `ERR_PERMIT_APPLICATION_STATE_INVALID`."

    Design: Corner/state_machines/permit_decision_before_submit_returns_permit_application_state_invalid
    """
    base = setup_campaign_with_zone(zone_overrides={"required_permit_types": ["ROW"]})
    application = make_permit(base["zone"]["id"], target_status="DRAFT")

    response = api_client.decide_permit_application(
        application["id"], permit_decision_payload("APPROVE"), PERMIT_OFFICE
    )

    validate_error(response, ApiErrorId.ERR_PERMIT_APPLICATION_STATE_INVALID, 409)
    reread = validate_success(api_client.get_permit_application(application["id"], PM))
    assert_permit_application(reread)
    assert reread["status"] == "DRAFT", reread["status"]
    assert reread["approved_at"] is None, reread["approved_at"]
    assert reread["reviewer_user_id"] is None, reread["reviewer_user_id"]
    assert reread["version"] == application["version"], reread["version"]
    assert read_zone(base["zone"]["id"])["readiness_posture"] == "BLOCKED"


def test_confirming_attachment_before_the_quote_is_accepted_is_refused():
    """A surveyed request has a price but no commitment, so nothing may be hung on the poles.

    PRD 3.5: "`DENIED` and `ATTACHED` are both terminal, and a decision before a survey, an
    attachment before an acceptance, or any action on a request that is already `DENIED` or
    `ATTACHED`, is `ERR_POLE_REQUEST_STATE_INVALID`."

    Design: Corner/state_machines/pole_attachment_before_acceptance_returns_pole_request_state_invalid
    """
    base = setup_campaign_with_zone(zone_overrides={"required_permit_types": ["ROW"]})
    request = make_pole_request(
        base["zone"]["id"], target_status="SURVEYED", make_ready_cost_cents=45600
    )

    response = api_client.attach_pole_attachment_request(request["id"], UTILITY)

    validate_error(response, ApiErrorId.ERR_POLE_REQUEST_STATE_INVALID, 409)
    reread = validate_success(
        api_client.get_pole_attachment_request(request["id"], PM)
    )
    assert_pole_attachment_request(reread)
    assert reread["status"] == "SURVEYED", reread["status"]
    assert_cents(reread["make_ready_cost_cents"], 45600, "make_ready_cost_cents")
    assert reread["attached_at"] is None, reread["attached_at"]
    assert_cents(
        read_zone(base["zone"]["id"])["make_ready_cost_cents"],
        0,
        "zone.make_ready_cost_cents",
    )


def test_cancelling_an_already_cancelled_preorder_appends_no_second_refund():
    """The lifecycle dimension has already come to rest, so the money dimension must not move again.

    PRD 2.5: "The money dimension is driven only as a consequence of lifecycle movement - it is
    never addressed directly by any endpoint - but it is a distinct dimension nonetheless, with
    `REFUNDED`, `APPLIED` and `FORFEITED` all terminal, and `CONVERTED`, `CANCELLED` and `LAPSED`
    terminal on the lifecycle side."

    Design: Corner/state_machines/second_cancel_of_cancelled_preorder_returns_preorder_state_invalid
    """
    base = setup_serviceable_address()
    account = base["account"]
    preorder = make_preorder(
        base["zone"]["id"], base["address"]["id"], account["id"]
    )
    subscriber = make_subscriber_headers(account["id"])
    validate_success(api_client.cancel_preorder(preorder["id"], subscriber))

    response = api_client.cancel_preorder(preorder["id"], subscriber)

    validate_error(response, ApiErrorId.ERR_PREORDER_STATE_INVALID, 409)
    reread = read_preorder(preorder["id"])
    assert_preorder(reread)
    assert reread["preorder_status"] == "CANCELLED", reread["preorder_status"]
    assert reread["deposit_status"] == "REFUNDED", reread["deposit_status"]
    entries, listing = list_ledger_for_preorder(preorder["id"])
    assert_total_count(listing, 2)
    assert [entry["entry_type"] for entry in entries] == [
        "DEPOSIT_HELD",
        "DEPOSIT_REFUNDED",
    ], entries
    assert_cents(
        read_account(account["id"])["deposit_held_cents"], 0, "deposit_held_cents"
    )


def test_a_signed_agreement_refuses_a_later_decline_from_the_same_owner():
    """The owner already signed, so the decline branch has no admissible source state left.

    PRD 3.2: "Declining is likewise admissible from `SENT` and from `COUNTERED`, again only while
    the clock is strictly before `expires_at`, and again the two branches behave identically."

    Design: Corner/state_machines/signed_mdu_agreement_is_terminal_and_rejects_further_owner_response
    """
    base = setup_mdu_address_with_agreement(agreement_status="SIGNED")
    agreement = base["agreement"]
    owner_headers = make_mdu_owner_headers(base["owner"]["id"])

    response = api_client.mdu_owner_response(
        agreement["id"], owner_response_payload("DECLINE"), owner_headers
    )

    validate_error(response, ApiErrorId.ERR_MDU_AGREEMENT_STATE_INVALID, 409)
    reread = validate_success(api_client.get_mdu_agreement(agreement["id"], PM))
    assert_mdu_agreement(reread)
    assert reread["status"] == "SIGNED", reread["status"]
    assert_instant_equals(reread["signed_at"], CLOCK_EPOCH, "signed_at")


def test_a_sent_agreement_materialises_as_expired_on_the_read_after_the_clock_moves():
    """Nothing runs in the background, so the expiry only becomes visible when somebody looks.

    PRD 3.2: "Expiry produces exactly the same consequences with exactly the same conditions, and
    it applies to a `SENT` agreement and to a `COUNTERED` one alike: when the logical clock has
    reached or passed `expires_at`, the next read or write that touches the row materializes it as
    `EXPIRED` - terminal, with `signed_at` still null - and runs the same address and zone
    cascade."

    Design: Corner/state_machines/sent_mdu_agreement_expires_lazily_on_the_next_read
    """
    base = setup_mdu_address_with_agreement(
        agreement_status="SENT", expires_at=AGREEMENT_EXPIRY
    )
    agreement = base["agreement"]
    assert agreement["status"] == "SENT", agreement["status"]
    set_clock(AGREEMENT_EXPIRY)

    expired = validate_success(api_client.get_mdu_agreement(agreement["id"], PM))

    assert_mdu_agreement(expired)
    assert expired["status"] == "EXPIRED", expired["status"]
    assert_instant_is_null(expired["signed_at"], "signed_at")
    late_signature = api_client.mdu_owner_response(
        agreement["id"],
        owner_response_payload("SIGN"),
        make_mdu_owner_headers(base["owner"]["id"]),
    )
    validate_error(late_signature, ApiErrorId.ERR_MDU_AGREEMENT_STATE_INVALID, 409)
    assert_instant_is_null(
        validate_success(api_client.get_mdu_agreement(agreement["id"], PM))["signed_at"],
        "signed_at",
    )


def test_approving_the_last_required_permit_steps_the_zone_on_to_pole_pending():
    """One required type, one approval: the permit gate closes and the pole gate becomes the blocker.

    PRD 3.5: "Approval moves `SUBMITTED -> APPROVED`, stamps `approved_at` with the logical clock,
    sets `expires_at` to `approved_at` advanced by `valid_days` whole days, clears
    `rejection_reason` back to null, records the acting operator's identifier in
    `reviewer_user_id`, and recomputes the zone's `readiness_posture` - which steps from
    `PERMIT_PENDING` to `POLE_PENDING` at the moment the last of the zone's required permit types
    has an approval."

    PRD 2.6 pins the posture cascade itself: "It reads `BLOCKED` when `construction_status` is
    `NOT_STARTED` and none of the zone's required permit types has an `APPROVED` application;
    ... `POLE_PENDING` when every required permit type has an `APPROVED` application but no
    pole-attachment request of the zone has reached `ATTACHED`". A still-NOT_STARTED zone whose
    only required type has no approval yet therefore reads `BLOCKED` before the decision.

    Design: Corner/state_machines/permit_approval_recomputes_zone_readiness_posture_to_pole_pending
    """
    base = setup_campaign_with_zone(zone_overrides={"required_permit_types": ["ROW"]})
    zone_id = base["zone"]["id"]
    application = make_permit(zone_id, target_status="SUBMITTED", valid_days=120)
    zone_before = read_zone(zone_id)
    assert zone_before["readiness_posture"] == "BLOCKED", zone_before

    response = api_client.decide_permit_application(
        application["id"], permit_decision_payload("APPROVE"), PERMIT_OFFICE
    )

    approved = validate_success(response, 200)
    assert_permit_application(approved)
    assert approved["status"] == "APPROVED", approved["status"]
    assert_instant_equals(approved["approved_at"], CLOCK_EPOCH, "approved_at")
    assert_instant_equals(
        approved["expires_at"], PERMIT_EXPIRY_AFTER_120_DAYS, "expires_at"
    )
    assert approved["rejection_reason"] is None, approved["rejection_reason"]
    assert approved["reviewer_user_id"] == PERMIT_OFFICE_USER_ID, approved
    zone_after = read_zone(zone_id)
    assert_build_zone(zone_after)
    assert zone_after["readiness_posture"] == "POLE_PENDING", zone_after


def test_completing_the_restoration_followup_releases_the_service_ready_declaration():
    """The first sign-off attempt is refused while a lawn is open; discharging the visit clears it.

    PRD 3.8: "Where the appointment being completed is itself a `RESTORATION_FOLLOWUP`, the parent
    appointment's `restoration_satisfied_at` is stamped with the logical clock, which lowers the
    zone's `outstanding_restoration_count` by 1 and is precisely what unblocks the service-ready
    declaration of §3.6."

    Design: Corner/state_machines/restoration_followup_completion_unblocks_construction_complete
    """
    base = setup_completed_bury_appointment()
    zone_id = base["zone"]["id"]
    parent = base["appointment"]
    assert_instant_equals(
        parent["restoration_due_by"], RESTORATION_DUE_BY, "restoration_due_by"
    )
    assert base["zone"]["outstanding_restoration_count"] == 1, base["zone"]

    blocked = api_client.complete_construction(zone_id, PM)
    validate_error(blocked, ApiErrorId.ERR_RESTORATION_OUTSTANDING, 409)

    restoration_crew = make_crew(name="Restore Crew 1", crew_type="RESTORATION")
    followup = make_appointment(
        base["converted"]["id"],
        restoration_crew["id"],
        "2026-10-06T09:00:00Z",
        FOLLOWUP_COMPLETION,
        appointment_type="RESTORATION_FOLLOWUP",
        parent_appointment_id=parent["id"],
    )
    set_clock(FOLLOWUP_COMPLETION)
    completed_followup = record_outcome(followup["id"], "COMPLETED")

    assert_install_appointment(completed_followup)
    assert completed_followup["status"] == "COMPLETED", completed_followup["status"]
    assert_instant_equals(
        read_appointment(parent["id"])["restoration_satisfied_at"],
        FOLLOWUP_COMPLETION,
        "restoration_satisfied_at",
    )
    assert read_zone(zone_id)["outstanding_restoration_count"] == 0
    finished = validate_success(api_client.complete_construction(zone_id, PM), 200)
    assert_build_zone(finished)
    assert finished["construction_status"] == "SERVICE_READY", finished
    assert_crew_load(read_crew(restoration_crew["id"]), 0, 0)
