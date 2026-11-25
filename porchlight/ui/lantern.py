"""The porch lantern beside the setup screens: an old lantern drawn in large pixels, with a
candle that flickers and now and then nearly goes out, moths around the glass, a slow sway
on its chain and a glow that falls off one level at a time.

    COLUMNS, ROWS      the cells it covers, two pixels high each
    TICK               the seconds from one picture to the next
    pixels(tick)       the picture at a moment: HEIGHT rows of WIDTH colors
    brightness(tick)   how strong the light is at a moment, from 0 to 1

Colors are numbers of the 256-color terminal palette; NIGHT is the dark the light does not
reach. The same tick always draws the same picture; nothing here draws or knows curses.
"""

import math

COLUMNS, ROWS = 30, 17
WIDTH, HEIGHT = COLUMNS, 2 * ROWS  # in pixels
TICK = 0.12

AMBER = 214
NIGHT = 233
GLOW = (NIGHT, 234, 235, 237, 94, 130, 172)  # from the dark to the nearest the light reaches
REACH, STEP = 22, 2.5  # pixels the light reaches at full strength, pixels per level
GLASS = (236, 94, 130, 136, 172, 178)  # from unlit to beside the flame
INK = {
    "K": 16,  # iron, outline
    "I": 237,  # iron
    "i": 240,  # iron, lit edge
    "R": 94,  # rust
    "r": 130,  # rust, lit
    "B": 136,  # brass
    "b": 94,  # brass, shade
    "C": 180,  # candle
    "c": 137,  # candle, shade
    "o": 202,  # flame, edge
    "f": 220,  # flame
    "F": 231,  # flame, core
    "M": 254,  # moth
    "m": 245,  # moth, wings
}

# 12 by 19 pixels; "g" is glass, shaded by its distance to the flame.
LANTERN = (
    ".....KK.....",
    "....KIIK....",
    "...KIiiIK...",
    "..KIiIiRIK..",
    ".KIiiIIirIK.",
    "KKKKKKKKKKKK",
    ".KggggggggK.",
    ".KggggggggK.",
    ".RggggggggK.",
    ".KggggggggK.",
    ".KggggggggK.",
    ".KggggggggR.",
    ".KggggggggK.",
    ".KggggggggK.",
    "KKKKKKKKKKKK",
    ".KBBBBBBBBK.",
    "..KbBbbBbK..",
    "...KKKKKK...",
    ".....KK.....",
)
FLAME_CENTER = (6, 9.5)  # inside the lantern
CANDLE = ("CCCc", "CCCc")  # at lantern column 4, row 12
FLAMES = (  # at lantern column 4, row 7
    ("..o.", ".of.", ".ff.", "oFFo", ".FF."),
    (".o..", ".fo.", ".ff.", "oFFo", ".FF."),
    ("....", ".of.", "offo", "oFFo", ".FF."),
    (".o..", ".of.", "offo", ".FFo", ".FF."),
    ("..o.", ".fo.", "oFf.", "oFFo", ".FF."),
)
WEAK_FLAMES = (  # as the light nearly goes out: the weaker, the smaller
    ("....", "....", ".o..", ".ff.", ".Ff."),
    ("....", "....", "....", ".o..", ".fo."),
    ("....", "....", "....", "....", ".o.."),
)
FLAME_ORDER = (0, 2, 1, 3, 4, 2, 0, 3, 1, 4, 2, 3, 0, 4, 1)  # never the same twice in a row
CHAIN = (("i", "I"), ("I", "K"), ("K", "K"))
HANG = (9, 8)  # the lantern's top left pixel when it hangs still
SWAY = 33  # ticks for one swing there and back

STEADY = (60, 85, 72, 95)  # ticks of steady light before each time it nearly goes out
GUTTER = (0.75, 0.4, 0.22, 0.38, 0.14, 0.1, 0.3, 0.6, 0.85, 1.0)
CYCLE = sum(STEADY) + len(STEADY) * len(GUTTER)

