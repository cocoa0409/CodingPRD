"""Season posture gates and administration: frozen/closed blankets, guarded
scope, unfreeze preconditions, and the run-review counter (PRD §2.7, §3.9).
"""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ADMIN,
    LEAD,
    LC_JANE,
    ApiErrorId,
    api_client,
    add_insight,
    create_category_payload,
    create_concept,
    create_concept_payload,
    create_insight_payload,
    file_case,
    freeze_season,
    run_review,
    setup_season_with_category,
    unfreeze_season,
    validate_error,
    validate_ok,
)


def test_frozen_season_blocks_all_child_mutations(api):
    """PRD §2.7: "While a season is `SEASON_FROZEN`, every season-scoped
    mutation is rejected with `ERR_SEASON_FROZEN` (HTTP 409)."

    Design: Corner/validations/frozen_season_blocks_all_child_mutations
    """
    base = setup_season_with_category()
    concept = create_concept(base["category"]["id"])
    freeze_season(base["season"]["id"])
    resp1 = api_client.add_insight(
        concept["id"], create_insight_payload(10, "2026-09-01T00:00:00Z"), LEAD
    )
    validate_error(resp1, ApiErrorId.ERR_SEASON_FROZEN)
    resp2 = api_client.create_concept(
        create_concept_payload(base["category"]["id"], "Frozen concept"), LEAD
    )
    validate_error(resp2, ApiErrorId.ERR_SEASON_FROZEN)


def test_guarded_season_still_allows_research_ops(api):
    """PRD §2.7: "While a season is `SEASON_GUARDED`, exactly one operation is
    throttled: airing a media test is rejected with `ERR_SEASON_GUARDED` (HTTP
    409), while all other workflows, including retail-agreement signing,
    continue under a guarded season unless the category itself is `SEVERE`".

    Design: Corner/validations/guarded_season_still_allows_research_ops
    """
    base = setup_season_with_category()
    concept = create_concept(base["category"]["id"])
    file_case(base["category"]["id"], "PT-8001", 2_000_000, "HIGH",
              filer_headers=LC_JANE)
    file_case(base["category"]["id"], "PT-8002", 500_000, "MED",
              filer_headers=LC_JANE)
    data = add_insight(concept["id"], 10, "2026-09-01T00:00:00Z")
    assert data["research_momentum"] == pytest.approx(10.0, abs=1e-9)
    season = api_client.get_season(base["season"]["id"], ADMIN)
    assert validate_ok(season)["posture"] == "SEASON_GUARDED"


def test_closed_season_blocks_categories_and_review(api):
    """PRD §2.7: "While a season is `SEASON_CLOSED`, every season-scoped
    mutation — including the run-review checkpoint itself — is rejected with
    `ERR_SEASON_CLOSED` (HTTP 409)." and "Creating a category is exempt from
    the frozen gate as an administrative repair path, but it is not exempt
    from a closed season."

    Design: Corner/validations/closed_season_blocks_categories_and_review
    """
    base = setup_season_with_category()
    validate_ok(api_client.close_season(base["season"]["id"], ADMIN))
    resp1 = api_client.create_category(
        create_category_payload(base["season"]["id"], "Late Category", 1), ADMIN
    )
    validate_error(resp1, ApiErrorId.ERR_SEASON_CLOSED)
    resp2 = api_client.run_review(base["season"]["id"], ADMIN)
    validate_error(resp2, ApiErrorId.ERR_SEASON_CLOSED)


def test_unfreeze_requires_intervening_review(api):
    """PRD §3.9: "Unfreezing back to `SEASON_OPEN` is deliberately harder, and
    both of its preconditions failing surface as `ERR_INVALID_STATE`: at least
    one full run-review must have completed since the freeze, meaning the
    current `review_index` must be strictly greater than
    `frozen_at_review_index`; and no linked category may be `SEVERE`."

    Design: Corner/state_machines/unfreeze_requires_intervening_review
    """
    base = setup_season_with_category()
    freeze_season(base["season"]["id"])  # frozen_at_review_index = 0
    resp = api_client.unfreeze_season(base["season"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    run_review(base["season"]["id"])  # review_index 1 > 0
    data = unfreeze_season(base["season"]["id"])
    assert data["posture"] == "SEASON_OPEN"
    assert data["frozen_at_review_index"] is None


def test_run_review_advances_index_and_repeat_review_is_inert(api):
    """PRD §3.9: "Each run first increments `review_index` by one, stamps
    `last_review_at` from the logical clock, and advances the season's
    `version` by one; it then applies eleven ordered steps. Step 1 activates
    pending litigation: every PatentCase in `FILED` status in a category
    linked to the season becomes `ACTIVE`."

    Design: Corner/cross_cutting_complexity_layers/run_review_advances_index_and_repeat_review_is_inert
    """
    base = setup_season_with_category()
    file_case(base["category"]["id"], "PT-5001", 1_000_000, "MED",
              filer_headers=LC_JANE)
    season = run_review(base["season"]["id"])
    assert season["review_index"] == 1
    stamped = datetime.fromisoformat(
        season["last_review_at"].replace("Z", "+00:00")
    )
    assert stamped == datetime(2026, 9, 1, tzinfo=timezone.utc)
    season = run_review(base["season"]["id"])
    assert season["review_index"] == 2
    cases = validate_ok(
        api_client.list_category_patent_cases(base["category"]["id"], LC_JANE)
    )
    assert cases[0]["status"] == "ACTIVE"
