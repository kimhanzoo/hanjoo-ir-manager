#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include "IRrecv.h"
#include "IRremoteESP8266.h"
#include "IRutils.h"

static std::vector<uint16_t> parse_csv(const std::string &line) {
  std::vector<uint16_t> out;
  out.push_back(static_cast<uint16_t>(50000U / kRawTick));
  std::stringstream ss(line); std::string item;
  while (std::getline(ss, item, ',')) {
    if (item.empty()) continue;
    long long v = std::llabs(std::strtoll(item.c_str(), nullptr, 10));
    if (v <= 0) continue;
    uint32_t ticks = static_cast<uint32_t>(v / kRawTick);
    if (!ticks) ticks = 1;
    if (ticks > 65535U) ticks = 65535U;
    out.push_back(static_cast<uint16_t>(ticks));
    if (out.size() >= 20001) break;
  }
  return out;
}
static std::string esc(const std::string &s) {
  std::string o; for (char c : s) { if (c=='\\'||c=='"') o+='\\'; o+=c; } return o;
}
static std::string hex64(uint64_t v) {
  std::ostringstream o; o << "0x" << std::uppercase << std::hex << v; return o.str();
}
int main() {
  std::string line; if (!std::getline(std::cin, line)) return 2;
  auto raw = parse_csv(line);
  if (raw.size() < 5) { std::cout << "{\"ok\":false,\"match\":null,\"coverage\":128}\n"; return 0; }
  decode_results result; result.rawbuf=raw.data(); result.rawlen=static_cast<uint16_t>(raw.size()); result.overflow=false;
  IRrecv receiver(0, static_cast<uint16_t>(std::min<size_t>(raw.size()+8, 65535)));
  receiver.setTolerance(30);
  bool ok = receiver.decode(&result, nullptr, 2, 0);
  if (!ok || result.decode_type == UNKNOWN) {
    std::cout << "{\"ok\":true,\"match\":null,\"coverage\":128}\n"; return 0;
  }
  std::string protocol = typeToString(result.decode_type);
  bool ac = hasACState(result.decode_type);
  std::ostringstream out;
  out << "{\"ok\":true,\"coverage\":128,\"match\":{"
      << "\"protocol\":\"" << esc(protocol) << "\","
      << "\"type_id\":" << static_cast<int>(result.decode_type) << ","
      << "\"bits\":" << result.bits << ","
      << "\"ac_state\":" << (ac?"true":"false") << ","
      << "\"repeat\":" << (result.repeat?"true":"false") << ",";
  if (ac) {
    size_t bytes = std::min<size_t>((result.bits+7)/8, kStateSizeMax);
    std::ostringstream state; state << std::uppercase << std::hex << std::setfill('0');
    for (size_t i=0;i<bytes;++i) state << std::setw(2) << static_cast<int>(result.state[i]);
    out << "\"state_hex\":\"" << state.str() << "\"";
  } else {
    out << "\"value\":\"" << hex64(result.value) << "\",\"address\":" << result.address
        << ",\"command\":" << result.command;
  }
  out << "}}\n"; std::cout << out.str(); return 0;
}
