from classes.GogsDbReader import GogsDbReader


class PullRequestComment(object):
	"""
	Duck-typed from Comment class.

	Encodes references to issues or pull requests from commit messages
	"""

	def __init__(self, db_reader: GogsDbReader, row: {}):
		self.db_reader = db_reader
		self.row = row
		self.created_unix = row['merged_unix']
		self.created = GogsDbReader.unix_to_human_time(row['merged_unix'])

	def get_comment_text(self, issue_map):
		user = self.db_reader.format_user(self.row['name'], self.db_reader.find_github_user_by_name(self.row['name']))
		content = f"\nThis pull request for branch `{self.row['head_branch']}` was merged into "
		content += f"commit {self.row['merge_base']} of branch `{self.row['base_branch']}` "
		content += f"in commit {self.row['merged_commit_id']} by {user} on _{self.created}_"
		return content
