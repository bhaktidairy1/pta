import os
import socket
import threading
import time
import binascii
import requests
from urllib.parse import urlparse
from flask import Flask, jsonify

HOST = "202.239.51.41"
PORT = 30001

# — Hard‑coded list of three dummy Mage URLs —
MAGE_URLS = [#iruna15
"https://gae4php82-real.an.r.appspot.com/_ah/login?continue=https://gae4php82-real.an.r.appspot.com/authcreate&auth=g.a000ywigSRDmMyF3ttFIHK5N6MIKtzBJ-LGyQ1CtSoli6OpmucenowwWY45GfwMCnfMLB1VtFAACgYKAVsSARUSFQHGX2Miq2D2ZhC3VbJ_K9kyqHctBxoVAUF8yKp8-9rmA1GqRchawk9lmbLh0076",
        #14
    "https://gae4php82-real.an.r.appspot.com/_ah/login?continue=https://gae4php82-real.an.r.appspot.com/authcreate&auth=g.a000ywitBIOzJ9x5UpMzqadLmT_bRqbWUocG-8WbtpqkC9gwHbJxbvDaE9pvH1pvCnwdG1zHFQACgYKAe0SARISFQHGX2Miqq6GlB1F9OtvMwDzZbCg4xoVAUF8yKoCGgAU8I4kxj7Wu24b3p7A0076",
                #MINS
"https://gae4php82-real.an.r.appspot.com/_ah/login?continue=https://gae4php82-real.an.r.appspot.com/authcreate&auth=g.a000ywjqyOTVEvNd-vMfhKJhVBbVCadfYW1aJvFji_zskW4-JQkwkI0P3kUDa1N3r2G6p73gRAACgYKAe4SARQSFQHGX2MiuurB6fQTsINZpcs2JBKldhoVAUF8yKpj77J0GuTe9mEFxLWlx6Zd0076",
]

app = Flask(__name__)

def hex_recv(sock, expect_len=4096, label=None) -> bytes:
    data = sock.recv(expect_len)
    if not data:
        raise ConnectionError("Server closed connection")
    h = binascii.hexlify(data).decode()
    print(f"[{label or 'RECV'}] ({len(data)} bytes): {h}")
    return data

def hex_send(sock, hexstr: str, label=None):
    raw = binascii.unhexlify(hexstr)
    sock.sendall(raw)
    print(f"[{label or 'SEND'}]: {hexstr}")

def coordinate_sender(sock, stop_event):
    while not stop_event.is_set():
        try:
            hex_send(sock, "0006010133b65786", "Auto Coords")
        except Exception as e:
            print(f"[!] Error sending coords: {e}")
            break
        time.sleep(1)

