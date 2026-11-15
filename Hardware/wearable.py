#!/usr/bin/env python3
"""
wearable.py  -  paramedic indoor-navigation wearable
Raspberry Pi 4 + Grove Base HAT version. Replaces the Arduino Mega sketch AND
the bridge script: reads the sensors, talks to the server, drives the cues.

RUN
  Test mode (no server): prints events, type commands like  CUE L  and press Enter
      python3 wearable.py
  With the server:
      SERVER_URL=https://your-server.example DEVICE_ID=wearable-1 python3 wearable.py

ONE-TIME SETUP ON THE PI
  sudo raspi-config   ->  Interface Options  ->  I2C  ->  Enable, then reboot
  pip3 install --break-system-packages smbus2 requests
  sudo apt install -y python3-opencv        (for the webcam; or: sudo apt install -y fswebcam)
  (gpiozero is already installed on Raspberry Pi OS)
  Check sensors are seen:  i2cdetect -y 1   -> expect 68 (GY-521), 76 or 77 (barometer), 04 or 08 (HAT)

WIRING  (Grove port names are printed on the HAT; header pins = physical pin numbers)
  Grove barometer (BMP280)   any I2C port, plug straight in
  GY-521                     small breadboard, pins in a1-a8 (VCC in a1); male-to-female wires:
                               e1->pin 1 (3.3V)  e2->pin 9 (GND)  e3->pin 5 (SCL)  e4->pin 3 (SDA)
  Grove air quality sensor   port A0, plug straight in
  Grove buzzer               port D22, plug straight in
  Button 1 (confirm)         small breadboard e15/e17/f15/f17: j15->pin 29, a17->pin 30 (GND)
  Button 2 (elevator out)    small breadboard e22/e24/f22/f24: j22->pin 36, a24->pin 34 (GND)
  Logitech webcam            any USB port on the Pi; clip it to the chest strap facing forward
  Grove LED socket kit       port D24, plug straight in (long LED leg in the + hole)
                             Only free while the LCD is off (the LCD uses D24's pins).
  Grove button modules       ports D5 and D16, plug straight in (set GROVE_BUTTONS = True)
  Grove vibration motor      port D18, plug straight in (no transistor needed)
  MINIMAL-WIRE BUILD: Grove cables only, plus 4 female-female jumpers for the MPU-9250/GY-521
                      (VCC->pin 1, GND->pin 9, SCL->pin 5, SDA->pin 3); set USE_LCD = False.
  Vibration motor (kit)      port D18, Grove-to-jumper: yellow->1k->PN2222 base, black->emitter
                             motor + -> header pin 2 (5V); motor - -> collector; diode across motor
  16x2 LCD (header pins)     RS->pin 18  E->pin 22  D4->pin 37  D5->pin 13  D6->pin 38  D7->pin 40
                             VDD->pin 4 (5V)   A->220 ohm->5V   VSS,RW,K->GND (pin 6/9/14...)
                             V0->1k->GND (contrast)   D0-D3 empty
  Do NOT use Grove ports D24 and D26: their pins are used by the LCD.

MESSAGES (same as the Arduino version, so the server needs no changes)
  Out: hello, step, turn, floor, btn, air, state, ack   (JSON, see WEARABLE_SOFTWARE_SPEC.md)
       fall         {"t":"fall"}          possible fall: drop, hard impact, then lying still
       fall_cancel  {"t":"fall_cancel"}   medic pressed button 1 within 15 s: "I'm OK"
       photo        {"t":"photo","n":3,"reason":"scan","bytes":41230}   a webcam picture was sent
  Status LED: solid = running and online | slow blink = turn cue | fast blink = wrong way or fall
              short flash every 2 s = no connection to the server
  In:  CUE L|R|S|U, ARRIVED, WRONG, CLEAR, RESET, CAL, TXT <text>, PING,
       SNAP (take one picture), SCAN ON / SCAN OFF (a picture every 2 s, e.g. near the patient's door)
  Server link: POST {SERVER_URL}/api/device/{DEVICE_ID}/events  {"events":[...]}
               reply {"commands":["CUE L", ...]}
               POST {SERVER_URL}/api/device/{DEVICE_ID}/photo   multipart: image (JPEG), ts, n, reason
               reply {"commands":[...]} (optional)
  Without SERVER_URL, pictures are saved in ./snaps/ instead.
"""

import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

try:
    from smbus2 import SMBus
except ImportError:
    sys.exit("Missing library: run  pip3 install --break-system-packages smbus2")
from gpiozero import LED, Button, DigitalOutputDevice

# ---------------- Settings ----------------
SERVER_URL = os.environ.get("SERVER_URL", "").rstrip("/")
DEVICE_ID = os.environ.get("DEVICE_ID", "wearable-1")

