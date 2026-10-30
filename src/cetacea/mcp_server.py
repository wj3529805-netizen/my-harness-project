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
    def photo_list_orders(): return call('list_orders')
    @server.tool()
    def photo_list_sources(): return call('list_sources')
    @server.tool()
    def photo_scan_source(source_id: str): return call('scan_source', source_id=source_id)
    @server.tool()
    def photo_plan_import(order_id: str, photographer_id: str, source_id: str, batch_label: str | None = None, preset_id: str | None = None, stages: list[str] | None = None):
        return call('plan_import', order_id=order_id, photographer_id=photographer_id, source_id=source_id, batch_label=batch_label, preset_id=preset_id, stages=stages)
    @server.tool()
    def photo_execute_import(task_id: str): return call('execute', task_id=task_id)
    @server.tool()
    def photo_get_task(task_id: str): return call('get_task', task_id=task_id)
    @server.tool()
    def photo_cancel_task(task_id: str): return call('cancel', task_id=task_id)
    @server.tool()
    def photo_retry_task(task_id: str): return call('retry', task_id=task_id)
    @server.tool()
    def photo_list_assets(task_id: str | None = None, batch_id: str | None = None): return call('list_assets', task_id=task_id, batch_id=batch_id)
    @server.tool()
    def lightroom_get_status(): return call('lightroom_status')
    @server.tool()
    def lightroom_import_verified(task_id: str): return call('execute_lightroom', task_id=task_id, stages=['lr_register'])
    @server.tool()
    def lightroom_apply_preset(task_id: str, preset_id: str): return call('execute_lightroom', task_id=task_id, stages=['lr_preset'], preset_id=preset_id)
    @server.tool()
    def lightroom_export_preview(task_id: str): return call('execute_lightroom', task_id=task_id, stages=['lr_export', 'preview_verify'])
    @server.tool()
    def photo_verify_preview(task_id: str): return call('verify_preview', task_id=task_id)
    return server


def main(home, actor='ai:mcp', scopes=None):
    create_server(home, actor, scopes).run()
