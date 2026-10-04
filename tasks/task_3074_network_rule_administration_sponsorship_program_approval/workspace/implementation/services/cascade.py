"""Cascade service: member suspension/reinstatement/termination cascades,
participant termination cascade, program retirement cascade."""

import db
from helpers import touch


def suspend_member_cascade(member_id):
    """Member ACTIVE -> SUSPENDED:
    - Participants sponsored by member in ACTIVE -> SUSPENDED
    - Merchants under those just-suspended participants (any pre-state except
      TERMINATED? PRD: 'merchants under those participants follow them down')
      -> SUSPENDED (only ACTIVE ones transition; SUSPENDED already there,
      TERMINATED terminal)
    - BinRanges of the issuer in ACTIVE -> SUSPENDED
    """
    suspended_participants = []
    for p in db.participants.values():
        if p["sponsor_member_id"] == member_id and p["status"] == "ACTIVE":
            p["status"] = "SUSPENDED"
            touch(p)
            suspended_participants.append(p["id"])
    for m in db.merchants.values():
        if m.get("participant_id") in suspended_participants and m["status"] == "ACTIVE":
            m["status"] = "SUSPENDED"
            touch(m)
    for b in db.bin_ranges.values():
        if b["issuer_member_id"] == member_id and b["status"] == "ACTIVE":
            b["status"] = "SUSPENDED"
            touch(b)


def reinstate_member_cascade(member_id):
    """Member SUSPENDED -> ACTIVE:
    - Participants sponsored by member still SUSPENDED -> ACTIVE
    - Merchants under those participants (SUSPENDED) -> ACTIVE
    - BinRanges of the issuer in SUSPENDED -> ACTIVE
    """
    reinstated_participants = []
    for p in db.participants.values():
        if p["sponsor_member_id"] == member_id and p["status"] == "SUSPENDED":
            p["status"] = "ACTIVE"
            touch(p)
            reinstated_participants.append(p["id"])
    for m in db.merchants.values():
        if m.get("participant_id") in reinstated_participants and m["status"] == "SUSPENDED":
            m["status"] = "ACTIVE"
            touch(m)
    for b in db.bin_ranges.values():
        if b["issuer_member_id"] == member_id and b["status"] == "SUSPENDED":
            b["status"] = "ACTIVE"
            touch(b)


def terminate_member_cascade(member_id):
    """Member SUSPENDED -> TERMINATED:
    - sponsored participants still SUSPENDED -> TERMINATED
    - merchants under those terminated participants -> TERMINATED (participant
      termination cascade)
    """
    for p in db.participants.values():
        if p["sponsor_member_id"] == member_id and p["status"] == "SUSPENDED":
            p["status"] = "TERMINATED"
            touch(p)
            terminate_participant_cascade(p["id"])


def terminate_participant_cascade(participant_id):
    """Participant SUSPENDED -> TERMINATED: merchants under it -> TERMINATED."""
    for m in db.merchants.values():
        if m.get("participant_id") == participant_id and m["status"] != "TERMINATED":
            m["status"] = "TERMINATED"
            touch(m)


def retire_program_cascade(program_id):
    """Program PRODUCTION_ENABLED -> RETIRED: bound ACTIVE BinRanges -> DEACTIVATED."""
    for b in db.bin_ranges.values():
        if b.get("assigned_program_id") == program_id and b["status"] == "ACTIVE":
            b["status"] = "DEACTIVATED"
            touch(b)
