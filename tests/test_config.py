"""Tests of the configuration file: what it accepts, what it refuses and how it is written."""

import tempfile
import unittest
from pathlib import Path

from porchlight import config

ONE = """
terminal = "warp"

[projects.shop]
path = "~/Projects/shop"
permission_mode = "manual"
preset = "recommended"
"""


def problems(text):
    with unittest.TestCase().assertRaises(config.ConfigError) as caught:
        config.parse(text)
    return caught.exception.problems


class Parse(unittest.TestCase):
    def test_reads_one_project_with_a_preset(self):
        parsed = config.parse(ONE)

        self.assertEqual(parsed.terminal, "warp")
        self.assertEqual([project.name for project in parsed.projects], ["shop"])
        shop = parsed.projects[0]
        self.assertEqual(shop.path, "~/Projects/shop")
        self.assertEqual(shop.directory, Path.home() / "Projects" / "shop")
        self.assertEqual(shop.permission_mode, "manual")
        self.assertEqual(shop.features, tuple(config.FEATURES))
        self.assertEqual(shop.prefix, "shop", "the session prefix defaults to the project's name")
        self.assertIsNone(shop.base, "the base branch is read from the repository when not given")

    def test_reads_several_projects_each_with_its_own_features(self):
        parsed = config.parse(
            ONE
            + """
[projects.blog]
path = "/srv/blog"
permission_mode = "plan"
base = "origin/trunk"
session_prefix = "Blog"
features = ["keep-awake", "server"]
"""
        )

        self.assertEqual([project.name for project in parsed.projects], ["shop", "blog"])
        blog = parsed.projects[1]
        self.assertEqual(blog.features, ("server", "keep-awake"), "features keep the order of the feature table")
        self.assertEqual(blog.base, "origin/trunk")
        self.assertEqual(blog.prefix, "Blog")
        self.assertTrue(blog.has("server"))
        self.assertFalse(blog.has("tabs"))

    def test_a_file_without_projects_is_valid_and_empty(self):
        self.assertEqual(config.parse("").projects, ())

    def test_the_terminal_is_needed_only_by_the_features_that_open_tabs(self):
        without_tabs = """
[projects.shop]
path = "~/Projects/shop"
permission_mode = "manual"
features = ["server", "resume-list"]
"""
        self.assertIsNone(config.parse(without_tabs).terminal)

        with_tabs = without_tabs.replace('["server", "resume-list"]', '["ready-session", "tabs"]')
        self.assertEqual(problems(with_tabs), [("terminal", 'required by "tabs" of the project "shop"')])


