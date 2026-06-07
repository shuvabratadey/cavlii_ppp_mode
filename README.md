# ESP32 + Cavli C16QS — Developer Guide

A complete developer guide covering hardware setup, AT commands, PPP/PPPoS cellular connectivity, HTTP data transmission, GNSS tracking, and Python diagnostic tooling — from first boot to internet-connected IoT device.

**Tags:** `ESP-IDF v5.x` · `PPPoS / lwIP` · `AT Commands` · `GNSS / NMEA` · `Python Tkinter GUI` · `Raspberry Pi`

---

## Table of Contents

1. [Introduction — ESP32 & Cavli C16QS overview](#1-introduction)
2. [Hardware Overview — pins, power, UART](#2-hardware-overview)
3. [Interfacing — wiring, configuration, initialization](#3-esp32--cavli-c16qs-interfacing)
4. [AT Commands — fundamentals & command sequence](#4-at-commands)
5. [Ping Requests — connectivity & DNS testing](#5-ping-requests--ppp-connectivity-testing)
6. [Data Communication — HTTP, MQTT, TCP/UDP](#6-data-communication)
7. [Python Utility Tools — PPP Workbench, GNSS Monitor](#7-python-utility-tools)
8. [Main ESP32 Project — architecture & workflow](#8-main-esp32-project-documentation)
9. [ESP32 Code Walkthrough — line-by-line](#9-esp32-source-code-walkthrough)
10. [Python Code Walkthrough](#10-python-source-code-walkthrough)
11. [Creating a New Project — from scratch](#11-creating-a-new-project)
12. [Raspberry Pi + Cavli C16QS Integration](#12-raspberry-pi--cavli-c16qs-integration)
13. [Troubleshooting Guide](#13-troubleshooting-guide)
14. [AT Command Reference](#14-at-command-reference)

---

## 1. Introduction

### 1.1 ESP32 Platform Overview

The **ESP32** is a powerful, low-cost System-on-Chip (SoC) by Espressif Systems. It features a dual-core Xtensa LX6 processor running up to 240 MHz, 520 KB SRAM, integrated Wi-Fi (802.11 b/g/n), Bluetooth 4.2/BLE, and a rich peripheral set — including three hardware UART ports that make it ideal for modem interfacing.

| Feature | Description |
|---|---|
| **Dual-Core 240 MHz** | Xtensa LX6 cores — one for real-time modem I/O, one for application logic. |
| **3× Hardware UART** | UART0 (debug), UART1, UART2 — UART2 used for modem on pins 16/17. |
| **lwIP TCP/IP** | Full-featured embedded TCP/IP stack with PPPoS support built into ESP-IDF. |
| **FreeRTOS** | Real-time OS with tasks, queues, event groups — used for PPP RX task. |

### 1.2 Cavli C16QS Module Overview

The **Cavli C16QS** is a compact LTE Cat-1 cellular IoT module offering a full suite of communication capabilities. It bridges your embedded device to the global cellular network and exposes functionality through a standard AT command interface over UART.

| Feature | Description |
|---|---|
| **LTE Cat-1** | 10 Mbps DL / 5 Mbps UL — ideal for IoT telemetry and moderate-bandwidth applications. |
| **GNSS Built-in** | Integrated GNSS receiver supporting GPS, GLONASS — outputs NMEA sentences over UART. |
| **PPP Support** | Native `AT+PPPSTART` command switches UART to binary PPP data mode. |
| **Standard AT Interface** | ITU-T V.25ter + 3GPP TS 27.007 / 27.005 AT command set. |

### 1.3 Typical IoT Applications

- Remote sensor telemetry over cellular (temperature, pressure, vibration)
- Asset tracking with GPS + cellular uplink
- Industrial gateway bridging field devices to cloud platforms
- Smart metering and utility monitoring
- Emergency communication devices with fallback connectivity
- Agricultural IoT — soil, weather, irrigation automation

---

## 2. Hardware Overview

### 2.1 ESP32 UART Pin Map

| UART Port | Default TX | Default RX | Role in this Project |
|---|---|---|---|
| `UART0` | GPIO1 | GPIO3 | USB debug serial / ESP-IDF monitor |
| `UART1` | GPIO10 | GPIO9 | Available for other peripherals |
| `UART2` | **GPIO17** | **GPIO16** | **Modem interface (C16QS)** |

### 2.2 Cavli C16QS Power Requirements

| Parameter | Value | Notes |
|---|---|---|
| Supply Voltage (VCC) | 3.3 V – 4.2 V | Use 3.7 V LiPo or regulated 3.8 V |
| Peak Current (Tx burst) | Up to 2 A | Use bulk capacitors (≥470 µF) |
| Idle Current | ~5 mA | With RF on, no data |
| UART Logic Level | 1.8 V | Level-shift if ESP32 (3.3 V) is used directly |
| Power-on Sequence | PWRKEY pulse | Hold PWRKEY low for ≥500 ms |

> ⚠️ **Voltage Warning:** The C16QS UART pins operate at **1.8 V logic**. Connecting 3.3 V ESP32 UART directly without a level shifter may damage the module. Use a bidirectional level-shift IC (e.g., TXS0102 or similar) or the official EVK USB serial port which handles level conversion internally.

---

## 3. ESP32 ↔ Cavli C16QS Interfacing

### 3.1 Required Hardware

- ESP32 development board (ESP32-DevKitC, WROOM-32, or similar)
- Cavli C16QS module or EVK (Evaluation Kit)
- Activated nano/micro SIM card (with data plan — e.g., Airtel)
- Antenna: LTE main + diversity antennas connected to U.FL connectors
- 1.8 V ↔ 3.3 V bidirectional level shifter (if not using EVK)
- Stable 3.8 V power supply with ≥2 A capability
- USB-to-UART bridge (CP2102/CH340) for serial debugging
- Jumper wires

### 3.2 UART Wiring Diagram

```
ESP32                Level Shifter           Cavli C16QS
GPIO17 (TX)  ──────────────────────────→   UART RX
GPIO16 (RX)  ←──────────────────────────   UART TX
GND          ────────────────────────────   GND
3.3 V        ──────────────────────────→   VCC (3.8 V)
```

> ℹ️ **TX/RX Crossing is Mandatory:** The UART lines must cross: ESP32 TX → Module RX, and Module TX → ESP32 RX. TX-to-TX or RX-to-RX connections will produce no communication. Always verify GND is shared between all devices.

### 3.3 Connection Summary Table

| ESP32 Pin | Direction | C16QS Signal | Description |
|---|---|---|---|
| `GPIO17 (UART2_TX)` | → | RXD | ESP32 transmits AT commands & PPP frames |
| `GPIO16 (UART2_RX)` | ← | TXD | ESP32 receives module responses & PPP data |
| `GND` | — | GND | Common ground reference |
| `EN / RESET` | → | RESET_N | Optional module reset line (active low) |

### 3.4 UART Configuration (ESP-IDF)

The firmware configures UART2 with these exact parameters — matching the C16QS default serial settings:

| Parameter | Value |
|---|---|
| Baud Rate | `115200` |
| Data Bits | `8` |
| Parity | `None` |
| Stop Bits | `1` |
| Flow Control | `Disabled` |
| RX Buffer | `4096 bytes` |
| TX Buffer | `4096 bytes` |

### 3.5 Module Initialization Flow

```
Power ON — Hold PWRKEY ≥500 ms
        ↓
Wait for boot (~3–5 seconds)
        ↓
Send AT → expect OK
        ↓
Send ATE0 — disable echo
        ↓
Send AT+CPIN? → expect +CPIN: READY
        ↓
Send AT+CFUN=1 — enable full RF
        ↓
Poll registration → AT+CREG? / AT+CEREG?
        ↓
Module Ready for Data / PPP
```

---

## 4. AT Commands

### 4.1 AT Command Fundamentals

AT commands are ASCII text instructions originally designed for Hayes-compatible modems and standardized by ITU-T V.25ter and 3GPP TS 27.007. Every command begins with the prefix `AT` (Attention) and is terminated by a carriage return (`\r`). The module responds with result codes like `OK` or `ERROR`.

| Command Form | Example | Purpose |
|---|---|---|
| Basic test | `AT` | Verify module is alive |
| Set | `AT+CFUN=1` | Write a parameter value |
| Read | `AT+CREG?` | Read current parameter |
| Test range | `AT+CFUN=?` | Query supported values |

### 4.2 Complete AT Command Sequence (PPP Mode)

The following is the exact command sequence used by the firmware before entering PPP mode:

| # | Command | Expected Response | Purpose |
|---|---|---|---|
| 1 | `AT` | `OK` | Basic connectivity test |
| 2 | `ATE0` | `OK` | Disable command echo |
| 3 | `AT+CMEE=2` | `OK` | Enable verbose error messages |
| 4 | `AT+CPIN?` | `+CPIN: READY` | Verify SIM is unlocked |
| 5 | `AT+CFUN=1` | `OK` | Enable full radio functionality |
| 6 | `AT+COPS=0` | `OK` | Auto-select network operator |
| 7 | `AT+CREG=1` | `OK` | Enable circuit-switched registration URC |
| 8 | `AT+CEREG=1` | `OK` | Enable LTE/EPS registration URC |
| 9 | `AT+CSQ` | `+CSQ: 23,0` | Read signal quality (RSSI) |
| 10 | `AT+CREG?` | `+CREG: 1,1` or `1,5` | Check circuit registration (1=home, 5=roaming) |
| 11 | `AT+CEREG?` | `+CEREG: 1,1` | Check LTE registration |
| 12 | `AT+CGATT?` | `+CGATT: 1` | Verify packet domain attach |
| 13 | `AT+CGDCONT=1,"IP","airtelgprs.com"` | `OK` | Configure PDP context with APN |
| 14 | `AT+CGDCONT?` | `+CGDCONT: 1,"IP","airtelgprs.com",...` | Verify APN configuration |
| 15 | `AT+CGACT=1,1` | `OK` | Activate PDP context |
| 16 | `AT+CGACT?` | `+CGACT: 1,1` | Verify PDP activation |
| 17 | `AT+PPPSTART` | `CONNECT` / `+PPPSTART` | Switch UART to binary PPP mode |

> 🚨 **After AT+PPPSTART — Do Not Send AT Commands!** Once `AT+PPPSTART` succeeds and returns `CONNECT`, the UART transitions from ASCII text mode to binary PPP data mode. Any AT command sent at this point will corrupt the PPP session. The firmware logs: *"UART is now PPP binary mode. Do not send more AT commands."*

### 4.3 Serial Monitor Output Example

```
I (1230) CAVLI_PPP: ESP32 + Cavli C16QS AT+PPPSTART + PPPoS + HTTP POST
I (1232) CAVLI_PPP: Preparing Cavli modem for PPP mode
I (1234) CAVLI_PPP: MODEM >>> AT
AT
OK
I (1244) CAVLI_PPP: MODEM command OK
I (1246) CAVLI_PPP: MODEM >>> ATE0
ATE0
OK
I (1260) CAVLI_PPP: MODEM command OK
I (1262) CAVLI_PPP: MODEM >>> AT+CMEE=2
OK
I (1272) CAVLI_PPP: MODEM command OK
I (1274) CAVLI_PPP: MODEM >>> AT+CPIN?
+CPIN: READY
OK
I (1290) CAVLI_PPP: MODEM command OK
I (1292) CAVLI_PPP: MODEM >>> AT+CFUN=1
OK
I (1300) CAVLI_PPP: MODEM command OK
W (45000) CAVLI_PPP: Network not ready. Retrying in 5 seconds...
I (50200) CAVLI_PPP: Network ready
I (50210) CAVLI_PPP: MODEM >>> AT+PPPSTART
CONNECT
I (65000) CAVLI_PPP: PPP mode started
I (65001) CAVLI_PPP: UART is now PPP binary mode. Do not send more AT commands.
I (65200) CAVLI_PPP: Starting lwIP PPPoS
I (65205) CAVLI_PPP: PPP RX task started
I (65210) CAVLI_PPP: Starting PPP negotiation
I (67500) CAVLI_PPP: PPP CONNECTED
I (67502) CAVLI_PPP: PPP IP  : 100.95.4.168
I (67503) CAVLI_PPP: PPP GW  : 10.64.64.64
I (67504) CAVLI_PPP: PPP MASK: 255.255.255.255
I (67506) CAVLI_PPP: DNS0: 8.8.8.8
I (67507) CAVLI_PPP: DNS1: 1.1.1.1
```

---

## 5. Ping Requests & PPP Connectivity Testing

### 5.1 How Ping Works Over PPP

A cellular ping does not use the standard OS-level ping utility. Instead, ICMP Echo Request packets are manually constructed and encapsulated within PPP frames — the entire stack is:

```
ICMP Echo Request (Type 8, Code 0)
        ↓ encapsulated in
IPv4 Packet (Protocol 0x01 = ICMP)
        ↓ wrapped in
PPP Frame (Protocol 0x0021 = IPv4)
        ↓ byte-escaped + FCS added
Raw Bytes over UART
```

### 5.2 PPP Frame Structure

| Byte(s) | Value | Field | Description |
|---|---|---|---|
| `0x7E` | `7E` | Flag | Start-of-frame delimiter |
| `0xFF` | `FF` | Address | All-stations broadcast address |
| `0x03` | `03` | Control | Unnumbered Information (UI) frame |
| `[2]` | e.g. `C0 21` | Protocol | LCP / IPCP / IPv4 identifier |
| variable | — | Information | LCP/IPCP options or IPv4 payload |
| `[2]` | — | FCS | CRC-16 HDLC checksum (little-endian) |
| `0x7E` | `7E` | Flag | End-of-frame delimiter |

### 5.3 PPP Protocol Values

| Protocol | Hex | Purpose |
|---|---|---|
| LCP | `C0 21` | Link Control — negotiate link parameters, keepalive, teardown |
| PAP | `C0 23` | Password Authentication (if requested by server) |
| CHAP | `C2 23` | Challenge Handshake Auth (if requested by server) |
| IPCP | `80 21` | IP Control — negotiate IPv4 address, DNS |
| IPv4 | `00 21` | Actual IPv4 data packets (ICMP, TCP, UDP) |
| IPv6CP | `80 57` | IPv6 Control (not needed for IPv4 ping) |

### 5.4 PPP Negotiation Sequence

1. **LCP Configure-Request** — Host and modem exchange LCP Configure-Requests negotiating MRU (Maximum Receive Unit), Magic Number, and compression options.
2. **LCP Configure-Ack** — Each side acknowledges the other's options. LCP is now **OPEN**.
3. **IPCP Configure-Request** — Host sends IPCP request with IP `0.0.0.0` and DNS `0.0.0.0` to request addresses from the server.
4. **IPCP Configure-Nak** — Server replies with suggested IP and DNS addresses.
5. **IPCP Configure-Request (retry)** — Host re-sends with the suggested IP/DNS values.
6. **IPCP Configure-Ack** — Server accepts. IPCP is now **OPEN**. Host has an IP address.
7. **IPv4 / ICMP Traffic** — With IPCP open, the host can now send IPv4 packets (including ICMP ping) encapsulated in PPP frames.

### 5.5 Python Ping Packet Generator

The `cavli_generateppp_packets.py` tool can construct ICMP Echo Request packets for manual testing. Example usage:

```python
# Build an ICMP Echo Request inside a PPP frame
# src_ip: your assigned IP from IPCP negotiation
# dst_ip: ping target (e.g. 8.8.8.8 = Google DNS)
pkt = build_icmp_echo(
    src_ip="100.95.4.168",   # Your IPCP-assigned IP
    dst_ip="8.8.8.8",        # Target (Google DNS)
    seq=1,
    payload_str="Cavli-PPP-Test"
)
# pkt is raw bytes — send over UART as-is (no ASCII encoding)
print(" ".join(f"{b:02X}" for b in pkt))
```

### 5.6 Interpreting a Successful Ping Response

A valid ICMP Echo Reply from `8.8.8.8` will arrive as a PPP frame with:

- PPP Protocol: `00 21` (IPv4)
- IPv4 Source: `8.8.8.8`, Destination: your IPCP IP
- IPv4 Protocol byte: `01` (ICMP)
- ICMP Type: `00` (Echo Reply), Code: `00`
- ICMP Identifier and Sequence match the sent Echo Request

---

## 6. Data Communication

### 6.1 HTTP POST via PPPoS (Project Implementation)

Once PPPoS establishes an IP connection, the ESP32 uses standard lwIP BSD socket APIs — exactly like any TCP/IP-connected device. The firmware sends HTTP POST requests to a webhook endpoint:

```c
// 1. DNS Resolution
struct addrinfo hints = { .ai_family=AF_INET, .ai_socktype=SOCK_STREAM };
struct addrinfo *res;
getaddrinfo("webhook.site", NULL, &hints, &res);

// 2. Create TCP socket
int sock = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);

// 3. Set timeouts (15 seconds)
struct timeval timeout = { .tv_sec=15, .tv_usec=0 };
setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));

// 4. Connect to server
connect(sock, res->ai_addr, res->ai_addrlen);

// 5. Build and send HTTP POST
snprintf(request, sizeof(request),
    "POST /path HTTP/1.1\r\n"
    "Host: webhook.site\r\n"
    "Content-Type: text/plain\r\n"
    "Content-Length: %u\r\n"
    "Connection: close\r\n\r\n%s",
    strlen(body), body);
send(sock, request, strlen(request), 0);

// 6. Read response
recv(sock, rx, sizeof(rx)-1, 0);
close(sock);
```

### 6.2 HTTP GET Request Example

```c
// Resolve hostname
getaddrinfo("api.example.com", NULL, &hints, &res);
int sock = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
connect(sock, res->ai_addr, res->ai_addrlen);

// Build GET request
snprintf(request, sizeof(request),
    "GET /data/sensors HTTP/1.1\r\n"
    "Host: api.example.com\r\n"
    "User-Agent: ESP32-Cavli/1.0\r\n"
    "Connection: close\r\n\r\n");

send(sock, request, strlen(request), 0);

// Read chunked response
while ((len = recv(sock, rx, sizeof(rx)-1, 0)) > 0) {
    rx[len] = '\0';
    printf("%s", rx);
}
close(sock);
```

### 6.3 TCP Socket Communication

The same BSD socket API supports raw TCP connections to custom servers — useful for IoT telemetry protocols, MQTT brokers, or proprietary cloud APIs:

```c
// After PPPoS connected, send JSON sensor data
const char *json = "{\"temp\":25.4,\"hum\":62.1,\"device\":\"ESP32-001\"}";
int sock = socket(AF_INET, SOCK_STREAM, 0);
// connect to MQTT broker or custom TCP server on port 1883 / custom port
struct sockaddr_in addr = { .sin_family=AF_INET, .sin_port=htons(1883) };
inet_pton(AF_INET, "192.168.1.100", &addr.sin_addr);
connect(sock, (struct sockaddr*)&addr, sizeof(addr));
send(sock, json, strlen(json), 0);
close(sock);
```

### 6.4 UDP Communication

```c
int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
struct sockaddr_in dest = {
    .sin_family = AF_INET,
    .sin_port   = htons(5005)
};
inet_pton(AF_INET, "203.0.113.10", &dest.sin_addr);
const char *msg = "ESP32-Cavli:ALIVE";
sendto(sock, msg, strlen(msg), 0, (struct sockaddr*)&dest, sizeof(dest));
close(sock);
```

### 6.5 Serial Monitor — HTTP POST Output

```
I (67800) CAVLI_PPP: Resolving webhook.site to IP
I (68200) CAVLI_PPP: webhook.site resolved IP: 34.202.18.214
I (68202) CAVLI_PPP: Connecting to IP 34.202.18.214:80
I (68850) CAVLI_PPP: TCP connected
I (68852) CAVLI_PPP: Sending HTTP POST

---------------- HTTP REQUEST ----------------
POST /a68f971c-ad3a-47aa-8b92-4879e7cdebbf HTTP/1.1
Host: webhook.site
User-Agent: ESP32-Cavli-PPPoS/1.0
Content-Type: text/plain
Content-Length: 5
Connection: close

shuva
----------------------------------------------
I (69400) CAVLI_PPP: HTTP request sent. Reading response...

---------------- HTTP RESPONSE ---------------
HTTP/1.1 200 OK
Content-Type: text/plain
...
----------------------------------------------
I (69800) CAVLI_PPP: HTTP POST done
I (69802) CAVLI_PPP: First HTTP POST successful
```

---

## 7. Python Utility Tools

### 7.1 cavli_generateppp_packets.py — PPP Packet Builder & Decoder (Tkinter GUI)

A standalone Python/Tkinter GUI tool for building, inspecting, and decoding PPP packets. Designed for engineers who need to manually test PPP sessions using a USB-to-TTL serial adapter and a serial debug assistant application, or for studying PPP protocol internals.

**Features:**
- Build LCP Configure-Request, Configure-Ack, Terminate-Request, Echo-Request packets
- Build PAP Authentication Request (username/password)
- Build IPCP Configure-Request and Configure-Ack with IP/DNS fields
- Build ICMP Echo Request (Ping) packets wrapped in IPv4 in PPP
- Paste raw hex from serial terminal → decode protocol, options, FCS validity
- Next-Step Advisor — analyzes decoded packet and suggests what to send next
- PPP state machine tracker and reset

**Installation:**

```bash
pip install tkinter  # Usually included with Python
python cavli_generateppp_packets.py
```

**GUI Usage:**

| Tab | Controls | Output |
|---|---|---|
| LCP | MRU (default 1500), Magic Number, packet type | Hex bytes of PPP-framed LCP packet |
| PAP | Username (`airtelgprs.com`), Password | PAP Auth-Request frame bytes |
| IPCP | Requested IP (`0.0.0.0`), DNS, packet type | IPCP Configure-Request/Ack frame |
| ICMP | Source IP, Dest IP (`8.8.8.8`), Sequence, Payload text | Full PPP-wrapped ICMP ping frame |
| Decoder | Paste hex from serial terminal | Decoded protocol, fields, FCS status, advisor tip |

---

### 7.2 cavli_ppp_gui.py — Live PPP Serial Workbench (Full Protocol Stack)

A real-time PPP client GUI that connects to the Cavli C16QS over a COM/serial port and conducts the full PPP negotiation — LCP, IPCP — automatically. Useful for diagnosing PPP sessions without embedded firmware, or for testing modem behavior from a PC.

**Features:**
- Selectable COM port and baud rate with live port scan
- Automatic LCP negotiation (Configure-Request, Ack, Echo-Reply handling)
- Automatic IPCP negotiation (handles Nak → retry with suggested IP)
- Live packet log with color-coded protocol labels
- Manual send panel for custom hex payloads
- IP/DNS status display updated in real-time

**Installation:**

```bash
pip install pyserial
python cavli_ppp_gui.py
```

**Workflow:**
1. Select COM port and baud rate (115200)
2. Click **Open Port**
3. Manually send AT commands via the AT console tab until `AT+PPPSTART` succeeds
4. Switch to PPP mode — the tool auto-negotiates LCP and IPCP
5. Observe IP assignment and DNS in the status panel

---

### 7.3 fetch_gnss.py — GNSS / GPS Monitor (NMEA Parser with Map Integration)

A live GNSS monitoring GUI that reads NMEA sentences from the Cavli C16QS GNSS output port, parses GPS/GLONASS fix data, and can open the device's current location directly in Google Maps.

**Features:**
- Auto-scans all available COM ports
- Sends `AT+CGPS=1` and `AT+GPSPORT=1` to enable GNSS output
- Parses `$GNRMC` (fix, lat/lon, time) and `$GNGGA` (satellites, altitude)
- Displays: Fix status, Latitude, Longitude, Altitude, Satellite count, UTC Time
- Live NMEA sentence log with scrolling
- One-click Google Maps integration (opens browser at current coordinates)

**Installation:**

```bash
pip install pyserial pynmea2
python fetch_gnss.py
```

**AT Commands Sent Automatically:**

```
AT          ← Verify module communication
AT+CGPS=1   ← Enable GNSS engine
AT+GPSPORT=1← Route NMEA output to serial port
```

---

### 7.4 ppp_packet_decoder_gui.py — Standalone PPP Frame Decoder

A focused decoder tool — paste any raw PPP hex dump (space/colon-separated or raw) and get a full dissection: FCS validation, protocol identification, LCP/IPCP option parsing, ICMP type decoding, and IP header breakdown.

**Installation:**

```bash
python ppp_packet_decoder_gui.py   # No extra dependencies needed
```

---

### 7.5 Web-Based Tools

| Tool | Description |
|---|---|
| `cavli-ppp-workbench.html` | Browser-based PPP packet builder and decoder — no installation required. Open in any modern browser. |
| `cavli_ppp_terminal.html` | Web serial terminal for AT command interaction with the C16QS module (requires Chrome with Web Serial API). |

---

## 8. Main ESP32 Project Documentation

### 8.1 Project Folder Structure

```
esp32_cavli_ppppos/
├── main/
│   ├── CMakeLists.txt          ← Component registration
│   └── main.c                  ← Full firmware source
├── CMakeLists.txt              ← Project root build file
├── sdkconfig                   ← menuconfig settings
└── README.md
```

### 8.2 CMakeLists.txt (Component)

```cmake
idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_timer        # High-resolution timer for get_ms()
        esp_driver_uart  # UART driver APIs
        esp_netif        # Network interface abstraction
        esp_event        # Event loop
        lwip             # TCP/IP stack + PPPoS
)
```

### 8.3 Firmware Architecture Block Diagram

```
app_main()
        ↓
esp_netif_init() + esp_event_loop_create_default()
        ↓
modem_uart_init() — configure UART2 pins 16/17
        ↓
modem_enter_ppp_mode() — AT command sequence
        ↓
start_pppos() — create PPPoS session + RX task
        ↓ PPP Connected
http_post_to_webhook_ip() — DNS → TCP → HTTP POST
        ↓
Loop: repeat HTTP POST every 30 seconds
```

### 8.4 Key Defines

| Define | Value | Description |
|---|---|---|
| `MODEM_UART_NUM` | `UART_NUM_2` | Hardware UART port for modem |
| `MODEM_TX_PIN` | `17` | ESP32 TX → Module RX |
| `MODEM_RX_PIN` | `16` | ESP32 RX ← Module TX |
| `MODEM_BAUD` | `115200` | UART baud rate |
| `MODEM_APN` | `"airtelgprs.com"` | Carrier APN string |
| `MODEM_NETWORK_TIMEOUT_MS` | `180000` (3 min) | Registration wait timeout |
| `PPP_CONNECT_TIMEOUT_MS` | `60000` (1 min) | PPPoS connect timeout |
| `WEBHOOK_HOST` | `"webhook.site"` | HTTP POST destination |
| `POST_BODY` | `"shuva"` | HTTP POST body payload |

---

## 9. ESP32 Source Code Walkthrough

### 9.1 Includes & Global State

```c
#include "freertos/FreeRTOS.h"       // FreeRTOS kernel
#include "freertos/task.h"            // xTaskCreate, vTaskDelay
#include "freertos/event_groups.h"    // xEventGroupCreate, xEventGroupWaitBits
#include "esp_log.h"                  // ESP_LOGI, ESP_LOGE, ESP_LOGW
#include "esp_timer.h"                // esp_timer_get_time() for get_ms()
#include "driver/uart.h"              // UART driver (uart_write_bytes, uart_read_bytes)
#include "lwip/dns.h"                 // dns_setserver, dns_getserver
#include "lwip/sockets.h"             // BSD socket API
#include "netif/ppp/pppos.h"          // PPPoS (PPP over Serial) library
#include "netif/ppp/pppapi.h"         // ppp_connect, ppp_set_default

static ppp_pcb *g_ppp = NULL;               // PPP control block (lwIP)
static struct netif g_ppp_netif;            // Network interface descriptor
static EventGroupHandle_t g_ppp_event_group; // Signal PPP connected/failed
```

The PPP control block (`g_ppp`) is the lwIP handle for the PPPoS session. The event group allows the main task to block until PPP is either connected (`PPP_CONNECTED_BIT`) or failed (`PPP_FAILED_BIT`).

### 9.2 UART Initialization

```c
static void modem_uart_init(void)
{
    uart_config_t uart_config = {
        .baud_rate  = MODEM_BAUD,          // 115200
        .data_bits  = UART_DATA_8_BITS,    // 8-bit data
        .parity     = UART_PARITY_DISABLE, // No parity
        .stop_bits  = UART_STOP_BITS_1,    // 1 stop bit
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE, // No RTS/CTS
#if ESP_IDF_VERSION_MAJOR >= 5
        .source_clk = UART_SCLK_DEFAULT,   // Auto clock source (IDF v5+)
#endif
    };
    // Install UART driver with 4 KB RX and TX buffers
    ESP_ERROR_CHECK(uart_driver_install(MODEM_UART_NUM, 4096, 4096, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(MODEM_UART_NUM, &uart_config));
    // Map UART2 to GPIO16 (RX) and GPIO17 (TX)
    ESP_ERROR_CHECK(uart_set_pin(MODEM_UART_NUM, MODEM_TX_PIN, MODEM_RX_PIN,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(uart_flush_input(MODEM_UART_NUM)); // Clear stale data
}
```

### 9.3 AT Command Engine

```c
static bool modem_send_at(const char *cmd, char *resp, size_t resp_size, uint32_t timeout_ms)
{
    modem_flush_rx(50);                              // Discard any stale bytes
    ESP_LOGI(TAG, "MODEM >>> %s", cmd);
    uart_write_bytes(MODEM_UART_NUM, cmd, strlen(cmd)); // Send command
    uart_write_bytes(MODEM_UART_NUM, "\r", 1);          // Send CR terminator
    uart_wait_tx_done(MODEM_UART_NUM, pdMS_TO_TICKS(1000)); // Wait for TX complete

    // modem_wait_response: reads bytes until "OK" or "ERROR" is seen in buffer
    bool got_token = modem_wait_response(resp, resp_size, timeout_ms,
                                         "OK", "ERROR", NULL);
    if (!got_token) {
        ESP_LOGE(TAG, "Timeout after command: %s", cmd);
        return false;
    }
    return (resp && strstr(resp, "OK")); // true only if response contains "OK"
}
```

### 9.4 Network Registration Polling

```c
static bool modem_wait_network(uint32_t timeout_ms)
{
    // Polls every MODEM_NETWORK_RETRY_MS (5s) until timeout (3 min)
    while ((get_ms() - start) < timeout_ms) {
        modem_send_at("AT+CSQ",    resp, sizeof(resp), 3000); // Signal strength
        modem_send_at("AT+CREG?",  resp, sizeof(resp), 3000);
        registered_ok = modem_response_has_reg(resp);          // Check ,1 or ,5
        modem_send_at("AT+CEREG?", resp, sizeof(resp), 3000);
        registered_ok |= modem_response_has_reg(resp);
        modem_send_at("AT+CGATT?", resp, sizeof(resp), 3000);
        attached_ok = (strstr(resp, "+CGATT: 1") != NULL);

        if (registered_ok && attached_ok) return true;         // Network ready!

        if (registered_ok && !attached_ok)
            modem_send_at("AT+CGATT=1", resp, sizeof(resp), 15000); // Force attach

        vTaskDelay(pdMS_TO_TICKS(MODEM_NETWORK_RETRY_MS));     // Wait 5 s
    }
    return false; // Timeout
}
```

### 9.5 PPPoS Callbacks

```c
// Called by lwIP when it has PPP data to send — we write it to UART
static u32_t ppp_output_cb(ppp_pcb *pcb, const void *data, u32_t len, void *ctx)
{
    return (u32_t)uart_write_bytes(MODEM_UART_NUM, data, len);
}

// Called by lwIP when PPP connection state changes
static void ppp_status_cb(ppp_pcb *pcb, int err_code, void *ctx)
{
    switch (err_code) {
    case PPPERR_NONE:  // Successfully connected
        ESP_LOGI(TAG, "PPP IP : %s", ip4addr_ntoa(netif_ip4_addr(ppp_netif(pcb))));
        // Override peer DNS with reliable Google/Cloudflare DNS
        IP_ADDR4(&dns1, 8, 8, 8, 8);   // Google DNS
        IP_ADDR4(&dns2, 1, 1, 1, 1);   // Cloudflare DNS
        dns_setserver(0, &dns1);
        dns_setserver(1, &dns2);
        xEventGroupSetBits(g_ppp_event_group, PPP_CONNECTED_BIT);
        break;
    case PPPERR_CONNECT:
    case PPPERR_AUTHFAIL:
    case PPPERR_PROTOCOL:
        xEventGroupSetBits(g_ppp_event_group, PPP_FAILED_BIT);
        break;
    }
}
```

### 9.6 PPP RX Task

```c
// Dedicated FreeRTOS task at priority 18 — reads raw bytes from UART
// and feeds them into lwIP's PPPoS parser (pppos_input_tcpip)
static void ppp_rx_task(void *arg)
{
    uint8_t rx_buf[256];
    while (1) {
        int len = uart_read_bytes(MODEM_UART_NUM, rx_buf, sizeof(rx_buf),
                                  pdMS_TO_TICKS(20)); // 20ms timeout
        if (len > 0 && g_ppp != NULL)
            pppos_input_tcpip(g_ppp, rx_buf, len); // Hand to lwIP PPPoS engine
    }
}
```

This task runs continuously at a high priority (18) to ensure no incoming PPP bytes are missed. `pppos_input_tcpip()` is thread-safe and posts the received data to the lwIP core for processing via its internal task queue.

### 9.7 app_main() — Entry Point

```c
void app_main(void)
{
    // 1. Initialize network interface layer and event loop
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    // 2. Initialize UART2 for modem communication
    modem_uart_init();

    // 3. Run AT command sequence → configure APN → AT+PPPSTART
    if (!modem_enter_ppp_mode()) {
        ESP_LOGE(TAG, "Failed to enter PPP mode"); return;
    }

    // 4. Create PPPoS session + RX task → wait for IP assignment
    if (!start_pppos()) {
        ESP_LOGE(TAG, "Failed to start PPPoS"); return;
    }

    // 5. With IP assigned, send HTTP POST over the cellular link
    if (!http_post_to_webhook_ip()) {
        ESP_LOGE(TAG, "First HTTP POST failed"); return;
    }

    // 6. Repeat HTTP POST every 30 seconds indefinitely
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(30000));
        http_post_to_webhook_ip();
    }
}
```

---

## 10. Python Source Code Walkthrough

### 10.1 PPP Frame Construction (cavli_generateppp_packets.py)

#### CRC-16 HDLC FCS

```python
def fcs16(data: bytes) -> int:
    """CRC-16 HDLC FCS — the PPP Frame Check Sequence.
    
    Computed over: FF 03 <protocol> <information> (before byte-escaping)
    Appended little-endian to the frame body before the closing 7E flag.
    """
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408  # Reversed polynomial for HDLC
            else:
                crc >>= 1
    return crc ^ 0xFFFF  # Final XOR with 0xFFFF
```

#### Byte Escaping

```python
def ppp_escape_byte(b: int) -> bytes:
    """PPP byte escaping rules:
    - 0x7E (flag) becomes 7D 5E
    - 0x7D (escape) becomes 7D 5D
    - Any byte < 0x20 (control chars) becomes 7D (byte XOR 0x20)
    - All other bytes are sent as-is
    """
    if b == PPP_FLAG or b == PPP_ESCAPE or b < 0x20:
        return bytes([PPP_ESCAPE, b ^ 0x20])
    return bytes([b])

def ppp_frame(proto: int, payload: bytes) -> bytes:
    """Build a complete PPP frame with HDLC framing and FCS."""
    inner = bytes([0xFF, 0x03]) + struct.pack(">H", proto) + payload
    crc   = fcs16(inner)
    raw   = inner + struct.pack("<H", crc)   # FCS appended little-endian
    escaped = bytearray([PPP_FLAG])           # Opening 7E
    for b in raw:
        escaped.extend(ppp_escape_byte(b))    # Escape body + FCS
    escaped.append(PPP_FLAG)                  # Closing 7E
    return bytes(escaped)
```

#### LCP Configure-Request Builder

```python
def build_lcp_configure_request(magic=0x01234567, mru=1500):
    # Option 1: MRU (Max Receive Unit) — 4 bytes: type(1) len(1) value(2)
    opts  = struct.pack(">BBH", 1, 4, mru)
    # Option 5: Magic Number — 6 bytes: type(1) len(1) value(4)
    opts += struct.pack(">BBI", 5, 6, magic)
    # Option 7: Protocol-Field-Compression — 2 bytes
    opts += struct.pack(">BB", 7, 2)
    # Option 8: Address-Control-Field-Compression — 2 bytes
    opts += struct.pack(">BB", 8, 2)

    # LCP header: code(1)=1(Conf-Req) id(1) length(2)
    payload = struct.pack(">BBH", 1, next_id(), 4 + len(opts)) + opts
    return ppp_frame(PROTO_LCP, payload)  # Wrap in PPP frame with 0xC021
```

#### ICMP Echo Request Builder

```python
def build_icmp_echo(src_ip, dst_ip, seq=1, payload_str="Cavli-PPP"):
    data = payload_str.encode()

    # ICMP header: type=8(Echo Req), code=0, checksum=0(placeholder), id=1, seq
    icmp_hdr = struct.pack(">BBHHH", 8, 0, 0, 1, seq) + data
    csum = ip_checksum(icmp_hdr)           # Calculate ICMP checksum
    icmp = struct.pack(">BBHHH", 8, 0, csum, 1, seq) + data  # With real checksum

    src = bytes(map(int, src_ip.split(".")))
    dst = bytes(map(int, dst_ip.split(".")))

    # IPv4 header: version=4, IHL=5, TOS=0, total_len, id, flags, TTL=64, proto=1(ICMP)
    iph  = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20+len(icmp), 1, 0, 64, 1, 0, src, dst)
    csum2 = ip_checksum(iph)               # Calculate IPv4 header checksum
    iph  = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20+len(icmp), 1, 0, 64, 1, csum2, src, dst)

    return ppp_frame(PROTO_IP, iph + icmp) # Wrap IPv4+ICMP in PPP frame (0x0021)
```

### 10.2 GNSS Monitor Architecture (fetch_gnss.py)

```python
def read_loop(self):
    """Background thread: reads NMEA lines from serial port and updates UI."""
    while self.running:
        line = self.ser.readline().decode(errors="ignore").strip()

        if line.startswith("$GNRMC"):          # Recommended Minimum (fix + lat/lon)
            msg = pynmea2.parse(line)
            if msg.status == "A":              # A = Active fix (GPS locked)
                self.update_label("Fix",       "VALID FIX")
                self.update_label("Latitude",  str(msg.latitude))
                self.update_label("Longitude", str(msg.longitude))
                self.update_label("UTC Time",  str(msg.timestamp))
                self.latitude, self.longitude = msg.latitude, msg.longitude
                # Enable the Google Maps button
                self.after(0, lambda: self.map_btn.config(state="normal"))

        elif line.startswith("$GNGGA"):        # Fix data (satellites, altitude)
            msg = pynmea2.parse(line)
            self.update_label("Satellites", str(msg.num_sats))
            self.update_label("Altitude",   f"{msg.altitude} {msg.altitude_units}")
```

---

## 11. Creating a New Project

### 11.1 Install ESP-IDF

**Step 1 — Install prerequisites (Ubuntu/Debian):**

```bash
sudo apt install git wget flex bison gperf python3 python3-venv \
     python3-pip cmake ninja-build ccache libffi-dev libssl-dev dfu-util
```

**Step 2 — Clone ESP-IDF:**

```bash
git clone -b v5.3 --recursive https://github.com/espressif/esp-idf.git ~/esp/esp-idf
cd ~/esp/esp-idf && ./install.sh esp32
. ~/esp/esp-idf/export.sh   # Add IDF tools to PATH
```

**Step 3 — Create a new project:**

```bash
cp -r $IDF_PATH/examples/get-started/hello_world ~/my_cavli_project
cd ~/my_cavli_project
idf.py set-target esp32
```

**Step 4 — Add required CMake dependencies:**

Edit `main/CMakeLists.txt` to include the required components:

```cmake
idf_component_register(SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES esp_timer esp_driver_uart esp_netif esp_event lwip)
```

**Step 5 — Enable PPPoS in menuconfig:**

```bash
idf.py menuconfig
# Navigate to:
# Component config → LWIP → Enable PPP support → [*] Enable PPPoS support
```

**Step 6 — Copy main.c from this project and customize APN:**

```c
#define MODEM_APN "your.apn.here"     // Change to your carrier APN
#define WEBHOOK_HOST "your.server.com" // Change to your endpoint
#define WEBHOOK_PATH "/your/path"
#define POST_BODY "your payload"
```

**Step 7 — Build, flash and monitor:**

```bash
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

### 11.2 Required Drivers (Windows)

- **CP210x** — Silicon Labs USB-to-UART (most ESP32 DevKit boards): https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers
- **CH340/CH341** — WCH USB-to-UART (common on clone boards): https://www.wch-ic.com/downloads/CH341SER_EXE.html

### 11.3 Common APN Values by Carrier

| Carrier | APN String | Country |
|---|---|---|
| Airtel India | `airtelgprs.com` | India |
| Jio India | `jionet` | India |
| T-Mobile USA | `fast.t-mobile.com` | USA |
| AT&T USA | `broadband` | USA |
| Vodafone UK | `internet` | UK |
| Hologram IoT | `hologram` | Global |
| Twilio Super SIM | `super` | Global |

---

## 12. Raspberry Pi + Cavli C16QS Integration

### 12.1 Hardware Setup

The Raspberry Pi GPIO header includes dedicated UART pins. Raspberry Pi 4B uses `/dev/ttyAMA0` (hardware UART) for the GPIO UART. The wiring follows the same cross-TX/RX principle:

```
Raspberry Pi 4B         Level Shifter       Cavli C16QS
GPIO14 (TXD0)  ──────────────────────────→  RX
GPIO15 (RXD0)  ←──────────────────────────  TX
Pin 6 (GND)    ────────────────────────────  GND
Pin 2 (5V)     ──────────────────────────→  VCC (3.8V)
```

> ℹ️ **Raspberry Pi UART Note:** On RPi 4B, the primary UART (`/dev/ttyAMA0` / `/dev/serial0`) is mapped to GPIO 14/15. Disable the Bluetooth serial overlay if the hardware UART is being used by Bluetooth.

### 12.2 Raspberry Pi OS — Serial Port Configuration

**Step 1 — Enable UART in /boot/config.txt:**

```bash
sudo nano /boot/config.txt
# Add these lines:
enable_uart=1
dtoverlay=disable-bt       # Disable Bluetooth to free hardware UART
```

**Step 2 — Disable serial console on UART:**

```bash
sudo raspi-config
# → Interface Options → Serial Port
# "Would you like a login shell..." → No
# "Would you like serial port hardware enabled..." → Yes
sudo reboot
```

**Step 3 — Install required packages:**

```bash
sudo apt update && sudo apt install -y ppp minicom python3-serial
```

**Step 4 — Test serial communication with minicom:**

```bash
minicom -D /dev/ttyAMA0 -b 115200
# In minicom, type: AT  → should see: OK
# Type: AT+CPIN?  → should see: +CPIN: READY
# Exit: Ctrl+A, then X
```

### 12.3 PPP Connection via pppd

**Step 1 — Create a chat script to initialize the modem:**

```bash
sudo nano /etc/ppp/peers/cavli-ppp

# Contents of the peer file:
/dev/ttyAMA0
115200
defaultroute
persist
noauth
debug
usepeerdns
connect '/usr/sbin/chat -v -f /etc/ppp/chat-cavli'
```

**Step 2 — Create the chat script:**

```bash
sudo nano /etc/ppp/chat-cavli

# Contents:
ABORT "BUSY"
ABORT "NO CARRIER"
ABORT "ERROR"
TIMEOUT 30
"" AT
OK ATE0
OK AT+CMEE=2
OK AT+CPIN?
READY AT+CFUN=1
OK AT+COPS=0
OK \dAT+CREG=1
OK AT+CEREG=1
OK \d\d\d\d\d\dAT+CGDCONT=1,"IP","airtelgprs.com"
OK AT+CGACT=1,1
OK AT+PPPSTART
CONNECT ""
```

**Step 3 — Start PPP connection:**

```bash
sudo pon cavli-ppp    # Start the PPP connection
# Monitor: tail -f /var/log/syslog | grep pppd
# Or: ifconfig ppp0   → shows assigned IP from IPCP
```

**Step 4 — Verify internet connectivity:**

```bash
ifconfig ppp0               # Check PPP interface IP
ping -I ppp0 8.8.8.8 -c 4  # Ping through PPP interface
curl --interface ppp0 https://ifconfig.me  # Get external IP
poff cavli-ppp              # Disconnect when done
```

### 12.4 Python Script on Raspberry Pi

```python
import serial, time

def send_at(ser, cmd, wait=1):
    ser.write((cmd + "\r\n").encode())
    time.sleep(wait)
    return ser.read_all().decode(errors="ignore")

# Open Raspberry Pi hardware UART
with serial.Serial("/dev/ttyAMA0", 115200, timeout=2) as ser:
    print(send_at(ser, "AT"))          # → OK
    print(send_at(ser, "ATE0"))        # → OK
    print(send_at(ser, "AT+CPIN?"))    # → +CPIN: READY
    print(send_at(ser, "AT+CSQ"))      # → +CSQ: 23,0
    print(send_at(ser, "AT+CEREG?"))   # → +CEREG: 1,1
    print(send_at(ser, "AT+CGATT?"))   # → +CGATT: 1
```

### 12.5 Raspberry Pi GNSS with fetch_gnss.py

```bash
pip3 install pyserial pynmea2
python3 fetch_gnss.py
# Select /dev/ttyAMA0 (or /dev/ttyUSB0 if using USB adapter)
# Click OPEN PORT → START GNSS
# Wait for GNSS fix (may take 1-5 minutes outdoors with clear sky view)
```

---

## 13. Troubleshooting Guide

### Module not detected — `AT` has no response

**Causes & Solutions:**
- **Wrong COM port** — Check Device Manager (Windows) or `ls /dev/tty*` (Linux) for the correct port
- **TX/RX not crossed** — Swap the TX and RX connections
- **Wrong baud rate** — Try 9600, 57600, 115200 in sequence
- **No common GND** — Verify GND is shared between ESP32/Pi and module
- **Module not powered** — Check VCC and PWRKEY boot sequence
- **Port still in PPP mode** — Power cycle the module to reset to AT mode
- **Voltage mismatch** — Ensure level shifter is correctly wired (1.8 V ↔ 3.3 V)

### SIM Card Errors — `AT+CPIN?` not READY

- **+CPIN: SIM PIN** — Unlock SIM: `AT+CPIN="1234"` (use your actual PIN)
- **+CPIN: SIM PUK** — SIM is PUK-locked; contact your carrier
- **ERROR / no response** — SIM not inserted, SIM tray not seated, or SIM voltage incompatibility
- **eSIM** — If using internal eSIM, check firmware provisioning documentation

### Network Registration Failures — `CREG/CEREG` never reaches 1 or 5

- **No or poor signal** — Check `AT+CSQ`; values 1–30 indicate signal. 99 means no signal. Attach antenna.
- **SIM not activated** — Verify SIM works in a phone first
- **Band mismatch** — Check `AT+COPS=?` for available operators and supported bands
- **RF disabled** — Send `AT+CFUN=1` to enable full radio
- **Power droop** — Network attach draws peak current; ensure supply can deliver ≥1.5 A
- Status 3 (`+CREG: 1,3`) means registration denied — check SIM and operator compatibility

### CGATT stays 0 / CGACT fails

- Ensure registration is complete first (`CREG`/`CEREG` = 1 or 5)
- Try force-attach: `AT+CGATT=1`
- Verify APN is correct for your carrier (case-sensitive!)
- Check SIM has mobile data enabled (may need to enable in carrier app)
- Wait up to 60 seconds after registration before retrying attach

### AT+PPPSTART fails or times out

- Verify `AT+CGACT?` returns `+CGACT: 1,1` before sending PPPSTART
- PPP must be supported on the AT port in use (some modules use a separate PPP port)
- Check firmware version — older firmware may use a different command
- Ensure UART is at 115200 and no flow control is configured
- Do not send PPP binary data before PPPSTART completes

### PPP negotiation fails — LCP never completes

- **FCS incorrect** — Recalculate CRC-16 HDLC over `FF 03 proto payload` before escaping
- **Byte escaping wrong** — `7E`→`7D 5E`, `7D`→`7D 5D`, bytes <0x20 also need escaping
- **Sending ASCII hex instead of raw bytes** — serial terminal must send raw binary, not text representation
- **Didn't ACK peer LCP** — When modem sends LCP Configure-Request, host must reply with Configure-Ack
- **Authentication required** — Modem may demand PAP/CHAP; check if server sends Configure-Request with Auth option

### PPP connected but HTTP POST fails

- Check DNS is reachable: `ping 8.8.8.8` over ppp interface to rule out DNS issues
- The firmware overrides DNS with `8.8.8.8` and `1.1.1.1` — ensure these aren't blocked by your carrier
- Check socket timeout: increase `SO_RCVTIMEO` for slow cellular links
- Check if target server blocks IoT traffic
- Verify `Content-Length` matches actual body length

### GNSS — No Fix / fetch_gnss.py shows "NO FIX"

- GNSS requires clear sky view — indoor testing rarely works
- Cold start can take 2–10 minutes for initial fix (subsequent starts are faster)
- Verify `AT+CGPS=1` and `AT+GPSPORT=1` responded with `OK`
- Check NMEA data is flowing in the log panel — if empty, check serial port and baud rate
- Ensure GNSS antenna is connected to the correct U.FL connector (usually labeled GNSS/GPS)

### 13.1 Quick Diagnostic Checklist

```
□ AT returns OK
□ ATE0 returns OK
□ AT+CPIN? returns +CPIN: READY
□ AT+CFUN=1 returns OK
□ AT+CSQ shows RSSI 1-30 (not 99)
□ AT+CREG? shows ,1 or ,5
□ AT+CEREG? shows ,1 or ,5
□ AT+CGATT? shows +CGATT: 1
□ AT+CGDCONT=1,"IP","<your-apn>" returns OK
□ AT+CGACT=1,1 returns OK
□ AT+CGACT? shows +CGACT: 1,1
□ AT+PPPSTART returns CONNECT / +PPPSTART
□ [lwIP] PPP CONNECTED log appears
□ IP address assigned (not 0.0.0.0)
□ DNS reachable (8.8.8.8 ping test)
```

---

## 14. AT Command Reference

### 14.1 General Commands

| Command | Description | Response |
|---|---|---|
| `AT` | Module alive test | `OK` |
| `ATE0` | Disable echo | `OK` |
| `ATE1` | Enable echo | `OK` |
| `ATI` | Module identification | Model, revision info |
| `AT+CMEE=2` | Enable verbose errors | `OK` |
| `AT+CGMI` | Manufacturer identification | Cavli |
| `AT+CGMM` | Model identification | C16QS |
| `AT+CGMR` | Firmware revision | Firmware string |
| `AT+CGSN` | IMEI number | 15-digit IMEI |

### 14.2 SIM & Radio Commands

| Command | Description | Key Response Values |
|---|---|---|
| `AT+CPIN?` | SIM status | `READY`, `SIM PIN`, `SIM PUK` |
| `AT+CFUN=1` | Full radio functionality | `OK` |
| `AT+CFUN=0` | Minimum functionality (RF off) | `OK` |
| `AT+CFUN=4` | Airplane mode | `OK` |
| `AT+CSQ` | Signal quality (RSSI, BER) | `+CSQ: 23,0` (0–31, 99=unknown) |
| `AT+COPS=0` | Auto operator selection | `OK` |
| `AT+COPS?` | Current operator | `+COPS: 0,0,"Airtel",7` |
| `AT+CREG?` | Circuit-switched registration | `+CREG: 1,1` (1=home, 5=roaming) |
| `AT+CEREG?` | LTE/EPS registration | `+CEREG: 1,1` |

### 14.3 Packet Data Commands

| Command | Description | Example |
|---|---|---|
| `AT+CGATT?` | Packet attach status | `+CGATT: 1` |
| `AT+CGATT=1` | Force packet attach | `OK` |
| `AT+CGDCONT=1,"IP","apn"` | Configure PDP context | Set APN for context 1 |
| `AT+CGDCONT?` | Read PDP context config | `+CGDCONT: 1,"IP","airtelgprs.com",...,0` |
| `AT+CGACT=1,1` | Activate PDP context 1 | `OK` |
| `AT+CGACT?` | PDP context status | `+CGACT: 1,1` |
| `AT+PPPSTART` | Start PPP mode on UART | `CONNECT` |

### 14.4 GNSS Commands

| Command | Description |
|---|---|
| `AT+CGPS=1` | Enable GNSS engine |
| `AT+CGPS=0` | Disable GNSS engine |
| `AT+CGPS?` | Query GNSS status (`+CGPS: 1,1` = enabled, running) |
| `AT+GPSPORT=1` | Route NMEA output to main serial/UART port |
| `AT+CGPSINF=0` | Query current GPS fix information |

### 14.5 Useful Links & Resources

- [ESP-IDF Official Documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/)
- [ESP32 Technical Reference Manual](https://www.espressif.com/sites/default/files/documentation/esp32_technical_reference_manual_en.pdf)
- [lwIP TCP/IP Stack](https://savannah.nongnu.org/projects/lwip/)
- [RFC 1661 — PPP Standard](https://tools.ietf.org/html/rfc1661)
- [RFC 1662 — PPP in HDLC-like Framing](https://tools.ietf.org/html/rfc1662)
- [RFC 1332 — PPP IPCP](https://tools.ietf.org/html/rfc1332)
- [Cavli Wireless Official Website](https://cavliwireless.com/)

---

> ✅ **You're ready to build!** This guide covers the complete journey from hardware wiring through AT command initialization, PPP/PPPoS cellular data connectivity, HTTP POST, GNSS tracking, Python diagnostic tools, and Raspberry Pi integration. For questions or hardware-specific issues, refer to the Cavli C16QS official AT command manual and the ESP-IDF documentation.
