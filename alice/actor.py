from flask import Flask, request, jsonify, abort
# from logging.handlers import RotatingFileHandler
from alice.helper.constants  import *
import requests
#from flask import app as application
import simplejson as json
from alice.config.message_template import *
from alice.commons.base import Base, PushPayloadParser
from alice.helper.github_helper import GithubHelper, PRFilesNotFoundException
from alice.helper.slack_helper import SlackHelper
from alice.helper.file_utlis import write_to_file_from_top, clear_file
from enum import Enum
import logging
from alice.helper.log_utils import logger
from logging import Formatter, FileHandler

app = Flask(__name__)


class Actor(Base):
    
    def __init__(self, pr_payload):
        self.pr = pr_payload
        self.github = GithubHelper(self.pr.config.organisation, self.pr.repo, self.pr.config.githubToken, self.pr.link)
        self.slack = SlackHelper(self.pr.config.slackToken)
        self.change_requires_product_plus1 = False
        self.is_product_plus1 = False
        self.sensitive_file_touched = {}
        if self.pr.is_merged:
            self.parse_files_and_set_flags()

        self.base_branch = self.pr.base_branch
        self.head_branch = self.pr.head_branch


    def was_eligible_to_merge(self):
        if self.pr.is_merged: #and self.head_branch in PushPayload.PROTECTED_BRANCH_LIST:  TO ENABLE
            is_bad_pr = self.is_reviewed(self.pr.opened_by_slack)
            logger.info("Bad PR={msg} repo:{repo}".format(repo=self.pr.repo, msg=is_bad_pr))
            return {"msg":"Bad PR={msg} repo:{repo}".format(repo=self.pr.repo, msg=is_bad_pr)}
        return {"msg":"Skipped review because its not PR merge event"}


    def add_comment(self):
        if self.pr.is_opened:
            if not self.pr.config.is_debug:
                if self.pr.base_branch == self.pr.config.mainBranch:
                    guideline_comment = special_comment
                else:
                    guideline_comment = general_comment
                self.github.comment_pr(self.pr.comments_section, guideline_comment)
                logger.info("**** Added Comment of dev guidelines ***")
                return {"msg": "Added Comment of dev guidelines"}
            return {"msg": "Skipped commenting because DEBUG is on "}
        return {"msg": "Skipped commenting because its not PR opened"}


    def slack_merged_to_channel(self):
        if self.pr.is_merged and self.pr.is_sensitive_branch:
            #print "**** Repo=" + repo + ", new merge came to " + base_branch + " set trace to " + code_merge_channel + " channel"
            msg = MSG_CODE_CHANNEL.format(title=title_pr, desc=body_pr, pr=self.pr.link,
                                          head_branch=self.pr.head_branch, base_branch=self.pr.base_branch,
                                          pr_by=self.pr.opened_by_slack, merge_by=self.pr.merged_by_slack)
            return msg
            #slack_helper.postToSlack(code_merge_channel, msg, data={"username": bot_name})  # code-merged

    def slack_direct_on_specific_action(self):
        #if self.pr.is_opened:
        desired_action = self.pr.config.actionToBeNotifiedFor
        if self.pr.action == desired_action:
            if self.pr.base_branch == self.pr.config.mainBranch:
                msg = MSG_OPENED_TO_MAIN_BRANCH.format(repo=self.pr.repo, pr_by=self.pr.opened_by_slack,
                                                       main_branch=self.pr.config.mainBranch,
                                                       title_pr=self.pr.title, pr_link=self.pr.link_preety)
                for person in self.pr.config.techLeadsToBeNotified:
                    self.slack.postToSlack(person, msg + MSG_RELEASE_PREPARATION)
                logger.info("Notified to %s on action %s" % (self.pr.config.techLeadsToBeNotified, self.pr.action))
                return {"msg": "Notified to %s on action %s" % (self.pr.config.techLeadsToBeNotified, self.pr.action)}
            else:
                msg = MSG_OPENED_TO_PREVENTED_BRANCH.format(repo=self.pr.repo, pr_by=self.pr.opened_by_slack,
                                                            base_branch=self.pr.base_branch,
                                                            title_pr=self.pr.title, pr_link=self.pr.link_preety)
                self.slack.postToSlack('@' + self.pr.config.personToBeNotified, msg)
                logger.info("Notified to %s on action %s" % (self.pr.config.personToBeNotified, self.pr.action))
                return {"msg": "Notified to %s on action %s" %(self.pr.config.personToBeNotified,self.pr.action)}
        return {"msg": "Skipped notify because its not desired event %s" % self.pr.action}




    def slack_personally_for_release_guidelines(self):
        if self.pr.is_merged:
            if self.base_branch in self.pr.config.sensitiveBranches:
                msg = MSG_GUIDELINE_ON_MERGE.format(person=self.pr.merged_by_slack, pr_link= self.pr.link_preety,
                                                    base_branch=self.pr.base_branch)
                slack_helper.postToSlack('@' + self.pr.opened_by_slack, msg)
                logger.info("slacked personally to %s" %self.pr.opened_by_slack)
                return {"msg":"slacked personally to %s" %self.pr.opened_by_slack}
            return {"msg": "skipped slack personally because not sensitive branch"}
        return {"msg": "skipped slack personally because its not merge event" % self.pr.opened_by_slack}


    def close_dangerous_pr(self):
        if self.pr.is_opened or self.pr.is_reopened:
            master_branch = self.pr.config.mainBranch
            qa_branch =  self.pr.config.testBranch
            if self.base_branch == master_branch and self.head_branch != qa_branch:
                msg = MSG_AUTO_CLOSE.format(tested_branch=qa_branch, main_branch=master_branch)
                self.github.modify_pr(msg, "closed")
                self.slack.postToSlack(self.pr.config.alertChannelName, "@" + self.pr.opened_by_slack + ": " + msg)
                logger.info("closed dangerous PR %s"%self.pr.link_preety)
                return {"msg":"closed dangerous PR %s"%self.pr.link_preety}
            return {"msg": "skipped closing PR because not raised to mainBranch %s" % self.pr.link_pretty}
        return {"msg": "skipped closing PR because not a opened PR"}


    def notify_on_sensitive_files_touched(self):
        if self.pr.is_merged:
            if sensitive_file_touched.get("is_found"):
                self.slack.postToSlack(self.pr.config.alertChannelName, self.pr.config.devOpsTeam + " " + sensitive_file_touched["file_name"]
                                       + " is modified in PR=" + pr_link + " by @" + pr_by_slack,
                                       {"parse":False})
                logger.info("informed %s because sensitive files are touched" % self.pr.config.devOpsTeam)
                return {"msg":"informed %s because sensitive files are touched" % self.pr.config.devOpsTeam}
            return {"msg": "Skipped sensitive files alerts because no sensitive file being touched"}
        return {"msg": "Skipped sensitive files alerts because its not PR merge event" % self.pr.config.devOpsTeam}


    def personal_msgs_to_leads_on_release_freeze(self):
        if self.pr.is_opened:
            pass

    def notify_QA_signOff(self):
        msg = "<@{0}>  QA passed :+1: `master` is updated <{1}|Details here>  Awaiting your go ahead. \n cc: {2} {3} ".\
            format(self.pr.config.personToBeNotified, data["pull_request"][
                "html_url"], self.pr.config.devOpsTeam, self.pr.config.techLeadsToBeNotified)

        self.slack.postToSlack(self.pr.config.alertChannelName, msg,
                               data=self.slack.getBot(channel_name, merged_by_slack))
        """ for bot """
        write_to_file_from_top(release_freeze_details_path, ":clubs:" +
                               str(datetime.now(pytz.timezone('Asia/Calcutta')).strftime(
                                   '%B %d,%Y at %I.%M %p')) + " with <" + pr_link + "|master> code")  # on:" + str(datetime.datetime.now().strftime('%B %d, %Y @ %I.%M%p'))
        clear_file(code_freeze_details_path)


    def notify_to_add_release_notes_for_next_release(self):
        pass

    def announce_code_freeze(self):
        pass

    def ci_lint_checker(self):
        pass

    def ci_unit_tests(self):
        pass

    def is_reviewed(self, created_by_slack_nick):
        reviews = self.github.get_reviews()
        if 200 != reviews.status_code:
            raise Exception(reviews.content)

        logger.debug("##### reviews= %s #####" + reviews.content)
        bad_pr = True
        logger.info("***** Reading Reviews *****")
        for item in json.loads(reviews.content):
            if "APPROVED" == item["state"]:
                review_comment = item["body"]
                logger.debug("review body= %s" + review_comment)
                thumbsUpIcon = THUMBS_UP_ICON in json.dumps(review_comment)
                logger.debug("unicode thumbsUp icon present=%s" % (thumbsUpIcon))

                if self.pr.opened_by in self.pr.config.superMembers:  # FEW FOLKS TO ALLOW TO HAVE SUPER POWER
                    logger.debug("PR is opened by %s who is the super user of repo %s, so NO alert'"
                                 % (self.pr.opened_by_slack, self.pr.repo))
                    bad_pr = False
                    break
                print "***** review_comment", review_comment
                if item["user"]["login"] != self.pr.opened_by and (review_comment.find("+1") != -1 or thumbsUpIcon):
                    logger.debug("+1 found from reviewer=%s marking No Alert" + item["user"]["login"])
                    bad_pr = False
                    break

        bad_name_str = MSG_BAD_START + "@" + created_by_slack_nick
        if bad_pr:
            msg = MSG_NO_TECH_REVIEW.format(name=bad_name_str, pr=self.pr.link_preety, branch=self.pr.base_branch,
                                            team=self.pr.config.alertChannelName)
            logger.debug(msg)
            self.slack.postToSlack(self.pr.config.alertChannelName, msg)
        return bad_pr

    def parse_files_and_set_flags(self):
        files_contents = self.github.get_files()
        self.change_requires_product_plus1 = False
        self.is_product_plus1 = False
        logger.info("**** Reading files ****")
        for item in files_contents:
            file_path = item["filename"]
            if any(x in str(file_path) for x in self.pr.config.sensitiveFiles):
                self.sensitive_file_touched["is_found"] = True
                self.sensitive_file_touched["file_name"] = str(file_path)
            if item["filename"].find(self.pr.config.productPlusRequiredDirPattern) != -1:
                logger.info("product change found marking ui_change to True")
                self.change_requires_product_plus1 = True
                # break


