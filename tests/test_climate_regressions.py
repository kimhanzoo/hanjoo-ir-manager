import ast, asyncio, logging, math, time
from datetime import datetime
from pathlib import Path
from enum import StrEnum, IntFlag
from typing import Any
from copy import deepcopy
from types import SimpleNamespace

base=Path(__file__).resolve().parents[1] / 'custom_components/hanjoo_ir'
def load_class(path, name, env):
    tree=ast.parse(path.read_text())
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==name)
    mod=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),node],type_ignores=[])
    exec(compile(ast.fix_missing_locations(mod),str(path),'exec'),env)
    return env[name]
class Error(Exception):pass
me={'DEFAULT_LEARN_TIMEOUT':20,'DEFAULT_FREQUENCY':38000,'DEVICE_TYPE_CLIMATE':'climate','callback':lambda f:f,'Any':Any,'time':time,'deepcopy':deepcopy,'HomeAssistantError':Error,'HanJooCoreError':Error}
Manager=load_class(base/'manager.py','HanJooIRManager',me)
class Mode(StrEnum):
    OFF='off';AUTO='auto';HEAT='heat';COOL='cool';HEAT_COOL='heat_cool';DRY='dry';FAN_ONLY='fan_only'
class Feature(IntFlag):
    TURN_ON=1;TURN_OFF=2;TARGET_TEMPERATURE=4;FAN_MODE=8;SWING_MODE=16;SWING_HORIZONTAL_MODE=32;PRESET_MODE=64
class Base:
    def __init__(self,manager,device_id,suffix):self.manager=manager;self.device_id=device_id;self.hass=SimpleNamespace();self.entity_id='climate.test'
    @property
    def device(self):return self.manager.device
    def async_write_ha_state(self):pass
    async def async_added_to_hass(self):pass
    def async_on_remove(self,fn):pass
    @property
    def hvac_modes(self):return self._attr_hvac_modes
class Climate:pass
class Restore:pass
scheduled=[]
def call_later(hass,delay,fn):
    slot={'delay':delay,'fn':fn,'cancelled':False};scheduled.append(slot)
    return lambda:slot.update(cancelled=True)
ce={'HanJooEntity':Base,'ClimateEntity':Climate,'RestoreEntity':Restore,'Any':Any,'HVACMode':Mode,'ClimateEntityFeature':Feature,'UnitOfTemperature':SimpleNamespace(CELSIUS='C',FAHRENHEIT='F'),'HomeAssistantError':Error,'time':time,'math':math,'datetime':datetime,'async_call_later':call_later,'_LOGGER':logging.getLogger('test'),'_PRESET_COMMANDS':('turbo','quiet','econo','sleep','clean')}
tree=ast.parse((base/'climate.py').read_text())
helpers=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
assign=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_MODE_ALIASES' for t in n.targets))
exec(compile(ast.Module(body=[assign]+helpers,type_ignores=[]),'helpers','exec'),ce)
Entity=load_class(base/'climate.py','HanJooClimate',ce)

async def main():
    m=Manager.__new__(Manager);m._rx_decode_tokens={'d':2};m._rx_states={};m._rx_sequence=0;m._listeners=set()
    assert m._canonical_native_hvac({})=={}
    state=m._canonical_native_hvac({'mode':1,'fanspeed':3,'swingv':0,'swingh':2,'degrees':25})
    assert (state['mode'],state['fan'],state['swing'],state['swing_horizontal'],state['temp'])==('cool','medium','auto','left',25)
    assert m._normalize_rx_timings([-10000,9000,-4500,560,-560])==[9000,-4500,560,-560]
    assert m._normalize_rx_timings([9000,4500,560,560])==[9000,-4500,560,-560]
    class Core:
        async def decode(self,p,t):return {'mode':'cool','temp':t[0]}
    m.core=Core()
    await m._async_decode_protocol_signal('d',{},'rx',[20],1)
    assert not m._rx_states # older RPC completion cannot overwrite newer capture
    await m._async_decode_protocol_signal('d',{},'rx',[26],2)
    assert m._rx_states['d']['temp']==26
    a={'mode':'cool','fan':'auto','swing':'off','temp':25,'swing_horizontal':'left','preset':'quiet'}
    b=dict(a,swing_horizontal='right')
    assert m._climate_key(a)!=m._climate_key(b)
    m.device={'type':'climate','climate':{'modes':['cool'],'min_temp':16,'max_temp':30,'fan_modes':['auto'],'swing_modes':['off','on'],'cells':[dict(a,codes=[{'format':'raw','timings':[100,-100,100,-100]}])]},'commands':{}}
    e=Entity(m,'d')
    e._apply_received_state({'type':'climate','sequence':1,'mode':'cool','temp':24})
    e._attr_target_temperature=27
    e._apply_received_state({'type':'climate','sequence':1,'mode':'cool','temp':24})
    assert e._attr_target_temperature==27 # an unrelated notify must not replay old remote state
    e._apply_received_state({'type':'climate','sequence':2,'mode':'off','power':False})
    e._apply_received_state({'type':'climate','sequence':3,'power':True})
    assert e._attr_hvac_mode==Mode.COOL
    await e.async_set_timer(30,'off');first=scheduled[-1]
    assert 1799<=first['delay']<=1800
    await e.async_set_timer(10,'on');assert first['cancelled']
    await e.async_set_timer(0);assert scheduled[-1]['cancelled'] and e._timer_deadline is None
    try:await e.async_set_timer(float('nan'));assert False
    except Error:pass
    calls=[]
    async def off():calls.append('off')
    e.async_turn_off=off
    await e.async_set_timer(1)
    await scheduled[-1]['fn'](datetime.now())
    assert calls==['off'] and e._timer_deadline is None
    async def fail():raise Error('offline')
    e.async_turn_off=fail
    await e.async_set_timer(1)
    await scheduled[-1]['fn'](datetime.now())
    assert e._timer_error=='offline'
    async def restored():return SimpleNamespace(state='cool',attributes={'hanjoo_timer_deadline':time.time()+300,'hanjoo_timer_action':'off'})
    e.async_get_last_state=restored
    ce.update(ATTR_TEMPERATURE='temperature',ATTR_FAN_MODE='fan_mode',ATTR_SWING_MODE='swing_mode',ATTR_SWING_HORIZONTAL_MODE='swing_horizontal_mode',ATTR_PRESET_MODE='preset_mode')
    await e.async_added_to_hass()
    assert 299<=scheduled[-1]['delay']<=300
    e._cancel_timer_callback()
    async def expired():return SimpleNamespace(state='off',attributes={'hanjoo_timer_deadline':time.time()-300,'hanjoo_timer_action':'on'})
    fresh=Entity(m,'d');fresh.async_get_last_state=expired
    before=len(scheduled);await fresh.async_added_to_hass();assert len(scheduled)==before
    # Learn keeps both horizontal swing states instead of replacing a cell.
    m.data={'devices':{'d':m.device}};m._capture_save_lock=asyncio.Lock();m._pending_captures={};m._get_capture=lambda *args:{'format':'raw','timings':[100,-100,100,-100]}
    async def save():pass
    m.async_save=save
    for horizontal in ('left','right'):
        await m.save_captured_climate_state('d','x',mode='cool',temp=25,fan='auto',swing='off',swing_horizontal=horizontal,preset='quiet')
    assert len(m.device['climate']['cells'])==2
    print('PASS: normalization, enum mapping, empty decode, stale RPC, state sequence, power ON, dimensions, timer replacement/cancel/execute/error/validation, learning distinct cells')
asyncio.run(main())
