import http.server
import json
import multiprocessing
import sys
import logging
import os
from review_bot import review, BackendType

# --- Logger Setup ---
# Get a logger for this module.
# Configuration is applied in main()
logger = logging.getLogger(__name__)

# --- Configuration (from Environment Variables) ---
HOST = os.environ.get('WEBHOOK_HOST', '0.0.0.0')
PORT = int(os.environ.get('WEBHOOK_PORT', '8080'))
GITLAB_WEBHOOK_LABEL = os.environ.get('GITLAB_WEBHOOK_LABEL', 'ai-review-requested')
GITLAB_WEBHOOK_TOKEN = os.environ.get('GITLAB_WEBHOOK_TOKEN')


# --- The function to run in a separate process ---

def start_ai_review(mr_id, mr_url):
    """
    This function is your target. It runs in its own process.
    It now receives the MR ID and URL directly.
    """
    try:
        logger.info(f"Processing URL: {mr_url}")
        # Simulate a long-running task (e.g., API calls, code analysis)
        review(mr_url, BackendType.GITLAB, post=True)
        logger.info(f"Finished URL: {mr_url}")
    except Exception as e:
        logger.error(f"ERROR during AI review for MR !{mr_url}: {e}", exc_info=True)


# --- The Webhook Server Handler ---

class GitLabWebhookHandler(http.server.BaseHTTPRequestHandler):

    def _validate_token(self):
        """Validates the 'X-Gitlab-Token' header against our secret."""
        received_token = self.headers.get('X-Gitlab-Token')

        if received_token == GITLAB_WEBHOOK_TOKEN:
            return True
        else:
            client_ip = self.client_address[0]
            logger.warning(f"Invalid token from {client_ip}. Got: '{received_token}'. Request denied.")
            self.send_response(401)  # Unauthorized
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Unauthorized: Invalid Secret Token")
            return False

    def do_POST(self):
        """Handles incoming POST requests from GitLab."""
        client_ip = self.client_address[0]
        logger.info(f"Received POST request from {client_ip} to {self.path}")

        if not self._validate_token():
            return

        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
        except (TypeError, ValueError, json.JSONDecodeError) as e:
            logger.error(f"Error parsing JSON payload from {client_ip}: {e}", exc_info=True)
            self.send_response(400)  # Bad Request
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Bad Request: Could not parse JSON")
            return
        except Exception as e:
            logger.error(f"Unknown error reading request from {client_ip}: {e}", exc_info=True)
            self.send_response(500)  # Internal Server Error
            self.end_headers()
            return

        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Webhook received and accepted.")

        try:
            self.handle_payload(data)
        except Exception as e:
            logger.error(f"Error in payload handling logic: {e}", exc_info=True)

    def handle_payload(self, data):
        """Contains the main logic for checking the MR and its labels."""

        object_kind = data.get('object_kind')
        if object_kind != 'merge_request':
            logger.info(f"Ignoring event: {object_kind}")
            return

        attributes = data.get('object_attributes', {})
        mr_action = attributes.get('action')
        if mr_action not in ['open', 'update', 'reopen']:
            logger.info(f"Ignoring MR action: {mr_action}")
            return

        labels = attributes.get('labels', [])
        label_names = [label['title'] for label in labels]
        mr_id = attributes.get('iid', 'N/A')
        mr_url = attributes.get('url', 'N/A')

        logger.info(f"Received update for MR !{mr_id}. Labels: {label_names}")

        if GITLAB_WEBHOOK_LABEL in label_names:
            logger.info(f"'{GITLAB_WEBHOOK_LABEL}' label found for MR !{mr_id}.")

            if mr_url == 'N/A' or mr_id == 'N/A':
                logger.error(f"Could not find MR ID or URL for incoming event. Aborting review.")
                return

            logger.info(f"Spawning new process for AI review...")
            p = multiprocessing.Process(
                target=start_ai_review,
                args=(mr_id, mr_url,),
                name=f"AI-Review-MR-{mr_id}"
            )
            p.daemon = True
            p.start()

        else:
            logger.info(f"No '{GITLAB_WEBHOOK_LABEL}' label found for MR !{mr_id}.")

    def do_GET(self):
        """Handle GET requests (e.g., for health checks)."""
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
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

    # --- Logging Configuration ---
    # Configure logging here so it's only active when main() is called
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(processName)s - %(levelname)s - %(message)s',
        stream=sys.stdout
    )


    # --- CRITICAL: Token Check ---
    if not GITLAB_WEBHOOK_TOKEN:
        logger.critical("FATAL: GITLAB_WEBHOOK_TOKEN environment variable is not set.")
        logger.critical("Please set this variable and restart the server.")
        return 1  # Return 1 for failure


    httpd = None  # Initialize to None for the finally block
    try:
        server_address = (HOST, PORT)
        httpd = http.server.HTTPServer(server_address, GitLabWebhookHandler)

        logger.info(f"Starting GitLab webhook server...")
        logger.info(f"Listening on: http://{HOST}:{PORT}")
        logger.info(f"Trigger Label: '{GITLAB_WEBHOOK_LABEL}'")
        logger.info("Token: Set (hidden for security)")
        logger.info("Press Ctrl+C to shut down.")

        httpd.serve_forever()

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