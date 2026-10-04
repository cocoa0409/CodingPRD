"""Administrator surveillance: the conjunctive auto-suspension threshold, the
decredentialing cascade that auto-denies claims and suspends the network, and
the network-ownership gate on provider onboarding."""
from test_helpers import (
    TEST_USERS, api_client, validate_error, validate_paginated,
    adjudicate_claim, create_claim_for_appointment, create_claim_payload,
    create_provider_payload, create_tpa, decide_credential, get_claim, get_tpa,
    make_provider_rep_headers, make_tpa_admin_headers, onboard_provider,
    setup_episode_with_completed_appointments,
)

COORD = TEST_USERS["care_coordinator_headers"]


def test_denial_rate_threshold_requires_both_conditions():
    """PRD §3.1: "When a recompute lands on an `adjudicated_events` of at least
    5 **and** a `denial_rate` strictly greater than 0.20, the administrator's
    `contract_status` flips from `ACTIVE` to `SUSPENDED` automatically; a rate
    of exactly 0.20 does not suspend."
    PRD §3.1: "The `denial_rate` is the denied count divided by the adjudicated
    count, rounded half up to 4 decimal places, and is zero while no events
    exist."

    Design: Corner/calculations/denial_rate_threshold_requires_both_conditions
    """
    tpa = create_tpa()
    provider = onboard_provider(tpa)
    env_a = setup_episode_with_completed_appointments(
        num_appointments=2, authorized_visits=2, tpa=tpa, provider=provider,
        duration_days=300,
    )
    env_b = setup_episode_with_completed_appointments(
        num_appointments=2, authorized_visits=2, tpa=tpa, provider=provider,
        duration_days=300,
    )
    c1 = create_claim_for_appointment(env_a["authorization"],
                                      env_a["appointments"][0], provider)
    c2 = create_claim_for_appointment(env_a["authorization"],
                                      env_a["appointments"][1], provider)
    c3 = create_claim_for_appointment(env_b["authorization"],
                                      env_b["appointments"][0], provider)
    c4 = create_claim_for_appointment(env_b["authorization"],
                                      env_b["appointments"][1], provider)

    adjudicate_claim(c1["id"], tpa, "DENIED", "CLINICAL_REVIEW")
    adjudicate_claim(c2["id"], tpa, "PAID")
    adjudicate_claim(c3["id"], tpa, "PAID")
    adjudicate_claim(c4["id"], tpa, "PAID")

    after = get_tpa(tpa["id"])
    assert after["adjudicated_events"] == 4
    assert after["denied_events"] == 1
    assert after["denial_rate"] == 0.25
    # Rate 0.25 exceeds 0.20 but 4 events < the 5-event floor: no suspension.
    assert after["contract_status"] == "ACTIVE"


def test_decredential_autodenies_claims_suspends_tpa():
    """PRD §3.1: "First, every claim of that provider still in `RECEIVED`
    status is auto-denied, with its `denial_reason` recorded as
    `PROVIDER_DECREDENTIALED`."
    PRD §3.1: "Second, each of those cascade auto-denials is a
    claim-finalization event on the claim's administrator:
    `adjudicated_events` and `denied_events` each increase by one,
    `denial_rate` is recomputed, and the auto-suspension check runs."
    PRD §3.1: "While an administrator is `SUSPENDED`, new claim submissions for
    authorizations under that network are rejected with `ERR_TPA_SUSPENDED`."

    Design: Difficulty/transitive_cascade/decredential_autodenies_claims_suspends_tpa
    """
    tpa = create_tpa()
    p1 = onboard_provider(tpa, name="Prov One")
    p2 = onboard_provider(tpa, name="Prov Two", latitude=40.2, longitude=-75.2)

    env1 = setup_episode_with_completed_appointments(
        num_appointments=3, authorized_visits=3, tpa=tpa, provider=p1,
        duration_days=300,
    )
    env2 = setup_episode_with_completed_appointments(
        num_appointments=2, authorized_visits=2, tpa=tpa, provider=p1,
        duration_days=300,
    )
    claims = [
        create_claim_for_appointment(env1["authorization"],
                                     env1["appointments"][i], p1)
        for i in range(3)
    ] + [
        create_claim_for_appointment(env2["authorization"],
                                     env2["appointments"][i], p1)
        for i in range(2)
    ]
    c1, c2, c3, _c4, c5 = claims

    adjudicate_claim(c1["id"], tpa, "DENIED", "CLINICAL_REVIEW")
    adjudicate_claim(c2["id"], tpa, "DENIED", "CLINICAL_REVIEW")

    # An unrelated credentialed provider's episode, ready to bill.
    env3 = setup_episode_with_completed_appointments(
        num_appointments=1, authorized_visits=1, tpa=tpa, provider=p2,
        duration_days=300,
    )

    # Trigger: decredentialing P1 auto-denies its three RECEIVED claims; the
    # three cascade denials push the network to 5/5 and suspend it.
    decide_credential(p1, "DECREDENTIALED")

    c3_after = get_claim(c3["id"])
    assert c3_after["status"] == "DENIED"
    assert c3_after["denial_reason"] == "PROVIDER_DECREDENTIALED"
    assert get_claim(c5["id"])["status"] == "DENIED"

    tpa_after = get_tpa(tpa["id"])
    assert tpa_after["adjudicated_events"] == 5
    assert tpa_after["denied_events"] == 5
    assert tpa_after["contract_status"] == "SUSPENDED"

    resp = api_client.create_claim(
        create_claim_payload(env3["authorization"]["id"], "2026-09-06"),
        make_provider_rep_headers(p2["id"]),
    )
    validate_error(resp, "ERR_TPA_SUSPENDED")


def test_tpa_admin_cannot_onboard_provider_to_other_tpa():
    """PRD §3.1: "A `TPAAdministrator` onboards a **community provider** into
    its own network — the administrator in the path must be the caller's own,
    or the request fails with `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/validations/tpa_admin_cannot_onboard_provider_to_other_tpa
    """
    tpa_a = create_tpa(name="TPA A", region_code="RA")
    tpa_b = create_tpa(name="TPA B", region_code="RB")

    resp = api_client.create_provider(
        tpa_b["id"], create_provider_payload(name="Intruder"),
        make_tpa_admin_headers(tpa_a["id"]),
    )
    validate_error(resp, "ERR_OWNERSHIP_MISMATCH")

    _items, meta = validate_paginated(api_client.list_providers(tpa_b["id"], COORD))
    assert meta["total_count"] == 0
