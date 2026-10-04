"""Breadth test: immediate consistency — a create response already carries the
final stored state, and a same-instant read returns identical values."""

from test_helpers import (
    CLOCK_START_ISO,
    assert_instant,
    assert_noncompliance_record,
    fixtures as fx,
)


def test_immediate_visibility_of_created_nr(api):
    """PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects. For 2xx responses with no data, it contains an empty
    object. Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    PRD §3.3: "The record is born `OPEN`, with `issued_at` stamped from the
    logical clock."

    Design: Corner/consistency_model/immediate_visibility_of_created_nr
    """
    est = fx.create_establishment(api, name="CM1 Plant", species_classes=["CATTLE"])
    inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])

    created = fx.issue_nr(api, est["id"], inspector["id"], regulation_family="OTHER",
                          description="visibility probe")

    # The POST response already shows the final stored state.
    assert_noncompliance_record(created)
    assert created["status"] == "OPEN"
    assert_instant(created["issued_at"], CLOCK_START_ISO, "issued_at stamped from the logical clock")

    # A same-instant read returns identical field values — no asynchronous lag.
    reread = fx.get_nr(api, created["id"])
    assert_noncompliance_record(reread)
    for field in ("id", "status", "issued_at", "observed_at", "regulation_family",
                  "description", "establishment_id", "issued_by_inspector_id", "version"):
        assert reread[field] == created[field], (
            f"{field}: read {reread[field]!r} diverges from the create response {created[field]!r}"
        )
