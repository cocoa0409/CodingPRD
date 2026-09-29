"""The error contract read from the outside: the header gate that runs before
everything else, the twelve distinct not-found codes, the version pin on a second
engagement, the surrogate-authority guards, the escalation preconditions and the
billing window that discharge closes.
"""
from test_helpers import (
    acknowledge_conflict_of_interest,
    api_client,
    assert_timestamps_equal,
    BILLING_ADMINISTRATOR,
    convene_conference,
    create_approved_time_entry,
    create_conference_decision_payload,
    create_invoice_payload,
    create_service_authorization_payload,
    coi_event_payload,
    decision_state_payload,
    discharge_client,
    disclose_conflict_of_interest,
    document_conference,
    escalate_conference_decision,
    get_success_data,
    invoice_state_payload,
    make_care_manager_headers,
    make_family_decision_maker_headers,
    make_practice_supervisor_headers,
    make_headers,
    NOT_FOUND_ERROR_IDS,
    open_invoice,
    PRACTICE_ADMIN,
    propose_service_authorization,
    ratify_conference_decision,
    read_authorization,
    read_care_plan,
    read_client,
    read_decision,
    read_invoice,
    read_time_entry,
    record_capacity_determination,
    record_conference_decision,
    register_care_manager,
    register_client,
    register_family_contact,
    register_supervisor,
    register_surrogate_contact,
    schedule_conference,
    set_logical_clock,
    setup_active_care_plan_scenario,
    uniform_domain_scores,
    validate_error,
    validate_paginated,
    void_invoice,
)

_UNKNOWN_IDS = [
    "00000000-0000-4000-8000-00000000000a",
    "00000000-0000-4000-8000-00000000000b",
    "00000000-0000-4000-8000-00000000000c",
    "00000000-0000-4000-8000-00000000000d",
    "00000000-0000-4000-8000-00000000000e",
    "00000000-0000-4000-8000-00000000000f",
    "00000000-0000-4000-8000-000000000010",
    "00000000-0000-4000-8000-000000000011",
    "00000000-0000-4000-8000-000000000012",
    "00000000-0000-4000-8000-000000000013",
    "00000000-0000-4000-8000-000000000014",
    "00000000-0000-4000-8000-000000000015",
]


def _readers_in_path_variable_order():
    """One read per addressable path variable, in the left-to-right order the
    twelve not-found codes are enumerated in."""
    return [
        api_client.get_client,
        api_client.get_care_manager,
        api_client.get_vendor,
        api_client.get_family_contact,
        api_client.get_assessment,
        api_client.get_care_plan,
        api_client.get_service_authorization,
        api_client.get_family_conference,
        api_client.get_conference_decision,
        api_client.get_crisis_episode,
        api_client.get_time_entry,
        api_client.get_invoice,
    ]


def _one_readable_client():
    """A single client, so that a request failing the header gate would otherwise
    have succeeded."""
    set_logical_clock("2026-08-30T09:00:00Z")
    return register_client(full_name="Ines Rivera", residence_setting="PRIVATE_HOME")


