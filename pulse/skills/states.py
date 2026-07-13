"""Single source of truth for the skill lifecycle state machine.

    candidate --pass--> promoted --regress--> quarantined
        |                   |                      |
        +--fail--> deprecated <--rollback-- promoted

Maps an evaluation *decision* to the resulting skill *status*.
"""
from __future__ import annotations

DECISION_TO_STATUS: dict[str, str] = {
    "promote": "promoted",
    "quarantine": "quarantined",
    "rollback": "promoted",  # roll back to last known-good promoted version
    "deprecate": "deprecated",
    "refine": "candidate",
}
