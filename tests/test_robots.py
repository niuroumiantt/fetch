import unittest

from fetch.core.robots import Robots


SAMPLE = """
User-agent: *
Disallow: /private
Allow: /private/ok
Crawl-delay: 1.5
Sitemap: https://example.com/sitemap.xml

User-agent: inresearch-fetch
Disallow: /blocked
Crawl-delay: 2
"""


class RobotsTests(unittest.TestCase):
    def test_longest_match_and_delay(self):
        policy = Robots(SAMPLE, "inresearch-fetch/1")
        self.assertFalse(policy.allowed("https://example.com/blocked"))
        self.assertTrue(policy.allowed("https://example.com/public"))
        self.assertEqual(policy.delay, 2.0)
        self.assertEqual(policy.sitemaps, ["https://example.com/sitemap.xml"])

    def test_empty_disallow_allows(self):
        policy = Robots("User-agent: *\nDisallow:\n", "bot")
        self.assertTrue(policy.allowed("https://example.com/anything"))


if __name__ == "__main__":
    unittest.main()
