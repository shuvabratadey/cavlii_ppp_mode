"""
Cavli C16QS PPP Packet Tool
- Build PPP packets (LCP, IPCP, PAP, CHAP, ICMP/Ping)
- Decode hex/raw PPP responses pasted from serial terminal
- Suggest next packet based on PPP negotiation state
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, font
import struct
import binascii
import threading
import time
from datetime import datetime

# ─────────────────────────────────────────────────────────
#  PPP CONSTANTS
# ─────────────────────────────────────────────────────────
PPP_FLAG      = 0x7E
PPP_ESCAPE    = 0x7D
PPP_ADDR      = 0xFF
PPP_CTRL      = 0x03

PROTO_LCP     = 0xC021
PROTO_PAP     = 0xC023
PROTO_CHAP    = 0xC223
PROTO_IPCP    = 0x8021
PROTO_IP      = 0x0021

LCP_CODES = {1:"Configure-Request",2:"Configure-Ack",3:"Configure-Nak",
             4:"Configure-Reject",5:"Terminate-Request",6:"Terminate-Ack",
             7:"Code-Reject",9:"Echo-Request",10:"Echo-Reply"}

IPCP_CODES = {1:"Configure-Request",2:"Configure-Ack",3:"Configure-Nak",
              4:"Configure-Reject",5:"Terminate-Request",6:"Terminate-Ack"}

LCP_OPTIONS = {1:"MRU",2:"Async-Control-Char-Map",3:"Auth-Protocol",
               4:"Quality-Protocol",5:"Magic-Number",7:"Protocol-Field-Compression",
               8:"Address-Control-Compression"}

IPCP_OPTIONS = {1:"IP-Addresses (deprecated)",3:"IP-Compression-Protocol",
                129:"IP-Address",130:"Primary-DNS",131:"Primary-NBNS",
                132:"Secondary-DNS",133:"Secondary-NBNS"}

# ─────────────────────────────────────────────────────────
#  PPP FRAMING UTILITIES
# ─────────────────────────────────────────────────────────
def fcs16(data: bytes) -> int:
    """CRC-16 (HDLC FCS)"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8408
            else:
                crc >>= 1
    return crc ^ 0xFFFF

def ppp_escape_byte(b: int) -> bytes:
    if b == PPP_FLAG or b == PPP_ESCAPE or b < 0x20:
        return bytes([PPP_ESCAPE, b ^ 0x20])
    return bytes([b])

def ppp_frame(proto: int, payload: bytes) -> bytes:
    """Wrap payload in PPP HDLC framing with FCS"""
    inner = bytes([PPP_ADDR, PPP_CTRL]) + struct.pack(">H", proto) + payload
    crc = fcs16(inner)
    raw = inner + struct.pack("<H", crc)
    escaped = bytearray([PPP_FLAG])
    for b in raw:
        escaped.extend(ppp_escape_byte(b))
    escaped.append(PPP_FLAG)
    return bytes(escaped)

def ppp_unescape(data: bytes) -> bytes:
    out = bytearray()
    escaped = False
    for b in data:
        if b == PPP_FLAG:
            continue
        if b == PPP_ESCAPE:
            escaped = True
            continue
        if escaped:
            out.append(b ^ 0x20)
            escaped = False
        else:
            out.append(b)
    return bytes(out)

def ip_checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b'\x00'
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i+1]
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF

# ─────────────────────────────────────────────────────────
#  PACKET BUILDERS
# ─────────────────────────────────────────────────────────
_id_counter = 1
def next_id():
    global _id_counter
    v = _id_counter & 0xFF
    _id_counter += 1
    return v

def build_lcp_configure_request(magic: int = 0x01234567, mru: int = 1500) -> bytes:
    opts = struct.pack(">BBH", 1, 4, mru)                          # MRU
    opts += struct.pack(">BBI", 5, 6, magic)                       # Magic-Number
    opts += struct.pack(">BB", 7, 2)                               # PFC
    opts += struct.pack(">BB", 8, 2)                               # ACFC
    payload = struct.pack(">BBH", 1, next_id(), 4 + len(opts)) + opts
    return ppp_frame(PROTO_LCP, payload)

def build_lcp_configure_ack(identifier: int, options: bytes) -> bytes:
    payload = struct.pack(">BBH", 2, identifier, 4 + len(options)) + options
    return ppp_frame(PROTO_LCP, payload)

def build_lcp_terminate_request() -> bytes:
    payload = struct.pack(">BBH", 5, next_id(), 4) 
    return ppp_frame(PROTO_LCP, payload)

def build_lcp_echo_request(magic: int = 0x01234567) -> bytes:
    payload = struct.pack(">BBHI", 9, next_id(), 8, magic)
    return ppp_frame(PROTO_LCP, payload)

