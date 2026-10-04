"""Run-create state gates: agreement must be ACTIVE, format must be QUALIFIED,
and gate-6 state errors mask gate-9 capacity errors (PRD §2.7, §3.4)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    set_clock, create_plant, create_customer, create_agreement, sign_agreement,
    create_line, create_format, create_qualified_format,
    get_agreement_version, scheduler, manager, api_client,
)

RUN_BODY = {
    "scheduled_qty": 50_000,
    "graphics_code": "G1",
    "window_start": "2026-09-10T08:00:00Z",
    "window_end": "2026-09-10T16:00:00Z",
}


def _draft_env(api, capacity=1_000_000):
    """Plant + customer + DRAFT agreement + line + QUALIFIED format."""
    set_clock()
    plant = create_plant(warehouse_capacity_units=capacity)
    customer = create_customer()
    agreement = create_agreement(plant["id"], customer["id"])
    line = create_line(plant["id"])
    fmt = create_qualified_format(plant["id"], customer["id"])
    return plant, customer, agreement, line, fmt


class TestFormatNotQualified:
    def test_run_create_with_unqualified_format_returns_format_not_qualified(self, api):
        """PRD §3.4: "The format must be `QUALIFIED`, otherwise
        `ERR_FORMAT_NOT_QUALIFIED`." PRD §3.3: "only `QUALIFIED` formats may be
        scheduled onto runs."

        Design: Corner/errors/run_create_with_unqualified_format_returns_format_not_qualified
        """
        set_clock()
        plant = create_plant()
        customer = create_customer()
        agreement = sign_agreement(create_agreement(plant["id"], customer["id"]))
        line = create_line(plant["id"])
        fmt = create_format(plant["id"], customer["id"])  # PROPOSED
        api.tool_format(fmt["id"], manager())             # TOOLED, not QUALIFIED
        version = get_agreement_version(agreement["id"])
        resp = api.create_run(agreement["id"],
                              dict(RUN_BODY, line_id=line["id"],
                                   format_id=fmt["id"],
                                   expected_agreement_version=version),
                              scheduler())
        validate_error(resp, ApiErrorId.ERR_FORMAT_NOT_QUALIFIED)
        api.qualify_format(fmt["id"], manager())
        version = get_agreement_version(agreement["id"])
        ok = validate_success(api.create_run(
            agreement["id"],
            dict(RUN_BODY, line_id=line["id"], format_id=fmt["id"],
                 expected_agreement_version=version), scheduler()), 201)
        assert ok["status"] == "SCHEDULED"


class TestAgreementActiveGate:
    def test_run_create_on_draft_agreement_rejected_not_active(self, api):
        """PRD §3.4: "The parent agreement must be `ACTIVE`, otherwise the
        create is rejected with `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/run_create_requires_agreement_active_then_succeeds_after_sign
        """
        _p, _c, agreement, line, fmt = _draft_env(api)
        resp = api.create_run(
            agreement["id"],
            dict(RUN_BODY, line_id=line["id"], format_id=fmt["id"],
                 expected_agreement_version=agreement["version"]), scheduler())
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)

    def test_run_create_after_sign_succeeds(self, api):
        """PRD §3.2: "a `CustomerPlanner` acting for the agreement's customer
        moves the agreement from `DRAFT` to `ACTIVE`." PRD §3.4: "A created run
        starts in `SCHEDULED`."

        Design: Difficulty/cross_entity_state_dependency/run_create_requires_agreement_active_then_succeeds_after_sign
        """
        _p, _c, agreement, line, fmt = _draft_env(api)
        signed = sign_agreement(agreement)
        assert signed["status"] == "ACTIVE"
        ok = validate_success(api.create_run(
            agreement["id"],
            dict(RUN_BODY, line_id=line["id"], format_id=fmt["id"],
                 expected_agreement_version=signed["version"]), scheduler()), 201)
        assert ok["status"] == "SCHEDULED"


class TestStateBeatsCapacity:
    def _draft_env_unqualified(self, api):
        """DRAFT agreement, format deliberately left PROPOSED, tiny capacity."""
        set_clock()
        plant = create_plant(warehouse_capacity_units=1_000_000)
        customer = create_customer()
        agreement = create_agreement(plant["id"], customer["id"])
        line = create_line(plant["id"])
        fmt = create_format(plant["id"], customer["id"])  # PROPOSED
        return plant, customer, agreement, line, fmt

    def test_create_on_draft_agreement_state_beats_capacity_overflow(self, api):
        """PRD §2.7: "a request that would fail several gates is always rejected
        with the error from the earliest failing gate" — gate 6 state ("run
        creation ... under an agreement that is not `ACTIVE`:
        `ERR_AGREEMENT_NOT_ACTIVE`") precedes gate 9 warehouse capacity
        (`ERR_WAREHOUSE_CAPACITY_EXCEEDED`).

        Design: Difficulty/priority_pair_validation_conflict/create_on_draft_agreement_state_beats_capacity_overflow
        """
        _p, _c, agreement, line, fmt = self._draft_env_unqualified(api)
        resp = api.create_run(
            agreement["id"],
            dict(RUN_BODY, scheduled_qty=2_000_000, line_id=line["id"],
                 format_id=fmt["id"],
                 expected_agreement_version=agreement["version"]), scheduler())
        err = validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)
        assert err["error_id"] != ApiErrorId.ERR_WAREHOUSE_CAPACITY_EXCEEDED
        assert err["error_id"] != ApiErrorId.ERR_FORMAT_NOT_QUALIFIED

    def test_create_on_draft_agreement_persists_nothing(self, api):
        """PRD §2.7 gate 6: state preconditions reject before any persistence;
        the rejected create must leave the agreement's run list empty.

        Design: Difficulty/priority_pair_validation_conflict/create_on_draft_agreement_state_beats_capacity_overflow
        """
        _p, _c, agreement, line, fmt = self._draft_env_unqualified(api)
        api.create_run(agreement["id"],
                       dict(RUN_BODY, scheduled_qty=2_000_000,
                            line_id=line["id"], format_id=fmt["id"],
                            expected_agreement_version=agreement["version"]),
                       scheduler())
        rows, _ = validate_paginated(
            api.list_runs(manager(), params={"agreement_id": agreement["id"]}))
        assert len(rows) == 0
