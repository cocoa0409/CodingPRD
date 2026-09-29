"""Breadth coverage of the validation ladder's ordering: when one request violates several
rungs at once, exactly one of them is allowed to answer.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_instant_equals
from test_helpers.constants import ROLE_PLANT_ADMIN, ROLE_QUALITY_MANAGER
from test_helpers.test_users import (
    ADMIN1_ID,
    ADMIN_HEADERS,
    ENGINEER_HEADERS,
    LAB1_ID,
    QUALITY_HEADERS,
    headers_missing_role,
    headers_missing_user_id,
    make_headers,
)

BLANK_HEADERS = {"X-User-ID": "", "X-User-Role": "", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# validations: rung 10 answers before rung 30
# ---------------------------------------------------------------------------
def test_blank_credentials_are_answered_before_the_unknown_path_id_is_resolved(api):
    """Both headers arrive as empty strings against a plant id nobody ever registered, and the
    authentication rung answers first: an anonymous caller learns nothing about which ids
    exist. The very same call under real PlantAdmin credentials walks two rungs further and
    reports the 404.

    PRD: "For any request, the implementation walks the validation rules whose scope matches
    that request in ascending priority order and returns the **first** violated rule's error."

    Design: Corner/validations/blank_auth_headers_beat_a_nonexistent_path_id_unauthenticated
    """
    body = validate_error(
        api.get_plant(NON_EXISTENT_UUID, BLANK_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    for leaked in ("id", "name", "region_code", "permit_nox_kg_per_tonne_clinker_cap"):
        assert leaked not in body, f"the 401 body leaks {leaked}"

    validate_error(
        api.get_plant(NON_EXISTENT_UUID, ADMIN_HEADERS),
        ApiErrorId.ERR_PLANT_NOT_FOUND.value,
        404,
    )


def test_an_empty_header_string_counts_as_an_absent_header(api):
    """A blank id, a blank role and a blank pair are all unauthenticated, on a plant that
    really exists exactly as on one that does not.

    PRD: "On every endpoint: both `X-User-ID` and `X-User-Role` present and non-empty, else
    `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/validations/blank_auth_headers_beat_a_nonexistent_path_id_unauthenticated
    """
    plant = fx.create_plant(api)

    for headers in (
        BLANK_HEADERS,
        headers_missing_user_id(ROLE_PLANT_ADMIN),
        headers_missing_role(ADMIN1_ID),
    ):
        validate_error(
            api.get_plant(plant["id"], headers),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api.get_plant(NON_EXISTENT_UUID, headers),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )

    readable = validate_success(api.get_plant(plant["id"], ADMIN_HEADERS))
    assert readable["id"] == plant["id"]


# ---------------------------------------------------------------------------
# validations: rung 30 answers before rung 40
# ---------------------------------------------------------------------------
def test_an_unknown_silo_id_is_reported_before_the_payloads_bad_enum(api):
    """MELTED is not a silo status and the path id resolves to nothing, so the two defects
    race: the path rung wins and the answer names the missing row, not the malformed body.

    PRD: "On every endpoint carrying a path identifier: the identifier resolves to an existing
    row of the expected entity, else that entity's own not-found error (404)."

    Design: Corner/validations/unknown_path_id_beats_an_invalid_payload_not_found
    """
    plant = fx.create_plant(api)
    silo = fx.create_clinker_silo(api, plant["id"])
    assert silo["status"] == "OPEN"

    validate_error(
        api.patch_silo(NON_EXISTENT_UUID, {"status": "MELTED"}, ADMIN_HEADERS),
        ApiErrorId.ERR_SILO_NOT_FOUND.value,
        404,
    )

    untouched = validate_success(api.get_silo(silo["id"], ADMIN_HEADERS))
    assert untouched["status"] == "OPEN"
    assert untouched["version"] == silo["version"]


def test_the_same_bad_enum_against_a_real_silo_is_a_shape_error(api):
    """Once the path resolves, the shape rung finally gets its turn on the identical payload:
    400 rather than 404, and the silo is left OPEN at the version it started from.

    PRD: "On every write endpoint: required fields present; numeric fields numeric, and
    non-negative wherever the field is a tonnage, a percentage or an energy; enum fields drawn
    from their declared value sets; datetime fields parseable as ISO 8601 UTC; array fields
    actually arrays; `gypsum_pct` between 2.00 and 7.00 inclusive; `blaine_target_m2_per_kg`
    inside the cement type's Blaine band; `as_of_month` between 1 and 12 inclusive."

    Design: Corner/validations/unknown_path_id_beats_an_invalid_payload_not_found
    """
    plant = fx.create_plant(api)
    silo = fx.create_clinker_silo(api, plant["id"])

    validate_error(
        api.patch_silo(silo["id"], {"status": "MELTED"}, ADMIN_HEADERS),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    unchanged = validate_success(api.get_silo(silo["id"], ADMIN_HEADERS))
    assert unchanged["status"] == "OPEN"
    assert unchanged["block_reason"] is None
    assert unchanged["version"] == silo["version"]

    # The legal member of the same enum is accepted on the same field.
    blocked = validate_success(
        api.patch_silo(
            silo["id"],
            {"status": "BLOCKED", "block_reason": "SILO_INSPECTION"},
            ADMIN_HEADERS,
        )
    )
    assert blocked["status"] == "BLOCKED"


# ---------------------------------------------------------------------------
# validations: rung 50 answers before rung 62
# ---------------------------------------------------------------------------
def _blocked_silo_after_a_release(api):
    """583.78 released tonnes in SC1, its version read by the caller, and then a PlantAdmin
    block that both shuts the silo and moves the version the caller is holding."""
    env = fx.released_clinker_environment(api)
    stale = validate_success(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))
    assert stale["status"] == "OPEN"
    assert_amount(stale["tonnes_on_hand"], 583.78, "tonnes_on_hand")
    assert_amount(stale["available_tonnes"], 583.78, "available_tonnes")

    blocked = validate_success(
        api.patch_silo(
            env["clinker_silo"]["id"],
            {"status": "BLOCKED", "block_reason": "SILO_INSPECTION"},
            ADMIN_HEADERS,
        )
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["version"] > stale["version"], "a status change must move the version"
    return env, stale


def _draw_payload(api, env, expected_version):
    return f.cement_batch_payload(
        env["plant_id"],
        env["clinker_silo"]["id"],
        env["cement_silo"]["id"],
        expected_version,
    )


def test_a_blocked_silo_answers_the_stale_read_before_it_answers_the_block(api):
    """One PlantAdmin action created both defects at once, and the caller is told to re-read
    rather than told the silo is shut: 412, not 409. Nothing is reserved on the way out.

    PRD: "If the silo's current `version` differs, the create is refused with
    `ERR_STALE_SILO_VERSION`."

    Design: Corner/validations/stale_silo_version_priority_50_beats_silo_blocked_priority_62
    """
    env, stale = _blocked_silo_after_a_release(api)

    validate_error(
        api.create_cement_batch(
            _draw_payload(api, env, stale["version"]), ENGINEER_HEADERS
        ),
        ApiErrorId.ERR_STALE_SILO_VERSION.value,
        412,
    )

    _rows, meta = validate_paginated(
        api.list_cement_batches(ENGINEER_HEADERS, params={"plant_id": env["plant_id"]})
    )
    assert meta["total_count"] == 0

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))
    assert_amount(silo["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(silo["available_tonnes"], 583.78, "available_tonnes")
    assert_amount(silo["tonnes_on_hand"], 583.78, "tonnes_on_hand")


def test_retrying_with_the_current_version_falls_through_to_the_blocked_gate(api):
    """Obeying the 412 and re-reading does not get the batch made: the next rung down is
    waiting with the reason the first answer withheld.

    PRD: "Every silo the operation touches is `OPEN`, else `ERR_SILO_BLOCKED` (409)."

    Design: Corner/validations/stale_silo_version_priority_50_beats_silo_blocked_priority_62
    """
    env, _stale = _blocked_silo_after_a_release(api)

    current = validate_success(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))
    assert current["status"] == "BLOCKED"

    validate_error(
        api.create_cement_batch(
            _draw_payload(api, env, current["version"]), ENGINEER_HEADERS
        ),
        ApiErrorId.ERR_SILO_BLOCKED.value,
        409,
    )

    _rows, meta = validate_paginated(
        api.list_cement_batches(ENGINEER_HEADERS, params={"plant_id": env["plant_id"]})
    )
    assert meta["total_count"] == 0

    silo = validate_success(api.get_silo(env["clinker_silo"]["id"], ENGINEER_HEADERS))
    assert_amount(silo["reserved_tonnes"], 0.00, "reserved_tonnes")
    assert_amount(silo["available_tonnes"], 583.78, "available_tonnes")


# ---------------------------------------------------------------------------
# validations: rung 55 answers before rung 60
# ---------------------------------------------------------------------------
def test_the_strength_recorder_is_refused_before_the_certificates_state_gate(api):
    """The retry comes from the very technician who measured the 28-day strength, now wearing a
    QualityManager role, against a certificate that has already been issued. Both rungs are
    violated and the governance one answers: 403, not 409 — and the certificate keeps the
    original issuer and instant.

    PRD: "The issuing `X-User-ID` must differ from the `recorded_by_user_id` of the batch's
    newest 28-day strength test, else `ERR_SEGREGATION_OF_DUTIES` — the person who measured the
    strength may not certify against it."

    Design: Corner/validations/segregation_priority_55_beats_certificate_state_priority_60
    """
    env = fx.qualified_cement_environment(api, strength_value=30.0)
    batch_id = env["batch"]["id"]

    rows, meta = validate_paginated(
        api.list_lab_tests(
            QUALITY_HEADERS,
            params={
                "cement_batch_id": batch_id,
                "test_type": "COMPRESSIVE_STRENGTH_28D",
            },
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["recorded_by_user_id"] == LAB1_ID

    customer = fx.create_customer(api)
    draft = fx.create_draft_certificate(api, batch_id, customer["id"], 574.72)

    issued = validate_success(api.issue_mill_certificate(draft["id"], QUALITY_HEADERS))
    assert issued["status"] == "ISSUED"
    assert issued["issued_by_user_id"] == QUALITY_HEADERS["X-User-ID"]
    assert_instant_equals(issued["issued_at"], "2026-08-01T12:00:00Z", "issued_at")

    validate_error(
        api.issue_mill_certificate(
            draft["id"], make_headers(LAB1_ID, ROLE_QUALITY_MANAGER)
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    unchanged = validate_success(api.get_mill_certificate(draft["id"], QUALITY_HEADERS))
    assert unchanged["status"] == "ISSUED"
    assert unchanged["issued_by_user_id"] == QUALITY_HEADERS["X-User-ID"]
    assert_instant_equals(unchanged["issued_at"], "2026-08-01T12:00:00Z", "issued_at")
    assert_amount(unchanged["certified_tonnes"], 574.72, "certified_tonnes")

    batch = validate_success(api.get_cement_batch(batch_id, QUALITY_HEADERS))
    assert batch["status"] == "CERTIFIED"
    assert_amount(
        batch["certified_tonnes_allocated"], 574.72, "certified_tonnes_allocated"
    )
