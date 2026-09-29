"""Error families: the not-found catalogue, the auth pair, and the capped workflow ladders."""

from test_helpers import (
    APPROVER,
    ASSESSOR,
    ApiErrorId,
    CLAIMS_ASSESSOR_USER_ID,
    COORDINATOR,
    PERMIT_OFFICE,
    PM,
    UNKNOWN_ACCOUNT_ID,
    UNKNOWN_DAMAGE_CLAIM_ID,
    UNKNOWN_FALLBACK_OFFER_ID,
    UNKNOWN_FALLBACK_OPTION_ID,
    UNKNOWN_INSTALL_APPOINTMENT_ID,
    UNKNOWN_INSTALL_CREW_ID,
    UNKNOWN_LEDGER_ENTRY_ID,
    UNKNOWN_MDU_AGREEMENT_ID,
    UNKNOWN_PERMIT_APPLICATION_ID,
    UNKNOWN_POLE_REQUEST_ID,
    UNKNOWN_ROLE_HEADERS,
    UNKNOWN_SERVICE_ADDRESS_ID,
    UTILITY,
    api_client,
    appointment_outcome_payload,
    assert_build_zone,
    assert_cents,
    assert_crew_load,
    assert_damage_claim,
    assert_error_body,
    assert_fallback_offer,
    assert_install_appointment,
    assert_instant_equals,
    assert_instant_is_null,
    assert_permit_application,
    assert_pole_attachment_request,
    assert_preorder,
    assert_service_address,
    assert_total_count,
    blank_role_headers,
    campaign_payload,
    claim_decision_payload,
    damage_claim_payload,
    fallback_offer_response_payload,
    grant_unserved_exception,
    install_appointment_payload,
    make_account,
    make_address,
    make_appointment,
    make_campaign,
    make_crew,
    make_headers,
    make_offer,
    make_permit,
    make_pole_request,
    make_subscriber_headers,
    missing_role_headers,
    permit_decision_payload,
    read_account,
    read_address,
    read_appointment,
    read_claim,
    read_crew,
    read_crew_version,
    read_preorder,
    read_zone,
    record_outcome,
    set_clock,
    set_serviceability,
    setup_converted_preorder,
    setup_not_serviceable_address_with_options,
    setup_zone_with_preorders,
    validate_error,
    validate_success,
)

CLOCK_AFTER_DEADLINE = "2026-10-01T00:00:00Z"
OFFER_EXPIRY = "2026-09-01T00:00:00Z"
SHORT_OFFER_EXPIRY = "2026-08-15T00:00:00Z"
BURY_COMPLETION = "2026-10-05T11:00:00Z"
SECOND_COMPLETION = "2026-10-05T13:00:00Z"
RESTORATION_DUE_BY = "2026-10-12T11:00:00Z"
SECOND_RESTORATION_DUE_BY = "2026-10-12T13:00:00Z"


