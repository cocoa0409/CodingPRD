"""System cascades: prohibition, suspension, remediation, withdrawal, bubble-up.

Each cascade is an ordered sequence of steps because later steps read state the
earlier steps wrote, and every cascade applies inside the one request that
triggered it (PRD 2.11).
"""

import calc
from store import db, touch


# ------------------------------------------------------------------ terminals
def quarantine_terminals(program, reason, states):
    """Move the program's terminals in `states` to QUARANTINED with `reason`.

    Each terminal transition also recomputes enforcing_terminal_count for its
    merchant; that census is derived from the terminal rows themselves, so the
    recomputation is implicit and no merchant version is bumped (PRD 3.7/3.8
    bump only the program and terminal versions).
    """
    moved = []
    for term in calc.program_terminals(program["id"]):
        if term["state"] in states:
            term["state"] = "QUARANTINED"
            term["quarantine_reason"] = reason
            touch(term)
            moved.append(term)
    return moved


def disable_terminals_of_program(program):
    moved = []
    for term in calc.program_terminals(program["id"]):
        if term["state"] != "DISABLED":
            term["state"] = "DISABLED"
            touch(term)
            moved.append(term)
    return moved


# ------------------------------------------------------------------ artifacts
def expire_attested_artifacts(program, reason):
    moved = []
    for art in calc.program_artifacts(program["id"]):
        if art["state"] == "ATTESTED":
            art["state"] = "EXPIRED"
            art["expired_reason"] = reason
            touch(art)
            moved.append(art)
    return moved


# ------------------------------------------------------------------ program
def suspend_program(program, disable_reason, quarantine_reason):
    """ACTIVE -> SUSPENDED with the ENFORCING-terminal quarantine cascade."""
    program["status"] = "SUSPENDED"
    program["disable_reason"] = disable_reason
    # CASCADE STEP 1 then STEP 2 (census follows each terminal transition).
    quarantine_terminals(program, quarantine_reason, ("ENFORCING",))
    touch(program)


def remediation_cascade(program):
    """ACTIVE -> REMEDIATION after a substantiation past the exposure threshold."""
    # STEP 1
    program["status"] = "REMEDIATION"
    program["disable_reason"] = "REMEDIATION_ORDER"
    # STEP 2
    expire_attested_artifacts(program, "REMEDIATION_ORDER")
    # STEP 3: readiness is recomputed and the enforcing terminals stop.
    calc.recompute_disclosure_ready(program)
    quarantine_terminals(program, "DISCLOSURE_EXPIRED", ("ENFORCING",))
    # STEP 4 is the census recomputation carried by each terminal transition.
    touch(program)


def withdraw_program(program):
    program["status"] = "WITHDRAWN"
    expire_attested_artifacts(program, "PROGRAM_WITHDRAWN")
    for reg in calc.program_registrations(program["id"]):
        if reg["state"] in ("SUBMITTED", "ACKNOWLEDGED", "EFFECTIVE"):
            reg["state"] = "REVOKED"
            reg["revoked_at"] = db.now()
            touch(reg)
    disable_terminals_of_program(program)
    touch(program)


def bubble_up_remediation_close(case):
    """REMEDIATION -> ACTIVE once the last blocking case closes and readiness holds."""
    program = db.programs.get(case["program_id"])
    if program is None or program["status"] != "REMEDIATION":
        return
    for other in calc.program_cases(program["id"]):
        if other["id"] == case["id"]:
            continue
        if other["investigation_state"] == "SUBSTANTIATED" and other["remediation_state"] != "CLOSED":
            return
    if not calc.disclosure_readiness(program):
        return
    program["status"] = "ACTIVE"
    program["disable_reason"] = "NONE"
    calc.recompute_disclosure_ready(program)
    touch(program)


# ------------------------------------------------------------ law-change sweeps
def prohibition_cascade(jurisdiction):
    """surcharge_permitted true -> false."""
    for program in _programs_of_jurisdiction(jurisdiction["id"]):
        if program["program_type"] != "SURCHARGE":
            continue
        if program["status"] in ("DISABLED", "WITHDRAWN"):
            continue
        program["status"] = "DISABLED"
        program["disable_reason"] = "JURISDICTION_PROHIBITION"
        # The prohibition sweep reaches configured-but-not-yet-enforcing terminals.
        quarantine_terminals(program, "PROGRAM_DISABLED", ("CONFIGURED", "ENFORCING"))
        touch(program)


def repermission_cascade(jurisdiction):
    """surcharge_permitted false -> true."""
    for program in _programs_of_jurisdiction(jurisdiction["id"]):
        if program["status"] != "DISABLED":
            continue
        if program["disable_reason"] != "JURISDICTION_PROHIBITION":
            continue
        program["status"] = "SUSPENDED"
        program["disable_reason"] = "OPERATOR_SUSPENSION"
        calc.recompute_cap(program)
        touch(program)


def _programs_of_jurisdiction(jurisdiction_id):
    from store import sort_rows
    return sort_rows([p for p in db.programs.values()
                      if p["jurisdiction_id"] == jurisdiction_id])