MOTHS = (  # (across, up and down, turn per tick, where it starts), in pixels and radians
    (9, 6, 0.11, 0.0),
    (11, 8, -0.08, 2.1),
    (7, 9, 0.14, 4.0),
)


def noise(x, y):
    """A fixed number from 0 to 1 for a pair of integers: the texture of the pixels."""
    n = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return (n ^ (n >> 16)) / 4294967296


def brightness(tick):
    """The light at a moment: steady with a small flicker, then nearly out for a moment."""
    at = tick % CYCLE
    for steady in STEADY:
        if at < steady:
            return 0.9 + 0.1 * noise(tick, 7)
        at -= steady
        if at < len(GUTTER):
            return GUTTER[at]
        at -= len(GUTTER)
    return 1.0  # not reached: the steps add up to the cycle


def flame(light, tick):
    if light > 0.5:
        return FLAMES[FLAME_ORDER[tick % len(FLAME_ORDER)]]
    return WEAK_FLAMES[0 if light > 0.3 else 1 if light > 0.15 else 2]


def pixels(tick):
    """The picture at a moment, as HEIGHT rows of WIDTH palette colors."""
    light = brightness(tick)
    sway = round(math.sin(tick * 2 * math.pi / SWAY) * 1.3)
    left, top = HANG[0] + sway, HANG[1]
    center_x, center_y = left + FLAME_CENTER[0], top + FLAME_CENTER[1]
    reach = REACH * light
    grid = []
    for y in range(HEIGHT):
        row = []
        for x in range(WIDTH):
            distance = abs(x + 0.5 - center_x) + abs(y + 0.5 - center_y)
            level = max(0, min(len(GLOW) - 1, int((reach - distance) // STEP)))
            if level and noise(x, y) < 0.2:
                level -= 1  # a fixed dither, so the glow has the grain of blocks
            row.append(GLOW[level])
        grid.append(row)

    def put(x, y, color):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            grid[y][x] = color

    def moth(x, y, open_wings):
        put(x, y, INK["M"])
        if open_wings:
            put(x - 1, y, INK["m"])
            put(x + 1, y, INK["m"])
        else:
            put(x, y - 1, INK["m"])

    spread = 1.6 if light < 0.8 else 1.0  # they scatter when the light fails
    moths = []
    for number, (across, upright, turn, start) in enumerate(MOTHS):
        angle = start + turn * tick + 0.25 * math.sin(0.37 * tick + start)
        moths.append(
            (
                round(center_x - 0.5 + math.cos(angle) * across * spread),
                round(center_y - 0.5 + math.sin(angle) * upright * spread),
                (tick + number) % 2 == 0,
                math.sin(angle + number) > 0,  # in front of the lantern, else behind it
            )
        )
    for x, y, open_wings, in_front in moths:
        if not in_front:
            moth(x, y, open_wings)

    for y in range(top):
        x = HANG[0] + 5 + round(sway * (y + 1) / top)  # from the fixed hook to the swinging ring
        put(x, y, INK[CHAIN[y % 3][0]])
        put(x + 1, y, INK[CHAIN[y % 3][1]])

    for y, line in enumerate(LANTERN):
        for x, ink in enumerate(line):
            if ink == "g":
                distance = abs(x + 0.5 - FLAME_CENTER[0]) + abs(y + 0.5 - FLAME_CENTER[1])
                shade = round(5 * light - distance * 0.5 + (noise(x, y + 40) - 0.5) * 1.4)
                put(left + x, top + y, GLASS[max(0, min(len(GLASS) - 1, shade))])
            elif ink != ".":
                put(left + x, top + y, INK[ink])
    for y, line in enumerate(CANDLE):
        for x, ink in enumerate(line):
            put(left + 4 + x, top + 12 + y, INK[ink])
    for y, line in enumerate(flame(light, tick)):
        for x, ink in enumerate(line):
            if ink != ".":
                put(left + 4 + x, top + 7 + y, INK[ink])

    for x, y, open_wings, in_front in moths:
        if in_front:
            moth(x, y, open_wings)
    return grid

