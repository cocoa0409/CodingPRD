"""Data share grants, the scope gate, and identity-scoped reads."""

from test_helpers import (
    ApiErrorId,
    AGRONOMIST,
    add_machine,
    create_data_share_grant_payload,
    create_dealer,
    create_grant,
    create_machine_payload,
    create_org,
    create_partner,
    make_dealer_technician_headers,
    make_grower_manager_headers,
    make_partner_app_headers,
    read_grant,
    read_session,
    revoke_grant,
    setup_open_session,
    setup_org_dealer,
    suspend_grant,
    validate_error,
    validate_success,
)


def test_grant_revoke_is_terminal_lockdown(api):
    """PRD section 3.4: "revoking moves either `ACTIVE` or `SUSPENDED` →
    `REVOKED`, which is terminal." A second revoke and a resume on a revoked
    grant are transitions that do not exist and fail with
    `ERR_INVALID_STATE_TRANSITION` (PRD section 2.10 step 6).

    Design: Corner/state_machines/grant_revoke_is_terminal_lockdown
    """
    ctx = setup_org_dealer(api)
    grant = create_grant(ctx, api)
    revoke_grant(ctx, api, grant["id"])

    response = api.revoke_data_share_grant(grant["id"], headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    response = api.resume_data_share_grant(grant["id"], headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    grant = read_grant(ctx, api, grant["id"])
    assert grant["status"] == "REVOKED"


def test_scope_gate_denied_granted_then_suspended(api):
    """PRD section 3.4: "a grant, which must be `ACTIVE`, must belong to the
    target organization, must have a `grantee_type` mapping to the caller's
    role, must have `grantee_ref_id` equal to the caller's `X-User-ID`, must
    have a closed window covering the current logical time, and must include
    the scope the endpoint requires. ... Any shortfall is
    `ERR_DATA_ACCESS_DENIED` (HTTP 403)." and "suspending moves `ACTIVE` →
    `SUSPENDED` (and a suspended grant grants nothing while it sits)".

    Design: Corner/validations/scope_gate_denied_granted_then_suspended
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api, serial_number="SN-0001")

    response = api.get_machine(machine["id"], headers=AGRONOMIST)
    validate_error(response, ApiErrorId.ERR_DATA_ACCESS_DENIED)

    grant = create_grant(ctx, api, grantee_type="AGRONOMIST",
                         grantee_ref_id="agron-ada", scopes=["TELEMATICS"])
    data = validate_success(api.get_machine(machine["id"], headers=AGRONOMIST), 200)
    assert data["serial_number"] == "SN-0001"

    suspend_grant(ctx, api, grant["id"])
    response = api.get_machine(machine["id"], headers=AGRONOMIST)
    validate_error(response, ApiErrorId.ERR_DATA_ACCESS_DENIED)


def test_grower_cannot_read_other_orgs_machine(api):
    """PRD section 2.1: "ownership checks on any resource that references an
    organization compare the resource's `organization_id` field to
    `X-User-ID`", and PRD section 3.4: "Any shortfall is
    `ERR_DATA_ACCESS_DENIED` (HTTP 403)." The GrowerManager of one organization
    cannot read another organization's machine.

    Design: Corner/rbac/grower_cannot_read_other_orgs_machine
    """
    ctx = setup_org_dealer(api)
    org2 = create_org(api, name="Cottonwood Creek Coop", region_code="US-KS")
    machine2 = validate_success(
        api.create_machine(
            create_machine_payload(org2["id"], ctx["dealer"]["id"],
                                   serial_number="SN-0002",
                                   modem_imei="IMEI-0002"),
            headers=make_grower_manager_headers(org2["id"]),
        ),
        201,
    )

    response = api.get_machine(machine2["id"], headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_DATA_ACCESS_DENIED)


def test_dealer_cannot_close_foreign_session(api):
    """PRD section 3.5: "A dealer session closes only when the caller's
    `X-User-ID` equals the session's `dealer_id`; an independent session closes
    only when the caller's `X-User-ID` equals the consuming ticket's
    `requester_ref_id`; anyone else is rejected with
    `ERR_DATA_ACCESS_DENIED`."

    Design: Corner/rbac/dealer_cannot_close_foreign_session
    """
    ctx = setup_open_session(api)
    dealer2 = create_dealer(
        api, dealer_code="D-200", name="Plains Agri Supply",
        region_code="US-KS", service_tier="PREMIUM",
    )
    response = api.close_diagnostic_session(
        ctx["session"]["id"],
        {"fault_found": False},
        headers=make_dealer_technician_headers(dealer2["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DATA_ACCESS_DENIED)
    session = read_session(ctx, api, ctx["session"]["id"])
    assert session["status"] == "OPEN"


def test_dealer_get_restricted_to_self_or_admin(api):
    """PRD section 3.1: "a `DealerTechnician` caller may read only the dealer
    whose `id` equals their `X-User-ID`, and any other dealer read by a
    technician is rejected with `ERR_DATA_ACCESS_DENIED`."

    Design: Corner/entities/dealer_get_restricted_to_self_or_admin
    """
    ctx = setup_org_dealer(api)
    dealer2 = create_dealer(
        api, dealer_code="D-200", name="Plains Agri Supply",
        region_code="US-KS", service_tier="PREMIUM",
    )

    data = validate_success(
        api.get_dealer(ctx["dealer"]["id"], headers=ctx["dealer_headers"]), 200
    )
    assert data["name"] == "River Valley Equipment"

    response = api.get_dealer(
        ctx["dealer"]["id"],
        headers=make_dealer_technician_headers(dealer2["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DATA_ACCESS_DENIED)


def test_partner_reads_other_partner_denied(api):
    """PRD section 3.9: "A `PartnerApp` may read its own partner record —
    `X-User-ID` must equal the partner `id`, otherwise
    `ERR_DATA_ACCESS_DENIED` — and `PlatformAdmin` reads any."

    Design: Corner/rbac/partner_reads_other_partner_denied
    """
    partner = create_partner(api, name="AgriSight Analytics",
                             api_quota_calls_per_day=100)
    partner2 = create_partner(api, name="FieldOps Cloud",
                              api_quota_calls_per_day=50)

    response = api.get_integration_partner(
        partner["id"], headers=make_partner_app_headers(partner2["id"])
    )
    validate_error(response, ApiErrorId.ERR_DATA_ACCESS_DENIED)

    data = validate_success(
        api.get_integration_partner(
            partner["id"], headers=make_partner_app_headers(partner["id"])
        ),
        200,
    )
    assert data["name"] == "AgriSight Analytics"


def test_grant_window_overlap_interior_and_touching_rejected(api):
    """PRD section 3.4: "Creation is rejected with `ERR_GRANT_WINDOW_OVERLAP`
    when the closed window overlaps that of any existing `ACTIVE` or
    `SUSPENDED` grant for the same organization, grantee type, and grantee
    reference that shares at least one scope — touching endpoints of the closed
    intervals count as overlap."

    Design: Difficulty/resource_temporal_overlap/grant_window_closed_interval_overlap
    """
    ctx = setup_org_dealer(api)
    create_grant(ctx, api, grantee_type="AGRONOMIST", grantee_ref_id="agron-ada",
                 scopes=["TELEMATICS"],
                 valid_from="2026-01-01T00:00:00Z",
                 valid_until="2026-03-31T00:00:00Z")

    interior = create_data_share_grant_payload(
        ctx["org"]["id"], grantee_type="AGRONOMIST", grantee_ref_id="agron-ada",
        scopes=["TELEMATICS"],
        valid_from="2026-02-01T00:00:00Z", valid_until="2026-04-30T00:00:00Z",
    )
    response = api.create_data_share_grant(interior, headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_GRANT_WINDOW_OVERLAP)

    touching = create_data_share_grant_payload(
        ctx["org"]["id"], grantee_type="AGRONOMIST", grantee_ref_id="agron-ada",
        scopes=["TELEMATICS"],
        valid_from="2026-03-31T00:00:00Z", valid_until="2026-06-30T00:00:00Z",
    )
    response = api.create_data_share_grant(touching, headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_GRANT_WINDOW_OVERLAP)


def test_grant_window_disjoint_day_and_disjoint_scope_accepted(api):
    """PRD section 3.4: "Creation is rejected with `ERR_GRANT_WINDOW_OVERLAP`
    when the closed window overlaps that of any existing `ACTIVE` or
    `SUSPENDED` grant for the same organization, grantee type, and grantee
    reference that shares at least one scope" — a window starting the day after
    the existing grant's inclusive end does not overlap, and an overlapping
    window on a disjoint scope set shares no scope, so both creates succeed.

    Design: Difficulty/resource_temporal_overlap/grant_window_closed_interval_overlap
    """
    ctx = setup_org_dealer(api)
    create_grant(ctx, api, grantee_type="AGRONOMIST", grantee_ref_id="agron-ada",
                 scopes=["TELEMATICS"],
                 valid_from="2026-01-01T00:00:00Z",
                 valid_until="2026-03-31T00:00:00Z")

    next_window = create_data_share_grant_payload(
        ctx["org"]["id"], grantee_type="AGRONOMIST", grantee_ref_id="agron-ada",
        scopes=["TELEMATICS"],
        valid_from="2026-04-01T00:00:00Z", valid_until="2026-06-30T00:00:00Z",
    )
    grant2 = validate_success(
        api.create_data_share_grant(next_window, headers=ctx["grower_headers"]),
        201,
    )
    assert grant2["status"] == "ACTIVE"

    disjoint_scope = create_data_share_grant_payload(
        ctx["org"]["id"], grantee_type="AGRONOMIST", grantee_ref_id="agron-ada",
        scopes=["DIAGNOSTICS"],
        valid_from="2026-02-01T00:00:00Z", valid_until="2026-04-30T00:00:00Z",
    )
    grant3 = validate_success(
        api.create_data_share_grant(disjoint_scope, headers=ctx["grower_headers"]),
        201,
    )
    assert grant3["status"] == "ACTIVE"
