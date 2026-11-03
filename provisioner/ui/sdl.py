"""Drawing for the Provisioner: the system's SDL2 through ctypes (the one
EmulationStation uses, KMSDRM on the handheld; no pygame), with FireFly's
font (DejaVu Sans Mono, pre-rendered in assets/cockpit_font.bin, the same
file the Stump cockpit uses).

The layout takes the screen's own shape: a canvas as big as the screen,
or, on a screen narrower than 720, a bigger one scaled down by no more
than 0.8 so the type stays readable. 720x720 (the R36MAX) and 854x480 (the
OGS, RGB10 Max) are drawn 1:1; 640x480 (R36S, RG351V/MP, ...) is a 720x540
canvas; 480x320 (OGA, RK2020, RG351P/M) a 600x400 one. A panel mounted
sideways (the screen reports portrait) gets the picture turned: by the
panel's own `rotation` in the device tree when it says, else 270 degrees,
or PROVISIONER_ROTATE=0/90/180/270.

Only SDL 2.0.0 functions are used (the oldest SDL on these systems is
2.0.20-ish), so any SDL2 build works.
"""

import ctypes as C
import ctypes.util
import math
import os
import struct

W = H = 720                     # the canvas when nothing else is known (and the tests' default)
F10, F16, F20, F24, F30B = range(5)

SDL_INIT_VIDEO = 0x20
SDL_WINDOW_SHOWN = 0x4
SDL_WINDOW_FULLSCREEN_DESKTOP = 0x1001
SDL_WINDOW_HIDDEN = 0x8
SDL_WINDOWPOS_UNDEFINED = 0x1FFF0000
SDL_RENDERER_SOFTWARE = 1
SDL_RENDERER_ACCELERATED = 2
SDL_PIXELFORMAT_ABGR8888 = 0x16762004          # bytes R, G, B, A in memory (little-endian)
SDL_BLENDMODE_BLEND = 1
SDL_TEXTUREACCESS_TARGET = 2
MIN_SCALE = 0.8                 # a canvas is never shrunk more than this: the type stays readable
SDL_QUIT, SDL_KEYDOWN, SDL_TEXTINPUT = 0x100, 0x300, 0x303

# A keyboard's keys (a USB keyboard on the handheld, a computer's). Letters
# get their own names (kx...) so typing a "y" never means the Y button; what
# they type arrives separately, as ("text", "y").
SDLK = {13: "enter", 0x4000_0058: "enter", 27: "escape", 8: "backspace", 120: "kx", 121: "ky", 113: "kq",
        0x4000_0052: "up", 0x4000_0051: "down", 0x4000_0050: "left", 0x4000_004F: "right",
        9: "r", 0x4000_004B: "l", 0x4000_004E: "r"}


class Rect(C.Structure):
    _fields_ = [("x", C.c_int), ("y", C.c_int), ("w", C.c_int), ("h", C.c_int)]


def _lib():
    names = [os.environ.get("PROVISIONER_SDL2", ""), "libSDL2-2.0.so.0", ctypes.util.find_library("SDL2") or "",
             "/opt/homebrew/lib/libSDL2.dylib", "/usr/local/lib/libSDL2.dylib"]
    for n in names:
        if n:
            try:
                return C.CDLL(n)
            except OSError:
                pass
    raise RuntimeError("SDL2 not found (install libsdl2 / brew install sdl2)")


def canvas_for(w, h):
    """The canvas (layout size) for a screen of w x h (landscape)."""
    s = 1.0 if w >= W else max(MIN_SCALE, w / float(W))
    return int(round(w / s)), int(round(h / s))


def panel_rotation(dt="/proc/device-tree"):
    """The device tree's panel `rotation` (degrees), or None."""
    import glob
    for pat in ("*/panel*/rotation", "*/*/panel*/rotation", "*/*/*/panel*/rotation", "*/*/*/*/panel*/rotation"):
        for p in sorted(glob.glob(os.path.join(dt, pat))):
            try:
                with open(p, "rb") as f:
                    b = f.read(4)
                if len(b) == 4:
                    return struct.unpack(">I", b)[0] % 360
            except OSError:
                pass
    return None


def rotation_for(out_w, out_h, fullscreen, env=None, dt="/proc/device-tree"):
    """Degrees to turn the picture by: a portrait screen on the handheld is a
    panel mounted sideways (an SDL that already turns it reports landscape)."""
    env = os.environ if env is None else env
    forced = env.get("PROVISIONER_ROTATE", "")
    if forced.strip().isdigit():
        return int(forced) % 360
    if not fullscreen or out_h <= out_w:
        return 0
    r = panel_rotation(dt)
    return r if r in (90, 270) else 270