def build_pap_request(username: str, password: str) -> bytes:
    u = username.encode()
    p = password.encode()
    payload = struct.pack(">BBH", 1, next_id(), 4 + 1 + len(u) + 1 + len(p))
    payload += bytes([len(u)]) + u + bytes([len(p)]) + p
    return ppp_frame(PROTO_PAP, payload)

def build_ipcp_configure_request(ip: str = "0.0.0.0", dns1: str = "0.0.0.0") -> bytes:
    ip_b  = bytes(map(int, ip.split(".")))
    dns_b = bytes(map(int, dns1.split(".")))
    opts  = bytes([129, 6]) + ip_b        # IP-Address
    opts += bytes([129+3, 6]) + dns_b     # Primary-DNS (option 130 = 0x82)
    opts  = bytes([129, 6]) + ip_b + bytes([130, 6]) + dns_b
    payload = struct.pack(">BBH", 1, next_id(), 4 + len(opts)) + opts
    return ppp_frame(PROTO_IPCP, payload)

def build_ipcp_configure_ack(identifier: int, options: bytes) -> bytes:
    payload = struct.pack(">BBH", 2, identifier, 4 + len(options)) + options
    return ppp_frame(PROTO_IPCP, payload)

def build_icmp_echo(src_ip: str, dst_ip: str, seq: int = 1, payload_str: str = "Cavli-PPP") -> bytes:
    data = payload_str.encode()
    icmp_hdr = struct.pack(">BBHHH", 8, 0, 0, 1, seq) + data
    csum = ip_checksum(icmp_hdr)
    icmp = struct.pack(">BBHHH", 8, 0, csum, 1, seq) + data
    src = bytes(map(int, src_ip.split(".")))
    dst = bytes(map(int, dst_ip.split(".")))
    iph = struct.pack(">BBHHHBBH4s4s",
        0x45, 0, 20 + len(icmp), 1, 0, 64, 1, 0, src, dst)
    csum2 = ip_checksum(iph)
    iph = struct.pack(">BBHHHBBH4s4s",
        0x45, 0, 20 + len(icmp), 1, 0, 64, 1, csum2, src, dst)
    return ppp_frame(PROTO_IP, iph + icmp)

# ─────────────────────────────────────────────────────────
#  PACKET DECODER
# ─────────────────────────────────────────────────────────
def decode_ppp(hex_str: str) -> dict:
    hex_clean = hex_str.replace(" ", "").replace("\n", "").replace(":", "")
    try:
        raw = bytes.fromhex(hex_clean)
    except Exception as e:
        return {"error": f"Invalid hex: {e}"}

    if raw[0] == PPP_FLAG:
        raw = ppp_unescape(raw)

    info = {"raw_len": len(raw), "lines": []}
    add = info["lines"].append

    if len(raw) < 4:
        add("Frame too short"); return info

    # Strip FCS (last 2 bytes)
    fcs_recv = struct.unpack("<H", raw[-2:])[0]
    fcs_calc = fcs16(raw[:-2])
    fcs_ok = fcs_recv == fcs_calc
    add(f"FCS: {'✓ OK' if fcs_ok else '✗ MISMATCH'} (recv=0x{fcs_recv:04X} calc=0x{fcs_calc:04X})")

    data = raw[:-2]  # without FCS

    offset = 0
    if data[offset] == PPP_ADDR:
        add(f"Address: 0xFF  Control: 0x{data[1]:02X}")
        offset = 2
    
    if len(data) < offset + 2:
        add("Too short for protocol"); return info

    proto = struct.unpack(">H", data[offset:offset+2])[0]
    offset += 2
    proto_names = {PROTO_LCP:"LCP", PROTO_PAP:"PAP", PROTO_CHAP:"CHAP",
                   PROTO_IPCP:"IPCP", PROTO_IP:"IP"}
    add(f"Protocol: 0x{proto:04X}  ({proto_names.get(proto,'Unknown')})")

    payload = data[offset:]

    if proto == PROTO_LCP:
        _decode_cp(payload, LCP_CODES, LCP_OPTIONS, "LCP", add)
    elif proto == PROTO_IPCP:
        _decode_cp(payload, IPCP_CODES, IPCP_OPTIONS, "IPCP", add)
    elif proto == PROTO_PAP:
        _decode_pap(payload, add)
    elif proto == PROTO_IP:
        _decode_ip(payload, add)
    elif proto == PROTO_CHAP:
        _decode_chap(payload, add)
    else:
        add(f"Payload (hex): {payload.hex()}")

    info["proto"] = proto
    info["proto_name"] = proto_names.get(proto, "Unknown")
    return info

