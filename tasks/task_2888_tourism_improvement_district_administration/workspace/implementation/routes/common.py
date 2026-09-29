"""Shared route plumbing: role shortcuts and list filtering."""
import config

ADMIN = config.ROLE_DISTRICT_ADMIN
BOARD = config.ROLE_BOARD_MEMBER
OPERATOR = config.ROLE_OPERATOR
DMO = config.ROLE_DMO_LIAISON
HEARING = config.ROLE_HEARING_OFFICER
AUDITOR = config.ROLE_AUDITOR
VIEWER = config.ROLE_PUBLIC_VIEWER
EVERY_ROLE = list(config.ALL_ROLES)


def narrow(records, **pairs):
    """Apply equality filters, ignoring the ones the caller left unset."""
    out = records
    for field, value in pairs.items():
        if value is not None:
            out = [r for r in out if r.get(field) == value]
    return out
