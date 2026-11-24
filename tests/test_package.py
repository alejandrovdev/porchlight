import unittest

import porchlight


class Package(unittest.TestCase):
    def test_states_its_version(self):
        self.assertRegex(porchlight.__version__, r"^\d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