def run_bot(mageurl: str):
    """Run one independent bot instance against a single mageurl."""
    # — LOGIN TOKEN HANDLING —
    session = requests.Session()
    session.get(mageurl, allow_redirects=True)
    base = f"{urlparse(mageurl).scheme}://{urlparse(mageurl).netloc}"
    resp = session.get(f"{base}/authcreate")
    token = resp.text.strip().encode().hex()
    print(f"[{mageurl}] Token: {token}")

    # Prepare login packet
    token_prefixed = binascii.unhexlify("0020" + token + "0000")
    payload = b"\xFF\x02" + token_prefixed
    login_packet = len(payload).to_bytes(2, "big") + payload

    # — CONNECT & LOGIN —
    s = socket.socket()
    s.settimeout(5.0)
    print(f"[{mageurl}] Connecting…")
    s.connect((HOST, PORT))

    hex_send(s, "0002fff3", "Init")
    hex_recv(s, label="Init Header")

    s.sendall(login_packet)
    print(f"[{mageurl}] Sent Login Packet: {binascii.hexlify(login_packet).decode()}")
    data = hex_recv(s, label="Login ACK")
    if not binascii.hexlify(data).decode().startswith("00000003ff0200"):
        print(f"[{mageurl}] Login failed")
        s.close()
        return
    print(f"[{mageurl}] Login OK")

    # — Parse char_id_hex from ff03 packet —
    try:
        s.settimeout(0.3)
        extra = hex_recv(s, label="ff03+info")
        hexed = binascii.hexlify(extra).decode()
        idx = hexed.find("ff030100000001")
        char_id_hex = hexed[idx+14:idx+14+8]
        print(f"[{mageurl}] char_id_hex = {char_id_hex}")
    except Exception as e:
        print(f"[{mageurl}] Failed to parse char_id: {e}")
        s.close()
        return
    finally:
        s.settimeout(5.0)

    # ─────────── From here on: replay the “correct” Character/World sequence ───────────
    def send_and_log(pkt_hex, label=None, delay=0.1):
        hex_send(s, pkt_hex, label=label)
        time.sleep(delay)

    # 4) Character Select
    send_and_log("0002f032", "Character Select")
    #    → server: “0000009df032…” (character info)
    hex_recv(s, label="Character Info")

    # 5) Enter World #1: “00060001” + <char_id_hex>
    send_and_log("00060001", "Enter World")
    send_and_log(char_id_hex, "Character ID")

    #    → server: “00000fd7…” (big map blob)
    hex_recv(s, label="Map Data")

    # 6) Post‐Map: “000623f3” + <char_id_hex>
    send_and_log("000623f3", "Post-Map")
    send_and_log(char_id_hex, "Character ID Repeat")

    #    → server: “0000004323f300…” (world sync)
    hex_recv(s, label="World Sync")

    # 7) Four movement‐handshake packets + “00026002”
    for step in ["00023300", "00023303", "00023300", "00023303"]:
        send_and_log(step, "Movement Step")
    send_and_log("00026002", "Movement Step")

    #    → server: movement sync
    hex_recv(s, label="Movement Sync")

    # 8) Presence start: “001bb300” + 24 zeros
    send_and_log("001bb300", "Presence Start")
    send_and_log("00000000000000000000000000000000000000000000000000", "Zeroes")

    # 9) Begin Sync: “0002013a” then “000e0110000318940000320000001000”
    send_and_log("0002013a", "Begin Sync")
    send_and_log("000e0110000318940000320000001000", "Position Data")
    #    → server: ack for position
    hex_recv(s, label="Ack for Position")

    # 10) Resend Position: “0002013a”
    send_and_log("0002013a", "Resend Position")
    #    → server: extra state data
    hex_recv(s, label="Extra State Data")

    # 11) Bulk Action: “000f3002”
    send_and_log("000f3002", "Bulk Action")
    send_and_log("1100000000000000000003189400023209", "Bulk Action Contd.")

    # 12) Trigger Motion: “00020160”
    send_and_log("00020160", "Trigger Motion")
    #    → server: motion ack
    hex_recv(s, label="Motion Ack")

    # 13) Visuals Setup: “00038404”
    send_and_log("00038404", "Visuals Setup")
    send_and_log("00", "Visual Padding")

    # 14) Presence Confirm: “00060202” + <char_id_hex>
    send_and_log("00060202" + char_id_hex, "Presence Confirm")
    #    → server: presence ack
    hex_recv(s, label="Presence Ack")

    # 15) World Tick: “00033006”
    send_and_log("00033006", "World Tick")

    # 16) Trigger Something: “01000f300211000000020000000000031894”
    send_and_log("01000f300211000000020000000000031894", "Trigger Something")
    #    → server: update
    hex_recv(s, label="Server Update")

    # 17) Char “idle + coords” right away:
    #     “00067110” + <char_id_hex> + “0006010132001000”
    send_and_log("00067110" + char_id_hex + "0006010132001000", "Char Idle + Coords")

    print("\n[+] Game session established. Starting packet loop and GUI…\n")

    print("\n[+] Game session established. Running Party Map sequence…\n")

    # — Party Map → New Map sequence —
    def do_party_map():

        # Step 2: request party map
        send_and_log("0002b502", label="GUI: PartyMap-request")

        # → wait for response
        hex_recv(s, label="GUI: PartyMap Resp")

        # Step 3: ack party map
        send_and_log("0002b509", label="GUI: PartyMap-ack")

        # → wait for ack
        hex_recv(s, label="GUI: PartyMap Ack")

        # Step 5: jump to new map
        send_and_log("00120114", label="GUI: NewMap-step1")
        send_and_log("000aae60000000000000000000031894", label="GUI: NewMap-step2")

        # → wait for new-map header
        hex_recv(s, label="GUI: NewMap Resp")

        send_and_log("0003300601", label="Infinite Books")

        print("[+] Party Map sequence done. Auto-coords will now resume…")

    # run it…
    do_party_map()
    
    # — Start auto-coords thread —
    stop_event = threading.Event()
    threading.Thread(target=coordinate_sender, args=(s, stop_event), daemon=True).start()

    # KEEP ALIVE LOOP: just sleep so auto-coords continues
    while True:
        time.sleep(1)

# Start bots once Flask is ready
def start_bots():
    for url in MAGE_URLS:
        t = threading.Thread(target=run_bot, args=(url,), daemon=True)
        t.start()

@app.route('/')
def health():
    # Returns simple JSON to indicate service is up
    return jsonify({
        'status': 'ok',
        'bot_count': len(MAGE_URLS)
    })


if __name__ == '__main__':
    # Render provides PORT env var (e.g. 10000)
    start_bots()  # Eagerly start bots immediately when Flask launches
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
