import argparse
import json
import os
from .core import Workbench

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('--home',default=os.environ.get('CETACEA_HOME')); p.add_argument('--json',action='store_true')
    sub=p.add_subparsers(dest='command',required=True)
    def command(name,args=()):
        q=sub.add_parser(name); q.add_argument('--home',default=argparse.SUPPRESS); q.add_argument('--json',action='store_true',default=argparse.SUPPRESS)
        for arg in args: q.add_argument(arg)
        return q
    q=command('init'); q.add_argument('--library',required=True); q.add_argument('--preview',required=True)
    for group, actions in [('source',{'add':['source_id','path'],'list':[]}),('order',{'create':['order_id','title'],'list':[]}),('photographer',{'add':['photographer_id','name']}),('preset',{'add':['preset_id','label']}),('task',{'show':['task_id'],'list':[]})]:
        q=command(group); ss=q.add_subparsers(dest='action',required=True)
        for action,args in actions.items():
            s=ss.add_parser(action); s.add_argument('--json',action='store_true',default=argparse.SUPPRESS); s.add_argument('--home',default=argparse.SUPPRESS)
            for a in args: s.add_argument(a)
    command('scan',['source_id'])
    q=command('plan',['order_id','photographer_id','source_id']); q.add_argument('--batch-label'); q.add_argument('--preset-id'); q.add_argument('--stages',nargs='+')
    command('approve',['task_id','plan_digest'])
    for name in ['execute','cancel','retry']: command(name,['task_id'])
    q=command('assets'); q.add_argument('--task-id'); q.add_argument('--batch-id')
    command('recover')
    command('lr-status')
    command('verify-preview',['task_id'])
    command('report',['task_id'])
    a=p.parse_args(argv); v=vars(a); home=v.pop('home'); output_json=v.pop('json'); cmd=v.pop('command'); action=v.pop('action',None)
    if not home: p.error('--home or CETACEA_HOME required')
    if cmd=='init': Workbench.init(home,**v); result={'initialized':True}
    else:
        w=Workbench(home)
        method={('source','add'):'add_source',('source','list'):'list_sources',('order','create'):'create_order',('order','list'):'list_orders',('photographer','add'):'add_photographer',('preset','add'):'add_preset',('task','show'):'get_task',('task','list'):'list_tasks'}.get((cmd,action),{'scan':'scan_source','plan':'plan_import','assets':'list_assets','lr-status':'lightroom_status','verify-preview':'verify_preview'}.get(cmd,cmd))
        result=getattr(w,method)(**v)
    print(json.dumps(result,indent=None if output_json else 2))
if __name__=='__main__': main()
