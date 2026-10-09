"""Learning/storage/replay regressions; HA transport and Store are test doubles."""
import ast
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace
import time
import unicodedata
import unittest
import uuid

BASE = Path(__file__).resolve().parents[1] / 'custom_components/hanjoo_ir'
pkg = ModuleType('learning_test'); pkg.__path__ = [str(BASE)];sys.modules[pkg.__name__] = pkg

def module(name):
    spec = importlib.util.spec_from_file_location(f'learning_test.{name}', BASE / f'{name}.py')
    result = importlib.util.module_from_spec(spec);sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result

const = module('const'); ir = module('ir_code')
class Error(Exception): pass
env = {**vars(const), 'asyncio': asyncio, 'deepcopy': deepcopy, 'time': time,
       're': re, 'unicodedata': unicodedata, 'uuid': uuid, 'SimpleNamespace': SimpleNamespace,
       'callback': lambda f:f, 'HomeAssistantError': Error,
       'code_from_timings': ir.code_from_timings, 'command_from_code': ir.command_from_code}
tree = ast.parse((BASE / 'manager.py').read_text())
nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and getattr(n, 'name', '') in ('HanJooIRManager', '_slug')]
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')],level=0), *nodes], type_ignores=[])), str(BASE / 'manager.py'), 'exec'), env)
Manager = env['HanJooIRManager']
WAVE = [9000, -4500] + [560, -560, 560, -1690] * 16 + [560, -50000]

class LearningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        m = self.m = Manager.__new__(Manager)
        m.data = {'devices': {}};m.hass = SimpleNamespace();m._pending_captures = {}
        m._learn_lock = asyncio.Lock();m._capture_save_lock = asyncio.Lock();m._send_lock = asyncio.Lock()
        m._learning_receivers = set();m._active_capture_futures = {};m._rx_decode_tokens = {};m._suppress_receivers_until = {}
        self.persisted = {};self.sent = []
        async def save(): self.persisted = json.loads(json.dumps(m.data))
        m.async_save = save
        async def send(hass, emitter, command):
            self.sent.append((emitter, command.modulation, command.get_raw_timings()))
            await asyncio.sleep(0)
        env['async_send_command'] = send
        self.device_id = await m.create_custom_device(name='Manual', kind='custom', emitters=['infrared.tx'], receiver='infrared.rx')
        self.command_id = await m.add_custom_command(self.device_id, 'New command')

    def pending(self, token='t', wave=WAVE):
        self.m._pending_captures[token] = {'device_id': self.device_id, 'code': ir.code_from_timings(wave), 'created': asyncio.get_running_loop().time(), 'quality': 'good'}
        return token

    async def test_new_device_save_restart_and_replay(self):
        m = self.m
        signal = SimpleNamespace(timings=WAVE, modulation=None)
        async def capture(*args):return signal
        m._capture_signal = capture
        preview = await m.capture_for_preview(self.device_id)
        self.assertTrue(preview['can_save'])
        await m.test_captured_command(self.device_id, preview['token'])
        self.assertFalse(m.get_devices()[self.device_id]['commands'][self.command_id]['codes'])
        self.assertIn(preview['token'], m._pending_captures)
        await m.save_captured_command(self.device_id,self.command_id,preview['token'])
        m.data = json.loads(json.dumps(self.persisted))
        await m.send_command(self.device_id,self.command_id)
        self.assertEqual(self.sent, [('infrared.tx',38000,WAVE)] * 2)
        self.assertNotIn(preview['token'],m._pending_captures)

    async def test_relearn_cancel_keeps_old_then_save_replaces(self):
        await self.m.save_captured_command(self.device_id,self.command_id,self.pending())
        changed = [value * 2 if abs(value) < 50000 else value for value in WAVE]
        self.pending('cancel',changed);self.m.discard_capture('cancel')
        await self.m.send_command(self.device_id,self.command_id)
        self.pending('new',changed)
        await self.m.save_captured_command(self.device_id,self.command_id,'new')
        await self.m.send_command(self.device_id,self.command_id)
        self.assertEqual([row[2] for row in self.sent],[WAVE,changed])

    async def test_failed_storage_preserves_old_and_allows_retry(self):
        await self.m.save_captured_command(self.device_id,self.command_id,self.pending())
        old = deepcopy(self.m.data)
        self.pending('new',[800,-800]*12)
        original = self.m.async_save
        async def fail():raise OSError('disk full')
        self.m.async_save = fail
        with self.assertRaises(OSError):await self.m.save_captured_command(self.device_id,self.command_id,'new')
        self.assertEqual(self.m.data,old);self.assertIn('new',self.m._pending_captures)
        self.m.async_save = original
        await self.m.save_captured_command(self.device_id,self.command_id,'new')
        self.assertNotIn('new',self.m._pending_captures)

    async def test_wrong_device_does_not_consume_capture(self):
        self.pending()
        other = await self.m.create_custom_device(name='Other',kind='custom',emitters=['infrared.tx'],receiver='infrared.rx')
        command = await self.m.add_custom_command(other,'test')
        with self.assertRaises(Error):await self.m.save_captured_command(other,command,'t')
        self.assertIn('t',self.m._pending_captures)

    async def test_concurrent_multiframe_press_is_not_interleaved(self):
        d = self.m.get_devices()[self.device_id]
        a = {'codes':[ir.code_from_timings([100,-100]*12),ir.code_from_timings([200,-200]*12)]}
        b = {'codes':[ir.code_from_timings([300,-300]*12)]}
        await asyncio.gather(self.m._send_item(d,a),self.m._send_item(d,b))
        self.assertEqual([row[2][0] for row in self.sent],[100,200,300])

    async def test_invalid_later_code_does_not_partially_send(self):
        d = self.m.get_devices()[self.device_id]
        with self.assertRaises(ir.IRCodeError):
            await self.m._send_item(d,{'codes':[ir.code_from_timings(WAVE),{'format':'broken'}]})
        self.assertEqual(self.sent,[])

    async def test_subscription_failure_releases_receiver(self):
        def fail(*args):raise Error('receiver unavailable')
        env['async_subscribe_receiver'] = fail
        with self.assertRaises(Error):await self.m._capture_signal(self.m.get_devices()[self.device_id],2)
        self.assertEqual(self.m._learning_receivers,set());self.assertEqual(self.m._active_capture_futures,{})

    async def test_capture_cancel_cleans_subscription(self):
        subscribed = asyncio.Event();unsubscribed = []
        def subscribe(*args):subscribed.set();return lambda:unsubscribed.append(True)
        env['async_subscribe_receiver'] = subscribe
        task = asyncio.create_task(self.m._capture_signal(self.m.get_devices()[self.device_id],2))
        await subscribed.wait();self.m.cancel_capture_wait(self.device_id)
        with self.assertRaises(Error):await task
        self.assertEqual(unsubscribed,[True]);self.assertFalse(self.m._active_capture_futures)

    async def test_real_capture_collects_events_and_replays_all_timings(self):
        subscribed = asyncio.Event();callbacks = [];removed = []
        def subscribe(hass, receiver, callback):
            callbacks.append(callback);subscribed.set();return lambda:removed.append(True)
        env['async_subscribe_receiver'] = subscribe
        task = asyncio.create_task(self.m.capture_for_preview(self.device_id,2))
        await subscribed.wait()
        callbacks[0](SimpleNamespace(timings=WAVE[:34],modulation=40000))
        callbacks[0](SimpleNamespace(timings=WAVE[34:],modulation=40000))
        preview = await task
        self.assertEqual(preview['frame_count'],2)
        await self.m.save_captured_command(self.device_id,self.command_id,preview['token'])
        await self.m.send_command(self.device_id,self.command_id)
        self.assertEqual(self.sent,[('infrared.tx',40000,WAVE)])
        self.assertEqual(removed,[True])

    async def test_climate_failed_storage_preserves_cells_and_token(self):
        d = self.m.get_devices()[self.device_id]
        d['type'] = 'climate';d['climate'] = {'cells': [], 'off': None}
        old = deepcopy(d['climate']);self.pending()
        async def fail():raise OSError('disk full')
        self.m.async_save = fail
        with self.assertRaises(OSError):
            await self.m.save_captured_climate_state(self.device_id,'t',mode='cool',temp=25,fan='auto',swing='off')
        self.assertEqual(d['climate'],old);self.assertIn('t',self.m._pending_captures)

    async def test_create_response_waits_for_reload(self):
        node = next(n for n in ast.parse((BASE/'websocket_api.py').read_text()).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='ws_device_create_custom')
        node.decorator_list=[]
        started = asyncio.Event();finish = asyncio.Event();responses=[]
        async def reload(entry):started.set();await finish.wait();return True
        hass = SimpleNamespace(config_entries=SimpleNamespace(async_reload=reload))
        local = {'_runtime':lambda h:(self.m,'entry'), 'HomeAssistantError':Error,
                 '_error':lambda *args: self.fail(str(args[-1])), '_reload_soon':lambda *args: self.fail('deferred reload')}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'websocket','exec'),local)
        conn=SimpleNamespace(send_result=lambda *args:responses.append(args))
        task=asyncio.create_task(local['ws_device_create_custom'](hass,conn,{'id':1,'name':'Second','kind':'custom','emitters':['infrared.tx']}))
        await started.wait();self.assertEqual(responses,[])
        finish.set();await task;self.assertEqual(responses[0][1]['device_id'],'second')

    async def test_invalid_frequency_rejected_before_save(self):
        with self.assertRaises(ir.IRCodeError):ir.code_from_timings(WAVE,1000)

    async def test_signed_idle_and_malformed_phase(self):
        self.assertEqual(ir.command_from_code(ir.code_from_timings([-200000,*WAVE])).get_raw_timings(),WAVE)
        with self.assertRaises(ir.IRCodeError):ir.code_from_timings([100,-100,-100,100])

if __name__ == '__main__':unittest.main()
