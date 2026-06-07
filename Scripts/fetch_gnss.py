# ============================================================
# GNSS GUI WITH OPEN / CLOSE COM PORT IN SAME BUTTON
# ============================================================

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import serial
import serial.tools.list_ports
import threading
import time
import pynmea2
import webbrowser

# ============================================================
# COLORS
# ============================================================

BG     = "#0e1117"
PANEL  = "#161b25"
BORDER = "#2a3042"
ACC    = "#00d4ff"
ACC2   = "#00ff9d"
TXT    = "#dce8f0"
DIM    = "#5a6a7a"

# ============================================================
# MAIN APP
# ============================================================

class GNSSApp(tk.Tk):

    def __init__(self):

        super().__init__()

        self.title("Cavli C16QS GNSS Utility")
        self.geometry("1050x700")
        self.configure(bg=BG)

        self.ser = None
        self.running = False
        self.read_thread = None

        self.latitude = None
        self.longitude = None

        self.build_ui()
        self.refresh_ports()

    # ========================================================
    # UI
    # ========================================================

    def build_ui(self):

        # ====================================================
        # HEADER
        # ====================================================

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=15, pady=10)

        tk.Label(
            header,
            text="CAVLI C16QS",
            fg=ACC,
            bg=BG,
            font=("Courier New", 20, "bold")
        ).pack(side="left")

        tk.Label(
            header,
            text="GNSS MONITOR",
            fg=DIM,
            bg=BG,
            font=("Courier New", 11)
        ).pack(side="left", padx=10)

        # ====================================================
        # MAIN BODY
        # ====================================================

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=15)

        left = tk.Frame(body, bg=BG, width=320)
        left.pack(side="left", fill="y")

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=10)

        self.build_left(left)
        self.build_right(right)

    # ========================================================
    # SECTION
    # ========================================================

    def section(self, parent, title):

        frame = tk.LabelFrame(
            parent,
            text=f"  {title}  ",
            bg=PANEL,
            fg=ACC,
            font=("Courier New", 9, "bold"),
            relief="flat",
            highlightbackground=BORDER,
            highlightthickness=1
        )

        frame.pack(fill="x", pady=8)

        return frame

    # ========================================================
    # LEFT PANEL
    # ========================================================

    def build_left(self, parent):

        # ====================================================
        # SERIAL SECTION
        # ====================================================

        sec = self.section(parent, "Serial Port")

        # COM PORT

        row1 = tk.Frame(sec, bg=PANEL)
        row1.pack(fill="x", padx=10, pady=5)

        tk.Label(
            row1,
            text="COM Port",
            bg=PANEL,
            fg=DIM,
            width=10,
            anchor="w"
        ).pack(side="left")

        self.port_var = tk.StringVar()

        self.port_combo = ttk.Combobox(
            row1,
            textvariable=self.port_var,
            width=25,
            state="readonly"
        )

        self.port_combo.pack(side="left", fill="x", expand=True)

        tk.Button(
            row1,
            text="⟳",
            command=self.refresh_ports,
            bg=PANEL,
            fg=ACC,
            relief="flat",
            cursor="hand2"
        ).pack(side="left", padx=5)

        # BAUD

        row2 = tk.Frame(sec, bg=PANEL)
        row2.pack(fill="x", padx=10, pady=5)

        tk.Label(
            row2,
            text="Baud",
            bg=PANEL,
            fg=DIM,
            width=10,
            anchor="w"
        ).pack(side="left")

        self.baud_var = tk.StringVar(value="115200")

        self.baud_combo = ttk.Combobox(
            row2,
            textvariable=self.baud_var,
            values=[
                "9600",
                "19200",
                "38400",
                "57600",
                "115200",
                "230400"
            ],
            width=25,
            state="readonly"
        )

        self.baud_combo.pack(side="left", fill="x", expand=True)

        # ====================================================
        # BUTTONS
        # ====================================================

        btn_frame = tk.Frame(parent, bg=BG)
        btn_frame.pack(fill="x", pady=10)

        # SINGLE OPEN / CLOSE BUTTON

        self.port_btn = tk.Button(
            btn_frame,
            text="OPEN PORT",
            bg=ACC2,
            fg="#001a10",
            font=("Courier New", 11, "bold"),
            relief="flat",
            cursor="hand2",
            command=self.toggle_port
        )

        self.port_btn.pack(fill="x", pady=4)

        self.gnss_btn = tk.Button(
            btn_frame,
            text="START GNSS",
            bg=ACC,
            fg="#001822",
            font=("Courier New", 11, "bold"),
            relief="flat",
            cursor="hand2",
            state="disabled",
            command=self.start_gnss
        )

        self.gnss_btn.pack(fill="x", pady=4)

        self.map_btn = tk.Button(
            btn_frame,
            text="OPEN GOOGLE MAPS",
            bg="#ffaa00",
            fg="#221400",
            font=("Courier New", 11, "bold"),
            relief="flat",
            cursor="hand2",
            state="disabled",
            command=self.open_maps
        )

        self.map_btn.pack(fill="x", pady=4)

        # ====================================================
        # GNSS INFO
        # ====================================================

        info = self.section(parent, "GNSS Information")

        self.labels = {}

        fields = [
            "Fix",
            "Latitude",
            "Longitude",
            "Altitude",
            "Satellites",
            "UTC Time"
        ]

        for field in fields:

            row = tk.Frame(info, bg=PANEL)
            row.pack(fill="x", padx=10, pady=4)

            tk.Label(
                row,
                text=field,
                bg=PANEL,
                fg=DIM,
                width=12,
                anchor="w"
            ).pack(side="left")

            lbl = tk.Label(
                row,
                text="---",
                bg=PANEL,
                fg=TXT,
                anchor="w"
            )

            lbl.pack(side="left")

            self.labels[field] = lbl

    # ========================================================
    # RIGHT PANEL
    # ========================================================

    def build_right(self, parent):

        tk.Label(
            parent,
            text="LIVE NMEA DATA",
            bg=BG,
            fg=ACC,
            font=("Courier New", 10, "bold")
        ).pack(anchor="w")

        self.log_text = scrolledtext.ScrolledText(
            parent,
            bg="#080c14",
            fg=TXT,
            font=("Courier New", 10),
            relief="flat"
        )

        self.log_text.pack(fill="both", expand=True, pady=5)

    # ========================================================
    # LOG
    # ========================================================

    def log(self, msg):

        ts = time.strftime("%H:%M:%S")

        self.log_text.insert(
            "end",
            f"[{ts}] {msg}\n"
        )

        self.log_text.see("end")

    # ========================================================
    # SAFE LABEL UPDATE
    # ========================================================

    def update_label(self, name, value):

        self.after(
            0,
            lambda: self.labels[name].config(text=value)
        )

    # ========================================================
    # REFRESH PORTS
    # ========================================================

    def refresh_ports(self):

        ports = []

        for p in serial.tools.list_ports.comports():

            ports.append(
                f"{p.device} - {p.description}"
            )

        self.port_combo["values"] = ports

        if ports:
            self.port_combo.current(0)

    # ========================================================
    # TOGGLE PORT
    # ========================================================

    def toggle_port(self):

        if self.ser and self.ser.is_open:
            self.close_port()
        else:
            self.open_port()

    # ========================================================
    # OPEN PORT
    # ========================================================

    def open_port(self):

        try:

            selected = self.port_var.get()

            if not selected:
                raise Exception("No COM Port Selected")

            port = selected.split(" - ")[0]

            baud = int(self.baud_var.get())

            self.ser = serial.Serial(
                port,
                baud,
                timeout=1
            )

            self.running = True

            self.log(f"Port Opened: {port}")

            self.port_btn.config(
                text="CLOSE PORT",
                bg="#ff4c6a",
                fg="#220008",
                state="normal"
            )

            self.gnss_btn.config(state="normal")

            self.port_combo.config(state="disabled")
            self.baud_combo.config(state="disabled")

        except Exception as e:

            messagebox.showerror(
                "Error",
                str(e)
            )

    # ========================================================
    # CLOSE PORT
    # ========================================================

    def close_port(self):

        try:

            self.running = False

            time.sleep(0.2)

            if self.ser and self.ser.is_open:
                self.ser.close()

            self.ser = None

            self.log("Serial Port Closed")

            self.port_btn.config(
                text="OPEN PORT",
                bg=ACC2,
                fg="#001a10",
                state="normal"
            )

            self.gnss_btn.config(state="disabled")
            self.map_btn.config(state="disabled")

            self.port_combo.config(state="readonly")
            self.baud_combo.config(state="readonly")

            self.labels["Fix"].config(text="---")
            self.labels["Latitude"].config(text="---")
            self.labels["Longitude"].config(text="---")
            self.labels["Altitude"].config(text="---")
            self.labels["Satellites"].config(text="---")
            self.labels["UTC Time"].config(text="---")

            self.latitude = None
            self.longitude = None

        except Exception as e:

            self.log(f"ERROR: {e}")

    # ========================================================
    # SEND AT
    # ========================================================

    def send_at(self, cmd, delay=1):

        if not self.ser or not self.ser.is_open:
            self.log("ERROR: Serial port not open")
            return

        self.log(f">> {cmd}")

        self.ser.write((cmd + "\r\n").encode())

        time.sleep(delay)

        response = self.ser.read_all().decode(
            errors="ignore"
        )

        if response:
            self.log(response)

    # ========================================================
    # START GNSS
    # ========================================================

    def start_gnss(self):

        try:

            if not self.ser or not self.ser.is_open:
                messagebox.showerror(
                    "Error",
                    "Please open serial port first"
                )
                return

            self.send_at("AT")
            self.send_at("AT+CGPS=1")
            self.send_at("AT+GPSPORT=1")

            if not self.read_thread or not self.read_thread.is_alive():

                self.read_thread = threading.Thread(
                    target=self.read_loop,
                    daemon=True
                )

                self.read_thread.start()

            self.log("GNSS Started")

        except Exception as e:

            self.log(f"ERROR: {e}")

    # ========================================================
    # READ LOOP
    # ========================================================

    def read_loop(self):

        while self.running:

            try:

                if not self.ser or not self.ser.is_open:
                    break

                line = self.ser.readline().decode(
                    errors="ignore"
                ).strip()

                if not line:
                    continue

                self.after(0, lambda l=line: self.log(l))

                # ============================================
                # RMC
                # ============================================

                if line.startswith("$GNRMC"):

                    msg = pynmea2.parse(line)

                    if msg.status == "A":

                        self.update_label("Fix", "VALID FIX")
                        self.update_label("Latitude", str(msg.latitude))
                        self.update_label("Longitude", str(msg.longitude))
                        self.update_label("UTC Time", str(msg.timestamp))

                        self.latitude = msg.latitude
                        self.longitude = msg.longitude

                        self.after(
                            0,
                            lambda: self.map_btn.config(state="normal")
                        )

                    else:

                        self.update_label("Fix", "NO FIX")

                # ============================================
                # GGA
                # ============================================

                elif line.startswith("$GNGGA"):

                    msg = pynmea2.parse(line)

                    self.update_label("Satellites", str(msg.num_sats))

                    self.update_label(
                        "Altitude",
                        f"{msg.altitude} {msg.altitude_units}"
                    )

            except Exception as e:

                self.after(
                    0,
                    lambda err=e: self.log(f"ERROR: {err}")
                )

    # ========================================================
    # OPEN MAPS
    # ========================================================

    def open_maps(self):

        if self.latitude and self.longitude:

            url = (
                f"https://www.google.com/maps/"
                f"@{self.latitude},{self.longitude},20z/data=!3m1!1e3"
            )

            webbrowser.open(url)

        else:

            messagebox.showinfo(
                "Info",
                "Location not available yet"
            )

    # ========================================================
    # CLOSE WINDOW
    # ========================================================

    def on_close(self):

        self.running = False

        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except:
            pass

        self.destroy()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app = GNSSApp()

    app.protocol("WM_DELETE_WINDOW", app.on_close)

    app.mainloop()