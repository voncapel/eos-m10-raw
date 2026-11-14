#!/usr/bin/env python3
"""Minimal CHDK PTP client for the Canon EOS M10 (pyusb + libusb).

Library:
    from m10ptp import Cam
    c = Cam(); c.version(); c.peek(0x8000); c.read(addr, n); c.call(fn, *args)
    c.lua("return 1+1"); c.upload(local, "A/X.BIN"); c.download("A/X.LOG")

CLI:
    m10ptp.py ver
    m10ptp.py peek ADDR [N]          (words, buffered read: OK for MMIO)
    m10ptp.py dump ADDR SIZE FILE
    m10ptp.py shadow REG [REG...]    (engine regs via Canon shadow read)
    m10ptp.py call FN [ARGS...]
    m10ptp.py lua 'CODE'
    m10ptp.py up LOCAL REMOTE | down REMOTE LOCAL

On macOS, ptpcamerad grabs PTP cameras; it is killed automatically.
"""
import struct, sys, subprocess, time
import usb.core, usb.util, usb.backend.libusb1

CANON_VID = 0x04A9
OC_CHDK = 0x9999
OC_OPEN, OC_CLOSE = 0x1002, 0x1003
RC_OK = 0x2001
(CMD_VERSION, CMD_GETMEM, CMD_SETMEM, CMD_CALL, CMD_TEMP, CMD_UPLOAD,
 CMD_DOWNLOAD, CMD_EXEC, CMD_STATUS, CMD_SUPPORT, CMD_READMSG) = range(11)
MSG_TYPES = {0: "none", 1: "err", 2: "ret", 3: "user"}


def _backend():
    return usb.backend.libusb1.get_backend(
        find_library=lambda x: "/opt/homebrew/lib/libusb-1.0.dylib")


class PTPError(Exception):
    pass


