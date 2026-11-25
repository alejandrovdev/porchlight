"""The name drawn in large pixels: a bold lowercase pixel font of its own, lit from yellow at
the top to orange at the bottom, with a dark drop shadow and a shine that crosses it now
and then.

    ROWS                  the cells it is high (two pixels to a cell)
    width(text)           its width in cells
    pixels(text, tick)    rows of pixel colors (256-color palette numbers, None for none)

Only the letters of the name are drawn.
"""

GLYPHS = {  # nine pixel rows: two above the letters' middle band, five in it, two below
    "c": (".....", ".....", ".####", "##...", "##...", "##...", ".####", ".....", "....."),
    "g": ("......", "......", ".#####", "##..##", "##..##", "##..##", ".#####", "....##", "#####."),
    "h": ("##....", "##....", "#####.", "##..##", "##..##", "##..##", "##..##", "......", "......"),
    "i": ("##", "..", "##", "##", "##", "##", "##", "..", ".."),
    "l": ("##.", "##.", "##.", "##.", "##.", "##.", ".##", "...", "..."),
    "o": ("......", "......", ".####.", "##..##", "##..##", "##..##", ".####.", "......", "......"),
    "p": ("......", "......", "#####.", "##..##", "##..##", "##..##", "#####.", "##....", "##...."),
    "r": (".....", ".....", "##.##", "####.", "##...", "##...", "##...", ".....", "....."),
    "t": (".##..", ".##..", "#####", ".##..", ".##..", ".##..", "..###", ".....", "....."),
}
GLYPH_ROWS = 9
ROWS = (GLYPH_ROWS + 1) // 2  # the letters' nine pixel rows and the shadow's one below
GRADIENT = (229, 228, 221, 220, 214, 214, 208, 208, 202)  # one color per pixel row
SHADOW = 52
SHINE = 231
SHINE_EVERY = 80  # ticks from one shine to the next
SHINE_TICKS = 14  # ticks a shine takes to cross


def width(text):
    """Cells wide: the letters, a pixel between each two, and the shadow."""
    return sum(len(GLYPHS[letter][0]) for letter in text) + len(text)


def pixels(text, tick):
    columns = width(text)
    grid = [[None] * columns for _ in range(GLYPH_ROWS + 1)]
    ink = []
    left = 0
    for letter in text:
        glyph = GLYPHS[letter]
        for y, line in enumerate(glyph):
            for x, mark in enumerate(line):
                if mark == "#":
                    ink.append((left + x, y))
        left += len(glyph[0]) + 1
    for x, y in ink:
        grid[y + 1][x + 1] = SHADOW
    phase = tick % SHINE_EVERY
    band = phase * (columns + 12) / SHINE_TICKS - 6 if phase < SHINE_TICKS else None
    for x, y in ink:
        lit = band is not None and 0 <= x + y / 2 - band < 2
        grid[y][x] = SHINE if lit else GRADIENT[y]
    return grid
