"""Tests of the full-screen layout of the setup screens: the canvas it is drawn on, the pixel
name, and the screen of each kind of step at each size, composed without curses."""

import unittest

from porchlight.ui import lantern, scene, wordmark
from porchlight.ui.canvas import LOWER_HALF, UPPER_HALF, Canvas, Style
from porchlight.ui.sequence import Screen, Sequence
from porchlight.ui.widgets import DOWN, ENTER, SPACE, Checklist, Choice, Confirm, Item, Summary, TextField

FEATURES = (
    Item("server", "server", "The app creates sessions on this Mac, each in its own worktree"),
    Item("ready-session", "ready-session", "A session with Claude Code's interface is always ready to write in"),
    Item("tabs", "tabs", "A terminal tab opens when a session is used and closes when it is archived"),
    Item("live-view", "live-view", "A read-only tab follows a session the server started"),
)
NEEDS = {"tabs": ("ready-session",), "live-view": ("server", "tabs")}
STEPS = (("Prerequisites", scene.DONE), ("Terminal", scene.DONE), ("Features", scene.NOW), ("Save", scene.LATER))
WIDE = (140, 40)
ROOMY = (90, 26)


def view(widget, answers=None):
    return scene.View(widget, 3, 4, STEPS, answers or {"terminal": "warp", "mode": "plan"}, "0.1.3")


def screen_text(canvas):
    return "\n".join(canvas.line(row) for row in range(canvas.height))


def row_with(canvas, text):
    return next(row for row in range(canvas.height) if text in canvas.line(row))


def features():
    return Checklist.of("Features", FEATURES, NEEDS, ("server",))


class Drawing(unittest.TestCase):
    """The canvas: text, boxes and pixels on a grid of styled cells."""

    def test_text_is_cut_at_the_edge_and_never_reaches_the_last_column(self):
        canvas = Canvas(10, 2)

        end = canvas.text(0, 6, "porchlight", Style(214))

        self.assertEqual(canvas.line(0), "      por ")
        self.assertEqual(canvas.cell(0, 6), ("p", Style(214)))
        self.assertEqual(end, 16)
        self.assertEqual(canvas.text(1, 0, "porchlight", Style(), width=4), 4)
        self.assertEqual(canvas.line(1), "porc      ")

    def test_a_box_has_rounded_corners_a_title_on_top_and_a_note_below(self):
        canvas = Canvas(30, 4)

        canvas.box(0, 0, 4, 20, Style(94), "Features", Style(220), "1 of 4", Style(245))

        self.assertEqual(canvas.line(0)[:20], "╭─ Features ───────╮")
        self.assertEqual(canvas.line(1)[:20], "│                  │")
        self.assertEqual(canvas.line(3)[:20], "╰───────── 1 of 4 ─╯")
        self.assertEqual(canvas.cell(0, 3), ("F", Style(220)))

    def test_pixels_go_two_to_a_cell_and_none_lets_the_background_through(self):
        canvas = Canvas(5, 1)

        canvas.pixels(0, 0, [[1, None, 3, None], [2, 4, None, None]])

        self.assertEqual(canvas.cell(0, 0), (UPPER_HALF, Style(1, 2)))
        self.assertEqual(canvas.cell(0, 1), (LOWER_HALF, Style(4)))
        self.assertEqual(canvas.cell(0, 2), (UPPER_HALF, Style(3)))
        self.assertEqual(canvas.cell(0, 3), (" ", Style()))


class Name(unittest.TestCase):
    """The name drawn in large pixels."""

    def test_spells_porchlight_five_rows_high_with_a_shadow(self):
        grid = wordmark.pixels("porchlight", 0)

        self.assertEqual(len(grid), 2 * wordmark.ROWS)
        self.assertEqual(len(grid[0]), wordmark.width("porchlight"))
        colors = {color for line in grid for color in line if color is not None}
        self.assertIn(wordmark.SHADOW, colors)
        self.assertGreater(len(colors), 4, "a gradient from top to bottom, and a shadow")

    def test_a_shine_crosses_it_now_and_then(self):
        frames = [wordmark.pixels("porchlight", tick) for tick in range(wordmark.SHINE_EVERY)]
        self.assertGreater(len({str(frame) for frame in frames}), 5)
        self.assertEqual(frames[0], wordmark.pixels("porchlight", wordmark.SHINE_EVERY))


