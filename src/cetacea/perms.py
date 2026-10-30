from dataclasses import dataclass

class PermissionDenied(Exception): pass
class NotApproved(PermissionDenied): pass

@dataclass(frozen=True)
class Principal:
    actor_type: str
    actor_id: str
    scopes: frozenset[str]

    def require(self, scope):
        if self.actor_type not in {'human', 'ai'} or (scope == 'approve' and self.actor_type != 'human') or scope not in self.scopes:
            raise PermissionDenied(scope)

HUMAN = Principal('human', 'cli', frozenset({'read','plan','execute','approve','cancel','admin','lightroom'}))

AI_SCOPES = frozenset({'read', 'plan', 'execute', 'cancel', 'lightroom'})

def ai_principal(actor_id='ai:mcp', scopes=None):
    """Construct a least-privilege AI identity; elevated scopes are forbidden."""
    selected = AI_SCOPES if scopes is None else frozenset(scopes)
    if not selected <= AI_SCOPES:
        raise PermissionDenied('AI scopes must be read, plan, execute, cancel, lightroom')
    return Principal('ai', actor_id, selected)
