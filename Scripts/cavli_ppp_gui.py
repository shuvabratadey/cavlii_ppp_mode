import os, random, struct, time, threading, queue, serial, serial.tools.list_ports
import tkinter as tk
from tkinter import ttk, scrolledtext, font as tkfont

# ── PPP constants ─────────────────────────────────────────────────────────────
PPP_FLAG   = 0x7E
PPP_ESCAPE = 0x7D
PPP_TRANS  = 0x20
PROTO_IP   = 0x0021
PROTO_LCP  = 0xC021
PROTO_IPCP = 0x8021
CONF_REQ=1; CONF_ACK=2; CONF_NAK=3; CONF_REJ=4
TERM_REQ=5; TERM_ACK=6; ECHO_REQ=9; ECHO_REPLY=10

LCP_CODE_NAMES = {
    1:"CONF-REQ", 2:"CONF-ACK", 3:"CONF-NAK", 4:"CONF-REJ",
    5:"TERM-REQ", 6:"TERM-ACK", 9:"ECHO-REQ", 10:"ECHO-REPLY"
}
PROTO_NAMES = {
    PROTO_IP:   "IP",
    PROTO_LCP:  "LCP",
    PROTO_IPCP: "IPCP",
    0x0057:     "IPv6",
    0x8057:     "IPv6CP",
    0xC023:     "PAP",
    0xC223:     "CHAP",
}

ICMP_TYPE_NAMES = {0:"ECHO-REPLY", 3:"DEST-UNREACHABLE", 8:"ECHO-REQ",
                   11:"TIME-EXCEEDED", 12:"PARAM-PROBLEM"}
IP_PROTO_NAMES  = {1:"ICMP", 6:"TCP", 17:"UDP", 41:"IPv6", 89:"OSPF"}

# ── PPP helpers ───────────────────────────────────────────────────────────────
def checksum(data):
    if len(data) % 2: data += b"\x00"
    t = 0
    for i in range(0, len(data), 2):
        t += (data[i] << 8) + data[i+1]
        t = (t & 0xFFFF) + (t >> 16)
    return (~t) & 0xFFFF

def ppp_fcs16(data):
    fcs = 0xFFFF
    for b in data:
        fcs ^= b
        for _ in range(8):
            fcs = (fcs >> 1) ^ 0x8408 if fcs & 1 else fcs >> 1
            fcs &= 0xFFFF
    return fcs ^ 0xFFFF

def ppp_escape_wrap(data):
    out = bytearray([PPP_FLAG])
    for b in data:
        if b in (PPP_FLAG, PPP_ESCAPE) or b < 0x20:
            out += bytes([PPP_ESCAPE, b ^ PPP_TRANS])
        else:
            out.append(b)
    out.append(PPP_FLAG)
    return bytes(out)

def make_frame(proto, payload):
    raw = b"\xff\x03" + struct.pack("!H", proto) + payload
    return ppp_escape_wrap(raw + struct.pack("<H", ppp_fcs16(raw)))

def lcp_pkt(code, ident, data=b""):
    l = 4 + len(data)
    return struct.pack("!BBH", code, ident, l) + data

def parse_ctrl(payload):
    if len(payload) < 4: return None
    code, ident, length = struct.unpack("!BBH", payload[:4])
    if length > len(payload): return None
    return code, ident, payload[4:length]

def ip2b(ip):  return bytes(int(x) for x in ip.split("."))
def b2ip(b):   return ".".join(str(x) for x in b)

def parse_ipcp_opts(data):
    opts, i = {}, 0
    while i+2 <= len(data):
        t, l = data[i], data[i+1]
        if l < 2 or i+l > len(data): break
        opts[t] = data[i+2:i+l]; i += l
    return opts

def make_ipcp_opts(ip="0.0.0.0", d1="0.0.0.0", d2="0.0.0.0"):
    return b"\x03\x06"+ip2b(ip)+b"\x81\x06"+ip2b(d1)+b"\x83\x06"+ip2b(d2)

def make_ip_pkt(src, dst, payload, proto=1, ident=0):
    tl = 20 + len(payload)
    h0 = struct.pack("!BBHHHBBH4s4s", 0x45,0,tl,ident,0,64,proto,0, ip2b(src),ip2b(dst))
    cs = checksum(h0)
    h  = struct.pack("!BBHHHBBH4s4s", 0x45,0,tl,ident,0,64,proto,cs,ip2b(src),ip2b(dst))
    return h + payload

def make_icmp(ident, seq, data=b"cavli-gui-ppp"):
    h0 = struct.pack("!BBHHH", 8,0,0,ident,seq)
    cs = checksum(h0+data)
    return struct.pack("!BBHHH", 8,0,cs,ident,seq) + data