class Layouts(unittest.TestCase):
    """Which layout a size gets, and what each one holds."""

    def test_a_wide_terminal_shows_the_lantern_the_steps_the_name_and_the_panels(self):
        canvas = scene.compose(view(features()), *WIDE, 0)
        text = screen_text(canvas)

        self.assertIn("porchlight", canvas.line(0))
        self.assertIn("3/4", canvas.line(0))
        self.assertIn("v0.1.3", canvas.line(0))
        self.assertIn(scene.TAGLINE, text)
        self.assertIn("STEPS", text)
        self.assertIn("◉ Features", text)
        self.assertIn("○ Save", text)
        self.assertIn("TERMINAL", text)
        self.assertIn("warp", text)
        self.assertIn("╭─ ◆ Features", text)
        lantern_cells = [canvas.cell(row, column) for row in range(2, 2 + lantern.ROWS) for column in range(2, 2 + lantern.COLUMNS)]
        self.assertGreater(sum(character in (UPPER_HALF, LOWER_HALF) for character, _ in lantern_cells), 100)

    def test_a_roomy_terminal_keeps_the_name_the_steps_and_the_panels_without_the_lantern(self):
        canvas = scene.compose(view(features()), *ROOMY, 0)
        text = screen_text(canvas)

        self.assertIn("› ◉ Features ›", text)
        self.assertIn("╭─ ◆ Features", text)
        self.assertNotIn("STEPS", text)

    def test_a_small_terminal_gets_the_plain_layout(self):
        self.assertIsNone(scene.compose(view(features()), 79, 30, 0))
        self.assertIsNone(scene.compose(view(features()), 120, 23, 0))

    def test_the_panels_start_on_the_same_row_at_every_step(self):
        rows = set()
        for widget in (features(), Choice.of("Terminal", (Item("warp", "Warp", "installed"),)), Confirm("Save", ("Terminal: warp",), "Save?")):
            canvas = scene.compose(view(widget), *WIDE, 0)
            rows.add(row_with(canvas, "╭─ ◆"))
        self.assertEqual(len(rows), 1)

    def test_fits_and_leaves_the_last_column_empty_at_every_size(self):
        widgets = (
            features(),
            Choice.of("Terminal", tuple(Item("t%d" % n, "Terminal %d" % n, "installed " * 9) for n in range(40))),
            TextField("Project name", "porch", lambda text: "", "Lowercase letters, digits and hyphens, at most 32."),
            Confirm("Save", tuple("Line %d: %s" % (n, "value " * 30) for n in range(30)), "Save this configuration?"),
            Summary("Prerequisites", ("ok       git at /usr/bin/git", "missing  tmux: brew install tmux", "", "Nothing is installed.")),
        )
        for widget in widgets:
            for width in range(80, 220, 13):
                for height in range(24, 70, 5):
                    canvas = scene.compose(view(widget), width, height, 7)
                    self.assertEqual((canvas.width, canvas.height), (width, height))
                    self.assertTrue(all(canvas.cell(row, width - 1) == (" ", Style()) for row in range(height)), (widget.title, width, height))


