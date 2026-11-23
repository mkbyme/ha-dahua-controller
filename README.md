# ha-dahua-controller

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mkbyme&repository=ha-dahua-controller&category=integration)

HACS Điều khiển PTZ, Speaker, thiết lập dahua camera

Custom integration cho Home Assistant, dùng để điều khiển camera IP PTZ của Dahua
(di chuyển, preset, hiệu chỉnh PTZ, phát âm thanh/TTS qua loa)
qua HTTP CGI + Digest Auth. Thông tin kết nối camera (host/port/user/password/channel)
được cấu hình qua giao diện HA và có thể sửa lại sau — không có gì bị hardcode trong
integration.

## Tính năng

- Thiết lập qua config flow: thêm camera với host/port/username/password/channel,
  có thể sửa lại sau qua **Reconfigure** mà không cần xoá rồi thêm lại.
- Preset PTZ dưới dạng entity `select` — chọn 1 option sẽ di chuyển camera tới đó.
- Di chuyển PTZ dưới dạng entity `button`: Up / Down / Left / Right / Stop.
- Nút "Play Alert Tone" (phát 1 tiếng bíp qua loa camera) và nút "Sync Presets"
  (đồng bộ lại danh sách preset theo yêu cầu).
- Nút "PTZ Calibrate" — chạy PTZ self-check (tương đương "PTZ Restart" trên web UI
  của camera) để camera tự tìm lại gốc cơ học, xử lý trường hợp chạy lâu ngày các
  preset bị lệch dù không ai xoay camera bằng tay, hoặc sau khi rớt mạng / mất điện
  đột ngột làm camera "nhớ sai" vị trí. Camera sẽ quay hết hành trình pan/tilt khoảng
  1 phút; các preset đã lưu được giữ nguyên.
- Action `dahua_controller.create_preset` — lưu vị trí hiện tại của camera thành
  preset (chọn ô lưu 1-255 + đặt tên), danh sách Preset tự đồng bộ lại.
- Action `dahua_controller.get_presets` — trả về danh sách ô preset + tên và các ô
  còn trống, để tránh ghi đè nhầm. Entity Preset cũng hiển thị sẵn trong thuộc tính
  `presets` / `free_slots`.
- Entity `media_player` cho loa camera, dùng được như một target bình thường của
  `tts.speak` hoặc `media_player.play_media` — không cần truyền đường dẫn file cố
  định. Hỗ trợ cả audio nguồn WAV và mp3 (qua ffmpeg).
- Tuỳ chọn **Max audio gain** (100-150%, trong Options) để chỉnh độ to của âm thanh phát
  ra loa; trên 100% sẽ khuếch đại thêm và có thể bị rè/clip.

## Danh sách entity

| Platform | Entity | Hành động | Giao thức bên dưới |
|---|---|---|---|
| select | Preset | Di chuyển tới preset đã chọn; thuộc tính `presets` (ô → tên), `free_slots` | `ptz.cgi?action=start&code=GotoPreset` |
| button | PTZ Up/Down/Left/Right | Di chuyển từng bước (start → sleep → stop) | `ptz.cgi?action=start\|stop` |
| button | PTZ Stop | Dừng di chuyển ở mọi hướng | `ptz.cgi?action=stop` (tất cả code) |
| button | Play Alert Tone | Phát 1 tiếng bíp qua loa | NetSDK talk protocol (TCP 37777) |
| button | Sync Presets | Đồng bộ lại danh sách preset từ camera | `ptz.cgi?action=getPresets` |
| button | PTZ Calibrate | PTZ self-check, tìm lại gốc để preset hết lệch | RPC2 `ptz.restartPtz` qua HTTP (port 80) → DHIP TCP 37777 → `ptz.cgi code=Restart` |
| media_player | Speaker | Phát audio WAV/mp3 hoặc TTS qua loa | NetSDK talk protocol (TCP 37777) |

## Action: xem và tạo preset

Xem các ô đã dùng / còn trống (đọc trực tiếp từ camera):

```yaml
action: dahua_controller.get_presets
data:
  device_id: <chọn camera trong UI>
response_variable: ds
# ds = {"presets": [{"preset_number": 1, "name": "cửa cuốn"}, ...],
#       "free_slots": [6, 7, 8, 9, 10, 15, ...]}   # 10 ô trống nhỏ nhất
```

Trong Developer Tools → Actions bấm **Perform action** sẽ thấy kết quả ngay. Hoặc
xem thuộc tính `presets` / `free_slots` của entity `select.<camera>_preset`. (HA
không cho đổ danh sách động theo từng camera vào ô chọn của action, nên số ô vẫn
nhập tay trong `create_preset`.)

Đưa camera tới vị trí mong muốn (nút PTZ Up/Down/Left/Right), rồi gọi:

```yaml
action: dahua_controller.create_preset
data:
  device_id: <chọn camera trong UI>
  name: "Cổng chính"
  preset_number: 5   # tuỳ chọn; bỏ trống = dùng lại ô có cùng tên, hoặc ô trống nhỏ nhất
response_variable: preset   # tuỳ chọn: {"preset_number": 5, "name": "Cổng chính", "presets": [...], "free_slots": [...]}
```

