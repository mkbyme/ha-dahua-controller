# ha-dahua-controller

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mkbyme&repository=ha-dahua-controller&category=integration)

HACS Điều khiển PTZ, Speaker, thiết lập dahua camera

Custom integration cho Home Assistant, dùng để điều khiển camera IP PTZ của Dahua
(di chuyển, preset, phát âm thanh/TTS qua loa, đèn spotlight, và Active Deterrence)
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
- Entity `switch` cho tính năng Active Deterrence của camera (tự động bật đèn+loa+
  voice khi phát hiện chuyển động/người).
- Entity `light` cho đèn spotlight của camera (độ sáng 0-100%).
- Entity `media_player` cho loa camera, dùng được như một target bình thường của
  `tts.speak` hoặc `media_player.play_media` — không cần truyền đường dẫn file cố
  định. Hỗ trợ cả audio nguồn WAV và mp3 (qua ffmpeg).

## Danh sách entity

| Platform | Entity | Hành động | CGI bên dưới |
|---|---|---|---|
| select | Preset | Di chuyển tới preset đã chọn | `ptz.cgi?action=start&code=GotoPreset` |
| button | PTZ Up/Down/Left/Right | Di chuyển từng bước (start → sleep → stop) | `ptz.cgi?action=start\|stop` |
| button | PTZ Stop | Dừng di chuyển ở mọi hướng | `ptz.cgi?action=stop` (tất cả code) |
| button | Play Alert Tone | Phát 1 tiếng bíp qua loa | `audio.cgi?action=postAudioStream` |
| button | Sync Presets | Đồng bộ lại danh sách preset từ camera | `ptz.cgi?action=getPresets` |
| switch | Active Deterrence | Bật/tắt tự động đèn+loa+voice khi phát hiện | `configManager.cgi` (`LightGlobal[0].Enable`) |
| light | Spotlight | Bật/tắt đèn spotlight, chỉnh độ sáng | `configManager.cgi` (`Lighting[1][0]`) |
| media_player | Speaker | Phát audio WAV/mp3 hoặc TTS qua loa | `audio.cgi?action=postAudioStream` |

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
bấm nút di chuyển, và chu kỳ cập nhật trạng thái đèn/Active Deterrence.

## Ghi chú / lưu ý

Các ghi chú dưới đây được đúc kết từ việc test trực tiếp trên thiết bị thật
(`DH-P5D-5F-PV`, IP `192.168.100.110`, có PTZ + Active Deterrence + audio 2 chiều):

- **Cần ffmpeg để phát mp3/TTS.** Phát WAV (`media_player.play_media` với nguồn WAV)
  không cần ffmpeg, nhưng đa số engine TTS mặc định xuất ra mp3, và luồng đó được
  decode qua ffmpeg. Home Assistant OS/Container có sẵn ffmpeg; một số bản cài
  Core/venv hoặc Supervised có thể chưa có ffmpeg trong PATH — nếu phát TTS báo lỗi
  "ffmpeg binary not found", cần cài ffmpeg trên máy chủ.
- Các lệnh `setConfig` (đèn/Active Deterrence) luôn trả về HTTP 400 trên camera này,
  kể cả khi ghi thành công — integration sẽ đọc lại giá trị để xác nhận và log ở mức
  debug; đây là hành vi bình thường, không phải lỗi.
- Camera đóng kết nối mà không trả về HTTP response ngay sau khi nhận đủ audio POST
  thành công — cũng là hành vi bình thường của Dahua với `audio.cgi`, không phải lỗi.
- Chỉ số bảng cấu hình của đèn spotlight (`Lighting[1][0]`) là **giả định chưa được
  xác minh bằng mắt** — mới chỉ xác nhận qua đọc lại config, chưa xác nhận đèn thật
  có sáng lên không. Nếu entity Spotlight không làm đèn sáng lên, sửa `LIGHT_TABLE`
  trong `custom_components/dahua_controller/const.py` thành `"Lighting[0][0]"` rồi
  reload lại integration.
- Integration này giao tiếp với camera qua HTTP CGI ở port 80, không dùng giao thức
  nhị phân của Dahua ở port 37777.

## Camera tương thích

Được xây dựng và test trên Dahua `DH-P5D-5F-PV`. Về lý thuyết sẽ hoạt động với các
camera PTZ Dahua khác có cùng bộ CGI `ptz.cgi` / `configManager.cgi` / `audio.cgi`,
nhưng bộ code PTZ và chỉ số bảng đèn có thể khác nhau tuỳ model/firmware.

## License

MIT