class Steps(unittest.TestCase):
    """What each kind of step puts in its panels."""

    def test_the_option_under_the_cursor_is_a_bar_and_its_details_follow_it(self):
        widget = features().press(DOWN).press(DOWN)  # on tabs

        canvas = scene.compose(view(widget), *WIDE, 0)

        row = row_with(canvas, "▸")
        self.assertIn("tabs", canvas.line(row))
        column = canvas.line(row).index("tabs")
        self.assertEqual(canvas.cell(row, column)[1].bg, scene.CURSOR_BG)
        text = screen_text(canvas)
        self.assertIn("╭─ ◆ tabs", text)
        self.assertIn("NEEDS", text)
        self.assertIn("ready-session", text[text.index("╭─ ◆ tabs") :])
        self.assertIn("NEEDED BY", text)
        self.assertIn("live-view", text[text.index("NEEDED BY") :])

    def test_a_checklist_marks_what_is_on_and_counts_it(self):
        widget = features().press(DOWN).press(SPACE)  # ready-session on

        text = screen_text(scene.compose(view(widget), *WIDE, 0))

        self.assertIn("✓ server", text)
        self.assertIn("✓ ready-session", text)
        self.assertIn("○ tabs", text)
        self.assertIn("2 of 4 on", text)

    def test_a_choice_marks_the_one_chosen_before(self):
        items = (Item("warp", "Warp", "installed"), Item("terminal", "Terminal", "installed"))

        text = screen_text(scene.compose(view(Choice.of("Terminal", items, "terminal")), *WIDE, 0))

        self.assertIn("◉ Terminal", text)
        self.assertIn("○ Warp", text)

    def test_a_long_list_scrolls_and_says_how_many_are_hidden(self):
        items = tuple(Item("t%d" % n, "item-%02d" % n, "") for n in range(60))
        widget = Choice.of("Long", items)
        for _ in range(30):
            widget = widget.press(DOWN)

        text = screen_text(scene.compose(view(widget), *ROOMY, 0))

        self.assertIn("item-30", text)
        self.assertNotIn("item-00", text)
        self.assertRegex(text, r"↑ \d+ more")
        self.assertRegex(text, r"↓ \d+ more")

    def test_a_text_field_shows_the_text_a_caret_and_its_note(self):
        widget = TextField("Project name", "porch", lambda text: "", "Lowercase letters, digits and hyphens, at most 32.")

        text = screen_text(scene.compose(view(widget), *WIDE, 0))

        self.assertIn("❯ porch▌", text)
        self.assertIn("Lowercase letters", text)

    def test_the_summary_shows_labels_and_values_and_asks_the_question(self):
        widget = Confirm("Save", ("Terminal: warp", "Default features: server, tabs"), "Save this configuration?")

        text = screen_text(scene.compose(view(widget), *WIDE, 0))

        self.assertRegex(text, r"TERMINAL +warp")
        self.assertRegex(text, r"DEFAULT FEATURES +server, tabs")
        self.assertIn("Save this configuration?", text)
        self.assertIn(" y  Yes", text)
        self.assertIn(" n  No", text)

    def test_prerequisites_get_a_mark_each(self):
        widget = Summary("Prerequisites", ("ok       git at /usr/bin/git", "missing  tmux: brew install tmux", "", "Nothing is installed."))

        text = screen_text(scene.compose(view(widget), *WIDE, 0))

        self.assertIn("✓ git at /usr/bin/git", text)
        self.assertIn("✗ missing  tmux: brew install tmux", text)

    def test_a_warning_stands_out_and_long_check_lines_wrap(self):
        advice = "install the Warp app for the `tabs` feature with: brew install --cask warp, or leave that feature off"
        warning = "Warning: porchlight can install what is missing with Homebrew on the next screen. " * 2
        widget = Summary("Prerequisites", ("missing  Warp: " + advice, "", warning.strip()))

        canvas = scene.compose(view(widget), *ROOMY, 0)
        text = screen_text(canvas)

        self.assertIn("leave that feature off", text)
        self.assertNotIn("…", text)
        row = row_with(canvas, "⚠ Warning:")
        column = canvas.line(row).index("⚠")
        self.assertEqual(canvas.cell(row, column)[1], scene.WARNING_TEXT)
        self.assertEqual(canvas.cell(row + 1, column + 2)[1].fg, scene.WARNING_TEXT.fg, "the paragraph keeps its color")

    def test_the_keys_become_chips_at_the_bottom(self):
        canvas = scene.compose(view(features()), *WIDE, 0)

        last = canvas.line(WIDE[1] - 1)
        self.assertIn(" up/down  move", last)
        self.assertIn(" enter  accept", last)
        column = last.index("enter")
        self.assertEqual(canvas.cell(WIDE[1] - 1, column)[1].bg, scene.ACCENT)

    def test_an_error_shows_above_the_keys(self):
        widget = Checklist.of("Features", FEATURES, NEEDS, ()).press(ENTER)

        canvas = scene.compose(view(widget), *WIDE, 0)

        self.assertIn("✗ " + widget.error, canvas.line(WIDE[1] - 2))


class Reading(unittest.TestCase):
    """The view of a sequence: its step, and the steps done, asked now and still to come."""

    def test_lists_the_steps_done_now_and_later_with_the_answers_so_far(self):
        screens = [
            Screen("terminal", "--terminal", lambda given: Choice.of("Terminal", (Item("warp", "Warp"),))),
            Screen("mode", "--mode", lambda given: Choice.of("Mode", (Item("plan", "plan"),))),
            Screen("save", "--yes", lambda given: Confirm("Save", (), "Save?")),
        ]
        sequence = Sequence.start(screens).press(ENTER)

        seen = scene.view_of(sequence, "0.1.3")

        self.assertEqual(seen.steps, (("Terminal", scene.DONE), ("Mode", scene.NOW), ("Save", scene.LATER)))
        self.assertEqual((seen.number, seen.total), (2, 3))
        self.assertEqual(seen.answers, {"terminal": "warp"})
        self.assertEqual(seen.version, "0.1.3")


if __name__ == "__main__":
    unittest.main()
