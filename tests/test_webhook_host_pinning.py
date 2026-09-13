"""Tests for webhook GitLab host pinning (GITLAB_URL).

The review target must come from the pinned GITLAB_URL, never from the
payload's MR URL: reviews send GITLAB_API_TOKEN to whatever host the URL
names.
"""

import os
import unittest
from unittest import mock

import review_bot.gitlab_webhook as webhook

LABEL = "ai-review-requested"
PINNED = "https://gitlab.example.com"


def _mr_payload(url: str) -> dict:
    """Build a label-triggered merge_request webhook payload."""
    return {
        "object_kind": "merge_request",
        "object_attributes": {
            "state": "opened",
            "action": "open",
            "work_in_progress": False,
            "url": url,
            "labels": [{"title": LABEL}],
        },
        "changes": {},
    }


class TestOrigin(unittest.TestCase):
    def test_matching_origins_case_insensitive(self):
        self.assertEqual(
            webhook._origin("HTTPS://GitLab.Example.com/g/p/-/merge_requests/1"),
            webhook._origin(PINNED),
        )

    def test_different_host_is_mismatched(self):
        self.assertNotEqual(
            webhook._origin("https://evil.example.com/g/p/-/merge_requests/1"),
            webhook._origin(PINNED),
        )

    def test_different_port_is_mismatched(self):
        self.assertNotEqual(
            webhook._origin("https://gitlab.example.com:8443/g/p/-/merge_requests/1"),
            webhook._origin(PINNED),
        )

    def test_different_scheme_is_mismatched(self):
        self.assertNotEqual(
            webhook._origin("http://gitlab.example.com/g/p/-/merge_requests/1"),
            webhook._origin(PINNED),
        )

    def test_none_yields_degenerate_origin(self):
        self.assertEqual(webhook._origin(None), "://")

    def test_explicit_default_https_port_matches_portless(self):
        """GitLab payloads omit :443; a pinned URL may include it."""
        self.assertEqual(
            webhook._origin("https://gitlab.example.com:443/g/p/-/merge_requests/1"),
            webhook._origin(PINNED),
        )

    def test_explicit_default_http_port_matches_portless(self):
        self.assertEqual(
            webhook._origin("http://gitlab.example.com:80/g/p/-/merge_requests/1"),
            webhook._origin("http://gitlab.example.com"),
        )

    def test_non_default_port_preserved(self):
        self.assertEqual(
            webhook._origin("https://gitlab.example.com:8443/g/p/-/merge_requests/1"),
            "https://gitlab.example.com:8443",
        )

    def test_unparsable_port_never_matches(self):
        self.assertNotEqual(
            webhook._origin("https://gitlab.example.com:abc/g/p/-/merge_requests/1"),
            webhook._origin(PINNED),
        )


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        self._saved = {
            name: getattr(webhook, name)
            for name in (
                "HOST",
                "PORT",
                "GITLAB_WEBHOOK_LABEL",
                "GITLAB_WEBHOOK_REVIEW_ALL",
                "GITLAB_WEBHOOK_TOKEN",
                "GITLAB_URL",
                "MAX_PARALLEL_REVIEWS",
            )
        }
        self._env = {
            k: os.environ.get(k)
            for k in os.environ
            if k.startswith(("WEBHOOK", "GITLAB_"))
        }

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(webhook, name, value)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_load_config_reads_gitlab_url(self):
        os.environ["GITLAB_URL"] = PINNED
        webhook._load_config()
        self.assertEqual(webhook.GITLAB_URL, PINNED)

    def test_load_config_gitlab_url_unset_is_none(self):
        os.environ.pop("GITLAB_URL", None)
        webhook._load_config()
        self.assertIsNone(webhook.GITLAB_URL)


class TestHandlePayloadHostPinning(unittest.TestCase):
    def setUp(self):
        self._saved = {
            name: getattr(webhook, name)
            for name in (
                "GITLAB_WEBHOOK_LABEL",
                "GITLAB_WEBHOOK_REVIEW_ALL",
                "GITLAB_URL",
                "review_manager",
            )
        }
        webhook.GITLAB_WEBHOOK_LABEL = LABEL
        webhook.GITLAB_WEBHOOK_REVIEW_ALL = False
        webhook.GITLAB_URL = PINNED
        self.manager = mock.Mock()
        webhook.review_manager = self.manager
        self.handler = webhook.GitLabWebhookHandler.__new__(
            webhook.GitLabWebhookHandler
        )
        self.span = mock.Mock()

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(webhook, name, value)

    def test_pinned_host_submits(self):
        url = f"{PINNED}/group/project/-/merge_requests/1"
        self.handler.handle_payload(_mr_payload(url), self.span)
        self.manager.submit.assert_called_once_with(url)

    def test_pinned_host_case_insensitive_submits(self):
        url = "https://GitLab.Example.COM/group/project/-/merge_requests/1"
        self.handler.handle_payload(_mr_payload(url), self.span)
        self.manager.submit.assert_called_once_with(url)

    def test_foreign_host_is_dropped(self):
        url = "https://attacker.example.com/group/project/-/merge_requests/1"
        self.handler.handle_payload(_mr_payload(url), self.span)
        self.manager.submit.assert_not_called()

    def test_port_mismatch_is_dropped(self):
        url = "https://gitlab.example.com:9999/group/project/-/merge_requests/1"
        self.handler.handle_payload(_mr_payload(url), self.span)
        self.manager.submit.assert_not_called()

    def test_pinned_with_explicit_default_port_submits(self):
        webhook.GITLAB_URL = "https://gitlab.example.com:443"
        url = f"{PINNED}/group/project/-/merge_requests/1"
        self.handler.handle_payload(_mr_payload(url), self.span)
        self.manager.submit.assert_called_once_with(url)

    def test_missing_url_is_dropped(self):
        payload = _mr_payload(f"{PINNED}/group/project/-/merge_requests/1")
        del payload["object_attributes"]["url"]
        self.handler.handle_payload(payload, self.span)
        self.manager.submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