def test_each_unknown_path_identifier_names_its_own_entity_in_the_refusal():
    """Eleven reads against an empty database, eleven different not-found codes, all 404.

    PRD 2.10: "The rejection is the not-found code of the entity that failed to resolve -
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_BUILD_ZONE_NOT_FOUND`, `ERR_SERVICE_ADDRESS_NOT_FOUND`,
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_MDU_AGREEMENT_NOT_FOUND`, `ERR_PERMIT_APPLICATION_NOT_FOUND`,
    `ERR_POLE_REQUEST_NOT_FOUND`, `ERR_PREORDER_NOT_FOUND`, `ERR_INSTALL_CREW_NOT_FOUND`,
    `ERR_INSTALL_APPOINTMENT_NOT_FOUND`, `ERR_DAMAGE_CLAIM_NOT_FOUND`,
    `ERR_FALLBACK_OPTION_NOT_FOUND`, `ERR_FALLBACK_OFFER_NOT_FOUND` or
    `ERR_LEDGER_ENTRY_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/unknown_ids_return_the_entity_specific_not_found_code
    """
    set_clock()

    probes = [
        (
            api_client.get_service_address(UNKNOWN_SERVICE_ADDRESS_ID, PM),
            ApiErrorId.ERR_SERVICE_ADDRESS_NOT_FOUND,
        ),
        (
            api_client.get_account(UNKNOWN_ACCOUNT_ID, PM),
            ApiErrorId.ERR_ACCOUNT_NOT_FOUND,
        ),
        (
            api_client.get_mdu_agreement(UNKNOWN_MDU_AGREEMENT_ID, PM),
            ApiErrorId.ERR_MDU_AGREEMENT_NOT_FOUND,
        ),
        (
            api_client.get_permit_application(
                UNKNOWN_PERMIT_APPLICATION_ID, PERMIT_OFFICE
            ),
            ApiErrorId.ERR_PERMIT_APPLICATION_NOT_FOUND,
        ),
        (
            api_client.get_pole_attachment_request(UNKNOWN_POLE_REQUEST_ID, UTILITY),
            ApiErrorId.ERR_POLE_REQUEST_NOT_FOUND,
        ),
        (
            api_client.get_install_crew(UNKNOWN_INSTALL_CREW_ID, COORDINATOR),
            ApiErrorId.ERR_INSTALL_CREW_NOT_FOUND,
        ),
        (
            api_client.get_install_appointment(
                UNKNOWN_INSTALL_APPOINTMENT_ID, COORDINATOR
            ),
            ApiErrorId.ERR_INSTALL_APPOINTMENT_NOT_FOUND,
        ),
        (
            api_client.get_damage_claim(UNKNOWN_DAMAGE_CLAIM_ID, ASSESSOR),
            ApiErrorId.ERR_DAMAGE_CLAIM_NOT_FOUND,
        ),
        (
            api_client.get_fallback_option(UNKNOWN_FALLBACK_OPTION_ID, PM),
            ApiErrorId.ERR_FALLBACK_OPTION_NOT_FOUND,
        ),
        (
            api_client.get_fallback_offer(UNKNOWN_FALLBACK_OFFER_ID, PM),
            ApiErrorId.ERR_FALLBACK_OFFER_NOT_FOUND,
        ),
        (
            api_client.get_ledger_entry(UNKNOWN_LEDGER_ENTRY_ID, PM),
            ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND,
        ),
    ]

    for response, expected_error in probes:
        validate_error(response, expected_error, 404)
        assert_error_body(response, expected_error)


