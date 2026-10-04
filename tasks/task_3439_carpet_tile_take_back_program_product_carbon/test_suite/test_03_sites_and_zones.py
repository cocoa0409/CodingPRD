"""Customer sites and installed zones (PRD §3.3): required fields, certified
installation and the contractor window buffer, zone guards, the first-zone
bubble-up, the decommission cascade, and ownership on installer operations.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    cancel_takeback,
    create_collection,
    create_batch,
    create_installed_site,
    create_order,
    create_site,
    create_takeback,
    create_takeback_request_payload,
    create_zone_payload,
    install_site,
    lay_zone,
    make_installer_headers,
    make_specifier_headers,
    match_order,
    schedule_takeback,
    set_clock,
    setup_collection_with_batch,
    validate_created,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_site_create_missing_required_budget_returns_invalid_request(
    api, specifier_headers
):
    """PRD §2.8 (rule 11): "and general request shape — required fields
    present, enum members known, `vintage_year` at least 2020,
    `target_reduction_pct` strictly between 0 and 1, quantities positive
    (`ERR_INVALID_REQUEST`, 400)."
    PRD §3.3 lists `annual_replacement_budget_cents` among the registration
    payload fields with no optional marker: "records the `installation_system`
    — `ADHESIVE_FREE` or `CONVENTIONAL` — together with the contractor's
    certification snapshot `adhesive_free_certified`, the certification's
    `cert_expires_on`, and the site's `annual_replacement_budget_cents`, a
    whole-cents budget of zero or more."

    Design: Corner/entities/site_create_missing_required_budget_returns_invalid_request
    """
    set_clock()
    payload = {
        "contractor_name": "inst-bob",
        "address": "1 Harbor Way",
        "install_window_start": "2026-09-02T00:00:00Z",
        "install_window_end": "2026-09-03T00:00:00Z",
        "installation_system": "CONVENTIONAL",
        "adhesive_free_certified": False,
        "cert_expires_on": "2027-01-01T00:00:00Z",
    }
    resp = api.create_site(payload, specifier_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_first_zone_bubbles_site_to_in_service_exactly_once(api, admin_headers):
    """PRD §3.3: "Laying the site's first zone also bubbles the site itself
    from `INSTALLED` to `IN_SERVICE`, incrementing the site's `version` by 1."
    PRD §2.4: "`version` (integer): a system-managed integer that starts at 1
    when the resource is created and increments by exactly 1 on every mutation
    of the entity's own stored fields — including mutations that arrive through
    a cascade or an automatic state reconciliation rather than a direct client
    call on that resource."

    Design: Corner/state_machines/first_zone_bubbles_site_to_in_service_exactly_once
    """
    set_clock()
    built = setup_collection_with_batch()
    site = create_installed_site()
    assert site["version"] == 2, "create (1) + install bump = 2"

    lay_zone(site, built["batch"]["id"], zone_code="Z-1", area_m2=30)
    data = validate_success(api.get_site(site["id"], admin_headers))
    assert data["status"] == "IN_SERVICE"
    assert data["version"] == 3, "first zone bubbles the parent exactly once"

    lay_zone(site, built["batch"]["id"], zone_code="Z-2", area_m2=20)
    data = validate_success(api.get_site(site["id"], admin_headers))
    assert data["version"] == 3, "second zone mutates no site field — no bump"
    batch = validate_success(api.get_batch(built["batch"]["id"], admin_headers))
    assert batch["available_m2"] == 50


def test_decommission_cascades_to_zones_and_orders(api, admin_headers):
    """PRD §2.9: "Decommissioning a site that is `IN_SERVICE` reclaims every
    zone still `IN_SERVICE` to `RECLAIMED`, cancels every replacement order of
    the site in `DRAFT` or `MATCH_FAILED`, and cancels every order in `MATCHED`
    with the order's full cancellation side effect — the reserved area is
    returned to the matched batch's `available_m2`, and a batch sitting at
    `EXHAUSTED` reverts to `RELEASED` as availability returns."

    Design: Corner/state_machines/decommission_cascades_to_zones_and_orders
    """
    set_clock()
    built = setup_collection_with_batch()
    batch = built["batch"]
    site = create_installed_site()
    z1 = lay_zone(site, batch["id"], zone_code="Z-1", area_m2=30)
    z2 = lay_zone(site, batch["id"], zone_code="Z-2", area_m2=40)
    ord1 = create_order(site, z1, reason="WEAR", new_zone_code="Z-1R")
    ord1 = match_order(ord1, site)
    assert ord1["status"] == "MATCHED"
    # The 30 m2 reservation takes the batch from 30 available to EXHAUSTED.
    assert validate_success(api.get_batch(batch["id"], admin_headers))[
        "status"
    ] == "EXHAUSTED"
    ord2 = create_order(site, z2, reason="DESIGN_CHANGE", new_zone_code="Z-2R")
    assert ord2["status"] == "DRAFT"

    resp = api.decommission_site(
        site["id"], make_installer_headers(site["contractor_name"])
    )
    data = validate_success(resp)
    assert data["status"] == "DECOMMISSIONED"

    rows, _ = validate_paginated(
        api.list_zones(admin_headers, params={"site_id": site["id"]})
    )
    assert {row["zone_code"]: row["status"] for row in rows} == {
        "Z-1": "RECLAIMED",
        "Z-2": "RECLAIMED",
    }
    rows, _ = validate_paginated(
        api.list_replacement_orders(admin_headers, params={"site_id": site["id"]})
    )
    assert {row["id"]: row["status"] for row in rows} == {
        ord1["id"]: "CANCELLED",
        ord2["id"]: "CANCELLED",
    }
    batch = validate_success(api.get_batch(batch["id"], admin_headers))
    assert batch["available_m2"] == 30
    assert batch["status"] == "RELEASED", "reservation release reverts EXHAUSTED"


def test_zone_code_conflict_among_in_service_zones(api, admin_headers):
    """PRD §3.3: "The `zone_code` must be unique among the site's zones that
    are currently `IN_SERVICE`; a collision is rejected with
    `ERR_ZONE_CODE_CONFLICT` (HTTP 409)."

    Design: Corner/validations/zone_code_conflict_among_in_service_zones
    """
    set_clock()
    built = setup_collection_with_batch()
    site = create_installed_site()
    lay_zone(site, built["batch"]["id"], zone_code="Z-1", area_m2=30)
    resp = api.create_zone(
        site["id"],
        create_zone_payload(built["batch"]["id"], zone_code="Z-1", area_m2=10),
        make_installer_headers(site["contractor_name"]),
    )
    validate_error(resp, ApiErrorId.ERR_ZONE_CODE_CONFLICT)
    # A different code on the same site succeeds.
    lay_zone(site, built["batch"]["id"], zone_code="Z-2", area_m2=10)
    batch = validate_success(api.get_batch(built["batch"]["id"], admin_headers))
    assert batch["available_m2"] == 60


def test_area_exceeds_batch_availability_returns_422(api, admin_headers):
    """PRD §3.3: "The requested `area_m2` may not exceed the batch's
    `available_m2`, on pain of `ERR_AREA_EXCEEDS_BATCH` (HTTP 422)."

    Design: Corner/validations/area_exceeds_batch_availability_returns_422
    """
    set_clock()
    built = setup_collection_with_batch()
    site = create_installed_site()
    resp = api.create_zone(
        site["id"],
        create_zone_payload(built["batch"]["id"], zone_code="Z-BIG", area_m2=100.5),
        make_installer_headers(site["contractor_name"]),
    )
    validate_error(resp, ApiErrorId.ERR_AREA_EXCEEDS_BATCH)
    batch = validate_success(api.get_batch(built["batch"]["id"], admin_headers))
    assert batch["available_m2"] == 100, "the failed laying debits nothing"


def test_planned_site_blocks_zone_and_takeback_and_quarantine_batch_blocked(
    api, admin_headers
):
    """PRD §3.3: "The batch must be `RELEASED` — laying from any other batch
    state is rejected with `ERR_BATCH_NOT_RELEASED` (HTTP 409) — and the site
    must be `INSTALLED` or `IN_SERVICE`, otherwise `ERR_SITE_NOT_INSTALLED`
    (HTTP 409)."
    PRD §3.5: "The site must be `INSTALLED` or `IN_SERVICE`; a take-back
    against a site in `PLANNED` or `DECOMMISSIONED` is rejected with
    `ERR_SITE_NOT_INSTALLED` (HTTP 409)."

    Design: Corner/validations/planned_site_blocks_zone_and_takeback_and_quarantine_batch_blocked
    """
    set_clock()
    built = setup_collection_with_batch()  # RELEASED batch
    col = create_collection()
    batch = create_batch(col["id"])  # stays QUARANTINE
    site1 = create_site()  # stays PLANNED (contractor inst-bob)
    site2 = create_site(
        contractor_name="inst-cory",
        address="9 Meadow Ln",
        installation_system="ADHESIVE_FREE",
        adhesive_free_certified=True,
    )
    site2 = install_site(site2)

    # Only the site-state guard can trip on this request: the batch is
    # RELEASED, so the PLANNED site alone determines the error.
    resp = api.create_zone(
        site1["id"],
        create_zone_payload(built["batch"]["id"]),
        make_installer_headers("inst-bob"),
    )
    validate_error(resp, ApiErrorId.ERR_SITE_NOT_INSTALLED)

    resp = api.create_takeback_request(
        create_takeback_request_payload(site1["id"], col["id"]),
        make_specifier_headers(site1["created_by"]),
    )
    validate_error(resp, ApiErrorId.ERR_SITE_NOT_INSTALLED)

    resp = api.create_zone(
        site2["id"],
        create_zone_payload(batch["id"]),
        make_installer_headers("inst-cory"),
    )
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_RELEASED)


def test_decommission_blocked_by_inflight_takeback_then_succeeds(api, admin_headers):
    """PRD §3.3: "The `Installer` whose `X-User-ID` matches the site's
    `contractor_name` may decommission from either `PLANNED` or `IN_SERVICE`,
    provided no take-back request of the site is still in flight — a take-back
    in `REQUESTED`, `SCHEDULED`, or `COLLECTED` blocks the transition with
    `ERR_TAKEBACK_IN_FLIGHT` (HTTP 409)."

    Design: Corner/validations/decommission_blocked_by_inflight_takeback_then_succeeds
    """
    set_clock()
    built = setup_collection_with_batch()
    site = create_installed_site()
    # A zone brings the site to IN_SERVICE — one of the two states from which
    # the PRD allows decommissioning at all.
    lay_zone(site, built["batch"]["id"], zone_code="Z-1", area_m2=10)
    tb = create_takeback(site, built["collection"]["id"])
    schedule_takeback(tb, site)

    resp = api.decommission_site(
        site["id"], make_installer_headers(site["contractor_name"])
    )
    validate_error(resp, ApiErrorId.ERR_TAKEBACK_IN_FLIGHT)
    data = validate_success(api.get_site(site["id"], admin_headers))
    assert data["status"] == "IN_SERVICE", "blocked decommission changes nothing"

    cancel_takeback(tb)
    resp = api.decommission_site(
        site["id"], make_installer_headers(site["contractor_name"])
    )
    data = validate_success(resp)
    assert data["status"] == "DECOMMISSIONED"


def test_installer_ownership_mismatch_returns_forbidden(api, admin_headers):
    """PRD §2.1: "Installer-side ownership requires `X-User-ID` to equal the
    customer site's `contractor_name` string, which is recorded on the site at
    registration; an installer whose identifier does not match the site's
    `contractor_name` is rejected with `ERR_FORBIDDEN` even though the
    `Installer` role is authorized for the endpoint in general."

    Design: Corner/rbac/installer_ownership_mismatch_returns_forbidden
    """
    set_clock()
    site = create_site()  # contractor_name inst-bob, PLANNED
    resp = api.install_site(site["id"], make_installer_headers("inst-other"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    data = validate_success(api.get_site(site["id"], admin_headers))
    assert data["status"] == "PLANNED"


def test_window_start_exactly_one_day_after_prior_end_conflicts(api, admin_headers):
    """PRD §3.3: "no other site with the same `contractor_name` may sit in
    `INSTALLED` or `IN_SERVICE` with an install window that conflicts with this
    one, where a conflict is judged after extending each closed window by a
    buffer of one full day — 86,400 seconds — at both ends; a conflict is
    rejected with `ERR_CONTRACTOR_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/contractor_install_window_buffer_semantics
    """
    set_clock()
    s1 = create_site(
        address="11 Depot St",
        install_window_start="2026-10-05T00:00:00Z",
        install_window_end="2026-10-10T00:00:00Z",
        annual_replacement_budget_cents=500000,
    )
    install_site(s1)
    # Starts exactly one day after S1's window end: inside the buffer day.
    s2 = create_site(
        address="12 Depot St",
        install_window_start="2026-10-11T00:00:00Z",
        install_window_end="2026-10-15T00:00:00Z",
        annual_replacement_budget_cents=500000,
    )
    resp = api.install_site(s2["id"], make_installer_headers("inst-bob"))
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_WINDOW_CONFLICT)
    assert validate_success(api.get_site(s2["id"], admin_headers))["status"] == "PLANNED"
    assert validate_success(api.get_site(s1["id"], admin_headers))["status"] == (
        "INSTALLED"
    )


def test_window_beyond_buffer_installs_and_planned_site_does_not_block(
    api, admin_headers
):
    """PRD §3.3: "no other site with the same `contractor_name` may sit in
    `INSTALLED` or `IN_SERVICE` with an install window that conflicts with this
    one, where a conflict is judged after extending each closed window by a
    buffer of one full day — 86,400 seconds — at both ends; a conflict is
    rejected with `ERR_CONTRACTOR_WINDOW_CONFLICT` (HTTP 409)."
    The candidate set is only sites in INSTALLED or IN_SERVICE: the rejected
    (still PLANNED) middle site does not itself block a later install.

    Design: Difficulty/resource_temporal_overlap/contractor_install_window_buffer_semantics
    """
    set_clock()
    s1 = create_site(
        address="11 Depot St",
        install_window_start="2026-10-05T00:00:00Z",
        install_window_end="2026-10-10T00:00:00Z",
        annual_replacement_budget_cents=500000,
    )
    install_site(s1)
    s2 = create_site(
        address="12 Depot St",
        install_window_start="2026-10-11T00:00:00Z",
        install_window_end="2026-10-15T00:00:00Z",
        annual_replacement_budget_cents=500000,
    )
    validate_error(
        api.install_site(s2["id"], make_installer_headers("inst-bob")),
        ApiErrorId.ERR_CONTRACTOR_WINDOW_CONFLICT,
    )
    # S3 [10-13, 10-17] clears S1's buffered window under any reading of the
    # rule, while overlapping the PLANNED S2 under every reading — success
    # therefore also proves PLANNED sites are outside the candidate set.
    s3 = create_site(
        address="13 Depot St",
        install_window_start="2026-10-13T00:00:00Z",
        install_window_end="2026-10-17T00:00:00Z",
        annual_replacement_budget_cents=500000,
    )
    resp = api.install_site(s3["id"], make_installer_headers("inst-bob"))
    data = validate_success(resp)
    assert data["status"] == "INSTALLED"
    assert validate_success(api.get_site(s2["id"], admin_headers))["status"] == "PLANNED"


def test_install_uncertified_and_expired_returns_referential_error(api, admin_headers):
    """PRD §2.8: "the pipeline is **first-failure-wins**: checks run in the
    priority order below, and the first check that fails determines the error
    response; later checks are not evaluated for that request."
    PRD §2.8 (rule 9, referential): "an `ADHESIVE_FREE` installation requires
    the certified flag (`ERR_ADHESIVE_FREE_CERT_REQUIRED`, 422)".
    PRD §2.8 (rule 10, temporal): "A certified installer's `cert_expires_on`
    must be strictly later than the site's `install_window_start`
    (`ERR_CONTRACTOR_CERT_EXPIRED`, 422)".

    Design: Difficulty/priority_pair_validation_conflict/install_uncertified_and_expired_returns_referential_error
    """
    set_clock()
    # Dual violation: ADHESIVE_FREE without certification AND an expired cert.
    site = create_site(
        contractor_name="inst-x",
        address="7 Prairie Rd",
        install_window_start="2026-10-05T00:00:00Z",
        install_window_end="2026-10-10T00:00:00Z",
        installation_system="ADHESIVE_FREE",
        adhesive_free_certified=False,
        cert_expires_on="2026-01-01T00:00:00Z",
        annual_replacement_budget_cents=500000,
    )
    resp = api.install_site(site["id"], make_installer_headers("inst-x"))
    # The referential guard (priority 9) outranks the temporal one (10).
    validate_error(resp, ApiErrorId.ERR_ADHESIVE_FREE_CERT_REQUIRED)
    data = validate_success(api.get_site(site["id"], admin_headers))
    assert data["status"] == "PLANNED", "no partial transition"


def test_install_certified_but_expired_returns_temporal_error(api, admin_headers):
    """PRD §3.3: "Whenever the contractor is recorded as certified, the
    certification must still be live at the window's opening:
    `cert_expires_on` must be strictly later than `install_window_start`,
    otherwise `ERR_CONTRACTOR_CERT_EXPIRED` (HTTP 422)."
    PRD §3.3: "An `ADHESIVE_FREE` installation system requires
    `adhesive_free_certified` to be true; otherwise
    `ERR_ADHESIVE_FREE_CERT_REQUIRED` (HTTP 422)." — the temporal error is the
    one that fires when the referential one does not.

    Design: Difficulty/priority_pair_validation_conflict/install_uncertified_and_expired_returns_referential_error
    """
    set_clock()
    # Temporal violation only: certified, but the cert predates the window.
    site = create_site(
        contractor_name="inst-y",
        address="8 Prairie Rd",
        install_window_start="2026-10-05T00:00:00Z",
        install_window_end="2026-10-10T00:00:00Z",
        installation_system="ADHESIVE_FREE",
        adhesive_free_certified=True,
        cert_expires_on="2026-01-01T00:00:00Z",
        annual_replacement_budget_cents=500000,
    )
    resp = api.install_site(site["id"], make_installer_headers("inst-y"))
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_CERT_EXPIRED)
    data = validate_success(api.get_site(site["id"], admin_headers))
    assert data["status"] == "PLANNED", "no partial transition"
