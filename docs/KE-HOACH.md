# Kế hoạch: ứng dụng quản lý chế độ âm thanh kiểu Dolby Access

## Mục tiêu
1. Có danh sách chế độ (Dynamic, Movie, Music, Game, Voice, kèm Intelligent EQ) dựng lại từ số đo Dolby thật, bật/tắt bằng một cú bấm.
2. Phát hiện và chặn việc nhiều app xử lý chồng lên nhau trên cùng tai nghe (Spatial sound/Dolby, Equalizer APO/HeSuVi, Enhancements của Windows, Realtek/Nahimic, Peace, FxSound...).

## Hiện trạng đã kiểm tra
| Mục | Tình trạng |
|---|---|
| `hesuvi-control\hesuvi.ps1`, `livecheck.py`, `golden\` | Dùng lại được nguyên vẹn |
| `dolby-probe\probe.py` (measure / reanalyse / compare / export-hrir) | Dùng lại được, cần thêm chế độ đo hàng loạt |
| Music + Warm | Đã dựng và kiểm chứng (thread "HeSuVi Dolby music handoff" đang tinh chỉnh, mình không đụng vào) |
| Task "HeSuVi Logon Check" | **Đang hỏng**: vẫn trỏ tới `E:\Resilio Sync\SETUP\hesuvi-control\hesuvi.ps1`, nhưng thư mục đã chuyển vào `Dolby Access Custom`. Lần chạy OK cuối: 09:51 hôm nay |
| Python 3.12 + numpy, scipy, SoundCard, dawdreamer | Có sẵn |
| .NET SDK | Chỉ có 3.1 (cũ) |
| Thiết bị phát | UGREEN Stereo (A2DP), UGREEN Hands-Free, Realtek Speakers, Realtek Digital |

## Kiến trúc đề xuất

```
Dolby Access Custom\
  soundmode\                 (Python package, lõi)
    modes.py                 thư viện chế độ: modes\<ten>\mode.json + mode.txt (file include của EAPO)
    engine.py                bật chế độ = đổi 1 dòng Include trong HeSuVi, giữ golden + backup có ngày giờ
    detect.py                quét các lớp xử lý âm thanh theo từng thiết bị -> danh sách xung đột
    guard.py                 chạy nền: theo dõi thay đổi, áp luật chống chồng, báo popup
    probe\                   bọc dolby-probe: đo từng chế độ Dolby, fit EQ tĩnh + leveler (viết lại fitnova)
  app.pyw                    giao diện cửa sổ + icon khay hệ thống (tiếng Việt)
  modes\music-warm\          chế độ đầu tiên, chép từ golden hiện tại (chỉ đọc)
  backups\                   mỗi lần ghi file EAPO đều lưu bản cũ ở đây
```

**Bật một chế độ** chỉ thay nội dung file include (giống cách `music-warm.txt` đang được `postlude.txt` gọi), nên có hiệu lực ngay, không cần khởi động lại.

**Phát hiện chồng chéo** (theo từng thiết bị phát):
| Lớp | Cách phát hiện |
|---|---|
| Windows Spatial sound (Dolby Atmos / DTS / Windows Sonic) | Registry thuộc tính endpoint + tiến trình DolbyAccess |
| Equalizer APO / HeSuVi | Khoá FX của endpoint + `deact.txt` + nội dung `config.txt` |
| Windows Enhancements (Loudness Equalization, Bass Boost...) | Thuộc tính "Disable all enhancements" và khoá FX |
| APO của hãng (Realtek, Nahimic, Dolby DAX trên driver) | Khoá FxProperties của endpoint |
| App xử lý trong user (Peace, FxSound, Boom3D, Sonar, Voicemeeter) | Tiến trình đang chạy + thiết bị ảo |
| Kiểm tra thực tế | `livecheck.py`: phát noise nhỏ, đo độ nghiêng phổ, phân biệt 0 / 1 / 2 lớp |

**Ngăn chồng chéo**: mặc định chỉ một lớp "định hình âm" được hoạt động trên một thiết bị. Khi phát hiện Spatial sound bật trong lúc chế độ của mình đang chạy, app tự tắt lớp EAPO của mình (đảo ngược được) và báo popup kèm nút mở thẳng trang Spatial sound. Không tự sửa cài đặt hệ thống của app khác nếu chưa hỏi.

**Đo các chế độ Dolby**: Dolby Access không có API đổi chế độ, nên dùng trình hướng dẫn bán tự động: app nhắc "chọn Movie trong Dolby Access rồi bấm Tiếp", đo ~80 giây (tự tắt HeSuVi khi đo, như `--bypass-hesuvi`), rồi fit ra GraphicEQ + tham số leveler. Giới hạn đã biết: với nhạc stereo Dolby không tạo HRTF (đo được −79 dB crossfeed), nên bản dựng stereo rất sát; với game/phim 5.1/7.1 cần đo thêm đa kênh để lấy HRIR, để ở giai đoạn sau.

## Các giai đoạn
| GĐ | Nội dung | Có đụng hệ thống? |
|---|---|---|
| 0 | Sửa task "HeSuVi Logon Check" trỏ đúng đường dẫn mới | Có, cần bạn đồng ý |
| 1 | Lõi + `detect`: lệnh `soundmode status` liệt kê mọi lớp xử lý và xung đột | Không, chỉ đọc |
| 2 | Thư viện chế độ + `engine`: đóng gói Music+Warm thành chế độ đầu tiên, cơ chế đổi chế độ có backup | Ghi vào config EAPO, sẽ hỏi trước lần đầu |
| 3 | Trình đo: đo lần lượt các chế độ Dolby, fit EQ + leveler, sinh `mode.txt` | Bạn bật Dolby khi đo |
| 4 | Giao diện cửa sổ + khay hệ thống + `guard` chạy nền | Không |
| 5 | Thay task đăng nhập cũ bằng task của app (khởi động guard) | Có, cần bạn đồng ý |

## Câu cần bạn chọn
1. Sửa task đăng nhập đang hỏng ngay bây giờ? **Có (khuyên dùng)** / Để GĐ5 làm luôn
2. Công nghệ giao diện: **Python + tkinter, không tải gì (khuyên dùng)** / PySide6 đẹp hơn, tải ~70 MB / .NET 8 WPF, tải SDK ~200 MB
3. Đo những chế độ nào trước: **5 preset (Dynamic, Movie, Music, Game, Voice) với IEQ mặc định + Music × 3 IEQ (khuyên dùng)** / Tất cả 5 × 3 IEQ (15 lần đo, ~25 phút)
4. Khi phát hiện chồng: **Tự tắt lớp của app mình + báo (khuyên dùng)** / Chỉ cảnh báo
