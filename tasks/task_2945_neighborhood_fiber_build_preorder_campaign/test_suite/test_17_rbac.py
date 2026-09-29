"""Role-based access control: exclusive acts, shared acts, and account-backed ownership."""

from test_helpers import (
    CLOCK_EPOCH,
    COORDINATOR,
    PERMIT_OFFICE,
    PM,
    UNKNOWN_ACCOUNT_ID,
    UTILITY,
    ApiErrorId,
    account_payload,
    api_client,
    assert_build_zone,
    assert_cents,
    assert_instant_equals,
    assert_mdu_agreement,
    assert_pct,
    assert_permit_application,
    assert_pole_attachment_request,
    assert_preorder,
    assert_service_address,
    assert_total_count,
    install_crew_payload,
    list_ledger_for_account,
    make_mdu_owner_headers,
    make_owner_account,
    make_permit,
    make_pole_request,
    make_subscriber_headers,
    owner_response_payload,
    permit_decision_payload,
    pole_decision_payload,
    pole_survey_payload,
    read_account,
    read_address,
    read_zone,
    setup_campaign_with_zone,
    setup_mdu_address_with_agreement,
    setup_zone_with_preorders,
    validate_error,
    validate_success,
)


def test_five_exclusive_acts_each_refuse_the_wrong_role_and_leave_nothing_behind():
    """The program manager is not the permit office, not the utility and not the coordinator.

    PRD 2.1: "When the headers are well formed but the named role is not among the roles authorized
    for the endpoint being called, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD 2.1: "A `PermitOffice` principal is the municipal permitting authority and is the only actor
    that can approve or reject a submitted permit application."

    Design: Corner/rbac/exclusive_operations_are_forbidden_to_other_roles
    """
    base = setup_campaign_with_zone(
        zone_overrides={"household_count": 10, "required_permit_types": ["ROW"]}
    )
    zone_id = base["zone"]["id"]
    application = make_permit(zone_id, target_status="SUBMITTED", valid_days=120)
    request = make_pole_request(
        zone_id,
        target_status="REQUESTED",
        utility_owner="Aurora Power",
        pole_count=12,
    )

    refusals = [
        api_client.decide_permit_application(
            application["id"], permit_decision_payload("APPROVE"), PM
        ),
        api_client.survey_pole_attachment_request(
            request["id"], pole_survey_payload(45600), PM
        ),
        api_client.create_install_crew(install_crew_payload(), PM),
        api_client.qualification_run(base["campaign"]["id"], COORDINATOR),
        api_client.create_account(
            account_payload(), make_subscriber_headers(UNKNOWN_ACCOUNT_ID)
        ),
    ]

    for response in refusals:
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    settled_permit = validate_success(
        api_client.get_permit_application(application["id"], PERMIT_OFFICE), 200
    )
    assert_permit_application(settled_permit)
    assert settled_permit["status"] == "SUBMITTED", settled_permit["status"]
    assert settled_permit["reviewer_user_id"] is None, settled_permit
    settled_pole = validate_success(
        api_client.get_pole_attachment_request(request["id"], UTILITY), 200
    )
    assert_pole_attachment_request(settled_pole)
    assert settled_pole["status"] == "REQUESTED", settled_pole["status"]
    assert_cents(settled_pole["make_ready_cost_cents"], 0, "make_ready_cost_cents")
    assert_total_count(api_client.list_install_crews(COORDINATOR), 0)
    assert_total_count(api_client.list_accounts(PM), 0)
    settled_zone = read_zone(zone_id)
    assert_build_zone(settled_zone)
    assert settled_zone["campaign_status"] == "PREREG_OPEN", settled_zone


def test_the_quote_decision_answers_to_the_program_manager_and_to_the_utility_alike():
    """Two surveyed requests, two different roles deciding, and both decisions are honoured.

    PRD 3.5: "The **accept** branch is the `ProgramManager`'s, expressed as a `decision` of
    `ACCEPT`: it moves `SURVEYED -> ACCEPTED`, recomputes the zone's `make_ready_cost_cents` to
    include this request's quote, and increments the zone's `version` by 1."

    PRD 3.5: "The **deny** branch is the `UtilityOperator`'s, expressed as a `decision` of `DENY`
    accompanied by a `denial_reason` of `INSUFFICIENT_CLEARANCE`, `SAFETY_VIOLATION` or
    `CAPACITY_FULL`: it moves `SURVEYED -> DENIED`, and the zone's `make_ready_cost_cents` now
    *excludes* this request."

    Design: Corner/rbac/pole_decision_is_shared_between_program_manager_and_utility_operator
    """
    base = setup_campaign_with_zone(zone_overrides={"household_count": 10})
    zone_id = base["zone"]["id"]
    cheaper = make_pole_request(
        zone_id,
        target_status="SURVEYED",
        make_ready_cost_cents=45600,
        utility_owner="Aurora Power",
        pole_count=12,
    )
    dearer = make_pole_request(
        zone_id,
        target_status="SURVEYED",
        make_ready_cost_cents=90000,
        utility_owner="Aurora Telecom",
        pole_count=20,
    )

    accepted = validate_success(
        api_client.decide_pole_attachment_request(
            cheaper["id"], pole_decision_payload("ACCEPT"), PM
        ),
        200,
    )
    denied = validate_success(
        api_client.decide_pole_attachment_request(
            dearer["id"],
            pole_decision_payload("DENY", denial_reason="CAPACITY_FULL"),
            UTILITY,
        ),
        200,
    )

    assert_pole_attachment_request(accepted)
    assert accepted["status"] == "ACCEPTED", accepted["status"]
    assert_pole_attachment_request(denied)
    assert denied["status"] == "DENIED", denied["status"]
    settled = read_zone(zone_id)
    assert_build_zone(settled)
    assert_cents(settled["make_ready_cost_cents"], 45600, "make_ready_cost_cents")
    assert settled["construction_status"] == "NOT_STARTED", settled
    assert settled["suspension_reason"] is None, settled["suspension_reason"]