def _decode_cp(payload, code_map, opt_map, name, add):
    if len(payload) < 4: add("  Too short"); return
    code, ident, length = struct.unpack(">BBH", payload[:4])
    add(f"  Code: {code} ({code_map.get(code,'Unknown')})")
    add(f"  ID  : {ident}    Length: {length}")
    opts = payload[4:length]
    if code in (1, 2, 3, 4) and opts:
        add(f"  Options:")
        i = 0
        while i < len(opts):
            opt_type = opts[i]
            opt_len  = opts[i+1] if i+1 < len(opts) else 0
            opt_val  = opts[i+2:i+opt_len] if opt_len > 2 else b""
            oname = opt_map.get(opt_type, f"Type-{opt_type}")
            if opt_type in (1,) and len(opt_val)==2:  # MRU
                add(f"    {oname}: {struct.unpack('>H',opt_val)[0]}")
            elif opt_type == 5 and len(opt_val)==4:    # Magic
                add(f"    Magic-Number: 0x{opt_val.hex()}")
            elif opt_type in (129,130,131,132,133) and len(opt_val)==4:
                add(f"    {oname}: {'.'.join(str(b) for b in opt_val)}")
            elif opt_type == 3 and len(opt_val)>=2:    # Auth proto
                ap = struct.unpack(">H", opt_val[:2])[0]
                ap_name = {0xC023:"PAP", 0xC223:"CHAP"}.get(ap, f"0x{ap:04X}")
                add(f"    Auth-Protocol: {ap_name}")
            else:
                add(f"    {oname}: {opt_val.hex() if opt_val else '(empty)'}")
            i += max(opt_len, 2)
    elif code in (9, 10):  # Echo
        if len(payload) >= 8:
            magic = struct.unpack(">I", payload[4:8])[0]
            add(f"  Magic-Number: 0x{magic:08X}")

def _decode_pap(payload, add):
    if not payload: return
    code, ident, length = struct.unpack(">BBH", payload[:4])
    codes = {1:"Authenticate-Request", 2:"Authenticate-Ack", 3:"Authenticate-Nak"}
    add(f"  Code: {code} ({codes.get(code,'?')})")
    add(f"  ID  : {ident}")
    if code == 1 and len(payload) > 4:
        ul = payload[4]
        user = payload[5:5+ul].decode(errors='replace')
        pl = payload[5+ul] if 5+ul < len(payload) else 0
        pw = payload[6+ul:6+ul+pl].decode(errors='replace')
        add(f"  Username: {user}")
        add(f"  Password: {'*'*len(pw)}")
    elif code in (2,3) and len(payload) > 4:
        ml = payload[4]
        msg = payload[5:5+ml].decode(errors='replace')
        add(f"  Message: {msg}")

def _decode_chap(payload, add):
    if not payload: return
    code, ident, length = struct.unpack(">BBH", payload[:4])
    codes = {1:"Challenge",2:"Response",3:"Success",4:"Failure"}
    add(f"  Code: {code} ({codes.get(code,'?')})")
    add(f"  ID  : {ident}")
    if code in (1,2) and len(payload)>4:
        vl = payload[4]
        val = payload[5:5+vl]
        name = payload[5+vl:length].decode(errors='replace')
        add(f"  Value-Size: {vl}  Value: {val.hex()}")
        add(f"  Name: {name}")

def _decode_ip(payload, add):
    if len(payload) < 20: add("  IP too short"); return
    ver_ihl = payload[0]
    ttl = payload[8]; proto = payload[9]
    csum = struct.unpack(">H", payload[10:12])[0]
    src = ".".join(str(b) for b in payload[12:16])
    dst = ".".join(str(b) for b in payload[16:20])
    add(f"  IP: {src} → {dst}   TTL={ttl}  proto={proto}")
    ihl = (ver_ihl & 0x0F) * 4
    ip_data = payload[ihl:]
    if proto == 1:  # ICMP
        _decode_icmp(ip_data, add)
    elif proto == 6:
        add(f"  TCP (payload {len(ip_data)} bytes)")
    elif proto == 17:
        add(f"  UDP (payload {len(ip_data)} bytes)")

def _decode_icmp(data, add):
    if len(data) < 8: return
    typ, code, csum, ident, seq = struct.unpack(">BBHHH", data[:8])
    types = {0:"Echo Reply",8:"Echo Request",3:"Dest Unreachable",11:"TTL Exceeded"}
    add(f"  ICMP: {typ} ({types.get(typ,'?')})  ID={ident}  Seq={seq}")
    if len(data) > 8:
        add(f"  Data: {data[8:].decode(errors='replace')}")

