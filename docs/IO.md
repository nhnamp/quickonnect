**Message I/O Stream**

For the message feature, the main I/O stream is:

```text
User input
-> ChatWidget
-> ConnectionManager
-> shared protocol encoder
-> TCP socket write
-> server TCP socket read
-> server message handler
-> PostgreSQL write
-> server TCP socket broadcast
-> client TCP socket read
-> UI queue
-> ChatWidget render
```

**1. User Types And Sends**

The message begins in [chat_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/chat_widget.py:141).

At [lines 141-146](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/chat_widget.py:141), `_on_send()` checks that the user is currently inside a room and that the message text is not empty.

Then [lines 148-152](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/chat_widget.py:148) emit a `CHAT_MESSAGE` packet payload:

```python
{
    "room_code": self._current_room,
    "content": text,
    "msg_type": "text",
}
```

Important detail: the client does **not** immediately append the message to the chat window as a fake local echo. It only clears the input at [line 153](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/chat_widget.py:153). The visible message appears later only after the server stores and broadcasts it back.

**2. UI Hands Packet To Network Layer**

The emitted signal is connected in [main_window.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/main_window.py:165). It reaches `_send_packet()` at [main_window.py:271](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/main_window.py:271), which calls:

```python
self._conn.send(PacketType(packet_type), payload)
```

That enters [connection.py:82](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:82). The socket write is protected by `_send_lock` at [line 86](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:86), then sent through `send_packet()` at [line 88](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:88).

This matters because the same TCP connection may also carry heartbeat packets, screen packets, room packets, and friend packets. The lock prevents byte streams from being mixed together.

**3. Protocol Converts Message To TCP Bytes**

The shared protocol lives in [protocol.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:39).

For `CHAT_MESSAGE`, [shared/constants.py:38](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/constants.py:38) defines the packet type as `0x0030`.

The send path is:

- [protocol.py:45](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:45): JSON-encode the payload.
- [protocol.py:47](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:47): because `CHAT_MESSAGE` is not plaintext, encrypt it when an AES key exists.
- [protocol.py:48](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:48): build authenticated header data.
- [protocol.py:49](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:49): AES-GCM encrypt the JSON bytes.
- [protocol.py:50](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:50): pack the 40-byte binary header.
- [protocol.py:115](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:115): write all bytes to TCP using `sock.sendall(data)`.

So the real network stream is not plain text like `"hello"`. It is:

```text
40-byte QKNT header + AES-GCM encrypted JSON payload
```

**4. Server Reads The TCP Stream**

On the server, the per-client loop reads from the socket in [server/client_handler.py:191](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:191).

At [line 195](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:195), it calls:

```python
packet = read_packet(self._sock, self._aes_key)
```

`read_packet()` does the stream parsing in [protocol.py:89](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:89):

- [line 91](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:91): read exactly the 40-byte header.
- [line 92](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:92): decode and validate the header.
- [line 94](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:94): read exactly the payload length.
- [line 101](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:101): decrypt the payload.
- [line 103](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:103): parse JSON back into a Python dict.

Then [client_handler.py:205](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:205) dispatches the packet, and [line 209](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:209) maps `CHAT_MESSAGE` to `_handle_chat_message()`.

**5. Server Stores Message In Database**

The message handler starts at [client_handler.py:348](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:348).

- [lines 349-351](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:349): read `room_code`, `content`, and `msg_type`.
- [lines 353-354](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:353): ignore invalid empty messages.
- [lines 390-393](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:390): verify the room exists.
- [line 395](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:395): store the message using `message_service.store_message()`.

Database I/O happens in [message_service.py:13](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/services/message_service.py:13).

- [line 16](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/services/message_service.py:16): get a PostgreSQL connection.
- [lines 18-21](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/services/message_service.py:18): execute `INSERT INTO messages`.
- [line 23](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/services/message_service.py:23): fetch generated `id` and `sent_at`.
- [line 24](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/services/message_service.py:24): commit the transaction.

So the message is durable before it is broadcast back.

**6. Server Broadcasts Back To Clients**

After storage, the server prepares the outgoing payload:

- [client_handler.py:400](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:400): attach sender name.
- [line 401](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:401): convert the message model to dict.
- [line 402](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:402): attach `room_code`.
- [line 404](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:404): get connected clients in the room.
- [lines 405-406](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:405): send `CHAT_MESSAGE` to each room client.

This includes the sender, which is why the sender sees the server-confirmed version of their own message.

**7. Receiving Client Reads And Renders**

On every client, the receiver thread runs in [connection.py:111](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:111).

- [line 114](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:114): read/decrypt one packet from TCP.
- [line 115](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:115): put it into `packet_queue`.

The UI polls that queue in [main_window.py:192](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/main_window.py:192). When it sees `CHAT_MESSAGE`, [main_window.py:221](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/main_window.py:221) calls:

```python
self._chat_widget.add_message(data)
```

Then [chat_widget.py:155](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/chat_widget.py:155) appends it to local room state, and [line 225](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/chat_widget.py:225) updates the visible text area.

In short: the message feature uses **UI input**, **encrypted TCP socket output**, **server TCP input**, **PostgreSQL database output**, then **encrypted TCP output back to all clients**, and finally **UI rendering output**.