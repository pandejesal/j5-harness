"""Stable entry point for the delegation engine (task 4.2).

Thin facade over :mod:`tools.delegation.orchestrator` so callers have one
import path regardless of internal refactors. All orchestration logic lives
in ``orchestrator.py``; state, ledger, critique, consensus, and healing live
in their sibling modules.
"""

from __future__ import annotations

from .delegation_state import TaskNode, TaskState
from .ledger import DelegationLedger
from .orchestrator import DelegationDAG, Orchestrator

__all__ = ["TaskNode", "TaskState", "DelegationLedger", "DelegationDAG", "Orchestrator"]
__version__ = "1.0.0"