class Cam:
    def __init__(self, timeout=5000):
        subprocess.run(["killall", "ptpcamerad"], capture_output=True)
        self.dev = usb.core.find(idVendor=CANON_VID, backend=_backend())
        if self.dev is None:
            raise PTPError("no Canon device on USB (camera on?)")
        self.timeout = timeout
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except (usb.core.USBError, NotImplementedError):
            pass
        for attempt in range(20):
            subprocess.run(["killall", "-9", "ptpcamerad"], capture_output=True)
            try:
                usb.util.claim_interface(self.dev, 0)
                break
            except usb.core.USBError:
                time.sleep(0.05)
        else:
            raise PTPError("cannot claim interface (ptpcamerad still running?)")
        intf = self.dev.get_active_configuration()[(0, 0)]
        ep = lambda d, t: usb.util.find_descriptor(intf, custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) == d and
            usb.util.endpoint_type(e.bmAttributes) == t)
        self.ep_out = ep(usb.util.ENDPOINT_OUT, usb.util.ENDPOINT_TYPE_BULK)
        self.ep_in = ep(usb.util.ENDPOINT_IN, usb.util.ENDPOINT_TYPE_BULK)
        self.tid = 0
        self.session = False
        try:
            self._txn(OC_OPEN, [1])
        except PTPError as e:
            if "0x201e" not in str(e):  # session already open
                raise
        self.session = True

    # ---------- raw PTP ----------
    def _send(self, ctype, code, payload):
        hdr = struct.pack("<IHHI", 12 + len(payload), ctype, code, self.tid)
        self.ep_out.write(hdr + payload, self.timeout)

    def _recv(self):
        buf = bytes(self.ep_in.read(512 * 1024, self.timeout))
        length, ctype, code, tid = struct.unpack_from("<IHHI", buf)
        while len(buf) < length:
            buf += bytes(self.ep_in.read(max(512, length - len(buf)), self.timeout))
        return ctype, code, buf[12:length]

    def _txn(self, code, params, data_out=None):
        self.tid += 1
        self._send(1, code, struct.pack("<%dI" % len(params), *params))
        if data_out is not None:
            self._send(2, code, data_out)
        data_in = None
        while True:
            ctype, rcode, payload = self._recv()
            if ctype == 2:
                data_in = payload
            elif ctype == 3:
                if rcode != RC_OK:
                    raise PTPError("PTP response 0x%04x for op 0x%04x %r" % (rcode, code, params))
                n = len(payload) // 4
                return list(struct.unpack("<%dI" % n, payload[:4 * n])), data_in

    def chdk(self, cmd, params=(), data=None):
        return self._txn(OC_CHDK, [cmd] + list(params), data)

    # ---------- CHDK ops ----------
    def version(self):
        p, _ = self.chdk(CMD_VERSION)
        return p[0], p[1]

    def read(self, addr, size, buffered=True, force=False):
        # Direct reads of the 0xC0xxxxxx engine MMIO hung the camera (2026-11-07).
        # Use shadow(reg) for engine registers instead.
        if not force and (addr >> 28) in (0xC, 0xD):
            raise PTPError("refusing direct MMIO read at 0x%08x: use shadow()" % addr)
        _, d = self.chdk(CMD_GETMEM, [addr, size, 1 if buffered else 0])
        return d

    FN_SHADOW_READ = 0xfc38d2b9  # EngDrv shadow read (reg) -> value

    def shadow(self, reg):
        return self.call(self.FN_SHADOW_READ, reg)

    def peek(self, addr, n=1):
        return list(struct.unpack("<%dI" % n, self.read(addr, 4 * n)))

    def write(self, addr, data):
        self.chdk(CMD_SETMEM, [addr, len(data)], data)

    def poke(self, addr, *vals):
        self.write(addr, struct.pack("<%dI" % len(vals), *vals))

    def call(self, fn, *args):
        p, _ = self.chdk(CMD_CALL, [], struct.pack("<%dI" % (1 + len(args)),
                         fn, *[a & 0xffffffff for a in args]))
        return p[0]

    def readmsg(self):
        p, d = self.chdk(CMD_READMSG)
        mtype, sub, sid, ln = p[:4]
        return MSG_TYPES.get(mtype, mtype), sub, (d or b"")[:ln]

    def lua(self, code, wait=30.0):
        """Run Lua on camera, return list of (type, subtype, data) messages."""
        p, _ = self.chdk(CMD_EXEC, [0], code.encode() + b"\0")
        if p[1] != 0:
            raise PTPError("lua compile error: %r" % (self.readmsg(),))
        msgs, t0 = [], time.time()
        while time.time() - t0 < wait:
            st, _ = self.chdk(CMD_STATUS)
            if st[0] & 2:
                msgs.append(self.readmsg())
                continue
            if not st[0] & 1:
                break
            time.sleep(0.05)
        return msgs

    def upload(self, local, remote):
        data = open(local, "rb").read()
        name = remote.encode()
        self.chdk(CMD_UPLOAD, [], struct.pack("<I", len(name)) + name + data)

    def download(self, remote, local=None):
        self.chdk(CMD_TEMP, [0], remote.encode())
        _, d = self.chdk(CMD_DOWNLOAD)
        if local:
            open(local, "wb").write(d)
        return d

    def close(self):
        if self.session:
            try:
                self._txn(OC_CLOSE, [])
            except Exception:
                pass
        usb.util.release_interface(self.dev, 0)


def fmt_msg(m):
    """Decode a script message: subtype 1 nil, 2 bool, 3 int, 4 str, 5 table."""
    _, sub, d = m
    if sub in (2, 3) and len(d) >= 4:
        v = struct.unpack("<i", d[:4])[0]
        return bool(v) if sub == 2 else v
    if sub == 1:
        return None
    return d.decode(errors="replace")


def _int(s):
    return int(s, 0)


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    c = Cam()
    op = argv[0]
    if op == "ver":
        print("CHDK PTP %d.%d" % c.version())
    elif op == "peek":
        a, n = _int(argv[1]), _int(argv[2]) if len(argv) > 2 else 1
        for i, v in enumerate(c.peek(a, n)):
            print("%08x: %08x" % (a + 4 * i, v))
    elif op == "dump":
        a, n = _int(argv[1]), _int(argv[2])
        out, step = bytearray(), 0x10000
        for o in range(0, n, step):
            out += c.read(a + o, min(step, n - o))
        open(argv[3], "wb").write(out)
        print("%d bytes -> %s" % (len(out), argv[3]))
    elif op == "shadow":
        for r in argv[1:]:
            print("%08x = %08x" % (_int(r), c.shadow(_int(r))))
    elif op == "call":
        print("0x%08x" % c.call(*[_int(x) for x in argv[1:]]))
    elif op == "lua":
        for m in c.lua(argv[1]):
            print(m[0], fmt_msg(m))
    elif op == "up":
        c.upload(argv[1], argv[2])
    elif op == "down":
        c.download(argv[1], argv[2])
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
