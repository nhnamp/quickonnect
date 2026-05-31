# Báo Cáo Ngắn Về Chức Năng Audio

## 1. Dùng Gì Để Làm Audio?

Chức năng audio của QuicKonNect dùng các thành phần chính sau:

| Thành phần | Dùng để làm gì |
|---|---|
| `PyAudio` | Thu âm từ microphone và phát âm ra loa trên client |
| `TCP socket` | Truyền audio giữa client và server |
| `threading` | Chạy thu âm, phát âm, nhận client và mix audio song song |
| `PCM 16-bit` | Định dạng dữ liệu âm thanh thô |
| `base64` | Đóng gói bytes audio vào JSON packet |
| `AES-GCM` | Mã hóa packet audio trên đường truyền |
| `faster-whisper` | Tạo phụ đề, nếu bật STT |

Thông số audio hiện tại:

```text
Sample rate: 16 kHz
Channel: mono
Sample width: 16-bit
Frame size: 20 ms
Mỗi frame: 640 bytes
```

Client chia âm thanh thành từng đoạn nhỏ 20 ms rồi gửi liên tục lên server.

## 2. Vì Sao Dùng Các Công Nghệ Này?

### Vì sao dùng TCP?

Dự án thuộc môn Lập trình mạng, yêu cầu chính là tự xây hệ thống client-server bằng TCP socket. TCP đảm bảo dữ liệu đến đúng thứ tự và không bị mất packet, nên dễ thiết kế protocol và dễ demo hơn.

Đổi lại, TCP có độ trễ cao hơn UDP khi mạng yếu. Nhưng với demo 2-3 máy trong LAN hoặc qua ngrok, cách này vẫn chấp nhận được.

### Vì sao dùng PyAudio?

PyAudio cho phép Python truy cập microphone và speaker trực tiếp. Nó phù hợp với ứng dụng desktop PyQt6 vì có thể chạy thu âm/phát âm trong thread nền.

### Vì sao dùng PCM thô?

PCM thô dễ xử lý và dễ debug. Server có thể mix trực tiếp các sample âm thanh mà không cần giải mã codec phức tạp.

Nhược điểm là tốn băng thông hơn codec như Opus. Nếu tối ưu sau này, có thể thêm Opus để nén audio.

### Vì sao server phải mix audio?

Server-side mixing giúp mỗi client chỉ nhận một luồng audio đã trộn, thay vì phải nhận riêng audio của từng người.

Ví dụ có 3 người A, B, C:

- Nếu không mix: A phải nhận B và C riêng.
- Nếu có server mix: A chỉ nhận một luồng là B + C.

Cách này đơn giản hơn cho client và thể hiện rõ xử lý mạng phía server.

## 3. Luồng Dữ Liệu Audio

Luồng tổng quát:

```text
Microphone client A
    -> PyAudio đọc âm thanh
    -> chia thành frame PCM 20 ms
    -> gửi packet AUDIO_CHUNK qua TCP
    -> server nhận và đưa vào buffer của phòng
    -> server mix audio
    -> gửi packet MIXED_AUDIO về client khác
    -> client nhận, đưa vào playback queue
    -> PyAudio phát ra loa
```

Packet client gửi lên server là `AUDIO_CHUNK`, gồm:

```text
room_code
seq
timestamp_ms
sample_rate
channels
sample_width
pcm_b64
```

Packet server gửi về client là `MIXED_AUDIO`, gồm:

```text
room_code
timestamp_ms
sample_rate
channels
sample_width
pcm_b64
```

Trong đó `pcm_b64` là dữ liệu âm thanh PCM đã được base64 để đưa vào JSON.

## 4. Khi Có 2 Máy Thì Audio Chạy Như Thế Nào?

Giả sử có 2 máy:

```text
Máy 1: user A
Máy 2: user B
Server: chạy trên máy 1 hoặc một máy riêng
```

### Khi A nói

```text
Mic A
-> Client A gửi AUDIO_CHUNK lên server
-> Server nhận audio của A
-> Server tạo MIXED_AUDIO cho B
-> Client B nhận và phát ra loa
```

Server không gửi lại audio của A cho A, nên A không nghe lại chính mình từ server.

### Khi B nói

```text
Mic B
-> Client B gửi AUDIO_CHUNK lên server
-> Server nhận audio của B
-> Server tạo MIXED_AUDIO cho A
-> Client A nhận và phát ra loa
```

Với 2 người, server gần như chỉ chuyển audio của người này sang người kia, nhưng vẫn đi qua bước mixer để giữ cùng một cơ chế cho nhiều người.

## 5. Dữ Liệu Đi Qua Mạng Như Thế Nào?

Audio không đi trực tiếp máy 1 sang máy 2 theo kiểu peer-to-peer. Tất cả đều đi qua server:

```text
Client A <-> Server <-> Client B
```

Nếu test trên cùng một máy:

```text
Client A -> 127.0.0.1:9001 -> Server -> Client B
```

Nếu test LAN:

```text
Client A -> IP LAN server:9001 -> Server -> Client B
```

Nếu test ngrok:

```text
Client ngoài mạng -> ngrok TCP tunnel -> Server port 9001
```

Do đi qua server, server có thể:

- Kiểm tra user có ở trong phòng không.
- Quản lý mute/unmute.
- Mix nhiều người nói.
- Không gửi echo về chính người nói.
- Tạo phụ đề nếu bật STT.

