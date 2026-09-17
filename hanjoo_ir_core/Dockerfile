FROM alpine:3.22

RUN apk add --no-cache nodejs npm ca-certificates git g++ make binutils \
 && rm -rf /tmp/irtxrx-src /opt/hanjoo \
 && git clone --depth 1 --branch v0.21.0 https://github.com/0xPiyush/irtxrx.git /tmp/irtxrx-src \
 && cd /tmp/irtxrx-src \
 && npm install --ignore-scripts --no-audit --no-fund \
 && ./node_modules/.bin/tsc -p tsconfig.build.json \
 && ./node_modules/.bin/tsc -p tsconfig.cjs.json \
 && test -f dist/cjs/index.js \
 && printf '{"type":"commonjs"}' > dist/cjs/package.json \
 && mkdir -p /tmp/hanjoo-pack /opt/hanjoo \
 && npm pack --pack-destination /tmp/hanjoo-pack \
 && cd / \
 && printf '{"name":"hanjoo-ir-core-runtime","private":true}' > /opt/hanjoo/package.json \
 && npm install --prefix /opt/hanjoo --omit=dev --ignore-scripts --no-audit --no-fund /tmp/hanjoo-pack/irtxrx-0.21.0.tgz \
 && rm -rf /tmp/irtxrx-src /tmp/hanjoo-pack

COPY ir8266_probe.cpp /tmp/hanjoo-ir8266-probe.cpp
RUN git clone --depth 1 https://github.com/crankyoldgit/IRremoteESP8266.git /tmp/irremoteesp8266 \
 && cd /tmp/irremoteesp8266 \
 && git fetch --depth 1 origin 1e2f0f3ef0a93cbf2a8ddb2e95130f8f4c584b3f \
 && git checkout 1e2f0f3ef0a93cbf2a8ddb2e95130f8f4c584b3f \
 && g++ -O2 -std=gnu++11 -DUNIT_TEST -D_IR_LOCALE_=en-AU \
      -I/tmp/irremoteesp8266/src -I/tmp/irremoteesp8266/test \
      /tmp/hanjoo-ir8266-probe.cpp \
      /tmp/irremoteesp8266/src/IRrecv.cpp /tmp/irremoteesp8266/src/IRsend.cpp \
      /tmp/irremoteesp8266/src/IRtimer.cpp /tmp/irremoteesp8266/src/IRutils.cpp \
      /tmp/irremoteesp8266/src/IRtext.cpp /tmp/irremoteesp8266/src/ir_*.cpp \
      -o /opt/hanjoo/ir8266_probe \
 && strip /opt/hanjoo/ir8266_probe \
 && rm -rf /tmp/irremoteesp8266 /tmp/hanjoo-ir8266-probe.cpp

# Protected recognition/fusion logic is reconstructed during image build.
# v0.6.4 deliberately runs it as CommonJS under Node instead of SEA because
# Node SEA changed CommonJS module semantics on HAOS/Alpine and caused the
# Brain process to exit with `require is not defined`.
COPY brain_payload/ /tmp/brain_payload/
RUN cat /tmp/brain_payload/part-*.txt | base64 -d > /opt/hanjoo/brain_runtime.cjs \
 && node --check /opt/hanjoo/brain_runtime.cjs \
 && chmod 500 /opt/hanjoo/brain_runtime.cjs \
 && rm -rf /tmp/brain_payload

COPY core_payload/ /opt/hanjoo/payload/
COPY core_runtime.protected.cjs /opt/hanjoo/core_runtime.cjs
COPY probe_server.cjs /opt/hanjoo/probe_server.cjs
COPY integration/ /opt/hanjoo/integration/
COPY run.sh /run.sh
RUN find /opt/hanjoo/integration -type d -name __pycache__ -prune -exec rm -rf {} \; \
 && find /opt/hanjoo/integration -type f -name '*.pyc' -delete \
 && node --check /opt/hanjoo/core_runtime.cjs \
 && node --check /opt/hanjoo/probe_server.cjs \
 && node --check /opt/hanjoo/brain_runtime.cjs \
 && chmod 755 /run.sh \
 && apk del git g++ make binutils

ENV NODE_PATH=/opt/hanjoo/node_modules \
    HANJOO_VERSION=0.6.4
EXPOSE 8099 8101 8102
CMD ["/run.sh"]