# GPIO numbers (BCM). Grove port Dn uses GPIO n (yellow wire).
PIN_BTN_CONFIRM = 5     # Grove D5
PIN_BTN_ELEVATOR = 16   # Grove D16
PIN_MOTOR = 18          # Grove D18
PIN_BUZZER = 22         # Grove D22
LCD_PINS = dict(rs=24, e=25, d4=26, d5=27, d6=20, d7=21)  # header pins 18, 22, 37, 13, 38, 40
AIR_CHANNEL = 0         # Grove A0
PIN_LED = 24            # Grove D24 (LED socket kit)

# ---- Which parts are connected? (minimal-wire build: USE_LCD False, GROVE_BUTTONS True) ----
USE_LCD = False         # False = no 16x2 LCD; the medic's phone shows the cues instead
GROVE_BUTTONS = False   # True = Grove button modules (plug in); False = plain kit buttons to GND
USE_AIR_SENSOR = True
USE_MOTOR = False       # no vibration motor fitted
BUZZ_TURNS = True       # without a motor, the buzzer plays turn cues: 1 beep left, 2 right, 3 turn around
USE_CAMERA = True       # Logitech webcam on USB: reads door / suite signs (via the server)
CAM_INDEX = 0           # first USB camera
SCAN_INTERVAL_S = 2.0   # seconds between pictures while SCAN ON
USE_LED = True          # Grove LED socket kit on D24 (only while USE_LCD is False)
FALL_FREEFALL_G = 0.5   # fall = a moment below this...
FALL_IMPACT_G = 2.2     # ...then an impact above this within 1 s...
FALL_STILL_S = 2.0      # ...then lying still this long
FALL_CANCEL_S = 15      # button 1 within this many seconds cancels the alert
AIR_WARN_LEVEL = 2800   # raw 0-4095; tune by watching "air" in the state messages
STRIDE_M = 0.70         # metres per step; measure your wearer
STEP_HIGH_G = 1.12      # step when accel rises above this...
STEP_LOW_G = 1.02       # ...after first dropping below this
STEP_MIN_S = 0.28       # fastest allowed step rate
TURN_MIN_DEG = 60.0     # smallest rotation reported as a turn
TURN_SIGN = 1.0         # set to -1.0 if left/right come out swapped
FLOOR_HEIGHT_M = 3.5    # typical office floor-to-floor height
FLOOR_CHANGE_FRAC = 0.7 # altitude must move this fraction of a floor (held 3 s) to count as a new floor

# Patterns in ms: on, off, on, off, ...
VIB_LEFT, VIB_RIGHT, VIB_UTURN, VIB_STRAIGHT = [350], [150, 150, 150], [120, 120, 120, 120, 120], [60]
BEEP_CLICK, BEEP_ARRIVED, BEEP_FLOOR = [40], [600, 200, 600], [80, 80, 80]
BEEP_WRONG = [80, 60] * 4 + [80]
BEEP_AIR = [300, 100, 300, 100, 300]
BEEP_FALL = [1000, 200, 1000, 200, 1000]
BEEP_LEFT, BEEP_RIGHT, BEEP_UTURN = [150], [150, 150, 150], [120, 120, 120, 120, 120]

# ---------------- Output: server or console ----------------
outbox = queue.Queue()      # events waiting to go to the server
commands = queue.Queue()    # commands waiting to be executed
urgent = threading.Event()  # send now instead of waiting for the next 0.5 s tick
net_ok = [time.monotonic()] # last time the server answered


def emit(ev, now_send=True):
    ev["ts"] = int(time.time() * 1000)
    if SERVER_URL:
        outbox.put(ev)
        if now_send:
            urgent.set()
    else:
        print(json.dumps(ev, separators=(",", ":")), flush=True)


def net_worker():
    import requests
    session = requests.Session()
    url = f"{SERVER_URL}/api/device/{DEVICE_ID}/events"
    pending = []
    while True:
        urgent.wait(timeout=0.5)
        urgent.clear()
        while True:
            try:
                pending.append(outbox.get_nowait())
            except queue.Empty:
                break
        if not pending:
            continue
        try:
            r = session.post(url, json={"events": pending}, timeout=3)
            r.raise_for_status()
            pending = []
            net_ok[0] = time.monotonic()
            for c in (r.json() or {}).get("commands", []):
                commands.put(str(c))
        except Exception as e:  # keep events and retry; never crash the wearable
            print(f"[net] {e}", file=sys.stderr, flush=True)
            pending = pending[-300:]
            time.sleep(1)


def stdin_worker():
    for line in sys.stdin:
        if line.strip():
            commands.put(line.strip())


