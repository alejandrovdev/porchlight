"""Tests of the porch lantern drawn beside the setup screens: the picture at each moment,
computed without curses."""

import unittest

from porchlight.ui import lantern


def glowing(tick):
    """How many pixels the light reaches: those of a lit level of the glow."""
    return sum(1 for row in lantern.pixels(tick) for color in row if color in lantern.GLOW[1:])


class Picture(unittest.TestCase):
    def test_is_a_grid_of_palette_colors_two_pixels_to_each_cell_it_covers(self):
        self.assertEqual((lantern.WIDTH, lantern.HEIGHT), (lantern.COLUMNS, 2 * lantern.ROWS))
        for tick in range(0, lantern.CYCLE, 7):
            grid = lantern.pixels(tick)
            self.assertEqual(len(grid), lantern.HEIGHT)
            for row in grid:
                self.assertEqual(len(row), lantern.WIDTH)
                self.assertTrue(all(0 <= color < 256 for color in row), tick)

    def test_the_same_moment_draws_the_same_picture(self):
        self.assertEqual(lantern.pixels(41), lantern.pixels(41))

    def test_moves_from_one_moment_to_the_next(self):
        frames = [lantern.pixels(tick) for tick in range(12)]
        self.assertTrue(all(one != next_one for one, next_one in zip(frames, frames[1:])))

    def test_the_old_light_nearly_goes_out_now_and_then_and_comes_back(self):
        levels = [lantern.brightness(tick) for tick in range(lantern.CYCLE)]
        dim, bright = levels.index(min(levels)), levels.index(max(levels))

        self.assertLess(min(levels), 0.3)
        self.assertGreater(sum(level >= 0.9 for level in levels), lantern.CYCLE * 0.8, "steady most of the time")
        self.assertLess(glowing(dim), glowing(bright) / 4, "the glow shrinks with the flame")
        self.assertEqual(lantern.brightness(dim + lantern.CYCLE), min(levels))

    def test_a_picture_needs_few_color_pairs(self):
        # A curses without extended colors carries at most 255 pairs; the rest of the screen
        # takes a few dozen.
        for tick in range(0, 2400, 9):
            grid = lantern.pixels(tick)
            pairs = {(grid[row][column], grid[row + 1][column]) for row in range(0, lantern.HEIGHT, 2) for column in range(lantern.WIDTH)}
            self.assertLessEqual(len(pairs), 150, tick)


if __name__ == "__main__":
    unittest.main()
