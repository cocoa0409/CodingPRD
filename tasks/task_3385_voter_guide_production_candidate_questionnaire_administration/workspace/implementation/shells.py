"""CandidateResponse shell lifecycle shared by filings and questionnaires
(PRD 3.2 cascades, 3.3 issue, 3.4)."""
import helpers
from helpers import base_entity, touch
from store import store


def create_shell(questionnaire, filing):
    shell = base_entity()
    shell.update({
        "questionnaire_id": questionnaire["id"],
        "filing_id": filing["id"],
        "answers": [],
        "status": "INVITED",
        "submitted_at": None,
        "per_answer_word_counts": [],
        "over_limit_positions": [],
    })
    store.responses[shell["id"]] = shell
    return shell


def hide_shell_for_filing(filing):
    """Withdraw/disqualify cascade: the filing's shell, whatever its current
    status, moves to WITHDRAWN_HIDDEN."""
    shell = helpers.shell_of_filing(filing["id"])
    if shell is not None and shell["status"] != "WITHDRAWN_HIDDEN":
        shell["status"] = "WITHDRAWN_HIDDEN"
        touch(shell)
    return shell


def restore_shell_for_filing(filing):
    """Refile cascade: a hidden shell returns to INVITED, answers preserved."""
    shell = helpers.shell_of_filing(filing["id"])
    if shell is not None and shell["status"] == "WITHDRAWN_HIDDEN":
        shell["status"] = "INVITED"
        touch(shell)
    return shell
