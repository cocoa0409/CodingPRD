"""Layer-inspection disposition rules and the repair/re-inspect loop (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    PRINT_OP,
    QUALITY_INSP,
    assert_layer_inspection,
    create_layer_inspection_payload,
    create_printing_job,
    get_success_data,
    set_clock,
    setup_site_ready_for_print,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_quality_inspector_headers

QI_SECOND = make_quality_inspector_headers("qi-second")


def _printing_ctx(api, code):
    ctx = setup_site_ready_for_print(jurisdiction_code=code)
    job = create_printing_job(ctx)
    return ctx, job


def test_layer_inspection_repair_reinspect_cycle(api):
    """PRD §3.8: "Repairs are verified by re-inspection: recording a new
    inspection whose `supersedes_inspection_id` points to a `REPAIR_REQUIRED`
    inspection and whose layer range overlaps the earlier range leaves the old
    inspection at `REPAIR_REQUIRED` while the new one enters `PENDING`."

    Design: Difficulty/non_linear_state_machine/layer_inspection_repair_reinspect_cycle
    """
    ctx, job = _printing_ctx(api, "JL")
    site_id = ctx["site"]["id"]
    bad = get_success_data(
        api.create_layer_inspection(
            site_id,
            job["id"],
            create_layer_inspection_payload(
                layer_index_start=1, layer_index_end=5,
                bond_strength_mpa=1.0, dimensional_deviation_mm=4,
            ),
            QUALITY_INSP,
        )
    )
    assert bad["outcome"] == "FAIL_BOND"
    get_success_data(
        api.disposition_layer_inspection(
            site_id, job["id"], bad["id"], {"disposition": "REPAIR_REQUIRED"}, QI_SECOND
        )
    )
    new = validate_success(
        api.create_layer_inspection(
            site_id,
            job["id"],
            create_layer_inspection_payload(
                layer_index_start=1, layer_index_end=5,
                bond_strength_mpa=2.0, dimensional_deviation_mm=4,
                supersedes_inspection_id=bad["id"],
            ),
            QUALITY_INSP,
        ),
        201,
    )
    assert new["disposition"] == "PENDING"
    assert new["outcome"] == "PASS"
    inspections, _m = validate_paginated(
        api.list_layer_inspections(site_id, job["id"], QUALITY_INSP)
    )
    old = next(i for i in inspections if i["id"] == bad["id"])
    assert old["disposition"] == "REPAIR_REQUIRED", "old inspection stays REPAIR_REQUIRED"


def test_layers_printed_not_incremented_on_reinspection(api):
    """PRD §3.8: "the parent job's `layers_printed` is incremented by the band's
    layer count (end minus start plus one) only when the outcome is `PASS` and
    the inspection is not a re-inspection."

    Design: Difficulty/non_linear_state_machine/layer_inspection_repair_reinspect_cycle
    """
    ctx, job = _printing_ctx(api, "JL2")
    site_id = ctx["site"]["id"]
    bad = get_success_data(
        api.create_layer_inspection(
            site_id,
            job["id"],
            create_layer_inspection_payload(
                layer_index_start=1, layer_index_end=5,
                bond_strength_mpa=1.0, dimensional_deviation_mm=4,
            ),
            QUALITY_INSP,
        )
    )
    get_success_data(
        api.disposition_layer_inspection(
            site_id, job["id"], bad["id"], {"disposition": "REPAIR_REQUIRED"}, QI_SECOND
        )
    )
    get_success_data(
        api.create_layer_inspection(
            site_id,
            job["id"],
            create_layer_inspection_payload(
                layer_index_start=1, layer_index_end=5,
                bond_strength_mpa=2.0, dimensional_deviation_mm=4,
                supersedes_inspection_id=bad["id"],
            ),
            QUALITY_INSP,
        )
    )
    jobs, _m = validate_paginated(api.list_print_jobs(site_id, PRINT_OP))
    current = next(j for j in jobs if j["id"] == job["id"])
    assert current["layers_printed"] == 0, (
        "the failing first inspection and the passing re-inspection both leave "
        "layers_printed at 0"
    )


def test_layer_inspection_invalid_outcome_enum_rejected(api):
    """PRD §2.11 item 14: "required fields present and
    well-formed (`ERR_INVALID_REQUEST`)." PRD §3.8 defines the disposition
    vocabulary as `PENDING`/`ACCEPTED`/`REPAIR_REQUIRED`/`DEMOLISH_REQUIRED`.

    Design: Corner/entities/layer_inspection_invalid_outcome_enum_rejected
    """
    ctx, job = _printing_ctx(api, "JA6")
    site_id = ctx["site"]["id"]
    insp = get_success_data(
        api.create_layer_inspection(
            site_id,
            job["id"],
            create_layer_inspection_payload(),
            QUALITY_INSP,
        )
    )
    resp = api.disposition_layer_inspection(
        site_id, job["id"], insp["id"], {"disposition": "UNKNOWN_ENUM"}, QI_SECOND
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_disposition_missing_field_rejected(api):
    """PRD §2.11 item 14: "required fields present and
    well-formed (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/layer_inspection_invalid_outcome_enum_rejected
    """
    ctx, job = _printing_ctx(api, "JA6B")
    site_id = ctx["site"]["id"]
    insp = get_success_data(
        api.create_layer_inspection(
            site_id, job["id"], create_layer_inspection_payload(), QUALITY_INSP
        )
    )
    resp = api.disposition_layer_inspection(site_id, job["id"], insp["id"], {}, QI_SECOND)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_derived_posture_recomputed_on_demolish_required(api):
    """PRD §2.10 rule 2: "If any `LayerInspection` on any print job of the site
    has `disposition` `DEMOLISH_REQUIRED`, posture is `STOP`." PRD §3.8: "It
    may be moved to `DEMOLISH_REQUIRED` only when the outcome is exactly
    `FAIL_BOTH`; that disposition forces the site's posture to `STOP`."

    Design: Corner/cross_cutting_complexity_layers/derived_posture_recomputed_on_demolish_required
    """
    ctx, job = _printing_ctx(api, "JJ")
    site_id = ctx["site"]["id"]
    site_before = get_success_data(api.get_site(site_id, PRINT_OP))
    assert site_before["posture"] == "OPERATING"
    insp = get_success_data(
        api.create_layer_inspection(
            site_id,
            job["id"],
            create_layer_inspection_payload(
                layer_index_start=1, layer_index_end=5,
                bond_strength_mpa=1.0, dimensional_deviation_mm=10,
            ),
            QUALITY_INSP,
        )
    )
    assert insp["outcome"] == "FAIL_BOTH"
    disposed = validate_success(
        api.disposition_layer_inspection(
            site_id, job["id"], insp["id"], {"disposition": "DEMOLISH_REQUIRED"}, QI_SECOND
        )
    )
    assert disposed["disposition"] == "DEMOLISH_REQUIRED"
    site_after = get_success_data(api.get_site(site_id, PRINT_OP))
    assert site_after["posture"] == "STOP"


def test_repair_required_contributes_precautionary_posture(api):
    """PRD §2.10 rule 5: "If any `LayerInspection` on the site has `disposition`
    `REPAIR_REQUIRED`, posture is `PRECAUTIONARY`." PRD §3.8: "It may be moved
    to `REPAIR_REQUIRED` whenever the outcome is not `PASS`, which recomputes
    the site's posture (a `REPAIR_REQUIRED` inspection contributes to
    `PRECAUTIONARY`)."

    Design: Corner/cross_cutting_complexity_layers/derived_posture_recomputed_on_demolish_required
    """
    ctx, job = _printing_ctx(api, "JJ2")
    site_id = ctx["site"]["id"]
    insp = get_success_data(
        api.create_layer_inspection(
            site_id,
            job["id"],
            create_layer_inspection_payload(
                layer_index_start=1, layer_index_end=5,
                bond_strength_mpa=1.0, dimensional_deviation_mm=4,
            ),
            QUALITY_INSP,
        )
    )
    assert insp["outcome"] == "FAIL_BOND"
    get_success_data(
        api.disposition_layer_inspection(
            site_id, job["id"], insp["id"], {"disposition": "REPAIR_REQUIRED"}, QI_SECOND
        )
    )
    site_after = get_success_data(api.get_site(site_id, PRINT_OP))
    assert site_after["posture"] == "PRECAUTIONARY"