@app.route("/merge", methods=['POST'])
def merge():
    if request.method != 'POST':
        abort(501)
    payload = request.get_data()
    data = json.loads(unicode(payload, errors='replace'), strict=False)
    pull_request = Actor(PushPayloadParser(request, payload=data))

    steps = pull_request.pr.config.checks
    merge_correctness = {}
    #import pdb; pdb.set_trace()
    if len(steps) == 0:
            pull_request.close_dangerous_pr()
            pull_request.add_comment()
            pull_request.slack_direct_on_specific_action()
            pull_request.personal_msgs_to_leads_on_release_freeze()

            merge_correctness = pull_request.was_eligible_to_merge()
            pull_request.slack_merged_to_channel()
            pull_request.slack_personally_for_release_guidelines()
            pull_request.notify_on_sensitive_files_touched()
    else:
        for item in steps:
            if item == Action.TECH_REVIEW.value:
                merge_correctness = pull_request.was_eligible_to_merge()
            elif item == Action.PRODUCT_REVIEW.value:
                pass
            elif item == Action.GUIDELINES.value:
                pull_request.add_comment()
            elif item == Action.DIRECT_ON_OPEN.value:
                pull_request.slack_direct_on_specific_action()


    return jsonify(merge_correctness)


@app.route("/", methods=['GET', 'POST'])
def hello():
    return "Welcome to the world of Alice "


