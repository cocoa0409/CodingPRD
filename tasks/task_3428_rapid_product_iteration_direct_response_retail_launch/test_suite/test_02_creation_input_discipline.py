"""Creation-time input discipline: defaults, ignored client-supplied system
fields, malformed values, and uniqueness (PRD §2.5, §3.1, §3.3, §3.4).
"""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ADMIN,
    LEAD,
    LC_JANE,
    SCI_ANNA,
    SOURCING,
    ApiErrorId,
    api_client,
    assert_factory_partner,
    complete_round_payload,
    create_category_payload,
    create_concept,
    create_partner_payload,
    create_patent_case_payload,
    create_season,
    create_variant,
    create_variant_payload,
    get_season,
    reset_clock,
    set_clock,
    setup_engineering_locked_concept,
    setup_season_with_category,
    setup_tooled_variant,
    validate_created,
    validate_error,
    validate_ok,
    add_insight,
    advance_concept,
    create_open_round,
)


def test_partner_create_defaults_status_active_and_zero_allocation(api):
    """PRD §3.3: "A partner begins `ACTIVE` with `allocated_units` 0, and
    fetching a partner returns the live computed allocation."

    Design: Corner/entities/partner_create_defaults_status_active_and_zero_allocation
    """
    reset_clock()
    resp = api_client.create_partner(
        create_partner_payload("Shenzhen Precision", 500), SOURCING
    )
    data = validate_created(resp)
    assert_factory_partner(data)
    assert data["status"] == "ACTIVE"
    assert data["allocated_units"] == 0
    assert data["version"] == 1


def test_category_computed_fields_input_ignored(api):
    """PRD §3.1: "the category's `exposure_index` initializes to its
    `crowding_base`, and its `exposure_level` is banded immediately by the
    thresholds of §3.8".

    Design: Corner/entities/category_computed_fields_input_ignored
    """
    reset_clock()
    season = create_season("FW26")
    resp = api_client.create_category(
        create_category_payload(
            season["id"], "Air Fryers", 6,
            exposure_index=999, exposure_level="SEVERE",
        ),
        ADMIN,
    )
    data = validate_created(resp)
    assert data["exposure_index"] == 6
    assert data["exposure_level"] == "CLEAR"
    assert get_season(season["id"])["posture"] == "SEASON_OPEN"


def test_variant_create_client_input_ignored(api):
    """PRD §3.3: "A new variant's `lifecycle` is `DRAFT`" and PRD §2.5: "The
    `id` is a server-minted UUID with no type prefix. `created_at` records the
    creation instant as an ISO 8601 UTC timestamp with three fractional digits,
    drawn from the logical clock."

    Design: Corner/entities/variant_create_client_input_ignored
    """
    base = setup_season_with_category()
    concept = setup_engineering_locked_concept(base["category"]["id"])
    forged_id = "11111111-2222-3333-4444-555555555555"
    resp = api_client.create_variant(
        create_variant_payload(
            concept["id"], "CV900-DTC", "DTC", id=forged_id, lifecycle="RETIRED"
        ),
        LEAD,
    )
    data = validate_created(resp)
    assert data["id"] != forged_id
    assert data["lifecycle"] == "DRAFT"
    created = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
    assert created == datetime(2026, 9, 10, tzinfo=timezone.utc)


def test_invalid_enum_and_range_values_rejected(api):
    """PRD §3.8: "a `severity` of `LOW`, `MED`, or `HIGH`" (a value outside the
    declared set is malformed, and the only 400 in the §5 catalogue is
    `ERR_INVALID_REQUEST`) and PRD §3.2: "Completing a round records a `score`
    as an integer from 0 to 100 inclusive — anything outside that range is
    rejected with `ERR_INVALID_REQUEST`".

    Design: Corner/entities/invalid_enum_and_range_values_rejected
    """
    base = setup_season_with_category()
    concept = create_concept(base["category"]["id"])
    add_insight(concept["id"], 40, "2026-09-01T00:00:00Z")
    add_insight(concept["id"], 16, "2026-09-08T00:00:00Z")
    set_clock("2026-09-10T00:00:00Z")
    advance_concept(concept["id"])
    advance_concept(concept["id"])
    advance_concept(concept["id"])
    round_ = create_open_round(concept["id"])

    resp1 = api_client.create_patent_case(
        create_patent_case_payload(
            base["category"]["id"], "PT-9001", 500000, severity="CRITICAL"
        ),
        LC_JANE,
    )
    validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST)

    resp2 = api_client.complete_round(
        round_["id"], complete_round_payload(score=101), LEAD
    )
    validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)
    rounds = validate_ok(api_client.list_rounds(concept["id"], LEAD))
    assert rounds[0]["status"] == "OPEN"


def test_variant_duplicate_model_number_rejected(api):
    """PRD §3.3: "it is globally unique across all variants: reusing one is
    rejected with `ERR_MODEL_NUMBER_CONFLICT`."

    Design: Corner/entities/variant_duplicate_model_number_rejected
    """
    base = setup_season_with_category()
    concept1 = setup_engineering_locked_concept(base["category"]["id"])
    create_variant(concept1["id"], "CV100-AMZ", "AMAZON")
    concept2 = setup_engineering_locked_concept(
        base["category"]["id"], title="Quieter motor"
    )
    resp = api_client.create_variant(
        create_variant_payload(concept2["id"], "CV100-AMZ", "CLUB"), LEAD
    )
    validate_error(resp, ApiErrorId.ERR_MODEL_NUMBER_CONFLICT)


def test_study_create_missing_claim_text_rejected(api):
    """PRD §3.4: "A `ClaimsScientist` opens a ClaimStudy on a `TOOLED` variant
    by supplying the `variant_id` and the `claim_text` under test" — omitting
    the required `claim_text` is a malformed request, and the only 400 in the
    §5 catalogue is `ERR_INVALID_REQUEST`.

    Design: Corner/entities/study_create_missing_claim_text_rejected
    """
    base = setup_season_with_category()
    bundle = setup_tooled_variant(base["category"]["id"])
    resp = api_client.create_claim_study(
        {"variant_id": bundle["variant"]["id"]}, SCI_ANNA
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