# ---------------- Sensors ----------------
class MPU6050:
    ADDR = 0x68

    def __init__(self, bus):
        self.bus = bus
        bus.write_byte_data(self.ADDR, 0x6B, 0x00)  # wake
        bus.write_byte_data(self.ADDR, 0x1A, 0x03)  # low-pass ~44 Hz
        bus.write_byte_data(self.ADDR, 0x1B, 0x00)  # gyro +-250 deg/s
        bus.write_byte_data(self.ADDR, 0x1C, 0x08)  # accel +-4 g

    def read(self):
        d = self.bus.read_i2c_block_data(self.ADDR, 0x3B, 14)

        def s16(i):
            v = (d[i] << 8) | d[i + 1]
            return v - 65536 if v > 32767 else v
        return (s16(0) / 8192.0, s16(2) / 8192.0, s16(4) / 8192.0,
                s16(8) / 131.0, s16(10) / 131.0, s16(12) / 131.0)


class BMP280:
    def __init__(self, bus):
        self.bus = bus
        self.addr = None
        for a in (0x77, 0x76):
            try:
                if bus.read_byte_data(a, 0xD0) == 0x58:
                    self.addr = a
                    break
            except OSError:
                pass
        if self.addr is None:
            raise OSError("no BMP280 at 0x76/0x77")
        c = bus.read_i2c_block_data(self.addr, 0x88, 24)

        def u16(i): return c[i] | (c[i + 1] << 8)
        def s16(i):
            v = u16(i)
            return v - 65536 if v > 32767 else v
        self.T = [u16(0), s16(2), s16(4)]
        self.P = [u16(6)] + [s16(8 + 2 * k) for k in range(8)]
        bus.write_byte_data(self.addr, 0xF5, 0x30)  # standby 62.5 ms, filter x16
        bus.write_byte_data(self.addr, 0xF4, 0x57)  # temp x2, pressure x16, normal mode

    def pressure(self):
        d = self.bus.read_i2c_block_data(self.addr, 0xF7, 6)
        adc_p = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4)
        adc_t = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4)
        T1, T2, T3 = self.T
        P1, P2, P3, P4, P5, P6, P7, P8, P9 = self.P
        v1 = (adc_t / 16384.0 - T1 / 1024.0) * T2
        v2 = ((adc_t / 131072.0 - T1 / 8192.0) ** 2) * T3
        t_fine = v1 + v2
        v1 = t_fine / 2.0 - 64000.0
        v2 = v1 * v1 * P6 / 32768.0 + v1 * P5 * 2.0
        v2 = v2 / 4.0 + P4 * 65536.0
        v1 = (P3 * v1 * v1 / 524288.0 + P2 * v1) / 524288.0
        v1 = (1.0 + v1 / 32768.0) * P1
        if v1 == 0:
            return None
        p = 1048576.0 - adc_p
        p = (p - v2 / 4096.0) * 6250.0 / v1
        v1 = P9 * p * p / 2147483648.0
        v2 = p * P8 / 32768.0
        return p + (v1 + v2 + P7) / 16.0  # Pa


class DPS310:
    """Grove High Accuracy Barometer (Infineon DPS310), I2C 0x77 or 0x76."""
    KP, KT = 253952.0, 524288.0  # scale factors for 16x pressure / 1x temperature oversampling

    def __init__(self, bus):
        self.bus = bus
        self.addr = None
        for a in (0x77, 0x76):
            try:
                if (bus.read_byte_data(a, 0x0D) & 0x0F) in (0x00, 0x01) and bus.read_byte_data(a, 0x0D) >> 4 == 1:
                    self.addr = a
                    break
            except OSError:
                pass
        if self.addr is None:
            raise OSError("no DPS310 at 0x76/0x77")
        w = lambda r, v: bus.write_byte_data(self.addr, r, v)
        r = lambda reg: bus.read_byte_data(self.addr, reg)
        w(0x0C, 0x09)  # soft reset
        time.sleep(0.05)
        for _ in range(50):  # wait for coefficients + sensor ready
            if r(0x08) & 0xC0 == 0xC0:
                break
            time.sleep(0.01)
        # known DPS310 fix: otherwise temperature (and so pressure) can read wrong after power-up
        for reg, val in ((0x0E, 0xA5), (0x0F, 0x96), (0x62, 0x02), (0x0E, 0x00), (0x0F, 0x00)):
            w(reg, val)
        c = bus.read_i2c_block_data(self.addr, 0x10, 18)

        def sx(v, bits):
            return v - (1 << bits) if v & (1 << (bits - 1)) else v
        self.c0 = sx((c[0] << 4) | (c[1] >> 4), 12)
        self.c1 = sx(((c[1] & 0x0F) << 8) | c[2], 12)
        self.c00 = sx((c[3] << 12) | (c[4] << 4) | (c[5] >> 4), 20)
        self.c10 = sx(((c[5] & 0x0F) << 16) | (c[6] << 8) | c[7], 20)
        self.c01, self.c11, self.c20, self.c21, self.c30 = (
            sx((c[i] << 8) | c[i + 1], 16) for i in (8, 10, 12, 14, 16))
        ext = r(0x28) & 0x80  # which temperature sensor the coefficients belong to
        w(0x06, 0x34)         # pressure: 8 readings/s, 16x oversampling
        w(0x07, ext | 0x30)   # temperature: 8 readings/s, 1x
        w(0x09, 0x04)         # pressure result shift (needed above 8x oversampling)
        w(0x08, 0x07)         # continuous pressure + temperature
        time.sleep(0.3)

    def pressure(self):
        d = self.bus.read_i2c_block_data(self.addr, 0x00, 6)

        def s24(a, b, c):
            v = (a << 16) | (b << 8) | c
            return v - (1 << 24) if v & 0x800000 else v
        p = s24(d[0], d[1], d[2]) / self.KP
        t = s24(d[3], d[4], d[5]) / self.KT
        return (self.c00 + p * (self.c10 + p * (self.c20 + p * self.c30))
                + t * self.c01 + t * p * (self.c11 + p * self.c21))  # Pa