# ─────────────────────────────────────────────────────────
#  NEXT STEP ADVISOR
# ─────────────────────────────────────────────────────────
def suggest_next(decoded: dict, state: dict) -> str:
    if "error" in decoded:
        return "⚠  Invalid packet. Check your hex input."

    proto = decoded.get("proto")
    lines = "\n".join(decoded.get("lines", []))

    # LCP state machine
    if proto == PROTO_LCP:
        if "Configure-Request" in lines:
            state["lcp_remote_req"] = True
            if not state.get("lcp_local_sent"):
                return ("📤  Remote sent LCP Configure-Request.\n"
                        "→  Send your own LCP Configure-Request first,\n"
                        "   then send LCP Configure-Ack to acknowledge theirs.")
            return ("📤  Remote sent LCP Configure-Request.\n"
                    "→  Send LCP Configure-Ack (confirm their options).")
        if "Configure-Ack" in lines:
            state["lcp_ack"] = True
            if not state.get("lcp_remote_req"):
                return "✅  LCP Ack received. Wait for remote's Configure-Request."
            if state.get("auth_required"):
                return ("✅  LCP negotiated!\n→  Send PAP Authenticate-Request\n"
                        "   (username/password for Airtel APN).")
            return "✅  LCP negotiated!\n→  Send IPCP Configure-Request."
        if "Configure-Nak" in lines:
            return ("⚠  LCP Configure-Nak received.\n"
                    "   The modem rejected some options. Adjust your MRU/magic\n"
                    "   and re-send LCP Configure-Request.")
        if "Configure-Reject" in lines:
            return ("⚠  LCP Configure-Reject received.\n"
                    "   Remove the rejected options and re-send Configure-Request.")
        if "Echo-Request" in lines:
            return "📤  Modem sent LCP Echo-Request → Send LCP Echo-Reply."
        if "Terminate" in lines:
            return "⛔  Link terminated. Restart PPP from LCP Configure-Request."

    if proto == PROTO_PAP:
        if "Authenticate-Ack" in lines:
            state["auth_ok"] = True
            return "✅  PAP Auth OK!\n→  Send IPCP Configure-Request (IP + DNS)."
        if "Authenticate-Nak" in lines:
            return "❌  PAP Auth failed. Check Airtel APN username/password."
        if "Authenticate-Request" in lines:
            return "ℹ   Modem sent PAP Request (unusual). Respond with Ack if needed."

    if proto == PROTO_CHAP:
        if "Challenge" in lines:
            return ("📤  CHAP Challenge received.\n"
                    "→  Build CHAP Response (MD5 of id+secret+challenge).")
        if "Success" in lines:
            state["auth_ok"] = True
            return "✅  CHAP Auth OK!\n→  Send IPCP Configure-Request."
        if "Failure" in lines:
            return "❌  CHAP Auth failed."

    if proto == PROTO_IPCP:
        if "Configure-Request" in lines:
            state["ipcp_remote_req"] = True
            return ("📤  Modem sent IPCP Configure-Request.\n"
                    "→  Send IPCP Configure-Ack + your own IPCP Configure-Request\n"
                    "   with IP=0.0.0.0 (modem will assign via Nak).")
        if "Configure-Nak" in lines:
            state["got_ipcp_nak"] = True
            return ("📋  IPCP Configure-Nak — modem is assigning your IP/DNS.\n"
                    "   Extract the IP & DNS from the Nak options above,\n"
                    "   then re-send IPCP Configure-Request with those values.")
        if "Configure-Ack" in lines:
            state["ipcp_ok"] = True
            return ("🎉  IPCP done! PPP link is UP.\n"
                    "→  You can now send IP packets.\n"
                    "→  Send ICMP Echo-Request (ping) to 8.8.8.8 or google.com.")
        if "Configure-Reject" in lines:
            return ("⚠  IPCP Reject. Remove unsupported options\n"
                    "   (usually DNS options) and retry.")

    if proto == PROTO_IP:
        if "Echo Reply" in lines:
            return "🏓  Ping reply received! Internet connectivity confirmed."
        if "Echo Request" in lines:
            return "📤  Sent ping. Waiting for Echo Reply from remote."
        if "Dest Unreachable" in lines:
            return "❌  ICMP Dest Unreachable. Check IP address and routing."
        if "TTL Exceeded" in lines:
            return "⚠  TTL Exceeded. Traceroute hop info."

    return "ℹ   Packet decoded. Check details above and proceed accordingly."