def parse_ip(pkt):
    if len(pkt)<20: return None
    v,ihl = pkt[0]>>4, (pkt[0]&0xF)*4
    if v!=4 or len(pkt)<ihl: return None
    tl = struct.unpack("!H",pkt[2:4])[0]
    if tl>len(pkt): return None
    return b2ip(pkt[12:16]), b2ip(pkt[16:20]), pkt[9], pkt[ihl:tl]

def parse_icmp_reply(p):
    if len(p)<8: return None
    t,c,_,i,s = struct.unpack("!BBHHH",p[:8])
    return (i,s,p[8:]) if t==0 and c==0 else None

# ── Raw byte hex dump helper ──────────────────────────────────────────────────
def hex_dump(data, direction, prefix=""):
    """
    Format raw bytes as a readable hex dump with ASCII sidebar.
    Returns a list of (line_str, tag) tuples.
    """
    tag = "raw_tx" if direction == "TX" else "raw_rx"
    lines = []
    label = f"  {'TX' if direction=='TX' else 'RX'} RAW {prefix}  ({len(data)} bytes)"
    lines.append((label, tag))
    for off in range(0, len(data), 16):
        chunk = data[off:off+16]
        hex_part  = " ".join(f"{b:02X}" for b in chunk)
        # pad to 48 chars (16 bytes * 3)
        hex_part  = hex_part.ljust(48)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append((f"  {off:04X}  {hex_part}  {ascii_part}", tag))
    return lines

# ── Packet description helpers ────────────────────────────────────────────────
def describe_lcp(payload, direction):
    p = parse_ctrl(payload)
    if not p:
        return f"LCP [{direction}] (unparseable)"
    code, ident, data = p
    cname = LCP_CODE_NAMES.get(code, f"code={code}")
    extra = ""
    if code in (CONF_REQ, CONF_ACK, CONF_NAK, CONF_REJ) and data:
        extra = f"  opts={data.hex()}"
    elif code in (ECHO_REQ, ECHO_REPLY):
        magic = data[:4].hex() if len(data) >= 4 else ""
        extra = f"  magic=0x{magic}"
    elif code in (TERM_REQ, TERM_ACK):
        reason = data.decode(errors="replace").strip() if data else ""
        extra = f"  reason='{reason}'" if reason else ""
    return f"LCP [{direction}] {cname}  id={ident}{extra}"

def describe_ipcp(payload, direction):
    p = parse_ctrl(payload)
    if not p:
        return f"IPCP [{direction}] (unparseable)"
    code, ident, data = p
    cname = LCP_CODE_NAMES.get(code, f"code={code}")
    extra = ""
    if data:
        opts = parse_ipcp_opts(data)
        parts = []
        if 3 in opts and len(opts[3]) == 4:
            parts.append(f"IP={b2ip(opts[3])}")
        if 129 in opts and len(opts[129]) == 4:
            parts.append(f"DNS1={b2ip(opts[129])}")
        if 131 in opts and len(opts[131]) == 4:
            parts.append(f"DNS2={b2ip(opts[131])}")
        if parts:
            extra = "  " + "  ".join(parts)
    return f"IPCP [{direction}] {cname}  id={ident}{extra}"

def describe_ip(payload, direction):
    parsed = parse_ip(payload)
    if not parsed:
        return f"IP [{direction}] (unparseable)  raw={payload[:8].hex()}"
    src, dst, iproto, body = parsed
    pname = IP_PROTO_NAMES.get(iproto, f"proto={iproto}")
    extra = ""
    if iproto == 1 and len(body) >= 8:
        itype, icode = body[0], body[1]
        tname = ICMP_TYPE_NAMES.get(itype, f"type={itype}")
        ident = seq = None
        if itype in (0, 8) and len(body) >= 8:
            _, _, _, ident, seq = struct.unpack("!BBHHH", body[:8])
        extra = f"  ICMP {tname}"
        if ident is not None:
            extra += f"  id={ident}  seq={seq}"
    return f"IP [{direction}] {pname}  {src} → {dst}  len={len(payload)}{extra}"

def describe_packet(proto, payload, direction):
    pname = PROTO_NAMES.get(proto, f"0x{proto:04X}")
    if proto == PROTO_LCP:
        return describe_lcp(payload, direction), "pkt_lcp"
    elif proto == PROTO_IPCP:
        return describe_ipcp(payload, direction), "pkt_ipcp"
    elif proto == PROTO_IP:
        desc = describe_ip(payload, direction)
        tag  = "pkt_ip_rx" if direction == "RX" else "pkt_ip_tx"
        return desc, tag
    else:
        return f"{pname} [{direction}]  len={len(payload)}  raw={payload[:8].hex()}", "pkt_other"