class GroveADC:
    """The Grove Base HAT's analog ports, read over I2C."""

    def __init__(self, bus):
        self.bus = bus
        self.addr = None
        for a in (0x04, 0x08):
            try:
                bus.read_i2c_block_data(a, 0x10, 2)
                self.addr = a
                break
            except OSError:
                pass
        if self.addr is None:
            raise OSError("Grove Base HAT ADC not found")

    def raw(self, channel):
        d = self.bus.read_i2c_block_data(self.addr, 0x10 + channel, 2)
        return d[0] | (d[1] << 8)


# ---------------- Outputs ----------------
class Pulser:
    """Plays an on/off pattern without blocking the loop."""

    def __init__(self, dev):
        self.dev, self.seq = dev, None

    def play(self, seq):
        self.seq, self.i = seq, 0
        self.dev.on()
        self.next = time.monotonic() + seq[0] / 1000

    def update(self, now):
        if self.seq and now >= self.next:
            self.i += 1
            if self.i >= len(self.seq):
                self.dev.off()
                self.seq = None
                return
            self.dev.on() if self.i % 2 == 0 else self.dev.off()
            self.next = now + self.seq[self.i] / 1000


CUSTOM_CHARS = [  # \x01 left, \x02 right, \x03 up, \x04 check
    [0b00010, 0b00110, 0b01111, 0b11111, 0b01111, 0b00110, 0b00010, 0],
    [0b01000, 0b01100, 0b11110, 0b11111, 0b11110, 0b01100, 0b01000, 0],
    [0b00100, 0b01110, 0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0],
    [0b00000, 0b00001, 0b00011, 0b10110, 0b11100, 0b01000, 0b00000, 0],
]


class LCD:
    """16x2 HD44780 LCD in 4-bit mode, write-only (RW tied to GND)."""

    def __init__(self, rs, e, d4, d5, d6, d7):
        self.rs, self.e = DigitalOutputDevice(rs), DigitalOutputDevice(e)
        self.d = [DigitalOutputDevice(p) for p in (d4, d5, d6, d7)]
        self.lines = ["", ""]
        time.sleep(0.05)
        for _ in range(3):
            self._nibble(0x03)
            time.sleep(0.005)
        self._nibble(0x02)
        time.sleep(0.001)
        for c in (0x28, 0x0C, 0x06):  # 4-bit 2-line, display on, left-to-right
            self.cmd(c)
        for i, rows in enumerate(CUSTOM_CHARS):
            self.cmd(0x40 | (i << 3))
            for r in rows:
                self.data(r)
        self.clear()

    def _nibble(self, n):
        for i, pin in enumerate(self.d):
            pin.value = (n >> i) & 1
        self.e.on()
        self.e.off()
        time.sleep(0.00005)

    def _send(self, v, is_data):
        self.rs.value = 1 if is_data else 0
        self._nibble(v >> 4)
        self._nibble(v & 0x0F)

    def cmd(self, c):
        self._send(c, False)

    def data(self, d):
        self._send(d, True)

    def clear(self):
        self.cmd(0x01)
        time.sleep(0.002)
        self.lines = ["", ""]

    def line(self, row, text):
        text = text[:16].ljust(16)
        if self.lines[row] == text:
            return
        self.lines[row] = text
        self.cmd(0x80 | (0x40 if row else 0x00))
        for ch in text:
            o = ord(ch)
            self.data(o - 1 if 1 <= o <= 4 else (o if 32 <= o < 127 else 32))