# ─────────────────────────────────────────────────────────
#  GUI
# ─────────────────────────────────────────────────────────
DARK_BG   = "#0D1117"
PANEL_BG  = "#161B22"
BORDER    = "#30363D"
ACCENT    = "#00D9FF"
ACCENT2   = "#7EE787"
WARN      = "#F78166"
TEXT_PRI  = "#E6EDF3"
TEXT_SEC  = "#8B949E"
MONO_FONT = ("Consolas", 10)
TITLE_FONT= ("Segoe UI", 11, "bold")

class PPPTool(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cavli C16QS — PPP Packet Tool")
        self.geometry("1100x780")
        self.configure(bg=DARK_BG)
        self.resizable(True, True)
        self.ppp_state = {}
        self._build_ui()

    # ── helpers ──
    def _lbl(self, parent, text, fg=TEXT_SEC, size=9, bold=False, **kw):
        w = tk.Label(parent, text=text, bg=parent["bg"] if hasattr(parent,"bg_color") else self._bg(parent),
                     fg=fg, font=("Segoe UI", size, "bold" if bold else "normal"), **kw)
        return w

    def _bg(self, w):
        try: return w.cget("bg")
        except: return DARK_BG

    def _entry(self, parent, width=18, **kw):
        e = tk.Entry(parent, width=width, bg="#1C2128", fg=TEXT_PRI,
                     insertbackground=ACCENT, relief="flat", bd=0,
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT, font=MONO_FONT, **kw)
        return e

    def _btn(self, parent, text, cmd, color=ACCENT, width=22):
        b = tk.Button(parent, text=text, command=cmd, bg=color, fg=DARK_BG,
                      font=("Segoe UI", 9, "bold"), relief="flat", bd=0,
                      cursor="hand2", activebackground="#00AACF",
                      activeforeground=DARK_BG, padx=8, pady=4, width=width)
        return b

    def _frame(self, parent, bg=PANEL_BG, bd=1, **kw):
        f = tk.Frame(parent, bg=bg, bd=bd, relief="flat",
                     highlightthickness=1, highlightbackground=BORDER, **kw)
        return f

    def _text_out(self, parent, h=8, **kw):
        t = scrolledtext.ScrolledText(parent, height=h, bg="#0D1117", fg=TEXT_PRI,
            font=MONO_FONT, relief="flat", bd=0,
            insertbackground=ACCENT, highlightthickness=1,
            highlightbackground=BORDER, wrap=tk.WORD, state="disabled", **kw)
        return t

    def _write(self, widget, text, color=None, clear=False):
        widget.configure(state="normal")
        if clear:
            widget.delete("1.0", tk.END)
        ts = datetime.now().strftime("%H:%M:%S")
        if color:
            tag = f"col_{color.replace('#','')}"
            widget.tag_configure(tag, foreground=color)
            widget.insert(tk.END, f"[{ts}] ", "ts")
            widget.tag_configure("ts", foreground=TEXT_SEC)
            widget.insert(tk.END, text + "\n", tag)
        else:
            widget.insert(tk.END, f"[{ts}] {text}\n")
        widget.see(tk.END)
        widget.configure(state="disabled")

    # ── main UI ──
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=PANEL_BG, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="◈  CAVLI C16QS  PPP PACKET TOOL",
                 bg=PANEL_BG, fg=ACCENT,
                 font=("Consolas", 13, "bold")).pack(side="left", padx=16)
        tk.Label(hdr, text="Airtel SIM • LCP / IPCP / PAP / ICMP",
                 bg=PANEL_BG, fg=TEXT_SEC,
                 font=("Segoe UI", 9)).pack(side="left", padx=4)
        self._btn(hdr, "Clear All", self._clear_all, color="#21262D", width=10).pack(side="right", padx=12)

        # Main paned
        pane = tk.PanedWindow(self, orient="horizontal", bg=DARK_BG,
                              sashwidth=4, sashrelief="flat", sashpad=0)
        pane.pack(fill="both", expand=True, padx=8, pady=(4,8))

        left  = tk.Frame(pane, bg=DARK_BG)
        right = tk.Frame(pane, bg=DARK_BG)
        pane.add(left,  minsize=420)
        pane.add(right, minsize=420)

        self._build_builder(left)
        self._build_decoder(right)

    def _build_builder(self, parent):
        tk.Label(parent, text="PACKET BUILDER", bg=DARK_BG, fg=ACCENT,
                 font=("Consolas", 10, "bold")).pack(anchor="w", padx=4, pady=(4,0))

        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True, padx=2, pady=4)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook", background=DARK_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL_BG, foreground=TEXT_SEC,
                        padding=[8,4], font=("Segoe UI",9,"bold"))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)],
                  foreground=[("selected", DARK_BG)])

        self._tab_lcp  = tk.Frame(nb, bg=PANEL_BG, padx=8, pady=8)
        self._tab_pap  = tk.Frame(nb, bg=PANEL_BG, padx=8, pady=8)
        self._tab_ipcp = tk.Frame(nb, bg=PANEL_BG, padx=8, pady=8)
        self._tab_icmp = tk.Frame(nb, bg=PANEL_BG, padx=8, pady=8)

        nb.add(self._tab_lcp,  text=" LCP ")
        nb.add(self._tab_pap,  text=" PAP ")
        nb.add(self._tab_ipcp, text=" IPCP ")
        nb.add(self._tab_icmp, text=" ICMP ")

        self._build_lcp_tab()
        self._build_pap_tab()
        self._build_ipcp_tab()
        self._build_icmp_tab()

        # Output
        tk.Label(parent, text="GENERATED PACKET (hex)", bg=DARK_BG, fg=ACCENT,
                 font=("Consolas", 10, "bold")).pack(anchor="w", padx=4, pady=(2,0))
        self.build_out = self._text_out(parent, h=10)
        self.build_out.pack(fill="both", expand=True, padx=2, pady=(0,4))

    def _row(self, parent, label, entry_widget):
        f = tk.Frame(parent, bg=PANEL_BG)
        f.pack(fill="x", pady=3)
        tk.Label(f, text=label, bg=PANEL_BG, fg=TEXT_SEC,
                 font=("Segoe UI",9), width=16, anchor="w").pack(side="left")
        entry_widget.pack(side="left", padx=(4,0))
        return f

    def _build_lcp_tab(self):
        p = self._tab_lcp
        tk.Label(p, text="LCP – Link Control Protocol", bg=PANEL_BG,
                 fg=ACCENT2, font=("Segoe UI",9,"bold")).pack(anchor="w", pady=(0,6))

        self.lcp_mru   = self._entry(p, width=8); self.lcp_mru.insert(0,"1500")
        self.lcp_magic = self._entry(p, width=12); self.lcp_magic.insert(0,"01234567")
        self._row(p, "MRU", self.lcp_mru)
        self._row(p, "Magic (hex)", self.lcp_magic)

        pkt_var = tk.StringVar(value="Configure-Request")
        tk.Label(p, text="Packet Type", bg=PANEL_BG, fg=TEXT_SEC,
                 font=("Segoe UI",9)).pack(anchor="w", pady=(8,2))
        choices = ["Configure-Request", "Configure-Ack", "Terminate-Request", "Echo-Request"]
        self.lcp_pkt_type = ttk.Combobox(p, values=choices, textvariable=pkt_var,
                                          state="readonly", width=22)
        self.lcp_pkt_type.pack(anchor="w")
        style2 = ttk.Style()
        style2.configure("TCombobox", fieldbackground="#1C2128", background=PANEL_BG,
                         foreground=TEXT_PRI, selectbackground=ACCENT)

        tk.Label(p, text="ID (for Ack, 0=auto)", bg=PANEL_BG, fg=TEXT_SEC,
                 font=("Segoe UI",9)).pack(anchor="w", pady=(8,2))
        self.lcp_ack_id = self._entry(p, width=6); self.lcp_ack_id.insert(0,"1")
        self.lcp_ack_id.pack(anchor="w")

        self._btn(p, "Generate LCP Packet", self._gen_lcp, width=24).pack(pady=(12,0), anchor="w")

    def _build_pap_tab(self):
        p = self._tab_pap
        tk.Label(p, text="PAP – Password Authentication Protocol", bg=PANEL_BG,
                 fg=ACCENT2, font=("Segoe UI",9,"bold")).pack(anchor="w", pady=(0,6))
        tk.Label(p, text="Airtel APN credentials:", bg=PANEL_BG,
                 fg=TEXT_SEC, font=("Segoe UI",8)).pack(anchor="w")

        self.pap_user = self._entry(p, width=20); self.pap_user.insert(0,"airtelgprs.com")
        self.pap_pass = self._entry(p, width=20); self.pap_pass.insert(0,"")
        self._row(p, "Username", self.pap_user)
        self._row(p, "Password", self.pap_pass)
        self._btn(p, "Generate PAP Auth-Request", self._gen_pap, width=26).pack(pady=(12,0), anchor="w")

    def _build_ipcp_tab(self):
        p = self._tab_ipcp
        tk.Label(p, text="IPCP – IP Control Protocol", bg=PANEL_BG,
                 fg=ACCENT2, font=("Segoe UI",9,"bold")).pack(anchor="w", pady=(0,6))

        self.ipcp_ip   = self._entry(p, width=16); self.ipcp_ip.insert(0,"0.0.0.0")
        self.ipcp_dns1 = self._entry(p, width=16); self.ipcp_dns1.insert(0,"0.0.0.0")
        self._row(p, "Requested IP", self.ipcp_ip)
        self._row(p, "Primary DNS", self.ipcp_dns1)

        pkt_var = tk.StringVar(value="Configure-Request")
        tk.Label(p, text="Packet Type", bg=PANEL_BG, fg=TEXT_SEC,
                 font=("Segoe UI",9)).pack(anchor="w", pady=(8,2))
        self.ipcp_pkt_type = ttk.Combobox(p,
            values=["Configure-Request","Configure-Ack"], textvariable=pkt_var,
            state="readonly", width=22)
        self.ipcp_pkt_type.pack(anchor="w")

        self.ipcp_ack_id = self._entry(p, width=6); self.ipcp_ack_id.insert(0,"1")
        self._row(p, "ID (for Ack)", self.ipcp_ack_id)

        self._btn(p, "Generate IPCP Packet", self._gen_ipcp, width=24).pack(pady=(12,0), anchor="w")

    def _build_icmp_tab(self):
        p = self._tab_icmp
        tk.Label(p, text="ICMP – Echo Request (Ping)", bg=PANEL_BG,
                 fg=ACCENT2, font=("Segoe UI",9,"bold")).pack(anchor="w", pady=(0,6))

        self.icmp_src = self._entry(p, width=16); self.icmp_src.insert(0,"0.0.0.0")
        self.icmp_dst = self._entry(p, width=16); self.icmp_dst.insert(0,"8.8.8.8")
        self.icmp_seq = self._entry(p, width=6);  self.icmp_seq.insert(0,"1")
        self.icmp_pay = self._entry(p, width=20); self.icmp_pay.insert(0,"Cavli-PPP-Test")
        self._row(p, "Source IP", self.icmp_src)
        self._row(p, "Dest IP", self.icmp_dst)
        self._row(p, "Sequence", self.icmp_seq)
        self._row(p, "Payload text", self.icmp_pay)

        tk.Label(p, text="(Set src to your assigned IP from IPCP Nak)", bg=PANEL_BG,
                 fg=TEXT_SEC, font=("Segoe UI",8)).pack(anchor="w", pady=(4,0))

        self._btn(p, "Generate Ping Packet", self._gen_icmp, color=ACCENT2, width=24).pack(pady=(12,0), anchor="w")

    def _build_decoder(self, parent):
        tk.Label(parent, text="PACKET DECODER", bg=DARK_BG, fg=ACCENT,
                 font=("Consolas", 10, "bold")).pack(anchor="w", padx=4, pady=(4,0))

        f = self._frame(parent)
        f.pack(fill="x", padx=2, pady=4)
        tk.Label(f, text="Paste Cavli hex response (space/colon separated or raw):",
                 bg=PANEL_BG, fg=TEXT_SEC, font=("Segoe UI",9)).pack(anchor="w", padx=8, pady=(6,2))
        self.dec_input = scrolledtext.ScrolledText(f, height=6, bg="#0D1117", fg=ACCENT,
            font=MONO_FONT, relief="flat", bd=0, insertbackground=ACCENT,
            highlightthickness=1, highlightbackground=BORDER, wrap=tk.WORD)
        self.dec_input.pack(fill="x", padx=8, pady=(0,4))

        bf = tk.Frame(f, bg=PANEL_BG)
        bf.pack(fill="x", padx=8, pady=(0,8))
        self._btn(bf, "Decode Packet", self._decode, width=18).pack(side="left", padx=(0,6))
        self._btn(bf, "Clear", lambda: self.dec_input.delete("1.0",tk.END), color="#21262D", width=8).pack(side="left")

        tk.Label(parent, text="DECODED OUTPUT", bg=DARK_BG, fg=ACCENT,
                 font=("Consolas", 10, "bold")).pack(anchor="w", padx=4, pady=(2,0))
        self.dec_out = self._text_out(parent, h=10)
        self.dec_out.pack(fill="both", expand=True, padx=2, pady=(0,4))

        # Advisor
        tk.Label(parent, text="NEXT STEP ADVISOR", bg=DARK_BG, fg=ACCENT,
                 font=("Consolas", 10, "bold")).pack(anchor="w", padx=4)
        af = self._frame(parent)
        af.pack(fill="x", padx=2, pady=(0,4))
        self.advisor_lbl = tk.Label(af, text="Paste a decoded packet to get suggestions.",
                                    bg=PANEL_BG, fg=ACCENT2,
                                    font=("Segoe UI", 10), wraplength=500,
                                    justify="left", padx=12, pady=10)
        self.advisor_lbl.pack(fill="x")

        self._btn(parent, "Reset PPP State Machine", self._reset_state,
                  color=WARN, width=26).pack(anchor="w", padx=4, pady=(0,4))

    # ── generators ──
    def _emit(self, pkt: bytes, label: str):
        hex_spaced = " ".join(f"{b:02X}" for b in pkt)
        self._write(self.build_out, f"── {label} ──", ACCENT, clear=False)
        self._write(self.build_out, f"Length: {len(pkt)} bytes", TEXT_SEC)
        self._write(self.build_out, hex_spaced, ACCENT2)

    def _gen_lcp(self):
        try:
            ptype = self.lcp_pkt_type.get()
            if ptype == "Configure-Request":
                mru = int(self.lcp_mru.get())
                mag = int(self.lcp_magic.get(), 16)
                pkt = build_lcp_configure_request(mag, mru)
                self._emit(pkt, "LCP Configure-Request")
                self.ppp_state["lcp_local_sent"] = True
            elif ptype == "Configure-Ack":
                ident = int(self.lcp_ack_id.get())
                pkt = build_lcp_configure_ack(ident, b"")
                self._emit(pkt, f"LCP Configure-Ack (id={ident})")
            elif ptype == "Terminate-Request":
                pkt = build_lcp_terminate_request()
                self._emit(pkt, "LCP Terminate-Request")
            elif ptype == "Echo-Request":
                mag = int(self.lcp_magic.get(), 16)
                pkt = build_lcp_echo_request(mag)
                self._emit(pkt, "LCP Echo-Request")
        except Exception as e:
            self._write(self.build_out, f"Error: {e}", WARN)

    def _gen_pap(self):
        try:
            user = self.pap_user.get()
            pw   = self.pap_pass.get()
            pkt  = build_pap_request(user, pw)
            self._emit(pkt, f"PAP Auth-Request ({user})")
        except Exception as e:
            self._write(self.build_out, f"Error: {e}", WARN)

    def _gen_ipcp(self):
        try:
            ptype = self.ipcp_pkt_type.get()
            ip    = self.ipcp_ip.get()
            dns   = self.ipcp_dns1.get()
            if ptype == "Configure-Request":
                pkt = build_ipcp_configure_request(ip, dns)
                self._emit(pkt, f"IPCP Configure-Request IP={ip}")
            elif ptype == "Configure-Ack":
                ident = int(self.ipcp_ack_id.get())
                pkt = build_ipcp_configure_ack(ident, b"")
                self._emit(pkt, f"IPCP Configure-Ack (id={ident})")
        except Exception as e:
            self._write(self.build_out, f"Error: {e}", WARN)

    def _gen_icmp(self):
        try:
            src = self.icmp_src.get()
            dst = self.icmp_dst.get()
            seq = int(self.icmp_seq.get())
            pay = self.icmp_pay.get()
            pkt = build_icmp_echo(src, dst, seq, pay)
            self._emit(pkt, f"ICMP Echo-Request {src}→{dst} seq={seq}")
            self.icmp_seq.delete(0, tk.END)
            self.icmp_seq.insert(0, str(seq + 1))
        except Exception as e:
            self._write(self.build_out, f"Error: {e}", WARN)

    def _decode(self):
        raw = self.dec_input.get("1.0", tk.END).strip()
        if not raw:
            messagebox.showwarning("Empty", "Paste hex data first.")
            return
        result = decode_ppp(raw)
        self._write(self.dec_out, "═"*52, BORDER, clear=True)
        if "error" in result:
            self._write(self.dec_out, f"ERROR: {result['error']}", WARN)
        else:
            self._write(self.dec_out, f"Protocol: {result.get('proto_name','?')}  ({result.get('raw_len',0)} bytes)", ACCENT)
            for line in result.get("lines", []):
                color = ACCENT2 if "✓" in line else (WARN if ("✗" in line or "❌" in line) else TEXT_PRI)
                self._write(self.dec_out, "  " + line, color)
        suggestion = suggest_next(result, self.ppp_state)
        self.advisor_lbl.configure(text=suggestion)

    def _clear_all(self):
        self.build_out.configure(state="normal"); self.build_out.delete("1.0",tk.END); self.build_out.configure(state="disabled")
        self.dec_out.configure(state="normal"); self.dec_out.delete("1.0",tk.END); self.dec_out.configure(state="disabled")
        self.dec_input.delete("1.0", tk.END)
        self.advisor_lbl.configure(text="Paste a decoded packet to get suggestions.")

    def _reset_state(self):
        self.ppp_state.clear()
        self.advisor_lbl.configure(text="✔  PPP state machine reset. Start from LCP Configure-Request.")
        self._write(self.dec_out, "PPP state machine reset.", WARN)

if __name__ == "__main__":
    app = PPPTool()
    app.mainloop()