## 6. Server Xử Lý Audio Như Thế Nào?

Mỗi phòng có một `AudioRoomState`.

Trong đó server lưu:

- Buffer audio của từng user.
- Trạng thái user đang nói hay đang mute.
- Một mixer thread chạy mỗi 20 ms.
- Một subtitle worker nếu bật phụ đề.

Mỗi 20 ms, server:

1. Lấy một frame audio mới nhất từ mỗi user.
2. Với từng người nghe, chọn audio của những người còn lại.
3. Trộn các sample âm thanh lại.
4. Chia trung bình để tránh âm lượng quá lớn.
5. Gửi `MIXED_AUDIO` về người nghe.

Ví dụ phòng có A và B:

```text
Gửi cho A: chỉ gồm audio của B
Gửi cho B: chỉ gồm audio của A
```

Ví dụ phòng có A, B, C:

```text
Gửi cho A: mix B + C
Gửi cho B: mix A + C
Gửi cho C: mix A + B
```

## 7. Mute Và Unmute

Khi bấm `Mute`, client gửi một packet báo:

```text
muted = true
```

Server sẽ:

- Đánh dấu user đó đang mute.
- Xóa audio cũ trong buffer của user.
- Không đưa user đó vào mixer.

Khi `Unmute`, client gửi audio frame lại bình thường, server đưa user vào mixer trở lại.

## 8. Mã Hóa Audio

Audio đi qua cùng lớp mã hóa của hệ thống.

Khi client kết nối server:

1. Client và server bắt tay RSA.
2. Server tạo khóa AES session.
3. Sau đó các packet như `AUDIO_CHUNK`, `MIXED_AUDIO`, `SUBTITLE` được mã hóa bằng AES-GCM.

Vì vậy người ngoài mạng không đọc được nội dung audio packet.

Tuy nhiên đây không phải end-to-end encryption cho audio, vì server cần đọc audio để mix và tạo phụ đề.

## 9. Phụ Đề Hoạt Động Như Thế Nào?

Phụ đề là tính năng tùy chọn.

Nếu bật:

```powershell
$env:QUICKONNECT_STT_ENABLED = "1"
```

Server sẽ gom audio của từng người trong vài giây, đưa vào `faster-whisper`, rồi gửi kết quả về client bằng packet `SUBTITLE`.

Có 3 chế độ:

| Chế độ | Ý nghĩa |
|---|---|
| `transcribe` | Nhận dạng lời nói gốc |
| `translate` | Dịch sang tiếng Anh |
| `bilingual` | Hiển thị cả câu gốc và câu dịch |

Khi demo, nên dùng `transcribe` vì ổn định hơn. `bilingual` dễ sai hơn vì vừa nhận dạng vừa dịch.

## 10. Những Điểm Có Thể Nói Khi Báo Cáo

Có thể nói ngắn gọn như sau:

> Chức năng audio dùng PyAudio để thu và phát âm thanh. Client chia âm thanh microphone thành các frame PCM 20 ms rồi gửi lên server bằng packet AUDIO_CHUNK qua TCP. Server tạo một audio state cho từng phòng, lưu buffer audio của từng user và cứ mỗi 20 ms sẽ mix audio. Khi gửi về một user, server chỉ gửi audio của những người khác, không gửi lại audio của chính user đó để tránh echo. Dữ liệu audio đi qua lớp mã hóa AES-GCM sau bước bắt tay RSA. Nếu bật phụ đề, server gom audio theo từng đoạn vài giây và dùng faster-whisper để nhận dạng giọng nói.

## 11. Cô Có Thể Hỏi Gì?

### Vì sao dùng TCP cho audio?

Vì yêu cầu môn học là tự xây hệ thống TCP socket. TCP đảm bảo dữ liệu đến đúng thứ tự, dễ đóng gói packet và dễ demo. Nhược điểm là độ trễ cao hơn UDP.

### Vì sao không dùng WebRTC?

WebRTC là giải pháp có sẵn cho audio/video real-time, nhưng mục tiêu của project là tự xây socket, protocol, server, load balancing và xử lý audio phía server.

### Vì sao server phải mix audio?

Vì nếu nhiều người nói, server có thể gom lại thành một luồng audio cho mỗi client. Client đơn giản hơn và mỗi client không phải tự nhận nhiều luồng riêng lẻ.

### Làm sao tránh nghe lại tiếng của chính mình?

Khi server tạo audio cho một user, nó loại audio của chính user đó ra khỏi danh sách cần mix. Vì vậy user chỉ nghe người khác.

### Vì sao không dùng end-to-end encryption cho audio?

Vì server cần đọc audio để mix và tạo phụ đề. Nếu audio end-to-end thật sự, server không giải mã được nên không thể xử lý.

### Khi 2 máy ở khác mạng dùng ngrok thì dữ liệu đi thế nào?

Máy 2 kết nối đến địa chỉ TCP của ngrok. Ngrok chuyển kết nối đó về port `9001` trên máy chạy server. Sau đó client và server vẫn giao tiếp bằng protocol TCP của project như bình thường.

### Vì sao subtitle có thể sai?

Vì subtitle phụ thuộc microphone, tiếng ồn, model Whisper, độ dài câu nói và ngôn ngữ. Model nhỏ chạy nhanh nhưng kém chính xác hơn. Vì vậy khi demo nên dùng `transcribe` và nói rõ từng câu.
