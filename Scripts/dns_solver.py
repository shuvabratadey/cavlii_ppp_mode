import tkinter as tk
from tkinter import messagebox
import socket
from urllib.parse import urlparse


current_ip = ""


def extract_domain(url):
    url = url.strip()

    if not url:
        return ""

    if "://" not in url:
        url = "http://" + url

    parsed_url = urlparse(url)
    domain = parsed_url.netloc

    if domain.startswith("www."):
        domain = domain[4:]

    return domain


def resolve_dns():
    global current_ip

    website = entry_website.get()
    domain = extract_domain(website)

    if not domain:
        messagebox.showwarning("Input Error", "Please enter a website link.")
        return

    try:
        ip_address = socket.gethostbyname(domain)
        current_ip = ip_address

        result_label.config(
            text=f"Website: {domain}\nIP Address: {ip_address}",
            fg="green"
        )

        copy_button.config(state=tk.NORMAL)

    except socket.gaierror:
        current_ip = ""
        copy_button.config(state=tk.DISABLED)

        result_label.config(
            text="Could not resolve DNS.\nPlease check the website link.",
            fg="red"
        )


def copy_ip():
    if current_ip:
        window.clipboard_clear()
        window.clipboard_append(current_ip)
        window.update()
        messagebox.showinfo("Copied", f"IP copied: {current_ip}")


def clear_result():
    global current_ip

    current_ip = ""
    entry_website.delete(0, tk.END)
    result_label.config(text="")
    copy_button.config(state=tk.DISABLED)


# Create main window
window = tk.Tk()
window.title("DNS Resolver")
window.geometry("450x330")
window.resizable(False, False)

title_label = tk.Label(
    window,
    text="DNS Resolver",
    font=("Arial", 20, "bold")
)
title_label.pack(pady=15)

input_label = tk.Label(
    window,
    text="Enter Website Link:",
    font=("Arial", 12)
)
input_label.pack()

entry_website = tk.Entry(
    window,
    width=40,
    font=("Arial", 12)
)
entry_website.pack(pady=8)

resolve_button = tk.Button(
    window,
    text="Get IP Address",
    font=("Arial", 12),
    command=resolve_dns
)
resolve_button.pack(pady=8)

copy_button = tk.Button(
    window,
    text="Copy IP Address",
    font=("Arial", 12),
    command=copy_ip,
    state=tk.DISABLED
)
copy_button.pack(pady=5)

clear_button = tk.Button(
    window,
    text="Clear",
    font=("Arial", 12),
    command=clear_result
)
clear_button.pack()

result_label = tk.Label(
    window,
    text="",
    font=("Arial", 12),
    wraplength=400,
    justify="center"
)
result_label.pack(pady=20)

window.mainloop()