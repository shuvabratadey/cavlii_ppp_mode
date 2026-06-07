import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from typing import Dict, List, Tuple


SAMPLE_HEX = """0000: 7E FF 03 00 21 45 B8 00 3C 00 00 00 00 74 01 EA
0010: 37 08 08 08 08 64 5F E7 62 00 00 E4 1D C1 6C 00
0020: 1B A5 A5 A5 A5 A5 A5 A5 A5 A5 A5 A5 A5 A5 A5 A5
0030: A5 A5 A5 A5 A5 A5 A5 A5 A5 A5 A5 A5 A5 A5 A5 A5
0040: A5 02 33 7E"""


PPP_PROTOCOLS = {
    0x0021: "IPv4",
    0x0057: "IPv6",
    0x8021: "IPCP",
    0x8057: "IPv6CP",
    0xC021: "LCP",
    0xC023: "PAP",
    0xC223: "CHAP",
}

IP_PROTOCOLS = {
    1: "ICMP",
    6: "TCP",
    17: "UDP",
}

ICMP_TYPES = {
    0: "Echo Reply",
    3: "Destination Unreachable",
    5: "Redirect",
    8: "Echo Request",
    11: "Time Exceeded",
}


class PPPDecodeError(Exception):
    pass


def parse_hex_dump(text: str) -> bytes:
    """
    Extract hex bytes from many common dump formats.

    Supported examples:
        0000: 7E FF 7D 23 7D 20
        7E FF 7D 23 7D 20
        7EFF7D237D20
        7E FF 7D23 7D20

    Important:
    - Address labels before ':' are ignored.
    - This prevents 0000, 0010, etc. from becoming packet bytes.
    - Continuous hex groups like 7D27 are split into 7D 27.
    """
    out = bytearray()

    for original_line in text.splitlines():
        line = original_line.strip()
        if not line:
            continue

        # Remove address prefix, for example: 0000:
        # This is done before compact-hex parsing so offsets are not decoded.
        if ":" in line:
            line = line.split(":", 1)[1]

        # Remove common comments.
        line = line.split("#", 1)[0]
        line = line.split("//", 1)[0]

        # Keep only hex characters. This allows mixed spacing like:
        # 7D27, 7D 27, 7D-27, 7D,27, etc.
        hex_only = re.sub(r"[^0-9A-Fa-f]", "", line)

        if not hex_only:
            continue

        if len(hex_only) % 2 != 0:
            raise PPPDecodeError(
                f"Odd number of hex digits in line: {original_line!r}"
            )

        for i in range(0, len(hex_only), 2):
            out.append(int(hex_only[i:i + 2], 16))

    return bytes(out)


def extract_ppp_frames(raw: bytes) -> List[bytes]:
    """
    Extract frames between PPP flag bytes 0x7E.
    Returned frames include start and end 0x7E flags.
    """
    frames = []
    start = None

    for i, b in enumerate(raw):
        if b == 0x7E:
            if start is None:
                start = i
            else:
                if i > start:
                    frames.append(raw[start:i + 1])
                start = i

    return frames


def ppp_unescape(data: bytes) -> bytes:
    """
    PPP async HDLC escaping:
        0x7D XX means XX ^ 0x20
    """
    out = bytearray()
    i = 0

    while i < len(data):
        if data[i] == 0x7D:
            if i + 1 >= len(data):
                raise PPPDecodeError("Bad PPP escape: 0x7D at end of frame")
            out.append(data[i + 1] ^ 0x20)
            i += 2
        else:
            out.append(data[i])
            i += 1

    return bytes(out)


def ppp_fcs16(data: bytes) -> int:
    """
    PPP FCS-16 calculation.
    For a good PPP frame body INCLUDING received FCS,
    result should be 0xF0B8.
    """
    fcs = 0xFFFF

    for b in data:
        fcs ^= b
        for _ in range(8):
            if fcs & 1:
                fcs = (fcs >> 1) ^ 0x8408
            else:
                fcs >>= 1
            fcs &= 0xFFFF

    return fcs


def calc_ppp_fcs_to_send(data_without_fcs: bytes) -> int:
    """
    PPP sends FCS little-endian: low byte first, high byte second.
    """
    return ppp_fcs16(data_without_fcs) ^ 0xFFFF


