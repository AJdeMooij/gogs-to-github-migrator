from classes.GithubAppApi import GithubAppApi
from classes.GogsDbReader import GogsDbReader
from classes.gogs_model.Issue import Issue
from classes.gogs_model.PullRequestComment import PullRequestComment


class PullRequest(Issue):

	def __init__(self, api: GithubAppApi, db_reader: GogsDbReader, row: dict):
		super(PullRequest, self).__init__(api, db_reader, row)
		self.pull_requests = self.db_reader.get_pull_request_for_issue(self.id)
		self.head = self.pull_requests[0]['head_branch']
		self.base = self.pull_requests[0]['base_branch']

	def load_comments_for_issue(self):
		super(PullRequest, self).load_comments_for_issue()
		for pull_request in self.pull_requests:
			if pull_request["merged_unix"] is not None and pull_request['merged_unix']:
				self.comments.append(PullRequestComment(self.db_reader, pull_request))
		self.comments = sorted(self.comments, key=lambda c: c.created_unix)
		return self.comments

	def get_issue_content(self, issue_map: {int: int}):
		content = f"<sub>This issue was originally a pull request from branch `{self.head}` to branch `{self.base}`\n"
		content += self.get_issue_footer() + "</sub>\n\n"
		content += self.db_reader.replace_references(self.content, issue_map)
		return content

	def get_pull_request_content(self, issue_map):
		content = self.get_issue_footer() + "</sub>\n\n"
		content += self.db_reader.replace_references(self.content, issue_map)
		return content
