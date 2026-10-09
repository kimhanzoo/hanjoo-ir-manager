"""Portable JSON and live replacement tests using production parsers/methods."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
import test_learning_regressions as learning
from test_learning_regressions import module, env, WAVE, Error

imports = module('importers')
env.update(import_profiles_text=imports.import_profiles_text, import_profile_text=imports.import_profile_text,
           export_hanjoo_profile=imports.export_hanjoo_profile, export_hanjoo_library=imports.export_hanjoo_library)

class JsonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await learning.LearningTests.asyncSetUp(self)
        self.m.data['profiles']={};self.m._json_lock = asyncio.Lock();self.m.entry_id='entry'
        self.removed=[]
        env['er']=SimpleNamespace(async_get=lambda h:SimpleNamespace(async_remove=self.removed.append),
            async_entries_for_config_entry=lambda r,e:[SimpleNamespace(unique_id=f'entry_{self.device_id}_button_{self.command_id}',entity_id='button.old')])
        await self.m.save_captured_command(self.device_id,self.command_id,learning.LearningTests.pending(self))

    def text(self):return self.m.export_device(self.device_id)

    async def test_export_import_roundtrip_retains_wave_frequency_repeat(self):
        payload=json.loads(self.text());item=payload['profile']['commands'][self.command_id]
        item['codes'][0]['frequency']=40000;item['send_count']=3
        result=await self.m.import_profile(json.dumps(payload),'edited.json')
        saved=self.m.get_profile(result.profile['id'])
        self.assertEqual(saved['commands'][self.command_id],item)
        copy=await self.m.create_device_from_profile(profile_id=saved['id'],name='Imported',emitters=['infrared.other'],receiver='infrared.other_rx')
        await self.m.send_command(copy,self.command_id)
        self.assertEqual(self.sent,[('infrared.other',40000,WAVE)]*3)
        self.m.data=json.loads(json.dumps(self.persisted))
        self.assertEqual(json.loads(self.m.export_profile(saved['id']))['profile']['commands'][self.command_id],item)

    async def test_edit_device_add_command_preserves_routing_and_old_id(self):
        payload=json.loads(self.text());p=payload['profile'];p['commands']['added']={'name':'Mới','codes':[deepcopy(p['commands'][self.command_id]['codes'][0])],'send_count':1}
        p.update(id='different',emitter_entity_ids=['wrong'],receiver_entity_id='wrong')
        await self.m.update_device_json(self.device_id,json.dumps(payload))
        d=self.m.get_devices()[self.device_id]
        self.assertEqual(d['id'],self.device_id);self.assertEqual(d['emitter_entity_ids'],['infrared.tx']);self.assertEqual(d['receiver_entity_id'],'infrared.rx')
        await self.m.send_command(self.device_id,'added')
        self.assertEqual(self.sent,[('infrared.tx',38000,WAVE)]);self.assertIn(self.command_id,d['commands']);self.assertEqual(self.removed,[])

    async def test_removed_command_removes_only_its_entity(self):
        payload=json.loads(self.text());payload['profile']['commands']={}
        await self.m.update_device_json(self.device_id,json.dumps(payload))
        self.assertEqual(self.removed,['button.old'])

    async def test_device_type_change_rejected_without_mutation(self):
        old=deepcopy(self.m.data);payload=json.loads(self.text());payload['profile']['type']='fan'
        with self.assertRaises(Error):await self.m.update_device_json(self.device_id,json.dumps(payload))
        self.assertEqual(self.m.data,old)

    async def test_profile_update_keeps_id_does_not_overwrite_live_device(self):
        result=await self.m.import_profile(self.text());pid=result.profile['id']
        live=await self.m.create_device_from_profile(profile_id=pid,name='Copy',emitters=['infrared.tx'],receiver=None)
        payload=json.loads(self.m.export_profile(pid));payload['profile']['name']='Edited';payload['profile']['commands'][self.command_id]['codes'][0]['frequency']=40000
        await self.m.update_profile_json(pid,json.dumps(payload))
        self.assertEqual(self.m.get_profile(pid)['id'],pid);self.assertEqual(len(self.m.get_profiles()),1)
        self.assertEqual(self.m.get_devices()[live]['commands'][self.command_id]['codes'][0]['frequency'],38000)

    async def test_failed_edit_or_import_rolls_back(self):
        pid=(await self.m.import_profile(self.text())).profile['id'];old=deepcopy(self.m.data)
        async def fail():raise OSError('disk full')
        self.m.async_save=fail
        for operation in (self.m.import_profiles(self.text()),self.m.update_device_json(self.device_id,self.text()),self.m.update_profile_json(pid,self.text())):
            with self.assertRaises(OSError):await operation
            self.assertEqual(self.m.data,old)
        self.assertEqual(self.removed,[])

    async def test_single_import_rejects_bundle_before_writing(self):
        old=deepcopy(self.m.data);p=json.loads(self.text())['profile']
        with self.assertRaises(Error):await self.m.import_profile(imports.export_hanjoo_library([p,p]))
        self.assertEqual(self.m.data,old)

    async def test_bundle_invalid_later_row_is_atomic(self):
        old=deepcopy(self.m.data);p=json.loads(self.text())['profile'];bad=deepcopy(p);bad['commands'][self.command_id]['codes']=[{'format':'bad'}]
        with self.assertRaises((imports.ProfileImportError,ValueError)):
            await self.m.import_profiles(imports.export_hanjoo_library([p,bad]))
        self.assertEqual(self.m.data,old)

    async def test_empty_library_roundtrip(self):
        self.assertEqual(imports.import_profiles_text(imports.export_hanjoo_library([])),[])
        self.assertEqual(await self.m.import_profiles(imports.export_hanjoo_library([])),[])

    async def test_duplicate_keys_nonfinite_bad_types_and_repeats(self):
        invalid=['{"format":"hanjoo-ir-profile/1","format":"other"}',self.text().replace('38000','NaN',1)]
        for value in (0,-1,101,True,1.5,'2'):
            payload=json.loads(self.text());payload['profile']['commands'][self.command_id]['send_count']=value;invalid.append(json.dumps(payload))
        payload=json.loads(self.text());payload['profile']['fan']=[];invalid.append(json.dumps(payload))
        old=deepcopy(self.m.data)
        for text in invalid:
            with self.subTest(text=text[:80]):
                with self.assertRaises(imports.ProfileImportError):await self.m.import_profiles(text)
        self.assertEqual(self.m.data,old)

    async def test_climate_dimensions_and_dynamic_engine_roundtrip(self):
        p=json.loads(self.text())['profile'];p['type']='climate'
        code=p['commands'][self.command_id]['codes'][0]
        p['climate']={'min_temp':16,'max_temp':30,'precision':0.5,'off':{'codes':[code],'send_count':1},'on':{'codes':[code],'send_count':1},'cells':[{'mode':'cool','temp':25.5,'fan':'auto','swing':'off','swing_horizontal':'left','preset':'quiet','codes':[code],'send_count':1}]}
        p['protocol_engine']={'protocol':'DAIKIN','variant':'example'}
        result=imports.import_profile_text(imports.export_hanjoo_profile(p))
        self.assertEqual(result.profile['climate']['cells'],p['climate']['cells']);self.assertEqual(result.profile['climate']['off'],p['climate']['off']);self.assertEqual(result.profile['protocol_engine'],p['protocol_engine'])
        for field,value in [('precision',0),('modes','cool'),('min_temp',40)]:
            bad=deepcopy(p);bad['climate'][field]=value
            with self.assertRaises(imports.ProfileImportError):imports.import_profile_text(imports.export_hanjoo_profile(bad))

    async def test_new_fan_speed_not_hidden_by_declared_speeds(self):
        import ast
        from test_learning_regressions import BASE
        node=next(n for n in ast.parse((BASE/'fan.py').read_text()).body if isinstance(n,ast.ClassDef) and n.name=='HanJooFan')
        method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='_find_speed_commands')
        local={};exec(compile(ast.Module(body=[method],type_ignores=[]),'fan','exec'),local)
        commands={key:{'codes':[1]} for key in ('speed:low','speed:high','speed_3')}
        dummy=SimpleNamespace(device={'fan':{'speed_modes':['low']},'commands':commands})
        self.assertEqual(local['_find_speed_commands'](dummy),[('low','speed:low'),('high','speed:high'),('3','speed_3')])

    async def test_malformed_code_container_and_duplicate_climate_rejected(self):
        for value in ('',{},None):
            p=json.loads(self.text())['profile'];p['commands'][self.command_id]['codes']=value
            with self.assertRaises(imports.ProfileImportError):imports.import_profile_text(imports.export_hanjoo_profile(p))
        p=json.loads(self.text())['profile'];p['type']='climate'
        cell={'mode':'cool','temp':25,'codes':p['commands'][self.command_id]['codes']}
        p['climate']={'cells':[cell,dict(cell,temp=25.0)]}
        with self.assertRaises(imports.ProfileImportError):imports.import_profile_text(imports.export_hanjoo_profile(p))

    async def test_concurrent_add_waits_for_json_replacement(self):
        started=asyncio.Event();finish=asyncio.Event();save=self.m.async_save
        async def gated_save():
            started.set();await finish.wait();await save()
        self.m.async_save=gated_save
        replacement=asyncio.create_task(self.m.update_device_json(self.device_id,self.text()))
        await started.wait()
        added=asyncio.create_task(self.m.add_custom_command(self.device_id,'Concurrent'))
        await asyncio.sleep(0);self.assertFalse(added.done())
        finish.set();await replacement;command_id=await added
        self.assertIn(command_id,self.m.get_devices()[self.device_id]['commands'])

if __name__=='__main__':unittest.main()
