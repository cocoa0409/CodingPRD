"""The publication ledger: the one entity with no version and no way to edit it."""
from test_helpers import (
    assert_instant,
    assert_score,
    read_publication_records,
    setup_published_cycle,
    validate_success,
)


def test_the_published_row_carries_no_version_and_no_updated_at(api, public_headers):
    """Twelve entity types are versioned and mutable; the published rating is the public
    record of what was said on a date, so it has neither field and no way to edit it.

    PRD §2.4: "`PublicationRecord` is the sole exception: the publication ledger is append-only, so a publication record has `id` and `created_at` but no `updated_at` and no `version` field at all, and there is no endpoint that updates or deletes one."

    PRD §3.9: "Every field of this row is immutable thereafter: the entity is append-only, has no `updated_at`, no `version`, and no update or delete operation anywhere in the surface."

    PRD §3.9: "When `sequence_number` is 1, `previous_published_score` and `score_delta` are both null and `change_direction` is `FIRST_PUBLICATION`."

    PRD §3.9: "It populates `notified_recipient_kinds` as an ordered list that always begins with `RATED_ORGANIZATION` and appends `MEDIA` only when `change_direction` is not `FIRST_PUBLICATION` and the absolute value of `score_delta` is at least `10.00`."

    Design: Corner/entities/publication_record_immutable_append_only_with_no_version_field
    """
    scenario = setup_published_cycle()
    listed = read_publication_records(
        public_headers, rating_cycle_id=scenario["cycle"]["id"]
    )
    assert len(listed) == 1

    record = validate_success(
        api.get_publication_record(listed[0]["id"], public_headers)
    )

    assert record["sequence_number"] == 1
    assert record["change_direction"] == "FIRST_PUBLICATION"
    assert record["previous_published_score"] is None
    assert record["score_delta"] is None
    assert_score(record["published_score"], 83.13, "published_score")
    assert record["published_grade"] == "MEETS_STANDARDS"
    assert_score(record["weighted_sum_final"], 84.63, "weighted_sum_final")
    assert_score(record["standards_penalty_points"], 1.50, "standards_penalty_points")
    assert record["methodology_version_label"] == "M1"
    assert record["notified_recipient_kinds"] == ["RATED_ORGANIZATION"]
    assert_instant(record["published_at"], "2026-09-22T00:00:00Z", "published_at")
    assert record["rating_cycle_id"] == scenario["cycle"]["id"]
    assert record["organization_id"] == scenario["organization"]["id"]

    assert "version" not in record
    assert "updated_at" not in record
    assert "id" in record
    assert "created_at" in record
