"""The safety layer.

Three modules, in the order an action passes through them:

    policy        how risky is this
    paths         is this a real path somewhere sensible
    permissions   is this installation allowed to do it at all
    confirmations  has the user answered

Nothing else may decide any of those.
"""

from jarvis2.safety import confirmations, paths, permissions, policy
from jarvis2.safety.confirmations import ConfirmationManager
from jarvis2.safety.permissions import PermissionSet, default_permissions
from jarvis2.safety.policy import Action, Decision, Risk

__all__ = [
    "confirmations", "paths", "permissions", "policy",
    "Action", "ConfirmationManager", "Decision", "PermissionSet", "Risk",
    "default_permissions",
]