def internet_checksum(data: bytes) -> int:
    """IPv4 / ICMP checksum. Valid data with checksum included returns 0."""
    if len(data) % 2:
        data += b"\x00"

    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) + data[i + 1]
        total = (total & 0xFFFF) + (total >> 16)

    return (~total) & 0xFFFF


def ip4(addr: bytes) -> str:
    return ".".join(str(b) for b in addr)


def put(labels: Dict[int, Tuple[str, str]], idx: int, layer: str, meaning: str):
    labels[idx] = (layer, meaning)


def hex_line(data: bytes) -> str:
    return data.hex(" ").upper()


def ascii_byte(b: int) -> str:
    """
    Printable ASCII for one byte.
    Non-printable bytes are shown as '.' like a packet hex viewer.
    """
    return chr(b) if 32 <= b <= 126 else "."


def ascii_line(data: bytes) -> str:
    return "".join(ascii_byte(b) for b in data)


def decode_frame(frame: bytes, frame_number: int = 1) -> Tuple[str, List[Tuple[int, str, str, str, str]]]:
    """
    Returns:
        summary_text, rows

    rows contains:
        index, hex, ascii, layer, meaning
    """
    if len(frame) < 6:
        raise PPPDecodeError("Frame too short")

    if frame[0] != 0x7E or frame[-1] != 0x7E:
        raise PPPDecodeError("Not a complete PPP frame: missing 0x7E start/end flag")

    raw_inside = frame[1:-1]
    inside = ppp_unescape(raw_inside)

    # Decoded logical frame includes flags.
    decoded = bytes([0x7E]) + inside + bytes([0x7E])
    labels: Dict[int, Tuple[str, str]] = {}
    summary: List[str] = []

    put(labels, 0, "PPP", "Flag: start of PPP frame, value 0x7E")
    put(labels, len(decoded) - 1, "PPP", "Flag: end of PPP frame, value 0x7E")

    if len(inside) < 4:
        raise PPPDecodeError("PPP body too short")

    body_without_fcs = inside[:-2]
    received_fcs = inside[-2] | (inside[-1] << 8)
    computed_fcs = calc_ppp_fcs_to_send(body_without_fcs)
    fcs_ok = ppp_fcs16(inside) == 0xF0B8

    fcs_low_index = len(decoded) - 3
    fcs_high_index = len(decoded) - 2

    put(
        labels,
        fcs_low_index,
        "PPP",
        f"FCS low byte. Received FCS=0x{received_fcs:04X}, computed=0x{computed_fcs:04X}",
    )
    put(
        labels,
        fcs_high_index,
        "PPP",
        f"FCS high byte. PPP FCS check={'OK' if fcs_ok else 'BAD'}",
    )

    pos = 1

    has_ac = False
    if len(decoded) >= 5 and decoded[1] == 0xFF and decoded[2] == 0x03:
        has_ac = True
        put(labels, 1, "PPP", "Address field: 0xFF = all-stations address")
        put(labels, 2, "PPP", "Control field: 0x03 = UI, Unnumbered Information")
        pos = 3

    if pos >= len(decoded) - 3:
        raise PPPDecodeError("PPP protocol field missing")

    # PPP protocol field may be one or two bytes.
    if decoded[pos] & 0x01:
        ppp_protocol = decoded[pos]
        put(
            labels,
            pos,
            "PPP",
            f"Protocol field: 0x{ppp_protocol:02X} = {PPP_PROTOCOLS.get(ppp_protocol, 'unknown')}",
        )
        pos += 1
    else:
        if pos + 1 >= len(decoded) - 3:
            raise PPPDecodeError("Two-byte PPP protocol field incomplete")
        ppp_protocol = (decoded[pos] << 8) | decoded[pos + 1]
        proto_name = PPP_PROTOCOLS.get(ppp_protocol, "unknown")
        put(labels, pos, "PPP", f"Protocol MSB. Full protocol=0x{ppp_protocol:04X} = {proto_name}")
        put(labels, pos + 1, "PPP", f"Protocol LSB. Full protocol=0x{ppp_protocol:04X} = {proto_name}")
        pos += 2

    payload_start = pos
    payload_end = len(decoded) - 3
    payload = decoded[payload_start:payload_end]

    summary.append(f"Frame number          : {frame_number}")
    summary.append(f"Raw frame length      : {len(frame)} bytes")
    summary.append(f"Decoded frame length  : {len(decoded)} bytes")
    summary.append(f"PPP Address/Control   : {'present: FF 03' if has_ac else 'not present/compressed'}")
    summary.append(f"PPP Protocol          : 0x{ppp_protocol:04X} ({PPP_PROTOCOLS.get(ppp_protocol, 'unknown')})")
    summary.append(f"PPP Payload length    : {len(payload)} bytes")
    summary.append(f"PPP Payload hex       : {hex_line(payload)}")
    summary.append(f"PPP Payload ASCII     : {ascii_line(payload)}")
    summary.append(f"PPP FCS received      : 0x{received_fcs:04X}")
    summary.append(f"PPP FCS computed      : 0x{computed_fcs:04X}")
    summary.append(f"PPP FCS status        : {'OK' if fcs_ok else 'BAD'}")

    if ppp_protocol == 0x0021 and len(payload) >= 20:
        ip_start = payload_start

        version = payload[0] >> 4
        ihl_words = payload[0] & 0x0F
        ihl_bytes = ihl_words * 4

        if version != 4:
            summary.append("")
            summary.append(f"IPv4 warning          : Version field is {version}, expected 4")

        if ihl_bytes < 20 or len(payload) < ihl_bytes:
            summary.append("")
            summary.append("IPv4 warning          : Invalid or incomplete IPv4 header")
        else:
            dscp = payload[1] >> 2
            ecn = payload[1] & 0x03
            total_length = (payload[2] << 8) | payload[3]
            identification = (payload[4] << 8) | payload[5]
            flags_frag = (payload[6] << 8) | payload[7]
            flags = flags_frag >> 13
            frag_offset = flags_frag & 0x1FFF
            ttl = payload[8]
            ip_proto = payload[9]
            ip_checksum = (payload[10] << 8) | payload[11]
            src = payload[12:16]
            dst = payload[16:20]

            ip_header = payload[:ihl_bytes]
            ip_checksum_ok = internet_checksum(ip_header) == 0

            flag_reserved = (flags >> 2) & 1
            flag_df = (flags >> 1) & 1
            flag_mf = flags & 1

            put(labels, ip_start + 0, "IPv4", f"Version/IHL: IPv{version}, header length={ihl_bytes} bytes")
            put(labels, ip_start + 1, "IPv4", f"DS field: DSCP={dscp}, ECN={ecn}")
            put(labels, ip_start + 2, "IPv4", f"Total length high byte. Total IPv4 length={total_length} bytes")
            put(labels, ip_start + 3, "IPv4", f"Total length low byte. Total IPv4 length={total_length} bytes")
            put(labels, ip_start + 4, "IPv4", f"Identification high byte. ID=0x{identification:04X}")
            put(labels, ip_start + 5, "IPv4", f"Identification low byte. ID=0x{identification:04X}")
            put(labels, ip_start + 6, "IPv4", f"Flags/fragment high byte. R={flag_reserved}, DF={flag_df}, MF={flag_mf}, offset={frag_offset}")
            put(labels, ip_start + 7, "IPv4", f"Flags/fragment low byte. R={flag_reserved}, DF={flag_df}, MF={flag_mf}, offset={frag_offset}")
            put(labels, ip_start + 8, "IPv4", f"TTL: {ttl}")
            put(labels, ip_start + 9, "IPv4", f"Protocol: {ip_proto} = {IP_PROTOCOLS.get(ip_proto, 'unknown')}")
            put(labels, ip_start + 10, "IPv4", f"Header checksum high byte. Checksum=0x{ip_checksum:04X}, status={'OK' if ip_checksum_ok else 'BAD'}")
            put(labels, ip_start + 11, "IPv4", f"Header checksum low byte. Checksum=0x{ip_checksum:04X}, status={'OK' if ip_checksum_ok else 'BAD'}")

            for n in range(4):
                put(labels, ip_start + 12 + n, "IPv4", f"Source IP byte {n + 1}: {ip4(src)}")
                put(labels, ip_start + 16 + n, "IPv4", f"Destination IP byte {n + 1}: {ip4(dst)}")

            summary.append("")
            summary.append("IPv4 summary")
            summary.append(f"  Version             : IPv{version}")
            summary.append(f"  Header length       : {ihl_bytes} bytes")
            summary.append(f"  DSCP / ECN          : {dscp} / {ecn}")
            summary.append(f"  Total length        : {total_length} bytes")
            summary.append(f"  Identification      : 0x{identification:04X}")
            summary.append(f"  Flags               : R={flag_reserved}, DF={flag_df}, MF={flag_mf}")
            summary.append(f"  Fragment offset     : {frag_offset}")
            summary.append(f"  TTL                 : {ttl}")
            summary.append(f"  Protocol            : {ip_proto} ({IP_PROTOCOLS.get(ip_proto, 'unknown')})")
            summary.append(f"  Header checksum     : 0x{ip_checksum:04X} ({'OK' if ip_checksum_ok else 'BAD'})")
            summary.append(f"  Source IP           : {ip4(src)}")
            summary.append(f"  Destination IP      : {ip4(dst)}")

            ipv4_packet_end = min(total_length, len(payload))
            ipv4_packet = payload[:ipv4_packet_end]
            if total_length > len(payload):
                summary.append(f"  Length warning      : IPv4 total length says {total_length} bytes, but only {len(payload)} payload bytes are available")

            ip_payload_start = ip_start + ihl_bytes
            ip_payload = payload[ihl_bytes:ipv4_packet_end]
            summary.append(f"  Full IPv4 packet hex: {hex_line(ipv4_packet)}")
            summary.append(f"  Full IPv4 packet ASCII: {ascii_line(ipv4_packet)}")
            summary.append(f"  Full IP payload hex : {hex_line(ip_payload)}")
            summary.append(f"  Full IP payload ASCII: {ascii_line(ip_payload)}")
            summary.append(f"  Payload route       : {ip4(src)} -> {ip4(dst)}")

            if ip_proto == 1 and len(ip_payload) >= 8:
                icmp_type = ip_payload[0]
                icmp_code = ip_payload[1]
                icmp_checksum = (ip_payload[2] << 8) | ip_payload[3]
                icmp_id = (ip_payload[4] << 8) | ip_payload[5]
                icmp_seq = (ip_payload[6] << 8) | ip_payload[7]
                icmp_data = ip_payload[8:]
                icmp_checksum_ok = internet_checksum(ip_payload) == 0

                put(labels, ip_payload_start + 0, "ICMP", f"Type: {icmp_type} = {ICMP_TYPES.get(icmp_type, 'unknown')}")
                put(labels, ip_payload_start + 1, "ICMP", f"Code: {icmp_code}")
                put(labels, ip_payload_start + 2, "ICMP", f"Checksum high byte. Checksum=0x{icmp_checksum:04X}, status={'OK' if icmp_checksum_ok else 'BAD'}")
                put(labels, ip_payload_start + 3, "ICMP", f"Checksum low byte. Checksum=0x{icmp_checksum:04X}, status={'OK' if icmp_checksum_ok else 'BAD'}")
                put(labels, ip_payload_start + 4, "ICMP", f"Identifier high byte. ID=0x{icmp_id:04X}")
                put(labels, ip_payload_start + 5, "ICMP", f"Identifier low byte. ID=0x{icmp_id:04X}")
                put(labels, ip_payload_start + 6, "ICMP", f"Sequence high byte. Sequence={icmp_seq}")
                put(labels, ip_payload_start + 7, "ICMP", f"Sequence low byte. Sequence={icmp_seq}")

                for n in range(len(icmp_data)):
                    put(labels, ip_payload_start + 8 + n, "ICMP", f"Payload/data byte {n + 1}")

                summary.append("")
                summary.append("ICMP summary")
                summary.append(f"  Type                : {icmp_type} ({ICMP_TYPES.get(icmp_type, 'unknown')})")
                summary.append(f"  Code                : {icmp_code}")
                summary.append(f"  Checksum            : 0x{icmp_checksum:04X} ({'OK' if icmp_checksum_ok else 'BAD'})")
                summary.append(f"  Identifier          : 0x{icmp_id:04X}")
                summary.append(f"  Sequence            : {icmp_seq}")
                summary.append(f"  Payload length      : {len(icmp_data)} bytes")
                summary.append(f"  Payload hex         : {hex_line(icmp_data)}")
                summary.append(f"  Payload ASCII       : {ascii_line(icmp_data)}")
            elif ip_proto == 6:
                decode_tcp_basic(payload, ip_start, ihl_bytes, labels, summary)
            elif ip_proto == 17:
                decode_udp_basic(payload, ip_start, ihl_bytes, labels, summary)

    rows: List[Tuple[int, str, str, str, str]] = []
    for i, b in enumerate(decoded):
        layer, meaning = labels.get(i, ("DATA", "Payload/data or undecoded byte"))
        rows.append((i, f"{b:02X}", ascii_byte(b), layer, meaning))

    return "\n".join(summary), rows