# ── PPPReader ─────────────────────────────────────────────────────────────────
class PPPReader:
    def __init__(self, ser):
        self.ser=ser; self.buf=bytearray(); self.esc=False
        self._last_raw=b""   # stores the escaped wire bytes of the last complete frame

    def read_frame(self, timeout=0.5):
        end=time.time()+timeout
        while time.time()<end:
            b=self.ser.read(1)
            if not b: continue
            c=b[0]
            if c==PPP_FLAG:
                if len(self.buf)>=6:
                    f=bytes(self.buf); self.buf.clear(); self.esc=False
                    p=self._parse(f)
                    if p: return p
                else:
                    self.buf.clear(); self.esc=False
                continue
            if c==PPP_ESCAPE: self.esc=True; continue
            if self.esc: c^=PPP_TRANS; self.esc=False
            self.buf.append(c)
        return None

    def _parse(self, frame):
        if len(frame)<6: return None
        d=frame[:-2]; rx=struct.unpack("<H",frame[-2:])[0]
        if rx!=ppp_fcs16(d): return None
        if d[0:2]!=b"\xff\x03": return None
        proto=struct.unpack("!H",d[2:4])[0]
        # store decoded payload for raw dump
        self._last_raw = d[4:]   # payload bytes (after addr/ctrl/proto)
        return proto, d[4:]