class Refuse(unittest.TestCase):
    def test_reports_every_problem_by_its_key(self):
        found = problems(
            """
terminal = "teletype"
colour = "blue"

[projects.Shop_1]
path = "~/a"
permission_mode = "manual"
preset = "minimal"

[projects.blog]
permission_mode = 3
preset = "everything"
speed = "fast"
"""
        )

        self.assertEqual(
            found,
            [
                ("terminal", 'unknown terminal "teletype"; one of: warp'),
                ("colour", "unknown key"),
                ("projects.Shop_1", "a project's name has lowercase letters, digits and hyphens, at most 32"),
                ("projects.blog.path", "missing"),
                ("projects.blog.permission_mode", "must be text"),
                ("projects.blog.preset", 'unknown preset "everything"; one of: minimal, recommended'),
                ("projects.blog.speed", "unknown key"),
            ],
        )

    def test_a_project_states_its_features_once(self):
        both = ONE + 'features = ["server"]\n'
        neither = ONE.replace('preset = "recommended"\n', "")

        self.assertEqual(problems(both), [("projects.shop", "give either preset or features, not both")])
        self.assertEqual(problems(neither), [("projects.shop", "give a preset or a list of features")])

    def test_a_feature_needs_the_features_it_builds_on(self):
        found = problems(ONE.replace('preset = "recommended"', 'features = ["live-view", "reopen", "warp-speed"]'))

        self.assertEqual(
            found,
            [
                ("projects.shop.features", 'unknown feature "warp-speed"'),
                ("projects.shop.features", '"live-view" needs "server"'),
                ("projects.shop.features", '"live-view" needs "tabs"'),
                ("projects.shop.features", '"reopen" needs "ready-session"'),
            ],
        )

    def test_no_permission_mode_is_assumed(self):
        found = problems(ONE.replace('permission_mode = "manual"\n', ""))

        self.assertEqual(found, [("projects.shop.permission_mode", "missing")])

    def test_two_projects_cannot_share_a_folder_or_a_session_prefix(self):
        found = problems(
            ONE
            + """
[projects.store]
path = "~/Projects/shop/"
permission_mode = "manual"
preset = "minimal"
session_prefix = "shop"
"""
        )

        self.assertEqual(
            found,
            [
                ("projects.store.path", 'the project "shop" already uses this folder'),
                ("projects.store.session_prefix", 'the project "shop" already uses this prefix'),
            ],
        )

    def test_a_name_a_mode_or_a_prefix_that_ends_with_a_new_line_is_refused(self):
        named = '[projects."shop\\n"]\npath = "~/Projects/shop"\npermission_mode = "manual"\npreset = "minimal"\n'
        self.assertEqual([key for key, _ in problems(named)], ["projects.shop\n"])

        mode = ONE.replace('"manual"', '"manual\\n"')
        self.assertEqual(problems(mode), [("projects.shop.permission_mode", "must be one word")])

        prefix = ONE + 'session_prefix = "Shop\\n"\n'
        self.assertEqual([key for key, _ in problems(prefix)], ["projects.shop.session_prefix"])

    def test_text_that_is_not_toml_is_one_problem(self):
        found = problems("terminal = \n")

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], "")
        self.assertIn("line 1", found[0][1])

    def test_the_error_reads_as_one_line_per_problem(self):
        with self.assertRaises(config.ConfigError) as caught:
            config.parse('colour = "blue"\nshape = 1\n')

        self.assertEqual(str(caught.exception), "colour: unknown key\nshape: unknown key")


class Write(unittest.TestCase):
    def test_writes_what_it_reads(self):
        text = ONE + """
[projects.blog]
path = "/srv/my \\"blog\\""
permission_mode = "plan"
base = "origin/trunk"
session_prefix = "Blog"
features = ["server", "keep-awake"]
"""
        parsed = config.parse(text)

        self.assertEqual(config.parse(config.dump(parsed)), parsed)

    def test_writes_a_preset_by_its_name_and_other_sets_as_a_list(self):
        written = config.dump(config.parse(ONE.replace('"recommended"', '"minimal"')))

        self.assertIn('preset = "minimal"\n', written)
        self.assertNotIn("features", written)

        custom = config.dump(config.parse(ONE.replace('preset = "recommended"', 'features = ["server", "keep-awake"]')))
        self.assertIn('features = ["server", "keep-awake"]\n', custom)
        self.assertNotIn("preset", custom)

    def test_saves_and_loads_a_file_creating_its_folder(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "nested" / "config.toml"

            config.save(config.parse(ONE), path)

            self.assertEqual(config.load(path), config.parse(ONE))
            self.assertEqual(config.load(Path(scratch) / "absent.toml"), config.parse(""))


class Features(unittest.TestCase):
    def test_each_feature_names_only_known_features_and_comes_after_them(self):
        seen = []
        for name, feature in config.FEATURES.items():
            for needed in feature.needs:
                self.assertIn(needed, seen, "%s needs %s, which must come before it" % (name, needed))
            seen.append(name)

    def test_the_presets_are_complete_sets(self):
        for name, features in config.PRESETS.items():
            for feature in features:
                for needed in config.FEATURES[feature].needs:
                    self.assertIn(needed, features, "the preset %s lacks %s" % (name, needed))

    def test_tells_the_tools_a_set_of_features_needs(self):
        self.assertEqual(config.tools(("server",)), ("claude", "git"))
        self.assertEqual(config.tools(("ready-session", "tabs")), ("claude", "git", "tmux", "terminal"))
        self.assertEqual(config.tools(("keep-awake",)), ())


if __name__ == "__main__":
    unittest.main()