def test_a_bad_role_header_is_unauthenticated_while_a_real_wrong_role_is_forbidden():
    """Absent, blank and unknown roles all fail at the first rung; a real role fails at the second.

    PRD 2.10: "`X-User-Role` and `X-User-ID` are both present and non-empty, and `X-User-Role`
    names one of the eight roles in §2.1. A missing header, an empty-string header and an unknown
    role name all fail here with `ERR_UNAUTHENTICATED`."

    PRD 2.10: "The acting `X-User-Role` appears in the endpoint's authorized-role list in §4.
    Otherwise `ERR_FORBIDDEN_ROLE`."

    Design: Corner/errors/missing_or_unknown_role_header_is_unauthenticated_and_a_valid_wrong_role_is_forbidden
    """
    set_clock()
    campaign = make_campaign()
    account = make_account(0)

    for headers in (missing_role_headers(), blank_role_headers(), UNKNOWN_ROLE_HEADERS):
        response = api_client.get_campaign(campaign["id"], headers)
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    rogue = api_client.create_campaign(
        campaign_payload(name="Rogue Campaign"), make_subscriber_headers(account["id"])
    )
    validate_error(rogue, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    ghost_read = api_client.get_account(UNKNOWN_ACCOUNT_ID, blank_role_headers())
    validate_error(ghost_read, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert_total_count(api_client.list_campaigns(PM, params={"city": "Aurora"}), 1)


def test_the_resubmission_allowance_is_spent_by_the_second_submission():
    """One resubmission permitted, two submissions used, and the third attempt has nothing left.

    PRD 3.5: "A rejected application can be sent back for review: resubmission moves `REJECTED ->
    SUBMITTED`, is admissible only while `submission_round` reduced by 1 is strictly less than
    `max_resubmissions`, increases `submission_round` by 1 and clears `rejection_reason` to null."

    Design: Corner/errors/permit_resubmission_stops_at_the_declared_limit
    """
    base = setup_zone_with_preorders(
        preorder_count=0,
        household_count=10,
        zone_overrides={"required_permit_types": ["ROW"]},
    )
    zone_id = base["zone"]["id"]
    application = make_permit(
        zone_id, target_status="DRAFT", valid_days=120, max_resubmissions=1
    )

    first = validate_success(
        api_client.submit_permit_application(application["id"], PM), 200
    )
    assert first["submission_round"] == 1, first["submission_round"]
    validate_success(
        api_client.decide_permit_application(
            application["id"],
            permit_decision_payload("REJECT", rejection_reason="Traffic plan incomplete."),
            PERMIT_OFFICE,
        ),
        200,
    )

    second = validate_success(
        api_client.submit_permit_application(application["id"], PM), 200
    )
    assert_permit_application(second)
    assert second["submission_round"] == 2, second["submission_round"]
    assert second["rejection_reason"] is None, second["rejection_reason"]
    validate_success(
        api_client.decide_permit_application(
            application["id"],
            permit_decision_payload(
                "REJECT", rejection_reason="Still missing the detour drawing."
            ),
            PERMIT_OFFICE,
        ),
        200,
    )

    refused = api_client.submit_permit_application(application["id"], PM)

    validate_error(refused, ApiErrorId.ERR_RESUBMISSION_LIMIT_REACHED, 409)
    settled = validate_success(
        api_client.get_permit_application(application["id"], PM), 200
    )
    assert_permit_application(settled)
    assert settled["status"] == "REJECTED", settled["status"]
    assert settled["submission_round"] == 2, settled["submission_round"]
    assert settled["rejection_reason"] == "Still missing the detour drawing.", settled
    zone = read_zone(zone_id)
    assert_build_zone(zone)
    # PRD 2.6: "It reads `BLOCKED` when `construction_status` is `NOT_STARTED` and none of the
    # zone's required permit types has an `APPROVED` application" - this zone never got an
    # approval, so it is still BLOCKED rather than merely PERMIT_PENDING.
    assert zone["readiness_posture"] == "BLOCKED", zone["readiness_posture"]


def test_an_answered_offer_and_a_lapsed_offer_both_refuse_a_late_acceptance():
    """One offer was declined outright, the other simply ran out of time, and neither can be taken.

    PRD 3.2: "An `OFFERED` offer the clock has carried to `expires_at` is materialized as `EXPIRED`
    by the next read or write touching it, with `responded_at` left null and no option excluded.
    All three of `ACCEPTED`, `DECLINED` and `EXPIRED` are terminal, and answering an offer that is
    no longer `OFFERED` - already answered, or lazily expired - is
    `ERR_FALLBACK_OFFER_STATE_INVALID`."

    Design: Corner/errors/answered_or_expired_fallback_offer_rejects_a_response
    """
    base = setup_not_serviceable_address_with_options(
        option_specs=(
            {
                "technology": "FIXED_WIRELESS",
                "min_downstream_mbps": 300,
                "monthly_price_cents": 7000,
                "max_serviceable_distance_m": 1500,
                "priority_rank": 1,
            },
        ),
        address_overrides={"street_address": "12 Quarry Rd", "distance_to_node_m": 900},
        not_serviceable_reason="EXCESSIVE_DISTANCE",
    )
    option = base["options"][0]
    account = base["account"]
    subscriber = make_subscriber_headers(account["id"])
    first_address = base["address"]
    second_address = make_address(
        base["zone"]["id"], street_address="14 Quarry Rd", distance_to_node_m=950
    )
    set_serviceability(
        second_address["id"],
        "NOT_SERVICEABLE",
        not_serviceable_reason="EXCESSIVE_DISTANCE",
    )
    grant_unserved_exception(second_address["id"], exception_reason="Beyond reach.")
    declined = make_offer(
        first_address["id"], account["id"], expires_at=OFFER_EXPIRY
    )
    validate_success(
        api_client.respond_to_fallback_offer(
            declined["id"], fallback_offer_response_payload("DECLINE"), subscriber
        ),
        200,
    )
    lapsing = make_offer(
        second_address["id"], account["id"], expires_at=SHORT_OFFER_EXPIRY
    )
    assert lapsing["fallback_option_id"] == option["id"], lapsing

    answered_again = api_client.respond_to_fallback_offer(
        declined["id"], fallback_offer_response_payload("ACCEPT"), subscriber
    )
    set_clock(SHORT_OFFER_EXPIRY)
    too_late = api_client.respond_to_fallback_offer(
        lapsing["id"], fallback_offer_response_payload("ACCEPT"), subscriber
    )

    validate_error(answered_again, ApiErrorId.ERR_FALLBACK_OFFER_STATE_INVALID, 409)
    validate_error(too_late, ApiErrorId.ERR_FALLBACK_OFFER_STATE_INVALID, 409)
    settled_first = validate_success(
        api_client.get_fallback_offer(declined["id"], PM), 200
    )
    assert_fallback_offer(settled_first)
    assert settled_first["status"] == "DECLINED", settled_first["status"]
    settled_second = validate_success(
        api_client.get_fallback_offer(lapsing["id"], PM), 200
    )
    assert_fallback_offer(settled_second)
    assert settled_second["status"] == "EXPIRED", settled_second["status"]
    assert_instant_is_null(settled_second["responded_at"], "responded_at")
    for address_id in (first_address["id"], second_address["id"]):
        settled_address = read_address(address_id)
        assert_service_address(settled_address)
        assert settled_address["active_fallback_technology"] is None, settled_address


def test_a_quote_merely_accepted_does_not_break_ground_but_the_attachment_does():
    """The cables are not on the poles yet, and the refusal names the pole gate rather than permits.

    PRD 3.6: "Two readiness gates then apply, in this order: first every permit type in
    `required_permit_types` must have an application in status `APPROVED` whose `expires_at` is
    strictly after the logical clock, failing which the attempt is `ERR_PERMIT_READINESS_UNMET`;
    then the zone must have at least one pole-attachment request in status `ATTACHED`, failing which
    it is `ERR_POLE_READINESS_UNMET`."

    PRD 3.6: "Each recipient first receives the integer quotient of the total divided by the count,
    discarding any fraction."

    Design: Corner/errors/construction_start_without_an_attached_pole_is_refused
    """
    base = setup_zone_with_preorders(
        preorder_count=1,
        household_count=10,
        threshold_pct=10.0,
        zone_overrides={"required_permit_types": ["ROW"]},
    )
    zone_id = base["zone"]["id"]
    make_permit(zone_id, valid_days=200)
    pole = make_pole_request(
        zone_id,
        target_status="ACCEPTED",
        make_ready_cost_cents=45600,
        utility_owner="Aurora Power",
        pole_count=12,
    )
    set_clock(CLOCK_AFTER_DEADLINE)
    validate_success(api_client.qualification_run(base["campaign"]["id"], PM), 200)
    validate_success(api_client.sequencing_run(base["campaign"]["id"], PM), 200)
    before = read_zone(zone_id)
    assert before["readiness_posture"] == "POLE_PENDING", before["readiness_posture"]
    assert before["construction_status"] == "SEQUENCED", before["construction_status"]

    refused = api_client.start_construction(zone_id, PM)

    validate_error(refused, ApiErrorId.ERR_POLE_READINESS_UNMET, 409)
    attached = validate_success(
        api_client.attach_pole_attachment_request(pole["id"], UTILITY), 200
    )
    assert_pole_attachment_request(attached)
    assert attached["status"] == "ATTACHED", attached["status"]
    assert_instant_equals(attached["attached_at"], CLOCK_AFTER_DEADLINE, "attached_at")

    started = validate_success(api_client.start_construction(zone_id, PM), 200)
    assert_build_zone(started)
    assert started["construction_status"] == "IN_CONSTRUCTION", started
    assert started["readiness_posture"] == "READY", started["readiness_posture"]
    recipient = read_preorder(base["preorders"][0]["id"])
    assert_preorder(recipient)
    assert recipient["preorder_status"] == "QUALIFIED", recipient["preorder_status"]
    assert_cents(recipient["make_ready_share_cents"], 45600, "make_ready_share_cents")


def test_the_wrong_trade_the_second_outcome_and_the_late_restoration_are_each_refused():
    """One booking walk exercises certification, the terminal outcome and the restoration deadline.

    PRD 3.8: "The crew's certification must match the work: `DROP_BURY` requires a crew whose
    `crew_type` is `BURY`, `AERIAL_DROP` requires `AERIAL`, and `RESTORATION_FOLLOWUP` requires
    `RESTORATION`, with any mismatch refused as `ERR_CREW_TYPE_MISMATCH`."

    PRD 3.8: "From those instants the appointment's `occupied_minutes` is derived as the whole
    minutes between start and end **plus** the crew's `travel_buffer_minutes`, and that single
    figure is the unit of both the conflict geometry and the daily capacity accounting."

    PRD 3.8: "Where that flag is true, `restoration_due_by` is set to `completed_at` advanced by the
    campaign's `restoration_sla_days` whole days and the zone's `outstanding_restoration_count`
    rises by 1."

    PRD 3.8: "All three outcomes are admissible only from `SCHEDULED` - an appointment that already
    has an outcome yields `ERR_INSTALL_APPOINTMENT_STATE_INVALID` - and all three are terminal."

    PRD 3.9: "Booking the follow-up is subject to two extra rules beyond §3.8's geometry: its
    `window_start_at` must fall at or before the parent appointment's `restoration_due_by`, and the
    parent must genuinely still owe restoration - `restoration_required` true and
    `restoration_satisfied_at` null - with any violation refused as
    `ERR_RESTORATION_WINDOW_MISSED`."

    Design: Corner/errors/install_scheduling_and_outcome_error_family
    """
    base = setup_converted_preorder(
        drop_method="BURY", campaign_overrides={"restoration_sla_days": 7}
    )
    preorder_id = base["converted"]["id"]
    bury = make_crew(name="Bury Crew 1", crew_type="BURY")
    aerial = make_crew(name="Aerial Crew 1", crew_type="AERIAL")
    restoration = make_crew(name="Restore Crew 1", crew_type="RESTORATION")

    wrong_trade = api_client.create_install_appointment(
        install_appointment_payload(
            preorder_id,
            aerial["id"],
            "2026-10-05T09:00:00Z",
            "2026-10-05T11:00:00Z",
            read_crew_version(aerial["id"]),
            appointment_type="DROP_BURY",
        ),
        COORDINATOR,
    )

    validate_error(wrong_trade, ApiErrorId.ERR_CREW_TYPE_MISMATCH, 422)
    assert_crew_load(read_crew(aerial["id"]), 0, 0)

    appointment = make_appointment(
        preorder_id, bury["id"], "2026-10-05T09:00:00Z", "2026-10-05T11:00:00Z"
    )
    assert_install_appointment(appointment)
    assert appointment["occupied_minutes"] == 150, appointment["occupied_minutes"]
    set_clock(BURY_COMPLETION)
    completed = record_outcome(
        appointment["id"], "COMPLETED", restoration_required=True
    )
    assert completed["status"] == "COMPLETED", completed["status"]
    assert_instant_equals(
        completed["restoration_due_by"], RESTORATION_DUE_BY, "restoration_due_by"
    )

    second_outcome = api_client.record_appointment_outcome(
        appointment["id"], appointment_outcome_payload("NO_SHOW"), COORDINATOR
    )
    late_followup = api_client.create_install_appointment(
        install_appointment_payload(
            preorder_id,
            restoration["id"],
            "2026-10-13T09:00:00Z",
            "2026-10-13T10:00:00Z",
            read_crew_version(restoration["id"]),
            appointment_type="RESTORATION_FOLLOWUP",
            parent_appointment_id=appointment["id"],
        ),
        COORDINATOR,
    )

    validate_error(
        second_outcome, ApiErrorId.ERR_INSTALL_APPOINTMENT_STATE_INVALID, 409
    )
    validate_error(late_followup, ApiErrorId.ERR_RESTORATION_WINDOW_MISSED, 422)
    settled = read_appointment(appointment["id"])
    assert_install_appointment(settled)
    assert settled["status"] == "COMPLETED", settled["status"]
    assert_crew_load(read_crew(restoration["id"]), 0, 0)
    assert read_zone(base["zone"]["id"])["outstanding_restoration_count"] == 1


def test_the_claim_chain_refuses_the_undamaged_visit_the_early_decision_and_the_second_appeal():
    """A lawn claim walks filing, assessment, one denial and one appeal to the end of its allowance.

    PRD 3.9: "Filing is admissible only against an appointment that is `COMPLETED` - otherwise
    `ERR_INSTALL_APPOINTMENT_STATE_INVALID` - and only where that appointment had
    `restoration_required` true so that a `restoration_due_by` exists at all, and only within the
    campaign's `claim_filing_window_days` whole days of the appointment's `completed_at`; filing
    later than that, or against a visit that never disturbed the property, is
    `ERR_CLAIM_FILING_WINDOW_EXPIRED`."

    PRD 3.9: "To make the pinning concrete, a 150,000-cent lawn claim is capped to 120,000 and
    assesses at 120,000 when filed on time, and at 72,000 when filed late under the default factor."

    PRD 3.9: "Deciding is the `ClaimsApprover`'s exclusive act, is admissible only from
    `UNDER_ASSESSMENT`, and is subject to the segregation-of-duties rule of §2.1 - the acting
    `X-User-ID` must differ from `assessed_by_user_id`, or the request is
    `ERR_SEGREGATION_OF_DUTIES`."

    PRD 3.9: "The claimant may appeal, which moves the claim `DENIED -> UNDER_ASSESSMENT`, increases
    `appeal_count` by 1 and clears `denial_reason` back to null; `assessed_amount_cents` and
    `assessment_variant` are retained from the previous round until the next assessment overwrites
    them."

    PRD 3.9: "An appeal is admissible only while `appeal_count` is strictly less than `max_appeals`,
    and beyond that it is `ERR_APPEAL_LIMIT_REACHED`."

    Design: Corner/errors/damage_claim_chain_enforces_state_duties_and_appeal_limits
    """
    base = setup_converted_preorder(
        drop_method="BURY",
        campaign_overrides={
            "restoration_sla_days": 7,
            "claim_filing_window_days": 45,
            "late_filing_factor": 0.6,
        },
    )
    preorder_id = base["converted"]["id"]
    address_id = base["addresses"][0]["id"]
    account = base["accounts"][0]
    claimant = make_subscriber_headers(account["id"])
    crew = make_crew(name="Bury Crew 1", crew_type="BURY")
    undamaged = make_appointment(
        preorder_id, crew["id"], "2026-10-05T09:00:00Z", "2026-10-05T11:00:00Z"
    )
    trenched = make_appointment(
        preorder_id, crew["id"], "2026-10-05T12:00:00Z", "2026-10-05T13:00:00Z"
    )
    set_clock(BURY_COMPLETION)
    clean_visit = record_outcome(
        undamaged["id"], "COMPLETED", restoration_required=False
    )
    assert_instant_is_null(clean_visit["restoration_due_by"], "restoration_due_by")
    set_clock(SECOND_COMPLETION)
    dirty_visit = record_outcome(trenched["id"], "COMPLETED", restoration_required=True)
    assert_instant_equals(
        dirty_visit["restoration_due_by"],
        SECOND_RESTORATION_DUE_BY,
        "restoration_due_by",
    )

    against_clean_visit = api_client.create_damage_claim(
        damage_claim_payload(
            undamaged["id"],
            address_id,
            account["id"],
            description="Sod torn along the aerial run.",
            max_appeals=1,
        ),
        claimant,
    )

    validate_error(
        against_clean_visit, ApiErrorId.ERR_CLAIM_FILING_WINDOW_EXPIRED, 409
    )

    claim = validate_success(
        api_client.create_damage_claim(
            damage_claim_payload(
                trenched["id"],
                address_id,
                account["id"],
                description="Lawn trenched across the front yard.",
                max_appeals=1,
            ),
            claimant,
        ),
        201,
    )
    assert_damage_claim(claim)
    assert claim["status"] == "FILED", claim["status"]
    assert_instant_equals(claim["filed_at"], SECOND_COMPLETION, "filed_at")

    premature_decision = api_client.decide_damage_claim(
        claim["id"], claim_decision_payload("APPROVE"), APPROVER
    )
    validate_error(premature_decision, ApiErrorId.ERR_DAMAGE_CLAIM_STATE_INVALID, 409)

    assessed = validate_success(
        api_client.assess_damage_claim(claim["id"], ASSESSOR), 200
    )
    assert_damage_claim(assessed)
    assert assessed["status"] == "UNDER_ASSESSMENT", assessed["status"]
    assert_cents(assessed["assessed_amount_cents"], 120000, "assessed_amount_cents")
    assert assessed["assessment_variant"] == "STANDARD_SCHEDULE", assessed
    assert assessed["assessed_by_user_id"] == CLAIMS_ASSESSOR_USER_ID, assessed

    self_review = api_client.decide_damage_claim(
        claim["id"],
        claim_decision_payload("APPROVE"),
        make_headers(CLAIMS_ASSESSOR_USER_ID, "ClaimsApprover"),
    )
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    assert read_claim(claim["id"])["decided_by_user_id"] is None, claim["id"]

    denied = validate_success(
        api_client.decide_damage_claim(
            claim["id"],
            claim_decision_payload(
                "DENY", denial_reason="Sod was already dead before the dig."
            ),
            APPROVER,
        ),
        200,
    )
    assert denied["status"] == "DENIED", denied["status"]

    appealed = validate_success(api_client.appeal_damage_claim(claim["id"], claimant), 200)
    assert_damage_claim(appealed)
    assert appealed["appeal_count"] == 1, appealed["appeal_count"]
    assert appealed["status"] == "UNDER_ASSESSMENT", appealed["status"]
    assert appealed["denial_reason"] is None, appealed["denial_reason"]
    assert_cents(appealed["assessed_amount_cents"], 120000, "assessed_amount_cents")

    validate_success(
        api_client.decide_damage_claim(
            claim["id"],
            claim_decision_payload(
                "DENY", denial_reason="Photographs unchanged on review."
            ),
            APPROVER,
        ),
        200,
    )
    exhausted = api_client.appeal_damage_claim(claim["id"], claimant)

    validate_error(exhausted, ApiErrorId.ERR_APPEAL_LIMIT_REACHED, 409)
    settled = read_claim(claim["id"])
    assert_damage_claim(settled)
    assert settled["status"] == "DENIED", settled["status"]
    assert settled["appeal_count"] == 1, settled["appeal_count"]
    assert_instant_is_null(settled["paid_at"], "paid_at")
    assert_cents(
        read_account(account["id"])["credit_balance_cents"], 0, "credit_balance_cents"
    )
    assert_total_count(
        api_client.list_ledger_entries(PM, {"damage_claim_id": claim["id"]}), 0
    )