class Display:
    CUES = {
        "L": "\x01\x01\x01 TURN LEFT",
        "R": "TURN RIGHT \x02\x02\x02",
        "S": "\x03 GO STRAIGHT \x03",
        "U": "TURN AROUND",
        "A": "\x04 ARRIVED \x04",
        "X": "!! WRONG WAY !!",
    }

    def __init__(self, lcd):
        self.lcd = lcd
        self.override = False

    def cue(self, kind):
        self.override = False
        if self.lcd:
            self.lcd.line(0, self.CUES[kind])

    def message(self, top, bottom=None):
        if self.lcd:
            self.lcd.line(0, top)
            if bottom is not None:
                self.lcd.line(1, bottom)

    def text(self, t):
        self.override = True
        if self.lcd:
            self.lcd.line(1, t)

    def status(self, floor, dist):
        if self.lcd and not self.override:
            self.lcd.line(1, f"FL {floor}  {dist:.1f}m")

    def clear(self):
        self.override = False
        if self.lcd:
            self.lcd.clear()


# ---------------- Webcam ----------------
class Camera:
    """USB webcam. Uses OpenCV if installed, otherwise the fswebcam command."""

    def __init__(self, index):
        self.cap = None
        self.cv2 = None
        try:
            import cv2
            cap = cv2.VideoCapture(index)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.cv2, self.cap = cv2, cap
        except ImportError:
            pass
        if not self.cap and not shutil.which("fswebcam"):
            raise OSError("no webcam found (plug it in; install python3-opencv or fswebcam)")

    def jpeg(self):
        if self.cap:
            for _ in range(2):  # drop stale buffered frames
                self.cap.grab()
            ok, frame = self.cap.read()
            if not ok:
                return None
            ok, buf = self.cv2.imencode(".jpg", frame, [self.cv2.IMWRITE_JPEG_QUALITY, 80])
            return buf.tobytes() if ok else None
        out = subprocess.run(["fswebcam", "-q", "--no-banner", "-r", "640x480", "--jpeg", "80", "-"],
                             capture_output=True, timeout=8)
        return out.stdout or None


snap_requests = queue.Queue()
scan_on = threading.Event()


def camera_worker(cam):
    session = None
    if SERVER_URL:
        import requests
        session = requests.Session()
    else:
        os.makedirs("snaps", exist_ok=True)
    n, last = 0, 0.0
    while True:
        try:
            reason = snap_requests.get(timeout=0.2)
        except queue.Empty:
            if scan_on.is_set() and time.monotonic() - last >= SCAN_INTERVAL_S:
                reason = "scan"
            else:
                continue
        last = time.monotonic()
        try:
            jpg = cam.jpeg()
        except Exception as e:
            print(f"[camera] {e}", file=sys.stderr, flush=True)
            continue
        if not jpg:
            continue
        n += 1
        ev = {"t": "photo", "n": n, "reason": reason, "bytes": len(jpg)}
        if session:
            try:
                r = session.post(f"{SERVER_URL}/api/device/{DEVICE_ID}/photo",
                                 files={"image": ("snap.jpg", jpg, "image/jpeg")},
                                 data={"ts": str(int(time.time() * 1000)), "n": str(n), "reason": reason},
                                 timeout=8)
                r.raise_for_status()
                for c in (r.json() or {}).get("commands", []):
                    commands.put(str(c))
            except Exception as e:
                print(f"[camera upload] {e}", file=sys.stderr, flush=True)
                ev["sent"] = 0
        else:
            path = os.path.join("snaps", f"snap_{n:03d}.jpg")
            with open(path, "wb") as f:
                f.write(jpg)
            ev["file"] = path
        emit(ev, now_send=False)


# ---------------- Main ----------------
def try_make(name, fn):
    try:
        return fn()
    except Exception as e:
        print(f"[{name}] not available: {e}", file=sys.stderr, flush=True)
        return None


