# Phần của người 1: Screen Sharing và Remote Control

## 1. Kết nối, socket, I/O, stream, async và thread

Phần screen sharing dùng chung một kết nối TCP đã mã hóa giữa client và chat server, không tạo socket riêng cho media. Client gửi các packet `SCREEN_START`, `SCREEN_FRAME`, `SCREEN_STOP`, `REMOTE_REQUEST`, `REMOTE_GRANT`, và `REMOTE_EVENT` qua `ConnectionManager.send()`. Mỗi packet đều đi qua binary protocol chung của dự án: header có magic number, version, packet type, payload length, nonce và auth tag; payload JSON được mã hóa bằng AES-GCM sau khi client-server hoàn tất RSA handshake.

Luồng stream màn hình hoạt động theo chuỗi: client capture màn hình bằng `mss`, chuyển frame thành `QImage`, nén thành JPEG bằng `QBuffer`, base64 hóa và gửi qua TCP trong packet `SCREEN_FRAME`. Server không giải mã ảnh hay xử lý pixel, chỉ kiểm tra quyền và relay frame sang các client khác bằng `SCREEN_RELAY`. Bên viewer, client decode JPEG và render lên widget hiển thị.

Phần này có nhiều thread để tránh làm treo UI: capture thread lấy frame màn hình, send thread đọc frame từ hàng đợi và gửi qua TCP, network receiver thread nhận packet từ socket, UI thread render frame, và remote-control executor thread chạy `pyautogui` trên máy đang share. Hàng đợi frame có giới hạn kích thước 3 và dùng chiến lược drop-oldest, nghĩa là khi mạng chậm thì bỏ frame cũ để giữ frame mới nhất, giảm độ trễ khi xem màn hình.

Về async, module này không dùng `asyncio` mà triển khai bất đồng bộ theo mô hình của PyQt và thread. Network receiver thread nhận packet liên tục từ socket rồi đưa vào `packet_queue`; UI thread dùng `QTimer` polling khoảng 60 FPS để lấy packet ra xử lý và cập nhật giao diện. Nhờ đó, việc nhận `SCREEN_RELAY`, `REMOTE_REQUEST`, `REMOTE_GRANT` hay `REMOTE_EVENT` không block giao diện, và background thread cũng không trực tiếp sửa Qt widget. Đây là cách async phù hợp với PyQt vì mọi thay đổi UI vẫn được thực hiện trên main thread, còn network I/O và tác vụ nặng chạy nền.

## 2. Hạ tầng liên quan

Screen sharing là tính năng theo regular room, nên tất cả thành viên trong phòng phải được route về cùng một chat server. Load balancer dùng Redis để lưu room-to-server mapping; khi user join room, client hỏi load balancer trước, sau đó reconnect về server đang giữ room nếu cần. Điều này rất quan trọng vì screen frame và remote-control state là realtime state nằm trong bộ nhớ của một server.

Server lưu trạng thái share trong `ScreenRelayState` theo từng room. Mỗi room chỉ cho phép một người share tại một thời điểm; nếu user khác gửi `SCREEN_START` khi đã có sharer, server trả lỗi conflict. Server cũng kiểm tra sender có nằm trong room không, sender có phải current sharer không, và remote event có đến từ controller đã được cấp quyền không. Nhờ vậy, UI có lỗi hay client gửi packet sai thì server vẫn là nơi quyết định cuối cùng.

Về bảo mật, toàn bộ screen frame và remote-control event đi qua kênh AES-256-GCM đã được thiết lập bằng RSA-2048 handshake. Remote control bắt buộc có flow xin quyền: viewer gửi `REMOTE_REQUEST`, sharer thấy dialog allow/deny, server chỉ chấp nhận `REMOTE_EVENT` từ user đã được grant. Khi sharer revoke, stop sharing, leave room, hoặc disconnect, server xóa controller và broadcast trạng thái mới cho các client còn lại.

## 3. Tính năng chính

Người dùng có thể vào Screen tab để bật share màn hình. Người share thấy local preview để biết frame thực tế đang được capture; các thành viên khác trong cùng room nhận frame realtime. Late joiner không cần packet riêng: khi join room, server gửi `ROOM_STATE` kèm thông tin screen hiện tại, sau đó client sẽ render frame tiếp theo nhận được.

Remote control được xây trên screen sharing. Viewer bấm Request Control, sharer chấp nhận thì viewer mới được gửi chuột/phím. Tọa độ chuột được gửi dạng normalized từ 0.0 đến 1.0 thay vì pixel tuyệt đối, nên viewer resize cửa sổ vẫn điều khiển đúng vị trí trên màn hình host. Bên host, `RemoteControlExecutor` nhận event và chạy `pyautogui` trên thread riêng để không block giao diện.

Kết quả là module này thể hiện rõ các yêu cầu network programming: stream dữ liệu lớn qua TCP, xử lý đồng thời bằng thread, server relay nhiều client, room-aware routing qua load balancer, mã hóa dữ liệu, và có cơ chế permission an toàn cho remote control.

## 4. Kiến thức chương trình học đã áp dụng

Dựa trên nội dung phần screen sharing và remote control ở trên, các kiến thức đã áp dụng gồm:

- Chương 2 - Luồng dữ liệu (Stream) và I/O: luồng frame được capture, nén JPEG, base64 hóa và truyền liên tục qua TCP; phía nhận decode và render theo dòng dữ liệu đến.
- Chương 3 - Lập trình đa luồng - Multithreading: tách thread capture, send, network receiver, UI render và remote-control executor để tránh block UI; có hàng đợi giới hạn và drop-oldest để giảm trễ.
- Async/event-driven programming: dùng `QTimer` và `packet_queue` để xử lý packet bất đồng bộ trên UI thread, thay vì để socket thread cập nhật giao diện trực tiếp.
- Chương 4 - Lập trình socket cơ bản: client/server dùng socket để gửi và nhận packet theo binary protocol, có kiểm tra quyền và relay qua server.
- Chương 5 - Lập trình socket UDP và TCP: phần này sử dụng TCP cho các gói `SCREEN_*` và `REMOTE_*` để đảm bảo dữ liệu đến theo thứ tự và ổn định; không dùng UDP trong phạm vi mô tả.
- Chương 9 - Lập trình với RAW SOCKET: không áp dụng trong phần này, vì không thao tác gói tin thô hay tự xây IP/TCP header.
- Chương 11 - Bảo mật: handshake RSA-2048, mã hóa AES-256-GCM, nonce/auth tag, và cơ chế cấp quyền remote control (request/grant/revoke) để bảo vệ dữ liệu và quyền điều khiển.
