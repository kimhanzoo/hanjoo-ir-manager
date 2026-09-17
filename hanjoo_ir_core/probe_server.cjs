"use strict";

/*
 * Public irtxrx exhaustive probe sidecar.
 *
 * This service contains no proprietary HanJoo protocol implementation. It
 * exposes exhaustive per-protocol probing over the public irtxrx runtime so
 * a permissive earlier decoder cannot hide a later correct decoder.
 */
const http = require("node:http");
const { spawnSync } = require("node:child_process");
const { createRequire } = require("node:module");
const requireFromRuntime = createRequire("/opt/hanjoo/package.json");
const ir = requireFromRuntime("irtxrx");

const PORT = Number(process.argv[2] || 8101);
const VERSION = process.env.HANJOO_VERSION || "0.6.4";
const MAX_TIMINGS = 20000;

function safe(value) {
  if (typeof value === "bigint") return value.toString();
  if (value instanceof Uint8Array) return Array.from(value);
  if (Array.isArray(value)) return value.map(safe);
  if (value && typeof value === "object") {
    const out = {};
    for (const [k, v] of Object.entries(value)) out[k] = safe(v);
    return out;
  }
  return value;
}

function normalizeTimings(values) {
  if (!Array.isArray(values)) return [];
  const out = [];
  for (const value of values.slice(0, MAX_TIMINGS)) {
    const n = Math.abs(Number(value));
    if (Number.isFinite(n) && n > 0) out.push(Math.round(n));
  }
  return out;
}

function richness(canonical, state) {
  const src = canonical && typeof canonical === "object" ? canonical : state;
  if (!src || typeof src !== "object") return 0;
  const keys = [
    "power", "mode", "temp", "temperature", "fan", "fanSpeed",
    "swing", "swingV", "swingH"
  ];
  return keys.reduce(
    (count, key) => count + (src[key] !== undefined && src[key] !== null ? 1 : 0),
    0
  );
}

function probe(timings) {
  const t = normalizeTimings(timings);
  if (t.length < 4) {
    return { timings: t.length, registered_protocols: (ir.REGISTERED_PROTOCOLS || []).length, matches: [] };
  }

  const matches = [];
  for (const protocol of ir.REGISTERED_PROTOCOLS || []) {
    try {
      const result = ir.decode(t, { protocol });
      if (!result) continue;

      const info = ir.getProtocolInfo ? ir.getProtocolInfo(protocol) : undefined;
      let canonical;
      try {
        canonical = ir.toCanonical ? ir.toCanonical(protocol, result.state) : undefined;
      } catch (_) {}

      let canEncode = false;
      try {
        canEncode = !!(ir.canEncode && ir.canEncode(protocol));
      } catch (_) {}

      matches.push({
        protocol,
        brand: info?.brand || null,
        type: info?.type || null,
        structured: !!canonical,
        can_encode: canEncode,
        richness: richness(canonical, result.state),
        canonical: safe(canonical || null),
        state: safe(result.state || null),
      });
    } catch (_) {
      // Protocol mismatch is expected.
    }
  }

  matches.sort((a, b) =>
    Number(b.structured) - Number(a.structured) ||
    Number(b.type === "ac") - Number(a.type === "ac") ||
    b.richness - a.richness ||
    Number(b.can_encode) - Number(a.can_encode) ||
    String(a.protocol).localeCompare(String(b.protocol))
  );

  return {
    timings: t.length,
    registered_protocols: (ir.REGISTERED_PROTOCOLS || []).length,
    matches,
  };
}


function probeIrremoteEsp8266(timings) {
  const t = normalizeTimings(timings);
  if (t.length < 4) return { ok:true, coverage:128, match:null };
  const p = spawnSync("/opt/hanjoo/ir8266_probe", [], {
    input: t.join(",") + "\n", encoding:"utf8", timeout:2500, maxBuffer:1024*1024
  });
  if (p.error) return { ok:false, coverage:128, error:String(p.error.message || p.error), match:null };
  if (p.status !== 0) return { ok:false, coverage:128, error:String(p.stderr || `exit ${p.status}`), match:null };
  try { return JSON.parse(p.stdout || "{}"); }
  catch (e) { return { ok:false, coverage:128, error:`invalid native decoder JSON: ${e.message}`, match:null }; }
}
function inferBrandFromProtocol(name) {
  const p = String(name || "").toUpperCase();
  const rules = [
    ["DAIKIN","Daikin"],["PANASONIC","Panasonic"],["LG","LG"],["MITSUBISHI","Mitsubishi"],
    ["SAMSUNG","Samsung"],["GREE","Gree"],["MIDEA","Midea"],["HAIER","Haier"],["TOSHIBA","Toshiba"],
    ["FUJITSU","Fujitsu"],["HITACHI","Hitachi"],["CARRIER","Carrier"],["SHARP","Sharp"],["SANYO","Sanyo"],
    ["WHIRLPOOL","Whirlpool"],["ELECTRA","Electra"],["KELVINATOR","Kelvinator"],["ARGO","Argo"],
    ["COOLIX","Coolix"],["AIRWELL","Airwell"],["NEOCLIMA","Neoclima"],["VESTEL","Vestel"],["TECO","Teco"],
    ["TCL","TCL"],["BOSCH","Bosch"],["YORK","York"],["EUROM","Eurom"],["SONY","Sony"],["NEC","NEC"],
    ["JVC","JVC"],["DENON","Denon"],["RC5","Philips/RC5"],["RC6","Philips/RC6"],["EPSON","Epson"]
  ];
  for (const [token,brand] of rules) if (p.includes(token)) return brand;
  return null;
}

function send(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(data),
  });
  res.end(data);
}

const server = http.createServer((req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    return send(res, 200, {
      ok: true,
      service: "hanjoo-public-codec-probe",
      version: VERSION,
      irtxrx_protocols: (ir.REGISTERED_PROTOCOLS || []).length,
      irremoteesp8266_protocols: 128,
      recognition_coverage: 128,
    });
  }

  const isProbe = req.method === "POST" && (req.url === "/v1/probe" || req.url === "/v1/probe-all");
  if (!isProbe) return send(res, 404, { error:"not_found" });

  let raw = "";
  req.setEncoding("utf8");
  req.on("data", chunk => {
    raw += chunk;
    if (raw.length > 4_000_000) req.destroy();
  });
  req.on("end", () => {
    try {
      const payload = JSON.parse(raw || "{}");
      const timings = payload.timings || [];
      const irtxrx = probe(timings);
      if (req.url === "/v1/probe") return send(res, 200, irtxrx);
      const upstream = probeIrremoteEsp8266(timings);
      if (upstream?.match) upstream.match.brand = inferBrandFromProtocol(upstream.match.protocol);
      return send(res, 200, {
        timings: normalizeTimings(timings).length,
        recognition_coverage:128,
        irtxrx,
        irremoteesp8266:upstream,
      });
    } catch (err) {
      return send(res, 400, { error: String(err?.message || err) });
    }
  });
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(
    `[HanJoo IR Core] exhaustive codec probe listening on 0.0.0.0:${PORT}; protocols=${(ir.REGISTERED_PROTOCOLS || []).length}`
  );
});
