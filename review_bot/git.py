import subprocess


class Git():
    def __init__(self, logger, url):
        self.url = url
    def load(self):
        pass
    def diff(self):
        [code, diff] = subprocess.getstatusoutput(f"git diff  {self.url}")
        if code != 0:
            raise Exception(diff)
        return diff
    def title(self):
        return ""
    def get_file(self,path):
        with open(path, 'r') as file:
            return file.read()
    def get_files(self, paths):
        paths_dict = {}
        for path in paths:
            paths_dict[path] = self.get_file(path)
        return paths_dict
    def post_review(self, issue, old_path, new_path, old_position, new_position):
        pass
