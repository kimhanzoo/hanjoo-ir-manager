# HanJoo IR Manager

**HanJoo IR Manager** là Integration dành cho Home Assistant, cung cấp giao diện quản lý thiết bị hồng ngoại thống nhất và kết nối với **HanJoo IR Core** để nhận diện/generate protocol.

## Điểm nổi bật

- Kết hợp nhiều nguồn IR thay vì phụ thuộc một thư viện duy nhất: HanJoo Core/Brain, IRremoteESP8266, irtxrx, SmartIR, Flipper-IRDB và profile đã lưu.
- Thu nhiều mẫu từ remote gốc, phân tích timing/protocol và đối chiếu nhiều nguồn để tìm cấu hình phù hợp nhất.
- Hỗ trợ điều hòa, TV/media, quạt, loa, máy chiếu, đèn IR và thiết bị tùy chỉnh.
- Tạo entity Home Assistant phù hợp như `climate`, `fan`, `media_player`, `remote` để dùng trực tiếp với Dashboard, Automation và Assist.
- Dữ liệu thiết bị/profile/mã IR người dùng được quản lý bên Home Assistant để đi cùng hệ thống backup.
- Hỗ trợ Home Assistant OS trên Intel/AMD x86-64 (`amd64`) và ARM64 (`aarch64`) thông qua HanJoo IR Core Add-on.

## Cách cài khuyến nghị

Người dùng bình thường **không cần cài repository này bằng HACS**.

Hãy cài HanJoo IR từ Add-on repository:

**https://github.com/kimhanzoo/HanJoo_IR_Addon**

Trong Home Assistant:

1. **Settings → Add-ons → Add-on Store**.
2. **⋮ → Repositories**.
3. Thêm:

   ```text
   https://github.com/kimhanzoo/HanJoo_IR_Addon
   ```

4. Cài **HanJoo IR Core**.
5. Start Add-on.
6. Add-on tự cài/cập nhật HanJoo IR Manager này vào `/config/custom_components/hanjoo_ir`.
7. Restart Home Assistant Core một lần khi Manager vừa được cài hoặc cập nhật.

Sau đó toàn bộ việc học mã, thêm thiết bị, chọn emitter/receiver, quản lý profile và điều khiển IR được thực hiện trong giao diện **HanJoo IR**.

## Phần cứng IR

Bạn có thể dùng:

- ESP32/ESP8266 + 1 bộ phát IR + 1 mắt thu IR 38 kHz; hoặc
- IR blaster Tuya giá rẻ dùng Beken BK7231N, flash lại bằng ESPHome/LibreTiny nếu phần cứng phù hợp.

Ví dụ cấu hình ESPHome:

```yaml
remote_transmitter:
  id: ir_tx
  pin: 7
  carrier_duty_percent: 50%

remote_receiver:
  id: ir_rx
  pin:
    number: 8
    inverted: true
    mode:
      input: true
      pullup: true
  tolerance: 55%
  filter: 50us
  idle: 10ms
  buffer_size: 2kb
  dump: all

infrared:
  - platform: ir_rf_proxy
    name: IR Transmitter
    remote_transmitter_id: ir_tx

  - platform: ir_rf_proxy
    name: IR Receiver
    receiver_frequency: 38kHz
    remote_receiver_id: ir_rx
```

**Thay GPIO theo đúng phần cứng của bạn.** Sau khi Home Assistant tạo được IR Transmitter và IR Receiver, không cần compile lại firmware mỗi khi thêm remote/thiết bị IR mới; HanJoo IR Manager xử lý phần còn lại ở runtime.

## HACS / cài thủ công

Repository này vẫn hỗ trợ HACS cho developer hoặc người muốn quản lý Integration độc lập. Nếu dùng HACS, hãy tắt `install_manager` trong HanJoo IR Core Add-on để Add-on không ghi đè bản HACS.

Kiến trúc dự án được cố ý tách thành:

```text
Home Assistant Integration (mỏng)
→ UI, entities, device/profile storage, HA bridge

HanJoo IR Core Add-on
→ protocol engines, recognition Brain, scoring và recommendation logic
```