Ô đã có preset sẽ bị ghi đè. Không cho phép 2 ô trùng tên (Preset select chọn theo
tên). Vị trí được lưu bằng `ptz.cgi code=SetPreset`, tên được đặt bằng
`ptz.cgi?action=setPreset&arg1=<ô>&arg2=<tên>` (đã kiểm chứng trên `DH-P5D-5F-PV`;
lệnh `code=SetPresetName` trong tài liệu bị camera trả 400), rồi xác nhận bằng cách
đọc lại danh sách preset. Camera giới hạn số ô preset (ô 200 bị từ chối trên
`DH-P5D-5F-PV`) — nên dùng số ô nhỏ.
Có thể gắn action này vào một script và đặt nút trên dashboard.

## Cài đặt

### Qua HACS

Bấm vào badge bên dưới để thêm repo này vào HACS:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mkbyme&repository=ha-dahua-controller&category=integration)

Hoặc làm thủ công:

1. HACS → Integrations → ⋮ → Custom repositories → thêm
   `https://github.com/mkbyme/ha-dahua-controller` với loại **Integration**.
2. Cài đặt "Dahua Controller", khởi động lại Home Assistant.

### Thủ công (copy file)

Copy thư mục `custom_components/dahua_controller/` vào thư mục
`config/custom_components/` của Home Assistant, sau đó khởi động lại HA.

## Thiết lập

Settings → Devices & Services → Add Integration → tìm "Dahua Controller" → nhập
host, port (mặc định 80), username, password, channel (mặc định 1), và tên hiển thị
của camera.

### Sửa lại thông tin camera sau khi đã cấu hình

Mở entry của integration → **Reconfigure** để đổi host/port/username/password/channel
mà không cần xoá rồi thêm lại camera.

### Options

Mục **Configure** của entry cho phép chỉnh tốc độ/thời lượng/số bước PTZ mỗi lần
bấm nút di chuyển, và độ khuếch đại âm thanh tối đa.

## Ghi chú / lưu ý

Các ghi chú dưới đây được đúc kết từ việc test trực tiếp trên thiết bị thật
(`DH-P5D-5F-PV`, IP `192.168.100.110`, có PTZ + Active Deterrence + audio 2 chiều):

- **Cần ffmpeg để phát mp3/TTS.** Phát WAV (`media_player.play_media` với nguồn WAV)
  không cần ffmpeg, nhưng đa số engine TTS mặc định xuất ra mp3, và luồng đó được
  decode qua ffmpeg. Home Assistant OS/Container có sẵn ffmpeg; một số bản cài
  Core/venv hoặc Supervised có thể chưa có ffmpeg trong PATH — nếu phát TTS báo lỗi
  "ffmpeg binary not found", cần cài ffmpeg trên máy chủ.
- **PTZ Calibrate dùng RPC `ptz.restartPtz`, KHÔNG dùng `code=Reset` hay `PositionReset`.**
  Bảng code của `ptz.cgi` (Dahua HTTP API for IPC v1.40 §7.2.3) **không có** lệnh
  self-check/"PTZ Restart"; `Reset` là khôi phục cấu hình PTZ mặc định (mất preset),
  còn `PositionReset` lấy hướng hiện tại (đang bị lệch) làm gốc mới — cả hai đều làm
  lệch tệ hơn. Nút "PTZ Restart" trên web UI gọi JSON-RPC `ptz.restartPtz` trên object
  `ptz.factory.instance`; integration thử lần lượt: RPC2 qua HTTP (`/RPC2`, port cấu
  hình) → cùng RPC đó đóng gói DHIP qua TCP 37777 → `ptz.cgi code=Restart` (không có
  trong tài liệu, chỉ tính là thành công nếu camera trả `OK`). ONVIF không có thao tác
  tương đương. Phương thức đã thành công/lỗi của lần bấm gần nhất nằm trong thuộc
  tính `last_method`/`last_errors` của entity nút và trong log HA.
  Đã kiểm chứng trên `DH-P5D-5F-PV`: RPC2 qua HTTP port 80 chạy được (camera xoay
  hiệu chỉnh như trên app DMSS), nhưng camera **không trả lời** lệnh `ptz.restartPtz`
  trong lúc board PTZ khởi động lại. Vì vậy timeout ở đúng bước gửi lệnh (sau khi
  đăng nhập + lấy PTZ object đã thành công) được tính là "đã gửi"
  (`last_method: http_no_reply`) và không gửi lại qua cách khác, tránh hiệu chỉnh 2
  lần. Trên model này, DHIP JSON ở cổng 37777 không trả lời (`global.login` timeout).
- **Loa (Speaker/Play Alert Tone) đi qua giao thức nhị phân NetSDK của Dahua ở port
  37777, không phải `audio.cgi`.** `audio.cgi?action=postAudioStream` từng được dùng
  nhưng camera nhận request, đóng kết nối sạch sẽ, mà thực tế không hề phát ra loa
  (kiểm chứng bằng tai trên thiết bị thật) — trong khi app DMSS chính chủ vẫn phát
  được bình thường qua NetSDK, nên integration đã chuyển hẳn sang giao thức đó.

## Camera tương thích

Được xây dựng và test trên Dahua `DH-P5D-5F-PV`. Về lý thuyết sẽ hoạt động với các
camera PTZ Dahua khác có cùng bộ CGI `ptz.cgi` / `configManager.cgi` / `audio.cgi`,
nhưng bộ code PTZ và chỉ số bảng đèn có thể khác nhau tuỳ model/firmware.

## License

MIT
