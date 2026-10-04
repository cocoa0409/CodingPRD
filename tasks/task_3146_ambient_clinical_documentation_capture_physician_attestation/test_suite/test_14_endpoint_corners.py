"""Endpoint corners: list pagination envelope and defaults, status-filtered
suggestion listings, and the modify-then-confirm suggestion path.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.fixtures import (
    create_draft,
    create_encounter,
    create_patient,
    create_physician,
    ready_world,
)
from test_helpers.test_users import make_physician_headers


class TestListPaginationEnvelope:
    def test_limit_offset_and_defaults(self, client):
        """PRD 2.3: "`limit` sets the maximum number of items returned per
        page; it defaults to 10, with a minimum of 1 and a maximum of 100.
        `offset` sets the number of items to skip and defaults to 0."
        PRD 2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/corner_list_pagination_envelope_fields
        """
        patient = create_patient(client)
        physician = create_physician(client)
        headers = make_physician_headers(physician["id"])
        for _ in range(3):
            create_encounter(client, patient, physician)

        page1, meta1 = validate_paginated(
            client.list_patient_encounters(
                patient["id"], headers=headers, params={"limit": 2, "offset": 0}
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            client.list_patient_encounters(
                patient["id"], headers=headers, params={"limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False

        page_default, meta_default = validate_paginated(
            client.list_patient_encounters(patient["id"], headers=headers)
        )
        assert len(page_default) == 3
        assert meta_default["limit"] == 10
        assert meta_default["offset"] == 0


class TestFilteredListCodeSuggestionsByStatus:
    def test_status_filter_narrows_rows(self, client):
        """PRD 3.6: "Suggestion listings may be filtered by `status` and by
        `code_type`."

        Design: Corner/endpoints/corner_filtered_list_code_suggestions_by_status
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        headers = world["physician_headers"]
        suggestions = validate_success(
            client.create_code_suggestions(
                draft["id"],
                {
                    "suggestions": [
                        f.diagnosis_suggestion_payload("D201", confidence=0.9),
                        f.diagnosis_suggestion_payload("D202", confidence=0.8),
                    ]
                },
                headers=headers,
            ),
            201,
        )
        get_success_data(client.reject_suggestion(suggestions[0]["id"], headers=headers))

        all_rows, _ = validate_paginated(
            client.list_code_suggestions(draft["id"], headers=headers)
        )
        assert len(all_rows) == 2

        rejected, _ = validate_paginated(
            client.list_code_suggestions(
                draft["id"], headers=headers, params={"status": "REJECTED"}
            )
        )
        assert len(rejected) == 1
        assert rejected[0]["status"] == "REJECTED"

        suggested, _ = validate_paginated(
            client.list_code_suggestions(
                draft["id"], headers=headers, params={"status": "SUGGESTED"}
            )
        )
        assert len(suggested) == 1
        assert suggested[0]["status"] == "SUGGESTED"


class TestModifyThenConfirmSuggestion:
    def test_modify_recomputes_line_and_confirm_admits(self, client):
        """PRD 3.6: "Modification moves `SUGGESTED` → `MODIFIED`, replacing
        `code_value` with `new_code_value` (itself subject to the
        `ERR_CODE_VALUE_MALFORMED` format check) and optionally `quantity`
        with `new_quantity`, then recomputing `line_total_cents`."
        PRD 3.6: "Confirmation moves `SUGGESTED` → `CONFIRMED` or `MODIFIED`
        → `CONFIRMED`"

        Design: Corner/endpoints/corner_modify_then_confirm_suggestion
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        headers = world["physician_headers"]
        suggestions = validate_success(
            client.create_code_suggestions(
                draft["id"],
                {
                    "suggestions": [
                        f.billing_suggestion_payload(
                            "B401", confidence=1.0, quantity=1, unit_fee_cents=1000
                        )
                    ]
                },
                headers=headers,
            ),
            201,
        )
        suggestion_id = suggestions[0]["id"]
        modified = validate_success(
            client.modify_suggestion(
                suggestion_id,
                {"new_code_value": "B402", "new_quantity": 3},
                headers=headers,
            )
        )
        assert modified["status"] == "MODIFIED"
        assert modified["line_total_cents"] == 3000, "1000 * 3 * 1.0"
        confirmed = validate_success(
            client.confirm_suggestion(suggestion_id, headers=headers)
        )
        assert confirmed["status"] == "CONFIRMED"
        draft_body = validate_success(client.get_note_draft(draft["id"], headers=headers))
        assert draft_body["billing_final_cents"] == 3000
