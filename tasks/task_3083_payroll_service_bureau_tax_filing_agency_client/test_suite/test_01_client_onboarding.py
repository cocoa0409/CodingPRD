"""Client onboarding and registration gate tests (PRD §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_client,
    assert_registration,
    create_client,
    create_jurisdiction,
    create_registration_payload,
    get_client,
    get_success_data,
    setup_active_client,
    validate_error,
    validate_success,
)


def test_client_onboarding_happy_path():
    """PRD §3.2: "A new client starts in `PROSPECT` status with `risk_posture` of
    `NORMAL`, a `funding_failure_count` of 0, and `credit_hold` false."
    PRD §3.2: "Beginning onboarding moves the client from `PROSPECT` to `ONBOARDING`."
    PRD §3.2: "Successful activation stamps `onboarded_at` with the logical clock's
    current instant."

    Design: Corner/state_machines/sm_client_onboarding_happy_path
    """
    jurisdiction = create_jurisdiction()
    client = create_client(legal_name="Happy Path Co")
    assert client["status"] == "PROSPECT"
    assert client["risk_posture"] == "NORMAL"
    assert client["funding_failure_count"] == 0
    assert client["credit_hold"] is False
    assert_client(client)

    onboarding = validate_success(
        api_client.begin_onboarding(client["id"], TEST_USERS["onboarder_headers"])
    )
    assert onboarding["status"] == "ONBOARDING"

    reg = get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=jurisdiction["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    validate_success(
        api_client.verify_registration(reg["id"], TEST_USERS["onboarder_headers"])
    )

    active = validate_success(
        api_client.activate_client(client["id"], TEST_USERS["onboarder_headers"])
    )
    assert active["status"] == "ACTIVE"
    assert active.get("onboarded_at"), "onboarded_at must be stamped at activation"


def test_client_created_in_prospect_with_zeroed_risk_fields():
    """PRD §3.2: "A new client starts in `PROSPECT` status with `risk_posture` of
    `NORMAL`, a `funding_failure_count` of 0, and `credit_hold` false."

    Design: Corner/state_machines/sm_client_onboarding_happy_path
    """
    client = create_client(legal_name="Prospect Fields Co")
    assert client["status"] == "PROSPECT"
    assert client["risk_posture"] == "NORMAL"
    assert client["funding_failure_count"] == 0
    assert client["credit_hold"] is False
    assert client.get("onboarded_at") in (None, ""), (
        "PROSPECT client must not carry an onboarded_at stamp"
    )


def test_activate_without_verified_registration_rejected():
    """PRD §3.2: "at least one of the client's JurisdictionRegistrations must be
    `VERIFIED`, otherwise the attempt is rejected with `ERR_NO_VERIFIED_JURISDICTION`
    (HTTP 422)."

    Design: Corner/state_machines/sm_activate_without_verified_registration_rejected
    """
    jurisdiction = create_jurisdiction()
    client = create_client(legal_name="No Reg Co")
    api_client.begin_onboarding(client["id"], TEST_USERS["onboarder_headers"])
    get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=jurisdiction["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    # Registration is still PENDING — never verified.
    resp = api_client.activate_client(client["id"], TEST_USERS["onboarder_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_VERIFIED_JURISDICTION, 422)
    assert get_client(client["id"])["status"] == "ONBOARDING"


def test_activate_with_no_registration_at_all_rejected():
    """PRD §3.2: "at least one of the client's JurisdictionRegistrations must be
    `VERIFIED`, otherwise the attempt is rejected with `ERR_NO_VERIFIED_JURISDICTION`
    (HTTP 422)."

    Design: Corner/state_machines/sm_activate_without_verified_registration_rejected
    """
    create_jurisdiction()
    client = create_client(legal_name="Zero Reg Co")
    api_client.begin_onboarding(client["id"], TEST_USERS["onboarder_headers"])
    resp = api_client.activate_client(client["id"], TEST_USERS["onboarder_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_VERIFIED_JURISDICTION, 422)
    assert get_client(client["id"])["status"] == "ONBOARDING"


def test_registration_rejection_resubmit_verify_cycle():
    """PRD §3.3: "a rejected registration may be resubmitted back to `PENDING`,
    which clears both `verified_at` and `rejected_reason`. This rejection loop —
    `REJECTED` back to `PENDING` and onward to `VERIFIED` — may cycle any number
    of times."

    Design: Difficulty/non_linear_state_machine/registration_rejection_resubmit_cycle
    """
    jurisdiction = create_jurisdiction(
        code="NY-NYS45", name="NY NYS-45", deposit_frequency="MONTHLY",
        underpayment_threshold_cents=100000,
    )
    client = create_client(legal_name="Cycle Corp")
    api_client.begin_onboarding(client["id"], TEST_USERS["onboarder_headers"])
    reg = get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=jurisdiction["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    rejected = validate_success(
        api_client.reject_registration(
            reg["id"], "Agency account number mismatch", TEST_USERS["onboarder_headers"]
        )
    )
    assert rejected["status"] == "REJECTED"
    resubmitted = validate_success(
        api_client.resubmit_registration(reg["id"], TEST_USERS["onboarder_headers"])
    )
    assert resubmitted["status"] == "PENDING"
    assert resubmitted.get("rejected_reason") in (None, ""), (
        "resubmit must clear rejected_reason"
    )
    verified = validate_success(
        api_client.verify_registration(reg["id"], TEST_USERS["onboarder_headers"])
    )
    assert verified["status"] == "VERIFIED"
    assert verified.get("verified_at"), "verified_at must be stamped on verification"


def test_resubmitted_registration_can_verify_again():
    """PRD §3.3: "This rejection loop — `REJECTED` back to `PENDING` and onward
    to `VERIFIED` — may cycle any number of times. `VERIFIED` is terminal for the
    registration itself."

    Design: Difficulty/non_linear_state_machine/registration_rejection_resubmit_cycle
    """
    jurisdiction = create_jurisdiction()
    client = create_client(legal_name="Double Cycle Co")
    api_client.begin_onboarding(client["id"], TEST_USERS["onboarder_headers"])
    reg = get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=jurisdiction["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    # Two full cycles of the rejection loop.
    for _ in range(2):
        validate_success(
            api_client.reject_registration(
                reg["id"], "Paperwork rejected", TEST_USERS["onboarder_headers"]
            )
        )
        validate_success(
            api_client.resubmit_registration(reg["id"], TEST_USERS["onboarder_headers"])
        )
    verified = validate_success(
        api_client.verify_registration(reg["id"], TEST_USERS["onboarder_headers"])
    )
    assert verified["status"] == "VERIFIED"
    # VERIFIED is terminal: another verify is not a defined transition.
    resp = api_client.verify_registration(reg["id"], TEST_USERS["onboarder_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_registration_reject_resubmit_verify_side_effects_on_row():
    """PRD §3.3: "A registration may instead be rejected, moving it from `PENDING`
    to `REJECTED` with the supplied `reason` recorded in `rejected_reason`, and a
    rejected registration may be resubmitted back to `PENDING`, which clears both
    `verified_at` and `rejected_reason`."
    PRD §3.3: "Verification moves the registration from `PENDING` to `VERIFIED` ...
    success stamps `verified_at` with the logical clock."

    Design: Corner/state_machines/sm_registration_reject_then_verify_side_effects
    """
    jurisdiction = create_jurisdiction()
    client = create_client(legal_name="Side Effect Co")
    api_client.begin_onboarding(client["id"], TEST_USERS["onboarder_headers"])
    reg = get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=jurisdiction["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    rejected = validate_success(
        api_client.reject_registration(
            reg["id"], "Bad account number", TEST_USERS["onboarder_headers"]
        )
    )
    assert rejected["rejected_reason"] == "Bad account number"
    assert rejected["status"] == "REJECTED"

    resubmitted = validate_success(
        api_client.resubmit_registration(reg["id"], TEST_USERS["onboarder_headers"])
    )
    assert resubmitted.get("rejected_reason") in (None, "")
    assert resubmitted.get("verified_at") in (None, "")

    verified = validate_success(
        api_client.verify_registration(reg["id"], TEST_USERS["onboarder_headers"])
    )
    assert verified["status"] == "VERIFIED"
    assert verified.get("verified_at"), "verified_at must be non-null after verify"
    assert_registration(verified)


def test_registrations_filtered_list_reverse_reaches_children():
    """PRD §3.3: "Registrations can be listed per client (with `jurisdiction_id`
    and `status` filters) or across clients through a bureau-wide list that accepts
    `client_id`, `jurisdiction_id`, and `status` filters as reverse-reachability
    channels."

    Design: Corner/endpoints/ep_registrations_filtered_list_reverse_reaches_children
    """
    setup = setup_active_client()
    client, reg = setup["client"], setup["registration"]

    resp = api_client.list_client_registrations(
        client["id"], TEST_USERS["onboarder_headers"], params={"status": "VERIFIED"}
    )
    data = validate_success(resp)
    rows = data if isinstance(data, list) else data.get("items", data)
    assert len(rows) == 1
    assert rows[0]["id"] == reg["id"]

    resp = api_client.list_client_registrations(
        client["id"], TEST_USERS["onboarder_headers"], params={"status": "PENDING"}
    )
    data = validate_success(resp)
    rows = data if isinstance(data, list) else data.get("items", data)
    assert len(rows) == 0


def test_registrations_list_scoped_to_owning_client():
    """PRD §3.3: "Registrations can be listed per client (with `jurisdiction_id`
    and `status` filters) or across clients through a bureau-wide list that accepts
    `client_id`, `jurisdiction_id`, and `status` filters as reverse-reachability
    channels."

    Design: Corner/endpoints/ep_registrations_filtered_list_reverse_reaches_children
    """
    setup = setup_active_client()
    client, reg = setup["client"], setup["registration"]
    other = create_client(legal_name="Other Reg Co")

    resp = api_client.list_client_registrations(
        other["id"], TEST_USERS["onboarder_headers"]
    )
    data = validate_success(resp)
    rows = data if isinstance(data, list) else data.get("items", data)
    assert len(rows) == 0

    resp = api_client.list_client_registrations(
        client["id"], TEST_USERS["onboarder_headers"]
    )
    data = validate_success(resp)
    rows = data if isinstance(data, list) else data.get("items", data)
    assert [r["id"] for r in rows] == [reg["id"]]
