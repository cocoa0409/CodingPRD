"""Resource temporal overlap (queue A): one ACTIVE agreement per issuer; one
live provisioning window per device."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    create_agreement_payload,
    get_success_data,
    make_cardholder_headers,
    open_session,
    reset_clock,
    setup_account_and_artifact,
    setup_cardholder,
    setup_device,
    setup_issuer_active,
    validate_error,
)
from test_helpers import create_issuer_payload


def _issuer_with_active_agreement(api):
    reset_clock(api)
    issuer = get_success_data(api.create_issuer(create_issuer_payload(), ADMIN))
    agr_a = get_success_data(
        api.create_agreement(create_agreement_payload(issuer["id"]), ADMIN)
    )
    get_success_data(api.activate_agreement(agr_a["id"], ADMIN))
    agr_b = get_success_data(
        api.create_agreement(
            create_agreement_payload(
                issuer["id"], terms_version="v2", fee_bps=100, fee_cap_cents=900,
                effective_at="2027-09-01T00:00:00Z",
                expires_at="2028-09-01T00:00:00Z",
            ),
            ADMIN,
        )
    )
    return issuer, agr_a, agr_b


def test_second_agreement_activation_rejected_overlap(api):
    """PRD section 3.1: "no other agreement of the same issuer may already be
    ACTIVE (otherwise ERR_AGREEMENT_OVERLAP). There is at most one active fee
    schedule per issuer at any moment." A second agreement whose window merely
    touches the incumbent is still rejected.

    Design: Difficulty/resource_temporal_overlap/agreement_activation_rejects_overlapping_active_agreement_half_open_window
    """
    _issuer, _a, agr_b = _issuer_with_active_agreement(api)
    resp = api.activate_agreement(agr_b["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_OVERLAP)


def test_agreement_activation_succeeds_after_incumbent_terminated(api):
    """PRD section 3.1: "Terminating the ACTIVE agreement has a sharper edge:
    if it was the issuer's last active agreement, the parent issuer drops to
    SUSPENDED" and "no other agreement of the same issuer may already be
    ACTIVE (otherwise ERR_AGREEMENT_OVERLAP)." Once the incumbent is
    terminated, the issuer is no longer OFFBOARDED and no agreement is ACTIVE,
    so the pending agreement activates.

    Design: Difficulty/resource_temporal_overlap/agreement_activation_rejects_overlapping_active_agreement_half_open_window
    """
    _issuer, agr_a, agr_b = _issuer_with_active_agreement(api)
    get_success_data(api.terminate_agreement(agr_a["id"], ADMIN))
    activated = get_success_data(api.activate_agreement(agr_b["id"], ADMIN))
    assert activated["status"] == "ACTIVE"


def _device_with_open_session(api):
    reset_clock(api)
    ch = setup_cardholder(api)
    issuer, _ = setup_issuer_active(api)
    device = setup_device(api, ch)
    account, artifact = setup_account_and_artifact(api, ch, issuer)
    session = open_session(api, device, artifact, ch)
    return ch, device, account, artifact, session


def test_second_session_rejected_while_first_is_live(api):
    """PRD section 2.10: "One active provisioning window per device — a device
    that already has a non-terminal provisioning session (one in INITIATED,
    VERIFICATION_REQUIRED, or VERIFIED that has not yet expired) rejects a
    second session creation with ERR_INVALID_STATE."

    Design: Difficulty/resource_temporal_overlap/provisioning_session_overlap_rejected_per_device_active_window
    """
    ch, device, _account, artifact, _session = _device_with_open_session(api)
    resp = api.create_provisioning_session(
        device["id"],
        {"card_artifact_id": artifact["id"], "idempotency_key": "prov-second"},
        make_cardholder_headers(ch["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_new_session_accepted_after_first_expires(api):
    """PRD section 2.10: "One active provisioning window per device — a device
    that already has a non-terminal provisioning session (one in INITIATED,
    VERIFICATION_REQUIRED, or VERIFIED that has not yet expired) rejects a
    second session creation with ERR_INVALID_STATE." After the first session's
    window closes (clock advanced past expires_at), a new session is accepted.

    Design: Difficulty/resource_temporal_overlap/provisioning_session_overlap_rejected_per_device_active_window
    """
    ch, device, _account, artifact, session = _device_with_open_session(api)
    api.set_clock("2026-09-02T00:00:00Z", None)
    # lazy flip on read
    get_success_data(api.get_provisioning_session(session["id"]))
    resp = api.create_provisioning_session(
        device["id"],
        {"card_artifact_id": artifact["id"], "idempotency_key": "prov-second"},
        make_cardholder_headers(ch["id"]),
    )
    new_session = get_success_data(resp)
    assert new_session["status"] == "VERIFICATION_REQUIRED"