def is_fullscreen_driver(env=None):
    env = os.environ if env is None else env
    return env.get("PROVISIONER_FULLSCREEN") == "1" or env.get("SDL_VIDEODRIVER", "") in ("kmsdrm", "fbcon", "wayland")


def rgb(hexstr):
    v = int(hexstr.lstrip("#"), 16)
    return (v >> 16) & 255, (v >> 8) & 255, v & 255


def load_fonts(path):
    """[{px, adv64, asc, line, glyphs: {cp: (w, h, xo, yo, bytes)}}] from cockpit_font.bin."""
    with open(path, "rb") as f:
        buf = f.read()
    if buf[:8] != b"CKFONT1\0":
        raise ValueError("not a cockpit font")
    n = struct.unpack_from("<I", buf, 8)[0]
    pos, fonts = 12, []
    for _ in range(n):
        px, adv, asc, desc, line, bold, ng, dlen = struct.unpack_from("<HHhhHHII", buf, pos)
        pos += 20
        recs = [struct.unpack_from("<IhhHHI", buf, pos + 16 * k) for k in range(ng)]
        pos += 16 * ng
        data = buf[pos:pos + dlen]
        pos += dlen
        glyphs = {cp: (w, h, xo, yo, data[off:off + w * h]) for cp, xo, yo, w, h, off in recs}
        fonts.append({"px": px, "adv64": adv, "asc": asc, "line": line, "glyphs": glyphs})
    return fonts


