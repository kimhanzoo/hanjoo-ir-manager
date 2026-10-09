const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../custom_components/hanjoo_ir/frontend/hanjoo-ir-panel.js'),'utf8');
const methods=source.slice(source.indexOf('  async openJsonEditor('),source.indexOf('  async importFile('));
const Panel=new Function(`return class { ${methods} }`)();
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
(async()=>{
  const p=new Panel();const requests=[];p.render=()=>{};p.errText=e=>e.message;p.toast=()=>{};p.loadAll=async()=>{};p.openDevice=async()=>{};
  p.ws=async(type,data)=>{requests.push({type,data});if(type.endsWith('/export'))return {text:'{"format":"hanjoo-ir-profile/1"}'};throw Error('invalid JSON');};
  await p.openJsonEditor('device','old');p._jsonEditor.text='broken';await p.saveJsonEditor();
  assert.equal(requests.at(-1).type,'device/update_json');assert.equal(requests.at(-1).data.device_id,'old');
  assert.equal(p._jsonEditor.text,'broken');assert.equal(p._jsonEditor.error,'invalid JSON');assert.equal(p._jsonEditor.saving,false);
  const file=deferred();const loading=p.loadJsonEditorFile({target:{files:[{size:10,text:()=>file.promise}]}});
  const count=requests.length;await p.saveJsonEditor();assert.equal(requests.length,count,'save blocked during file read');
  p._jsonEditor={text:'new dialog'};file.resolve('stale file');await loading;assert.equal(p._jsonEditor.text,'new dialog');
  await p.openJsonEditor('profile','profile-id');p._jsonEditor.text='edited';p.ws=async(type,data)=>requests.push({type,data});
  await p.saveJsonEditor();assert.equal(p._jsonEditor,null);assert.deepEqual(requests.at(-1),{type:'profile/update_json',data:{profile_id:'profile-id',text:'edited'}});
  console.log('PASS: JSON editor target IDs, errors preserve draft, file-read/save ordering, stale file isolation, successful save');
})().catch(err=>{console.error(err);process.exitCode=1;});