# ── Worker thread ─────────────────────────────────────────────────────────────
class PPPWorker(threading.Thread):
    def __init__(self, port, baud, apn, target, interval,
                 log_q, status_q, ip_result_q, stop_event, show_raw):
        super().__init__(daemon=True)
        self.port=port; self.baud=baud
        self.apn=apn; self.target=target; self.interval=interval
        self.log_q=log_q; self.status_q=status_q
        self.ip_result_q=ip_result_q
        self.stop=stop_event
        self.show_raw=show_raw
        self.ser=None

    def log(self, msg, tag="info"):
        self.log_q.put((msg, tag))

    def log_raw(self, data, direction, prefix=""):
        """Emit hex dump lines only when show_raw is checked."""
        if not self.show_raw.get():
            return
        for line, tag in hex_dump(data, direction, prefix):
            self.log_q.put((line, tag))

    def log_pkt(self, proto, payload, direction):
        """Log decoded packet description (always shown when raw is on)."""
        if not self.show_raw.get():
            return
        desc, tag = describe_packet(proto, payload, direction)
        self.log_q.put((desc, tag))

    def status(self, s, color=None):
        self.status_q.put((s, color))

    def at(self, cmd, timeout=3.0):
        self.ser.reset_input_buffer()
        self.ser.write((cmd+"\r").encode()); self.ser.flush()
        end=time.time()+timeout; rx=b""
        while time.time()<end:
            c=self.ser.read(256)
            if c:
                rx+=c
                t=rx.decode(errors="ignore")
                if "OK" in t or "ERROR" in t: break
            time.sleep(0.05)
        text=rx.decode(errors="ignore").strip()
        self.log(f">>> {cmd}", "cmd")
        self.log(text if text else "(no response)", "at")
        return text

    def write_ppp(self, proto, payload):
        frame = make_frame(proto, payload)
        # log decoded description
        self.log_pkt(proto, payload, "TX")
        # log raw wire bytes
        self.log_raw(frame, "TX", f"proto=0x{proto:04X}")
        self.ser.write(frame); self.ser.flush()

    def is_reg(self, r): return ",1" in r or ",5" in r

    def wait_network(self, timeout=180):
        self.log("Waiting for network registration…", "info")
        end=time.time()+timeout
        while time.time()<end:
            if self.stop.is_set(): return False
            csq=self.at("AT+CSQ")
            creg=self.at("AT+CREG?"); cereg=self.at("AT+CEREG?")
            cgatt=self.at("AT+CGATT?")
            reg=self.is_reg(creg) or self.is_reg(cereg)
            att="+CGATT: 1" in cgatt
            if reg and att:
                self.log("Network ready.", "ok"); return True
            if reg and not att:
                self.log("Registered – forcing CGATT=1…", "warn")
                self.at("AT+CGATT=1", timeout=15)
            self.log("Not ready, retry in 5 s…", "warn")
            for _ in range(50):
                if self.stop.is_set(): return False
                time.sleep(0.1)
        self.log("Network timeout.", "err"); return False

    def wait_pppstart(self, timeout=15):
        end=time.time()+timeout; rx=b""
        while time.time()<end:
            c=self.ser.read(256)
            if c:
                rx+=c; t=rx.decode(errors="ignore")
                if "CONNECT" in t or "+PPPSTART" in t:
                    self.log(t.strip(), "ok"); return True
                if "ERROR" in t:
                    self.log(t.strip(), "err"); return False
            time.sleep(0.05)
        return False

    def enter_ppp(self):
        self.at("AT",timeout=3); self.at("ATE0",timeout=3)
        self.at("AT+CMEE=2",timeout=3)
        cpin=self.at("AT+CPIN?",timeout=3)
        if "READY" not in cpin:
            raise RuntimeError("SIM not ready.")
        self.at("AT+CFUN=1",timeout=10)
        self.at("AT+COPS=0",timeout=10)
        self.at("AT+CREG=1",timeout=3); self.at("AT+CEREG=1",timeout=3)
        if not self.wait_network(): raise RuntimeError("Network registration failed.")
        if self.apn:
            self.at(f'AT+CGDCONT=1,"IP","{self.apn}"',timeout=5)
        self.at("AT+CGDCONT?",timeout=5)
        self.at("AT+CGACT=1,1",timeout=20)
        self.at("AT+CGACT?",timeout=5)
        self.ser.reset_input_buffer()
        self.ser.write(b"AT+PPPSTART\r"); self.ser.flush()
        self.log(">>> AT+PPPSTART","cmd")
        if not self.wait_pppstart():
            raise RuntimeError("AT+PPPSTART failed.")
        self.log("PPP mode started.","ok")

    def negotiate_lcp(self, reader, timeout=25):
        self.log("LCP negotiation…","info")
        self.status("LCP…","#f0c040")
        my_id=1; magic=random.randint(1,0xFFFFFFFF)
        opts=b"\x01\x04"+struct.pack("!H",1500)+b"\x05\x06"+struct.pack("!I",magic)
        got_ack=acked_peer=False; next_send=0; end=time.time()+timeout
        while time.time()<end:
            if self.stop.is_set(): raise RuntimeError("Stopped by user.")
            if time.time()>=next_send and not got_ack:
                self.write_ppp(PROTO_LCP, lcp_pkt(CONF_REQ,my_id,opts))
                next_send=time.time()+3
            item=reader.read_frame(0.4)
            if not item: continue
            proto,payload=item
            # log RX decoded description
            self.log_pkt(proto, payload, "RX")
            # log RX raw bytes (full unescaped frame payload)
            rx_raw = b"\xff\x03" + struct.pack("!H", proto) + payload
            self.log_raw(rx_raw, "RX", f"proto=0x{proto:04X}")
            if proto!=PROTO_LCP: continue
            p=parse_ctrl(payload)
            if not p: continue
            code,ident,data=p
            if code==CONF_REQ:
                self.write_ppp(PROTO_LCP,lcp_pkt(CONF_ACK,ident,data))
                acked_peer=True; self.log("LCP: peer ACKed","ok")
            elif code==CONF_ACK and ident==my_id:
                got_ack=True; self.log("LCP: our Req ACKed","ok")
            elif code==CONF_NAK and ident==my_id:
                opts=data; my_id=(my_id+1)&0xFF or 1
                got_ack=False; next_send=0; self.log("LCP: NAK, retry","warn")
            elif code==CONF_REJ and ident==my_id:
                opts=b""; my_id=(my_id+1)&0xFF or 1
                got_ack=False; next_send=0; self.log("LCP: REJ, retry","warn")
            elif code==ECHO_REQ:
                self.write_ppp(PROTO_LCP,lcp_pkt(ECHO_REPLY,ident,data))
            elif code==TERM_REQ:
                self.write_ppp(PROTO_LCP,lcp_pkt(TERM_ACK,ident,data))
                raise RuntimeError("Peer terminated during LCP.")
            if got_ack and acked_peer:
                self.log("LCP complete.","ok"); return
        raise TimeoutError("LCP timeout.")

    def negotiate_ipcp(self, reader, timeout=35):
        self.log("IPCP negotiation…","info")
        self.status("IPCP…","#f0c040")
        my_id=10; rip="0.0.0.0"; d1="0.0.0.0"; d2="0.0.0.0"
        got_ack=acked_peer=False; next_send=0; end=time.time()+timeout
        while time.time()<end:
            if self.stop.is_set(): raise RuntimeError("Stopped by user.")
            if time.time()>=next_send and not got_ack:
                self.write_ppp(PROTO_IPCP, lcp_pkt(CONF_REQ,my_id,make_ipcp_opts(rip,d1,d2)))
                next_send=time.time()+3
            item=reader.read_frame(0.4)
            if not item: continue
            proto,payload=item
            self.log_pkt(proto, payload, "RX")
            rx_raw = b"\xff\x03" + struct.pack("!H", proto) + payload
            self.log_raw(rx_raw, "RX", f"proto=0x{proto:04X}")
            if proto==PROTO_LCP:
                p=parse_ctrl(payload)
                if p and p[0]==ECHO_REQ:
                    self.write_ppp(PROTO_LCP,lcp_pkt(ECHO_REPLY,p[1],p[2]))
                continue
            if proto!=PROTO_IPCP: continue
            p=parse_ctrl(payload)
            if not p: continue
            code,ident,data=p
            if code==CONF_REQ:
                self.write_ppp(PROTO_IPCP,lcp_pkt(CONF_ACK,ident,data))
                acked_peer=True; self.log("IPCP: peer ACKed","ok")
            elif code==CONF_ACK and ident==my_id:
                got_ack=True; self.log("IPCP: our Req ACKed","ok")
            elif code==CONF_NAK and ident==my_id:
                opts=parse_ipcp_opts(data)
                if 3 in opts and len(opts[3])==4:   rip=b2ip(opts[3])
                if 129 in opts and len(opts[129])==4: d1=b2ip(opts[129])
                if 131 in opts and len(opts[131])==4: d2=b2ip(opts[131])
                self.log(f"IPCP NAK → IP={rip} DNS1={d1} DNS2={d2}","warn")
                my_id=(my_id+1)&0xFF or 10; got_ack=False; next_send=0
            elif code==CONF_REJ and ident==my_id:
                self.log("IPCP REJ, IP-only retry","warn")
                opts=b"\x03\x06"+ip2b(rip); my_id=(my_id+1)&0xFF or 10
                self.write_ppp(PROTO_IPCP,lcp_pkt(CONF_REQ,my_id,opts))
                next_send=time.time()+3
            if got_ack and acked_peer:
                self.log(f"IPCP complete. IP={rip}  DNS1={d1}  DNS2={d2}","ok")
                return rip, d1, d2
        raise TimeoutError("IPCP timeout.")

    def ping_once(self, reader, src, dst, ident, seq, timeout=5):
        icmp=make_icmp(ident,seq)
        pkt=make_ip_pkt(src,dst,icmp,proto=1,ident=seq)
        t0=time.time()
        self.write_ppp(PROTO_IP,pkt)
        while time.time()-t0<timeout:
            if self.stop.is_set(): return None,None
            item=reader.read_frame(0.4)
            if not item: continue
            proto,payload=item
            self.log_pkt(proto, payload, "RX")
            rx_raw = b"\xff\x03" + struct.pack("!H", proto) + payload
            self.log_raw(rx_raw, "RX", f"proto=0x{proto:04X}")
            if proto==PROTO_LCP:
                p=parse_ctrl(payload)
                if p and p[0]==ECHO_REQ:
                    self.write_ppp(PROTO_LCP,lcp_pkt(ECHO_REPLY,p[1],p[2]))
                continue
            if proto!=PROTO_IP: continue
            ip=parse_ip(payload)
            if not ip: continue
            src2,dst2,iproto,ippayload=ip
            if iproto!=1: continue
            r=parse_icmp_reply(ippayload)
            if r and r[0]==ident and r[1]==seq:
                return src2, (time.time()-t0)*1000
        return None, None

    def stop_ppp(self):
        try:
            self.write_ppp(PROTO_LCP, lcp_pkt(TERM_REQ,99,b"bye"))
            time.sleep(0.8)
        except: pass

    def run_mode3(self):
        self.status("AT setup…","#f0c040")
        self.enter_ppp()
        reader=PPPReader(self.ser)
        self.negotiate_lcp(reader)
        local_ip,d1,d2=self.negotiate_ipcp(reader)
        if local_ip=="0.0.0.0":
            raise RuntimeError("Got 0.0.0.0 – IPCP incomplete.")
        self.log("━"*44,"sep")
        self.log(f"  Local IP : {local_ip}","result")
        self.log(f"  DNS1     : {d1}  DNS2: {d2}","result")
        self.log(f"  Target   : {self.target}","result")
        self.log("━"*44,"sep")
        self.status(f"Pinging {self.target}","#40c0ff")
        self.ip_result_q.put(local_ip)
        ident=os.getpid()&0xFFFF; seq=1
        while not self.stop.is_set():
            src,ms=self.ping_once(reader,local_ip,self.target,ident,seq)
            if src:
                self.log(f"Reply from {src}:  seq={seq}  time={ms:.1f} ms","ping_ok")
            else:
                self.log(f"Timeout  seq={seq}","ping_to")
            seq=(seq+1)&0xFFFF or 1
            for _ in range(int(self.interval*10)):
                if self.stop.is_set(): break
                time.sleep(0.1)
        self.stop_ppp()

    def run(self):
        try:
            self.ser=serial.Serial(
                port=self.port, baudrate=self.baud,
                timeout=0.05, write_timeout=2,
                rtscts=False, dsrdtr=False)
            self.log(f"Port {self.port} opened @ {self.baud} baud.","ok")
            self.run_mode3()
        except Exception as e:
            self.log(f"ERROR: {e}","err")
            self.status("Error","#ff4444")
        finally:
            try:
                if self.ser and self.ser.is_open: self.ser.close()
            except: pass
            self.log("Serial port closed.","info")
            self.status_q.put(("DONE", None))


