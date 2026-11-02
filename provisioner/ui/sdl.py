"""Drawing for the Provisioner: the system's SDL2 through ctypes (the one
EmulationStation uses, KMSDRM on the handheld; no pygame), with FireFly's
font (DejaVu Sans Mono, pre-rendered in assets/cockpit_font.bin, the same
file the Stump cockpit uses).

The screen is laid out at 720x720 (the R36MAX); any other screen (the
R36S's 640x480, a computer window) shows it scaled to fit.
"""

import ctypes as C
import ctypes.util
import math
import os
import struct

W = H = 720
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
SDL_QUIT, SDL_KEYDOWN = 0x100, 0x300

SDLK = {13: "a", 0x4000_0058: "a", 27: "b", 8: "b", 120: "x", 121: "y", 32: "x",
        0x4000_0052: "up", 0x4000_0051: "down", 0x4000_0050: "left", 0x4000_004F: "right",
        9: "r", 113: "quit", 0x4000_004B: "l", 0x4000_004E: "r"}


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
    def __init__(self, font_path, headless=False, windowed=None):
        self.sdl = sdl = _lib()
        self._protos()
        if headless:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            os.environ.setdefault("SDL_RENDER_DRIVER", "software")
        if sdl.SDL_Init(SDL_INIT_VIDEO) != 0:
            raise RuntimeError("SDL_Init: %s" % sdl.SDL_GetError().decode())
        if windowed is None:
            windowed = headless or os.environ.get("SDL_VIDEODRIVER", "") not in ("kmsdrm", "fbcon")
        flags = (SDL_WINDOW_HIDDEN if headless else SDL_WINDOW_SHOWN) | (0 if windowed else SDL_WINDOW_FULLSCREEN_DESKTOP)
        self.win = sdl.SDL_CreateWindow(b"RK3326 Provisioner", SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED,
                                        W, H, flags)
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
        if self.out_size != (W, H):
            sdl.SDL_RenderSetLogicalSize(self.ren, W, H)   # the 720x720 layout, scaled to fit
        sdl.SDL_ShowCursor(0)
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
            while s and self.text_width(fid, s + "…") > max_w:
                s = s[:-1]
            s += "…"
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

    def present(self):
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
        return out

    def snapshot(self):
        """(w, h, RGBA bytes) of what's drawn (the tests' screenshots)."""
        ow, oh = self.out_size
        buf = (C.c_uint8 * (ow * oh * 4))()
        self.sdl.SDL_RenderReadPixels(self.ren, None, SDL_PIXELFORMAT_ABGR8888, buf, ow * 4)
        return ow, oh, bytes(buf)

    def close(self):
        for tex, _ in self._atlases:
            self.sdl.SDL_DestroyTexture(tex)
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
