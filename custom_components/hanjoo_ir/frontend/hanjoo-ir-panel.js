/* HanJoo IR Manager v0.5.6 - dependency-free Home Assistant admin panel */

// Home Assistant's native device page currently hard-codes its toolbar back path
// to /config/devices/dashboard. When a device was opened from HanJoo, intercept
// only that immediate return route and send the user back to HanJoo Devices.
const HANJOO_DEVICE_RETURN_KEY = "hanjoo_ir_device_return";

function hanjooHandleNativeDeviceReturn() {
  let marker = null;
  try { marker = JSON.parse(sessionStorage.getItem(HANJOO_DEVICE_RETURN_KEY) || "null"); } catch (_) {}
  if (!marker) return;

  const path = window.location.pathname;
  if (path.startsWith("/config/devices/device/")) return;

  if (path === "/config/devices/dashboard") {
    try { sessionStorage.removeItem(HANJOO_DEVICE_RETURN_KEY); } catch (_) {}
    window.history.replaceState(null, "", marker.returnPath || "/hanjoo-ir");
    window.dispatchEvent(new CustomEvent("location-changed"));
    return;
  }

  // The user intentionally navigated somewhere else from the native device page.
  // Drop the marker so a later visit to Devices is not unexpectedly redirected.
  try { sessionStorage.removeItem(HANJOO_DEVICE_RETURN_KEY); } catch (_) {}
}

