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
        self.discussions = self.get_discussion()
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
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/versions"
        return self.get_json_response(url)


    def get_json_response(self, url):
        headers = {
            "PRIVATE-TOKEN": self.private_token
        }
        response = requests.get(url, headers=headers)
        if not response.ok:
            self.logger.error(f"Error fetching {url}: {response}")
            return None
        return response.json()

    def get_text_response(self, url):
        headers = {
            "PRIVATE-TOKEN": self.private_token
        }
        response = requests.get(url, headers=headers)
        if not response.ok:
            self.logger.error(f"Error fetching {url}: {response}")
            return None
        return response.text

    def get_merge_request_diff(self):
        # Construct the API endpoint
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/raw_diffs"
        return self.get_text_response(url)


    def get_mr(self):
        # Construct the API endpoint
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}"
        return self.get_json_response(url)


    def get_file(self, file_path):
        """
        Fetches the content of a file from GitLab at a specific commit.
        """
        commit_sha = self.versions[0]["head_commit_sha"]
        # URL-encode the file path to handle special characters
        encoded_file_path = urllib.parse.quote_plus(file_path)
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/repository/files/{encoded_file_path}?ref={commit_sha}"
        response = self.get_json_response(url)
        if not response:
            return None
        content_base64 = response['content']
        decoded_content = base64.b64decode(content_base64).decode('utf-8')
        return decoded_content

    def get_discussion(self):
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/discussions"
        return self.get_json_response(url)

    def post_review_as_inline_comments(self,payload):
        url = f"{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{self.merge_request_iid}/discussions"
        headers = {
            "PRIVATE-TOKEN": self.private_token,
            "Content-Type": "application/json"
        }
        response = requests.post(url, headers=headers, json=payload)
        if not response.ok:
            self.logger.error(f"Error posting inline comment to GitLab: {response}")
    def post_review(self, issue, old_path, new_path, old_position, new_position):

        if new_path == "/dev/null":
            new_path = None
        if old_path == "/dev/null":
            old_path = None
        if any(
                # For discussions that pass the filter, safely access the rest
                d['notes'][0].get('position', {}).get('new_path') == new_path and
                d['notes'][0].get('position', {}).get('new_line') == new_position
                # The filter: only process discussions where 'notes' is a non-empty list
                for d in self.discussions if d.get('notes')
        ):
            self.logger.info(f"Already a discussion on path {new_path} and position {new_position}")
            return

        comment_text = f"""**{issue['severity']} / {issue['category']}** : {issue['summary']}

**suggestion** : `{issue['suggestion']} `

**rationale** : {issue['rationale']}
        """
        position = {
            "new_path": new_path,
            "old_path": old_path,
            "base_sha": self.versions[0]["base_commit_sha"],
            "start_sha": self.versions[0]["start_commit_sha"],
            "head_sha": self.versions[0]["head_commit_sha"],
            "position_type": "text",
            "new_line": new_position,
            "old_line": old_position
        }
        payload = {"body": comment_text, "position": position}
        self.post_review_as_inline_comments(payload)