# ── GUI ───────────────────────────────────────────────────────────────────────
BG     = "#0e1117"
PANEL  = "#161b25"
BORDER = "#2a3042"
ACC    = "#00d4ff"
ACC2   = "#00ff9d"
TXT    = "#dce8f0"
DIM    = "#5a6a7a"

TAG_COLORS = {
    "info":     "#8ab0c8",
    "cmd":      "#00d4ff",
    "at":       "#7a8a9a",
    "ok":       "#00ff9d",
    "warn":     "#f0c040",
    "err":      "#ff4c6a",
    "result":   "#ffffff",
    "sep":      "#2a3042",
    "ping_ok":  "#00e890",
    "ping_to":  "#ff8040",
    "pkt_lcp":    "#b57aff",
    "pkt_ipcp":   "#ff9f40",
    "pkt_ip_tx":  "#3ac8ff",
    "pkt_ip_rx":  "#60ffc0",
    "pkt_other":  "#888888",
    # raw byte dump tags
    "raw_tx":   "#3ac8ff",   # cyan  – TX wire bytes
    "raw_rx":   "#60ffc0",   # mint  – RX wire bytes
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cavli C16QS  –  PPP Test Utility")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(820, 580)

        self._worker   = None
        self._stop_evt = threading.Event()
        self._log_q    = queue.Queue()
        self._stat_q   = queue.Queue()
        self._ip_q     = queue.Queue()

        self._build_ui()
        self._refresh_ports()
        self._poll()

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=18, pady=(14,0))
        tk.Label(hdr, text="CAVLI  C16QS", bg=BG, fg=ACC,
                 font=("Courier New",20,"bold")).pack(side="left")
        tk.Label(hdr, text="PPP Test Utility", bg=BG, fg=DIM,
                 font=("Courier New",11)).pack(side="left", padx=(10,0), pady=(6,0))

        self._status_var = tk.StringVar(value="Idle")
        self._status_lbl = tk.Label(hdr, textvariable=self._status_var,
                                    bg=BG, fg=DIM,
                                    font=("Courier New",10,"bold"))
        self._status_lbl.pack(side="right", padx=4)
        tk.Label(hdr, text="STATUS:", bg=BG, fg=DIM,
                 font=("Courier New",9)).pack(side="right")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=18, pady=(10,0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=10)

        left  = tk.Frame(body, bg=BG, width=280)
        left.pack(side="left", fill="y", padx=(0,12))
        left.pack_propagate(False)

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self._build_left(left)
        self._build_right(right)

    def _section(self, parent, title):
        f = tk.LabelFrame(parent, text=f"  {title}  ", bg=PANEL,
                          fg=ACC, bd=1, relief="flat",
                          font=("Courier New",9,"bold"),
                          highlightbackground=BORDER,
                          highlightthickness=1)
        f.pack(fill="x", pady=(0,10))
        return f

    def _row(self, parent, label, widget_fn, **kw):
        r = tk.Frame(parent, bg=PANEL)
        r.pack(fill="x", padx=10, pady=3)
        tk.Label(r, text=label, bg=PANEL, fg=DIM,
                 font=("Courier New",9), width=12, anchor="w").pack(side="left")
        w = widget_fn(r, **kw)
        w.pack(side="left", fill="x", expand=True)
        return w

    def _entry(self, parent, default="", **kw):
        e = tk.Entry(parent, bg="#1e2535", fg=TXT, insertbackground=ACC,
                     relief="flat", bd=4,
                     font=("Courier New",10), **kw)
        e.insert(0, default)
        return e

    def _build_left(self, parent):
        # Serial Port
        sec = self._section(parent, "Serial Port")
        r = tk.Frame(sec, bg=PANEL); r.pack(fill="x", padx=10, pady=3)
        tk.Label(r, text="Port", bg=PANEL, fg=DIM,
                 font=("Courier New",9), width=12, anchor="w").pack(side="left")
        self._port_var = tk.StringVar()
        self._port_cb  = ttk.Combobox(r, textvariable=self._port_var,
                                       font=("Courier New",10), width=14, state="readonly")
        self._port_cb.pack(side="left", fill="x", expand=True)
        btn_rf = tk.Button(r, text="⟳", bg=PANEL, fg=ACC, relief="flat",
                           font=("Courier New",11), cursor="hand2",
                           command=self._refresh_ports)
        btn_rf.pack(side="left", padx=(4,0))

        r2 = tk.Frame(sec, bg=PANEL); r2.pack(fill="x", padx=10, pady=3)
        tk.Label(r2, text="Baud", bg=PANEL, fg=DIM,
                 font=("Courier New",9), width=12, anchor="w").pack(side="left")
        self._baud_var = tk.StringVar(value="115200")
        baud_cb = ttk.Combobox(r2, textvariable=self._baud_var,
                                font=("Courier New",10), width=14,
                                values=["9600","19200","38400","57600","115200","230400","460800"])
        baud_cb.pack(side="left", fill="x", expand=True)

        # Connection
        sec2 = self._section(parent, "Connection")
        self._apn_e    = self._row(sec2, "APN",       self._entry, default="airtelgprs.com")
        self._target_e = self._row(sec2, "Target IP",  self._entry, default="8.8.8.8")
        self._intv_e   = self._row(sec2, "Interval s", self._entry, default="1.0")

        # Options
        sec3 = self._section(parent, "Options")
        self._show_raw = tk.BooleanVar(value=False)
        chk = tk.Checkbutton(sec3,
                             text="Show raw packets (hex dump)\nfor TX and RX",
                             variable=self._show_raw,
                             bg=PANEL, fg=TXT, selectcolor=BG,
                             activebackground=PANEL, activeforeground=ACC,
                             font=("Courier New",8), cursor="hand2",
                             justify="left")
        chk.pack(anchor="w", padx=12, pady=(4,6))

        # Buttons
        bf = tk.Frame(parent, bg=BG)
        bf.pack(fill="x", pady=(4,0))
        self._btn_start = tk.Button(bf, text="▶  START", bg=ACC2, fg="#071a0e",
                                     font=("Courier New",11,"bold"), relief="flat",
                                     bd=0, padx=10, pady=7, cursor="hand2",
                                     command=self._start)
        self._btn_start.pack(fill="x", pady=(0,6))
        self._btn_stop = tk.Button(bf, text="■  STOP", bg="#ff4c6a", fg="#1a000a",
                                    font=("Courier New",11,"bold"), relief="flat",
                                    bd=0, padx=10, pady=7, cursor="hand2",
                                    state="disabled", command=self._stop)
        self._btn_stop.pack(fill="x")

    def _build_right(self, parent):
        hdr = tk.Frame(parent, bg=BG)
        hdr.pack(fill="x", pady=(0,6))
        tk.Label(hdr, text="LOG OUTPUT", bg=BG, fg=ACC,
                 font=("Courier New",9,"bold")).pack(side="left")

        # Legend
        legend = tk.Frame(hdr, bg=BG)
        legend.pack(side="left", padx=(16,0))
        for label, color in [("LCP","#b57aff"),("IPCP","#ff9f40"),
                              ("IP-TX","#3ac8ff"),("IP-RX","#60ffc0"),
                              ("RAW-TX","#3ac8ff"),("RAW-RX","#60ffc0")]:
            tk.Label(legend, text=f"■ {label}", bg=BG, fg=color,
                     font=("Courier New",7)).pack(side="left", padx=3)

        clr_btn = tk.Button(hdr, text="Clear", bg=PANEL, fg=DIM,
                             font=("Courier New",8), relief="flat", bd=0,
                             cursor="hand2", padx=6, pady=2,
                             command=self._clear_log)
        clr_btn.pack(side="right")

        self._log = scrolledtext.ScrolledText(
            parent, bg="#080c14", fg=TXT,
            font=("Courier New",10), relief="flat", bd=0,
            state="disabled", wrap="word",
            insertbackground=ACC, selectbackground=BORDER)
        self._log.pack(fill="both", expand=True)

        for tag, color in TAG_COLORS.items():
            self._log.tag_config(tag, foreground=color)
        self._log.tag_config("sep", foreground=BORDER)

        # stats bar
        sb = tk.Frame(parent, bg=PANEL)
        sb.pack(fill="x", pady=(6,0))
        self._sent_var  = tk.StringVar(value="Sent: 0")
        self._recv_var  = tk.StringVar(value="Recv: 0")
        self._loss_var  = tk.StringVar(value="Loss: —")
        self._last_var  = tk.StringVar(value="Last: —")
        for v,fg in [(self._sent_var,DIM),(self._recv_var,ACC2),
                     (self._loss_var,"#ff8040"),(self._last_var,ACC)]:
            tk.Label(sb, textvariable=v, bg=PANEL, fg=fg,
                     font=("Courier New",9), padx=12, pady=4).pack(side="left")

        self._sent=0; self._recv=0

    # ── helpers ───────────────────────────────────────────────────────────────
    def _refresh_ports(self):
        ports=[p.device for p in serial.tools.list_ports.comports()]
        self._port_cb["values"]=ports
        if ports and not self._port_var.get():
            self._port_var.set(ports[0])

    def _clear_log(self):
        self._log.config(state="normal")
        self._log.delete("1.0","end")
        self._log.config(state="disabled")
        self._sent=self._recv=0
        self._sent_var.set("Sent: 0"); self._recv_var.set("Recv: 0")
        self._loss_var.set("Loss: —"); self._last_var.set("Last: —")

    def _append_log(self, msg, tag="info"):
        self._log.config(state="normal")
        ts=time.strftime("%H:%M:%S")
        self._log.insert("end", f"[{ts}]  {msg}\n", tag)
        self._log.see("end")
        self._log.config(state="disabled")

        if tag=="ping_ok":
            self._sent+=1; self._recv+=1
            try:
                ms=float(msg.split("time=")[1].split()[0])
                self._last_var.set(f"Last: {ms:.1f} ms")
            except: pass
        elif tag=="ping_to":
            self._sent+=1
        self._sent_var.set(f"Sent: {self._sent}")
        self._recv_var.set(f"Recv: {self._recv}")
        if self._sent>0:
            loss=100*(self._sent-self._recv)//self._sent
            self._loss_var.set(f"Loss: {loss}%")

    def _set_status(self, text, color=None):
        self._status_var.set(text)
        self._status_lbl.config(fg=color or DIM)

    # ── start / stop ──────────────────────────────────────────────────────────
    def _start(self):
        port=self._port_var.get()
        if not port:
            self._append_log("No serial port selected.","err"); return
        try: baud=int(self._baud_var.get())
        except: baud=115200
        apn    = self._apn_e.get().strip()
        target = self._target_e.get().strip() or "8.8.8.8"
        try: interval=float(self._intv_e.get())
        except: interval=1.0

        self._stop_evt.clear()
        self._sent=self._recv=0
        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")
        self._set_status("Running…","#f0c040")
        self._append_log(f"Starting  port={port}  baud={baud}","info")

        self._worker=PPPWorker(
            port=port, baud=baud, apn=apn,
            target=target, interval=interval,
            log_q=self._log_q, status_q=self._stat_q,
            ip_result_q=self._ip_q,
            stop_event=self._stop_evt,
            show_raw=self._show_raw)
        self._worker.start()

    def _stop(self):
        self._stop_evt.set()
        self._btn_stop.config(state="disabled")
        self._set_status("Stopping…","#f0c040")

    def _autofill_ip(self, ip):
        self._append_log(f"Negotiated Local IP: {ip}","ok")

    # ── poll queues ───────────────────────────────────────────────────────────
    def _poll(self):
        while not self._log_q.empty():
            msg, tag = self._log_q.get_nowait()
            self._append_log(msg, tag)

        while not self._ip_q.empty():
            ip = self._ip_q.get_nowait()
            self._autofill_ip(ip)

        while not self._stat_q.empty():
            s, col = self._stat_q.get_nowait()
            if s=="DONE":
                self._btn_start.config(state="normal")
                self._btn_stop.config(state="disabled")
                if "Error" not in self._status_var.get():
                    self._set_status("Finished","#00ff9d")
            else:
                self._set_status(s, col)

        self.after(80, self._poll)


# ── Style tweaks for ttk ──────────────────────────────────────────────────────
def apply_style(app):
    s = ttk.Style(app)
    s.theme_use("default")
    s.configure("TCombobox",
                fieldbackground="#1e2535", background=PANEL,
                foreground=TXT, arrowcolor=ACC,
                selectbackground="#1e2535", selectforeground=TXT,
                relief="flat", borderwidth=0)
    s.map("TCombobox", fieldbackground=[("readonly","#1e2535")])


if __name__ == "__main__":
    app = App()
    apply_style(app)
    app.geometry("1020x640")
    app.mainloop()