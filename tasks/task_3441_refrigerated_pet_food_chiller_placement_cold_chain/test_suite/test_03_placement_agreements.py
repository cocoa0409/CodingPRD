"""Placement agreement lifecycle, OCC guards, and signing RBAC (PRD §2.8, §3.2, §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_placement,
    create_agreement,
    create_chiller,
    create_placement_payload,
    create_site_evaluation,
    create_store,
    make_store_operator_headers,
    setup_signed_agreement,
    sign_agreement,
    validate_error,
    validate_success,
)


def test_agreement_created_in_proposed_initial_state(api, placement_manager_headers):
    """PRD §3.2: "An agreement is born `PROPOSED`, with `signed_at` and
    `terminated_at` both null."

    Design: Corner/state_machines/agreement_created_in_proposed_initial_state
    """
    store = create_store()
    resp = api.create_placement_agreement(
        store["id"], {"allocated_sqft": 16, "max_capex_cents": 500000, "term_months": 60},
        placement_manager_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PROPOSED"
    assert data["signed_at"] is None
    assert data["terminated_at"] is None
    assert data["version"] == 1


def test_sign_terminated_agreement_returns_invalid_state(api, placement_manager_headers):
    """PRD §3.2: "Termination is available from `PROPOSED`, `SIGNED`, or
    `ACTIVE` and always lands in the terminal `TERMINATED` state with
    `terminated_at` stamped and `version` incremented."
    PRD §3.2: "Signing moves `PROPOSED` to `SIGNED`, stamps `signed_at` with
    the logical now, and increments `version`."

    Design: Corner/state_machines/sign_terminated_agreement_returns_invalid_state
    """
    store = create_store()
    agreement = create_agreement(store["id"])
    resp = api.terminate_agreement(agreement["id"], placement_manager_headers)
    terminated = validate_success(resp, expected_status=200)
    assert terminated["status"] == "TERMINATED"
    assert terminated["terminated_at"] is not None

    resp = api.sign_agreement(agreement["id"], placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409

    listed = validate_success(api.list_placement_agreements(store["id"], placement_manager_headers))
    assert listed[0]["status"] == "TERMINATED", "terminal state must survive the rejected sign"
    assert listed[0]["terminated_at"] is not None


def test_occ_revise_stale_version_returns_412(api, placement_manager_headers):
    """PRD §2.8: "Revising a placement agreement's commercial terms requires
    the request to carry `expected_agreement_version`, the caller's last
    observed `version` of that agreement; if the agreement's current `version`
    has advanced past that value — because another editor has revised the terms
    since the caller last read it — the revise is rejected with 412
    `ERR_STALE_VERSION`, preventing the caller from overwriting terms it has
    not observed."

    Design: Corner/cross_cutting_layers/occ_revise_stale_version_returns_412
    """
    store = create_store()
    agreement = create_agreement(store["id"])  # version 1
    assert agreement["version"] == 1

    first = validate_success(
        api.revise_agreement(agreement["id"],
                             {"expected_agreement_version": 1, "max_capex_cents": 450000},
                             placement_manager_headers),
        expected_status=200,
    )
    assert first["version"] == 2, "each successful revise increments version by exactly 1"
    assert first["max_capex_cents"] == 450000
    assert first["status"] == "PROPOSED", "negotiation rounds loop back to PROPOSED"

    resp = api.revise_agreement(agreement["id"],
                                {"expected_agreement_version": 1, "term_months": 48},
                                placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412

    listed = validate_success(api.list_placement_agreements(store["id"], placement_manager_headers))
    assert listed[0]["term_months"] == 60, "stale revise must not overwrite terms"
    assert listed[0]["max_capex_cents"] == 450000


def test_occ_install_stale_agreement_version_returns_412(api, placement_manager_headers):
    """PRD §2.8: "Installing a chiller against a placement agreement is guarded
    the same way: the install request must carry `expected_agreement_version`
    matching the agreement's current `version`, because the terms the caller
    priced the installation against may have been superseded by a revision; a
    mismatch is rejected with 412 `ERR_STALE_VERSION`, and the caller must
    re-read the agreement and resubmit with the current version."

    Design: Corner/cross_cutting_layers/occ_install_stale_agreement_version_returns_412
    """
    store = create_store()
    create_site_evaluation(store["id"])
    agreement = create_agreement(store["id"])
    pre_sign_version = agreement["version"]
    signed = sign_agreement(agreement["id"])
    chiller = create_chiller()

    payload = create_placement_payload(store["id"], agreement["id"], chiller["id"], pre_sign_version)
    resp = api.create_placement(payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412, "install carrying the pre-sign version must be rejected"

    payload = create_placement_payload(store["id"], agreement["id"], chiller["id"], signed["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    placement = validate_success(resp, expected_status=201)
    assert_placement(placement)
    assert placement["status"] == "ACTIVE"


def test_store_operator_cannot_sign_agreement(api, placement_manager_headers):
    """PRD §2.1: "Each endpoint authorizes a specific subset of these roles
    (see §4); an authenticated caller whose role is not in the endpoint's list
    is rejected with 403 `ERR_FORBIDDEN_ROLE`."
    PRD §4: "Sign a PROPOSED agreement | PlacementManager".

    Design: Corner/rbac/store_operator_cannot_sign_agreement
    """
    store = create_store()
    agreement = create_agreement(store["id"])
    resp = api.sign_agreement(agreement["id"], make_store_operator_headers(store["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert resp.status_code == 403

    listed = validate_success(api.list_placement_agreements(store["id"], placement_manager_headers))
    assert listed[0]["status"] == "PROPOSED", "denied sign must not advance the agreement"


def test_install_blocked_while_agreement_proposed(api, placement_manager_headers):
    """PRD §3.4: "The gates, in validation-tier order: the agreement must be
    `SIGNED` (otherwise 409 `ERR_AGREEMENT_NOT_SIGNED`); ..."

    Design: Difficulty/cross_entity_state_dependency/install_requires_agreement_signed
    """
    store = create_store()
    create_site_evaluation(store["id"])
    agreement = create_agreement(store["id"])  # PROPOSED
    chiller = create_chiller()
    payload = create_placement_payload(store["id"], agreement["id"], chiller["id"], agreement["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_SIGNED)
    assert resp.status_code == 409, "install is gated on the AGREEMENT's state, not the chiller's"


def test_install_succeeds_after_sign_and_activates_agreement(api, placement_manager_headers):
    """PRD §3.2: "A `SIGNED` agreement becomes `ACTIVE` automatically the first
    time an installation naming it succeeds — a system transition, not a
    client call."
    PRD §3.4: "A successful installation creates the **Placement** in `status`
    `ACTIVE` with `performance_status` `PENDING`, `operational_status` `OK`,
    and `underperforming_streak` 0."

    Design: Difficulty/cross_entity_state_dependency/install_requires_agreement_signed
    """
    store, evaluation, agreement = setup_signed_agreement()
    chiller = create_chiller()
    payload = create_placement_payload(store["id"], agreement["id"], chiller["id"], agreement["version"])
    resp = api.create_placement(payload, placement_manager_headers)
    placement = validate_success(resp, expected_status=201)
    assert placement["status"] == "ACTIVE"
    assert placement["performance_status"] == "PENDING"
    assert placement["operational_status"] == "OK"
    assert placement["underperforming_streak"] == 0

    listed = validate_success(api.list_placement_agreements(store["id"], placement_manager_headers))
    assert listed[0]["status"] == "ACTIVE", "SIGNED -> ACTIVE on first successful install"
    assert listed[0]["version"] == agreement["version"] + 1
