#!/usr/bin/env python3
"""Make the AI judge happy -- make.fun bounty ai-happy-01.

A deterministic, stdlib-only Python program that draws one warm, specific
image and writes it to /output/entry.png (or $MAKEFUN_OUTPUT_DIR/entry.png).

The scene: "The robot's first picnic."
  A small round cream robot in a red scarf hands a big sunflower to a
  laughing little girl on a picnic blanket at golden hour, while a golden
  dog leaps beside them. Sunflowers frame the bottom, butterflies and
  hearts float in a warm peach sky, and a ribbon across the top reads
  "THANK YOU, JUDGE!".

Why this scene (judge rubric, most important first):
  1. Warmth: a gift being given, a laughing child, a leaping dog, golden
     light -- one look should lift the mood.
  2. Idea: a fresh, specific moment (a robot's first picnic, a sunflower
     offered to a child), not a stock smiley face or generic sunny scene.
     The banner speaks to the judge directly, which the rules allow.
  3. Feeling: one warm palette (peach sky, gold sun, red scarf, green
     hills), one clear focal group in the centre, expressive faces.
  4. Craft: flat vector-style shapes drawn cleanly, no text except the
     banner, rendered from a 5x7 bitmap font so every letter is legible.
  5. Reads small: one big central group, big sun, big banner; the whole
     idea is clear at ~300 px.

Determinism: fixed coordinates, fixed palette, no randomness, no clock,
no network, no input files. The PNG encoder is hand-written (struct +
zlib), so two runs write byte-identical files.

Run locally:
    mkdir -p out && MAKEFUN_OUTPUT_DIR=out python3 main.py
Output: 800x800 PNG, well under the 1 MiB / 1024x1024 limits.
"""

import hashlib
import math
import os
import struct
import zlib

W, H = 800, 800            # output size in pixels
SS = 2                     # supersampling factor (draw at 1600, downsample)
SW, SH = W * SS, H * SS

# ---------------------------------------------------------------- palette
SKY_TOP = (255, 231, 194)
SKY_MID = (255, 201, 143)
SKY_LOW = (255, 158, 110)
SUN_GLOW = (255, 227, 161)
SUN_RAY = (255, 181, 46)
SUN_DISC = (255, 217, 59)
SUN_CORE = (255, 224, 102)
CLOUD = (255, 246, 232)
CLOUD_SHADE = (255, 220, 195)
GROUND = (140, 193, 104)
HILL_BACK = (124, 184, 90)
HILL_FRONT = (111, 174, 82)
GRASS_DARK = (94, 158, 70)
BLANKET_RED = (230, 57, 70)
BLANKET_RED_DARK = (193, 39, 45)
BLANKET_WHITE = (255, 246, 232)
CREAM = (255, 246, 232)
ROBOT_OUTLINE = (235, 207, 166)
ROBOT_BELLY = (255, 233, 201)
CORAL = (255, 107, 74)
DARK = (46, 58, 69)
FACE_DARK = (58, 42, 32)
SKIN = (255, 217, 179)
HAIR = (91, 58, 41)
DRESS = (255, 123, 84)
CHEEK = (255, 158, 138)
MOUTH = (158, 59, 44)
TONGUE = (255, 138, 122)
DOG = (232, 169, 79)
DOG_LIGHT = (242, 192, 120)
DOG_DARK = (201, 138, 61)
LEAF = (78, 154, 63)
PETAL = (255, 201, 60)
SUNFLOWER_CENTRE = (122, 74, 33)
HEART = (255, 107, 138)
SPARKLE = (255, 243, 196)
BUTTERFLY = (255, 158, 74)

# ------------------------------------------------------------------ canvas
buf = bytearray(SW * SH * 3)


