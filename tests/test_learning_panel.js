const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../custom_components/hanjoo_ir/frontend/hanjoo-ir-panel.js'), 'utf8');
const start = source.indexOf('  async beginCapture(payload)');
const end = source.indexOf('  async learnCommand(', start);
const Panel = new Function(`return class { ${source.slice(start, end)} }`)();
async function run(rejectOld) {
  const p = new Panel();p.render=()=>{};p.errText=err=>err.message;
  const pending=[];const discarded=[];
  p.ws=(type,payload)=> {
    if(type==='device/discard_capture'){discarded.push(payload.token);return Promise.resolve();}
    return new Promise((resolve,reject)=>pending.push({resolve,reject}));
  };
  const old=p.beginCapture({deviceId:'old',commandId:'first'});
  p._learnDialog=null;
  const current=p.beginCapture({deviceId:'new',commandId:'second'});
  if(rejectOld)pending[0].reject(new Error('old capture cancelled'));
  else pending[0].resolve({token:'old-token'});
  await old;
  assert.equal(p._learnDialog.deviceId,'new');assert.equal(p._learnDialog.stage,'waiting');
  assert.deepEqual(discarded,rejectOld?[]:['old-token']);
  pending[1].resolve({token:'new-token'});await current;
  assert.equal(p._learnDialog.capture.token,'new-token');
}
(async()=>{await run(false);await run(true);console.log('PASS: stale capture result and error cannot overwrite a new learning session');})().catch(err=>{console.error(err);process.exitCode=1;});
