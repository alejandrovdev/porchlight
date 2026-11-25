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

    def test_terminal_app_is_a_terminal_after_warp(self):
        self.assertEqual(config.TERMINALS, ("warp", "apple-terminal"))
        self.assertEqual(config.parse(ONE.replace('terminal = "warp"', 'terminal = "apple-terminal"')).terminal, "apple-terminal")
        self.assertEqual(config.parse(ONE).terminal, "warp", "Warp is still accepted")

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

    def test_keep_awake_is_on_battery_too_unless_it_says_plugged_in(self):
        self.assertIsNone(config.parse(ONE).keep_awake)
        self.assertEqual(config.keep_awake(config.parse(ONE)), "always")
        parsed = config.parse('keep_awake = "plugged-in"\n' + ONE)
        self.assertEqual(parsed.keep_awake, "plugged-in")
        self.assertEqual(config.keep_awake(parsed), "plugged-in")
        self.assertEqual(config.parse(config.dump(parsed)), parsed, "it is written back")

    def test_an_unknown_keep_awake_is_a_problem(self):
        self.assertIn(
            ("keep_awake", 'unknown value "sometimes"; one of: always, plugged-in'),
            problems('keep_awake = "sometimes"\n' + ONE),
        )

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
                ("terminal", 'unknown terminal "teletype"; one of: warp, apple-terminal'),
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

    def test_a_projects_path_is_absolute_or_starts_from_the_home_folder(self):
        for relative in ("Projects/shop", "./shop", "../shop", "~shop-but-no-such-person/x"):
            found = problems(ONE.replace('path = "~/Projects/shop"', 'path = "%s"' % relative))

            self.assertEqual(found, [("projects.shop.path", "must be absolute, or start with ~/")], relative)
        for absolute in ("/srv/shop", "~/Projects/shop", "~"):
            parsed = config.parse(ONE.replace('path = "~/Projects/shop"', 'path = "%s"' % absolute))

            self.assertEqual(parsed.projects[0].path, absolute)

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


DEFAULTS = """
terminal = "warp"

[defaults]
permission_mode = "plan"
preset = "minimal"
"""


class Defaults(unittest.TestCase):
    """The optional table `[defaults]`: what every new project starts from."""

    def test_reads_a_permission_mode_and_a_preset(self):
        parsed = config.parse(DEFAULTS)

        self.assertEqual(parsed.defaults, config.Defaults("plan", ("server",)))
        self.assertEqual(parsed.terminal, "warp", "the terminal stays a top-level key")

    def test_reads_a_feature_list_in_the_order_of_the_feature_table(self):
        parsed = config.parse(DEFAULTS.replace('preset = "minimal"', 'features = ["reopen", "ready-session"]'))

        self.assertEqual(parsed.defaults.features, ("ready-session", "reopen"))

    def test_a_file_without_the_table_has_no_defaults(self):
        self.assertEqual(config.parse(ONE).defaults, config.Defaults())
        self.assertEqual(config.Config().defaults, config.Defaults())
        self.assertIsNone(config.Defaults().permission_mode)
        self.assertIsNone(config.Defaults().features)

    def test_each_value_of_the_table_may_be_left_out(self):
        self.assertEqual(config.parse('[defaults]\npermission_mode = "plan"\n').defaults, config.Defaults("plan"))
        self.assertEqual(
            config.parse('[defaults]\npreset = "recommended"\n').defaults,
            config.Defaults(None, tuple(config.FEATURES)),
        )

    def test_a_feature_list_must_have_what_each_feature_builds_on(self):
        found = problems(DEFAULTS.replace('preset = "minimal"', 'features = ["tabs"]'))

        self.assertEqual(found, [("defaults.features", '"tabs" needs "ready-session"')])

    def test_features_are_given_once(self):
        found = problems(DEFAULTS + 'features = ["server"]\n')

        self.assertEqual(found, [("defaults", "give either preset or features, not both")])

    def test_reports_an_unknown_key_inside_it_by_its_key(self):
        found = problems(DEFAULTS + 'terminal = "warp"\ncolour = "blue"\n')

        self.assertEqual(found, [("defaults.terminal", "unknown key"), ("defaults.colour", "unknown key")])

    def test_reports_wrong_values_by_key(self):
        found = problems('[defaults]\npermission_mode = "two words"\npreset = "everything"\n')

        self.assertEqual(
            found,
            [
                ("defaults.permission_mode", "must be one word"),
                ("defaults.preset", 'unknown preset "everything"; one of: minimal, recommended'),
            ],
        )

    def test_must_be_a_table(self):
        self.assertEqual(problems('defaults = "plan"\n'), [("defaults", "must be a table")])

    def test_dump_writes_it_before_the_projects_and_reads_back_the_same(self):
        parsed = config.parse(DEFAULTS + ONE.replace('terminal = "warp"\n', ""))
        written = config.dump(parsed)

        self.assertLess(written.index("[defaults]"), written.index("[projects.shop]"))
        self.assertLess(written.index('terminal = "warp"'), written.index("[defaults]"))
        self.assertEqual(config.parse(written), parsed)

    def test_dump_reads_back_the_same_for_every_shape_of_the_table(self):
        shapes = (
            config.Defaults(),
            config.Defaults("plan"),
            config.Defaults(None, ("server", "keep-awake")),
            config.Defaults("acceptEdits", tuple(config.FEATURES)),
        )
        for defaults in shapes:
            configuration = config.Config(None, (), defaults)
            self.assertEqual(config.parse(config.dump(configuration)), configuration, defaults)

    def test_dump_writes_no_table_when_nothing_is_set(self):
        self.assertNotIn("[defaults]", config.dump(config.Config("warp")))


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