def main():
    bus = SMBus(1)
    imu = try_make("GY-521", lambda: MPU6050(bus))
    def make_baro():
        try:
            return BMP280(bus)
        except OSError:
            return DPS310(bus)  # Grove High Accuracy Barometer
    baro = try_make("barometer", make_baro)
    adc = try_make("air sensor", lambda: GroveADC(bus)) if USE_AIR_SENSOR else None
    lcd = try_make("LCD", lambda: LCD(**LCD_PINS)) if USE_LCD else None
    display = Display(lcd)
    led = try_make("LED", lambda: LED(PIN_LED)) if (USE_LED and not USE_LCD) else None
    cam = try_make("webcam", lambda: Camera(CAM_INDEX)) if USE_CAMERA else None
    if cam:
        threading.Thread(target=camera_worker, args=(cam,), daemon=True).start()
    motor = Pulser(DigitalOutputDevice(PIN_MOTOR)) if USE_MOTOR else None
    buzzer = Pulser(DigitalOutputDevice(PIN_BUZZER))

    presses = queue.Queue()
    btn1 = Button(PIN_BTN_CONFIRM, pull_up=not GROVE_BUTTONS, bounce_time=0.03)
    btn2 = Button(PIN_BTN_ELEVATOR, pull_up=not GROVE_BUTTONS, bounce_time=0.03)
    btn1.when_pressed = lambda: presses.put((1, "confirm"))
    btn2.when_pressed = lambda: presses.put((2, "elevator_out"))

    threading.Thread(target=net_worker if SERVER_URL else stdin_worker, daemon=True).start()

    # ---- tracking state ----
    s = dict(steps=0, heading=0.0, turn_ref=0.0, still_since=0.0, armed=False, last_step=0.0,
             mag=1.0, grav=[0.0, 0.0, 1.0], bias=[0.0, 0.0, 0.0],
             p=0.0, p0=0.0, alt=0.0, floor=0, cand=0, cand_since=0.0,
             air=0, air_warn=False, calibrated=False, still_n=0, yaw_f=0.0, alt_off=0.0,
             ff_time=-99.0, impact_time=None, still_bad=0, fall_until=0.0,
             led_event_mode="on", led_event_until=0.0, led_mode=None)

    def calibrate():
        if not imu:
            return
        display.message("CALIBRATING...", "HOLD STILL")
        g = [0.0] * 3
        a = [0.0] * 3
        n = 0
        for _ in range(300):  # aim for 200 good samples; a flaky wire just skips some
            try:
                ax, ay, az, gx, gy, gz = imu.read()
            except OSError:
                time.sleep(0.01)
                continue
            for i, v in enumerate((gx, gy, gz)):
                g[i] += v
            for i, v in enumerate((ax, ay, az)):
                a[i] += v
            n += 1
            if n >= 200:
                break
            time.sleep(0.01)
        if n < 100:
            raise OSError(f"only {n} good readings")
        s["bias"] = [v / n for v in g]
        s["grav"] = [v / n for v in a]
        s["calibrated"] = True
        display.clear()

    def try_calibrate():
        try:
            calibrate()
        except OSError as e:
            print(f"[GY-521] calibration failed: {e}", file=sys.stderr, flush=True)
            display.clear()

    def reset_position():
        s.update(steps=0, heading=0.0, turn_ref=0.0, p0=s["p"], alt=0.0, alt_off=0.0, floor=0, cand=0)

    def wrap(h):
        return h % 360.0

    def update_imu(now, dt):
        ax, ay, az, gx, gy, gz = imu.read()
        # steps: each footstep is a bump in total acceleration
        mag_raw = math.sqrt(ax * ax + ay * ay + az * az)
        s["mag"] = s["mag"] * 0.8 + mag_raw * 0.2
        if not s["armed"] and s["mag"] < STEP_LOW_G:
            s["armed"] = True
        if s["armed"] and s["mag"] > STEP_HIGH_G and now - s["last_step"] > STEP_MIN_S:
            s["steps"] += 1
            s["armed"] = False
            s["last_step"] = now
            emit({"t": "step", "n": s["steps"], "d": round(s["steps"] * STRIDE_M, 1),
                  "hd": round(wrap(s["heading"]), 1)})
        # heading: rotation around "up", however the unit is mounted
        g = s["grav"]
        for i, v in enumerate((ax, ay, az)):
            g[i] = g[i] * 0.98 + v * 0.02
        gn = math.sqrt(sum(v * v for v in g)) or 1.0
        b = s["bias"]
        # drift fix: after ~1 s of stillness (no stepping, no fast rotation), re-learn the gyro's
        # zero point. Fixes a bad calibration too; real turns (30+ deg/s) are never learned as drift.
        if abs(mag_raw - 1.0) < 0.05 and max(abs(gx - b[0]), abs(gy - b[1]), abs(gz - b[2])) < 15.0:
            s["still_n"] += 1
        else:
            s["still_n"] = 0
        if s["still_n"] > 100:
            for i, v in enumerate((gx, gy, gz)):
                b[i] = b[i] * 0.98 + v * 0.02
        yaw_rate = ((gx - b[0]) * g[0] + (gy - b[1]) * g[1] + (gz - b[2]) * g[2]) / gn
        s["heading"] += -yaw_rate * dt * TURN_SIGN
        # turns: report once rotation has stopped. Smooth the rotation rate first (~0.5 s),
        # otherwise the wobble of each footstep keeps it "rotating" and turns are never reported
        # while walking.
        s["yaw_f"] = s["yaw_f"] * 0.98 + yaw_rate * 0.02
        if abs(s["yaw_f"]) > 12:
            s["still_since"] = now
        elif now - s["still_since"] > 0.4:
            delta = s["heading"] - s["turn_ref"]
            if abs(delta) >= TURN_MIN_DEG:
                emit({"t": "turn", "dir": "R" if delta > 0 else "L", "deg": int(delta)})
                s["turn_ref"] = s["heading"]
            elif abs(delta) < 25:
                s["turn_ref"] = s["heading"]
        # fall: free fall, hard impact, then lying still
        gmag = math.sqrt((gx - b[0]) ** 2 + (gy - b[1]) ** 2 + (gz - b[2]) ** 2)
        if mag_raw < FALL_FREEFALL_G:
            s["ff_time"] = now
        if s["impact_time"] is None:
            if mag_raw > FALL_IMPACT_G and now - s["ff_time"] < 1.0:
                s["impact_time"], s["still_bad"] = now, 0
        else:
            t = now - s["impact_time"]
            if t > 0.5 and (abs(mag_raw - 1.0) > 0.3 or gmag > 30):
                s["still_bad"] += 1
            if t > 0.5 + FALL_STILL_S:
                if s["still_bad"] < 10:
                    emit({"t": "fall"})
                    buzzer.play(BEEP_FALL)
                    s["fall_until"] = now + FALL_CANCEL_S
                s["impact_time"] = None

    def update_baro(now):
        p = baro.pressure()
        if not p or p < 30000:
            return
        s["p"] = p if s["p"] == 0 else s["p"] * 0.9 + p * 0.1
        if s["p0"] == 0:
            s["p0"] = s["p"]
        raw_alt = 44330.0 * (1.0 - (s["p"] / s["p0"]) ** 0.1903)
        # drift fix: on a floor, slowly pull the altitude back to that floor's level (~2 min),
        # so weather / ventilation pressure changes fade out; real floor changes take seconds
        s["alt_off"] += (raw_alt - s["alt_off"] - s["floor"] * FLOOR_HEIGHT_M) * 0.0008
        s["alt"] = raw_alt - s["alt_off"]
        # only a clear change (70% of a floor, held 3 s) counts as a new floor
        if abs(s["alt"] - s["floor"] * FLOOR_HEIGHT_M) > FLOOR_CHANGE_FRAC * FLOOR_HEIGHT_M:
            cand = round(s["alt"] / FLOOR_HEIGHT_M)
        else:
            cand = s["floor"]
        if cand == s["floor"]:
            s["cand"] = s["floor"]
        elif cand != s["cand"]:
            s["cand"], s["cand_since"] = cand, now
        elif now - s["cand_since"] > 3.0:
            s["floor"] = cand
            emit({"t": "floor", "fl": cand, "alt": round(s["alt"], 1)})
            buzzer.play(BEEP_FLOOR)

    def update_air(now, start):
        s["air"] = adc.raw(AIR_CHANNEL)
        if now - start < 20:  # sensor warm-up
            return
        warn = s["air"] > AIR_WARN_LEVEL
        if warn != s["air_warn"]:
            s["air_warn"] = warn
            emit({"t": "air", "v": s["air"], "warn": int(warn)})
            if warn:
                buzzer.play(BEEP_AIR)

    def handle(raw):
        up = raw.strip().upper()
        if up.startswith("CUE ") and up[4:5] in "LRSU" and len(up) >= 5:
            k = up[4]
            display.cue(k)
            if k != "S":
                s["led_event_mode"], s["led_event_until"] = "slow", time.monotonic() + 4
            if motor:
                motor.play({"L": VIB_LEFT, "R": VIB_RIGHT, "S": VIB_STRAIGHT, "U": VIB_UTURN}[k])
            elif BUZZ_TURNS and k != "S":
                buzzer.play({"L": BEEP_LEFT, "R": BEEP_RIGHT, "U": BEEP_UTURN}[k])
        elif up == "ARRIVED":
            display.cue("A")
            buzzer.play(BEEP_ARRIVED)
            s["led_event_mode"], s["led_event_until"] = "arrived", time.monotonic() + 4
        elif up == "WRONG":
            display.cue("X")
            buzzer.play(BEEP_WRONG)
            s["led_event_mode"], s["led_event_until"] = "fast", time.monotonic() + 4
            if motor:
                motor.play(VIB_UTURN)
        elif up == "CLEAR":
            display.clear()
        elif up == "RESET":
            reset_position()
        elif up == "CAL":
            calibrate()
        elif up.startswith("TXT "):
            display.text(up[4:])
        elif up == "SNAP":
            snap_requests.put("snap")
        elif up == "SCAN ON":
            scan_on.set()
        elif up == "SCAN OFF":
            scan_on.clear()
        elif up.startswith("BRIGHT"):
            pass  # LCD backlight is fixed; accepted for compatibility
        elif up == "PING":
            emit({"t": "pong"})
            return
        else:
            emit({"t": "error", "msg": "unknown command", "cmd": raw.strip()})
            return
        emit({"t": "ack", "cmd": raw.strip()})

    def update_led(now):
        if not led:
            return
        if now < s["fall_until"]:
            mode = "fast"
        elif now < s["led_event_until"]:
            mode = s["led_event_mode"]
        elif SERVER_URL and now - net_ok[0] > 5:
            mode = "offline"
        else:
            mode = "on"
        if mode == s["led_mode"]:
            return
        s["led_mode"] = mode
        if mode == "on":
            led.on()
        elif mode == "slow":
            led.blink(on_time=0.5, off_time=0.5)
        elif mode == "fast":
            led.blink(on_time=0.1, off_time=0.1)
        elif mode == "arrived":
            led.blink(on_time=0.3, off_time=0.3)
        else:  # offline
            led.blink(on_time=0.1, off_time=1.9)

    # ---- start ----
    try_calibrate()
    net_ok[0] = time.monotonic()
    emit({"t": "hello", "fw": "medic-wearable-pi-3", "imu": int(bool(imu)), "baro": int(bool(baro)),
          "air": int(bool(adc)), "lcd": int(bool(lcd)), "led": int(bool(led)), "cam": int(bool(cam))})
    buzzer.play(BEEP_CLICK)

    start = last_imu = last_baro = last_air = last_state = time.monotonic()
    last_imu_try, imu_errs, last_cal_try = 0.0, 0, time.monotonic()
    try:
        while True:
            now = time.monotonic()
            while not commands.empty():
                handle(commands.get_nowait())
            while not presses.empty():
                bid, ev = presses.get_nowait()
                if bid == 1 and now < s["fall_until"]:
                    emit({"t": "fall_cancel"})
                    s["fall_until"] = 0.0
                else:
                    emit({"t": "btn", "id": bid, "ev": ev})
                    if bid == 1:
                        snap_requests.put("button")
                buzzer.play(BEEP_CLICK)
            if motor:
                motor.update(now)
            buzzer.update(now)
            update_led(now)

            # sensor reads never crash the loop: a loose wire just skips readings
            if imu and not s["calibrated"] and now - last_cal_try >= 10.0:
                last_cal_try = now
                try_calibrate()
                last_imu = now = time.monotonic()
            if imu and now - last_imu >= 0.01:
                try:
                    update_imu(now, min(now - last_imu, 0.1))
                    imu_errs = 0
                except OSError:
                    imu_errs += 1
                    if imu_errs >= 50:  # ~0.5 s of failed reads: drop it and keep trying to reconnect
                        print("[GY-521] lost connection, retrying", file=sys.stderr, flush=True)
                        emit({"t": "sensor", "imu": 0})
                        imu, imu_errs = None, 0
                last_imu = now
            elif not imu and now - last_imu_try >= 3.0:
                last_imu_try = now
                try:
                    imu = MPU6050(bus)
                    print("[GY-521] connected", file=sys.stderr, flush=True)
                    if not s["calibrated"]:
                        try_calibrate()
                    emit({"t": "sensor", "imu": 1})
                except OSError:
                    imu = None
                last_imu = time.monotonic()
            if baro and now - last_baro >= 0.1:
                last_baro = now
                try:
                    update_baro(now)
                except OSError:
                    pass
            if adc and now - last_air >= 1.0:
                last_air = now
                try:
                    update_air(now, start)
                except OSError:
                    pass
            if now - last_state >= 0.5:
                last_state = now
                st = {"t": "state", "steps": s["steps"], "d": round(s["steps"] * STRIDE_M, 1),
                      "hd": round(wrap(s["heading"]), 1), "fl": s["floor"], "alt": round(s["alt"], 2),
                      "p": round(s["p"], 1)}
                if adc:
                    st["air"] = s["air"]
                emit(st, now_send=False)
                display.status(s["floor"], s["steps"] * STRIDE_M)
            time.sleep(0.002)
    except KeyboardInterrupt:
        pass
    finally:
        if motor:
            motor.dev.off()
        buzzer.dev.off()
        if led:
            led.off()
        display.clear()


if __name__ == "__main__":
    main()
