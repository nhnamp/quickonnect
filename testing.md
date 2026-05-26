# Test QuicKonNect

Luu y: ban hien tai dang bypass load balancer, nen tren client hai o `LB Host` va `LB Port` chinh la host/port cua chat server.

## Chay Server

Chay server co audio thuong:

```powershell
cd C:\Users\nguye\OneDrive\Desktop\LTMCB\quickonnect
$env:DB_PORT = "55432"
$env:SERVER_HOST = "0.0.0.0"
$env:SERVER_PORT = "9001"
$env:SERVER_ID = "server-9001"
.venv\Scripts\python.exe scripts\run_server.py 9001
```

Neu can subtitle, them truoc dong run server:

```powershell
$env:QUICKONNECT_STT_ENABLED = "1"
$env:QUICKONNECT_STT_MODEL = "small"
$env:QUICKONNECT_STT_TASK = "transcribe"
```

## 1. Test Tren 1 May

Mo 2 client tren cung may.

Client 1:

```powershell
$env:LB_HOST = "127.0.0.1"
$env:LB_PORT = "9001"
$env:QUICKONNECT_DATA = "$PWD\.localdata\client1"
.venv\Scripts\python.exe scripts\run_client.py
```

Client 2:

```powershell
$env:LB_HOST = "127.0.0.1"
$env:LB_PORT = "9001"
$env:QUICKONNECT_DATA = "$PWD\.localdata\client2"
.venv\Scripts\python.exe scripts\run_client.py
```

Tren giao dien ca 2 client:

```text
LB Host: 127.0.0.1
LB Port: 9001
```

## 2. Test Qua LAN

Tren may server, lay IP:

```powershell
ipconfig
```

Vi du IP may server la:

```text
192.168.1.235
```

Client may server:

```text
LB Host: 127.0.0.1
LB Port: 9001
```

Client may 2 cung Wi-Fi/LAN:

```text
LB Host: 192.168.1.235
LB Port: 9001
```

Neu khong ket noi duoc, kiem tra firewall va dung IP may server.

## 3. Test Qua Ngrok

Tren may server, chay:

```powershell
ngrok tcp 9001
```

Neu ngrok hien:

```text
tcp://0.tcp.ap.ngrok.io:27844
```

Client may server:

```text
LB Host: 127.0.0.1
LB Port: 9001
```

Client may 2:

```text
LB Host: 0.tcp.ap.ngrok.io
LB Port: 27844
```

Khong dien `tcp://` vao Host. Moi lan mo lai ngrok, port co the doi.

## Test Audio

1. Hai may dang nhap 2 user khac nhau.
2. Mot may tao room.
3. May con lai join room code.
4. Ca hai vao tab `Audio`.
5. Ca hai bam `Join Audio`.
6. Noi thu hai chieu.
7. Test `Mute` / `Unmute`.

Neu subtitle sai nhieu, demo audio truoc; subtitle nen de `transcribe` thay vi `bilingual`.