@app.before_first_request
def setup_logging():
    if not app.debug:
        # In production mode, add log handler to sys.stderr.
        file_handler = FileHandler('output.log')
        handler = logging.StreamHandler()
        file_handler.setLevel(logging.DEBUG)
        handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(Formatter(
            '%(asctime)s %(levelname)s: %(message)s '
            '[in %(pathname)s:%(lineno)d]'
        ))
        handler.setFormatter(Formatter(
            '%(asctime)s %(levelname)s: %(message)s '
            '[in %(pathname)s:%(lineno)d]'
        ))
        app.logger.addHandler(handler)
        app.logger.addHandler(file_handler)

        app.logger.info('****** flask logger ...')
        logger.debug('************ log from setup_config *********')


# if __name__ == "__main__":
#     #application.run()
#     handler = RotatingFileHandler('app.log', maxBytes=100000, backupCount=3)
#     logger = logging.getLogger('tdm')
#     logger.setLevel(logging.DEBUG)
#     logger.addHandler(handler)
#
#     application.run(debug=True,
#         host="0.0.0.0",
#         port=int("5006")
#     )


class Action(Enum):

    TECH_REVIEW = "tech_review"
    PRODUCT_REVIEW = "product_review"
    GUIDELINES = "comment_guidelines"
    DIRECT_ON_OPEN = "slack_direct_on_pr_open"




# @application.after_request
# def after_request(response):
#     timestamp = strftime('[%Y-%b-%d %H:%M]')
#     application.logger.error('%s %s %s %s %s %s', timestamp, request.remote_addr, request.method, request.scheme, request.full_path, response.status)
#     return response

# @application.errorhandler(Exception)
# def exceptions(e):
#     tb = traceback.format_exc()
#     timestamp = strftime('[%Y-%b-%d %H:%M]')
#     application.logger.error('%s %s %s %s %s 5xx INTERNAL SERVER ERROR\n%s', timestamp, request.remote_addr, request.method, request.scheme, request.full_path, tb)
#     return e.status_code
