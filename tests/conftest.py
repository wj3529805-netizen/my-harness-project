import os
import pytest
from cetacea.core import Workbench
@pytest.fixture
def env(tmp_path):
    card=tmp_path/'card'; card.mkdir()
    w=Workbench.init(tmp_path/'home',tmp_path/'library',tmp_path/'preview')
    w.add_source('card',card); w.create_order('order','Order'); w.add_photographer('p','Photographer')
    return w,card
@pytest.fixture
def planned(env):
    w,card=env; (card/'DSC0001.RAF').write_bytes(os.urandom(128))
    return w,w.plan_import('order','p','card')
def run(w,t):
    w.approve(t['task_id'],t['plan_digest']); return w.execute(t['task_id'])