class Display:
    def __init__(self, font_path, headless=False, windowed=None, screen=None, rotate=None):
        """screen: the window's size (the tests pretend a handheld's screen);
        rotate: degrees, None to work it out."""
        self.sdl = sdl = _lib()
        self._protos()
        if headless:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            os.environ.setdefault("SDL_RENDER_DRIVER", "software")
        sdl.SDL_SetHint(b"SDL_RENDER_SCALE_QUALITY", b"1")        # scaled type stays smooth
        if sdl.SDL_Init(SDL_INIT_VIDEO) != 0:
            raise RuntimeError("SDL_Init: %s" % sdl.SDL_GetError().decode())
        if windowed is None:
            windowed = headless or not is_fullscreen_driver()
        flags = (SDL_WINDOW_HIDDEN if headless else SDL_WINDOW_SHOWN) | (0 if windowed else SDL_WINDOW_FULLSCREEN_DESKTOP)
        sw, sh = screen or (W, H)
        self.win = sdl.SDL_CreateWindow(b"RK3326 Provisioner", SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED,
                                        sw, sh, flags)
        if not self.win:
            raise RuntimeError("SDL_CreateWindow: %s" % sdl.SDL_GetError().decode())
        self.ren = sdl.SDL_CreateRenderer(self.win, -1, SDL_RENDERER_SOFTWARE if headless else SDL_RENDERER_ACCELERATED)
        if not self.ren:
            self.ren = sdl.SDL_CreateRenderer(self.win, -1, SDL_RENDERER_SOFTWARE)
        if not self.ren:
            raise RuntimeError("SDL_CreateRenderer: %s" % sdl.SDL_GetError().decode())
        ow, oh = C.c_int(), C.c_int()
        sdl.SDL_GetRendererOutputSize(self.ren, C.byref(ow), C.byref(oh))
        self.out_size = (ow.value, oh.value)
        self.rot = rotation_for(ow.value, oh.value, not windowed) if rotate is None else rotate % 360
        lw, lh = (oh.value, ow.value) if self.rot in (90, 270) else (ow.value, oh.value)
        self.size = canvas_for(lw, lh)
        self.target = None
        if self.rot or self.size != (lw, lh):
            # Drawn on a texture the canvas's size, then scaled (and turned) onto
            # the screen in one go: scaling each shape alone leaves seams.
            self.target = sdl.SDL_CreateTexture(self.ren, SDL_PIXELFORMAT_ABGR8888, SDL_TEXTUREACCESS_TARGET,
                                                self.size[0], self.size[1])
            if not self.target or sdl.SDL_SetRenderTarget(self.ren, self.target) != 0:
                raise RuntimeError("can't draw on a texture to scale or turn (PROVISIONER_ROTATE=0 to try "
                                   "without turning): %s" % sdl.SDL_GetError().decode())
        sdl.SDL_ShowCursor(0)
        sdl.SDL_StartTextInput()
        sdl.SDL_SetRenderDrawBlendMode(self.ren, SDL_BLENDMODE_BLEND)
        self.fonts = load_fonts(font_path)
        self._atlases = [self._atlas(f) for f in self.fonts]

    def _protos(self):
        s, vp, i, u = self.sdl, C.c_void_p, C.c_int, C.c_uint32
        s.SDL_GetError.restype = C.c_char_p
        s.SDL_CreateWindow.restype = vp
        s.SDL_CreateWindow.argtypes = [C.c_char_p, i, i, i, i, u]
        s.SDL_CreateRenderer.restype = vp
        s.SDL_CreateRenderer.argtypes = [vp, i, u]
        s.SDL_CreateTexture.restype = vp
        s.SDL_CreateTexture.argtypes = [vp, u, i, i, i]
        for name, args in (("SDL_GetRendererOutputSize", [vp, C.POINTER(i), C.POINTER(i)]),
                           ("SDL_RenderSetLogicalSize", [vp, i, i]),
                           ("SDL_SetRenderDrawBlendMode", [vp, i]),
                           ("SDL_SetRenderDrawColor", [vp, C.c_uint8, C.c_uint8, C.c_uint8, C.c_uint8]),
                           ("SDL_RenderClear", [vp]), ("SDL_RenderPresent", [vp]),
                           ("SDL_RenderFillRect", [vp, C.POINTER(Rect)]),
                           ("SDL_RenderFillRects", [vp, C.POINTER(Rect), i]),
                           ("SDL_UpdateTexture", [vp, C.POINTER(Rect), vp, i]),
                           ("SDL_SetTextureBlendMode", [vp, i]),
                           ("SDL_SetTextureColorMod", [vp, C.c_uint8, C.c_uint8, C.c_uint8]),
                           ("SDL_RenderCopy", [vp, vp, C.POINTER(Rect), C.POINTER(Rect)]),
                           ("SDL_RenderReadPixels", [vp, C.POINTER(Rect), u, vp, i]),
                           ("SDL_SetRenderTarget", [vp, vp]), ("SDL_SetHint", [C.c_char_p, C.c_char_p]),
                           ("SDL_RenderCopyEx", [vp, vp, C.POINTER(Rect), C.POINTER(Rect), C.c_double, vp, i]),
                           ("SDL_PollEvent", [vp]), ("SDL_DestroyTexture", [vp]),
                           ("SDL_DestroyRenderer", [vp]), ("SDL_DestroyWindow", [vp])):
            getattr(s, name).argtypes = args

    # -- fonts as textures --
    def _atlas(self, font):
        aw, x, y, rowh, place = 1024, 0, 0, 0, {}
        for cp, (w, h, xo, yo, data) in font["glyphs"].items():
            if x + w > aw:
                x, y, rowh = 0, y + rowh + 1, 0
            place[cp] = (x, y, w, h, xo, yo)
            x += w + 1
            rowh = max(rowh, h)
        ah = y + rowh + 1
        px = bytearray(aw * ah * 4)
        for cp, (gx, gy, w, h, xo, yo) in place.items():
            data = font["glyphs"][cp][4]
            for r in range(h):
                row = data[r * w:(r + 1) * w]
                o = ((gy + r) * aw + gx) * 4
                for c, a in enumerate(row):
                    if a:
                        px[o + 4 * c:o + 4 * c + 4] = bytes((255, 255, 255, a))
        tex = self.sdl.SDL_CreateTexture(self.ren, SDL_PIXELFORMAT_ABGR8888, 0, aw, ah)
        buf = (C.c_char * len(px)).from_buffer(px)
        self.sdl.SDL_UpdateTexture(tex, None, buf, aw * 4)
        self.sdl.SDL_SetTextureBlendMode(tex, SDL_BLENDMODE_BLEND)
        return tex, place

    def text(self, fid, x, y_top, s, color, max_w=0):
        """Draws s; returns its width. Cut (with …) at max_w when given."""
        f = self.fonts[fid]
        tex, place = self._atlases[fid]
        s = str(s)
        if max_w and self.text_width(fid, s) > max_w:
            fit = max(0, max_w * 64 // f["adv64"] - 1)     # monospace: the cut is a count
            s = s[:fit] + "…"
        self.sdl.SDL_SetTextureColorMod(tex, *color)
        base, acc = y_top + f["asc"], 0
        src, dst = Rect(), Rect()
        for ch in s:
            p = place.get(ord(ch)) or place.get(ord("?"))
            if p:
                gx, gy, w, h, xo, yo = p
                if w and h:
                    src.x, src.y, src.w, src.h = gx, gy, w, h
                    dst.x, dst.y, dst.w, dst.h = x + acc // 64 + xo, base + yo, w, h
                    self.sdl.SDL_RenderCopy(self.ren, tex, C.byref(src), C.byref(dst))
            acc += f["adv64"]
        return acc // 64

    def text_width(self, fid, s):
        return len(str(s)) * self.fonts[fid]["adv64"] // 64

    def line(self, fid):
        return self.fonts[fid]["line"]

    def has(self, ch):
        return all(ord(ch) in a[1] for a in self._atlases)

    # -- shapes --
    def color(self, c, a=255):
        self.sdl.SDL_SetRenderDrawColor(self.ren, c[0], c[1], c[2], a)

    def clear(self, c):
        self.color(c)
        self.sdl.SDL_RenderClear(self.ren)

    def fill(self, x, y, w, h, c):
        self.color(c)
        self.sdl.SDL_RenderFillRect(self.ren, C.byref(Rect(int(x), int(y), int(w), int(h))))

    def fill_rrect(self, x, y, w, h, r, c):
        r = max(0, min(r, w // 2, h // 2))
        rects = [Rect(x, y + r, w, h - 2 * r)]
        for i in range(r):
            dy = r - i - 0.5
            inset = int(round(r - math.sqrt(max(0.0, r * r - dy * dy))))
            rects.append(Rect(x + inset, y + i, w - 2 * inset, 1))
            rects.append(Rect(x + inset, y + h - 1 - i, w - 2 * inset, 1))
        arr = (Rect * len(rects))(*rects)
        self.color(c)
        self.sdl.SDL_RenderFillRects(self.ren, arr, len(rects))

    def stroke_rrect(self, x, y, w, h, r, edge, inside):
        self.fill_rrect(x, y, w, h, r, edge)
        self.fill_rrect(x + 2, y + 2, w - 4, h - 4, max(0, r - 2), inside)

    def _turned(self):
        """Copies the canvas, turned and scaled, onto the screen (the target is the screen)."""
        sdl, (ow, oh), (cw, ch) = self.sdl, self.out_size, self.size
        lw, lh = (oh, ow) if self.rot in (90, 270) else (ow, oh)
        s = min(lw / float(cw), lh / float(ch))
        dw, dh = int(round(cw * s)), int(round(ch * s))
        dst = Rect((ow - dw) // 2, (oh - dh) // 2, dw, dh)       # turned about its centre: fills the screen
        sdl.SDL_SetRenderDrawColor(self.ren, 0, 0, 0, 255)
        sdl.SDL_RenderClear(self.ren)
        sdl.SDL_RenderCopyEx(self.ren, self.target, None, C.byref(dst), float(self.rot), None, 0)

    def present(self):
        if self.target:
            self.sdl.SDL_SetRenderTarget(self.ren, None)
            self._turned()
            self.sdl.SDL_RenderPresent(self.ren)
            self.sdl.SDL_SetRenderTarget(self.ren, self.target)
        else:
            self.sdl.SDL_RenderPresent(self.ren)

    def events(self):
        """Keyboard actions since the last call (a USB keyboard, a computer)."""
        out, ev = [], (C.c_uint8 * 64)()
        while self.sdl.SDL_PollEvent(ev):
            etype = struct.unpack_from("<I", bytes(ev[:4]))[0]
            if etype == SDL_QUIT:
                out.append("quit")
            elif etype == SDL_KEYDOWN:
                sym = struct.unpack_from("<i", bytes(ev[20:24]))[0]
                act = SDLK.get(sym)
                if act:
                    out.append(act)
            elif etype == SDL_TEXTINPUT:
                txt = bytes(ev[12:44]).split(b"\0", 1)[0].decode("utf-8", "replace")
                if txt:
                    out.append(("text", txt))
        return out

    def snapshot(self):
        """(w, h, RGBA bytes) of what's on the screen (the tests' screenshots)."""
        ow, oh = self.out_size
        buf = (C.c_uint8 * (ow * oh * 4))()
        if self.target:
            self.sdl.SDL_SetRenderTarget(self.ren, None)
            self._turned()
        self.sdl.SDL_RenderReadPixels(self.ren, None, SDL_PIXELFORMAT_ABGR8888, buf, ow * 4)
        if self.target:
            self.sdl.SDL_SetRenderTarget(self.ren, self.target)
        return ow, oh, bytes(buf)

    def close(self):
        for tex, _ in self._atlases:
            self.sdl.SDL_DestroyTexture(tex)
        if self.target:
            self.sdl.SDL_DestroyTexture(self.target)
        self.sdl.SDL_DestroyRenderer(self.ren)
        self.sdl.SDL_DestroyWindow(self.win)
        self.sdl.SDL_Quit()


def write_png(path, w, h, rgba):
    import zlib
    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
                chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
