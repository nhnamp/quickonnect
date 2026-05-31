# Test QuicKonNect

Có 2 chế độ kết nối:

- **Multi-server**: client đi qua Load Balancer `9000`.
- **Single-server/ngrok**: client nối thẳng Chat Server `9001`, cần bật `QUICKONNECT_DIRECT_SERVER=1`.

Nếu trỏ client vào `9001` mà không bật direct mode, dễ gặp lỗi `connection closed while reading`.

## 1. Test Multi-Server

Chạy stack:

```powershell
cd C:\Users\nguye\OneDrive\Desktop\LTMCB\quickonnect
$env:DB_PORT = "55432"
$env:QUICKONNECT_STT_ENABLED = "1"
$env:QUICKONNECT_STT_MODEL = "small"
$env:QUICKONNECT_STT_TASK = "bilingual"
$env:QUICKONNECT_STT_WINDOW_SECONDS = "5"
$env:QUICKONNECT_STT_BEAM_SIZE = "5"
.venv\Scripts\python.exe scripts\run_demo_stack.py
```

Mở client:

```powershell
$env:DB_PORT = "55432"
$env:LB_HOST = "127.0.0.1"
$env:LB_PORT = "9000"
Remove-Item Env:\QUICKONNECT_DIRECT_SERVER -ErrorAction SilentlyContinue
.venv\Scripts\python.exe scripts\run_client.py
```

Trên giao diện:

```text
LB Host: 127.0.0.1
LB Port: 9000
```

Test:

- Đăng nhập 2 client.
- Xem log để thấy client được route vào `server-9001` hoặc `server-9002`.
- Test friend online, DM, tạo room/join room.

## 2. Test Trên 1 Máy Với 1 Server

Chạy server:

```powershell
cd C:\Users\nguye\OneDrive\Desktop\LTMCB\quickonnect
$env:DB_PORT = "55432"
$env:SERVER_HOST = "0.0.0.0"
$env:SERVER_PORT = "9001"
$env:SERVER_ID = "server-9001"
$env:QUICKONNECT_STT_ENABLED = "1"
$env:QUICKONNECT_STT_MODEL = "small"
$env:QUICKONNECT_STT_TASK = "bilingual"
$env:QUICKONNECT_STT_WINDOW_SECONDS = "5"
$env:QUICKONNECT_STT_BEAM_SIZE = "5"
.venv\Scripts\python.exe scripts\run_server.py 9001
```

Mở client 1:

```powershell
$env:DB_PORT = "55432"
$env:LB_HOST = "127.0.0.1"
$env:LB_PORT = "9001"
$env:QUICKONNECT_DIRECT_SERVER = "1"
$env:QUICKONNECT_DATA = "$PWD\.localdata\client1"
.venv\Scripts\python.exe scripts\run_client.py
```

Mở client 2:

```powershell
$env:DB_PORT = "55432"
$env:LB_HOST = "127.0.0.1"
$env:LB_PORT = "9001"
$env:QUICKONNECT_DIRECT_SERVER = "1"
$env:QUICKONNECT_DATA = "$PWD\.localdata\client2"
.venv\Scripts\python.exe scripts\run_client.py
```

Trên giao diện:

```text
LB Host: 127.0.0.1
LB Port: 9001
```

## 3. Test Qua LAN Với 1 Server

Trên máy server lấy IP:

```powershell
ipconfig
```

Ví dụ IP server:

```text
192.168.1.235
```

Máy server chạy server `9001` như mục 2.

Client máy 2 chạy:

```powershell
$env:LB_HOST = "192.168.1.235"
$env:LB_PORT = "9001"
$env:QUICKONNECT_DIRECT_SERVER = "1"
.venv\Scripts\python.exe scripts\run_client.py
```

Trên giao diện máy 2:

```text
LB Host: 192.168.1.235
LB Port: 9001
```

## 4. Test Qua Ngrok Với 1 Server

Máy server chạy server `9001` như mục 2.

Chạy ngrok:

```powershell
ngrok tcp 9001
```

Nếu ngrok hiện:

```text
tcp://0.tcp.ap.ngrok.io:27844
```

Client máy 2 chạy với direct mode:

```powershell
$env:LB_HOST = "0.tcp.ap.ngrok.io"
$env:LB_PORT = "27844"
$env:QUICKONNECT_DIRECT_SERVER = "1"
.venv\Scripts\python.exe scripts\run_client.py
```

Trên giao diện máy 2:

```text
LB Host: 0.tcp.ap.ngrok.io
LB Port: 27844
```

Không nhập `tcp://` vào ô Host.

## Test Audio

1. Hai client đăng nhập 2 user khác nhau.
2. Một client tạo room.
3. Client còn lại join room code.
4. Cả hai vào tab `Audio`.
5. Cả hai bấm `Join Audio`.
6. Nói thử hai chiều.
7. Test `Mute` / `Unmute`.

Subtitle đã được bật sẵn trong các lệnh chạy server ở trên. Nếu lần đầu chạy model `small`, phụ đề có thể xuất hiện chậm vài giây.
