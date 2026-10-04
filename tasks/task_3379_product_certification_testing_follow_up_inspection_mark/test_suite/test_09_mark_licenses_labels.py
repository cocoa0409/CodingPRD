"""Mark licenses, label batches, and serial traceability.

Covers the dual quota variants (STANDARD_QUOTA vs PROBATION_QUOTA), sequential
serial-range allocation, the exact-fit quota boundary, the state-versus-quota
error priority on an EXHAUSTED license, the void compensating invariant
(quota restored, serials never rewound), and terminal lockdown of voided
batches.
"""

from test_helpers import (
    ApiErrorId,
    SECOND_ENGINEER_ID,
    create_factory,
    create_manufacturer,
    create_mark_license,
    drive_factory_to_probation,
    expected_serial_prefix,
    issue_label_batch,
    label_batch_payload,
    make_manufacturer_rep_headers,
    refresh_certification,
    refresh_factory,
    refresh_mark_license,
    setup_certified,
    setup_certified_with_license,
    setup_probation_certified_with_license,
    validate_error,
    void_label_batch,
    void_label_batch_payload,
)


def _two_factories_one_probation(api):
    """Two SMALL manufacturers with certifications on the same standard; the
    second factory is driven to PROBATION by a factory-level CRITICAL finding
    that names no certification (so its certification stays ACTIVE)."""
    ctx_one = setup_certified(api)
    mfr_two = create_manufacturer(
        api, legal_name="Beacon Power Co", annual_revenue_tier="SMALL"
    )
    fac_two = create_factory(
        api,
        mfr_two["id"],
        site_code="GZ-1",
        country_code="CN",
        jurisdiction_code="CN-GZ",
    )
    ctx_two = setup_certified(
        api,
        {"standard": ctx_one["standard"], "manufacturer": mfr_two, "factory": fac_two},
        project_overrides={"product_model": "BP-9"},
        engineer_id=SECOND_ENGINEER_ID,
    )
    drive_factory_to_probation(api, fac_two["id"])
    return ctx_one, ctx_two


def test_serial_range_allocation_sequential_across_batches(api):
    """PRD §3.7: "The batch's `serial_start` is the license's `next_serial` at
    that instant, and its `serial_end` is `serial_start` plus `quantity` minus
    one. The license's `next_serial` then advances by `quantity` and its
    `used_quantity` increases by `quantity`; when `used_quantity` reaches
    `authorized_quantity`, the license becomes `EXHAUSTED` automatically."
    PRD §3.7: "The license is minted with a `serial_prefix` — the
    certification's `listing_number`, followed by a hyphen, followed by the
    first letter of the `label_type` — with `used_quantity` at zero,
    `next_serial` at 1, and `status` `ACTIVE`, all tied to the certification
    through `certification_id`."

    Design: Corner/calculations/serial_range_allocation_sequential_across_batches
    """
    ctx = setup_certified_with_license(api, label_type="HOLOGRAM")
    lic_id = ctx["mark_license"]["id"]
    mfr_id = ctx["manufacturer"]["id"]

    first = issue_label_batch(api, lic_id, mfr_id, 100)
    second = issue_label_batch(api, lic_id, mfr_id, 250)
    assert first["serial_start"] == 1
    assert first["serial_end"] == 100
    assert second["serial_start"] == 101
    assert second["serial_end"] == 350

    license_view = refresh_mark_license(api, lic_id)
    assert license_view["used_quantity"] == 350
    assert license_view["next_serial"] == 351
    assert license_view["status"] == "ACTIVE"
    assert license_view["serial_prefix"] == expected_serial_prefix(
        ctx["certification"]["listing_number"], "HOLOGRAM"
    )