def test_01_a_request_without_an_acting_principal_is_unauthenticated():
    """A well-formed read of an existing client with the role header present but no
    `X-User-ID` fails the header gate, and the body is an error envelope carrying no
    client payload.

    PRD: "If either header is absent or empty, or if `X-User-Role` is not one of the five declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_or_unknown_role_header_returns_4XX_unauthenticated
    """
    client = _one_readable_client()

    error = validate_error(
        api_client.get_client(
            client["id"],
            {"X-User-Role": "CareManager", "Content-Type": "application/json"},
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )
    assert "full_name" not in error
    assert "id" not in error
    assert error["message"].strip() != ""


def test_02_a_role_outside_the_declared_five_is_unauthenticated_not_unauthorized():
    """An undeclared role name is refused by the authentication gate rather than the
    authorisation gate, so the answer is 401 and never 403.

    PRD: "If either header is absent or empty, or if `X-User-Role` is not one of the five declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_or_unknown_role_header_returns_4XX_unauthenticated
    """
    client = _one_readable_client()

    response = api_client.get_client(client["id"], make_headers("any-value", "AUDITOR"))
    error = validate_error(response, "ERR_UNAUTHENTICATED", 401)
    assert response.status_code != 403
    assert error["error_id"] != "ERR_UNAUTHORIZED"
    assert "residence_setting" not in error


def test_03_every_entity_path_answers_an_unknown_id_with_its_own_not_found_code():
    """Twelve reads of twelve absent records return twelve distinct 404 codes, so no
    entity borrows another's not-found error and none of them falls back to a
    generic one.

    PRD: "Each resolves to its own not-found error: a `clientId` or a body-carried `client_id` that matches no client yields `ERR_CLIENT_NOT_FOUND`; a `careManagerId` or a referenced `care_manager_id` yields `ERR_CARE_MANAGER_NOT_FOUND`; a `vendorId` or referenced `vendor_id` yields `ERR_VENDOR_NOT_FOUND`; a `contactId` or a referenced `decided_by_contact_id`, `acknowledged_by_contact_id` or element of `invited_contact_ids` yields `ERR_CONTACT_NOT_FOUND`; an `assessmentId` or referenced `source_assessment_id` yields `ERR_ASSESSMENT_NOT_FOUND`; a `carePlanId` or a referenced `care_plan_id` or `supersedes_care_plan_id` yields `ERR_CARE_PLAN_NOT_FOUND`; an `authorizationId` yields `ERR_AUTHORIZATION_NOT_FOUND`; a `conferenceId` or referenced `family_conference_id` yields `ERR_CONFERENCE_NOT_FOUND`; a `decisionId` or referenced `authorizing_decision_id` yields `ERR_DECISION_NOT_FOUND`; an `episodeId` or referenced `crisis_episode_id` yields `ERR_CRISIS_EPISODE_NOT_FOUND`; a `timeEntryId` yields `ERR_TIME_ENTRY_NOT_FOUND`; and an `invoiceId` yields `ERR_INVOICE_NOT_FOUND`."

    Design: Corner/errors/not_found_sweep_returns_4XX_for_every_entity_path
    """
    set_logical_clock("2026-08-30T09:00:00Z")

    observed = []
    for reader, unknown_id, expected_error_id in zip(
        _readers_in_path_variable_order(), _UNKNOWN_IDS, NOT_FOUND_ERROR_IDS
    ):
        error = validate_error(
            reader(unknown_id, PRACTICE_ADMIN), expected_error_id, 404
        )
        assert error["message"].strip() != ""
        observed.append(error["error_id"])

    assert observed == NOT_FOUND_ERROR_IDS
    assert len(set(observed)) == 12


def _an_active_plan_with_room_for_two_caregivers():
    """An ACTIVE plan whose client may staff two concurrent caregivers, and a clean
    vendor waiting to be engaged."""
    return setup_active_care_plan_scenario(
        clock="2026-08-31T09:00:00Z",
        client_overrides={
            "full_name": "Jonas Aaltonen",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
            "authorized_concurrent_caregivers": 2,
        },
        vendor_overrides={
            "name": "Northgate Home Care",
            "vendor_type": "HOME_CARE",
            "has_referral_relationship": False,
        },
        scores=uniform_domain_scores(2),
        goals=["Split-shift coverage"],
    )


def _propose_against(scenario, expected_care_plan_version, coverage_start, coverage_end):
    """A raw creation carrying whatever plan version the caller believes in."""
    return api_client.create_service_authorization(
        create_service_authorization_payload(
            scenario.care_plan_id,
            scenario.vendor_id,
            expected_care_plan_version,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            concurrent_caregivers=1,
            hourly_cost_cents=4_000,
        ),
        scenario.cm_headers,
    )


def test_04_a_replayed_care_plan_version_on_a_second_engagement_is_refused():
    """The first engagement advances the plan's version, so the same expected
    version replayed on a second engagement no longer matches and the create is
    refused with nothing written.

    PRD: "If `expected_care_plan_version` does not equal the named care plan's current `version`, the create is rejected with `ERR_STALE_CARE_PLAN_VERSION` (HTTP 412), because the caller's coverage view is no longer trustworthy: another authorization may already have consumed the capacity, or the plan may have been superseded."

    Design: Corner/errors/stale_care_plan_version_on_second_authorization_returns_4XX
    """
    scenario = _an_active_plan_with_room_for_two_caregivers()
    observed_version = read_care_plan(scenario.care_plan_id)["version"]

    get_success_data(
        _propose_against(
            scenario,
            observed_version,
            "2026-09-28T08:00:00Z",
            "2026-09-28T12:00:00Z",
        ),
        201,
    )

    validate_error(
        _propose_against(
            scenario,
            observed_version,
            "2026-09-29T08:00:00Z",
            "2026-09-29T12:00:00Z",
        ),
        "ERR_STALE_CARE_PLAN_VERSION",
        412,
    )

    rows, meta = validate_paginated(
        api_client.list_service_authorizations(
            PRACTICE_ADMIN, params={"care_plan_id": scenario.care_plan_id}
        )
    )
    assert meta["total_count"] == 1
    assert [row["coverage_start"][:10] for row in rows] == ["2026-09-28"]


def test_05_the_same_payload_succeeds_once_the_plan_version_is_re_read():
    """Creating an engagement advances the parent plan's version by one, and the
    refused payload is accepted unchanged once it carries that refreshed value.

    PRD: "Because a pending disclosure is one of the `ELEVATED` triggers, the client's `risk_posture` is recomputed; the parent care plan's `version` and the client's `version` each increase by 1."

    Design: Corner/errors/stale_care_plan_version_on_second_authorization_returns_4XX
    """
    scenario = _an_active_plan_with_room_for_two_caregivers()
    observed_version = read_care_plan(scenario.care_plan_id)["version"]

    get_success_data(
        _propose_against(
            scenario,
            observed_version,
            "2026-09-28T08:00:00Z",
            "2026-09-28T12:00:00Z",
        ),
        201,
    )
    fresh_version = read_care_plan(scenario.care_plan_id)["version"]
    assert fresh_version == observed_version + 1

    second = get_success_data(
        _propose_against(
            scenario,
            fresh_version,
            "2026-09-29T08:00:00Z",
            "2026-09-29T12:00:00Z",
        ),
        201,
    )
    assert second["auth_status"] == "PROPOSED"
    assert second["coverage_hours"] == 4

    _rows, meta = validate_paginated(
        api_client.list_service_authorizations(
            PRACTICE_ADMIN, params={"care_plan_id": scenario.care_plan_id}
        )
    )
    assert meta["total_count"] == 2


def _a_disclosed_engagement_and_a_convened_conference():
    """A referral vendor's disclosure awaiting acknowledgement, and a convened
    conference attended by both the surrogate and a non-surrogate relative."""
    scenario = setup_active_care_plan_scenario(
        clock="2026-09-01T09:00:00Z",
        client_overrides={
            "full_name": "Lior Feldman",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
        },
        surrogate_role="POA_HEALTHCARE",
        vendor_overrides={
            "name": "Southgate Elder Law",
            "vendor_type": "LEGAL",
            "has_referral_relationship": True,
            "referral_fee_pct": 5,
        },
        scores=uniform_domain_scores(2),
        goals=["Elder-law engagement"],
    )
    sibling = register_family_contact(
        scenario.client_id,
        full_name="Nils Feldman",
        contact_role="INTERESTED_FAMILY",
    )
    assert sibling["is_surrogate_decision_maker"] is False

    authorization = propose_service_authorization(
        scenario.care_plan_id,
        scenario.vendor_id,
        scenario.care_manager_id,
        coverage_start="2026-09-30T09:00:00Z",
        coverage_end="2026-09-30T13:00:00Z",
        concurrent_caregivers=1,
        hourly_cost_cents=6_000,
    )
    assert authorization["coi_status"] == "PENDING_DISCLOSURE"
    disclosed = disclose_conflict_of_interest(
        authorization["id"],
        scenario.care_manager_id,
        note="Referral relationship disclosed",
    )
    assert disclosed["coi_status"] == "DISCLOSED"

    conference = schedule_conference(
        scenario.client_id,
        [scenario.surrogate_id, sibling["id"]],
        scenario.care_manager_id,
        scheduled_start="2026-09-02T14:00:00Z",
        scheduled_end="2026-09-02T15:00:00Z",
        agenda="Engage elder-law counsel",
    )
    conference = convene_conference(
        conference["id"],
        [scenario.surrogate_id, sibling["id"]],
        scenario.care_manager_id,
    )
    assert conference["quorum_met"] is True
    assert read_client(scenario.client_id)["capacity_status"] == "PRESUMED_CAPABLE"
    return scenario, sibling, authorization, conference


def test_06_only_an_eligible_surrogate_may_acknowledge_the_disclosure():
    """An interested relative who is not a surrogate cannot close the disclosure
    even for himself, and the dimension stays open until the surrogate does it.

    PRD: "The contact named in `acknowledged_by_contact_id` must be a family contact of the authorization's client whose `is_surrogate_decision_maker` is true and whose `contact_role` is one of `POA_HEALTHCARE`, `POA_FINANCIAL`, `GUARDIAN` or `RESPONSIBLE_PARTY` — an `INTERESTED_FAMILY` contact, or any non-surrogate, is rejected with `ERR_COI_ACK_BY_INELIGIBLE_PARTY` — and the acting `X-User-ID` must equal `acknowledged_by_contact_id`, so nobody acknowledges on somebody else's behalf."

    Design: Corner/errors/coi_acknowledgement_and_decision_authority_require_a_surrogate
    """
    scenario, sibling, authorization, _conference = (
        _a_disclosed_engagement_and_a_convened_conference()
    )

    validate_error(
        api_client.post_coi_event(
            authorization["id"],
            coi_event_payload("ACKNOWLEDGE", acknowledged_by_contact_id=sibling["id"]),
            make_family_decision_maker_headers(sibling["id"]),
        ),
        "ERR_COI_ACK_BY_INELIGIBLE_PARTY",
        422,
    )
    assert read_authorization(authorization["id"])["coi_status"] == "DISCLOSED"

    acknowledged = acknowledge_conflict_of_interest(
        authorization["id"], scenario.surrogate_id
    )
    assert acknowledged["coi_status"] == "ACKNOWLEDGED"
    assert acknowledged["coi_acknowledged_by_contact_id"] == scenario.surrogate_id


def test_07_only_a_surrogate_may_be_recorded_as_the_decision_maker():
    """The same relative may attend the conference but may not be the person the
    decision is made by, and the decision the practice tried to record does not
    exist until the surrogate stands behind it.

    PRD: "Second, the person named in `decided_by_contact_id` must have `is_surrogate_decision_maker` set to true, and when the client's `capacity_status` is `ADJUDICATED_INCAPACITATED` that person's `contact_role` must additionally be `POA_HEALTHCARE` or `GUARDIAN`; a decision maker holding no adequate surrogate authority is rejected with `ERR_SURROGATE_AUTHORITY_MISSING`."

    Design: Corner/errors/coi_acknowledgement_and_decision_authority_require_a_surrogate
    """
    scenario, sibling, _authorization, conference = (
        _a_disclosed_engagement_and_a_convened_conference()
    )

    validate_error(
        api_client.create_conference_decision(
            create_conference_decision_payload(
                conference["id"],
                sibling["id"],
                decision_type="VENDOR_ENGAGEMENT",
                decision_text="Retain Southgate Elder Law",
            ),
            scenario.cm_headers,
        ),
        "ERR_SURROGATE_AUTHORITY_MISSING",
        422,
    )
    _rows, meta = validate_paginated(
        api_client.list_conference_decisions(
            PRACTICE_ADMIN, params={"family_conference_id": conference["id"]}
        )
    )
    assert meta["total_count"] == 0

    decision = record_conference_decision(
        conference["id"],
        scenario.surrogate_id,
        scenario.care_manager_id,
        decision_type="VENDOR_ENGAGEMENT",
        decision_text="Retain Southgate Elder Law",
    )
    assert decision["status"] == "RECORDED"
    assert decision["decided_by_contact_id"] == scenario.surrogate_id


_CAPACITY_BASIS = "MMSE 18/30 on 2026-08-28 with corroborating family report"
_PLACEMENT_TEXT = "Move to the secured memory-care wing"
_GUARDIANSHIP_ORDER = "Court guardianship order 2026-08-30"


def _a_diminished_capacity_client_at_a_convened_conference():
    """A client whose capacity has been documented as diminished, and a conference
    convened by the one guardian who may speak for her."""
    set_logical_clock("2026-09-03T09:00:00Z")
    care_manager = register_care_manager(
        full_name="Dana Reyes", hourly_rate_cents=22_500
    )
    client = register_client(
        full_name="Oona Ferreira", residence_setting="SKILLED_NURSING"
    )
    assert client["capacity_status"] == "PRESUMED_CAPABLE"

    determined = record_capacity_determination(
        client["id"],
        "DIMINISHED_DOCUMENTED",
        _CAPACITY_BASIS,
        make_care_manager_headers(care_manager["id"]),
    )
    assert determined["capacity_status"] == "DIMINISHED_DOCUMENTED"
    assert determined["capacity_basis"] == _CAPACITY_BASIS

    guardian = register_surrogate_contact(
        client["id"], full_name="Pim Ferreira", contact_role="GUARDIAN"
    )
    conference = schedule_conference(
        client["id"],
        [guardian["id"]],
        care_manager["id"],
        scheduled_start="2026-09-04T14:00:00Z",
        scheduled_end="2026-09-04T15:00:00Z",
        agenda="Placement change",
    )
    conference = convene_conference(
        conference["id"], [guardian["id"]], care_manager["id"]
    )
    assert conference["quorum_met"] is True
    assert conference["surrogate_present"] is True
    return care_manager, client, guardian, conference


def test_08_a_decision_for_a_diminished_capacity_client_needs_its_basis():
    """`capacity_basis` is optional in the payload contract and mandatory in effect
    the moment capacity is no longer presumed, so the decision is refused and no row
    is written.

    PRD: "First, `capacity_basis` — the evidentiary basis for relying on a surrogate at all — is optional in general but mandatory whenever the client's `capacity_status` is anything other than `PRESUMED_CAPABLE`; a decision documented for a `DIMINISHED_DOCUMENTED` or `ADJUDICATED_INCAPACITATED` client without it is rejected with `ERR_CAPACITY_BASIS_REQUIRED`."

    Design: Corner/errors/capacity_basis_required_once_capacity_is_not_presumed
    """
    care_manager, _client, guardian, conference = (
        _a_diminished_capacity_client_at_a_convened_conference()
    )

    validate_error(
        api_client.create_conference_decision(
            create_conference_decision_payload(
                conference["id"],
                guardian["id"],
                decision_type="PLACEMENT_CHANGE",
                decision_text=_PLACEMENT_TEXT,
            ),
            make_care_manager_headers(care_manager["id"]),
        ),
        "ERR_CAPACITY_BASIS_REQUIRED",
        422,
    )

    _rows, meta = validate_paginated(
        api_client.list_conference_decisions(
            PRACTICE_ADMIN, params={"family_conference_id": conference["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_09_the_identical_decision_is_recorded_once_the_basis_is_supplied():
    """The refused payload with the evidentiary basis added is accepted, and the
    basis is stored on the decision as supplied.

    PRD: "First, `capacity_basis` — the evidentiary basis for relying on a surrogate at all — is optional in general but mandatory whenever the client's `capacity_status` is anything other than `PRESUMED_CAPABLE`; a decision documented for a `DIMINISHED_DOCUMENTED` or `ADJUDICATED_INCAPACITATED` client without it is rejected with `ERR_CAPACITY_BASIS_REQUIRED`."

    Design: Corner/errors/capacity_basis_required_once_capacity_is_not_presumed
    """
    care_manager, _client, guardian, conference = (
        _a_diminished_capacity_client_at_a_convened_conference()
    )

    decision = record_conference_decision(
        conference["id"],
        guardian["id"],
        care_manager["id"],
        decision_type="PLACEMENT_CHANGE",
        decision_text=_PLACEMENT_TEXT,
        capacity_basis=_GUARDIANSHIP_ORDER,
    )
    assert decision["status"] == "RECORDED"
    assert decision["capacity_basis"] == _GUARDIANSHIP_ORDER
    assert decision["decision_type"] == "PLACEMENT_CHANGE"

    _rows, meta = validate_paginated(
        api_client.list_conference_decisions(
            PRACTICE_ADMIN, params={"family_conference_id": conference["id"]}
        )
    )
    assert meta["total_count"] == 1


_NEUROPSYCH_BASIS = "Neuropsychological evaluation 2026-09-04"


def _two_ratified_decisions_on_a_documented_conference():
    """A fully written-up conference carrying two ratified decisions — one vendor
    engagement, one guardianship petition — for a client still presumed capable."""
    set_logical_clock("2026-09-05T09:00:00Z")
    care_manager = register_care_manager(
        full_name="Dana Reyes", hourly_rate_cents=22_500
    )
    supervisor = register_supervisor(
        full_name="Iris Vance", credential="CCM", hourly_rate_cents=30_000
    )
    client = register_client(
        full_name="Quinn Adeyemi", residence_setting="PRIVATE_HOME"
    )
    assert client["capacity_status"] == "PRESUMED_CAPABLE"
    surrogate = register_surrogate_contact(
        client["id"], full_name="Remy Adeyemi", contact_role="POA_HEALTHCARE"
    )

    conference = schedule_conference(
        client["id"],
        [surrogate["id"]],
        care_manager["id"],
        scheduled_start="2026-09-06T14:00:00Z",
        scheduled_end="2026-09-06T15:00:00Z",
        agenda="Vendor engagement and protective options",
    )
    convene_conference(conference["id"], [surrogate["id"]], care_manager["id"])

    engagement = record_conference_decision(
        conference["id"],
        surrogate["id"],
        care_manager["id"],
        decision_type="VENDOR_ENGAGEMENT",
        decision_text="Retain Northgate Home Care",
    )
    petition = record_conference_decision(
        conference["id"],
        surrogate["id"],
        care_manager["id"],
        decision_type="ESCALATE_GUARDIANSHIP_PETITION",
        decision_text="Consider a guardianship petition",
    )
    engagement = ratify_conference_decision(engagement["id"], supervisor["id"])
    petition = ratify_conference_decision(petition["id"], supervisor["id"])
    assert engagement["status"] == "RATIFIED"
    assert petition["status"] == "RATIFIED"

    documented = document_conference(conference["id"], care_manager["id"])
    assert documented["status"] == "DOCUMENTED"
    return care_manager, supervisor, client, engagement, petition


def test_10_a_non_escalation_decision_type_cannot_be_escalated():
    """The escalation edge exists out of `RATIFIED`, so a vendor-engagement decision
    is refused for failing the escalation preconditions rather than for having no
    edge at all, and nothing about the client's protective posture moves.

    PRD: "`RATIFIED → ESCALATED` requires that the decision's `decision_type` is `ESCALATE_GUARDIANSHIP_PETITION` or `ESCALATE_APS_REPORT`, that the client's `capacity_status` is `DIMINISHED_DOCUMENTED` or `ADJUDICATED_INCAPACITATED`, and that the parent conference's `status` is `DOCUMENTED` — the practice does not petition a court on the strength of a conference it has not finished writing up."

    Design: Corner/errors/escalation_precondition_unmet_for_presumed_capable_client_and_wrong_type
    """
    _care_manager, supervisor, client, engagement, _petition = (
        _two_ratified_decisions_on_a_documented_conference()
    )

    response = api_client.patch_conference_decision_state(
        engagement["id"],
        decision_state_payload("ESCALATED"),
        make_practice_supervisor_headers(supervisor["id"]),
    )
    error = validate_error(response, "ERR_ESCALATION_PRECONDITION_UNMET", 422)
    assert error["error_id"] != "ERR_INVALID_STATE_TRANSITION"

    unchanged = read_decision(engagement["id"])
    assert unchanged["status"] == "RATIFIED"
    assert unchanged["escalated_at"] is None
    assert read_client(client["id"])["protective_escalation_status"] == "NONE"


def test_11_a_petition_waits_for_the_capacity_finding_that_justifies_it():
    """The guardianship petition is refused while the client is presumed capable and
    accepted unchanged once capacity is documented as diminished, at which point the
    escalation is stamped with the logical clock.

    PRD: "On success, `escalated_at` is set to the logical clock's current instant, the client's `protective_escalation_status` is recomputed to `PENDING`, the client's `risk_posture` is recomputed, and both the decision's `version` and the client's `version` increase by 1."

    Design: Corner/errors/escalation_precondition_unmet_for_presumed_capable_client_and_wrong_type
    """
    care_manager, supervisor, client, _engagement, petition = (
        _two_ratified_decisions_on_a_documented_conference()
    )

    validate_error(
        api_client.patch_conference_decision_state(
            petition["id"],
            decision_state_payload("ESCALATED"),
            make_practice_supervisor_headers(supervisor["id"]),
        ),
        "ERR_ESCALATION_PRECONDITION_UNMET",
        422,
    )
    assert read_client(client["id"])["protective_escalation_status"] == "NONE"

    determined = record_capacity_determination(
        client["id"],
        "DIMINISHED_DOCUMENTED",
        _NEUROPSYCH_BASIS,
        make_care_manager_headers(care_manager["id"]),
    )
    assert determined["capacity_status"] == "DIMINISHED_DOCUMENTED"

    escalated = escalate_conference_decision(petition["id"], supervisor["id"])
    assert escalated["status"] == "ESCALATED"
    assert_timestamps_equal(escalated["escalated_at"], "2026-09-05T09:00:00Z")
    assert read_client(client["id"])["protective_escalation_status"] == "PENDING"


def _a_discharged_client_holding_a_draft_invoice():
    """Two approved days of coordination, a draft invoice over the second half of
    the month, and then a closed file."""
    scenario = setup_active_care_plan_scenario(
        clock="2026-08-25T09:00:00Z",
        client_overrides={
            "full_name": "Sena Okafor",
            "residence_setting": "PRIVATE_HOME",
            "billing_increment_min": 15,
            "retainer_floor_cents": 0,
        },
        surrogate_role="POA_FINANCIAL",
        scores=uniform_domain_scores(2),
        goals=["Short-term coordination"],
    )
    first = create_approved_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        scenario.supervisor_id,
        "2026-08-10T10:00:00Z",
        "2026-08-10T11:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )
    second = create_approved_time_entry(
        scenario.client_id,
        scenario.care_manager_id,
        scenario.supervisor_id,
        "2026-08-20T10:00:00Z",
        "2026-08-20T11:00:00Z",
        service_type="CARE_COORDINATION",
        service_location_id="OFFICE",
    )
    draft = open_invoice(
        scenario.client_id, period_start="2026-08-16", period_end="2026-08-31"
    )
    assert draft["status"] == "DRAFT"

    discharged = discharge_client(scenario.client_id, reason="Client moved out of state")
    assert discharged["status"] == "DISCHARGED"
    return scenario, first, second, draft


def test_12_no_invoice_may_be_opened_for_a_discharged_client():
    """Discharge closes the billing window at its entrance: a fresh period cannot be
    opened for the client at all, and the discharge itself has already withdrawn her
    care plan.

    PRD: "An invoice may not be opened for a `DISCHARGED` client, which reports `ERR_CLIENT_NOT_IN_SERVICE`, and an invoice whose line set would be empty is rejected with `ERR_NO_BILLABLE_ACTIVITY`."

    Design: Corner/errors/discharged_client_blocks_invoice_creation_and_issue
    """
    scenario, _first, _second, _draft = _a_discharged_client_holding_a_draft_invoice()

    validate_error(
        api_client.create_invoice(
            create_invoice_payload(
                scenario.client_id, period_start="2026-08-01", period_end="2026-08-15"
            ),
            BILLING_ADMINISTRATOR,
        ),
        "ERR_CLIENT_NOT_IN_SERVICE",
        409,
    )

    assert read_client(scenario.client_id)["status"] == "DISCHARGED"
    assert read_care_plan(scenario.care_plan_id)["status"] == "WITHDRAWN"


def test_13_an_already_drafted_invoice_may_no_longer_be_issued():
    """The window closes behind an invoice that was drafted while the client was
    still in service: issuing it is refused and it stays exactly where it was.

    PRD: "It requires that recomputing under the final variant still yields a non-empty `line_entry_ids`, else `ERR_NO_BILLABLE_ACTIVITY`, and that the client is not `DISCHARGED`."

    Design: Corner/errors/discharged_client_blocks_invoice_creation_and_issue
    """
    _scenario, _first, _second, draft = _a_discharged_client_holding_a_draft_invoice()

    validate_error(
        api_client.patch_invoice_state(
            draft["id"], invoice_state_payload("ISSUED"), BILLING_ADMINISTRATOR
        ),
        "ERR_CLIENT_NOT_IN_SERVICE",
        409,
    )

    unchanged = read_invoice(draft["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["issued_at"] is None


def test_14_that_draft_may_still_be_voided_and_no_time_is_consumed():
    """Voiding a draft is always available and consumes nothing, so both approved
    days survive uninvoiced and the whole accrual is still standing.

    PRD: "A `DRAFT` invoice may always be voided; the supplied `reason` is stored as `voided_reason`, the invoice's `version` increases by 1, and no money and no entry state changes at all, because a draft invoice never drew retainer nor moved any entry."

    Design: Corner/errors/discharged_client_blocks_invoice_creation_and_issue
    """
    scenario, first, second, draft = _a_discharged_client_holding_a_draft_invoice()

    voided = void_invoice(draft["id"], reason="Client discharged before issue")
    assert voided["status"] == "VOIDED"
    assert voided["voided_reason"] == "Client discharged before issue"
    assert voided["version"] > draft["version"]

    for entry in (first, second):
        observed = read_time_entry(entry["id"])
        assert observed["status"] == "APPROVED"
        assert observed["invoice_id"] is None

    assert read_client(scenario.client_id)["unbilled_accrual_cents"] == 45_000
