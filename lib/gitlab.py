import requests
import urllib
import base64
class Gitlab():
    def __init__(self, logger, gitlab_url, private_token, project_id, merge_request_iid):
        self.logger = logger
        self.gitlab_url = gitlab_url
        self.private_token = private_token
        self.project_id = project_id
        self.merge_request_iid = merge_request_iid
    def load(self):
        self.versions = self.get_versions()
        self.diff_response = self.get_merge_request_diff()
        self.mr = self.get_mr()

    def diff(self):
        return self.diff_response

    def title(self):
        return self.mr['title']


    def get_files(self, paths):
        paths_dict = {}
        for path in paths:
            if path not in paths_dict:
                paths_dict[path] = self.get_file(path)
        return paths_dict

    def get_versions(self):
        """
        Fetches the diff from a GitLab merge request

        Args:
            project_id (int): The project ID in GitLab
            merge_request_iid (int): The merge request IID
            gitlab_url (str): Base URL of your GitLab instance
            private_token (str): Your GitLab private token

        Returns:
            str: The raw diff content
        """

        # Construct the API endpoint
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/versions"

        # Set up headers with authentication
        headers = {
            "PRIVATE-TOKEN": self.private_token
        }

        try:
            # Make the API request
            response = requests.get(url, headers=headers)
            response.raise_for_status()  # Raises an HTTPError for bad responses

            # Return the diff content
            return response.json()

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching merge request diff: {e}")
            return None


    def get_merge_request_diff(self):
        # Construct the API endpoint
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/raw_diffs"

        # Set up headers with authentication
        headers = {
            "PRIVATE-TOKEN": self.private_token
        }

        try:
            # Make the API request
            response = requests.get(url, headers=headers)
            response.raise_for_status()  # Raises an HTTPError for bad responses

            # Return the diff content
            return response.text

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching merge request diff: {e}")
            return None

    def get_mr(self):
        # Construct the API endpoint
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}"
        # Set up headers with authentication
        headers = {
            "PRIVATE-TOKEN": self.private_token
        }
        try:
            # Make the API request
            response = requests.get(url, headers=headers)
            response.raise_for_status()  # Raises an HTTPError for bad responses
            # Return the diff content
            return response.json()

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching merge request diff: {e}")
            return None

    def get_file(self, file_path):
        """
        Fetches the content of a file from GitLab at a specific commit.
        """
        commit_sha = self.versions[0]["head_commit_sha"]
        # URL-encode the file path to handle special characters
        encoded_file_path = urllib.parse.quote_plus(file_path)
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/repository/files/{encoded_file_path}?ref={commit_sha}"
        headers = {"PRIVATE-TOKEN": self.private_token}

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()

            # GitLab API returns file content as a base64 encoded string
            content_base64 = response.json()['content']
            decoded_content = base64.b64decode(content_base64).decode('utf-8')
            return decoded_content

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching file content for '{file_path}': {e}")
            return None

    def post_review_as_inline_comments(self,issue):
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/discussions"
        headers = {
            "PRIVATE-TOKEN": self.private_token,
            "Content-Type": "application/json"
        }

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
    def post_review(self, issue, old_path, new_path, old_position, new_position):
        comment_text = f"""**{issue['severity']} / {issue['category']}** : {issue['summary']}

        **suggestion** : `{issue['suggestion']} `

        **rationale** : {issue['rationale']}
        """
        position = {
            "new_path": old_path,
            "old_path": new_path,
            "base_sha": self.versions[0]["base_commit_sha"],
            "start_sha": self.versions[0]["start_commit_sha"],
            "head_sha": self.versions[0]["head_commit_sha"],
            "position_type": "text",
            "new_line": new_position,
            "old_line": old_position
        }
        payload = {"body": comment_text, "position": position}
        self.post_review_as_inline_comments(payload)





