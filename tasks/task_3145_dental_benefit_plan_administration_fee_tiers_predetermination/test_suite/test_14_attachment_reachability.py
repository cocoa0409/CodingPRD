"""Endpoint reachability: attachments readable from both parents."""

from test_helpers import factories as f
from test_helpers.assertions import get_success_data, validate_paginated
from test_helpers.constants import CLAIM_PENDED_ATTACHMENTS
from test_helpers.fixtures import claim_lines, standard_stack
from test_helpers.test_users import EXAMINER, make_provider_headers


class TestAttachmentReachability:
    def test_attachments_reachable_from_claim_and_claim_line(self, client):
        """The same attachment shows under the claim and under the line.

        PRD 3.5: "Providers supply missing documentation by uploading
        attachments: each attachment names the `claim_line_id` it supports —
        which must belong to the same claim, else
        `ERR_CROSS_REFERENCE_MISMATCH` — an `attachment_kind` of `RADIOGRAPH`,
        `NARRATIVE`, `PERIO_CHART`, or `PHOTO`, and an opaque `blob_ref`
        storage reference."
        PRD 4 lists both "List attachments for a claim" and "List attachments
        linked to one claim line" among the endpoints all six roles may read.

        Design: Corner/endpoints/attachments_reachable_from_claim_and_claim_line
        """
        entries = [
            f.fee_schedule_entry_payload(
                cdt_code="D2740", allowed_cents=10000, category="MAJOR",
                requires_attachment=True,
            ),
        ]
        stack = standard_stack(client, entries=entries)
        resp = client.create_claim(
            f.create_claim_payload(
                stack["subscriber"]["id"],
                stack["provider"]["id"],
                lines=[
                    f.claim_line_payload(
                        cdt_code="D2740", tooth_number="14",
                        submitted_amount_cents=9000,
                    )
                ],
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )
        claim = get_success_data(resp)
        assert claim["status"] == CLAIM_PENDED_ATTACHMENTS
        line_id = claim_lines(client, claim["id"])[0]["id"]

        resp = client.create_claim_attachment(
            claim["id"],
            f.create_attachment_payload(
                line_id, attachment_kind="NARRATIVE", blob_ref="blob://note"
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )
        attachment = get_success_data(resp)

        claim_level, _meta = validate_paginated(
            client.list_claim_attachments(claim["id"], headers=EXAMINER)
        )
        assert len(claim_level) == 1
        assert claim_level[0]["attachment_kind"] == "NARRATIVE"

        line_level, _meta = validate_paginated(
            client.list_claim_line_attachments(line_id, headers=EXAMINER)
        )
        assert len(line_level) == 1
        assert line_level[0]["id"] == attachment["id"], (
            "both paths expose the same attachment row"
        )
