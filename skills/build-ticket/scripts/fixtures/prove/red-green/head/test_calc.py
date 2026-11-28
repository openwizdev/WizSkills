import unittest

from calc import add


class Add(unittest.TestCase):
    def test_adds(self):
        self.assertEqual(add(2, 3), 5)


if __name__ == "__main__":
    unittest.main()
