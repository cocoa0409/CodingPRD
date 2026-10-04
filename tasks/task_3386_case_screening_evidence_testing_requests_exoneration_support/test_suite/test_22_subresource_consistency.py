"""Subresource listing isolation across sibling cases and immediate
read-after-write consistency."""
from test_helpers import (
    TEST_USERS,
    create_client,
    create_evidence_item,
    create_jurisdiction,
    get_case,
    list_rows,
    setup_accepted_case,
    update_case,
    validate_ok,
)

ATTORNEY = TEST_USERS["staff_attorney_headers"]


def test_case_subresource_lists_exactly_its_children(api):
    """PRD section 4: GET `/cases/{id}/evidence-items` lists the evidence
    items of a case.
    PRD section 2.3: "Unless otherwise specified, all list endpoints return
    resources sorted by `created_at` in ascending order. List responses carry
    the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta`
    object of the response envelope."

    Design: Corner/endpoints/case_subresource_lists_exactly_its_children
    """
    jurisdiction = create_jurisdiction(state_code="ID", name="Idaho")
    client = create_client(full_name="Ann Ow", inmate_number="ID-11")
    case_a = setup_accepted_case(
        jurisdiction_id=jurisdiction["id"], client_id=client["id"],
        intake_overrides={"conviction_summary": "Subresource A"},
    )["case"]
    case_b = setup_accepted_case(
        jurisdiction_id=jurisdiction["id"], client_id=client["id"],
        intake_overrides={"conviction_summary": "Subresource B"},
    )["case"]

    items_a = [
        create_evidence_item(case_a["id"], description=f"A{i}", initial_sample_ng=5)
        for i in (1, 2)
    ]
    create_evidence_item(case_b["id"], description="B1", initial_sample_ng=5)

    rows, meta = list_rows(api.list_case_evidence_items(case_a["id"], ATTORNEY))
    assert meta["total_count"] == 2
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {item["id"] for item in items_a}
    assert all(row["case_id"] == case_a["id"] for row in rows), (
        "case B's item never leaks into case A's list"
    )

    rows_b, meta_b = list_rows(api.list_case_evidence_items(case_b["id"], ATTORNEY))
    assert meta_b["total_count"] == 1
    assert rows_b[0]["case_id"] == case_b["id"]


def test_immediate_read_after_write_reflects_every_mutation(api):
    """PRD section 3.6: "A successful update applies the provided fields,
    increments the case's `version` by one, and refreshes `updated_at`".
    PRD section 2.5: "`updated_at` ... refreshed on every mutation of the
    resource, including mutations the resource suffers as the target of a
    cascade."
    PRD section 2.5: "starts at 1 at creation and increments by exactly 1 on
    every mutation, again including cascaded side effects."

    Design: Corner/consistency_model/immediate_read_after_write_reflects_every_mutation
    """
    jurisdiction = create_jurisdiction(state_code="NJ", name="New Jersey")
    ctx = setup_accepted_case(jurisdiction_id=jurisdiction["id"])

    # The very next read after each write reflects it exactly.
    fetched = api.get_jurisdiction(jurisdiction["id"], ATTORNEY)
    assert validate_ok(fetched)["name"] == "New Jersey"

    before = get_case(ctx["case"]["id"])
    assert before["version"] == 1
    update_case(
        ctx["case"]["id"], before["version"],
        strategy_notes="Immediate-read probe",
        theory_of_case="Mistaken identity",
    )
    after = get_case(ctx["case"]["id"])
    assert after["strategy_notes"] == "Immediate-read probe"
    assert after["theory_of_case"] == "Mistaken identity"
    assert after["version"] == before["version"] + 1
    assert after["updated_at"] >= after["created_at"], (
        "mutations refresh the timestamp"
    )
