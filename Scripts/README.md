# Cavli C16QS — PPP Mode via UART (USB-to-TTL) & Google Ping

## Table of Contents
1. [Hardware Setup](#1-hardware-setup)
2. [AT Command Sequence — Entering PPP Mode](#2-at-command-sequence--entering-ppp-mode)
3. [PPP Protocol Overview](#3-ppp-protocol-overview)
4. [LCP — Link Control Protocol](#4-lcp--link-control-protocol)
5. [PAP — Password Authentication Protocol](#5-pap--password-authentication-protocol)
6. [IPCP — IP Control Protocol](#6-ipcp--ip-control-protocol)
7. [ICMP — Ping Packets over PPP](#7-icmp--ping-packets-over-ppp)
8. [Packet Send Order](#8-packet-send-order)
9. [Understanding Reply Packets](#9-understanding-reply-packets)
10. [Python Script Walkthrough](#10-python-script-walkthrough)

---

## 1. Hardware Setup

| USB-to-TTL Pin | C16QS Pin |
|----------------|-----------|
| TX             | RXD (UART RX) |
| RX             | TXD (UART TX) |
| GND            | GND       |
| 3.3 V (optional) | VCC (if powering from USB) |

**Serial Settings**

```
Baud rate : 115200
Data bits : 8
Stop bits : 1
Parity    : None
Flow ctrl : None
```

---

## 2. AT Command Sequence — Entering PPP Mode

Run these AT commands in order over the serial port. Each line ends with `\r\n`.

### Step 1 — Check modem is alive
```
AT
```
Expected reply: `OK`

### Step 2 — Check SIM status
```
AT+CIMI
```
Expected reply: 15-digit IMSI number, then `OK`

### Step 3 — Check registration
```
AT+CREG?
```
Expected reply: `+CREG: 0,1` (1 = home network, 5 = roaming)

### Step 4 — Check signal quality
```
AT+CSQ
```
Expected reply: `+CSQ: <rssi>,<ber>` — rssi 10–31 is usable

### Step 5 — Set PDP context (APN)
```
AT+CGDCONT=1,"IP","<YOUR_APN>"
```
Replace `<YOUR_APN>` with your carrier's APN (e.g. `internet`, `airtelgprs.com`, etc.)  
Expected reply: `OK`

### Step 6 — Activate PDP context
```
AT+CGACT=1,1
```
Expected reply: `OK`

### Step 7 — Dial into PPP
```
ATD*99***1#
```
Expected reply: `CONNECT` — modem is now in PPP data mode.  
After `CONNECT`, the port switches to binary PPP framing. **Do not send further AT commands.**

---

## 3. PPP Protocol Overview

PPP (Point-to-Point Protocol) wraps every packet in an HDLC-like frame:

```
+------+------+------+------+--------...--------+------+------+
| Flag | Addr | Ctrl | Protocol (2B) |  Payload  | FCS  | Flag |
| 0x7E | 0xFF | 0x03 |               |           | 2 B  | 0x7E |
+------+------+------+------+--------...--------+------+------+
```

| Field    | Value  | Meaning                          |
|----------|--------|----------------------------------|
| Flag     | `7E`   | Frame delimiter (start & end)    |
| Address  | `FF`   | Broadcast (always FF in PPP)     |
| Control  | `03`   | Unnumbered Information frame     |
| Protocol | 2 bytes| Identifies payload type (see below)|
| Payload  | N bytes| LCP / PAP / IPCP / IP data      |
| FCS      | 2 bytes| CRC-16 checksum over Addr→Payload|

**Protocol codes:**

| Protocol | Hex    |
|----------|--------|
| LCP      | `C0 21`|
| PAP      | `C0 23`|
| IPCP     | `80 21`|
| IPv4     | `00 21`|

**Byte stuffing:** any byte `7E` or `7D` inside the payload is escaped as `7D 5E` or `7D 5D` respectively.

---

## 4. LCP — Link Control Protocol

LCP negotiates the link. The sequence is:

```
Host  ──► Modem  :  LCP Configure-Request
Host  ◄── Modem  :  LCP Configure-Request  (modem's options)
Host  ──► Modem  :  LCP Configure-Ack
Host  ◄── Modem  :  LCP Configure-Ack
```

### 4.1 LCP Configure-Request (host → modem)

Full frame bytes (hex):

```
7E FF 03 C0 21 01 01 00 0A 05 06 xx xx xx xx 07 02 08 02 FCS FCS 7E
```

Byte-by-byte breakdown:

| Offset | Hex   | Meaning |
|--------|-------|---------|
| 0      | `7E`  | PPP flag — start of frame |
| 1      | `FF`  | PPP address |
| 2      | `03`  | PPP control |
| 3–4    | `C0 21` | Protocol = LCP |
| 5      | `01`  | LCP code = Configure-Request |
| 6      | `01`  | Identifier (0x01 for first request) |
| 7–8    | `00 0A` | Length of LCP payload = 10 bytes |
| 9      | `05`  | Option type = Magic Number |
| 10     | `06`  | Option length = 6 bytes |
| 11–14  | `xx xx xx xx` | 4-byte random magic number |
| 15     | `07`  | Option type = Protocol-Field-Compression |
| 16     | `02`  | Option length = 2 |
| 17     | `08`  | Option type = Address-and-Control-Field-Compression |
| 18     | `02`  | Option length = 2 |
| 19–20  | FCS   | 16-bit CRC |
| 21     | `7E`  | PPP flag — end of frame |

### 4.2 LCP Configure-Ack (host → modem, after receiving modem's request)

Same structure as Configure-Request but:
- Code byte = `02` (Configure-Ack)
- Identifier = same as modem sent
- Payload = exact copy of modem's options

### 4.3 LCP Codes Reference

| Code | Hex | Name |
|------|-----|------|
| Configure-Request | `01` | Propose options |
| Configure-Ack     | `02` | Accept all options |
| Configure-Nak     | `03` | Accept some, change others |
| Configure-Reject  | `04` | Cannot support option |
| Terminate-Request | `05` | Close link |
| Echo-Request      | `09` | Keep-alive ping |

---

## 5. PAP — Password Authentication Protocol

Some ISPs require PAP after LCP. The modem will send an `Authenticate-Request` challenge.

### PAP Authenticate-Request (host → modem)

```
7E FF 03 C0 23 01 01 00 LL UL <username> PL <password> FCS FCS 7E
```

| Offset | Hex | Meaning |
|--------|-----|---------|
| 0      | `7E` | PPP flag |
| 1–2    | `FF 03` | Address + Control |
| 3–4    | `C0 23` | Protocol = PAP |
| 5      | `01`   | Code = Authenticate-Request |
| 6      | `01`   | Identifier |
| 7–8    | `00 LL` | Total length |
| 9      | `UL`   | Username length (1 byte) |
| 10…    | username bytes |
| next   | `PL`   | Password length (1 byte) |
| next…  | password bytes |
| last 2 | FCS    |
| last   | `7E`   |

If successful, modem replies: `Code=02` (Authenticate-Ack).  
If your ISP doesn't use PAP, skip this step.

---

## 6. IPCP — IP Control Protocol

IPCP negotiates IP addresses. Sequence:

```
Host  ──► Modem  :  IPCP Configure-Request  (IP 0.0.0.0 = "please assign me one")
Host  ◄── Modem  :  IPCP Configure-Nak      (contains the IP the modem wants to give)
Host  ──► Modem  :  IPCP Configure-Request  (repeat with the assigned IP)
Host  ◄── Modem  :  IPCP Configure-Ack
```

### 6.1 IPCP Configure-Request — requesting an IP (host → modem)

```
7E FF 03 80 21 01 01 00 10 03 06 00 00 00 00 81 06 00 00 00 00 83 06 00 00 00 00 FCS FCS 7E
```

| Offset | Hex          | Meaning |
|--------|--------------|---------|
| 0      | `7E`         | PPP start |
| 1–2    | `FF 03`      | Address + Control |
| 3–4    | `80 21`      | Protocol = IPCP |
| 5      | `01`         | Code = Configure-Request |
| 6      | `01`         | Identifier |
| 7–8    | `00 10`      | Length = 16 bytes |
| 9      | `03`         | Option = IP-Address |
| 10     | `06`         | Option length = 6 |
| 11–14  | `00 00 00 00`| IP = 0.0.0.0 (request assignment) |
| 15     | `81`         | Option = Primary DNS |
| 16     | `06`         | Option length |
| 17–20  | `00 00 00 00`| DNS = 0.0.0.0 (request) |
| 21     | `83`         | Option = Secondary DNS |
| 22     | `06`         | Option length |
| 23–26  | `00 00 00 00`| DNS = 0.0.0.0 (request) |
| 27–28  | FCS          |
| 29     | `7E`         | PPP end |

### 6.2 After IPCP Configure-Nak

The modem's Nak contains the real IP/DNS values. Extract them, put them in a second Configure-Request, and the modem will reply with Configure-Ack.

### 6.3 IPCP Option Codes

| Option | Hex  | Description |
|--------|------|-------------|
| IP-Address        | `03` | The host's IP address |
| Primary DNS       | `81` | Primary DNS server |
| Secondary DNS     | `83` | Secondary DNS server |

---

## 7. ICMP — Ping Packets over PPP

Once IPCP is complete, the modem has given you a real IP. ICMP Echo-Request (ping) packets are wrapped as:

```
PPP Header → IPv4 Header → ICMP Payload
```

### 7.1 Full ICMP Echo-Request frame

```
7E FF 03 00 21
  45 00 00 3C <ip-id> 00 00 00 40 01 <ip-chk> <src-ip x4> <dst-ip x4>
  08 00 <icmp-chk> 00 01 00 01
  <payload 32 bytes>
FCS FCS 7E
```

### 7.2 IPv4 Header — byte breakdown

| Offset | Hex     | Meaning |
|--------|---------|---------|
| 0      | `45`    | Version=4, IHL=5 (20 byte header) |
| 1      | `00`    | DSCP/ECN = 0 |
| 2–3    | `00 3C` | Total length = 60 bytes (20 IP + 8 ICMP + 32 data) |
| 4–5    | `AB CD` | Identification (random 16-bit) |
| 6–7    | `00 00` | Flags=0, Fragment Offset=0 |
| 8      | `40`    | TTL = 64 |
| 9      | `01`    | Protocol = ICMP (1) |
| 10–11  | checksum| IP header checksum (one's complement) |
| 12–15  | src IP  | Your assigned IP (from IPCP) |
| 16–19  | dst IP  | 8.8.8.8 = `08 08 08 08` |

### 7.3 ICMP Header — byte breakdown

| Offset | Hex    | Meaning |
|--------|--------|---------|
| 20     | `08`   | ICMP Type = Echo-Request |
| 21     | `00`   | Code = 0 |
| 22–23  | chksum | ICMP checksum (over ICMP header + data) |
| 24–25  | `00 01`| Identifier = 1 |
| 26–27  | `00 01`| Sequence Number = 1 (increment each ping) |
| 28–59  | data   | 32 bytes of padding (e.g. `61 62 63…`) |

### 7.4 IP Checksum Algorithm

```python
def checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i+1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF
```

---

## 8. Packet Send Order

Send packets **strictly in this order**. Do not proceed to the next step until you receive the expected reply.

```
1.  AT commands (text mode)
      └─ ATD*99***1#  →  wait for "CONNECT"

2.  Switch to binary PPP mode

3.  LCP Configure-Request       (host → modem)
4.  LCP Configure-Request       (modem → host)   ← receive & parse
5.  LCP Configure-Ack           (host → modem)   ← ack modem's options
6.  LCP Configure-Ack           (modem → host)   ← receive (modem acks ours)

7.  [Optional] PAP Authenticate-Request (if modem sends Authenticate challenge)
8.  [Optional] PAP Ack           (modem → host)

9.  IPCP Configure-Request      (host → modem, IP=0.0.0.0)
10. IPCP Configure-Nak          (modem → host)   ← extract assigned IP
11. IPCP Configure-Request      (host → modem, real IP)
12. IPCP Configure-Ack          (modem → host)   ← PPP tunnel is UP

13. Build ICMP Echo-Request with assigned IP as source, 8.8.8.8 as dest
14. Wrap in PPP frame and send
15. Receive PPP frame containing ICMP Echo-Reply
16. Parse and print round-trip time
```

---

## 9. Understanding Reply Packets

### 9.1 Stripping the PPP wrapper

Every incoming frame:
1. Strip leading `7E` and trailing `7E`
2. Un-stuff bytes (`7D 5E` → `7E`, `7D 5D` → `7D`)
3. Verify FCS (last 2 bytes) — discard if wrong
4. Read protocol field (bytes 3–4)

### 9.2 ICMP Echo-Reply — full parse

Protocol field = `00 21` (IPv4), then:

| Offset | Field | How to use |
|--------|-------|------------|
| 0–19   | IPv4 header | Read src IP (bytes 12–15) = modem's IP |
| 20     | ICMP Type | Must be `00` = Echo-Reply |
| 21     | ICMP Code | Must be `00` |
| 22–23  | Checksum  | Verify |
| 24–25  | Identifier| Match to your request identifier |
| 26–27  | Sequence  | Match to your sequence number |
| 28–end | Data      | Should mirror what you sent |

### 9.3 Common ICMP Type codes in replies

| Type | Meaning |
|------|---------|
| `00` | Echo-Reply — success |
| `03` | Destination Unreachable |
| `0B` | Time Exceeded (TTL = 0) |

### 9.4 LCP Echo-Request (keep-alive from modem)

Modem may send periodic LCP Echo-Requests (code `09`). You must reply with code `0A` (Echo-Reply), same identifier, same magic number — or the modem will drop the link.

---

## 10. Python Script Walkthrough

```python
import serial, struct, time

PORT   = "/dev/ttyUSB0"   # adjust for your OS
BAUD   = 115200
APN    = "internet"

# --- CRC-16 (HDLC / PPP FCS) ---
def fcs16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF

def stuff(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b in (0x7E, 0x7D):
            out += bytes([0x7D, b ^ 0x20])
        else:
            out.append(b)
    return bytes(out)

def frame(protocol: bytes, payload: bytes) -> bytes:
    inner = b'\xFF\x03' + protocol + payload
    fcs   = struct.pack('<H', fcs16(inner))
    return b'\x7E' + stuff(inner + fcs) + b'\x7E'

# --- Checksum helper ---
def checksum(data: bytes) -> int:
    if len(data) % 2: data += b'\x00'
    s = sum((data[i] << 8) + data[i+1] for i in range(0, len(data), 2))
    while s >> 16: s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF

# --- Build ICMP Echo-Request ---
def build_ping(src_ip: bytes, seq: int) -> bytes:
    dst_ip  = bytes([8, 8, 8, 8])
    icmp_id = 1
    payload = b'abcdefghijklmnopqrstuvwxyz123456'
    icmp_hdr = struct.pack('>BBHHH', 8, 0, 0, icmp_id, seq)
    icmp_ck  = checksum(icmp_hdr + payload)
    icmp     = struct.pack('>BBHHH', 8, 0, icmp_ck, icmp_id, seq) + payload

    ip_id  = seq & 0xFFFF
    ip_hdr = struct.pack('>BBHHHBBH4s4s',
        0x45, 0, 20 + len(icmp), ip_id, 0, 64, 1, 0, src_ip, dst_ip)
    ip_ck  = checksum(ip_hdr)
    ip_hdr = struct.pack('>BBHHHBBH4s4s',
        0x45, 0, 20 + len(icmp), ip_id, 0, 64, 1, ip_ck, src_ip, dst_ip)

    return frame(b'\x00\x21', ip_hdr + icmp)

# Usage:
# ser = serial.Serial(PORT, BAUD, timeout=2)
# ... run AT commands, negotiate PPP, extract src_ip from IPCP ...
# ser.write(build_ping(src_ip, seq=1))
# reply = ser.read(1500)
# Parse ICMP type at offset 20 inside PPP payload
```

---

## References

- RFC 1661 — The Point-to-Point Protocol (PPP)
- RFC 1332 — The PPP Internet Protocol Control Protocol (IPCP)
- RFC 792  — Internet Control Message Protocol (ICMP)
- RFC 1334 — PPP Authentication Protocols (PAP / CHAP)
- Cavli C16QS AT Command Manual (contact Cavli Wireless)
