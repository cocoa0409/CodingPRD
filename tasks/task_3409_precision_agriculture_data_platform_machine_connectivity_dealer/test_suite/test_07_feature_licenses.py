"""Feature license purchase fees, OCC guard, lifecycle, and the machine-side
active-license count invariant."""

from test_helpers import (
    ApiErrorId,
    activate_license,
    add_machine,
    create_feature_license_payload,
    purchase_license,
    read_license,
    read_machine,
    revoke_license,
    same_instant,
    set_clock,
    setup_connected_machine,
    setup_org_dealer,
    validate_error,
    validate_paginated,
)


def test_term_license_expires_at_clock_boundary(api):
    """PRD section 3.7: "on the first activation stamps `activated_at` and, for
    `TERM` licenses, sets `expires_at` to `activated_at` plus `term_months`"
    and "the clock sweep expires a `TERM` license in `ACTIVATED` once the
    logical time reaches `expires_at`, moving it to terminal `EXPIRED`. Every
    one of these transitions recomputes the machine's `active_license_count`".

    Design: Corner/state_machines/term_license_expires_at_clock_boundary
    """
    ctx = setup_connected_machine(api)
    machine_id = ctx["machine"]["id"]
    license = purchase_license(
        ctx, api, machine_id, feature_code="TELEMATICS_PREMIUM",
        license_type="TERM", term_months=1,
    )
    license = activate_license(api, license["id"])
    assert license["status"] == "ACTIVATED"
    assert same_instant(license["expires_at"], "2026-10-01T00:00:00Z")

    set_clock(api, "2026-10-01T00:00:00Z")
    license = read_license(ctx, api, license["id"])
    assert license["status"] == "EXPIRED"
    machine = read_machine(ctx, api, machine_id)
    assert machine["active_license_count"] == 0


def test_license_duplicate_feature_rejected(api):
    """PRD section 3.7: "At most one non-`REVOKED` license may exist per
    machine and feature code; a duplicate is `ERR_LICENSE_ALREADY_EXISTS`." —
    with a freshly observed machine version the OCC guard passes and the
    uniqueness rule is what fires.

    Design: Corner/validations/license_duplicate_feature_rejected
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    purchase_license(ctx, api, machine["id"], feature_code="AUTO_GUIDANCE")

    version = read_machine(ctx, api, machine["id"])["version"]
    payload = create_feature_license_payload(
        machine["id"], version, feature_code="AUTO_GUIDANCE",
        license_type="PERPETUAL",
    )
    response = api.create_feature_license(payload, headers=ctx["grower_headers"])
    error = validate_error(response, ApiErrorId.ERR_LICENSE_ALREADY_EXISTS)
    assert error["error_id"] != "ERR_STALE_MACHINE_VERSION"

    rows, _meta = validate_paginated(
        api.list_feature_licenses(
            headers=ctx["grower_headers"], params={"machine_id": machine["id"]}
        )
    )
    assert len(rows) == 1


def test_occ_stale_machine_version_on_license_purchase(api):
    """PRD section 2.8: "Purchasing a feature license requires
    `expected_machine_version`, carrying the client's last observed `version`
    of the machine; a mismatch is rejected with `ERR_STALE_MACHINE_VERSION`
    (HTTP 412), because license provisioning mutates the machine's
    configuration and a prior purchase advances its version."

    Design: Corner/cross_cutting/occ_stale_machine_version_on_license_purchase
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    version = read_machine(ctx, api, machine["id"])["version"]
    purchase_license(ctx, api, machine["id"], feature_code="AUTO_GUIDANCE",
                     expected_machine_version=version)

    payload = create_feature_license_payload(
        machine["id"], version, feature_code="SECTION_CONTROL",
        license_type="PERPETUAL",
    )
    response = api.create_feature_license(payload, headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_STALE_MACHINE_VERSION)

    machine = read_machine(ctx, api, machine["id"])
    assert machine["active_license_count"] == 1


def test_license_bundle_fee_evaluation_order(api):
    """PRD section 3.7: "First, count the machine's existing licenses in
    `PURCHASED`, `ACTIVATED`, or `SUSPENDED`, plus the new license itself; call
    that n. Second, the bundle discount is 0.00 when n is 1, 0.10 when n is 2,
    and 0.20 when n is 3 or more. Third, the base fee is read from the feature
    table: `AUTO_GUIDANCE` 120000 cents, `SECTION_CONTROL` 180000 cents,
    `VARIABLE_RATE_SPREAD` 90000 cents, `TELEMATICS_PREMIUM` 60000 cents."

    Design: Difficulty/combinatorial_formula/license_bundle_fee_evaluation_order
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    machine_id = machine["id"]

    lic1 = purchase_license(ctx, api, machine_id, feature_code="AUTO_GUIDANCE")
    assert lic1["fee_cents"] == 120000
    lic2 = purchase_license(ctx, api, machine_id, feature_code="SECTION_CONTROL")
    assert lic2["fee_cents"] == 162000
    lic3 = purchase_license(
        ctx, api, machine_id, feature_code="VARIABLE_RATE_SPREAD",
        license_type="TERM", term_months=12,
    )
    assert lic3["fee_cents"] == 72000


def test_license_bundle_purchases_increment_machine_version(api):
    """PRD section 2.11: "purchasing a feature license increments the target
    machine's `version`" and PRD section 3.7: "`active_license_count` ...
    counts exactly the machine's licenses in `PURCHASED`, `ACTIVATED`, or
    `SUSPENDED`". Three purchases move a fresh machine to version 4 with count
    3.

    Design: Difficulty/combinatorial_formula/license_bundle_fee_evaluation_order
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    machine_id = machine["id"]

    purchase_license(ctx, api, machine_id, feature_code="AUTO_GUIDANCE")
    purchase_license(ctx, api, machine_id, feature_code="SECTION_CONTROL")
    purchase_license(ctx, api, machine_id,
                     feature_code="VARIABLE_RATE_SPREAD",
                     license_type="TERM", term_months=12)

    machine = read_machine(ctx, api, machine_id)
    assert machine["active_license_count"] == 3
    assert machine["version"] == 4


def test_license_purchase_increments_active_count(api):
    """PRD section 3.7: "Every one of these transitions recomputes the
    machine's `active_license_count`, which counts exactly the machine's
    licenses in `PURCHASED`, `ACTIVATED`, or `SUSPENDED` — `EXPIRED` and
    `REVOKED` licenses drop out."

    Design: Difficulty/compensating_invariant/machine_license_count_purchase_revoke_roundtrip
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    assert machine["active_license_count"] == 0

    purchase_license(ctx, api, machine["id"],
                     feature_code="TELEMATICS_PREMIUM")
    machine = read_machine(ctx, api, machine["id"])
    assert machine["active_license_count"] == 1


def test_license_revoke_compensates_active_count(api):
    """PRD section 3.7: "A `PlatformAdmin` may suspend an `ACTIVATED` license
    ... or revoke any license in `PURCHASED`, `ACTIVATED`, or `SUSPENDED` to
    terminal `REVOKED`" — paired with the purchase, the revoke returns the
    machine's `active_license_count` to exactly 0.

    Design: Difficulty/compensating_invariant/machine_license_count_purchase_revoke_roundtrip
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    license = purchase_license(ctx, api, machine["id"],
                               feature_code="TELEMATICS_PREMIUM")

    revoke_license(api, license["id"])
    license = read_license(ctx, api, license["id"])
    assert license["status"] == "REVOKED"
    machine = read_machine(ctx, api, machine["id"])
    assert machine["active_license_count"] == 0