def decode_udp_basic(payload: bytes, ip_start: int, ihl_bytes: int, labels: Dict[int, Tuple[str, str]], summary: List[str]):
    udp_start = ip_start + ihl_bytes
    udp = payload[ihl_bytes:]
    if len(udp) < 8:
        summary.append("")
        summary.append("UDP warning           : UDP header incomplete")
        return

    src_port = (udp[0] << 8) | udp[1]
    dst_port = (udp[2] << 8) | udp[3]
    length = (udp[4] << 8) | udp[5]
    checksum = (udp[6] << 8) | udp[7]

    put(labels, udp_start + 0, "UDP", f"Source port high byte. Source port={src_port}")
    put(labels, udp_start + 1, "UDP", f"Source port low byte. Source port={src_port}")
    put(labels, udp_start + 2, "UDP", f"Destination port high byte. Destination port={dst_port}")
    put(labels, udp_start + 3, "UDP", f"Destination port low byte. Destination port={dst_port}")
    put(labels, udp_start + 4, "UDP", f"Length high byte. UDP length={length}")
    put(labels, udp_start + 5, "UDP", f"Length low byte. UDP length={length}")
    put(labels, udp_start + 6, "UDP", f"Checksum high byte. Checksum=0x{checksum:04X}")
    put(labels, udp_start + 7, "UDP", f"Checksum low byte. Checksum=0x{checksum:04X}")

    for n in range(8, len(udp)):
        put(labels, udp_start + n, "UDP", f"UDP payload byte {n - 7}")

    summary.append("")
    summary.append("UDP summary")
    summary.append(f"  Source port         : {src_port}")
    udp_payload = udp[8:length] if length >= 8 else b""
    summary.append(f"  Destination port    : {dst_port}")
    summary.append(f"  UDP length          : {length}")
    summary.append(f"  UDP checksum        : 0x{checksum:04X}")
    summary.append(f"  Full UDP payload hex: {hex_line(udp_payload)}")
    summary.append(f"  Full UDP payload ASCII: {ascii_line(udp_payload)}")