def test_only_the_named_building_owner_can_sign_the_access_agreement():
    """A second landlord holds a valid MduOwner role and still cannot answer somebody else's offer.

    PRD 2.1: "When `X-User-Role` is `MduOwner`, `X-User-ID` is likewise the `id` of the acting
    `Account`, and it is compared to the agreement's `owner_account_id`. A mismatch in any of these
    comparisons is `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    PRD 3.2: "Signing then cascades three hops beyond the agreement: the referenced address moves
    `CONDITIONAL_MDU -> SERVICEABLE` with `serviceability_determined_at` stamped and
    `counts_toward_threshold` recomputed to true; every `PENDING` preorder standing at that address
    has its own `counts_toward_threshold` recomputed to true as a consequence; and as a consequence
    of that, the zone's `provisional_qualifying_count` and `prereg_rate_pct` are recomputed and the
    zone's `version` is incremented by 1."

    Design: Corner/rbac/mdu_owner_cannot_answer_another_owners_agreement
    """
    base = setup_mdu_address_with_agreement(agreement_status="SENT")
    agreement = base["agreement"]
    landlord = base["owner"]
    stranger = make_owner_account(
        full_name="Cedar Court LLC",
        email="owner@cedar.example.com",
        phone="+13035550198",
    )

    trespass = api_client.mdu_owner_response(
        agreement["id"],
        owner_response_payload("SIGN"),
        make_mdu_owner_headers(stranger["id"]),
    )

    validate_error(trespass, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)
    still_sent = validate_success(api_client.get_mdu_agreement(agreement["id"], PM), 200)
    assert_mdu_agreement(still_sent)
    assert still_sent["status"] == "SENT", still_sent["status"]
    assert still_sent["signed_at"] is None, still_sent["signed_at"]

    signed = validate_success(
        api_client.mdu_owner_response(
            agreement["id"],
            owner_response_payload("SIGN"),
            make_mdu_owner_headers(landlord["id"]),
        ),
        200,
    )
    assert_mdu_agreement(signed)
    assert signed["status"] == "SIGNED", signed["status"]
    assert_instant_equals(signed["signed_at"], CLOCK_EPOCH, "signed_at")
    settled_address = read_address(base["address"]["id"])
    assert_service_address(settled_address)
    assert settled_address["serviceability"] == "UNDETERMINED", settled_address


def test_a_cancellation_is_open_to_the_resident_and_to_the_operator_alike():
    """One resident walks away and the operator withdraws the other, and both deposits come back.

    PRD 3.3: "Cancellation is available to the owning `Subscriber` and to any `ProgramManager`, and
    its fiscal consequence depends entirely on which lifecycle state the preorder is in."

    PRD 3.3: "From `PENDING` the transition is `PENDING -> CANCELLED`: `cancelled_at` is stamped
    with the logical clock and the money dimension moves `HELD -> REFUNDED`, appending one
    `DEPOSIT_REFUNDED` entry whose `amount_cents` is the negative of `deposit_amount_cents` and
    recomputing the account's `deposit_held_cents`."

    Design: Corner/rbac/cancel_is_reachable_by_both_the_owner_and_the_program_manager
    """
    base = setup_zone_with_preorders(preorder_count=2, household_count=10)
    zone_id = base["zone"]["id"]
    first_account, second_account = base["accounts"]
    first_preorder, second_preorder = base["preorders"]

    by_owner = validate_success(
        api_client.cancel_preorder(
            first_preorder["id"], make_subscriber_headers(first_account["id"])
        ),
        200,
    )
    by_operator = validate_success(
        api_client.cancel_preorder(second_preorder["id"], PM), 200
    )

    assert_preorder(by_owner)
    assert by_owner["preorder_status"] == "CANCELLED", by_owner["preorder_status"]
    assert by_owner["deposit_status"] == "REFUNDED", by_owner["deposit_status"]
    assert_preorder(by_operator)
    assert by_operator["preorder_status"] == "CANCELLED", by_operator
    assert by_operator["deposit_status"] == "REFUNDED", by_operator
    for account in (first_account, second_account):
        assert_cents(
            read_account(account["id"])["deposit_held_cents"], 0, "deposit_held_cents"
        )
    entries, listing = list_ledger_for_account(second_account["id"])
    assert_total_count(listing, 2)
    assert [entry["entry_type"] for entry in entries] == [
        "DEPOSIT_HELD",
        "DEPOSIT_REFUNDED",
    ], entries
    assert_cents(entries[1]["amount_cents"], -1000, "DEPOSIT_REFUNDED.amount_cents")
    settled_zone = read_zone(zone_id)
    assert_build_zone(settled_zone)
    assert settled_zone["provisional_qualifying_count"] == 0, settled_zone
    assert_pct(settled_zone["prereg_rate_pct"], 0.00, "prereg_rate_pct")