window.addEventListener("location-changed", () => queueMicrotask(hanjooHandleNativeDeviceReturn));
window.addEventListener("popstate", () => queueMicrotask(hanjooHandleNativeDeviceReturn));
class HanjooIrPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._lang = "vi";
    this._loaded = false;
    this._loading = false;
    this._tab = "devices";
    this._summary = {};
    this._hardware = { emitters: [], receivers: [] };
    this._devices = [];
    this._profiles = [];
    this._native = [];
    this._nativeDevices = [];
    this._onlineItems = [];
    this._onlineSources = [];
    this._sources = [];
    this._discoverItems = [];
    this._discoverLoaded = false;
    this._discoverLoading = false;
    this._discoverError = "";
    this._discoverErrors = [];
    this._discoverQuery = "";
    this._discoverKind = "";
    this._discoverEmitter = "";
    this._discoverReceiver = "";
    this._addMode = "identify";
    this._identifyCaptures = [];
    this._identifyResult = null;
    this._identifyCapturing = false;
    this._identifyAutoRunning = false;
    this._identifyStepErrors = {};
    this._identifyAnalyzing = false;
    this._identifyError = "";
    this._identifyVerified = new Set();
    this._identifyKind = "auto";
    this._identifyQuery = "";
    this._onlineTotal = 0;
    this._onlineCatalogTotal = 0;
    this._onlineLoaded = false;
    this._onlineLoading = false;
    this._onlineError = "";
    this._onlineQuery = "";
    this._onlineKind = "";
    this._learnDialog = null;
    this._detail = null;
    this._busyText = "";
    this._search = "";
  }

  set hass(hass) {
    const previousLang = this._lang;
    this._hass = hass;
    this._lang = this.detectLanguage();
    if (!this._loaded && !this._loading) this.loadAll();
    else if (previousLang !== this._lang) this.render();
  }

  set panel(panel) { this._panel = panel; }
  set narrow(narrow) {
    const changed = this._narrow !== narrow;
    this._narrow = narrow;
    if (changed && this._loaded) this.render();
  }
  set route(route) { this._route = route; }

  detectLanguage() {
    const raw = String(
      this._hass?.language ||
      this._hass?.locale?.language ||
      navigator.language ||
      "vi"
    ).toLowerCase();
    return raw.startsWith("vi") ? "vi" : "en";
  }

  tr(vi, en) {
    return this._lang === "vi" ? vi : en;
  }

  uiTranslations() {
    return new Map([
      ["thiết bị", "devices"],
      ["Thiết bị", "Devices"],
      ["Thêm thiết bị", "Add device"],
      ["Tìm theo hãng/model", "Search by brand/model"],
      ["Nhận diện bằng remote", "Identify by remote"],
      ["Học thủ công", "Manual learning"],
      ["Nhận diện protocol từ remote gốc", "Identify protocol from physical remote"],
      ["Nhận diện thiết bị bằng remote", "Identify device by remote"],
      ["Tự động xác định", "Auto-detect"],
      ["Điều hòa — độ chính xác cao nhất", "Air conditioner — highest accuracy"],
      ["TV / Media", "TV / Media"],
      ["Loa / Audio", "Speaker / Audio"],
      ["Gợi ý hãng/model", "Brand/model hint"],
      ["Thông tin nhận diện", "Identification inputs"],
      ["Transmitter để Test", "Transmitter for testing"],
      ["Không rõ hãng", "Unknown brand"],
      ["Chưa xác định", "Unknown"],
      ["Nút chức năng thứ hai", "Second function button"],
      ["Nút chức năng thứ ba", "Third function button"],
      ["Mẫu bổ sung", "Extra sample"],
      ["Không có khuyến nghị tự động", "No automatic recommendation"],
      ["✓ Có khuyến nghị an toàn", "✓ Safe recommendation available"],
      ["Thu tín hiệu", "Capture signal"],
      ["Thu lại", "Capture again"],
      ["Xóa mẫu", "Clear samples"],
      ["Dùng cấu hình này", "Use this configuration"],
      ["Thư viện", "Library"],
      ["Đang tải HanJoo IR…", "Loading HanJoo IR…"],
      ["Chưa có thiết bị IR", "No IR devices yet"],
      ["Hãy dùng “Thêm thiết bị”. Ưu tiên profile native hoặc profile thư viện; chỉ học RAW khi chưa được hỗ trợ.", "Use “Add device”. Prefer native or library profiles and learn RAW only when needed."],
      ["+ Thêm thiết bị đầu tiên", "+ Add your first device"],
      ["Thiết bị của bạn", "Your devices"],
      ["Mỗi thiết bị được bọc thành climate / fan / media_player / remote để dùng trực tiếp với Overview, Automation và Assist.", "Each device is exposed as climate / fan / media_player / remote for direct use in Overview, Automations, and Assist."],
      ["+ Thêm", "+ Add"],
      ["Mở device", "Open device"],
      ["Mở trong HA", "Open in HA"],
      ["Quản lý", "Manage"],
      ["lệnh", "commands"],
      ["trạng thái AC", "AC states"],
      ["Không dùng receiver", "Do not use receiver"],
      ["Chỉ cần chọn loại và nhập hãng/model nếu biết. HanJoo tự tìm trên mọi nguồn đang bật rồi xếp phương án tốt nhất lên đầu.", "Choose the device type and enter a brand/model if known. HanJoo searches every enabled source and ranks the best option first."],
      ["Loại thiết bị", "Device type"],
      ["Tự nhận / tất cả", "Auto-detect / all"],
      ["Điều hòa", "Air conditioner"],
      ["Quạt", "Fan"],
      ["Máy chiếu", "Projector"],
      ["Loa", "Speaker"],
      ["Đèn / LED", "Light / LED"],
      ["Máy lọc không khí", "Air purifier"],
      ["Khác / Custom", "Other / Custom"],
      ["Hãng hoặc model", "Brand or model"],
      ["Ví dụ: Daikin ARC433, LG AKB75215403, Samsung UE55…", "Example: Daikin ARC433, LG AKB75215403, Samsung UE55…"],
      ["Tìm cấu hình", "Find configuration"],
      ["IR blaster dùng cho Test/Thêm", "IR blaster used for Test/Add"],
      ["Không có IR Transmitter", "No IR Transmitter"],
      ["Nguồn đang dùng:", "Enabled sources:"],
      ["Chưa bật nguồn nào.", "No sources are enabled."],
      ["⚙ Chọn nguồn", "⚙ Choose sources"],
      ["⏳ Đang tìm và xếp hạng cấu hình…", "⏳ Searching and ranking configurations…"],
      ["Một số nguồn online có lỗi nhưng các nguồn còn lại vẫn dùng được:", "Some online sources failed, but the remaining sources are still available:"],
      ["Kết quả đề xuất", "Recommended results"],
      ["Ưu tiên tự động: ", "Automatic priority: "],
      [" trước; với điều hòa ưu tiên ", " first; for air conditioners, prefer "],
      [" trước profile online; thiết bị khác ưu tiên ", " before online profiles; for other devices, prefer "],
      [". Learn/Custom luôn ở cuối.", ". Learn/Custom is always last."],
      ["phương án", "options"],
      ["Khuyên dùng", "Recommended"],
      ["⚙ Sinh mã động", "⚙ Dynamic code generation"],
      ["đã cài", "installed"],
      ["Thiết lập native", "Set up native"],
      ["Tạo & học lệnh", "Create & learn commands"],
      ["Dùng cấu hình này", "Use this configuration"],
      ["Không có cấu hình khớp từ các nguồn đã bật. Hãy bật Learn/Custom hoặc thử nhập chỉ tên hãng.", "No matching configuration was found in enabled sources. Enable Learn/Custom or try searching by brand only."],
      ["Tùy chọn nâng cao / profile đã lưu", "Advanced options / saved profiles"],
      ["Bạn vẫn có thể vào Thư viện để import/export profile hoặc quản lý từng nguồn thủ công.", "You can still use the Library to import/export profiles or manage sources manually."],
      ["Mở Thư viện IR", "Open IR Library"],
      ["Thư viện IR & nguồn tìm kiếm", "IR Library & search sources"],
      ["Chọn những nguồn HanJoo được phép dùng khi thêm thiết bị. Càng ít nguồn càng gọn; HanJoo tự xếp hạng nên bạn không phải chọn nguồn mỗi lần.", "Choose which sources HanJoo may use when adding devices. HanJoo ranks them automatically, so you do not need to pick a source each time."],
      ["Nguồn đầu vào", "Input sources"],
      ["Mặc định khuyên dùng: Native HA + Protocol Engine + SmartIR + Learn/Custom. Flipper có thể bật thêm khi cần phạm vi model rộng hơn.", "Recommended defaults: Native HA + Protocol Engine + SmartIR + Learn/Custom. Enable Flipper when you need a broader model catalog."],
      ["(ưu tiên AC)", "(AC priority)"],
      ["mục", "items"],
      ["hãng", "brands"],
      ["integration đã cài", "installed integrations"],
      ["Đang bật", "Enabled"],
      ["Đang tắt", "Disabled"],
      ["↻ Làm mới", "↻ Refresh"],
      ["Tắt", "Disable"],
      ["Bật nguồn", "Enable source"],
      ["Không có source provider khả dụng.", "No source providers are available."],
      ["Import profile / thư viện", "Import profile / library"],
      ["Bạn vẫn có thể import ", "You can still import "],
      [" từ file.", " from files."],
      ["Export toàn bộ library", "Export full library"],
      ["Profile đã import được đưa vào tìm kiếm tự động ở trang Thêm thiết bị.", "Imported profiles are included automatically in Add Device search."],
      ["Không rõ hãng/model", "Unknown brand/model"],
      ["cảnh báo import", "import warnings"],
      ["Dùng profile", "Use profile"],
      ["Xóa", "Delete"],
      ["Chưa có profile import.", "No imported profiles yet."],
      ["HanJoo không khóa dữ liệu vào board. Emitter/receiver là hạ tầng; thiết bị và profile nằm ở HA.", "HanJoo does not lock data to the blaster. Emitters/receivers are infrastructure; devices and profiles stay in Home Assistant."],
      ["Không tìm thấy Infrared Emitter.", "No Infrared Emitter found."],
      ["Receiver được dùng cả để học mã và nghe remote thật nhằm cập nhật trạng thái thiết bị về Home Assistant.", "The Receiver is used both for learning codes and listening to the physical remote so HanJoo can update device state in Home Assistant."],
      ["↔ Đồng bộ 2 chiều", "↔ Two-way sync"],
      ["→ Chỉ phát", "→ Send only"],
      ["Core offline", "Core offline"],
      ["mục", "items"],
      ["hãng", "brands"],
      ["integration đã cài", "installed integrations"],
      ["ưu tiên AC", "AC priority"],
      ["Đang bật", "Enabled"],
      ["Đang tắt", "Disabled"],
      ["Làm mới", "Refresh"],
      ["Add-on", "Add-on"],
      ["Engine API", "Engine API"],
      ["Add-on có thể đang chạy nhưng dịch vụ Core chưa sẵn sàng hoặc Home Assistant chưa kết nối được.", "The add-on may be running, but the Core service is not ready or Home Assistant cannot reach it."],
      ["Core đang hoạt động và có thể tạo/giải mã các protocol IR được hỗ trợ.", "Core is healthy and can generate/decode supported IR protocols."],
      ["Không kết nối được HanJoo IR Core add-on. Hãy kiểm tra add-on đã cài và đang chạy.", "Cannot connect to HanJoo IR Core add-on. Check that the add-on is installed and running."],
      ["HanJoo IR Core add-on chưa chạy hoặc không thể kết nối.", "HanJoo IR Core add-on is not running or cannot be reached."],
      ["Trạng thái add-on Running chỉ có nghĩa container đang chạy; dòng lỗi phía trên cho biết Core API có thực sự healthy hay không.", "The add-on status Running only means the container is running; the error above shows whether the Core API itself is actually healthy."],
      ["Chọn Receiver để bật đồng bộ 2 chiều: khi bạn bấm remote thật, HanJoo sẽ nhận diện lệnh/trạng thái và cập nhật entity Home Assistant.", "Select a Receiver to enable two-way synchronization: when you use the physical remote, HanJoo recognizes the command/state and updates the Home Assistant entity."],
      ["Không tìm thấy Infrared Receiver; vẫn phát được nhưng không thể học lệnh hoặc đồng bộ trạng thái từ remote thật.", "No Infrared Receiver found; sending still works, but learning and physical-remote state sync are unavailable."],
      ["Thiết kế dữ liệu", "Data design"],
      [" giữ library + mappings + entity semantic. ", " stores the library + mappings + semantic entities. "],
      [" chỉ đảm nhiệm phát/thu. Vì vậy thay blaster không phải học lại thiết bị.", " only handles IR send/receive. Replacing a blaster therefore does not require relearning devices."],
      ["Định tuyến IR", "IR routing"],
      ["Không dùng", "Do not use"],
      ["Lưu routing", "Save routing"],
      ["Lệnh phụ / fallback", "Extra / fallback commands"],
      ["Nút có mã sẽ thành button nếu không được entity semantic đảm nhiệm.", "Commands not handled by a semantic entity are exposed as buttons."],
      ["Đã học", "Learned"],
      ["Chưa học", "Not learned"],
      ["Học lại", "Relearn"],
      ["Học", "Learn"],
      ["Không có lệnh phụ.", "No extra commands."],
      ["Tên nút tùy chỉnh", "Custom button name"],
      ["+ Thêm nút", "+ Add button"],
      ["Mở device trong Home Assistant", "Open device in Home Assistant"],
      ["Export thiết bị", "Export device"],
      ["Xóa thiết bị", "Delete device"],
      ["Thiết bị này ", "This device "],
      ["không cần học từng nhiệt độ", "does not need each temperature to be learned"],
      [". HanJoo tạo frame IR khi phát và, nếu có Receiver, giải mã remote thật để đồng bộ trạng thái về Home Assistant.", ". HanJoo generates IR frames for sending and, when a Receiver is configured, decodes the physical remote to synchronize state back to Home Assistant."],
      ["Test nhanh từ trang ", "Quick-test from the "],
      [" dùng trạng thái Cool 25°C · Fan Auto. Sau khi thêm, điều khiển trực tiếp bằng entity climate của Home Assistant.", " page using Cool 25°C · Fan Auto. After adding it, control the device directly with its Home Assistant climate entity."],
      ["Mỗi mã là ", "Each code is "],
      ["một trạng thái đầy đủ", "a complete state"],
      [". Đây là cách đúng với remote điều hòa stateful.", ". This is the correct model for stateful A/C remotes."],
      ["trạng thái", "states"],
      ["chưa có mode", "no modes yet"],
      ["Loại frame", "Frame type"],
      ["Trạng thái hoạt động", "Operating state"],
      ["Power ON riêng", "Dedicated Power ON"],
      ["Nhiệt độ", "Temperature"],
      ["Học trạng thái này", "Learn this state"],
      ["Xem", "View"],
      ["trạng thái đã có", "saved states"],
      ["Học trạng thái điều hòa", "Learn A/C state"],
      ["Đang chờ tín hiệu IR…", "Waiting for IR signal…"],
      ["Chĩa remote gốc vào mắt thu IR rồi bấm ", "Point the original remote at the IR receiver and press the desired button "],
      ["một lần", "once"],
      [" nút cần học.", "."],
      ["Thời gian chờ tối đa:", "Maximum wait:"],
      ["giây", "seconds"],
      ["Hủy", "Cancel"],
      ["⚠ Tín hiệu chưa hợp lệ", "⚠ Invalid IR signal"],
      ["⚠ Đã nhận tín hiệu, nhưng frame khá ngắn", "⚠ Signal received, but the frame is quite short"],
      ["✓ Đã nhận được tín hiệu", "✓ IR signal received"],
      ["Tần số", "Frequency"],
      ["Số timing", "Timing count"],
      ["Độ dài frame", "Frame duration"],
      ["Xem trước timing", "Timing preview"],
      ["Mã này ", "This code "],
      ["chưa được lưu", "has not been saved"],
      [". Hãy lưu nếu đúng lần bấm vừa rồi, hoặc học lại nếu remote bị bấm nhầm/nhiễu.", ". Save it if it matches the last button press, or relearn if the capture was accidental/noisy."],
      ["↻ Học lại", "↻ Relearn"],
      ["✓ Lưu mã này", "✓ Save this code"],
      ["Đang lưu mã IR…", "Saving IR code…"],
      ["Không nhận được tín hiệu", "No IR signal received"],
      ["Thử lại", "Try again"],
      ["Đóng", "Close"],
      ["Học / Custom", "Learn / Custom"],
      ["Tạo thiết bị rồi HanJoo sẽ cho bạn học từng nút từ remote thật. Đây là fallback khi các cấu hình tự động không đúng.", "Create the device, then HanJoo will let you learn each button from the original remote. This is the fallback when automatic configurations do not work."],
      ["Tên thiết bị", "Device name"],
      ["Tạo thiết bị để học lệnh", "Create device and learn commands"],
      ["Thêm từ profile", "Add from profile"],
      ["Chọn transmitter", "Choose transmitter"],
      ["Thêm ", "Add "],
      ["Đặt IR blaster hướng về thiết bị. HanJoo sẽ phát Power/On/Off hoặc state đại diện.", "Point the IR blaster at the device. HanJoo will send Power/On/Off or a representative state."],
      ["▶ Phát mã test", "▶ Send test code"],
      ["Nếu thiết bị phản hồi đúng, đóng cửa sổ và chọn ", "If the device responds correctly, close this window and choose "],
      [". Nếu không, thử profile khác trong thư viện.", ". Otherwise, try another library profile."],
      ["⚡ Thử nhanh profile", "⚡ Quick profile test"],
      ["Mã", "Code"],
      ["Hướng IR blaster vào thiết bị rồi bấm ", "Point the IR blaster at the device and press "],
      ["Phát thử", "Test send"],
      [". Nếu thiết bị không phản hồi, chọn ", ". If the device does not respond, choose "],
      ["Không đúng → mã tiếp", "No → next code"],
      [". Khi phản hồi đúng, chọn ", ". When it responds correctly, choose "],
      ["Đúng → dùng mã này", "Yes → use this code"],
      ["Không có Infrared Emitter để thử.", "No Infrared Emitter is available for testing."],
      ["← Mã trước", "← Previous code"],
      ["▶ Phát thử", "▶ Test send"],
      ["✓ Đúng → lưu và dùng mã này", "✓ Yes → save and use this code"],
      ["Đã đến profile cuối trong danh sách hiện tại. Có thể sửa từ khóa/model để tìm nhóm khác.", "This is the last profile in the current list. Change the keyword/model to search another group."],
      ["HanJoo sẽ tải profile SmartIR tạm thời và phát Power/On/Off hoặc một state đại diện. Profile ", "HanJoo will temporarily load the SmartIR profile and send Power/On/Off or a representative state. The profile "],
      ["chưa được lưu", "is not saved"],
      [" chỉ vì bạn Test.", " just because you test it."],
      ["Lưu profile này vào HanJoo", "Save this profile to HanJoo"],
      ["Thông tin", "About"],
      ["Thông tin HanJoo IR", "About HanJoo IR"],
      ["Home Assistant infrared device manager", "Home Assistant infrared device manager"],
      ["Tác giả / Maintainer", "Author / Maintainer"],
      ["Facebook", "Facebook"],
      ["Email", "Email"],
      ["Phiên bản", "Version"],
      ["Ngôn ngữ giao diện", "Interface language"],
      ["Theo ngôn ngữ Home Assistant", "Follows Home Assistant language"],
      ["Tiếng Việt", "Vietnamese"],
      ["Tiếng Anh", "English"],
      ["Ưu tiên cao nhất khi Home Assistant có integration IR chính thức; entity và config flow do HA quản lý.", "Highest priority when Home Assistant provides an official IR integration; entities and config flows are managed by HA."],
      ["Core tạo/giải mã frame IR động cho nhiều họ protocol điều hòa. Danh sách thực tế được đọc trực tiếp từ HanJoo IR Core đang chạy; mỗi protocol/model cần Test trước khi thêm.", "The Core dynamically generates/decodes IR frames for many HVAC protocol families. The live list comes directly from the running HanJoo IR Core; test each protocol/model before adding it."],
      ["Điều hòa, TV/media và quạt. Profile được tải theo nhu cầu; HanJoo chuẩn hóa Broadlink, Xiaomi Raw, ESPHome và SmartIR.", "Air conditioners, TV/media devices, and fans. Profiles are fetched on demand; HanJoo normalizes Broadlink, Xiaomi Raw, ESPHome, and SmartIR formats."],
      ["CSDL CC0 rất lớn theo loại → hãng → model. Hỗ trợ trực tiếp RAW và các parsed protocol phổ biến: NEC/NECext, Samsung32, Sony SIRC và RC5/RC5X.", "Large CC0 database organized by type → brand → model. Directly supports RAW and common parsed protocols: NEC/NECext, Samsung32, Sony SIRC, and RC5/RC5X."],
      ["Fallback cuối cùng: học trực tiếp remote thật và tự thêm nút. Không cần Internet.", "Final fallback: learn directly from the original remote and add custom buttons. No Internet required."],
      ["TV và điều hòa LG; có hỗ trợ receiver cho một số trạng thái/lệnh.", "LG TVs and air conditioners; receiver support is available for some states/commands."],
      ["TV và điều hòa Samsung dùng giao thức native của Home Assistant.", "Samsung TVs and air conditioners using Home Assistant's native protocol implementation."],
      ["Quạt/máy lọc không khí Dyson điều khiển IR.", "Dyson fans/air purifiers controlled by IR."],
      ["Loa Edifier có profile/model native.", "Edifier speakers with native profiles/models."],
      ["Ampli/receiver Marantz điều khiển bằng IR.", "Marantz amplifiers/receivers controlled by IR."],
      ["LED strip/bulb dùng remote IR 13/24/40/44 nút được hỗ trợ native.", "LED strips/bulbs using 13/24/40/44-button IR remotes supported natively."],
      ["Loa Persang có mã native trong Home Assistant.", "Persang speakers with native codes in Home Assistant."],
      ["Dùng khi các cấu hình phía trên không điều khiển đúng thiết bị.", "Use this when none of the configurations above controls the device correctly."],
      ["lệnh đã lưu", "saved commands"],
      ["Home Assistant chưa sẵn sàng", "Home Assistant is not ready"],
      ["Lỗi không xác định", "Unknown error"],
      ["Không tìm thấy cấu hình", "Configuration not found"],
      ["Hãy chọn IR Transmitter", "Please select an IR Transmitter"],
      ["Phương án này không có bước Test IR", "This option does not have an IR test step"],
      ["Không xác định được profile", "Unable to determine the profile"],
      ["Đã lưu mã IR", "IR code saved"],
      ["Đã phát IR", "IR sent"],
      ["Đã xóa nút", "Button deleted"],
      ["Đã xóa thiết bị", "Device deleted"],
      ["Đã xóa profile", "Profile deleted"],
      ["Đã lưu routing", "Routing saved"],
      ["Đã thêm nút; giờ hãy bấm Học", "Button added; now press Learn"],
      ["File lớn hơn giới hạn 16 MB", "File exceeds the 16 MB limit"],

      ["Chọn cách phù hợp nhất với thông tin bạn đang có.", "Choose the method that best matches the information you have."],
      ["Biết hãng hoặc mã remote/model.", "Use this when you know the brand or remote/model number."],
      ["Có remote gốc: HanJoo hợp nhất protocol + thư viện.", "Have the original remote: HanJoo combines protocol decoding with library matching."],
      ["Dùng khi không có profile/protocol phù hợp.", "Use this when no suitable profile or protocol is available."],
      ["Chọn loại và nhập brands/model nếu biết. HanJoo tự tìm trên mọi nguồn đang bật rồi xếp options tốt nhất lên đầu.", "Choose the device type and enter a brand/model if known. HanJoo searches all enabled sources and ranks the best options first."],
      ["Chọn loại và nhập brand/model nếu biết. HanJoo tự tìm trên mọi nguồn đang bật rồi xếp options tốt nhất lên đầu.", "Choose the device type and enter a brand/model if known. HanJoo searches all enabled sources and ranks the best options first."],
      ["Chọn IR Receiver", "Choose IR Receiver"],
      ["Chọn IR Transmitter", "Choose IR Transmitter"],
      ["Đã lưu", "Saved"],
      ["Thiết bị khác", "Other device"],
      ["Fusion Matcher kết hợp HanJoo Protocol Core + profile đã lưu + SmartIR + Flipper-IRDB. Nếu bằng chứng yếu hoặc nhiều ứng viên quá gần nhau, HanJoo sẽ không khuyến nghị.", "Fusion Matcher combines HanJoo Protocol Core + saved profiles + SmartIR + Flipper-IRDB. If the evidence is weak or candidates are too close, HanJoo will not recommend one."],
      ["Không đoán khi độ khớp thấp.", "No guessing when confidence is low."],
      ["Tối thiểu 3 mẫu. Profile RAW phải khớp ít nhất 3 mẫu và ít nhất 2 lệnh khác nhau; ứng viên đầu phải hơn ứng viên thứ hai ít nhất 8 điểm.", "At least 3 samples are required. A RAW profile must match at least 3 samples and at least 2 different commands; the top candidate must lead the runner-up by at least 8 points."],
      ["(không bắt buộc)", "(optional)"],
      ["Ví dụ Samsung, Daikin, Sony…", "Example: Samsung, Daikin, Sony…"],
      ["Tự động: HanJoo chỉ kết luận loại thiết bị nếu một protocol/profile cụ thể vượt ngưỡng. Nếu bạn biết đây là điều hòa/TV/quạt, chọn loại tương ứng sẽ giảm rất nhiều ứng viên sai.", "Auto mode determines the device type only when a specific protocol/profile passes the confidence threshold. If you already know it is an air conditioner, TV, or fan, selecting the type greatly reduces false candidates."],
      ["Với TV/quạt/media, chỉ biết NEC/RC5/SIRC… chưa đủ để kết luận hãng. SmartIR/Flipper chỉ được dùng để khuyến nghị khi profile thực sự khớp các frame đã thu. Nhập gợi ý hãng/model sẽ giúp HanJoo tải đúng nhóm profile thay vì quét cả Internet.", "For TV/fan/media devices, knowing only NEC/RC5/SIRC is not enough to determine the brand. SmartIR/Flipper can recommend a profile only when it actually matches the captured frames. A brand/model hint helps HanJoo query the right profile group instead of searching broadly."],
      ["Điều hòa dùng chuỗi 24 → 25 → 26°C để Core kiểm tra cả checksum, cấu trúc frame và sự thay đổi state.", "For air conditioners, the 24 → 25 → 26°C sequence lets Core verify the checksum, frame structure, and state changes."],
      ["Không có Infrared Receiver. Không thể dùng nhận diện bằng remote.", "No Infrared Receiver is available. Remote identification cannot be used."],
      ["Đang phân tích…", "Analyzing…"],
      ["Nhận dạng:", "Identified as:"],
      ["Nguồn:", "Sources:"],
      ["Đã đối chiếu", "Compared"],
      ["profile online", "online profiles"],
      ["Bạn vẫn có thể Test ứng viên, nhưng HanJoo không cho thêm trực tiếp cho tới khi một ứng viên vượt ngưỡng an toàn.", "You can still test candidates, but HanJoo will not allow direct addition until one candidate passes the safety threshold."],
      ["Khớp", "Matched"],
      ["lệnh khác nhau", "different commands"],

      ["Tạo thiết bị trước, sau đó HanJoo mở trang quản lý để bạn học từng nút/trạng thái bằng remote.", "Create the device first; HanJoo will then open its management page so you can learn each button/state from the remote."],
      ["Tên thiết bị", "Device name"],
      ["Không dùng receiver", "Do not use receiver"],

      ["Search by brand/model", "Search by brand/model"],
      ["Choose device type and enter brand/model if known. HanJoo searches all enabled sources and ranks the best options first.", "Choose device type and enter brand/model if known. HanJoo searches all enabled sources and ranks the best options first."],
      ["IR blaster used for Test/Add", "IR blaster used for Test/Add"],

      ["Đặt remote ở Cool 23°C. Khi HanJoo chờ bước này, bấm Temp+ một lần để phát trạng thái Cool 24°C.", "Prepare the remote so the next press sends Cool 24°C (for example, start at 23°C and press Temp+)."],
      ["HanJoo tự chuyển sang bước này. Khi thấy “đang chờ”, bấm Temp+ một lần để phát Cool 25°C.", "From 24°C, click Capture signal and press Temp+ once so the remote sends Cool 25°C."],
      ["HanJoo tự chuyển tiếp. Khi thấy “đang chờ”, bấm Temp+ một lần để phát Cool 26°C.", "From 25°C, click Capture signal and press Temp+ once so the remote sends Cool 26°C."],
      ["Khi HanJoo chuyển đến bước cuối, bấm OFF. Mẫu này giúp phân biệt các protocol gần giống nhau.", "Press OFF. This sample is optional but helps distinguish similar protocols."],
      ["Bấm “Thu tín hiệu”, sau đó nhấn Power trên remote.", "Click “Capture signal”, then press Power on the remote."],
      ["Thu một lệnh khác:", "Capture a different command:"],
      ["Nên dùng nút có chức năng rõ và khác Power.", "Use a clearly defined button that is different from Power."],
      ["Thu lệnh thứ ba:", "Capture a third command:"],
      ["Càng nhiều lệnh khác nhau càng dễ loại profile sai.", "More distinct commands make it easier to reject incorrect profiles."],
      ["HanJoo sẽ chờ thêm một nút khác để tăng độ chắc chắn nếu các ứng viên còn sát nhau.", "Optional. Capture another different button to improve confidence if candidates are still close."],

      ["Thư viện IR & nguồn tìm kiếm", "IR Library & search sources"],
      ["Chọn những nguồn HanJoo được phép dùng khi thêm thiết bị. Càng ít nguồn càng gọn; HanJoo tự xếp hạng nên bạn không phải chọn nguồn mỗi lần.", "Choose which sources HanJoo may use when adding devices. HanJoo ranks them automatically, so you do not need to choose a source each time."],
      ["Nguồn đầu vào", "Input sources"],
      ["Mặc định khuyên dùng: Native HA + Protocol Engine + SmartIR + Learn/Custom. Flipper có thể bật thêm khi cần phạm vi model rộng hơn.", "Recommended defaults: Native HA + Protocol Engine + SmartIR + Learn/Custom. Enable Flipper when you need a broader model catalog."],
      ["Không có source provider khả dụng.", "No source providers are available."],
      ["Bạn vẫn có thể import SmartIR JSON, HAIR .wig.json và HanJoo profile/library từ file.", "You can import SmartIR JSON, HAIR .wig.json, and HanJoo profile/library files."],

      ["IR Blasters", "IR Blasters"],
      ["Định tuyến IR", "IR routing"],
      ["Lệnh phụ / fallback", "Extra / fallback commands"],
      ["Mở device trong Home Assistant", "Open device in Home Assistant"],
      ["Export thiết bị", "Export device"],
      ["Xóa thiết bị", "Delete device"],
      ["Không có lệnh phụ.", "No extra commands."],
      ["Nút có mã sẽ thành button nếu không được entity semantic đảm nhiệm.", "Commands with learned codes become buttons when they are not handled by the semantic entity."],

      ["Tạo thiết bị rồi HanJoo sẽ cho bạn học từng nút từ remote thật. Đây là fallback khi các cấu hình tự động không đúng.", "Create the device, then HanJoo will let you learn each button from the physical remote. Use this fallback when automatic configurations are not correct."],
      ["Bắt đầu học lệnh cho thiết bị này.", "Start learning commands for this device."],
      ["Thiết bị có phản hồi không?", "Did the device respond?"],
      ["Chỉ thêm nếu thiết bị phản hồi đúng.", "Only add it if the device responds correctly."],
      ["Ứng viên không có nguồn Test hợp lệ", "The candidate has no valid test source"],
      ["Ứng viên này chưa đạt ngưỡng khuyến nghị an toàn", "This candidate has not passed the safe recommendation threshold"],
      ["Không lấy được profile để thêm thiết bị", "Could not retrieve the profile needed to add the device"],
      ["Tín hiệu không đủ chất lượng. Hãy thu lại.", "Signal quality is insufficient. Please capture it again."],
      ["Cần ít nhất 3 mẫu remote", "At least 3 remote samples are required"],
      ["Đã tìm thấy một protocol đủ độ tin cậy để khuyến nghị.", "A protocol with sufficient confidence was found and can be recommended."],
      ["Chưa đủ độ tin cậy để HanJoo khuyến nghị tự động.", "Confidence is still too low for HanJoo to recommend automatically."],
      ["Đang tạo thiết bị học thủ công…", "Creating the manually learned device…"],
      ["Đang tạo thiết bị…", "Creating device…"],
      ["Đang tải và chuẩn hóa profile online…", "Loading and normalizing the online profile…"],
      ["Đã lưu profile online vào thư viện HanJoo", "Online profile saved to the HanJoo library"],
      ["Profile này đã có trong thư viện HanJoo", "This profile is already in the HanJoo library"],
      ["Đang bật và kiểm tra nguồn…", "Enabling and checking the source…"],
      ["Đang tắt nguồn…", "Disabling source…"],
      ["Đã bật nguồn", "Source enabled"],
      ["Đã tắt nguồn", "Source disabled"],
      ["Đang làm mới catalog nguồn…", "Refreshing source catalog…"],
      ["Fusion Matcher đang đối chiếu HanJoo Protocol + thư viện…", "Fusion Matcher is comparing HanJoo Protocol + library profiles…"],
      ["hãy bấm remote ngay…", "press the remote now…"],
      ["Đã phát thử:", "Test signal sent:"],
      ["Đã phát mã test:", "Test code sent:"],
      ["Nếu thiết bị phản hồi đúng, chọn “Dùng cấu hình này”.", "If the device responds correctly, choose “Use this configuration”."],
      ["Đang tải và test", "Loading and testing"],
      ["Đang phát test", "Sending test"],
      ["Đang thêm", "Adding"],
      ["Đang lưu profile", "Saving profile"],
      ["Đang tải và phát thử", "Loading and sending a test"],
      ["Đã phát:", "Sent:"],
      ["Profile đã có sẵn; hãy chọn tên và emitter để thêm thiết bị", "The profile is already saved; choose a name and emitter to add the device"],
      ["Đã lưu profile; bước cuối là thêm thiết bị", "Profile saved; the final step is to add the device"],
      ["Đã lưu profile vào thư viện HanJoo", "Profile saved to the HanJoo library"],
      ["Đã thu mẫu", "Captured sample"],
      ["cảnh báo", "warnings"],
      ["file lỗi", "failed files"],
      ["Import xong:", "Import complete:"],
      ["Có remote gốc: HanJoo tự nhận diện và đối chiếu protocol + thư viện.", "Have the original remote: HanJoo automatically identifies and cross-checks protocols + libraries."],
      ["Dùng khi không có remote hoặc bạn đã biết hãng/model.", "Use this when you do not have the remote or already know the brand/model."],
      ["Nhận diện thiết bị bằng remote", "Identify device by remote"],
      ["Thông tin nhận diện", "Identification details"],
      ["Điều hòa — độ chính xác cao nhất", "Air conditioner — highest accuracy"],
      ["Transmitter để Test", "Transmitter for Test"],
      ["Thu lại", "Capture again"],
      ["Thu tín hiệu", "Capture signal"],
      ["Xóa mẫu", "Clear samples"],
      ["Phân tích", "Analyze"],
      ["mẫu", "samples"],
      ["✓ Có khuyến nghị an toàn", "✓ Safe recommendation"],
      ["Độ tin cậy", "Confidence"],
      ["Đã xác nhận bằng Test", "Verified by Test"],
      ["Thêm thiết bị này", "Add this device"],
      ["Bạn có thể Test từng ứng viên. Nếu thiết bị phản hồi đúng và bạn xác nhận, HanJoo sẽ cho phép thêm thiết bị ngay cả khi thuật toán chưa đủ chắc để tự khuyến nghị.", "You can test each candidate. If the device responds correctly and you confirm it, HanJoo will allow adding the device even when the algorithm is not confident enough to auto-recommend."],
      ["Đã xác nhận ứng viên bằng Test. Bạn có thể thêm thiết bị.", "Candidate verified by Test. You can now add the device."],
      ["Ứng viên chưa được xác nhận. Hãy thử ứng viên khác.", "Candidate not verified. Try another candidate."],
      ["Hãy Test và xác nhận thiết bị phản hồi đúng trước khi thêm.", "Test the candidate and confirm that the device responds correctly before adding it."],
      ["Nhận diện", "Detected"],
      ["Chưa nhận diện được protocol từ mẫu này", "Protocol not identified from this sample yet"],
      ["Mã nhận được", "Received code"],
      ["Nếu Core không nhận diện đủ chắc, hãy chuyển sang tìm theo hãng/model hoặc học thủ công.", "If Core cannot identify the remote reliably, switch to brand/model search or manual learning."],
      ["Tìm cấu hình tương thích", "Find compatible configuration"],
      ["Core đã nhận diện protocol nhưng chưa có bộ điều khiển động tương ứng. Đã chuyển sang tìm theo hãng/model.", "Core identified the protocol, but no matching dynamic controller is available. Switched to brand/model search."]
    ]);
  }

  translateText(text) {
    if (this._lang === "vi" || !text) return text;
    const map = this.uiTranslations();
    if (map.has(text)) return map.get(text);
    let out = text;
    // Preserve leading/trailing whitespace while translating the visible core.
    const lead = out.match(/^\s*/)?.[0] || "";
    const trail = out.match(/\s*$/)?.[0] || "";
    let core = out.slice(lead.length, out.length - trail.length || undefined);
    if (map.has(core)) return lead + map.get(core) + trail;

    const rules = [
      [/^(\d+) thiết bị$/, "$1 devices"],
      [/^(\d+) lệnh$/, "$1 commands"],
      [/^(\d+) trạng thái AC$/, "$1 AC states"],
      [/^(\d+) trạng thái$/, "$1 states"],
      [/^(\d+) phương án$/, "$1 options"],
      [/^(\d+) mục$/, "$1 items"],
      [/^(\d+) hãng$/, "$1 brands"],
      [/^(\d+) integration đã cài$/, "$1 installed integrations"],
      [/^(\d+) cảnh báo import$/, "$1 import warnings"],
      [/^Xem (\d+) trạng thái đã có$/, "View $1 saved states"],
      [/^Thời gian chờ tối đa: (\d+) giây$/, "Maximum wait: $1 seconds"],
      [/^Mã (\d+)\/(\d+)$/, "Code $1/$2"],
      [/^Đã thêm thiết bị (.+)$/, "Added device $1"],
      [/^Đã tạo (.+)$/, "Created $1"],
      [/^Đã thêm (.+)$/, "Added $1"],
      [/^Đã làm mới (\d+) profile$/, "Refreshed $1 profiles"],
      [/^Phân tích (\d+) mẫu$/, "Analyze $1 samples"],
      [/^Đã đối chiếu (\d+) profile online$/, "Compared $1 online profiles"],
      [/^Khớp (\d+)\/(\d+)$/, "Matched $1/$2"],
      [/^(\d+) lệnh khác nhau$/, "$1 different commands"],
      [/^Đã thu mẫu (\d+): (\d+) timings$/, "Captured sample $1: $2 timings"],
      [/^⏳ (.+): hãy bấm remote ngay…$/, "⏳ $1: press the remote now…"],
      [/^⏳ Đang phát test (.+)$/, "⏳ Sending test: $1"],
      [/^⏳ Đang thêm (.+)$/, "⏳ Adding $1"],
      [/^⏳ Đang lưu profile (.+)$/, "⏳ Saving profile $1"],
      [/^⏳ Đang tải và phát thử (.+)$/, "⏳ Loading and test-sending $1"],
      [/^Đã phát: (.+)\. Thiết bị có phản hồi không\?$/, "Sent: $1. Did the device respond?"],
      [/^Đã phát thử: (.+)\. Chỉ thêm nếu thiết bị phản hồi đúng\.$/, "Test signal sent: $1. Only add it if the device responds correctly."],
      [/^Đã phát thử: (.+)\. Nếu thiết bị phản hồi đúng, chọn “Dùng cấu hình này”\.$/, "Test signal sent: $1. If the device responds correctly, choose “Use this configuration”."],
      [/^Đã phát mã test: (.+)$/, "Test code sent: $1"],
      [/^Import xong: (.+)$/, "Import complete: $1"],
    ];
    for (const [pattern, replacement] of rules) {
      if (pattern.test(core)) return lead + core.replace(pattern, replacement) + trail;
    }

    // Translate known fragments in compound text nodes produced around <b> tags.
    for (const [vi, en] of map.entries()) {
      if (vi.length >= 4 && core.includes(vi)) core = core.replaceAll(vi, en);
    }
    return lead + core + trail;
  }

  translateDom(root) {
    if (this._lang === "vi" || !root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      if (["STYLE", "SCRIPT"].includes(node.parentElement?.tagName)) continue;
      node.nodeValue = this.translateText(node.nodeValue);
    }
    root.querySelectorAll?.("[placeholder],[title],[aria-label]").forEach(el => {
      for (const attr of ["placeholder", "title", "aria-label"]) {
        if (el.hasAttribute(attr)) el.setAttribute(attr, this.translateText(el.getAttribute(attr)));
      }
    });
  }

  async ws(type, data = {}) {
    if (!this._hass) throw new Error(this.tr("Home Assistant chưa sẵn sàng", "Home Assistant is not ready"));
    return this._hass.callWS({ type: `hanjoo_ir/${type}`, ...data });
  }

  async loadAll() {
    if (this._loading) return;
    this._loading = true;
    this.render();
    try {
      const [summary, hardware, devices, profiles, nativeCatalog, nativeDevices, sources] = await Promise.all([
        this.ws("summary"),
        this.ws("hardware"),
        this.ws("devices"),
        this.ws("profiles"),
        this.ws("native_catalog"),
        this.ws("native_devices"),
        this.ws("sources"),
      ]);
      this._summary = summary;
      this._hardware = hardware;
      this._devices = devices;
      this._profiles = profiles;
      this._native = nativeCatalog;
      this._nativeDevices = nativeDevices;
      this._sources = sources || [];
      if (!this._discoverEmitter && (hardware.emitters || []).length) {
        this._discoverEmitter = hardware.emitters[0];
      }
      if (!this._discoverReceiver && (hardware.receivers || []).length) {
        this._discoverReceiver = hardware.receivers[0];
      }
      this._loaded = true;
    } catch (err) {
      this.toast(this.errText(err), true);
    } finally {
      this._loading = false;
      this.render();
    }
    if (this._loaded && !this._discoverLoaded && !this._discoverLoading) {
      this.loadDiscovery();
    }
  }

  async loadDiscovery(force = false) {
    if (this._discoverLoading) return;
    if (!force && !this._discoverQuery.trim() && !this._discoverKind) {
      this._discoverItems = [];
      this._discoverErrors = [];
      this._discoverError = "";
      this._discoverLoaded = false;
      this.render();
      return;
    }
    this._discoverLoading = true;
    this._discoverError = "";
    this.render();
    try {
      const result = await this.ws("discover", {
        query: this._discoverQuery || "",
        kind: this._discoverKind || null,
        limit: 100,
      });
      this._discoverItems = result.items || [];
      this._sources = result.sources || this._sources;
      this._discoverErrors = result.errors || [];
      this._discoverLoaded = true;
    } catch (err) {
      this._discoverItems = [];
      this._discoverErrors = [];
      this._discoverError = this.errText(err);
    } finally {
      this._discoverLoading = false;
      this.render();
    }
  }

  async loadOnline(force = false) {
    if (this._onlineLoading) return;
    this._onlineLoading = true;
    this._onlineError = "";
    this.render();
    try {
      const result = await this.ws("online/search", {
        query: this._onlineQuery || "",
        kind: this._onlineKind || null,
        limit: 120,
        force,
      });
      this._onlineItems = result.items || [];
      this._onlineTotal = result.total || 0;
      this._onlineCatalogTotal = result.catalog_total || 0;
      this._onlineSources = result.sources || [];
      this._onlineLoaded = true;
    } catch (err) {
      this._onlineError = this.errText(err);
      this._onlineItems = [];
      try {
        this._onlineSources = await this.ws("online/sources");
      } catch (_) {
        this._onlineSources = [];
      }
    } finally {
      this._onlineLoading = false;
      this.render();
    }
  }

  sourceNote(source) {
    if (!source) return "";
    const localized = this._lang === "vi" ? source.note_vi : source.note_en;
    if (localized) return localized;
    return this.translateText(source.note || "");
  }

  errText(err) {
    const raw = err?.message || err?.body?.message || String(err || "Lỗi không xác định");
    return this.translateText(raw);
  }

  sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

  esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  toast(text, error = false) {
    const localized = this.translateText(String(text ?? ""));
    this._busyText = `${error ? "❌" : "✅"} ${localized}`;
    this.render();
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this._busyText = "";
      this.render();
    }, error ? 7000 : 3500);
  }

  semanticLabel(type) {
    return {
      climate: "Climate",
      fan: "Fan",
      media_player: "Media player",
      remote: "Remote",
    }[type] || type || "IR";
  }

  kindLabel(kind) {
    const vi = {
      tv: "TV", air_conditioner: "Điều hòa", fan: "Quạt", projector: "Máy chiếu",
      speaker: "Loa", soundbar: "Soundbar", receiver: "Ampli / Receiver", washer: "Máy giặt",
      dishwasher: "Máy rửa bát", light: "Đèn / LED", air_purifier: "Máy lọc không khí",
      camera: "Camera", console: "Console", custom: "Custom", legacy_air_conditioner: "Điều hòa cũ (v0.1)",
    };
    const en = {
      tv: "TV", air_conditioner: "Air conditioner", fan: "Fan", projector: "Projector",
      speaker: "Speaker", soundbar: "Soundbar", receiver: "Amplifier / Receiver", washer: "Washer",
      dishwasher: "Dishwasher", light: "Light / LED", air_purifier: "Air purifier",
      camera: "Camera", console: "Console", custom: "Custom", legacy_air_conditioner: "Legacy A/C (v0.1)",
    };
    return (this._lang === "vi" ? vi : en)[kind] || kind || "Custom";
  }

  sourceLabel(source) {
    const labels = this._lang === "vi" ? {
      native_ha: "Native Home Assistant", protocol_engine: "Protocol Engine", saved_profile: "Profile đã lưu",
      smartir: "SmartIR", flipper_irdb: "Flipper-IRDB", learn_custom: "Learn / Custom",
    } : {
      native_ha: "Native Home Assistant", protocol_engine: "Protocol Engine", saved_profile: "Saved profile",
      smartir: "SmartIR", flipper_irdb: "Flipper-IRDB", learn_custom: "Learn / Custom",
    };
    return labels[source] || source || "IR";
  }


  render() {
    if (!this.shadowRoot) return;
    const busy = this._busyText
      ? `<div class="toast">${this.esc(this._busyText)}</div>` : "";
    this.shadowRoot.innerHTML = `
      <style>${this.styles()}
      .danger.subtle {
        color: var(--error-color, #db4437);
        border-color: color-mix(in srgb, var(--error-color, #db4437) 45%, transparent);
        background: transparent;
      }
      .danger.subtle:hover {
        background: color-mix(in srgb, var(--error-color, #db4437) 10%, transparent);
      }
</style>
      <div class="shell">
        ${this._narrow ? `
          <div class="mobile-ha-toolbar">
            <ha-menu-button id="hanjoo-ha-menu"></ha-menu-button>
            <div class="mobile-ha-title">HanJoo IR</div>
          </div>` : ""}
        <header>
          <div>
            <div class="title">HanJoo IR</div>
            <div class="subtitle">IR devices → Home Assistant semantic entities</div>
          </div>
          <div class="stats">
            <span>${this._summary.devices || 0} thiết bị</span>
            <span>${this._summary.profiles || 0} profile</span>
            <span>${this._summary.emitters || 0} emitter</span>
          </div>
        </header>
        ${busy}
        <nav>
          ${this.tabButton("devices", "Thiết bị", "mdi:devices")}
          ${this.tabButton("add", "Thêm thiết bị", "mdi:plus-circle")}
          ${this.tabButton("library", "Thư viện", "mdi:bookshelf")}
          ${this.tabButton("hardware", "IR Blasters", "mdi:remote")}
          ${this.tabButton("about", "About", "mdi:information-outline")}
        </nav>
        <main>
          ${this._loading && !this._loaded ? `<div class="empty">Đang tải HanJoo IR…</div>` : this.renderTab()}
        </main>
      </div>
      ${this._detail ? this.renderModal() : ""}
      ${this._learnDialog ? this.renderLearnDialog() : ""}
    `;
    this.translateDom(this.shadowRoot);
    const haMenu = this.shadowRoot.querySelector("#hanjoo-ha-menu");
    if (haMenu) {
      haMenu.hass = this._hass;
      haMenu.narrow = true;
    }
    this.bind();
  }

  tabButton(id, label) {
    return `<button class="tab ${this._tab === id ? "active" : ""}" data-tab="${id}">${label}</button>`;
  }

  renderTab() {
    if (this._tab === "add") return this.renderAdd();
    if (this._tab === "library") return this.renderLibrary();
    if (this._tab === "hardware") return this.renderHardware();
    if (this._tab === "about") return this.renderAbout();
    return this.renderDevices();
  }

  renderDevices() {
    if (!this._devices.length && !this._nativeDevices.length) {
      return `<section class="empty">
        <div class="big">📡</div>
        <h2>Chưa có thiết bị IR</h2>
        <p>Hãy dùng “Thêm thiết bị”. Ưu tiên profile native hoặc profile thư viện; chỉ học RAW khi chưa được hỗ trợ.</p>
        <button class="primary" data-tab="add">+ Thêm thiết bị đầu tiên</button>
      </section>`;
    }
    return `
      <div class="section-head">
        <div><h2>Thiết bị của bạn</h2><p>Mỗi thiết bị được bọc thành climate / fan / media_player / remote để dùng trực tiếp với Overview, Automation và Assist.</p></div>
        <button class="primary" data-tab="add">+ Thêm</button>
      </div>
      ${this._nativeDevices.length ? `
        <h3 class="group-title">Native Home Assistant</h3>
        <div class="grid native-device-grid">
          ${this._nativeDevices.map(d => `
            <article class="card device-card native-installed">
              <div class="card-top">
                <div class="device-icon">✨</div>
                <div class="grow"><h3>${this.esc(d.name)}</h3>
                  <div class="muted">${this.esc(d.brand || "")} · ${this.esc(d.native_domain)}</div>
                </div><span class="pill">Native HA</span>
              </div>
              <div class="meta">${(d.semantic_entities || []).map(x => `<span>${this.esc(x)}</span>`).join("")}</div>
              <div class="actions">
                ${d.ha_device_id ? `<button data-overview="${this.esc(d.ha_device_id)}">Mở device</button>` : ""}
                <button data-native-settings="${this.esc(d.native_domain)}">Integration</button>
              </div>
            </article>`).join("")}
        </div>` : ""}
      ${this._devices.length ? `<h3 class="group-title">HanJoo managed / learned</h3>` : ""}
      <div class="grid">
        ${this._devices.map(d => `
          <article class="card device-card">
            <div class="card-top">
              <div class="device-icon">${d.type === "climate" ? "❄️" : d.type === "fan" ? "🌀" : d.type === "media_player" ? "📺" : "🎛️"}</div>
              <div class="grow">
                <h3>${this.esc(d.name)}</h3>
                <div class="muted">${this.esc(this.kindLabel(d.kind))} · ${this.esc(this.semanticLabel(d.type))}</div>
              </div>
              <span class="pill">${this.esc(d.source || "learned")}</span>
            </div>
            <div class="meta">
              ${d.brand ? `<span>${this.esc(d.brand)} ${this.esc(d.model || "")}</span>` : ""}
              <span>${d.learned_command_count || 0}/${d.command_count || 0} lệnh</span>
              ${d.type === "climate" ? `<span>${d.climate_cell_count || 0} trạng thái AC</span>` : ""}
              ${d.two_way_enabled ? `<span>↔ Đồng bộ 2 chiều</span>` : `<span>→ Chỉ phát</span>`}
            </div>
            <div class="actions">
              <button data-manage="${this.esc(d.id)}">Quản lý</button>
              ${d.ha_device_id ? `<button data-overview="${this.esc(d.ha_device_id)}">Mở trong HA</button>` : ""}
              <button class="danger subtle" data-delete-card="${this.esc(d.id)}">Xóa</button>
            </div>
          </article>
        `).join("")}
      </div>`;
  }

  identifySteps() {
    if (this._identifyKind === "air_conditioner") return [
      { label: "Cool 24°C", help: "Đặt remote ở Cool 23°C. Khi HanJoo chờ bước này, bấm Temp+ một lần để phát trạng thái Cool 24°C.", expected: { power: true, mode: "cool", temp: 24 } },
      { label: "Cool 25°C", help: "HanJoo tự chuyển sang bước này. Khi thấy “đang chờ”, bấm Temp+ một lần để phát Cool 25°C.", expected: { power: true, mode: "cool", temp: 25 } },
      { label: "Cool 26°C", help: "HanJoo tự chuyển tiếp. Khi thấy “đang chờ”, bấm Temp+ một lần để phát Cool 26°C.", expected: { power: true, mode: "cool", temp: 26 } },
      { label: "Power Off", help: "Khi HanJoo chuyển đến bước cuối, bấm OFF. Mẫu này giúp phân biệt các protocol gần giống nhau.", expected: { power: false } },
    ];
    const byKind = {
      tv: ["Power", "Volume +", "Mute"],
      fan: ["Power", "Speed", "Oscillate / Swing"],
      projector: ["Power", "Input / Source", "Menu"],
      speaker: ["Power", "Volume +", "Mute"],
    };
    const labels = byKind[this._identifyKind] || ["Power", "Nút chức năng thứ hai", "Nút chức năng thứ ba"];
    return [
      { label: labels[0], help: `Khi HanJoo chờ bước 1, nhấn ${labels[0]} trên remote.`, expected: {} },
      { label: labels[1], help: `HanJoo tự chuyển sang bước 2; nhấn ${labels[1]}.`, expected: {} },
      { label: labels[2], help: `HanJoo tự chuyển sang bước 3; nhấn ${labels[2]}.`, expected: {} },
      { label: "Mẫu bổ sung", help: "HanJoo sẽ chờ thêm một nút khác để tăng độ chắc chắn nếu các ứng viên còn sát nhau.", expected: {} },
    ];
  }

  renderAdd() {
    return `
      <div class="section-head">
        <div>
          <h2>Thêm thiết bị</h2>
          <p>Chọn cách phù hợp nhất với thông tin bạn đang có.</p>
        </div>
      </div>
      <div class="add-methods">
        <button class="add-method ${this._addMode === "identify" ? "selected" : ""}" data-add-mode="identify">
          <ha-icon icon="mdi:remote"></ha-icon><b>Nhận diện bằng remote</b><span>Có remote gốc: HanJoo tự nhận diện và đối chiếu protocol + thư viện.</span>
        </button>
        <button class="add-method ${this._addMode === "search" ? "selected" : ""}" data-add-mode="search">
          <ha-icon icon="mdi:magnify"></ha-icon><b>Tìm theo hãng/model</b><span>Dùng khi không có remote hoặc bạn đã biết hãng/model.</span>
        </button>
        <button class="add-method ${this._addMode === "manual" ? "selected" : ""}" data-add-mode="manual">
          <ha-icon icon="mdi:gesture-tap-button"></ha-icon><b>Học thủ công</b><span>Dùng khi không có profile/protocol phù hợp.</span>
        </button>
      </div>
      ${this._addMode === "identify" ? this.renderRemoteIdentify() : this._addMode === "manual" ? this.renderManualAdd() : this.renderSearchAdd()}
    `;
  }

  renderCaptureRecognition(cap) {
    const timings = Array.isArray(cap?.timings) ? cap.timings : [];
    const preview = timings.slice(0, 22).join(" ");
    const suffix = timings.length > 22 ? " …" : "";
    const freq = Number(cap?.frequency || 0);
    const hint = Array.isArray(cap?.protocol_hints) ? cap.protocol_hints[0] : null;
    const hintText = hint?.protocol ? ` · ${this.tr("Nhận dạng sơ bộ", "Preliminary")}: <b>${this.esc(hint.brand ? `${hint.brand} ${hint.protocol}` : hint.protocol)}</b> ${Number(hint.confidence || 0)}%` : "";
    return `<small class="capture-recognition"><b>${this.tr("Mã nhận được", "Received code")}:</b> ${freq ? `${Math.round(freq/1000)} kHz · ` : ""}${this.esc(preview)}${suffix}${hintText}</small>`;
  }

  renderRemoteIdentify() {
    const receiverOptions = `<option value="">Chọn IR Receiver</option>` + this._hardware.receivers.map(x =>
      `<option value="${this.esc(x)}" ${this._discoverReceiver === x ? "selected" : ""}>${this.esc(x)}</option>`
    ).join("");
    const emitterOptions = `<option value="">Chọn IR Transmitter</option>` + this._hardware.emitters.map(x =>
      `<option value="${this.esc(x)}" ${this._discoverEmitter === x ? "selected" : ""}>${this.esc(x)}</option>`
    ).join("");
    const steps = this.identifySteps();
    const captured = new Map((this._identifyCaptures || []).map(x => [x.step, x]));
    const r = this._identifyResult;
    const candidates = r?.candidates || [];
    const sourceLabel = s => s === "protocol_engine" ? "HanJoo Protocol" : s === "raw_timing_heuristic" ? "Raw timing" : this.sourceLabel(s);
    const usedSourceLabels = Object.entries(r?.sources_used || {}).filter(([, enabled]) => !!enabled).map(([key]) => ({
      hanjoo_protocol: "HanJoo Core",
      irremoteesp8266: "IRremoteESP8266",
      raw_timing_heuristic: "Raw timing",
      saved_profile: this.tr("Profile đã lưu", "Saved profiles"),
      smartir: "SmartIR",
      flipper_irdb: "Flipper-IRDB",
    }[key] || key));
    const kindLabel = k => this.kindLabel(k === "climate" ? "air_conditioner" : k);
    return `
      <section class="subsection identify-box">
        <div class="section-head compact-head"><div>
          <h3>${this.tr("Nhận diện thiết bị bằng remote", "Identify device by remote")}</h3>
        </div></div>
        <div class="routing-mini">
          <div class="routing-title">${this.tr("Thông tin nhận diện", "Identification details")}</div>
          <label>${this.tr("Loại thiết bị", "Device type")}<select id="identify-kind">
            <option value="auto" ${this._identifyKind === "auto" ? "selected" : ""}>${this.tr("Tự động xác định", "Auto-detect")}</option>
            <option value="air_conditioner" ${this._identifyKind === "air_conditioner" ? "selected" : ""}>${this.tr("Điều hòa — độ chính xác cao nhất", "Air conditioner — highest accuracy")}</option>
            <option value="tv" ${this._identifyKind === "tv" ? "selected" : ""}>TV / Media</option>
            <option value="fan" ${this._identifyKind === "fan" ? "selected" : ""}>${this.tr("Quạt", "Fan")}</option>
            <option value="projector" ${this._identifyKind === "projector" ? "selected" : ""}>${this.tr("Máy chiếu", "Projector")}</option>
            <option value="speaker" ${this._identifyKind === "speaker" ? "selected" : ""}>${this.tr("Loa / Audio", "Speaker / Audio")}</option>
          </select></label>
          <label>${this.tr("Gợi ý hãng/model", "Brand/model hint")} <span class="muted">${this.tr("(không bắt buộc)", "(optional)")}</span><input id="identify-query" value="${this.esc(this._identifyQuery || "")}" placeholder="Ví dụ Samsung, Daikin, Sony…"></label>
          <label>Receiver<select id="identify-receiver">${receiverOptions}</select></label>
          <label>${this.tr("Transmitter để Test", "Transmitter for Test")}<select id="identify-emitter">${emitterOptions}</select></label>
        </div>
        ${!this._hardware.receivers.length ? `<div class="callout error-callout">Không có Infrared Receiver. Không thể dùng nhận diện bằng remote.</div>` : ""}
        <div class="actions identify-actions identify-start-actions">
          <button class="primary" id="identify-start" ${(this._identifyCapturing || this._identifyAnalyzing || this._identifyAutoRunning || !this._hardware.receivers.length) ? "disabled" : ""}>${this._identifyAutoRunning || this._identifyCapturing ? this.tr("Đang chờ remote…", "Waiting for remote…") : (this._identifyCaptures.length ? this.tr("Tiếp tục nhận tín hiệu", "Continue capture") : this.tr("Bắt đầu", "Start"))}</button>
          <button id="identify-reset" ${(!this._identifyCaptures.length && !Object.keys(this._identifyStepErrors || {}).length) || this._identifyCapturing ? "disabled" : ""}>${this.tr("Làm lại từ đầu", "Start over")}</button>
        </div>
        <div class="identify-steps">
          ${steps.map((step, i) => {
            const cap = captured.get(i);
            const stepError = (this._identifyStepErrors || {})[i];
            const active = this._identifyAutoRunning && !cap && !stepError && i === steps.findIndex((_, idx) => !captured.has(idx));
            return `<article class="identify-step ${cap ? "done" : stepError ? "error" : active ? "active" : ""}">
              <div class="identify-step-num">${cap ? "✓" : i + 1}</div>
              <div class="identify-step-main"><b>${this.esc(step.label)}</b><span>${this.esc(step.help)}</span>${active ? `<small>● ${this.tr("Đang chờ bạn bấm nút này trên remote…", "Waiting for this button on the remote…")}</small>` : ""}${stepError ? `<small class="step-error">⚠ ${this.esc(stepError)}</small>` : ""}${cap ? `<small>✓ ${cap.timing_count} timings · ${cap.duration_ms} ms · ${this.esc(cap.quality)}</small>${this.renderCaptureRecognition(cap)}` : ""}</div>
              ${(cap || stepError) ? `<button ${this._identifyCapturing ? "disabled" : ""} data-identify-capture="${i}">${this.tr("Thu lại", "Capture again")}</button>` : ""}
            </article>`;
          }).join("")}
        </div>
        ${this._identifyCaptures.length >= 3 && !this._identifyAutoRunning ? `<div class="actions identify-actions"><button id="identify-analyze" ${(this._identifyCapturing || this._identifyAnalyzing) ? "disabled" : ""}>${this._identifyAnalyzing ? this.tr("Đang phân tích…", "Analyzing…") : this.tr("Phân tích lại", "Analyze again")}</button></div>` : ""}
        ${this._identifyError ? `<div class="callout error-callout">${this.esc(this._identifyError)}</div>` : ""}
        ${r ? `<div class="identify-result ${r.recommended ? "strong" : "caution"}">
          <h3>${r.recommended ? this.tr("✓ Có khuyến nghị an toàn", "✓ Safe recommendation") : this.tr("Không có khuyến nghị tự động", "No automatic recommendation")}</h3>
          <p>${this.esc(this._lang === "vi" ? (r.message_vi || r.message || "") : (r.message_en || this.translateText(r.message || "")))}</p>
          ${r.inferred_kind ? `<div class="meta"><span>Nhận dạng: <b>${this.esc(kindLabel(r.inferred_kind))}</b></span></div>` : ""}
          <div class="meta"><span>${this.tr("Nguồn", "Sources")}: ${this.esc(usedSourceLabels.join(" · ") || "HanJoo Core")}</span></div>
          ${!r.recommended ? `<div class="muted">${this.tr("Nếu Core không nhận diện đủ chắc, hãy chuyển sang tìm theo hãng/model hoặc học thủ công.", "If Core cannot identify the remote reliably, switch to brand/model search or manual learning.")}</div>
          ${!r.recommended ? `<div class="actions fallback-actions"><button data-identify-search>${this.tr("Tìm theo hãng/model", "Search by brand/model")}</button><button data-identify-manual>${this.tr("Học thủ công", "Manual learning")}</button></div>` : ""}` : ""}
          ${candidates.length ? `<div class="identify-candidates">${candidates.slice(0,8).map((x) => {
            const c = x.candidate || {};
            const recommended = r.recommended && (
              r.recommended_id === c.id ||
              (r.equivalent_candidate_ids || []).includes(c.id)
            );
            const verified = this._identifyVerified?.has(c.id);
            const canAdd = recommended || verified;
            return `<article class="candidate-card ${recommended ? "recommended" : ""}">
              <div class="candidate-main"><div class="candidate-title">${recommended ? `<span class="recommend">${this.tr("Khuyên dùng", "Recommended")}</span>` : ""}${verified ? `<span class="recommend verified">${this.tr("Đã xác nhận bằng Test", "Verified by Test")}</span>` : ""}<b>${this.esc(c.brand || this.tr("Không rõ hãng", "Unknown brand"))}</b> ${this.esc(c.model || c.variant || "")}</div>
              <div class="candidate-meta"><span>${this.esc(kindLabel(c.kind || c.semantic_type))}</span><span>${this.esc(sourceLabel(c.source))}</span><span>${this.tr("Độ tin cậy", "Confidence")} ${Number(x.confidence || 0)}%</span><span>${this.tr("Khớp", "Matched")} ${x.matched_captures || 0}/${x.capture_count || 0}</span>${x.distinct_matches != null ? `<span>${x.distinct_matches} ${this.tr("lệnh khác nhau", "different commands")}</span>` : ""}</div></div>
              <div class="actions"><button data-identify-test="${this.esc(c.id || "")}">${this.tr("Test", "Test")}</button>${canAdd ? `<button class="primary" data-identify-add="${this.esc(c.id || "")}">${c.recognition_only ? this.tr("Tìm cấu hình tương thích", "Find compatible configuration") : (verified && !recommended ? this.tr("Thêm thiết bị này", "Add this device") : this.tr("Dùng cấu hình này", "Use this configuration"))}</button>` : ""}</div>
            </article>`;
          }).join("")}</div>` : ""}
        </div>` : ""}
      </section>`;
  }

  renderManualAdd() {
    const emitterOptions = this._hardware.emitters.map(x => `<option value="${this.esc(x)}" ${this._discoverEmitter === x ? "selected" : ""}>${this.esc(x)}</option>`).join("");
    const receiverOptions = `<option value="">Không dùng receiver</option>` + this._hardware.receivers.map(x => `<option value="${this.esc(x)}" ${this._discoverReceiver === x ? "selected" : ""}>${this.esc(x)}</option>`).join("");
    return `<section class="subsection">
      <h3>Học thủ công</h3><p>Tạo thiết bị trước, sau đó HanJoo mở trang quản lý để bạn học từng nút/trạng thái bằng remote.</p>
      <form id="manual-add-form" class="form-grid">
        <label>Tên thiết bị<input name="name" required placeholder="Ví dụ: Điều hòa phòng ngủ"></label>
        <label>Loại thiết bị<select name="kind"><option value="air_conditioner">Điều hòa</option><option value="tv">TV / Media</option><option value="fan">Quạt</option><option value="projector">Máy chiếu</option><option value="speaker">Loa</option><option value="custom">Khác / Custom</option></select></label>
        <label>Transmitter<select name="emitter" required>${emitterOptions || `<option value="">Không có IR Transmitter</option>`}</select></label>
        <label>Receiver<select name="receiver">${receiverOptions}</select></label>
        <div class="actions"><button class="primary" type="submit">Tạo thiết bị để học lệnh</button></div>
      </form>
    </section>`;
  }

  renderSearchAdd() {
    const emitterOptions = this._hardware.emitters.map(x =>
      `<option value="${this.esc(x)}" ${this._discoverEmitter === x ? "selected" : ""}>${this.esc(x)}</option>`
    ).join("");
    const receiverOptions = `<option value="">Không dùng receiver</option>` + this._hardware.receivers.map(x =>
      `<option value="${this.esc(x)}" ${this._discoverReceiver === x ? "selected" : ""}>${this.esc(x)}</option>`
    ).join("");
    const enabled = (this._sources || []).filter(s => s.enabled);

    return `
      <div class="section-head">
        <div>
          <h3>Tìm theo hãng/model</h3>
          <p>Chọn loại và nhập hãng/model nếu biết. HanJoo tự tìm trên mọi nguồn đang bật rồi xếp phương án tốt nhất lên đầu.</p>
        </div>
      </div>

      <section class="subsection discover-box">
        <div class="discover-inputs">
          <label>Loại thiết bị
            <select id="discover-kind">
              <option value="" ${!this._discoverKind ? "selected" : ""}>Tự nhận / tất cả</option>
              <option value="air_conditioner" ${this._discoverKind === "air_conditioner" ? "selected" : ""}>Điều hòa</option>
              <option value="tv" ${this._discoverKind === "tv" ? "selected" : ""}>TV / Media</option>
              <option value="fan" ${this._discoverKind === "fan" ? "selected" : ""}>Quạt</option>
              <option value="projector" ${this._discoverKind === "projector" ? "selected" : ""}>Máy chiếu</option>
              <option value="speaker" ${this._discoverKind === "speaker" ? "selected" : ""}>Loa</option>
              <option value="soundbar" ${this._discoverKind === "soundbar" ? "selected" : ""}>Soundbar</option>
              <option value="receiver" ${this._discoverKind === "receiver" ? "selected" : ""}>Ampli / Receiver</option>
              <option value="light" ${this._discoverKind === "light" ? "selected" : ""}>Đèn / LED</option>
              <option value="air_purifier" ${this._discoverKind === "air_purifier" ? "selected" : ""}>Máy lọc không khí</option>
              <option value="camera" ${this._discoverKind === "camera" ? "selected" : ""}>Camera</option>
              <option value="console" ${this._discoverKind === "console" ? "selected" : ""}>Console</option>
              <option value="custom" ${this._discoverKind === "custom" ? "selected" : ""}>Khác / Custom</option>
            </select>
          </label>
          <label class="discover-query">Hãng hoặc model
            <input id="discover-search" value="${this.esc(this._discoverQuery)}" placeholder="Ví dụ: Daikin ARC433, LG AKB75215403, Samsung UE55…">
          </label>
          <button class="primary discover-search-btn" id="discover-now">Tìm cấu hình</button>
        </div>

        <div class="routing-mini">
          <div class="routing-title">IR blaster dùng cho Test/Thêm</div>
          <label>Transmitter
            <select id="discover-emitter">
              ${emitterOptions || `<option value="">Không có IR Transmitter</option>`}
            </select>
          </label>
          <label>Receiver
            <select id="discover-receiver">${receiverOptions}</select>
          </label>
        </div>

        <div class="source-strip">
          <span class="muted">Nguồn đang dùng:</span>
          ${enabled.map(s => `<span class="pill source-on">${this.esc(s.name)}</span>`).join("") || `<span class="warn">Chưa bật nguồn nào.</span>`}
          <button data-tab="library">⚙ Chọn nguồn</button>
        </div>
      </section>

      ${this._discoverLoading ? `<div class="online-status">⏳ Đang tìm và xếp hạng cấu hình…</div>` : ""}
      ${this._discoverError ? `<div class="callout error-callout">${this.esc(this._discoverError)}</div>` : ""}
      ${this._discoverErrors?.length ? `<div class="callout"><b>Một số nguồn online có lỗi nhưng các nguồn còn lại vẫn dùng được:</b><br>${this._discoverErrors.map(x => this.esc(x)).join("<br>")}</div>` : ""}

      ${this._discoverLoaded && !this._discoverLoading ? `
        <section class="subsection">
          <div class="section-head mini">
            <div>
              <h3>Kết quả đề xuất</h3>
              <p>Ưu tiên tự động: <b>Native HA</b> trước; với điều hòa ưu tiên <b>Protocol Engine</b> trước profile online; thiết bị khác ưu tiên <b>SmartIR/Flipper</b>. Learn/Custom luôn ở cuối.</p>
            </div>
            <span class="pill">${this._discoverItems.length} phương án</span>
          </div>
          ${this._discoverItems.length ? `<div class="discover-results">
            ${this._discoverItems.map((item, index) => `
              <article class="candidate-row ${item.recommended ? "recommended" : ""}">
                <div class="candidate-rank">${item.recommended ? "★" : index + 1}</div>
                <div class="candidate-main">
                  <div class="card-top">
                    <div class="grow">
                      <h4>${this.esc(item.brand ? `${item.brand}${item.model ? ` · ${item.model}` : ""}` : item.name)}</h4>
                      <div class="muted">${this.esc(item.note || item.controller || "")}</div>
                    </div>
                    ${item.recommended ? `<span class="best">Khuyên dùng</span>` : ""}
                  </div>
                  <div class="meta">
                    <span>${this.esc(this.sourceLabel(item.source))}</span>
                    <span>${this.esc(this.kindLabel(item.kind))}</span>
                    ${item.quality === "dynamic_state" ? `<span>⚙ Sinh mã động</span>` : ""}
                    ${item.installed_entries ? `<span>${item.installed_entries} đã cài</span>` : ""}
                    ${item.code ? `<span>Code ${this.esc(item.code)}</span>` : ""}
                  </div>
                </div>
                <div class="candidate-actions">
                  ${item.action === "native"
                    ? `<button class="primary" data-candidate-add="${this.esc(item.id)}">Thiết lập native</button>`
                    : item.action === "custom"
                      ? `<button data-candidate-add="${this.esc(item.id)}">Tạo & học lệnh</button>`
                      : `<button data-candidate-test="${this.esc(item.id)}">▶ Test</button><button class="primary" data-candidate-add="${this.esc(item.id)}">Dùng cấu hình này</button>`
                  }
                </div>
              </article>`).join("")}
          </div>` : `<div class="empty small">Không có cấu hình khớp từ các nguồn đã bật. Hãy bật Learn/Custom hoặc thử nhập chỉ tên hãng.</div>`}
        </section>
      ` : ""}

      <details class="advanced-add">
        <summary>Tùy chọn nâng cao / profile đã lưu</summary>
        <div class="advanced-body">
          <p class="muted">Bạn vẫn có thể vào Thư viện để import/export profile hoặc quản lý từng nguồn thủ công.</p>
          <button data-tab="library">Mở Thư viện IR</button>
        </div>
      </details>`;
  }

  renderLibrary() {
    return `
      <div class="section-head">
        <div><h2>Thư viện IR & nguồn tìm kiếm</h2>
        <p>Chọn những nguồn HanJoo được phép dùng khi thêm thiết bị. Càng ít nguồn càng gọn; HanJoo tự xếp hạng nên bạn không phải chọn nguồn mỗi lần.</p></div>
      </div>
      <section class="subsection">
        <div class="section-head mini">
          <div>
            <h3>Nguồn đầu vào</h3>
            <p class="muted">Mặc định khuyên dùng: Native HA + Protocol Engine + SmartIR + Learn/Custom. Flipper có thể bật thêm khi cần phạm vi model rộng hơn.</p>
          </div>
        </div>
        <div class="priority-flow">
          <span>Native HA</span><b>→</b>
          <span>Protocol Engine <small>${this.tr("(ưu tiên AC)", "(AC priority)")}</small></span><b>→</b>
          <span>SmartIR / Flipper</span><b>→</b>
          <span>Learn / Custom</span>
        </div>
        <div class="source-list">
          ${(this._sources || []).map(s => `
            <div class="source-row">
              <div class="grow">
                <b>${this.esc(s.name)}</b>
                <div class="muted">${this.esc(this.sourceNote(s))}</div>
                <div class="meta">
                  ${s.id === "protocol_engine" ? `<span>${s.core_available ? "Core ✓" : "Core offline"}</span>` : ""}
                  ${s.id === "protocol_engine" && s.core_package_version ? `<span>${this.tr("Add-on", "Add-on")} ${this.esc(s.core_package_version)}</span>` : ""}
                  ${s.id === "protocol_engine" && s.core_version ? `<span>${this.tr("Engine API", "Engine API")} ${this.esc(s.core_version)}</span>` : ""}
                  ${s.license ? `<span>${this.esc(s.license)}</span>` : ""}
                  ${s.catalog_count != null ? `<span>${this.esc(s.catalog_count)} ${this.tr("mục", "items")}</span>` : ""}
                  ${s.protocol_count ? `<span>${this.esc(s.protocol_count)} dynamic protocols</span>` : ""}${s.recognition_protocol_count ? `<span>${this.esc(s.recognition_protocol_count)} recognition protocols</span>` : ""}
                  ${s.brand_count ? `<span>${this.esc(s.brand_count)} ${this.tr("hãng", "brands")}</span>` : ""}
                  ${s.installed_count != null ? `<span>${this.esc(s.installed_count)} ${this.tr("integration đã cài", "installed integrations")}</span>` : ""}
                  ${(s.kinds || []).slice(0, 5).map(k => `<span>${this.esc(this.kindLabel(k))}</span>`).join("")}
                </div>
                ${s.last_error ? `<div class="source-error">⚠ ${this.esc(this.translateText(s.last_error))}</div>` : ""}
                ${s.id === "protocol_engine" && !s.core_available ? `<div class="muted">${this.tr("Trạng thái add-on Running chỉ có nghĩa container đang chạy; dòng lỗi phía trên cho biết Core API có thực sự healthy hay không.", "The add-on status Running only means the container is running; the error above shows whether the Core API itself is actually healthy.")}</div>` : ""}
              </div>
              <div class="source-actions">
                <span class="pill ${s.enabled ? "source-on" : ""}">${this.tr(s.enabled ? "Đang bật" : "Đang tắt", s.enabled ? "Enabled" : "Disabled")}</span>
                ${s.enabled && ["smartir","flipper_irdb"].includes(s.id) ? `<button data-source-refresh="${this.esc(s.id)}">${this.tr("↻ Làm mới", "↻ Refresh")}</button>` : ""}
                <button class="${s.enabled ? "" : "primary"}" data-source-toggle="${this.esc(s.id)}" data-source-enabled="${s.enabled ? "1" : "0"}">${this.tr(s.enabled ? "Tắt" : "Bật nguồn", s.enabled ? "Disable" : "Enable source")}</button>
              </div>
            </div>`).join("") || `<div class="muted">Không có source provider khả dụng.</div>`}
        </div>
      </section>
      <section class="drop">
        <div class="big">📚</div>
        <h3>Import profile / thư viện</h3>
        <p>Bạn vẫn có thể import <b>SmartIR JSON</b>, <b>HAIR .wig.json</b> và <b>HanJoo profile/library</b> từ file.</p>
        <input id="profile-file" type="file" multiple accept=".json,.wig.json,application/json">
        <div class="actions" style="justify-content:center"><button id="export-library">Export toàn bộ library</button></div>
        <div class="muted">Profile đã import được đưa vào tìm kiếm tự động ở trang Thêm thiết bị.</div>
      </section>
      ${this._profiles.length ? `<div class="grid">
        ${this._profiles.map(p => `
          <article class="card">
            <div class="card-top"><div class="grow">
              <h3>${this.esc(p.name)}</h3>
              <div class="muted">${this.esc([p.brand, p.model].filter(Boolean).join(" · ") || "Không rõ hãng/model")}</div>
            </div><span class="pill">${this.esc(p.source)}</span></div>
            <div class="meta"><span>${this.esc(this.semanticLabel(p.type))}</span><span>${p.command_count} lệnh</span>${p.climate_cell_count ? `<span>${p.climate_cell_count} state</span>` : ""}</div>
            ${p.warnings?.length ? `<details><summary>${p.warnings.length} cảnh báo import</summary><ul>${p.warnings.map(w => `<li>${this.esc(w)}</li>`).join("")}</ul></details>` : ""}
            <div class="actions">
              <button data-test-profile="${this.esc(p.id)}">Test</button>
              <button data-export-profile="${this.esc(p.id)}">Export</button>
              <button class="primary" data-add-profile="${this.esc(p.id)}">Dùng profile</button>
              <button class="danger" data-delete-profile="${this.esc(p.id)}">Xóa</button>
            </div>
          </article>`).join("")}
      </div>` : `<div class="empty small">Chưa có profile import.</div>`}
`;  }

  renderAbout() {
    return `
      <div class="section-head">
        <div>
          <h2>Thông tin HanJoo IR</h2>
        </div>
      </div>

      <section class="subsection about-page">
        <div class="about-brand">
          <div class="about-logo">H</div>
          <div>
            <h3>HanJoo IR Manager</h3>
            <div class="muted">Home Assistant infrared device manager</div>
          </div>
        </div>

        <div class="about-grid">
          <div><span>Tác giả / Maintainer</span><b>${this.esc(this._summary.author || "HanJoo")}</b></div>
          <div><span>Facebook</span><b>${this.esc(this._summary.author_facebook || "Kim Han Yuu")}</b></div>
          <div><span>Email</span><b><a href="mailto:${this.esc(this._summary.author_email || "kimhanzoo@gmail.com")}">${this.esc(this._summary.author_email || "kimhanzoo@gmail.com")}</a></b></div>
          <div><span>Phiên bản</span><b>${this.esc(this._summary.version || "0.4.2")}</b></div>
          <div><span>Ngôn ngữ giao diện</span><b>${this._lang === "vi" ? "Tiếng Việt" : "English"}</b></div>
        </div>
      </section>`;
  }

  renderHardware() {
    return `
      <div class="section-head">
        <div><h2>IR Blasters</h2>
        <p>HanJoo không khóa dữ liệu vào board. Emitter/receiver là hạ tầng; thiết bị và profile nằm ở HA.</p></div>
      </div>
      <div class="grid">
        <article class="card">
          <h3>📤 Emitters</h3>
          ${this._hardware.emitters.length ? `<ul class="entity-list">${this._hardware.emitters.map(x => `<li>${this.esc(x)}</li>`).join("")}</ul>` : `<p class="warn">Không tìm thấy Infrared Emitter.</p>`}
        </article>
        <article class="card">
          <h3>📥 Receivers</h3><p class="muted">Receiver được dùng cả để học mã và nghe remote thật nhằm cập nhật trạng thái thiết bị về Home Assistant.</p>
          ${this._hardware.receivers.length ? `<ul class="entity-list">${this._hardware.receivers.map(x => `<li>${this.esc(x)}</li>`).join("")}</ul>` : `<p class="warn">Không tìm thấy Infrared Receiver; vẫn phát được nhưng không thể học lệnh hoặc đồng bộ trạng thái từ remote thật.</p>`}
        </article>
      </div>
      <section class="subsection">
        <h3>Thiết kế dữ liệu</h3>
        <p><b>Home Assistant</b> giữ library + mappings + entity semantic. <b>ESPHome/Broadlink/MQTT IR</b> chỉ đảm nhiệm phát/thu. Vì vậy thay blaster không phải học lại thiết bị.</p>
      </section>`;
  }

  renderModal() {
    const d = this._detail;
    if (d.mode === "profile-add") return this.renderProfileAddModal(d.profile);
    if (d.mode === "profile-test") return this.renderProfileTestModal(d.profile);
    if (d.mode === "custom-add") return this.renderCustomAddModal(d);
    if (d.mode === "online-test") return this.renderOnlineTestModal(d.item);
    if (d.mode === "online-quick") return this.renderOnlineQuickModal(d);
    if (!d.device) return "";
    const device = d.device;
    const commands = Object.entries(device.commands || {});
    const emitters = new Set(device.emitter_entity_ids || []);
    const receiver = device.receiver_entity_id || "";
    return `
      <div class="modal-backdrop" data-close-modal>
        <div class="modal" data-modal-body>
          <div class="modal-head">
            <div><h2>${this.esc(device.name)}</h2><div class="muted">${this.esc(this.semanticLabel(device.type))} · ${this.esc(device.source)}</div></div>
            <button class="icon-btn" data-close-modal>✕</button>
          </div>

          <section class="modal-section">
            <h3>Định tuyến IR</h3><p class="muted">Chọn Receiver để bật đồng bộ 2 chiều: khi bạn bấm remote thật, HanJoo sẽ nhận diện lệnh/trạng thái và cập nhật entity Home Assistant.</p>
            <form id="routing-form" class="form-grid">
              <label>IR Transmitter
                <select name="emitter">${this._hardware.emitters.map(x => `<option value="${this.esc(x)}" ${emitters.has(x) ? "selected" : ""}>${this.esc(x)}</option>`).join("")}</select>
              </label>
              <label>IR Receiver
                <select name="receiver">${this._hardware.receivers.map(x => `<option value="${this.esc(x)}" ${receiver === x ? "selected" : ""}>${this.esc(x)}</option>`).join("")}<option value="" ${!receiver ? "selected" : ""}>Không dùng</option></select>
              </label>
              <div class="form-actions"><button type="submit">Lưu routing</button></div>
            </form>
          </section>

          ${device.type === "climate" ? this.renderClimateManager(device) : ""}

          <section class="modal-section">
            <div class="section-head mini"><div><h3>Lệnh phụ / fallback</h3><p>Nút có mã sẽ thành button nếu không được entity semantic đảm nhiệm.</p></div></div>
            <div class="command-list">
              ${commands.length ? commands.map(([id, c]) => `
                <div class="command-row">
                  <div class="grow"><b>${this.esc(c.name || id)}</b><div class="muted mono">${this.esc(id)}</div></div>
                  <span class="${c.codes?.length ? "ok" : "missing"}">${c.codes?.length ? "Đã học" : "Chưa học"}</span>
                  ${c.codes?.length ? `<button data-send-command="${this.esc(id)}">Test</button><button data-clear-command="${this.esc(id)}">Học lại</button>` : `<button class="primary" data-learn-command="${this.esc(id)}">Học</button>`}
                  <button class="danger subtle" data-delete-command="${this.esc(id)}">Xóa</button>
                </div>`).join("") : `<div class="muted">Không có lệnh phụ.</div>`}
            </div>
            <form id="add-command-form" class="inline-form">
              <input name="name" required placeholder="Tên nút tùy chỉnh">
              <button type="submit">+ Thêm nút</button>
            </form>
          </section>

          <div class="modal-footer">
            ${device.summary?.ha_device_id ? `<button data-overview="${this.esc(device.summary.ha_device_id)}">Mở device trong Home Assistant</button>` : ""}
            <button data-export-device>Export thiết bị</button>
            <button class="danger" data-delete-device>Xóa thiết bị</button>
          </div>
        </div>
      </div>`;
  }

  renderClimateManager(device) {
    const c = device.climate || {};
    const cells = c.cells || [];
    const protocol = device.protocol_engine;
    if (protocol) {
      return `
        <section class="modal-section climate-box">
          <h3>⚙️ Protocol Engine</h3>
          <p class="muted">Thiết bị này <b>không cần học từng nhiệt độ</b>. HanJoo tạo frame IR khi phát và, nếu có Receiver, giải mã remote thật để đồng bộ trạng thái về Home Assistant.</p>
          <div class="meta">
            <span>${this.esc(protocol.variant || protocol.engine)}</span>
            <span>${this.esc(c.min_temp ?? 16)}–${this.esc(c.max_temp ?? 30)}°${this.esc(c.unit || "C")}</span>
            <span>${this.esc((c.modes || []).join(", "))}</span>
            <span>Fan: ${this.esc((c.fan_modes || []).join(", "))}</span>
          </div>
          <div class="callout">Test nhanh từ trang <b>Thêm thiết bị</b> dùng trạng thái Cool 25°C · Fan Auto. Sau khi thêm, điều khiển trực tiếp bằng entity climate của Home Assistant.</div>
        </section>`;
    }
    return `
      <section class="modal-section climate-box">
        <h3>❄️ Climate state matrix</h3>
        <p class="muted">Mỗi mã là <b>một trạng thái đầy đủ</b>. Đây là cách đúng với remote điều hòa stateful.</p>
        <div class="meta">
          <span>${cells.length} trạng thái</span>
          <span>${this.esc((c.modes || []).join(", ") || "chưa có mode")}</span>
          <span>${this.esc(c.min_temp ?? 16)}–${this.esc(c.max_temp ?? 30)}°${this.esc(c.unit || "C")}</span>
        </div>
        <form id="climate-learn-form" class="form-grid climate-form">
          <label>Loại frame
            <select name="power">
              <option value="state">Trạng thái hoạt động</option>
              <option value="off">Power OFF</option>
              <option value="on">Power ON riêng</option>
            </select>
          </label>
          <label>Mode<select name="mode">
            ${["cool","dry","fan_only","heat","auto"].map(x => `<option value="${x}">${x}</option>`).join("")}
          </select></label>
          <label>Nhiệt độ<input name="temp" type="number" step="${this.esc(c.precision || 1)}" min="${this.esc(c.min_temp ?? 16)}" max="${this.esc(c.max_temp ?? 30)}" value="25"></label>
          <label>Fan<input name="fan" placeholder="auto / low / medium / high" value="auto"></label>
          <label>Swing<input name="swing" placeholder="off / on" value="off"></label>
          <div class="form-actions"><button class="primary" type="submit">Học trạng thái này</button></div>
        </form>
        ${cells.length ? `<details><summary>Xem ${cells.length} trạng thái đã có</summary>
          <div class="cell-list">${cells.slice(0, 250).map(x => `<span>${this.esc([x.mode, x.fan, x.swing, x.temp != null ? `${x.temp}°` : null].filter(Boolean).join(" · "))}</span>`).join("")}${cells.length > 250 ? `<span>… +${cells.length - 250}</span>` : ""}</div>
        </details>` : ""}
      </section>`;
  }

  renderLearnDialog() {
    const d = this._learnDialog;
    if (!d) return "";
    const isWaiting = d.stage === "waiting";
    const isPreview = d.stage === "preview";
    const isSaving = d.stage === "saving";
    const title = d.target === "climate"
      ? "Học trạng thái điều hòa"
      : `Học: ${this.esc(d.commandName || d.commandId || "lệnh IR")}`;

    return `<div class="learn-backdrop">
      <div class="learn-dialog">
        <div class="learn-head">
          <div><h2>${title}</h2><div class="muted">${this.esc(d.deviceName || "")}</div></div>
          ${!isSaving ? `<button class="icon-btn" data-cancel-learn>✕</button>` : ""}
        </div>
        ${isWaiting ? `
          <div class="learn-body centered">
            <div class="signal-animation"><span></span><span></span><span></span></div>
            <h3>Đang chờ tín hiệu IR…</h3>
            <p>Chĩa remote gốc vào mắt thu IR rồi bấm <b>một lần</b> nút cần học.</p>
            <div class="countdown-note">Thời gian chờ tối đa: ${d.timeout || 20} giây</div>
            <button data-cancel-learn>Hủy</button>
          </div>` : ""}
        ${isPreview ? `
          <div class="learn-body">
            <div class="${d.capture.can_save === false ? "capture-bad" : d.capture.quality === "warning" ? "capture-warn" : "capture-ok"}">
              ${d.capture.can_save === false ? "⚠ Tín hiệu chưa hợp lệ" : d.capture.quality === "warning" ? "⚠ Đã nhận tín hiệu, nhưng frame khá ngắn" : "✓ Đã nhận được tín hiệu"}
            </div>
            ${d.capture.quality_message ? `<div class="callout ${d.capture.can_save === false ? "error-callout" : ""}">${this.esc(d.capture.quality_message)}</div>` : ""}
            <div class="capture-grid">
              <div><span>Tần số</span><b>${this.esc(d.capture.frequency)} Hz</b></div>
              <div><span>Số timing</span><b>${this.esc(d.capture.timing_count)}</b></div>
              <div><span>Độ dài frame</span><b>${this.esc(d.capture.duration_ms)} ms</b></div>
            </div>
            <label class="preview-label">Xem trước timing</label>
            <div class="timing-preview mono">${this.esc((d.capture.preview || []).join(", "))}${d.capture.truncated ? ", …" : ""}</div>
            <p class="muted preview-note">Mã này <b>chưa được lưu</b>. Hãy lưu nếu đúng lần bấm vừa rồi, hoặc học lại nếu remote bị bấm nhầm/nhiễu.</p>
            <div class="learn-actions">
              <button data-retry-learn>↻ Học lại</button>
              <button data-cancel-learn>Hủy</button>
              <button class="primary" data-save-learn ${d.capture.can_save === false ? "disabled" : ""}>✓ Lưu mã này</button>
            </div>
          </div>` : ""}
        ${isSaving ? `
          <div class="learn-body centered"><h3>Đang lưu mã IR…</h3></div>` : ""}
        ${d.stage === "error" ? `
          <div class="learn-body centered">
            <div class="learn-error">❌ ${this.esc(d.error || "Không nhận được tín hiệu")}</div>
            <div class="learn-actions"><button data-retry-learn>Thử lại</button><button data-cancel-learn>Đóng</button></div>
          </div>` : ""}
      </div>
    </div>`;
  }

  renderCustomAddModal(state) {
    const kind = state.kind || this._discoverKind || "custom";
    const suggested = state.name || this._discoverQuery || `Thiết bị ${this.kindLabel(kind)}`;
    return `<div class="modal-backdrop" data-close-modal><div class="modal small-modal" data-modal-body>
      <div class="modal-head">
        <div><h2>Học / Custom</h2><div class="muted">${this.esc(this.kindLabel(kind))}</div></div>
        <button class="icon-btn" data-close-modal>✕</button>
      </div>
      <p style="padding:0 20px">Tạo thiết bị rồi HanJoo sẽ cho bạn học từng nút từ remote thật. Đây là fallback khi các cấu hình tự động không đúng.</p>
      <form id="custom-form" class="form-grid">
        <label>Tên thiết bị<input name="name" required value="${this.esc(suggested)}"></label>
        <input type="hidden" name="kind" value="${this.esc(kind)}">
        <label>IR Transmitter
          <select name="emitter" required>
            ${this._hardware.emitters.map(x => `<option value="${this.esc(x)}" ${this._discoverEmitter === x ? "selected" : ""}>${this.esc(x)}</option>`).join("")}
          </select>
        </label>
        <label>IR Receiver
          <select name="receiver">
            <option value="">Không dùng receiver</option>
            ${this._hardware.receivers.map(x => `<option value="${this.esc(x)}" ${this._discoverReceiver === x ? "selected" : ""}>${this.esc(x)}</option>`).join("")}
          </select>
        </label>
        <div class="form-actions"><button class="primary" type="submit">Tạo thiết bị để học lệnh</button></div>
      </form>
    </div></div>`;
  }

  renderProfileAddModal(profile) {
    return `<div class="modal-backdrop" data-close-modal><div class="modal small-modal" data-modal-body>
      <div class="modal-head"><div><h2>Thêm từ profile</h2><div class="muted">${this.esc(profile.name)}</div></div><button class="icon-btn" data-close-modal>✕</button></div>
      <form id="profile-add-form" class="form-grid">
        <label>Tên thiết bị<input name="name" required value="${this.esc(profile.name)}"></label>
        <label>IR Transmitter<select name="emitter" required>${this.entityOptions(this._hardware.emitters, "Chọn transmitter")}</select></label>
        <label>IR Receiver<select name="receiver">${this.entityOptions(this._hardware.receivers, "Không dùng receiver", true)}</select></label>
        <div class="form-actions"><button class="primary" type="submit">Thêm ${this.esc(this.semanticLabel(profile.type))}</button></div>
      </form>
    </div></div>`;
  }

  renderProfileTestModal(profile) {
    return `<div class="modal-backdrop" data-close-modal><div class="modal small-modal" data-modal-body>
      <div class="modal-head"><div><h2>Test profile</h2><div class="muted">${this.esc(profile.name)}</div></div><button class="icon-btn" data-close-modal>✕</button></div>
      <p>Đặt IR blaster hướng về thiết bị. HanJoo sẽ phát Power/On/Off hoặc state đại diện.</p>
      <form id="profile-test-form" class="form-grid">
        <label>IR Transmitter<select name="emitter" required>${this.entityOptions(this._hardware.emitters, "Chọn transmitter")}</select></label>
        <div class="form-actions"><button class="primary" type="submit">▶ Phát mã test</button></div>
      </form>
      <div class="callout">Nếu thiết bị phản hồi đúng, đóng cửa sổ và chọn <b>Thêm thiết bị</b>. Nếu không, thử profile khác trong thư viện.</div>
    </div></div>`;
  }

  renderOnlineQuickModal(state) {
    const items = state.items || [];
    const index = Math.max(0, Math.min(state.index || 0, Math.max(0, items.length - 1)));
    const item = items[index];
    if (!item) return "";
    const savedEmitter = state.emitter || "";
    return `<div class="modal-backdrop" data-close-modal><div class="modal small-modal" data-modal-body>
      <div class="modal-head">
        <div>
          <h2>⚡ Thử nhanh profile</h2>
          <div class="muted">Mã ${index + 1}/${items.length} · ${this.esc(item.brand)} · ${this.esc(item.model)}</div>
        </div>
        <button class="icon-btn" data-close-modal>✕</button>
      </div>
      <div class="quick-progress"><span style="width:${Math.round(((index + 1) / items.length) * 100)}%"></span></div>
      <div class="quick-body">
        <p>Hướng IR blaster vào thiết bị rồi bấm <b>Phát thử</b>. Nếu thiết bị không phản hồi, chọn <b>Không đúng → mã tiếp</b>. Khi phản hồi đúng, chọn <b>Đúng → dùng mã này</b>.</p>
        <div class="candidate-card">
          <b>${this.esc(item.brand)}</b>
          <div>${this.esc(item.model)}</div>
          <div class="meta"><span>${this.esc(this.semanticLabel(item.kind))}</span><span>SmartIR ${this.esc(item.code)}</span>${item.controller ? `<span>${this.esc(item.controller)}</span>` : ""}</div>
        </div>
        <label>IR Transmitter
          <select id="quick-emitter" required>
            ${this._hardware.emitters.map(x => `<option value="${this.esc(x)}" ${savedEmitter === x ? "selected" : ""}>${this.esc(x)}</option>`).join("")}
          </select>
        </label>
        ${!this._hardware.emitters.length ? `<div class="callout error-callout">Không có Infrared Emitter để thử.</div>` : ""}
        <div class="quick-actions">
          <button id="quick-prev" ${index <= 0 ? "disabled" : ""}>← Mã trước</button>
          <button class="primary" id="quick-test" ${!this._hardware.emitters.length ? "disabled" : ""}>▶ Phát thử</button>
          <button id="quick-next" ${index >= items.length - 1 ? "disabled" : ""}>Không đúng → mã tiếp</button>
        </div>
        <button class="success-btn" id="quick-accept" ${!this._hardware.emitters.length ? "disabled" : ""}>✓ Đúng → lưu và dùng mã này</button>
        ${index >= items.length - 1 ? `<div class="muted center-note">Đã đến profile cuối trong danh sách hiện tại. Có thể sửa từ khóa/model để tìm nhóm khác.</div>` : ""}
      </div>
    </div></div>`;
  }

  renderOnlineTestModal(item) {
    return `<div class="modal-backdrop" data-close-modal><div class="modal small-modal" data-modal-body>
      <div class="modal-head"><div><h2>Test profile online</h2><div class="muted">${this.esc(item.brand)} · ${this.esc(item.model)}</div></div><button class="icon-btn" data-close-modal>✕</button></div>
      <p style="padding:0 20px">HanJoo sẽ tải profile SmartIR tạm thời và phát Power/On/Off hoặc một state đại diện. Profile <b>chưa được lưu</b> chỉ vì bạn Test.</p>
      <form id="online-test-form" class="form-grid" style="padding:0 20px 20px">
        <label>IR Transmitter<select name="emitter" required>${this.entityOptions(this._hardware.emitters, "Chọn transmitter")}</select></label>
        <div class="form-actions"><button class="primary" type="submit">▶ Phát mã test</button></div>
      </form>
      <div class="modal-footer">
        <button class="primary" data-online-install="${this.esc(item.id)}">Lưu profile này vào HanJoo</button>
      </div>
    </div></div>`;
  }

  entityOptions(values, emptyLabel, allowEmpty = false) {
    const empty = allowEmpty
      ? `<option value="">${this.esc(emptyLabel)}</option>`
      : `<option value="" disabled selected>${this.esc(emptyLabel)}</option>`;
    return empty + values.map(x => `<option value="${this.esc(x)}">${this.esc(x)}</option>`).join("");
  }

  navigateInHomeAssistant(path, replace = false) {
    if (!path || !path.startsWith("/")) return;
    if (replace) window.history.replaceState(null, "", path);
    else window.history.pushState(null, "", path);
    window.dispatchEvent(new CustomEvent("location-changed"));
  }

  bind() {
    const q = sel => this.shadowRoot.querySelector(sel);
    const qa = sel => [...this.shadowRoot.querySelectorAll(sel)];

    qa("[data-tab]").forEach(el => el.addEventListener("click", () => {
      this._tab = el.dataset.tab;
      this._detail = null;
      this.render();
    }));

    qa("[data-native]").forEach(el => el.addEventListener("click", () => {
      const domain = el.dataset.native;
      this.navigateInHomeAssistant(`/config/integrations/dashboard/add?domain=${encodeURIComponent(domain)}`);
    }));

    qa("[data-native-settings]").forEach(el => el.addEventListener("click", () => {
      this.navigateInHomeAssistant(`/config/integrations/integration/${encodeURIComponent(el.dataset.nativeSettings)}`);
    }));

    qa("[data-overview]").forEach(el => el.addEventListener("click", () => {
      // HA's native device page hard-codes its toolbar Back target to the
      // Devices dashboard. Remember that this device was opened from HanJoo;
      // the module-level route guard redirects that one Back navigation to
      // HanJoo's Devices tab instead.
      try {
        sessionStorage.setItem(HANJOO_DEVICE_RETURN_KEY, JSON.stringify({
          deviceId: String(el.dataset.overview || ""),
          returnPath: "/hanjoo-ir",
          openedAt: Date.now(),
        }));
      } catch (_) {}
      this.navigateInHomeAssistant(`/config/devices/device/${encodeURIComponent(el.dataset.overview)}`);
    }));

    qa("[data-manage]").forEach(el => el.addEventListener("click", async () => {
      await this.openDevice(el.dataset.manage);
    }));

    qa("[data-delete-card]").forEach(el => el.addEventListener("click", async () => {
      await this.deleteDeviceById(el.dataset.deleteCard);
    }));

    qa("[data-add-mode]").forEach(el => el.addEventListener("click", () => {
      this._addMode = el.dataset.addMode || "search";
      this._identifyError = "";
      this.render();
    }));
    const identifyKind = q("#identify-kind");
    if (identifyKind) identifyKind.addEventListener("change", e => { this._identifyKind = e.target.value; this._identifyCaptures = []; this._identifyStepErrors = {}; this._identifyResult = null; this._identifyVerified = new Set(); this._identifyError = ""; this.render(); });
    const identifyQuery = q("#identify-query");
    if (identifyQuery) identifyQuery.addEventListener("input", e => { this._identifyQuery = e.target.value; });
    const identifyReceiver = q("#identify-receiver");
    if (identifyReceiver) identifyReceiver.addEventListener("change", e => { this._discoverReceiver = e.target.value; this._identifyCaptures = []; this._identifyStepErrors = {}; this._identifyResult = null; });
    const identifyEmitter = q("#identify-emitter");
    if (identifyEmitter) identifyEmitter.addEventListener("change", e => { this._discoverEmitter = e.target.value; });
    qa("[data-identify-capture]").forEach(el => el.addEventListener("click", () => this.retryIdentifyStep(Number(el.dataset.identifyCapture))));
    const identifyStart = q("#identify-start");
    if (identifyStart) identifyStart.addEventListener("click", () => this.startRemoteIdentifySequence());
    const identifyAnalyze = q("#identify-analyze");
    if (identifyAnalyze) identifyAnalyze.addEventListener("click", () => this.analyzeRemoteIdentity());
    const identifyReset = q("#identify-reset");
    if (identifyReset) identifyReset.addEventListener("click", () => { this._identifyCaptures = []; this._identifyStepErrors = {}; this._identifyResult = null; this._identifyVerified = new Set(); this._identifyError = ""; this.render(); });
    qa("[data-identify-test]").forEach(el => el.addEventListener("click", () => this.testIdentifiedCandidate(el.dataset.identifyTest)));
    qa("[data-identify-add]").forEach(el => el.addEventListener("click", () => this.addIdentifiedCandidate(el.dataset.identifyAdd)));

    const identifySearch = q("[data-identify-search]");
    if (identifySearch) identifySearch.addEventListener("click", () => {
      const best = this._identifyResult?.candidates?.[0]?.candidate || {};
      this._discoverQuery = best.brand || "";
      this._addMode = "search"; this._discoverLoaded = false; this.render();
      setTimeout(() => this.shadowRoot?.querySelector("#discover-search")?.focus(), 0);
    });
    const identifyManual = q("[data-identify-manual]");
    if (identifyManual) identifyManual.addEventListener("click", () => { this._addMode = "manual"; this.render(); });
    const manualAdd = q("#manual-add-form");
    if (manualAdd) manualAdd.addEventListener("submit", e => this.createManualDevice(e));

    const discoverSearch = q("#discover-search");
    if (discoverSearch) {
      discoverSearch.addEventListener("input", e => {
        // Typing only updates the local query. Search starts on Enter or the
        // explicit Find configuration button, so rendering/network work cannot
        // steal focus while the user is typing.
        this._discoverQuery = e.target.value;
      });
      discoverSearch.addEventListener("keydown", e => {
        if (e.key === "Enter") {
          e.preventDefault();
          this.loadDiscovery(true);
        }
      });
    }
    const discoverKind = q("#discover-kind");
    if (discoverKind) discoverKind.addEventListener("change", e => {
      this._discoverKind = e.target.value;
      this._discoverLoaded = false;
      this.render();
    });
    const discoverNow = q("#discover-now");
    if (discoverNow) discoverNow.addEventListener("click", () => this.loadDiscovery(true));

    const discoverEmitter = q("#discover-emitter");
    if (discoverEmitter) discoverEmitter.addEventListener("change", e => {
      this._discoverEmitter = e.target.value;
    });
    const discoverReceiver = q("#discover-receiver");
    if (discoverReceiver) discoverReceiver.addEventListener("change", e => {
      this._discoverReceiver = e.target.value;
    });

    qa("[data-candidate-test]").forEach(el => el.addEventListener("click", () => {
      this.testCandidate(el.dataset.candidateTest);
    }));
    qa("[data-candidate-add]").forEach(el => el.addEventListener("click", () => {
      this.addCandidate(el.dataset.candidateAdd);
    }));

    const search = q("#profile-search");
    if (search) search.addEventListener("input", e => {
      this._search = e.target.value;
      this.render();
      const again = this.shadowRoot.querySelector("#profile-search");
      if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
    });

    const onlineSearch = q("#online-search");
    if (onlineSearch) onlineSearch.addEventListener("input", e => {
      this._onlineQuery = e.target.value;
      clearTimeout(this._onlineSearchTimer);
      this._onlineSearchTimer = setTimeout(() => this.loadOnline(false), 450);
    });
    const onlineKind = q("#online-kind");
    if (onlineKind) onlineKind.addEventListener("change", e => {
      this._onlineKind = e.target.value;
      this.loadOnline(false);
    });
    const onlineRefresh = q("#online-refresh");
    if (onlineRefresh) onlineRefresh.addEventListener("click", () => this.loadOnline(true));
    const onlineQuickStart = q("#online-quick-start");
    if (onlineQuickStart) onlineQuickStart.addEventListener("click", () => {
      this._detail = {
        mode: "online-quick",
        items: [...this._onlineItems],
        index: 0,
        emitter: this._hardware.emitters[0] || "",
      };
      this.render();
    });

    qa("[data-online-test]").forEach(el => el.addEventListener("click", () => {
      const item = this._onlineItems.find(x => x.id === el.dataset.onlineTest);
      if (item) { this._detail = { mode: "online-test", item }; this.render(); }
    }));
    qa("[data-online-install]").forEach(el => el.addEventListener("click", () => this.installOnline(el.dataset.onlineInstall)));

    const custom = q("#custom-form");
    if (custom) custom.addEventListener("submit", e => this.createCustom(e));

    const file = q("#profile-file");
    if (file) file.addEventListener("change", e => this.importFile(e));
    const exportLibrary = q("#export-library");
    if (exportLibrary) exportLibrary.addEventListener("click", () => this.exportLibrary());

    qa("[data-source-toggle]").forEach(el => el.addEventListener("click", () => {
      this.toggleSource(
        el.dataset.sourceToggle,
        el.dataset.sourceEnabled !== "1"
      );
    }));
    qa("[data-source-refresh]").forEach(el => el.addEventListener("click", () => {
      this.refreshOnlineSource(el.dataset.sourceRefresh);
    }));

    qa("[data-add-profile]").forEach(el => el.addEventListener("click", () => {
      const profile = this._profiles.find(p => p.id === el.dataset.addProfile);
      if (profile) { this._detail = { mode: "profile-add", profile }; this.render(); }
    }));
    qa("[data-test-profile]").forEach(el => el.addEventListener("click", () => {
      const profile = this._profiles.find(p => p.id === el.dataset.testProfile);
      if (profile) { this._detail = { mode: "profile-test", profile }; this.render(); }
    }));
    qa("[data-delete-profile]").forEach(el => el.addEventListener("click", () => this.deleteProfile(el.dataset.deleteProfile)));
    qa("[data-export-profile]").forEach(el => el.addEventListener("click", () => this.exportProfile(el.dataset.exportProfile)));

    qa("[data-close-modal]").forEach(el => el.addEventListener("click", e => {
      if (e.target.closest("[data-modal-body]") && !e.target.hasAttribute("data-close-modal")) return;
      this._detail = null; this.render();
    }));

    const modalBody = q("[data-modal-body]");
    if (modalBody) modalBody.addEventListener("click", e => e.stopPropagation());

    const profileAdd = q("#profile-add-form");
    if (profileAdd) profileAdd.addEventListener("submit", e => this.createFromProfile(e));
    const profileTest = q("#profile-test-form");
    if (profileTest) profileTest.addEventListener("submit", e => this.testProfile(e));

    const onlineTest = q("#online-test-form");
    if (onlineTest) onlineTest.addEventListener("submit", e => this.testOnline(e));

    const quickEmitter = q("#quick-emitter");
    if (quickEmitter) quickEmitter.addEventListener("change", e => {
      if (this._detail?.mode === "online-quick") this._detail.emitter = e.target.value;
    });
    const quickPrev = q("#quick-prev");
    if (quickPrev) quickPrev.addEventListener("click", () => this.quickMove(-1));
    const quickNext = q("#quick-next");
    if (quickNext) quickNext.addEventListener("click", () => this.quickMove(1));
    const quickTest = q("#quick-test");
    if (quickTest) quickTest.addEventListener("click", () => this.quickTest());
    const quickAccept = q("#quick-accept");
    if (quickAccept) quickAccept.addEventListener("click", () => this.quickAccept());

    const routing = q("#routing-form");
    if (routing) routing.addEventListener("submit", e => this.updateRouting(e));
    const addCommand = q("#add-command-form");
    if (addCommand) addCommand.addEventListener("submit", e => this.addCommand(e));
    const climateLearn = q("#climate-learn-form");
    if (climateLearn) climateLearn.addEventListener("submit", e => this.learnClimate(e));

    qa("[data-learn-command]").forEach(el => el.addEventListener("click", () => this.learnCommand(el.dataset.learnCommand)));
    qa("[data-clear-command]").forEach(el => el.addEventListener("click", () => this.learnCommand(el.dataset.clearCommand)));
    qa("[data-send-command]").forEach(el => el.addEventListener("click", () => this.sendCommand(el.dataset.sendCommand)));
    qa("[data-delete-command]").forEach(el => el.addEventListener("click", () => this.deleteCommand(el.dataset.deleteCommand)));

    qa("[data-cancel-learn]").forEach(el => el.addEventListener("click", () => this.cancelLearn()));
    qa("[data-retry-learn]").forEach(el => el.addEventListener("click", () => this.retryLearn()));
    qa("[data-save-learn]").forEach(el => el.addEventListener("click", () => this.saveLearn()));

    const deleteDevice = q("[data-delete-device]");
    if (deleteDevice) deleteDevice.addEventListener("click", () => this.deleteDevice());
    const exportDevice = q("[data-export-device]");
    if (exportDevice) exportDevice.addEventListener("click", () => this.exportDevice());
  }

  async openDevice(deviceId) {
    try {
      const device = await this.ws("device", { device_id: deviceId });
      this._detail = { mode: "device", device };
      this.render();
    } catch (err) { this.toast(this.errText(err), true); }
  }

  quickMove(delta) {
    if (this._detail?.mode !== "online-quick") return;
    const state = this._detail;
    state.index = Math.max(0, Math.min(state.items.length - 1, state.index + delta));
    this.render();
  }

  async quickTest() {
    if (this._detail?.mode !== "online-quick") return;
    const state = this._detail;
    const item = state.items[state.index];
    const emitter = state.emitter || this.shadowRoot.querySelector("#quick-emitter")?.value || "";
    if (!emitter) return this.toast("Hãy chọn IR Transmitter", true);
    state.emitter = emitter;
    try {
      this._busyText = `⏳ Đang tải và phát thử ${item.brand} ${item.model}…`;
      this.render();
      const result = await this.ws("online/test", {
        catalog_id: item.id,
        emitter,
      });
      this._busyText = "";
      this.toast(`Đã phát: ${result.label}. Thiết bị có phản hồi không?`);
      this.render();
    } catch (err) {
      this._busyText = "";
      this.toast(this.errText(err), true);
    }
  }

  async quickAccept() {
    if (this._detail?.mode !== "online-quick") return;
    const state = this._detail;
    const item = state.items[state.index];
    try {
      this._busyText = `⏳ Đang lưu profile ${item.brand} ${item.model}…`;
      this.render();
      const result = await this.ws("online/install", { catalog_id: item.id });
      this._busyText = "";
      await this.loadAll();
      const profile = this._profiles.find(p => p.id === result.profile_id);
      if (profile) {
        this._detail = { mode: "profile-add", profile };
        this.render();
        this.toast(result.already_installed ? "Profile đã có sẵn; hãy chọn tên và emitter để thêm thiết bị" : "Đã lưu profile; bước cuối là thêm thiết bị");
      } else {
        this._detail = null;
        this._tab = "library";
        this.render();
        this.toast("Đã lưu profile vào thư viện HanJoo");
      }
    } catch (err) {
      this._busyText = "";
      this.toast(this.errText(err), true);
    }
  }

  async toggleSource(sourceId, enabled) {
    try {
      this._busyText = enabled ? "⏳ Đang bật và kiểm tra nguồn…" : "⏳ Đang tắt nguồn…";
      this.render();
      await this.ws("source/set", {
        source_id: sourceId,
        enabled,
      });
      this._busyText = "";
      this._sources = await this.ws("sources");
      this._discoverLoaded = false;
      await this.loadDiscovery();
      this.render();
      this.toast(enabled ? "Đã bật nguồn" : "Đã tắt nguồn");
    } catch (err) {
      this._busyText = "";
      try { this._sources = await this.ws("sources"); } catch (_) {}
      this.render();
      this.toast(this.errText(err), true);
    }
  }

  async refreshOnlineSource(sourceId) {
    try {
      this._busyText = "⏳ Đang làm mới catalog nguồn…";
      this.render();
      const result = await this.ws("online/source/refresh", {
        source_id: sourceId,
      });
      this._busyText = "";
      this._onlineLoaded = false;
      this._sources = await this.ws("sources");
      this._discoverLoaded = false;
      await this.loadDiscovery();
      this.render();
      this.toast(`Đã làm mới ${result.catalog_count || 0} profile`);
    } catch (err) {
      this._busyText = "";
      try { this._sources = await this.ws("sources"); } catch (_) {}
      this.render();
      this.toast(this.errText(err), true);
    }
  }

  async captureIdentifyStep(stepIndex) {
    const receiver = this._discoverReceiver || this._hardware.receivers[0] || "";
    if (!receiver) { this.toast("Hãy chọn IR Receiver", true); return false; }
    const step = this.identifySteps()[stepIndex];
    if (!step) return false;
    try {
      this._identifyCapturing = true;
      this._identifyError = "";
      this._identifyResult = null;
      this._busyText = `⏳ ${step.label}: ${this.tr("hãy bấm nút trên remote…", "press the remote button now…")}`;
      this.render();
      const result = await this.ws("remote_identify/capture", { receiver, timeout: 20 });
      this._identifyCapturing = false; this._busyText = "";
      if (!result.usable) {
        this._identifyStepErrors = { ...(this._identifyStepErrors || {}), [stepIndex]: result.quality_message || this.tr("Tín hiệu không đủ chất lượng. Hãy thu lại.", "Signal quality is insufficient. Capture again.") };
        this._identifyError = this.tr(`Mẫu ${stepIndex + 1} chưa hợp lệ. Hãy bấm “Thu lại” tại bước này.`, `Sample ${stepIndex + 1} is invalid. Use “Capture again” for this step.`);
        this.render();
        return false;
      }
      const row = { step: stepIndex, label: step.label, expected: step.expected, timings: result.timings, frequency: result.frequency, timing_count: result.timing_count, duration_ms: result.duration_ms, quality: result.quality, probe: result.probe || null };
      this._identifyCaptures = [...this._identifyCaptures.filter(x => x.step !== stepIndex), row].sort((a,b) => a.step-b.step);
      const errors = { ...(this._identifyStepErrors || {}) }; delete errors[stepIndex]; this._identifyStepErrors = errors;
      this._identifyVerified = new Set();
      this.render();
      return true;
    } catch (err) {
      this._identifyCapturing = false; this._busyText = "";
      this._identifyStepErrors = { ...(this._identifyStepErrors || {}), [stepIndex]: this.errText(err) };
      this._identifyError = this.tr(`Không thu được mẫu ${stepIndex + 1}. Hãy thử lại bước này.`, `Could not capture sample ${stepIndex + 1}. Retry this step.`);
      this.render();
      return false;
    }
  }

  async startRemoteIdentifySequence(startAt = null) {
    if (this._identifyAutoRunning || this._identifyCapturing) return;
    const steps = this.identifySteps();
    let first = Number.isInteger(startAt) ? startAt : steps.findIndex((_, i) => !this._identifyCaptures.some(x => x.step === i));
    if (first < 0) first = 0;
    this._identifyAutoRunning = true;
    this._identifyError = "";
    this.render();
    for (let i = first; i < steps.length; i++) {
      if (this._identifyCaptures.some(x => x.step === i) && i !== startAt) continue;
      const ok = await this.captureIdentifyStep(i);
      if (!ok) { this._identifyAutoRunning = false; this.render(); return; }
    }
    this._identifyAutoRunning = false;
    this.render();
    if (this._identifyCaptures.length >= steps.length) await this.analyzeRemoteIdentity(true);
  }

  async retryIdentifyStep(stepIndex) {
    if (this._identifyCapturing || this._identifyAutoRunning) return;
    const ok = await this.captureIdentifyStep(stepIndex);
    if (!ok) return;
    const steps = this.identifySteps();
    const next = steps.findIndex((_, i) => i > stepIndex && !this._identifyCaptures.some(x => x.step === i));
    if (next >= 0) await this.startRemoteIdentifySequence(next);
    else if (this._identifyCaptures.length >= steps.length) await this.analyzeRemoteIdentity(true);
  }

  async analyzeRemoteIdentity(autoRun = false) {
    if ((this._identifyCaptures || []).length < 3) return this.toast("Cần ít nhất 3 mẫu remote", true);
    try {
      this._identifyAnalyzing = true; this._identifyError = ""; this._identifyVerified = new Set(); this._busyText = this.tr("⏳ Fusion Matcher đang đối chiếu HanJoo Protocol + thư viện…", "⏳ Fusion Matcher is comparing HanJoo Protocol + library profiles…"); this.render();
      const result = await this.ws("fusion/identify", { kind_hint: this._identifyKind || "auto", query_hint: this._identifyQuery || "", captures: this._identifyCaptures.map(x => ({ label: x.label, expected: x.expected, timings: x.timings, frequency: x.frequency })) });
      this._identifyAnalyzing = false; this._busyText = ""; this._identifyResult = result; this.render();
      if (result.recommended) this.toast("Đã tìm thấy một protocol đủ độ tin cậy để khuyến nghị.");
      else this.toast("Chưa đủ độ tin cậy để HanJoo khuyến nghị tự động.", true);
    } catch (err) { this._identifyAnalyzing = false; this._busyText = ""; this._identifyError = this.errText(err); this.render(); }
  }

  identifiedCandidate(candidateId) {
    return (this._identifyResult?.candidates || []).find(x => x?.candidate?.id === candidateId)?.candidate || null;
  }

  async testIdentifiedCandidate(candidateId) {
    const item = this.identifiedCandidate(candidateId); if (!item) return;
    const emitter = this._discoverEmitter || this._hardware.emitters[0] || "";
    if (!emitter) return this.toast("Hãy chọn IR Transmitter", true);
    try {
      this._busyText = `⏳ Đang phát test ${item.brand || ""} ${item.model || ""}…`; this.render();
      let result;
      if (item.source === "protocol_engine") result = await this.ws("protocol/test", { candidate_id: item.id, emitter });
      else if (item.source === "saved_profile") result = await this.ws("profile/test", { profile_id: item.profile_id, emitter });
      else if (item.catalog_id) result = await this.ws("online/test", { catalog_id: item.catalog_id, emitter });
      else throw new Error("Ứng viên không có nguồn Test hợp lệ");
      this._busyText = "";
      this.render();
      const responded = window.confirm(this.tr(
        `HanJoo vừa phát mã Test cho ${item.brand || ""} ${item.model || ""}. Thiết bị có phản hồi đúng không?`,
        `HanJoo just sent the Test code for ${item.brand || ""} ${item.model || ""}. Did the device respond correctly?`
      ));
      if (responded) {
        this._identifyVerified ??= new Set();
        this._identifyVerified.add(candidateId);
        this.render();
        this.toast(this.tr("Đã xác nhận ứng viên bằng Test. Bạn có thể thêm thiết bị.", "Candidate verified by Test. You can now add the device."));
      } else {
        this.toast(this.tr("Ứng viên chưa được xác nhận. Hãy thử ứng viên khác.", "Candidate not verified. Try another candidate."), true);
      }
    } catch (err) { this._busyText = ""; this.render(); this.toast(this.errText(err), true); }
  }

  async addIdentifiedCandidate(candidateId) {
    const r = this._identifyResult;
    const recommended = !!(r?.recommended && (
      r.recommended_id === candidateId ||
      (r.equivalent_candidate_ids || []).includes(candidateId)
    ));
    const verified = !!this._identifyVerified?.has(candidateId);
    const candidateMeta = (r?.candidates || []).find(x => x?.candidate?.id === candidateId)?.candidate || {};
    if (candidateMeta.recognition_only) {
      this._discoverQuery = candidateMeta.brand || candidateMeta.model || "";
      this._addMode = "search"; this._discoverLoaded = false; this.render();
      return this.toast(this.tr("Core đã nhận diện protocol nhưng chưa có bộ điều khiển động tương ứng. Đã chuyển sang tìm theo hãng/model.", "Core identified the protocol, but no matching dynamic controller is available. Switched to brand/model search."));
    }
    if (!recommended && !verified) return this.toast(this.tr("Hãy Test và xác nhận thiết bị phản hồi đúng trước khi thêm.", "Test the candidate and confirm that the device responds correctly before adding it."), true);
    const item = this.identifiedCandidate(candidateId); if (!item) return;
    const emitter = this._discoverEmitter || this._hardware.emitters[0] || "";
    const receiver = this._discoverReceiver || null;
    if (!emitter) return this.toast("Hãy chọn IR Transmitter", true);
    const kindName = ({air_conditioner:"Điều hòa",tv:"TV",fan:"Quạt",projector:"Máy chiếu",speaker:"Loa"}[item.kind] || "Thiết bị IR");
    const name = [item.brand, item.model].filter(Boolean).join(" ") || kindName;
    try {
      this._busyText = `⏳ Đang thêm ${name}…`; this.render();
      let result;
      if (item.source === "protocol_engine") {
        result = await this.ws("device/create_from_protocol", { candidate_id: item.id, name, emitters: [emitter], receiver });
      } else {
        let profileId = item.profile_id;
        if (!profileId && item.catalog_id) {
          const installed = await this.ws("online/install", { catalog_id: item.catalog_id });
          profileId = installed.profile_id;
        }
        if (!profileId) throw new Error("Không lấy được profile để thêm thiết bị");
        result = await this.ws("device/create_from_profile", { profile_id: profileId, name, emitters: [emitter], receiver });
      }
      this._busyText = ""; await this.sleep(900); this._identifyCaptures=[]; this._identifyResult=null; this._identifyVerified = new Set(); await this.loadAll(); this._tab="devices"; this.render(); this.toast(`Đã thêm thiết bị ${result.device_id || name}`);
    } catch (err) { this._busyText = ""; this.render(); this.toast(this.errText(err), true); }
  }

  async createManualDevice(e) {
    e.preventDefault(); const f = new FormData(e.currentTarget);
    if (!f.get("emitter")) return this.toast("Hãy chọn IR Transmitter", true);
    try {
      this._busyText = "⏳ Đang tạo thiết bị học thủ công…"; this.render();
      const result = await this.ws("device/create_custom", { name: String(f.get("name") || ""), kind: String(f.get("kind") || "custom"), emitters: [String(f.get("emitter"))], receiver: String(f.get("receiver") || "") || null });
      this._busyText = "";
      await this.sleep(900);
      await this.loadAll();
      this._tab = "devices";
      this._detail = null;
      // Manual-learning devices are intentionally opened immediately: the next
      // task after creation is learning their buttons/states, not browsing the
      // device list and opening Manage again.
      await this.openDevice(result.device_id);
      this.toast(`Đã tạo ${result.device_id}. Bắt đầu học lệnh cho thiết bị này.`);
    } catch (err) { this._busyText = ""; this.render(); this.toast(this.errText(err), true); }
  }

  candidateById(candidateId) {
    return (this._discoverItems || []).find(item => item.id === candidateId);
  }

  async testCandidate(candidateId) {
    const item = this.candidateById(candidateId);
    if (!item) return this.toast("Không tìm thấy cấu hình", true);
    const emitter = this._discoverEmitter || this._hardware.emitters[0] || "";
    if (!emitter) return this.toast("Hãy chọn IR Transmitter", true);
    try {
      this._busyText = `⏳ Đang test ${item.brand || ""} ${item.model || item.name || ""}…`;
      this.render();
      let result;
      if (item.action === "protocol") {
        result = await this.ws("protocol/test", {
          candidate_id: item.id,
          emitter,
        });
      } else if (item.action === "online") {
        result = await this.ws("online/test", {
          catalog_id: item.id,
          emitter,
        });
      } else if (item.action === "saved") {
        result = await this.ws("profile/test", {
          profile_id: item.profile_id,
          emitter,
        });
      } else {
        throw new Error("Phương án này không có bước Test IR");
      }
      this._busyText = "";
      this.toast(`Đã phát thử: ${result.label || "IR"}. Nếu thiết bị phản hồi đúng, chọn “Dùng cấu hình này”.`);
    } catch (err) {
      this._busyText = "";
      this.toast(this.errText(err), true);
    }
  }

  async addCandidate(candidateId) {
    const item = this.candidateById(candidateId);
    if (!item) return this.toast("Không tìm thấy cấu hình", true);

    if (item.action === "native") {
      this.navigateInHomeAssistant(`/config/integrations/dashboard/add?domain=${encodeURIComponent(item.native_domain)}`);
      return;
    }
    if (item.action === "custom") {
      const kind = this._discoverKind || item.kind || "custom";
      this._detail = {
        mode: "custom-add",
        kind,
        name: this._discoverQuery || "",
      };
      this.render();
      return;
    }

    const emitter = this._discoverEmitter || this._hardware.emitters[0] || "";
    if (!emitter) return this.toast("Hãy chọn IR Transmitter", true);
    const receiver = this._discoverReceiver || null;
    const suggestedName = [item.brand, item.model].filter(Boolean).join(" ") || item.name || "IR device";

    try {
      this._busyText = `⏳ Đang thêm ${suggestedName}…`;
      this.render();
      let result;
      if (item.action === "protocol") {
        result = await this.ws("device/create_from_protocol", {
          candidate_id: item.id,
          name: suggestedName,
          emitters: [emitter],
          receiver,
        });
      } else {
        let profileId = item.profile_id;
        if (item.action === "online") {
          const installed = await this.ws("online/install", {
            catalog_id: item.id,
          });
          profileId = installed.profile_id;
        }
        if (!profileId) throw new Error("Không xác định được profile");
        result = await this.ws("device/create_from_profile", {
          profile_id: profileId,
          name: suggestedName,
          emitters: [emitter],
          receiver,
        });
      }
      this._busyText = "";
      await this.sleep(900);
      this._discoverLoaded = false;
      await this.loadAll();
      this._tab = "devices";
      this._detail = null;
      this.render();
      this.toast(`Đã thêm thiết bị ${result.device_id || suggestedName}`);
    } catch (err) {
      this._busyText = "";
      this.toast(this.errText(err), true);
    }
  }

  async testOnline(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const item = this._detail?.item;
    if (!item) return;
    try {
      this._busyText = `⏳ Đang tải và test ${item.brand} ${item.model}…`;
      this.render();
      const result = await this.ws("online/test", {
        catalog_id: item.id,
        emitter: String(f.get("emitter")),
      });
      this._busyText = "";
      this.toast(`Đã phát mã test: ${result.label}${result.warnings?.length ? ` · ${result.warnings.length} cảnh báo import` : ""}`);
    } catch (err) {
      this._busyText = "";
      this.toast(this.errText(err), true);
    }
  }

  async installOnline(catalogId) {
    try {
      this._busyText = "⏳ Đang tải và chuẩn hóa profile online…";
      this.render();
      const result = await this.ws("online/install", { catalog_id: catalogId });
      this._busyText = "";
      this._detail = null;
      await this.loadAll();
      this._tab = "add";
      this.toast(result.already_installed ? "Profile này đã có trong thư viện HanJoo" : "Đã lưu profile online vào thư viện HanJoo");
    } catch (err) {
      this._busyText = "";
      this.toast(this.errText(err), true);
    }
  }

  async createCustom(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    if (!f.get("emitter")) return this.toast("Hãy chọn IR Transmitter", true);
    try {
      this.toast("Đang tạo thiết bị…");
      const result = await this.ws("device/create_custom", {
        name: String(f.get("name") || ""),
        kind: String(f.get("kind") || "custom"),
        emitters: [String(f.get("emitter"))],
        receiver: String(f.get("receiver") || "") || null,
      });
      this._detail = null;
      await this.sleep(900);
      await this.loadAll();
      this._tab = "devices";
      this.toast(`Đã tạo ${result.device_id}`);
    } catch (err) { this.toast(this.errText(err), true); }
  }

  async createFromProfile(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      const profile = this._detail.profile;
      const result = await this.ws("device/create_from_profile", {
        profile_id: profile.id,
        name: String(f.get("name") || profile.name),
        emitters: [String(f.get("emitter"))],
        receiver: String(f.get("receiver") || "") || null,
      });
      this._detail = null;
      await this.sleep(900);
      await this.loadAll();
      this._tab = "devices";
      this.toast(`Đã thêm ${result.device_id}`);
    } catch (err) { this.toast(this.errText(err), true); }
  }

  async testProfile(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      const profile = this._detail.profile;
      const result = await this.ws("profile/test", {
        profile_id: profile.id,
        emitter: String(f.get("emitter")),
      });
      this.toast(`Đã phát mã test: ${result.label}`);
    } catch (err) { this.toast(this.errText(err), true); }
  }

  async updateRouting(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      await this.ws("device/update_routing", {
        device_id: this._detail.device.id,
        emitters: [String(f.get("emitter"))],
        receiver: String(f.get("receiver") || "") || null,
      });
      this.toast("Đã lưu routing");
      await this.openDevice(this._detail.device.id);
    } catch (err) { this.toast(this.errText(err), true); }
  }

  async addCommand(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      await this.ws("device/add_command", {
        device_id: this._detail.device.id,
        name: String(f.get("name") || ""),
      });
      this.toast("Đã thêm nút; giờ hãy bấm Học");
      await this.openDevice(this._detail.device.id);
    } catch (err) { this.toast(this.errText(err), true); }
  }

  async beginCapture(payload) {
    this._learnDialog = {
      ...payload,
      stage: "waiting",
      timeout: payload.timeout || 20,
      capture: null,
      error: "",
    };
    this.render();
    try {
      const capture = await this.ws("device/capture", {
        device_id: payload.deviceId,
        timeout: payload.timeout || 20,
      });
      if (!this._learnDialog) {
        if (capture?.token) {
          this.ws("device/discard_capture", { token: capture.token }).catch(() => {});
        }
        return;
      }
      this._learnDialog = { ...this._learnDialog, stage: "preview", capture };
      this.render();
    } catch (err) {
      if (!this._learnDialog) return;
      this._learnDialog = {
        ...this._learnDialog,
        stage: "error",
        error: this.errText(err),
      };
      this.render();
    }
  }

  async learnCommand(commandId) {
    if (!this._detail?.device) return;
    const command = this._detail.device.commands?.[commandId] || {};
    await this.beginCapture({
      target: "command",
      deviceId: this._detail.device.id,
      deviceName: this._detail.device.name,
      commandId,
      commandName: command.name || commandId,
      timeout: 20,
    });
  }

  async learnClimate(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const device = this._detail.device;
    const power = String(f.get("power") || "state");
    await this.beginCapture({
      target: "climate",
      deviceId: device.id,
      deviceName: device.name,
      timeout: 20,
      climate: {
        power,
        mode: String(f.get("mode") || "cool"),
        temp: power === "state" ? Number(f.get("temp")) : null,
        fan: power === "state" ? (String(f.get("fan") || "") || null) : null,
        swing: power === "state" ? (String(f.get("swing") || "") || null) : null,
      },
    });
  }

  async retryLearn() {
    if (!this._learnDialog) return;
    const oldToken = this._learnDialog.capture?.token;
    const payload = {
      target: this._learnDialog.target,
      deviceId: this._learnDialog.deviceId,
      deviceName: this._learnDialog.deviceName,
      commandId: this._learnDialog.commandId,
      commandName: this._learnDialog.commandName,
      climate: this._learnDialog.climate,
      timeout: this._learnDialog.timeout || 20,
    };
    if (oldToken) {
      try { await this.ws("device/discard_capture", { token: oldToken, device_id: payload.deviceId }); } catch (_) {}
    }
    await this.beginCapture(payload);
  }

  async cancelLearn() {
    const token = this._learnDialog?.capture?.token;
    const deviceId = this._learnDialog?.deviceId;
    this._learnDialog = null;
    this.render();
    if (token || deviceId) {
      try {
        await this.ws("device/discard_capture", {
          token: token || undefined,
          device_id: deviceId || undefined,
        });
      } catch (_) {}
    }
  }

  async saveLearn() {
    const d = this._learnDialog;
    if (!d?.capture?.token || d.capture.can_save === false) return;
    this._learnDialog = { ...d, stage: "saving" };
    this.render();
    try {
      const payload = {
        device_id: d.deviceId,
        token: d.capture.token,
        target: d.target,
      };
      if (d.target === "command") {
        payload.command_id = d.commandId;
      } else {
        Object.assign(payload, d.climate || {});
      }
      await this.ws("device/save_capture", payload);
      this._learnDialog = null;
      await this.openDevice(d.deviceId);
      this.toast("Đã lưu mã IR");
    } catch (err) {
      this._learnDialog = {
        ...d,
        stage: "error",
        error: this.errText(err),
      };
      this.render();
    }
  }

  async sendCommand(commandId) {
    try {
      await this.ws("device/send", { device_id: this._detail.device.id, command_id: commandId });
      this.toast("Đã phát IR");
    } catch (err) { this.toast(this.errText(err), true); }
  }

  async deleteCommand(commandId) {
    if (!confirm(this.tr("Xóa hẳn nút/chức năng này?", "Delete this button/function permanently?"))) return;
    const deviceId = this._detail.device.id;
    try {
      await this.ws("device/delete_command", { device_id: deviceId, command_id: commandId });
      await this.sleep(700);
      await this.openDevice(deviceId);
      this.toast("Đã xóa nút");
    } catch (err) { this.toast(this.errText(err), true); }
  }

  async deleteDevice() {
    if (!this._detail?.device?.id) return;
    await this.deleteDeviceById(this._detail.device.id, this._detail.device.name, true);
  }

  async deleteDeviceById(id, knownName = "", closeDetail = false) {
    const summary = (this._devices || []).find(d => String(d.id) === String(id));
    const name = knownName || summary?.name || id;
    if (!confirm(this.tr(
      `Xóa thiết bị "${name}" và toàn bộ mã đã học?`,
      `Delete device "${name}" and all learned codes?`
    ))) return;

    try {
      await this.ws("device/delete", { device_id: id });
      if (closeDetail || this._detail?.device?.id === id) this._detail = null;
      await this.sleep(500);
      await this.loadAll();
      this._tab = "devices";
      this.toast(this.tr("Đã xóa thiết bị", "Device deleted"));
    } catch (err) {
      this.toast(this.errText(err), true);
    }
  }

  async importFile(e) {
    const files = [...(e.target.files || [])];
    if (!files.length) return;
    let imported = 0;
    let warnings = 0;
    let failed = 0;
    try {
      for (let index = 0; index < files.length; index++) {
        const file = files[index];
        this._busyText = `⏳ Import ${index + 1}/${files.length}: ${file.name}`;
        this.render();
        try {
          if (file.size > 16_000_000) throw new Error("File lớn hơn giới hạn 16 MB");
          const text = await file.text();
          const result = await this.ws("profile/import", { filename: file.name, text });
          imported += result.count || 1;
          warnings += result.warnings?.length || 0;
        } catch (err) {
          failed++;
          console.warn("HanJoo IR import failed", file.name, err);
        }
      }
      this._busyText = "";
      await this.loadAll();
      const parts = [`${imported} profile`];
      if (warnings) parts.push(`${warnings} cảnh báo`);
      if (failed) parts.push(`${failed} file lỗi`);
      this.toast(`Import xong: ${parts.join(" · ")}`, failed > 0 && imported === 0);
    } finally {
      this._busyText = "";
      e.target.value = "";
    }
  }

  async deleteProfile(id) {
    if (!confirm(this.tr("Xóa profile khỏi thư viện? Các thiết bị đã tạo từ profile vẫn giữ bản sao mã của chúng.", "Delete this profile from the library? Devices created from it will keep their copied codes."))) return;
    try {
      await this.ws("profile/delete", { profile_id: id });
      await this.loadAll();
      this.toast("Đã xóa profile");
    } catch (err) { this.toast(this.errText(err), true); }
  }

  async exportLibrary() {
    try {
      const result = await this.ws("profile/export_library");
      this.downloadText(result.filename, result.text);
    } catch (err) { this.toast(this.errText(err), true); }
  }

  async exportProfile(id) {
    try {
      const result = await this.ws("profile/export", { profile_id: id });
      this.downloadText(result.filename, result.text);
    } catch (err) { this.toast(this.errText(err), true); }
  }

  async exportDevice() {
    try {
      const result = await this.ws("device/export", { device_id: this._detail.device.id });
      this.downloadText(result.filename, result.text);
    } catch (err) { this.toast(this.errText(err), true); }
  }

  downloadText(filename, text) {
    const blob = new Blob([text], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = String(filename || "hanjoo-ir.json").replace(/[\\/:*?"<>|]/g, "_");
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 500);
  }

  styles() {
    return `
      :host { display:block; color:var(--primary-text-color); background:var(--primary-background-color); min-height:100vh; }
      * { box-sizing:border-box; }
      .mobile-ha-toolbar {
        display:flex;
        align-items:center;
        min-height:56px;
        padding:0 8px;
        gap:4px;
        border-bottom:1px solid var(--divider-color);
        background:var(--app-header-background-color, var(--card-background-color));
        color:var(--app-header-text-color, var(--primary-text-color));
        position:sticky;
        top:0;
        z-index:20;
      }
      .mobile-ha-toolbar ha-menu-button {
        flex:0 0 auto;
      }
      .mobile-ha-title {
        font-size:20px;
        font-weight:500;
        padding-left:4px;
      }
      button,input,select { font:inherit; }
      button { border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); border-radius:10px; padding:9px 13px; cursor:pointer; }
      button:hover { filter:brightness(.97); }
      button.primary { background:var(--primary-color); color:var(--text-primary-color,white); border-color:var(--primary-color); font-weight:600; }
      button.danger { color:var(--error-color,#db4437); }
      button.subtle { padding:7px 9px; }
      input,select { width:100%; border:1px solid var(--divider-color); color:var(--primary-text-color); background:var(--card-background-color); border-radius:10px; padding:10px 12px; }
      label { display:flex; flex-direction:column; gap:6px; font-size:13px; font-weight:600; }
      .shell { max-width:1240px; margin:0 auto; padding:20px; }
      header { display:flex; justify-content:space-between; align-items:center; gap:20px; padding:10px 4px 18px; }
      .title { font-size:28px; font-weight:700; }
      .subtitle,.muted { color:var(--secondary-text-color); }
      .stats { display:flex; flex-wrap:wrap; gap:8px; }
      .stats span,.pill,.meta span { background:var(--secondary-background-color); border-radius:999px; padding:5px 9px; font-size:12px; }
      nav { display:flex; gap:6px; border-bottom:1px solid var(--divider-color); margin-bottom:22px; overflow:auto; }
      .tab { border:none; border-radius:8px 8px 0 0; background:transparent; padding:11px 16px; white-space:nowrap; }
      .tab.active { color:var(--primary-color); border-bottom:3px solid var(--primary-color); font-weight:700; }
      .toast { position:sticky; top:8px; z-index:20; margin:0 0 12px; padding:12px 15px; border:1px solid var(--divider-color); background:var(--card-background-color); border-radius:12px; box-shadow:var(--ha-card-box-shadow); }
      h2,h3,h4 { margin:0 0 7px; }
      p { line-height:1.55; }
      .section-head { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:18px; }
      .section-head h2 { font-size:23px; }
      .section-head p { margin:3px 0 0; color:var(--secondary-text-color); max-width:800px; }
      .section-head.mini { margin-bottom:10px; }
      .section-head.mini h3 { font-size:17px; }
      .group-title { margin:22px 0 10px; color:var(--secondary-text-color); font-size:15px; text-transform:uppercase; letter-spacing:.04em; }
      .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:14px; }
      .grid.compact { grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); }
      .card,.subsection,.drop { background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:14px; padding:16px; box-shadow:var(--ha-card-box-shadow); }
      .card-top { display:flex; align-items:flex-start; gap:10px; }
      .grow { flex:1; min-width:0; }
      .device-icon { font-size:27px; }
      .meta { display:flex; flex-wrap:wrap; gap:6px; margin:12px 0; color:var(--secondary-text-color); }
      .actions { display:flex; gap:7px; flex-wrap:wrap; margin-top:12px; }
      .subsection { margin:0 0 18px; }
      .subsection > p { margin-top:4px; }
      .best { color:var(--success-color,#43a047); font-size:11px; border:1px solid currentColor; border-radius:999px; padding:2px 7px; vertical-align:middle; }
      .fallback { color:var(--warning-color,#f9a825); font-size:11px; border:1px solid currentColor; border-radius:999px; padding:2px 7px; vertical-align:middle; }
      .toolbar { display:flex; gap:8px; margin:12px 0; }
      .toolbar input { max-width:480px; }
      .form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:12px; }
      .form-actions { display:flex; align-items:end; }
      .drop { text-align:center; border-style:dashed; margin-bottom:18px; }
      .drop input[type=file] { max-width:520px; margin:10px auto; }
      .big { font-size:42px; }
      .empty { text-align:center; padding:65px 20px; color:var(--secondary-text-color); }
      .empty.small { padding:25px 10px; }
      .entity-list { margin:8px 0 0; padding-left:20px; }
      .entity-list li { margin:8px 0; font-family:monospace; }
      .warn { color:var(--warning-color,#f9a825); }
      details { margin-top:12px; }
      details summary { cursor:pointer; }
      details ul { max-height:180px; overflow:auto; }
      .modal-backdrop { position:fixed; inset:0; z-index:100; background:rgba(0,0,0,.46); display:flex; align-items:flex-start; justify-content:center; padding:40px 14px; overflow:auto; }
      .modal { width:min(900px,100%); background:var(--card-background-color); border-radius:16px; box-shadow:0 18px 60px rgba(0,0,0,.35); border:1px solid var(--divider-color); overflow:hidden; }
      .small-modal { width:min(620px,100%); }
      .modal-head { display:flex; justify-content:space-between; align-items:start; padding:18px 20px; border-bottom:1px solid var(--divider-color); }
      .icon-btn { border:none; background:transparent; font-size:18px; }
      .modal-section { padding:18px 20px; border-bottom:1px solid var(--divider-color); }
      .modal-footer { padding:16px 20px; display:flex; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
      .command-list { display:flex; flex-direction:column; gap:7px; }
      .command-row { display:flex; align-items:center; gap:8px; padding:9px; border:1px solid var(--divider-color); border-radius:10px; }
      .mono { font-family:monospace; font-size:11px; }
      .ok { color:var(--success-color,#43a047); font-size:12px; }
      .missing { color:var(--secondary-text-color); font-size:12px; }
      .inline-form { display:flex; gap:8px; margin-top:12px; }
      .inline-form input { max-width:420px; }
      .climate-box { background:color-mix(in srgb,var(--primary-color) 5%,var(--card-background-color)); }
      .cell-list { display:flex; flex-wrap:wrap; gap:5px; margin-top:10px; max-height:180px; overflow:auto; }
      .cell-list span { font-size:11px; border:1px solid var(--divider-color); border-radius:7px; padding:5px 7px; }
      .callout { margin:16px 0 0; padding:12px; border-radius:10px; background:var(--secondary-background-color); }
      .error-callout { color:var(--error-color,#db4437); }
      .online-toolbar select { max-width:190px; }
      .online-summary { display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; }
      .online-status,.result-note { padding:10px 2px; }
      .quick-progress { height:5px; background:var(--divider-color); overflow:hidden; }
      .quick-progress span { display:block; height:100%; background:var(--primary-color); transition:width .2s ease; }
      .quick-body { padding:18px 20px 22px; }
      .candidate-card { margin:14px 0; padding:14px; border:1px solid var(--divider-color); border-radius:12px; background:var(--secondary-background-color); }
      .quick-actions { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px; margin-top:14px; }
      .success-btn { width:100%; margin-top:10px; background:var(--success-color,#43a047); color:white; border-color:var(--success-color,#43a047); font-weight:700; }
      .center-note { text-align:center; margin-top:10px; }
      .source-list { display:flex; flex-direction:column; gap:9px; }
      .source-row { display:flex; align-items:center; gap:14px; padding:13px; border:1px solid var(--divider-color); border-radius:10px; }
      .source-on { color:var(--success-color,#43a047); }
      .source-actions { display:flex; align-items:center; gap:7px; flex-wrap:wrap; justify-content:flex-end; }
      .source-error { color:var(--error-color,#db4437); font-size:12px; margin-top:7px; }
      .add-methods { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin:0 0 14px; }
      .add-method { min-height:104px; text-align:left; display:grid; grid-template-columns:auto 1fr; grid-template-rows:auto auto; column-gap:9px; align-content:center; padding:14px; border:1px solid var(--divider-color); border-radius:14px; background:var(--card-background-color); }
      .add-method ha-icon { grid-row:1 / span 2; align-self:center; }
      .add-method b { font-size:14px; }
      .add-method span { font-size:12px; color:var(--secondary-text-color); margin-top:4px; }
      .add-method.selected { border:2px solid var(--primary-color); padding:13px; }
      .identify-box { padding:17px; }
      .compact-head { margin-bottom:8px; }
      .safety-callout { border-left:4px solid var(--warning-color,#f59e0b); }
      .identify-steps { display:flex; flex-direction:column; gap:8px; margin-top:12px; }
      .identify-step { display:grid; grid-template-columns:36px minmax(0,1fr) auto; gap:10px; align-items:center; border:1px solid var(--divider-color); border-radius:12px; padding:10px; }
      .identify-step.done { border-color:var(--success-color,#43a047); }
      .identify-step-num { width:30px;height:30px;border-radius:50%;display:grid;place-items:center;background:var(--secondary-background-color);font-weight:700; }
      .identify-step-main { display:flex; flex-direction:column; gap:3px; min-width:0; }
      .identify-step-main span,.identify-step-main small { color:var(--secondary-text-color); }
      .identify-actions { margin-top:12px; justify-content:flex-end; }
      .identify-result { margin-top:14px; padding:14px; border-radius:12px; border:1px solid var(--divider-color); }
      .identify-result.strong { border-color:var(--success-color,#43a047); }
      .identify-result.caution { border-color:var(--warning-color,#f59e0b); }
      .identify-candidates { display:flex; flex-direction:column; gap:8px; margin-top:10px; }
      .discover-box { padding:17px; }
      .discover-inputs { display:grid; grid-template-columns:220px minmax(280px,1fr) auto; gap:10px; align-items:end; }
      .discover-query { min-width:0; }
      .discover-search-btn { min-height:42px; }
      .routing-mini { display:grid; grid-template-columns:auto minmax(230px,1fr) minmax(230px,1fr); gap:10px; align-items:end; margin-top:14px; padding-top:14px; border-top:1px solid var(--divider-color); }
      .routing-title { color:var(--secondary-text-color); font-size:12px; font-weight:700; align-self:center; }
      .source-strip { display:flex; gap:7px; align-items:center; flex-wrap:wrap; margin-top:14px; }
      .discover-results { display:flex; flex-direction:column; gap:9px; }
      .candidate-row { display:grid; grid-template-columns:42px minmax(0,1fr) auto; gap:12px; align-items:center; border:1px solid var(--divider-color); border-radius:12px; padding:12px; background:var(--card-background-color); }
      .candidate-row.recommended { border:2px solid var(--success-color,#43a047); background:color-mix(in srgb,var(--success-color,#43a047) 5%,var(--card-background-color)); }
      .candidate-rank { display:flex; align-items:center; justify-content:center; width:34px; height:34px; border-radius:50%; background:var(--secondary-background-color); font-weight:700; }
      .candidate-row.recommended .candidate-rank { color:var(--success-color,#43a047); font-size:18px; }
      .candidate-main h4 { margin:0 0 4px; }
      .candidate-actions { display:flex; gap:7px; flex-wrap:wrap; justify-content:flex-end; }
      .priority-flow { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:12px 0 16px; padding:10px 12px; border-radius:10px; background:var(--secondary-background-color); }
      .priority-flow span { font-weight:600; }
      .priority-flow small { font-weight:400; color:var(--secondary-text-color); }
      .advanced-add { margin:16px 0; padding:12px 14px; border:1px solid var(--divider-color); border-radius:12px; }
      .advanced-body { padding-top:10px; }
      .about-page { padding:20px; }
      .about-brand { display:flex; align-items:center; gap:14px; margin-bottom:18px; }
      .about-brand h3 { margin:0 0 4px; font-size:22px; }
      .about-logo { width:48px; height:48px; border-radius:14px; display:flex; align-items:center; justify-content:center; font-size:25px; font-weight:800; background:var(--primary-color); color:var(--text-primary-color,#fff); }
      .about-card { margin-top:18px; }
      .about-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; }
      .about-grid > div { display:flex; flex-direction:column; gap:5px; padding:12px; border:1px solid var(--divider-color); border-radius:10px; background:var(--secondary-background-color); }
      .about-grid span { color:var(--secondary-text-color); font-size:12px; }
      .about-grid a { color:var(--primary-color); text-decoration:none; word-break:break-all; }
      .about-note { margin:12px 0 0; }
      .hidden-section { display:none !important; }
      .add-methods { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:0 0 18px; }
      .method-card { min-height:76px; text-align:left; display:flex; flex-direction:column; gap:5px; padding:13px 14px; }
      .method-card span { color:var(--secondary-text-color); font-size:12px; line-height:1.35; }
      .method-card.active { border:2px solid var(--primary-color); background:color-mix(in srgb,var(--primary-color) 9%,var(--card-background-color)); }
      .learn-backdrop { position:fixed; inset:0; z-index:220; background:rgba(0,0,0,.62); display:flex; align-items:center; justify-content:center; padding:16px; }
      .learn-dialog { width:min(620px,100%); background:var(--card-background-color); border:1px solid var(--divider-color); border-radius:18px; box-shadow:0 24px 80px rgba(0,0,0,.45); overflow:hidden; }
      .learn-head { display:flex; justify-content:space-between; align-items:flex-start; padding:18px 20px; border-bottom:1px solid var(--divider-color); }
      .learn-body { padding:24px; }
      .learn-body.centered { text-align:center; padding:34px 24px; }
      .signal-animation { display:flex; justify-content:center; align-items:end; gap:7px; height:54px; margin-bottom:16px; }
      .signal-animation span { display:block; width:8px; border-radius:8px; background:var(--primary-color); animation:irpulse 1s infinite ease-in-out; }
      .signal-animation span:nth-child(1){height:18px;animation-delay:0s}.signal-animation span:nth-child(2){height:38px;animation-delay:.14s}.signal-animation span:nth-child(3){height:54px;animation-delay:.28s}
      @keyframes irpulse { 0%,100%{transform:scaleY(.35);opacity:.45} 50%{transform:scaleY(1);opacity:1} }
      .countdown-note { color:var(--secondary-text-color); margin:13px 0 18px; font-size:13px; }
      .capture-ok { color:var(--success-color,#43a047); font-weight:700; font-size:17px; margin-bottom:14px; }
      .capture-warn { color:var(--warning-color,#f9a825); font-weight:700; font-size:17px; margin-bottom:14px; }
      .capture-bad { color:var(--error-color,#db4437); font-weight:700; font-size:17px; margin-bottom:14px; }
      button:disabled { opacity:.45; cursor:not-allowed; filter:none; }
      .capture-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:9px; margin-bottom:16px; }
      .capture-grid div { padding:12px; border:1px solid var(--divider-color); border-radius:11px; }
      .capture-grid span { display:block; color:var(--secondary-text-color); font-size:11px; margin-bottom:4px; }
      .capture-grid b { font-size:15px; }
      .preview-label { margin-bottom:6px; }
      .timing-preview { max-height:120px; overflow:auto; padding:12px; border-radius:10px; background:var(--secondary-background-color); line-height:1.6; word-break:break-word; }
      .preview-note { margin:13px 0; }
      .learn-actions { display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap; margin-top:18px; }
      .learn-error { color:var(--error-color,#db4437); margin-bottom:18px; }
      @media(max-width:700px) {
        .shell { padding:12px; }
        header { align-items:flex-start; flex-direction:column; }
        .stats { display:none; }
        .form-grid { grid-template-columns:1fr; }
        .section-head { flex-direction:column; }
        .grid,.grid.compact { grid-template-columns:1fr; }
        .add-methods { grid-template-columns:1fr 1fr; }
        .capture-grid { grid-template-columns:1fr; }
        .modal-backdrop { padding:10px; }
        .command-row { flex-wrap:wrap; }
        .command-row .grow { flex-basis:100%; }
        .toolbar,.inline-form { flex-direction:column; }
        .source-row { align-items:flex-start; flex-direction:column; }
        .source-actions { width:100%; justify-content:flex-start; }
        .add-methods { grid-template-columns:1fr; }
        .identify-step { grid-template-columns:32px 1fr; }
        .identify-step > button { grid-column:2; justify-self:start; }
        .discover-inputs,.routing-mini,.about-grid { grid-template-columns:1fr; }
        .candidate-row { grid-template-columns:34px minmax(0,1fr); align-items:start; }
        .candidate-actions { grid-column:1 / -1; justify-content:flex-start; padding-left:46px; }
        .quick-actions { grid-template-columns:1fr; }
      }
    `;
  }
}

if (!customElements.get("hanjoo-ir-panel")) {
  customElements.define("hanjoo-ir-panel", HanjooIrPanel);
}
