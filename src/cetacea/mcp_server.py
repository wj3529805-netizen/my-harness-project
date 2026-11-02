"""ID-only stdio interface to the shared Workbench; approvals stay human-only."""
import json
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from .core import Workbench
from .perms import ai_principal, PermissionDenied, NotApproved
from .tasks import InvalidTransition
from .ingest.pathsafe import identifier


def create_server(home, actor='ai:mcp', scopes=None):
    principal = ai_principal(actor, scopes)
    server = MCPServer('CETACEA Photo Workbench')

    def call(method, **args):
        try:
            for key, value in args.items():
                if value is not None and (key.endswith('_id') or key == 'batch_label'):
                    identifier(value)
            w = Workbench(home, principal=principal)
            w._call('read', 'mcp.' + method, args.get('task_id'))
            if method == 'plan_import' and args['stages'] is None:
                principal.require('plan')
                if args['preset_id'] is None:
                    raise ValueError("Pass preset_id for the full pipeline, or stages=['ingest'] for ingest only")
                args['stages'] = ['ingest', 'lr_register', 'lr_preset', 'lr_export', 'preview_verify']
            # Resolve tasks first so every task-oriented tool has NOT_FOUND semantics.
            if args.get('task_id'): w.get_task(args['task_id'])
            result = getattr(w, method)(**args)
            if method in {'execute', 'execute_lightroom'}: result = w.get_task(args['task_id'])
            payload = {**result, 'mock': bool(w.adapter.mock)} if isinstance(result, dict) else {'items': result, 'mock': bool(w.adapter.mock)}
            return CallToolResult(content=[TextContent(type='text', text=json.dumps(payload))], structured_content=payload)
        except Exception as exc:
            code = ('NOT_APPROVED' if isinstance(exc, NotApproved) else
                    'PERMISSION_DENIED' if isinstance(exc, PermissionDenied) else
                    'INVALID_TRANSITION' if isinstance(exc, InvalidTransition) else
                    'NOT_FOUND' if isinstance(exc, KeyError) else
                    'INVALID_ARGUMENT' if isinstance(exc, (ValueError, TypeError)) else 'INTERNAL_ERROR')
            payload = {'code': code, 'message': str(exc)}
            return CallToolResult(is_error=True, content=[TextContent(type='text', text=json.dumps(payload))], structured_content=payload)

    @server.tool()
    def photo_list_orders():
        """List registered orders available for planning."""
        return call('list_orders')
    @server.tool()
    def photo_list_sources():
        """List registered read-only photo sources."""
        return call('list_sources')
    @server.tool()
    def photo_scan_source(source_id: str):
        """Scan a registered source and report its files and digest."""
        return call('scan_source', source_id=source_id)
    @server.tool()
    def photo_plan_import(order_id: str, photographer_id: str, source_id: str, batch_label: str | None = None, preset_id: str | None = None, stages: list[str] | None = None):
        """Plan import, Lightroom registration, preset, preview export and verification as one plan by default: ingest, lr_register, lr_preset, lr_export, preview_verify. Provide preset_id, or stages=['ingest'] for ingest only. One human approval is needed; AI cannot approve. Stop at WAITING_APPROVAL and report task_id and plan_digest to the human."""
        return call('plan_import', order_id=order_id, photographer_id=photographer_id, source_id=source_id, batch_label=batch_label, preset_id=preset_id, stages=stages)
    @server.tool()
    def photo_execute_import(task_id: str):
        """Run the whole approved pipeline end to end, all stages in the plan, skipping completed stages for resumability. Returns NOT_APPROVED when unapproved."""
        return call('execute', task_id=task_id)
    @server.tool()
    def photo_get_task(task_id: str):
        """Get a task's state, approved plan and progress details."""
        return call('get_task', task_id=task_id)
    @server.tool()
    def photo_cancel_task(task_id: str):
        """Cancel a task and revoke its approval."""
        return call('cancel', task_id=task_id)
    @server.tool()
    def photo_retry_task(task_id: str):
        """Resume a FAILED task after partial failure, skipping completed stages; no new approval is needed unless the plan changed. A CANCELLED task returns to WAITING_APPROVAL."""
        return call('retry', task_id=task_id)
    @server.tool()
    def photo_list_assets(task_id: str | None = None, batch_id: str | None = None):
        """List assets, optionally filtered by registered task or batch ID."""
        return call('list_assets', task_id=task_id, batch_id=batch_id)
    @server.tool()
    def lightroom_get_status():
        """Get Lightroom adapter status, including whether it is MOCK."""
        return call('lightroom_status')
    @server.tool()
    def lightroom_import_verified(task_id: str):
        """Run only registration from an already approved plan, useful to resume. Normally photo_execute_import runs all stages; a stage absent from the plan is denied."""
        return call('execute_lightroom', task_id=task_id, stages=['lr_register'])
    @server.tool()
    def lightroom_apply_preset(task_id: str, preset_id: str):
        """Run only preset application from an already approved plan, useful to resume. Normally photo_execute_import runs all stages; a stage absent from the plan is denied."""
        return call('execute_lightroom', task_id=task_id, stages=['lr_preset'], preset_id=preset_id)
    @server.tool()
    def lightroom_export_preview(task_id: str):
        """Run preview export and verification from an already approved plan, useful to resume. Normally photo_execute_import runs all stages; a stage absent from the plan is denied."""
        return call('execute_lightroom', task_id=task_id, stages=['lr_export', 'preview_verify'])
    @server.tool()
    def photo_verify_preview(task_id: str):
        """Verify the latest preview files for a task and report discrepancies."""
        return call('verify_preview', task_id=task_id)
    return server


def main(home, actor='ai:mcp', scopes=None):
    create_server(home, actor, scopes).run()
