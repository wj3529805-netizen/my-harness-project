"""Final read-only project-MCP status and designated test-catalog inventory."""
import asyncio,json
from pathlib import Path
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters,stdio_client
from run_real_validation import ROOT,DATA,OUT,workbench,save
assert (DATA/'home/config.json').exists()
w=workbench()  # validates source code, test paths, and lsof catalog identity
async def main():
 p=StdioServerParameters(command=str(ROOT/'.venv/bin/cetacea'),args=['--home',str(DATA/'home'),'mcp-serve'])
 async with stdio_client(p) as streams:
  async with ClientSession(*streams,read_timeout_seconds=45) as s:
   await s.initialize()
   r=await s.call_tool('lightroom_get_status',{})
   save('real-mcp-status.json',r.model_dump())
   assert not r.is_error
   payload=r.structured_content
   assert payload['mock'] is False and 'connected (real read-only' in payload['status'],payload
   print(json.dumps(payload),flush=True)
asyncio.run(main())
r=w.adapter.call_tool('search_photos',{'limit':20})
save('final-test-catalog-inventory.json',r)
assert r['count']==4 and len({p['id'] for p in r['photos']})==4
metadata=w.adapter.call_tool('get_photo_metadata',{'photo_ids':[str(p['id']) for p in r['photos']]})
save('final-test-catalog-metadata.json',metadata)
assert not metadata['missing'] and len(metadata['photos'])==4
assert all(Path(p['path']).is_relative_to(DATA/'library') for p in metadata['photos'])
print('Four test photos, all inside acceptance-data/library',flush=True)
