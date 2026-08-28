# pylint: disable=missing-module-docstring,missing-class-docstring
import os
import unittest


class TestUI(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_no_external_urls(self):
        for root, _, files in os.walk(self.base_dir):
            for file in files:
                if file.endswith(".html") or file.endswith(".js") or file.endswith(".css"):
                    filepath = os.path.join(root, file)
                    if "vendor" in filepath or f"{os.sep}docs{os.sep}" in filepath:
                        continue
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                        self.assertNotIn("https://unpkg.com", content, f"Found unpkg CDN in {filepath}")
                        self.assertNotIn("https://cdn.", content, f"Found CDN in {filepath}")

    def test_no_unsafe_js(self):
        for root, _, files in os.walk(self.base_dir):
            for file in files:
                if file.endswith(".js") and "vendor" not in root and f"{os.sep}docs{os.sep}" not in root:
                    filepath = os.path.join(root, file)
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                        self.assertNotIn("alert(", content, f"Found alert in {filepath}")
                        self.assertNotIn("prompt(", content, f"Found prompt in {filepath}")


if __name__ == "__main__":
    unittest.main()
