from classes.GithubAppApi import GithubAppApi
from classes.GogsDbReader import GogsDbReader
from classes.gogs_model.Comment import Comment


class Issue(object):

	def __init__(self, api: GithubAppApi, db_reader: GogsDbReader, row: dict):
		self.api = api
		self.db_reader = db_reader
		self.row = row

		self.id = row["id"]
		self.index = row["index"]
		self.name = row["name"]
		self.content = row["content"]
		self.milestone_id = row["milestone_id"] if row["milestone_id"] > 0 else None
		self.is_closed = row["is_closed"]
		self.is_pull = row["is_pull"]
		self.deadline_unix = GogsDbReader.unix_to_github_time(row["deadline_unix"])
		self.created = GogsDbReader.unix_to_human_time(row["created_unix"])
		self.updated = GogsDbReader.unix_to_human_time(row["updated_unix"])
		self.creator = row["creator"]
		self.assignee = row["assignee"]

		self.comments = []

	def load_comments_for_issue(self):
		self.comments += \
			[Comment(self.db_reader, self.get_type_string(), c) for c in self.db_reader.get_comments_for_issue(self.id)]
		return self.comments

	def load_labels_for_issue(self):
		return self.db_reader.get_label_for_issue(self.id)

	def get_type_string(self):
		return "pull request" if self.is_pull else "issue"

	def get_issue_content(self, issue_map: {int: int}):
		content = f"<sub>{self.get_issue_footer()}</sub>\n\n"
		content += self.db_reader.replace_references(self.content, issue_map)
		return content

	def get_github_assignees(self):
		assignee = self.db_reader.find_github_user_by_name(self.assignee)
		return [assignee] if assignee is not None else None  # and assignee in self.api.users.values() else None

	def get_issue_footer(self):
		creator = self.db_reader.format_user(self.creator, self.db_reader.find_github_user_by_name(self.creator))
		assignee = self.db_reader.format_user(self.assignee, self.db_reader.find_github_user_by_name(self.assignee))
		footer = f"This {self.get_type_string()} was originally created by {creator} on _{self.created}_"
		if self.created != self.updated:
			footer += f" and later updated on {self.updated}"
		if self.assignee is not None:
			footer += f"\nThis {self.get_type_string()} was originally assigned to {assignee}"

		return footer