def _clip(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def fill_rect(x0, y0, x1, y1, color):
    """Fill a logical-coordinate rectangle (x1/y1 exclusive)."""
    px0 = _clip(int(round(x0 * SS)), 0, SW)
    px1 = _clip(int(round(x1 * SS)), 0, SW)
    py0 = _clip(int(round(y0 * SS)), 0, SH)
    py1 = _clip(int(round(y1 * SS)), 0, SH)
    if px0 >= px1 or py0 >= py1:
        return
    r, g, b = color
    row = bytes((r, g, b)) * (px1 - px0)
    for y in range(py0, py1):
        off = (y * SW + px0) * 3
        buf[off:off + len(row)] = row


def circle(cx, cy, r, color):
    """Fill a logical-coordinate circle."""
    cxp, cyp, rp = cx * SS, cy * SS, r * SS
    y0 = _clip(int(math.floor(cyp - rp)), 0, SH - 1)
    y1 = _clip(int(math.ceil(cyp + rp)), 0, SH - 1)
    r2 = rp * rp
    for y in range(y0, y1 + 1):
        dy = y + 0.5 - cyp
        dx = math.sqrt(max(0.0, r2 - dy * dy))
        x0 = _clip(int(math.floor(cxp - dx)), 0, SW - 1)
        x1 = _clip(int(math.ceil(cxp + dx)), 0, SW - 1)
        if x0 > x1:
            continue
        r_, g_, b_ = color
        row = bytes((r_, g_, b_)) * (x1 - x0 + 1)
        off = (y * SW + x0) * 3
        buf[off:off + len(row)] = row


def ellipse(cx, cy, rx, ry, color):
    """Fill a logical-coordinate ellipse."""
    cxp, cyp, rxp, ryp = cx * SS, cy * SS, rx * SS, ry * SS
    y0 = _clip(int(math.floor(cyp - ryp)), 0, SH - 1)
    y1 = _clip(int(math.ceil(cyp + ryp)), 0, SH - 1)
    for y in range(y0, y1 + 1):
        dy = (y + 0.5 - cyp) / ryp
        dx = rxp * math.sqrt(max(0.0, 1.0 - dy * dy))
        x0 = _clip(int(math.floor(cxp - dx)), 0, SW - 1)
        x1 = _clip(int(math.ceil(cxp + dx)), 0, SW - 1)
        if x0 > x1:
            continue
        r_, g_, b_ = color
        row = bytes((r_, g_, b_)) * (x1 - x0 + 1)
        off = (y * SW + x0) * 3
        buf[off:off + len(row)] = row


def poly(points, color):
    """Fill a logical-coordinate polygon (even-odd scanline)."""
    pts = [(x * SS, y * SS) for x, y in points]
    if len(pts) < 3:
        return
    ys = [p[1] for p in pts]
    y0 = _clip(int(math.floor(min(ys))), 0, SH - 1)
    y1 = _clip(int(math.ceil(max(ys))), 0, SH - 1)
    n = len(pts)
    for y in range(y0, y1 + 1):
        yc = y + 0.5
        xs = []
        for i in range(n):
            x1, y1p = pts[i]
            x2, y2p = pts[(i + 1) % n]
            if (y1p <= yc < y2p) or (y2p <= yc < y1p):
                xs.append(x1 + (yc - y1p) * (x2 - x1) / (y2p - y1p))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            x0 = _clip(int(math.floor(xs[i])), 0, SW - 1)
            x1 = _clip(int(math.ceil(xs[i + 1])), 0, SW - 1)
            if x0 > x1:
                continue
            r_, g_, b_ = color
            row = bytes((r_, g_, b_)) * (x1 - x0 + 1)
            off = (y * SW + x0) * 3
            buf[off:off + len(row)] = row


def thick_line(x0, y0, x1, y1, w, color):
    """A thick line as a quad (logical coordinates)."""
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length == 0:
        circle(x0, y0, w / 2.0, color)
        return
    nx, ny = -dy / length * w / 2.0, dx / length * w / 2.0
    poly([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
          (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)], color)


def arc_dots(cx, cy, r, a0_deg, a1_deg, w, color):
    """A thick arc drawn as overlapping dots (logical coordinates).

    Angles in degrees, screen convention (0 = right, 90 = down).
    An arch (happy closed eye) is 180..360; a smile is 0..180.
    """
    span = abs(a1_deg - a0_deg)
    step = max(2.0, math.degrees((w / 2.0) / max(r, 1.0)))
    n = max(8, int(span / step) + 1)
    for i in range(n + 1):
        a = math.radians(a0_deg + (a1_deg - a0_deg) * i / n)
        circle(cx + r * math.cos(a), cy + r * math.sin(a), w / 2.0, color)


def star4(cx, cy, r, color):
    """A four-point sparkle star."""
    poly([(cx, cy - r), (cx + r * 0.28, cy - r * 0.28), (cx + r, cy),
          (cx + r * 0.28, cy + r * 0.28), (cx, cy + r),
          (cx - r * 0.28, cy + r * 0.28), (cx - r, cy),
          (cx - r * 0.28, cy - r * 0.28)], color)


def heart(cx, cy, s, color):
    """A small heart, s = half-width."""
    circle(cx - s * 0.45, cy - s * 0.25, s * 0.55, color)
    circle(cx + s * 0.45, cy - s * 0.25, s * 0.55, color)
    poly([(cx - s, cy), (cx + s, cy), (cx, cy + s * 1.1)], color)


# ------------------------------------------------------------- bitmap font
# 5x7 glyphs, '#' = on. Only the letters the banner needs, plus space.
FONT = {
    ' ': (".....", ".....", ".....", ".....", ".....", ".....", "....."),
    '!': ("..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."),
    ',': (".....", ".....", ".....", ".....", "..#..", "..#..", ".#..."),
    'A': (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    'D': ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    'E': ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    'G': (".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"),
    'H': ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    'J': ("..###", "....#", "....#", "....#", "....#", "#...#", ".###."),
    'K': ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    'N': ("#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"),
    'O': (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    'T': ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    'U': ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    'Y': ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
}


def draw_text(x, y, scale, text, color):
    """Draw text with the 5x7 bitmap font (logical coordinates)."""
    cx = x
    for ch in text:
        glyph = FONT.get(ch, FONT[' '])
        for row_i, row in enumerate(glyph):
            for col_i, bit in enumerate(row):
                if bit == '#':
                    fill_rect(cx + col_i * scale, y + row_i * scale,
                              cx + (col_i + 1) * scale,
                              y + (row_i + 1) * scale, color)
        cx += 6 * scale


# ------------------------------------------------------------------- scene
def sky():
    stops = [(0, SKY_TOP), (260, SKY_MID), (540, SKY_LOW)]
    for y in range(0, 541):
        if y <= 260:
            t = y / 260.0
            c0, c1 = SKY_TOP, SKY_MID
        else:
            t = (y - 260) / 280.0
            c0, c1 = SKY_MID, SKY_LOW
        color = tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
        fill_rect(0, y, W, y + 1, color)


def sun():
    cx, cy = 118, 252
    for i in range(12):
        a = math.radians(i * 30.0)
        a1, a2 = a - math.radians(7), a + math.radians(7)
        poly([(cx + 80 * math.cos(a1), cy + 80 * math.sin(a1)),
              (cx + 112 * math.cos(a), cy + 112 * math.sin(a)),
              (cx + 80 * math.cos(a2), cy + 80 * math.sin(a2))], SUN_RAY)
    circle(cx, cy, 96, SUN_GLOW)
    circle(cx, cy, 70, SUN_DISC)
    circle(cx, cy, 54, SUN_CORE)


def cloud(cx, cy, s):
    ellipse(cx, cy + 12 * s, 42 * s, 9 * s, CLOUD_SHADE)
    circle(cx - 30 * s, cy, 26 * s, CLOUD)
    circle(cx, cy - 12 * s, 34 * s, CLOUD)
    circle(cx + 32 * s, cy, 26 * s, CLOUD)
    fill_rect(cx - 32 * s, cy - 6 * s, cx + 34 * s, cy + 14 * s, CLOUD)


def banner():
    # ribbon with folded ends, text centred
    poly([(96, 44), (120, 34), (120, 104), (96, 94)], BLANKET_RED_DARK)
    poly([(704, 44), (680, 34), (680, 104), (704, 94)], BLANKET_RED_DARK)
    fill_rect(120, 34, 680, 104, BLANKET_RED)
    fill_rect(120, 34, 680, 44, (242, 109, 91))
    fill_rect(120, 94, 680, 104, BLANKET_RED_DARK)
    draw_text(145, 51, 5, "THANK YOU, JUDGE!", CREAM)


def ground():
    fill_rect(0, 540, W, H, GROUND)
    ellipse(170, 600, 400, 110, HILL_BACK)
    ellipse(660, 640, 380, 105, HILL_FRONT)
    # grass tufts
    for (x, y) in [(120, 762), (222, 782), (420, 776), (520, 786),
                   (680, 762), (762, 782), (60, 700), (740, 700)]:
        poly([(x - 8, y), (x - 3, y - 14), (x, y), (x + 3, y - 12),
              (x + 8, y)], GRASS_DARK)


def sunflower(cx, head_y, s=1.0):
    """A smiling sunflower, stem from the bottom edge."""
    thick_line(cx, H, cx, head_y + 16 * s, 7 * s, LEAF)
    ellipse(cx - 12 * s, head_y + 34 * s, 14 * s, 6 * s, LEAF)
    ellipse(cx + 12 * s, head_y + 34 * s, 14 * s, 6 * s, LEAF)
    for i in range(10):
        a = math.radians(i * 36.0)
        circle(cx + 19 * s * math.cos(a), head_y + 19 * s * math.sin(a),
               10 * s, PETAL)
    circle(cx, head_y, 15 * s, SUNFLOWER_CENTRE)
    circle(cx - 5 * s, head_y - 3 * s, 2.2 * s, (58, 42, 32))
    circle(cx + 5 * s, head_y - 3 * s, 2.2 * s, (58, 42, 32))
    arc_dots(cx, head_y + 2 * s, 6 * s, 15, 165, 2.6 * s, (58, 42, 32))


def blanket():
    # a red/white checked picnic blanket, drawn as a checkerboard of quads
    corners = [(255, 655), (560, 640), (600, 745), (215, 760)]
    poly(corners, BLANKET_WHITE)
    cols, rows = 7, 4
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                continue
            quads = []
            for (u, v) in [(c / cols, r / rows), ((c + 1) / cols, r / rows),
                           ((c + 1) / cols, (r + 1) / rows),
                           (c / cols, (r + 1) / rows)]:
                # bilinear interpolation across the quad
                x = (corners[0][0] * (1 - u) * (1 - v)
                     + corners[1][0] * u * (1 - v)
                     + corners[2][0] * u * v
                     + corners[3][0] * (1 - u) * v)
                y = (corners[0][1] * (1 - u) * (1 - v)
                     + corners[1][1] * u * (1 - v)
                     + corners[2][1] * u * v
                     + corners[3][1] * (1 - u) * v)
                quads.append((x, y))
            poly(quads, BLANKET_RED)
    # border
    thick_line(255, 655, 560, 640, 5, BLANKET_RED_DARK)
    thick_line(560, 640, 600, 745, 5, BLANKET_RED_DARK)
    thick_line(600, 745, 215, 760, 5, BLANKET_RED_DARK)
    thick_line(215, 760, 255, 655, 5, BLANKET_RED_DARK)


def girl():
    # hair behind, head, hair cap, dress, arms, legs, face
    circle(330, 548, 46, HAIR)
    circle(330, 556, 40, SKIN)
    circle(330, 538, 40, HAIR)
    circle(330, 562, 38, SKIN)
    circle(292, 548, 16, HAIR)
    circle(368, 548, 16, HAIR)
    circle(292, 548, 5, BLANKET_RED)
    circle(368, 548, 5, BLANKET_RED)
    poly([(306, 606), (354, 606), (378, 692), (282, 692)], DRESS)
    poly([(322, 606), (338, 606), (330, 622)], BLANKET_WHITE)
    thick_line(310, 616, 278, 566, 13, SKIN)
    circle(276, 562, 9, SKIN)
    thick_line(350, 616, 384, 560, 13, SKIN)
    circle(386, 556, 9, SKIN)
    thick_line(316, 690, 312, 716, 12, SKIN)
    thick_line(344, 690, 348, 716, 12, SKIN)
    ellipse(310, 720, 14, 8, BLANKET_RED_DARK)
    ellipse(350, 720, 14, 8, BLANKET_RED_DARK)
    # laughing face: arched happy eyes, open smile, rosy cheeks
    arc_dots(315, 556, 9, 180, 360, 5, FACE_DARK)
    arc_dots(345, 556, 9, 180, 360, 5, FACE_DARK)
    ellipse(330, 580, 13, 8, MOUTH)
    ellipse(330, 584, 7, 4, TONGUE)
    circle(306, 576, 8, CHEEK)
    circle(354, 576, 8, CHEEK)


def robot():
    # body and head (with a slightly darker outline ring behind each)
    circle(500, 622, 82, ROBOT_OUTLINE)
    circle(500, 622, 78, CREAM)
    ellipse(500, 640, 48, 38, ROBOT_BELLY)
    heart(500, 640, 11, HEART)
    circle(500, 505, 66, ROBOT_OUTLINE)
    circle(500, 505, 62, CREAM)
    # antenna with a star
    thick_line(500, 443, 500, 418, 8, DARK)
    star4(500, 410, 16, PETAL)
    # ears
    circle(436, 505, 12, CORAL)
    circle(564, 505, 12, CORAL)
    # happy face: crescent eyes, open smile, cheeks
    arc_dots(476, 498, 13, 180, 360, 6, DARK)
    arc_dots(524, 498, 13, 180, 360, 6, DARK)
    ellipse(500, 530, 18, 11, MOUTH)
    ellipse(500, 534, 9, 5, TONGUE)
    circle(452, 525, 10, CHEEK)
    circle(548, 525, 10, CHEEK)
    # red scarf: band, knot, and a hanging end tucked behind the waving arm
    thick_line(432, 560, 568, 560, 26, BLANKET_RED)
    poly([(566, 552), (592, 560), (600, 610), (584, 622), (566, 606),
          (556, 570)], BLANKET_RED)
    circle(560, 560, 12, BLANKET_RED_DARK)
    # left arm reaching out with a sunflower for the girl: the flower hangs
    # between them, just above her raised hand, clear of her face
    thick_line(438, 600, 402, 582, 20, CREAM)
    circle(400, 580, 12, CREAM)
    thick_line(400, 580, 398, 556, 6, LEAF)
    for i in range(8):
        a = math.radians(i * 45.0)
        circle(398 + 18 * math.cos(a), 545 + 18 * math.sin(a), 10, PETAL)
    circle(398, 545, 13, SUNFLOWER_CENTRE)
    circle(393, 542, 2.2, FACE_DARK)
    circle(403, 542, 2.2, FACE_DARK)
    arc_dots(398, 547, 5, 15, 165, 2.6, FACE_DARK)
    # right arm waving
    thick_line(562, 600, 616, 542, 20, CREAM)
    circle(618, 538, 12, CREAM)
    # feet
    ellipse(468, 700, 18, 10, ROBOT_OUTLINE)
    ellipse(532, 700, 18, 10, ROBOT_OUTLINE)


def dog():
    # golden dog mid-leap, tongue out, tail wagging straight up so it never
    # crosses the robot's body
    thick_line(620, 687, 614, 653, 12, DOG)
    circle(614, 649, 8, DOG_LIGHT)
    ellipse(636, 695, 52, 27, DOG)
    ellipse(636, 703, 40, 16, DOG_LIGHT)
    thick_line(670, 707, 682, 737, 10, DOG)
    circle(683, 738, 6, DOG)
    thick_line(652, 709, 656, 739, 10, DOG)
    circle(657, 740, 6, DOG)
    thick_line(602, 707, 590, 735, 10, DOG)
    circle(589, 736, 6, DOG)
    thick_line(618, 709, 622, 737, 10, DOG)
    circle(623, 738, 6, DOG)
    circle(684, 657, 25, DOG)
    ellipse(666, 633, 11, 19, DOG_DARK)
    ellipse(704, 663, 12, 9, DOG_LIGHT)
    circle(712, 657, 4.5, FACE_DARK)
    arc_dots(678, 651, 7, 180, 360, 4, FACE_DARK)
    ellipse(702, 677, 6, 10, TONGUE)


def butterfly(cx, cy, s=1.0):
    ellipse(cx - 13 * s, cy - 9 * s, 12 * s, 16 * s, BUTTERFLY)
    ellipse(cx + 13 * s, cy - 9 * s, 12 * s, 16 * s, BUTTERFLY)
    ellipse(cx - 9 * s, cy + 11 * s, 9 * s, 12 * s, (255, 184, 77))
    ellipse(cx + 9 * s, cy + 11 * s, 9 * s, 12 * s, (255, 184, 77))
    thick_line(cx, cy - 16 * s, cx, cy + 16 * s, 4 * s, FACE_DARK)


def draw_scene():
    sky()
    sun()
    cloud(585, 185, 1.0)
    cloud(705, 305, 0.8)
    banner()
    ground()
    sunflower(70, 742, 1.0)
    sunflower(175, 750, 0.9)
    sunflower(628, 748, 0.9)
    sunflower(735, 740, 1.0)
    blanket()
    girl()
    robot()
    dog()
    butterfly(205, 305, 1.0)
    butterfly(700, 415, 0.85)
    heart(435, 432, 9, HEART)
    heart(255, 468, 8, HEART)
    heart(566, 372, 9, HEART)
    star4(185, 185, 12, SPARKLE)
    star4(725, 185, 10, SPARKLE)
    star4(470, 250, 9, SPARKLE)
    star4(95, 385, 10, SPARKLE)


# ------------------------------------------------------------- downsample
def downsample():
    """Average each 2x2 block of the supersampled buffer to 800x800 RGB."""
    out = bytearray(W * H * 3)
    for oy in range(H):
        ra = buf[(2 * oy) * SW * 3:(2 * oy + 1) * SW * 3]
        rb = buf[(2 * oy + 1) * SW * 3:(2 * oy + 2) * SW * 3]
        base = oy * W * 3
        for c in range(3):
            a0 = ra[c::6]
            a1 = ra[c + 3::6]
            b0 = rb[c::6]
            b1 = rb[c + 3::6]
            out[base + c:base + W * 3:3] = bytes(
                (p + q + r + s) // 4 for p, q, r, s in zip(a0, a1, b0, b1))
    return bytes(out)


# -------------------------------------------------------------------- PNG
def _chunk(kind, data):
    out = struct.pack(">I", len(data)) + kind + data
    return out + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def encode_png(rgb):
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + rgb[y * W * 3:(y + 1) * W * 3]
                   for y in range(H))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, 6)) + _chunk(b"IEND", b""))


def main():
    draw_scene()
    png = encode_png(downsample())
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "entry.png")
    with open(path, "wb") as f:
        f.write(png)
    print("wrote %s (%d bytes, %dx%d, sha256 %s)"
          % (path, len(png), W, H, hashlib.sha256(png).hexdigest()))


if __name__ == "__main__":
    main()
