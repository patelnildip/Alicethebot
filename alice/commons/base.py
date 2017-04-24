from alice.config.config_provider import ConfigProvider
from alice.helper.common_utils import CommonUtils
from alice.helper.log_utils import logger
# from alice.helper.log_utils import Logger

class Base(object):
    API_START_PR = "https://api.github.com/repos/moengage/MoEngage/pulls/"
    API_START_ISSUES = "https://api.github.com/repos/moengage/MoEngage/issues/"


class PushPayloadParser(Base):

    def __init__(self, request, payload):
        self.request = request
        self.payload = payload
        self.pr = payload["pull_request"]
        logger.debug("Repo="+self.repo)
        self.config = ConfigProvider(self.repo)

    @property
    def repo(self):
        return self.payload["repository"]["name"]#self.data["head"]["repo"]["name"]

    @property
    def opened_by(self):
        return self.pr["user"]["login"]

    @property
    def merged_by(self):
        return self.pr["merged_by"]["login"]

    @property
    def link_preety(self):
        return self.pr["html_url"]

    @property
    def link(self):
        return self.pr["url"]

    @property
    def is_merged(self):
        return self.pr["merged"]

    @property
    def action(self):
        return self.payload["action"]

    @property
    def is_opened(self):
        return self.action == "opened"

    @property
    def is_reopened(self):
        return self.action == "reopened"

    @property
    def base_branch(self):
        return self.pr["base"]["ref"]

    @property
    def head_branch(self):
        return self.pr["head"]["ref"]
    
    @property
    def comments_section(self):
        return self.pr["_links"]["comments"]["href"]

    @property
    def is_sensitive_branch(self):
        return self.base_branch in self.config.sensitiveBranches()

    @property
    def merged_by_slack(self):
        return CommonUtils.getSlackNicksFromGitNicks(self.merged_by)

    @property
    def opened_by_slack(self):
        return CommonUtils.getSlackNicksFromGitNicks(self.opened_by)

    @property
    def title(self):
        return self.pr["title"]

    @property
    def description(self):
        return self.pr["description"]