def test_label_batch_zero_quantity_returns_invalid_request(api):
    """PRD §3.7: "A `quantity` below 1 is rejected with
    `ERR_INVALID_LABEL_QUANTITY` (HTTP 400)."

    Design: Corner/validations/label_batch_zero_quantity_returns_invalid_request
    """
    ctx = setup_certified_with_license(api)
    lic_id = ctx["mark_license"]["id"]
    response = api.issue_label_batch(
        lic_id,
        label_batch_payload(0),
        make_manufacturer_rep_headers(ctx["manufacturer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_LABEL_QUANTITY)
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["used_quantity"] == 0
    assert license_view["next_serial"] == 1, "a rejected batch consumes no serials"


def test_label_batch_void_twice_second_returns_already_terminal(api):
    """PRD §3.7: "The batch becomes `VOIDED`, which is terminal, and the
    license's `used_quantity` falls by the batch's `quantity` — `used_quantity`
    always equals the sum of `quantity` over the license's `ISSUED`
    (non-`VOIDED`) batches."
    PRD §2.8: "an entity already in a terminal state — `REJECTED`, `WITHDRAWN`,
    `EXPIRED`, `VOIDED`, `IMPLEMENTED`, or `EVALUATED_FAIL` — rejects all
    further transitions with `ERR_ALREADY_TERMINAL`"

    Design: Corner/state_machines/label_batch_void_twice_second_returns_already_terminal
    """
    ctx = setup_certified_with_license(api)
    lic_id = ctx["mark_license"]["id"]
    mfr_id = ctx["manufacturer"]["id"]
    batch = issue_label_batch(api, lic_id, mfr_id, 100)
    void_label_batch(api, batch["id"], mfr_id, reason="Print defect")

    second = api.void_label_batch(
        batch["id"],
        void_label_batch_payload("Duplicate void attempt"),
        make_manufacturer_rep_headers(mfr_id),
    )
    validate_error(second, ApiErrorId.ERR_ALREADY_TERMINAL)
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["used_quantity"] == 0, "the quota is credited exactly once"


def test_label_batch_exact_fit_allowed_over_by_one_rejected(api):
    """PRD §3.7: "The remaining quota is the `authorized_quantity` minus the
    `used_quantity`; a `quantity` that exceeds the remainder is rejected with
    `ERR_LABEL_QUOTA_EXCEEDED`, while an exact fit, where the `quantity` equals
    the remainder, is allowed."
    PRD §3.7: "when `used_quantity` reaches `authorized_quantity`, the license
    becomes `EXHAUSTED` automatically."

    Design: Difficulty/boundary_precision_check/label_batch_exact_fit_allowed_over_by_one_rejected
    """
    ctx = setup_probation_certified_with_license(api)  # authorized_quantity 500
    lic_id = ctx["mark_license"]["id"]
    mfr_id = ctx["manufacturer"]["id"]
    issue_label_batch(api, lic_id, mfr_id, 499)

    over = api.issue_label_batch(
        lic_id, label_batch_payload(2), make_manufacturer_rep_headers(mfr_id)
    )
    validate_error(over, ApiErrorId.ERR_LABEL_QUOTA_EXCEEDED)

    exact = issue_label_batch(api, lic_id, mfr_id, 1)
    assert exact["serial_start"] == 500
    assert exact["serial_end"] == 500
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["used_quantity"] == 500
    assert license_view["status"] == "EXHAUSTED"


def test_label_batch_exact_fit_boundary_intermediate_state(api):
    """PRD §3.7: "The remaining quota is the `authorized_quantity` minus the
    `used_quantity`; a `quantity` that exceeds the remainder is rejected with
    `ERR_LABEL_QUOTA_EXCEEDED`, while an exact fit, where the `quantity` equals
    the remainder, is allowed."

    Design: Difficulty/boundary_precision_check/label_batch_exact_fit_allowed_over_by_one_rejected
    """
    ctx = setup_probation_certified_with_license(api)  # authorized_quantity 500
    lic_id = ctx["mark_license"]["id"]
    mfr_id = ctx["manufacturer"]["id"]

    first = issue_label_batch(api, lic_id, mfr_id, 499)
    assert first["serial_start"] == 1
    assert first["serial_end"] == 499
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["used_quantity"] == 499
    assert license_view["status"] == "ACTIVE", (
        "one unit of headroom remains, so the license is not yet EXHAUSTED"
    )

    exact = issue_label_batch(api, lic_id, mfr_id, 1)
    assert exact["serial_start"] == 500
    assert exact["serial_end"] == 500


def test_batch_on_exhausted_license_state_error_wins_over_quota(api):
    """PRD §2.8: "Every request is validated against an ordered pipeline, and a
    failure at an earlier stage produces that stage's error rather than a later
    stage's."
    PRD §2.8: "label batch issuance requires an `ACTIVE` license
    (`ERR_LICENSE_NOT_ACTIVE`)"
    PRD §2.8: "a label batch's `quantity` must be at least 1
    (`ERR_INVALID_LABEL_QUANTITY`, HTTP 400) and must fit the license's
    remaining quota (`ERR_LABEL_QUOTA_EXCEEDED`, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/label_batch_on_exhausted_license_state_error_wins_over_quota
    """
    ctx = setup_certified_with_license(api)  # STANDARD_QUOTA, authorized 11000
    lic_id = ctx["mark_license"]["id"]
    mfr_id = ctx["manufacturer"]["id"]
    issue_label_batch(api, lic_id, mfr_id, 11000)  # exact fit -> EXHAUSTED

    # Quantity 1 violates both the state rule (license EXHAUSTED, stage 6) and
    # the quota rule (remaining 0, stage 11); the state error fires first.
    blocked = api.issue_label_batch(
        lic_id, label_batch_payload(1), make_manufacturer_rep_headers(mfr_id)
    )
    validate_error(blocked, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)


def test_rejected_batch_leaves_exhausted_license_untouched(api):
    """PRD §3.7: "when `used_quantity` reaches `authorized_quantity`, the
    license becomes `EXHAUSTED` automatically."
    PRD §2.8: "Every request is validated against an ordered pipeline, and a
    failure at an earlier stage produces that stage's error rather than a later
    stage's."

    Design: Difficulty/priority_pair_validation_conflict/label_batch_on_exhausted_license_state_error_wins_over_quota
    """
    ctx = setup_certified_with_license(api)  # STANDARD_QUOTA, authorized 11000
    lic_id = ctx["mark_license"]["id"]
    mfr_id = ctx["manufacturer"]["id"]
    issue_label_batch(api, lic_id, mfr_id, 11000)

    blocked = api.issue_label_batch(
        lic_id, label_batch_payload(1), make_manufacturer_rep_headers(mfr_id)
    )
    validate_error(blocked, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["used_quantity"] == 11000
    assert license_view["status"] == "EXHAUSTED", (
        "a rejected issuance mutates nothing"
    )


def test_void_restores_quota_and_reopens_exhausted_license(api):
    """PRD §3.7: "The batch becomes `VOIDED`, which is terminal, and the
    license's `used_quantity` falls by the batch's `quantity` — `used_quantity`
    always equals the sum of `quantity` over the license's `ISSUED`
    (non-`VOIDED`) batches. The license's `next_serial` is never rewound:
    serials are never reused, and a voided range is simply skipped. If the
    license was `EXHAUSTED` and is neither `SUSPENDED` nor `REVOKED`, it returns
    automatically to `ACTIVE` once the void drops usage below the
    authorization."

    Design: Difficulty/compensating_invariant/label_batch_void_restores_quota_without_serial_rewind
    """
    ctx = setup_probation_certified_with_license(api)  # authorized_quantity 500
    lic_id = ctx["mark_license"]["id"]
    mfr_id = ctx["manufacturer"]["id"]
    first = issue_label_batch(api, lic_id, mfr_id, 300)  # serials 1..300
    issue_label_batch(api, lic_id, mfr_id, 200)  # serials 301..500 -> EXHAUSTED
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["used_quantity"] == 500
    assert license_view["status"] == "EXHAUSTED"

    void_label_batch(api, first["id"], mfr_id, reason="Print defect on roll")
    license_view = refresh_mark_license(api, lic_id)
    assert license_view["used_quantity"] == 200
    assert license_view["status"] == "ACTIVE", "the void reopens the license"
    assert license_view["next_serial"] == 501, "voids never rewind serials"


def test_voided_serials_never_reused(api):
    """PRD §3.7: "The license's `next_serial` is never rewound: serials are
    never reused, and a voided range is simply skipped."
    PRD §3.7: "The batch's `serial_start` is the license's `next_serial` at that
    instant, and its `serial_end` is `serial_start` plus `quantity` minus one."

    Design: Difficulty/compensating_invariant/label_batch_void_restores_quota_without_serial_rewind
    """
    ctx = setup_probation_certified_with_license(api)  # authorized_quantity 500
    lic_id = ctx["mark_license"]["id"]
    mfr_id = ctx["manufacturer"]["id"]
    first = issue_label_batch(api, lic_id, mfr_id, 300)
    issue_label_batch(api, lic_id, mfr_id, 200)
    void_label_batch(api, first["id"], mfr_id, reason="Print defect on roll")

    third = issue_label_batch(api, lic_id, mfr_id, 300)
    assert third["serial_start"] == 501, "the voided 1..300 range is skipped"
    assert third["serial_end"] == 800
    license_view = refresh_mark_license(api, lic_id)
    # used_quantity again equals the sum over ISSUED batches: 200 + 300.
    assert license_view["used_quantity"] == 500
    assert license_view["status"] == "EXHAUSTED"


def test_quota_variants_diverge_standard_vs_probation(api):
    """PRD §3.7: "At creation the system selects the license's `quota_variant`
    from the conformity regime of the certification's factory at that moment —
    `STANDARD_QUOTA` for a `STANDARD` factory, `PROBATION_QUOTA` for a
    `PROBATION` factory — and computes the `authorized_quantity`. Under
    `STANDARD_QUOTA`, the raw authorization is the `declared_annual_volume`
    multiplied by 1.10, rounded down to a whole number and capped at 100,000.
    Under `PROBATION_QUOTA`, the raw authorization is the
    `declared_annual_volume` multiplied by 0.25, rounded down to a whole number
    and hard-capped at 500 — an identical declared volume yields a far smaller
    authorization under probation."

    Design: Difficulty/dual_variant_calc/label_quota_standard_vs_probation_regimes_diverge
    """
    ctx_one, ctx_two = _two_factories_one_probation(api)
    lic_standard = create_mark_license(
        api,
        ctx_one["certification"]["id"],
        ctx_one["manufacturer"]["id"],
        label_type="STANDARD",
        declared_annual_volume=10000,
    )
    lic_probation = create_mark_license(
        api,
        ctx_two["certification"]["id"],
        ctx_two["manufacturer"]["id"],
        label_type="STANDARD",
        declared_annual_volume=10000,
    )
    # Identical volume: floor(10000 * 1.10) = 11000 vs min(floor(10000 * 0.25),
    # 500) = 500 (both are already whole lots of 100).
    assert lic_standard["quota_variant"] == "STANDARD_QUOTA"
    assert lic_standard["authorized_quantity"] == 11000
    assert lic_probation["quota_variant"] == "PROBATION_QUOTA"
    assert lic_probation["authorized_quantity"] == 500
    assert lic_standard["status"] == "ACTIVE"
    assert lic_probation["status"] == "ACTIVE"


def test_probation_license_minting_fields_and_factory_state(api):
    """PRD §3.7: "The license is minted with a `serial_prefix` — the
    certification's `listing_number`, followed by a hyphen, followed by the
    first letter of the `label_type` — with `used_quantity` at zero,
    `next_serial` at 1, and `status` `ACTIVE`, all tied to the certification
    through `certification_id`."
    PRD §3.6: "Every `CRITICAL` finding that names a certification also suspends
    that certification, if it is `ACTIVE`"

    Design: Difficulty/dual_variant_calc/label_quota_standard_vs_probation_regimes_diverge
    """
    ctx_one, ctx_two = _two_factories_one_probation(api)
    # The factory-level finding named no certification, so no suspension
    # cascade reached the second certification.
    certification_two = refresh_certification(api, ctx_two["certification"]["id"])
    assert certification_two["status"] == "ACTIVE"
    factory_two = refresh_factory(api, ctx_two["factory"]["id"])
    assert factory_two["conformity_regime"] == "PROBATION"
    assert factory_two["conformity_score"] == 60

    lic_probation = create_mark_license(
        api,
        ctx_two["certification"]["id"],
        ctx_two["manufacturer"]["id"],
        label_type="STANDARD",
        declared_annual_volume=10000,
    )
    assert lic_probation["quota_variant"] == "PROBATION_QUOTA"
    assert lic_probation["authorized_quantity"] == 500
    assert lic_probation["used_quantity"] == 0
    assert lic_probation["next_serial"] == 1
    assert lic_probation["serial_prefix"] == expected_serial_prefix(
        ctx_two["certification"]["listing_number"], "STANDARD"
    )
    assert lic_probation["certification_id"] == ctx_two["certification"]["id"]