def decode_tcp_basic(payload: bytes, ip_start: int, ihl_bytes: int, labels: Dict[int, Tuple[str, str]], summary: List[str]):
    tcp_start = ip_start + ihl_bytes
    tcp = payload[ihl_bytes:]
    if len(tcp) < 20:
        summary.append("")
        summary.append("TCP warning           : TCP header incomplete")
        return

    src_port = (tcp[0] << 8) | tcp[1]
    dst_port = (tcp[2] << 8) | tcp[3]
    seq = int.from_bytes(tcp[4:8], "big")
    ack = int.from_bytes(tcp[8:12], "big")
    data_offset = (tcp[12] >> 4) * 4
    flags = tcp[13]
    window = (tcp[14] << 8) | tcp[15]
    checksum = (tcp[16] << 8) | tcp[17]
    urgent = (tcp[18] << 8) | tcp[19]

    flag_names = []
    for bit, name in [
        (0x80, "CWR"),
        (0x40, "ECE"),
        (0x20, "URG"),
        (0x10, "ACK"),
        (0x08, "PSH"),
        (0x04, "RST"),
        (0x02, "SYN"),
        (0x01, "FIN"),
    ]:
        if flags & bit:
            flag_names.append(name)
    flags_text = ",".join(flag_names) if flag_names else "none"

    for n in range(min(len(tcp), data_offset if data_offset >= 20 else 20)):
        put(labels, tcp_start + n, "TCP", "TCP header byte")

    put(labels, tcp_start + 0, "TCP", f"Source port high byte. Source port={src_port}")
    put(labels, tcp_start + 1, "TCP", f"Source port low byte. Source port={src_port}")
    put(labels, tcp_start + 2, "TCP", f"Destination port high byte. Destination port={dst_port}")
    put(labels, tcp_start + 3, "TCP", f"Destination port low byte. Destination port={dst_port}")
    put(labels, tcp_start + 4, "TCP", f"Sequence number byte 1. Sequence={seq}")
    put(labels, tcp_start + 5, "TCP", f"Sequence number byte 2. Sequence={seq}")
    put(labels, tcp_start + 6, "TCP", f"Sequence number byte 3. Sequence={seq}")
    put(labels, tcp_start + 7, "TCP", f"Sequence number byte 4. Sequence={seq}")
    put(labels, tcp_start + 8, "TCP", f"Acknowledgment byte 1. ACK={ack}")
    put(labels, tcp_start + 9, "TCP", f"Acknowledgment byte 2. ACK={ack}")
    put(labels, tcp_start + 10, "TCP", f"Acknowledgment byte 3. ACK={ack}")
    put(labels, tcp_start + 11, "TCP", f"Acknowledgment byte 4. ACK={ack}")
    put(labels, tcp_start + 12, "TCP", f"Data offset/reserved. TCP header length={data_offset} bytes")
    put(labels, tcp_start + 13, "TCP", f"TCP flags: 0x{flags:02X} = {flags_text}")
    put(labels, tcp_start + 14, "TCP", f"Window high byte. Window={window}")
    put(labels, tcp_start + 15, "TCP", f"Window low byte. Window={window}")
    put(labels, tcp_start + 16, "TCP", f"Checksum high byte. Checksum=0x{checksum:04X}")
    put(labels, tcp_start + 17, "TCP", f"Checksum low byte. Checksum=0x{checksum:04X}")
    put(labels, tcp_start + 18, "TCP", f"Urgent pointer high byte. Urgent={urgent}")
    put(labels, tcp_start + 19, "TCP", f"Urgent pointer low byte. Urgent={urgent}")

    for n in range(max(data_offset, 20), len(tcp)):
        put(labels, tcp_start + n, "TCP", f"TCP payload byte {n - max(data_offset, 20) + 1}")

    summary.append("")
    summary.append("TCP summary")
    summary.append(f"  Source port         : {src_port}")
    summary.append(f"  Destination port    : {dst_port}")
    summary.append(f"  Sequence number     : {seq}")
    summary.append(f"  Acknowledgment      : {ack}")
    summary.append(f"  Header length       : {data_offset} bytes")
    summary.append(f"  Flags               : {flags_text}")
    tcp_payload = tcp[data_offset:] if data_offset >= 20 else tcp[20:]
    summary.append(f"  Window              : {window}")
    summary.append(f"  TCP checksum        : 0x{checksum:04X}")
    summary.append(f"  Urgent pointer      : {urgent}")
    summary.append(f"  Full TCP payload hex: {hex_line(tcp_payload)}")
    summary.append(f"  Full TCP payload ASCII: {ascii_line(tcp_payload)}")


class PPPDecoderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cavli C16QS PPP Packet Decoder")
        self.geometry("1150x760")
        self.minsize(950, 620)

        self.last_report = ""
        self._build_ui()
        self.input_text.insert("1.0", SAMPLE_HEX)
        self.decode_input()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=8)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)

        title = ttk.Label(top, text="Cavli C16QS PPP Packet Decoder", font=("TkDefaultFont", 14, "bold"))
        title.grid(row=0, column=0, sticky="w")

        button_bar = ttk.Frame(top)
        button_bar.grid(row=0, column=1, sticky="e")

        ttk.Button(button_bar, text="Load Hex File", command=self.load_file).grid(row=0, column=0, padx=3)
        ttk.Button(button_bar, text="Decode", command=self.decode_input).grid(row=0, column=1, padx=3)
        ttk.Button(button_bar, text="Clear", command=self.clear_all).grid(row=0, column=2, padx=3)
        ttk.Button(button_bar, text="Save Report", command=self.save_report).grid(row=0, column=3, padx=3)

        main = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        upper = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        main.add(upper, weight=2)

        input_frame = ttk.LabelFrame(upper, text="Paste PPP hex dump here")
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(0, weight=1)

        self.input_text = ScrolledText(input_frame, wrap=tk.NONE, height=10, font=("Consolas", 10))
        self.input_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        upper.add(input_frame, weight=1)

        summary_frame = ttk.LabelFrame(upper, text="Decoded summary")
        summary_frame.columnconfigure(0, weight=1)
        summary_frame.rowconfigure(0, weight=1)

        self.summary_text = ScrolledText(summary_frame, wrap=tk.WORD, height=10, font=("Consolas", 10))
        self.summary_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        upper.add(summary_frame, weight=1)

        table_frame = ttk.LabelFrame(main, text="Byte-by-byte meaning")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        main.add(table_frame, weight=3)

        columns = ("index", "hex", "ascii", "layer", "meaning")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        self.tree.heading("index", text="Index")
        self.tree.heading("hex", text="Hex")
        self.tree.heading("ascii", text="ASCII")
        self.tree.heading("layer", text="Layer")
        self.tree.heading("meaning", text="Meaning")

        self.tree.column("index", width=70, anchor="center", stretch=False)
        self.tree.column("hex", width=70, anchor="center", stretch=False)
        self.tree.column("ascii", width=70, anchor="center", stretch=False)
        self.tree.column("layer", width=90, anchor="center", stretch=False)
        self.tree.column("meaning", width=780, anchor="w", stretch=True)

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        bottom = ttk.Frame(self, padding=(8, 0, 8, 8))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

    def clear_all(self):
        self.input_text.delete("1.0", tk.END)
        self.summary_text.delete("1.0", tk.END)
        self.clear_table()
        self.last_report = ""
        self.status_var.set("Cleared")

    def clear_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def load_file(self):
        path = filedialog.askopenfilename(
            title="Open hex dump file",
            filetypes=[
                ("Text files", "*.txt *.log *.dump *.hex"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = f.read()
        except OSError as e:
            messagebox.showerror("Open failed", str(e))
            return

        self.input_text.delete("1.0", tk.END)
        self.input_text.insert("1.0", data)
        self.status_var.set(f"Loaded: {path}")

    def decode_input(self):
        text = self.input_text.get("1.0", tk.END)
        self.summary_text.delete("1.0", tk.END)
        self.clear_table()
        self.last_report = ""

        try:
            raw = parse_hex_dump(text)
            if not raw:
                raise PPPDecodeError("No hex bytes found")

            frames = extract_ppp_frames(raw)
            if not frames:
                # If no 0x7E pair is found, try treating the whole input as one raw frame.
                if raw and raw[0] == 0x7E and raw[-1] == 0x7E:
                    frames = [raw]
                else:
                    raise PPPDecodeError("No complete PPP frame found between 0x7E flags")

            all_summary: List[str] = []
            all_report: List[str] = []

            for frame_number, frame in enumerate(frames, start=1):
                summary, rows = decode_frame(frame, frame_number)
                all_summary.append(summary)
                all_report.append("=" * 90)
                all_report.append(f"FRAME {frame_number}")
                all_report.append("=" * 90)
                all_report.append(summary)
                all_report.append("")
                all_report.append("Byte-by-byte decode")
                all_report.append("Index  Hex  ASCII  Layer     Meaning")
                all_report.append("-" * 110)

                for index, hx, asc, layer, meaning in rows:
                    self.tree.insert("", tk.END, values=(index, hx, asc, layer, meaning))
                    all_report.append(f"{index:5d}  {hx:>3}  {asc:^5}  {layer:<8}  {meaning}")

                if frame_number != len(frames):
                    self.tree.insert("", tk.END, values=("", "", "", "", ""))
                    all_summary.append("\n" + "-" * 60 + "\n")
                    all_report.append("")

            final_summary = "\n".join(all_summary)
            self.summary_text.insert("1.0", final_summary)
            self.last_report = "\n".join(all_report)
            self.status_var.set(f"Decoded {len(frames)} frame(s), {len(raw)} input byte(s)")

        except Exception as e:
            self.summary_text.insert("1.0", f"Decode error:\n{e}")
            self.status_var.set("Decode failed")
            messagebox.showerror("Decode error", str(e))

    def save_report(self):
        if not self.last_report:
            messagebox.showinfo("Nothing to save", "Decode a packet first.")
            return

        path = filedialog.asksaveasfilename(
            title="Save decoded report",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.last_report)
        except OSError as e:
            messagebox.showerror("Save failed", str(e))
            return

        self.status_var.set(f"Saved report: {path}")


if __name__ == "__main__":
    app = PPPDecoderApp()
    app.mainloop()
