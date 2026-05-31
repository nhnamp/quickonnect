# Prompt Tạo Ảnh Sơ Đồ PCM Audio

Tạo một sơ đồ kỹ thuật rõ ràng, dễ hiểu, bằng tiếng Việt, mô tả luồng xử lý audio PCM trong ứng dụng QuicKonNect.

## Nội Dung Sơ Đồ

Vẽ luồng từ trái sang phải với các khối chính sau:

```text
Giọng nói người dùng
-> Microphone
-> PyAudio thu âm
-> PCM samples
-> Chia frame 20 ms
-> AUDIO_CHUNK packet
-> TCP socket mã hóa
-> Server audio mixer
-> MIXED_AUDIO packet
-> Client nhận audio
-> PyAudio phát loa
-> Người nghe
```

## Nhãn Cần Có Trong Sơ Đồ

Thêm các nhãn kỹ thuật nhỏ gần phần `PCM samples`:

```text
16 kHz
16-bit
Mono
20 ms/frame
640 bytes/frame
```

Thêm ghi chú gần `TCP socket mã hóa`:

```text
Truyền qua TCP
Packet được mã hóa AES-GCM
```

Thêm ghi chú gần `Server audio mixer`:

```text
Trộn audio của người khác
Không gửi lại tiếng của chính người nghe
Giúp tránh echo từ server
```

## Bố Cục Gợi Ý

Chia ảnh thành 3 vùng lớn:

```text
[Client gửi]       [Server]             [Client nhận]
Microphone         Audio mixer          Speaker
PyAudio            Mix PCM              Playback queue
AUDIO_CHUNK        Loại tiếng bản thân  MIXED_AUDIO
```

Dùng mũi tên rõ ràng để thể hiện dữ liệu đi từ client gửi sang server rồi tới client nhận.

## Phong Cách Hình Ảnh

- Kiểu infographic kỹ thuật hiện đại.
- Nền sáng hoặc nền trắng.
- Màu xanh dương cho client.
- Màu cam hoặc tím cho server.
- Icon đơn giản cho microphone, server, network, speaker.
- Chữ tiếng Việt rõ ràng, dễ đọc.
- Không dùng quá nhiều chữ.
- Không dùng phong cách hoạt hình quá trẻ con.
- Tỉ lệ ảnh ngang 16:9.

## Yêu Cầu Quan Trọng

Sơ đồ phải làm rõ rằng:

1. PCM là dữ liệu âm thanh thô sau khi microphone thu vào.
2. Client cắt âm thanh thành frame 20 ms.
3. Audio được gửi qua TCP bằng packet `AUDIO_CHUNK`.
4. Server mix audio rồi gửi `MIXED_AUDIO` về client khác.
5. Server không gửi lại tiếng của chính người nghe để tránh echo.

## Prompt Ngắn Có Thể Copy

Tạo sơ đồ infographic tiếng Việt tỉ lệ 16:9 về luồng audio PCM trong app QuicKonNect. Bố cục từ trái sang phải gồm: Giọng nói người dùng -> Microphone -> PyAudio thu âm -> PCM samples -> Chia frame 20 ms -> AUDIO_CHUNK packet -> TCP socket mã hóa AES-GCM -> Server audio mixer -> MIXED_AUDIO packet -> Client nhận audio -> PyAudio phát loa -> Người nghe. Thêm nhãn kỹ thuật: 16 kHz, 16-bit, mono, 20 ms/frame, 640 bytes/frame. Ở server ghi chú: trộn audio của người khác, không gửi lại tiếng của chính người nghe, tránh echo từ server. Chia thành 3 vùng Client gửi, Server, Client nhận. Style kỹ thuật hiện đại, nền sáng, chữ rõ, icon microphone/server/network/speaker, màu xanh dương cho client và cam hoặc tím cho server.
