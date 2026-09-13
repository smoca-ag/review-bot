import asyncio
import hmac
import http.server
import json
import logging
import multiprocessing
import os
import signal as signal_module
import sys
import threading
import time
from typing import NoReturn
from urllib.parse import urlsplit

from dotenv import load_dotenv
from opentelemetry import trace

# Load .env before importing review_bot: config constants
# (AGENT_REQUEST_LIMIT, CONFIDENCE_THRESHOLD, MAX_LINES, ...) and this
# module's _load_config() are read at import/startup time and would
# otherwise miss .env values. Also runs in spawned review processes.
load_dotenv()

from review_bot import review  # noqa: E402
from review_bot.backend.container_manager import prune_stale_containers  # noqa: E402

# --- Logger Setup ---
# Get a logger for this module.
# Configuration is applied in main()
logger = logging.getLogger(__name__)

# Seconds between stale-sandbox sweeps in the reaper thread.
SWEEP_INTERVAL_SECONDS = 600

# --- Configuration (from Environment Variables) ---
# Read lazily in main() to allow env changes between runs / in tests.
HOST = None
PORT = None
GITLAB_WEBHOOK_LABEL = None
GITLAB_WEBHOOK_REVIEW_ALL = None
GITLAB_WEBHOOK_TOKEN = None
GITLAB_URL = None
MAX_PARALLEL_REVIEWS = None


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, exiting fatally on bad input.

    Args:
        name: Environment variable to read.
        default: Value used when the variable is unset.

    Returns:
        The parsed integer value.
    """
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError:
        logger.critical(f"FATAL: {name} must be an integer, got {raw!r}.")
        sys.exit(1)


def _load_config():
    """Populate module-level config from environment variables."""
    global \
        HOST, \
        PORT, \
        GITLAB_WEBHOOK_LABEL, \
        GITLAB_WEBHOOK_REVIEW_ALL, \
        GITLAB_WEBHOOK_TOKEN, \
        GITLAB_URL, \
        MAX_PARALLEL_REVIEWS
    HOST = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    PORT = _env_int("WEBHOOK_PORT", 8080)
    GITLAB_WEBHOOK_LABEL = os.environ.get("GITLAB_WEBHOOK_LABEL", "ai-review-requested")
    GITLAB_WEBHOOK_REVIEW_ALL = (
        os.environ.get("GITLAB_WEBHOOK_REVIEW_ALL", "false").lower() == "true"
    )
    GITLAB_WEBHOOK_TOKEN = os.environ.get("GITLAB_WEBHOOK_TOKEN")
    GITLAB_URL = os.environ.get("GITLAB_URL")
    MAX_PARALLEL_REVIEWS = _env_int("MAX_PARALLEL_REVIEWS", 3)


# --- The function to run in a separate process ---


def _raise_on_sigterm(signum: int, frame: object) -> NoReturn:
    """Abort the review cooperatively so sandbox cleanup still runs.

    Further SIGTERMs are ignored so the cleanup in the orchestrator's finally
    block finishes; the manager escalates to SIGKILL if that is not enough.
    """
    signal_module.signal(signal_module.SIGTERM, signal_module.SIG_IGN)
    raise SystemExit(128 + signum)


def start_ai_review(mr_url):
    """
    This function runs in its own process.
    It receives the MR URL for both identification and the review spec.
    """
    try:
        signal_module.signal(signal_module.SIGTERM, _raise_on_sigterm)
        logger.info(f"Processing {mr_url}")
        asyncio.run(review(mr_url, backend="gitlab", post=True))
        logger.info(f"Finished {mr_url}")
    except SystemExit as e:
        logger.info(f"Review for {mr_url} aborted by signal (exit {e.code})")
    except Exception as e:
        logger.error(f"ERROR during AI review for {mr_url}: {e}", exc_info=True)


class ReviewManager:
    """
    Manages a queue of merge requests to review, running up to max_parallel
    reviews concurrently.  If an update arrives for an MR that is already
    running or queued, the old entry is cancelled and replaced.
    """

    def __init__(self, max_parallel: int = 3):
        self.queue: list[str] = []
        self.active: dict[str, multiprocessing.Process] = {}
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.max_parallel = max_parallel
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        self.reaper_thread = threading.Thread(target=self._reaper, daemon=True)
        self.reaper_thread.start()

    def submit(self, mr_url: str) -> None:
        # Pop the running process and re-queue the MR in one atomic step:
        # the worker registers a started process under active[mr_url] inside
        # a single lock acquisition, so keeping the dict-removal and the
        # queue-append together prevents the worker from starting a second
        # process whose registration would overwrite the first (leaving it
        # untracked and uncancellable). The kill runs afterwards, off-lock.
        with self.condition:
            process_to_kill = self.active.pop(mr_url, None)

            if mr_url in self.queue:
                self.queue.remove(mr_url)
                logger.info(f"Replaced queued review for {mr_url}")

            self.queue.append(mr_url)
            logger.info(f"Queued review for {mr_url}. Queue: {len(self.queue)}, Active: {len(self.active)}")
            self.condition.notify_all()

        if process_to_kill and process_to_kill.is_alive():
            logger.info(f"Cancelling in-progress review for {mr_url}")
            self._kill_process(process_to_kill)

    def _kill_process(self, p: multiprocessing.Process) -> None:
        if p.pid is None:
            return
        try:
            os.kill(p.pid, signal_module.SIGTERM)
            p.join(timeout=30)
        except (ProcessLookupError, OSError):
            return
        if p.is_alive():
            p.kill()

    def _worker(self) -> None:
        while True:
            with self.condition:
                while True:
                    if self.queue and self._has_capacity():
                        break
                    self.condition.wait()

                mr_url = self.queue.pop(0)

                try:
                    logger.info(f"Starting review for {mr_url}...")
                    p = multiprocessing.Process(
                        target=start_ai_review,
                        args=(mr_url,),
                        name=f"AI-Review-{_sanitize_process_name(mr_url)}",
                    )
                    p.daemon = True
                    p.start()
                    self.active[mr_url] = p
                except Exception as e:
                    # Drop the MR instead of re-queuing (a persistent failure
                    # would hot-spin); a later push/label event re-triggers it.
                    # The process is not registered in self.active, so a dead
                    # entry can never poison _has_capacity.
                    logger.exception(f"Failed to start review for {mr_url}: {e}")

    def _reaper(self) -> None:
        last_sweep = time.monotonic()
        while True:
            with self.condition:
                finished = [url for url, p in self.active.items() if not p.is_alive()]
                for url in finished:
                    del self.active[url]
                    logger.info(f"Review completed for {url}")
                if finished:
                    self.condition.notify_all()
            if time.monotonic() - last_sweep >= SWEEP_INTERVAL_SECONDS:
                last_sweep = time.monotonic()
                removed = prune_stale_containers(logger)
                if removed:
                    logger.info(f"Pruned {removed} stale sandbox container(s)")
            time.sleep(0.5)

    def _has_capacity(self) -> bool:
        if self.max_parallel <= 0:
            return True
        return len(self.active) < self.max_parallel


def _sanitize_process_name(url: str) -> str:
    return url.rsplit("/", 1)[-1]


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: str | None) -> str:
    """Return the normalized ``scheme://host[:port]`` origin of a URL.

    Scheme and host are lowercased; an explicit default port (``:80`` for
    http, ``:443`` for https) is dropped so a configured
    ``GITLAB_URL=https://gitlab.example.com:443`` still matches the
    port-less URLs GitLab puts in webhook payloads.

    Args:
        url: Absolute URL, or None/empty for a degenerate origin.

    Returns:
        Normalized origin, suitable for host-pinning checks. URLs with an
        unparsable port yield an "invalid" origin that never matches.
    """
    parsed = urlsplit(url or "")
    scheme = parsed.scheme.lower()
    try:
        port = parsed.port
    except ValueError:
        return "invalid://"
    hostname = (parsed.hostname or "").lower()
    if port is not None and port == _DEFAULT_PORTS.get(scheme):
        port = None
    return f"{scheme}://{hostname}" + (f":{port}" if port else "")


# Global manager instance, initialized in main()
review_manager = None


# --- The Webhook Server Handler ---


class GitLabWebhookHandler(http.server.BaseHTTPRequestHandler):
    def _validate_token(self):
        """Validates the 'X-Gitlab-Token' header against our secret."""
        received_token = self.headers.get("X-Gitlab-Token")

        if received_token and hmac.compare_digest(
            received_token, GITLAB_WEBHOOK_TOKEN or ""
        ):
            return True
        else:
            client_ip = self.client_address[0]
            logger.warning(
                f"Invalid token from {client_ip}. Got: '{received_token}'. Request denied."
            )
            self.send_response(401)  # Unauthorized
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Unauthorized: Invalid Secret Token")
            return False

    def do_POST(self):
        """Handles incoming POST requests from GitLab."""
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("webhook_do_POST") as span:
            client_ip = self.client_address[0]
            span.set_attribute("http.client_ip", client_ip)
            logger.info(f"Received POST request from {client_ip} to {self.path}")

            if not self._validate_token():
                span.set_status(trace.StatusCode.ERROR, "Invalid token")
                return

            try:
                content_length = int(self.headers["Content-Length"])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode("utf-8"))
            except (TypeError, ValueError, json.JSONDecodeError) as e:
                logger.error(
                    f"Error parsing JSON payload from {client_ip}: {e}", exc_info=True
                )
                self.send_response(400)  # Bad Request
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Bad Request: Could not parse JSON")
                span.set_status(trace.StatusCode.ERROR, "Invalid JSON")
                return
            except Exception as e:
                logger.error(
                    f"Unknown error reading request from {client_ip}: {e}",
                    exc_info=True,
                )
                self.send_response(500)  # Internal Server Error
                self.end_headers()
                span.set_status(trace.StatusCode.ERROR, "Internal Server Error")
                return

            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Webhook received and accepted.")

            try:
                self.handle_payload(data, span)
            except Exception as e:
                logger.error(f"Error in payload handling logic: {e}", exc_info=True)
                span.set_status(trace.StatusCode.ERROR, "Payload handling error")

    def handle_payload(self, data, span):
        """Contains the main logic for checking the MR and its labels."""

        object_kind = data.get("object_kind")
        span.set_attribute("gitlab.object_kind", str(object_kind))
        if object_kind != "merge_request":
            logger.info(f"Ignoring event: {object_kind}")
            return

        attributes = data.get("object_attributes", {})
        mr_state = attributes.get("state")
        if mr_state != "opened":
            logger.info(f"Ignoring MR in state: {mr_state}")
            return

        is_draft = attributes.get("work_in_progress", False) or attributes.get(
            "draft", False
        )
        if is_draft:
            logger.info("Ignoring Draft/WIP MR.")
            return

        mr_action = attributes.get("action")
        if mr_action not in ["open", "update", "reopen"]:
            logger.info(f"Ignoring MR action: {mr_action}")
            return

        labels = attributes.get("labels", [])
        label_names = [label["title"] for label in labels]
        mr_url = attributes.get("url", "N/A")

        # Determine the reason for the trigger
        is_new_commit = "oldrev" in attributes
        is_label_added = False

        changes = data.get("changes", {})
        if "labels" in changes:
            prev_labels = [
                label["title"] for label in changes["labels"].get("previous", [])
            ]
            curr_labels = [
                label["title"] for label in changes["labels"].get("current", [])
            ]
            if (
                GITLAB_WEBHOOK_LABEL in curr_labels
                and GITLAB_WEBHOOK_LABEL not in prev_labels
            ):
                is_label_added = True

        logger.info(
            f"Received update for {mr_url}. Action: {mr_action}, New Commit: {is_new_commit}, Label Added: {is_label_added}"
        )

        trigger_review = False

        if GITLAB_WEBHOOK_REVIEW_ALL:
            if mr_action in ["open", "reopen"] or is_new_commit:
                trigger_review = True
                logger.info(
                    f"Review all flag is set. Triggering on {mr_action}/new_commit for {mr_url}."
                )
            else:
                logger.info(
                    f"Review all flag is set, but ignoring non-code update for {mr_url}."
                )
        else:
            if GITLAB_WEBHOOK_LABEL in label_names:
                if is_label_added:
                    trigger_review = True
                    logger.info(
                        f"'{GITLAB_WEBHOOK_LABEL}' label was just added to {mr_url}."
                    )
                elif is_new_commit:
                    trigger_review = True
                    logger.info(
                        f"New commits pushed to {mr_url} with '{GITLAB_WEBHOOK_LABEL}' label."
                    )
                elif mr_action in ["open", "reopen"]:
                    trigger_review = True
                    logger.info(
                        f"{mr_url} opened/reopened with '{GITLAB_WEBHOOK_LABEL}' label."
                    )
                else:
                    logger.info(
                        f"Ignoring update to {mr_url} (label present, but no new commits)."
                    )
            else:
                logger.info(
                    f"No '{GITLAB_WEBHOOK_LABEL}' label found for {mr_url} and review all is disabled."
                )

        if trigger_review:
            if not mr_url or mr_url == "N/A":
                logger.error(
                    "Could not find MR URL for incoming event. Aborting review."
                )
                return

            # The review target must come from the pinned GITLAB_URL, never
            # from the payload: the review sends GITLAB_API_TOKEN (API
            # headers + git credentials) to whatever host the URL names.
            expected_origin = _origin(GITLAB_URL)
            actual_origin = _origin(mr_url)
            if actual_origin != expected_origin:
                logger.warning(
                    f"Ignoring event for {mr_url}: origin {actual_origin} "
                    f"does not match pinned GITLAB_URL ({expected_origin}). "
                    "Refusing to send API credentials to an unpinned host."
                )
                return

            if review_manager:
                review_manager.submit(mr_url)
            else:
                logger.error("Review manager is not initialized.")

    def do_GET(self):
        """Handle GET requests (e.g., for health checks)."""
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Webhook server is running. Use POST for GitLab events.")

    def log_message(self, format, *args):
        """Overrides the default http.server logger to use our logger."""
        pass  # Silences the default HTTP access logs


# --- Main Application Entry Point ---


def main():
    """
    Main function to set up and run the webhook server.
    Returns an exit code (0 for success, 1 for failure).
    """
    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    _load_config()

    # --- Logging Configuration ---
    # Configure logging here so it's only active when main() is called
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(processName)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )

    # --- Telemetry Setup ---
    # Initialize telemetry after multiprocessing is configured to avoid issues on macOS
    from review_bot.infra.telemetry import setup_telemetry

    setup_telemetry(logger)

    # --- CRITICAL: Token Check ---
    if not GITLAB_WEBHOOK_TOKEN:
        logger.critical("FATAL: GITLAB_WEBHOOK_TOKEN environment variable is not set.")
        logger.critical("Please set this variable and restart the server.")
        return 1  # Return 1 for failure

    # --- CRITICAL: GitLab Host Pinning Check ---
    # Without a pinned host, a leaked webhook token would let an attacker
    # aim reviews (and GITLAB_API_TOKEN) at any server via payload MR URLs.
    if not GITLAB_URL:
        logger.critical("FATAL: GITLAB_URL environment variable is not set.")
        logger.critical(
            "Set it to your GitLab base URL "
            "(e.g. https://gitlab.example.com) and restart the server."
        )
        return 1  # Return 1 for failure

    global review_manager
    stale = prune_stale_containers(logger)
    if stale:
        logger.info(f"Pruned {stale} stale sandbox container(s) from previous runs")
    review_manager = ReviewManager(max_parallel=MAX_PARALLEL_REVIEWS)

    httpd = None  # Initialize to None for the finally block
    shutdown_event = threading.Event()

    def _shutdown_handler(signum, frame):
        logger.info(f"Received signal {signum}. Shutting down...")
        shutdown_event.set()

    try:
        import signal

        signal.signal(signal.SIGINT, _shutdown_handler)
        signal.signal(signal.SIGTERM, _shutdown_handler)

        server_address = (HOST, PORT)
        # Use ThreadingHTTPServer to handle multiple concurrent requests
        httpd = http.server.ThreadingHTTPServer(server_address, GitLabWebhookHandler)
        # Without a timeout, handle_request() can block in accept() until the
        # next connection, delaying shutdown_event detection by that long.
        httpd.timeout = 1

        logger.info("Starting GitLab webhook server...")
        logger.info(f"Listening on: http://{HOST}:{PORT}")
        logger.info(f"Trigger Label: '{GITLAB_WEBHOOK_LABEL}'")
        logger.info(f"Pinned GitLab URL: {GITLAB_URL}")
        logger.info("Token: Set (hidden for security)")
        logger.info("Press Ctrl+C to shut down.")

        # Serve until shutdown signal is received
        while not shutdown_event.wait(timeout=1):
            httpd.handle_request()

    except KeyboardInterrupt:
        logger.info("Shutting down server...")
    except OSError as e:
        logger.critical(f"Server failed to start, likely port {PORT} is in use: {e}")
        return 1  # Return 1 for failure
    except Exception as e:
        logger.critical(f"An unexpected server error occurred: {e}", exc_info=True)
        return 1  # Return 1 for failure
    finally:
        if httpd:
            httpd.server_close()
            logger.info("Server shut down gracefully.")

    return 0  # Return 0 for success


# --- Standard script execution ---

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
