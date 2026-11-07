# dolby-probe — đo hộp đen Dolby Atmos for Headphones → HeSuVi

Phát tín hiệu thử (~80 s) ra tai nghe mặc định, thu lại qua WASAPI loopback (thu **sau** Equalizer APO),
rồi tính:

| Phép thử | Cho ra | Dùng để |
|---|---|---|
| Sweep L-only / R-only (−20 dBFS) | Ma trận 2×2 đáp ứng xung loa ảo trước → tai | Xuất HRIR cho HeSuVi (`export-hrir`) |
| Sweep giữa ở −36/−28/−20/−12 dBFS | Đáp tuyến theo mức âm lượng | Phát hiện EQ phụ thuộc mức (loudness-EQ) |
| Noise pink / nặng bass / sáng, 8 s mỗi loại | Đáp tuyến ổn định theo nội dung + quỹ đạo thích nghi | Phát hiện **Intelligent EQ động** |
| Bước mức −40 → −14 → −40 dBFS | Gain theo thời gian | Volume leveler: attack/release τ, ratio |

Một hệ tuyến tính (như HeSuVi hiện tại) cho: bảng "content-adaptive" toàn 0, ratio 1.0, không có τ.
Bất kỳ số khác 0 nào ở đó chính là "chỉ số động" của Dolby.

## Quy trình đo Dolby Music Warm

Cần Dolby Atmos for Headphones đang chạy (mua trong Dolby Access, hoặc dùng bản dùng thử nếu được cung cấp).

1. Bluetooth UGREEN là thiết bị mặc định. Windows → Sound → Headphones → Properties → **Spatial sound: Dolby Atmos for Headphones**.
2. Dolby Access → Settings: chọn **Music**, Intelligent EQ **Warm**. Đóng các app phát âm thanh khác, không chỉnh volume khi đang đo.
3. Đo (tool tự tắt HeSuVi trong lúc đo rồi bật lại):
   ```
   python -I probe.py measure dolby_music_warm --bypass-hesuvi
   ```
   Kiểm tra dòng `crossfeed @1k`: khoảng −5…−15 dB nghĩa là đã đo được virtualizer. Nếu rất thấp (−40 dB trở xuống) thì Dolby chưa được bật.
4. (Nên đo thêm) cùng lệnh với `dolby_music_balanced`, `dolby_music_detailed` và một profile tắt Intelligent EQ, để tách phần HRTF khỏi phần EQ.
5. **Tắt Spatial sound** sau khi đo, nếu không sẽ xử lý hai lần cùng HeSuVi.

## Đưa kết quả vào HeSuVi

- **Bản sao chép (tĩnh) sát nhất cho nhạc stereo:**
  ```
  python -I probe.py export-hrir dolby_music_warm
  ```
  Chép `runs/dolby_music_warm_48.wav` → `HeSuVi\hrir\dolby_music_warm.wav` và `_44.wav` → `HeSuVi\hrir\44\dolby_music_warm.wav`,
  sửa `conv.txt`/`conv44.txt` trỏ tới file đó, và **tắt** `music-warm.txt` (EQ Warm đã nằm sẵn trong HRIR).
- **Hoặc chỉ lấy phần EQ** trên nền `atmos.wav` hiện tại:
  ```
  python -I probe.py compare dolby_music_warm atmos_hrir
  ```
  → dòng `GraphicEQ:` để thay các `Filter:` trong `music-warm.txt`.
- Nếu báo cáo cho thấy có EQ động hoặc leveler, phần đó không thể làm bằng EQ tĩnh. Khi đó dùng
  plugin VST dynamic EQ/compressor trong Equalizer APO, chỉnh theo τ, ratio và độ lệch đo được.

## Lệnh khác
- `python -I probe.py reanalyse LABEL`: phân tích lại từ `runs/LABEL_rec.wav` mà không phát lại.
- Đã kiểm chứng trên chain HeSuVi hiện tại (`runs/hesuvi_live*`): EQ tìm lại khớp EQ đã cài,
  HRIR xuất ra khớp chain gốc với sai số RMS 0,5 dB.
