from classes.GogsDbReader import GogsDbReader


class Comment(object):

	def __init__(self, db_reader: GogsDbReader, issue_type: str, row: {}):
		self.db_reader = db_reader
		self.issue_type = issue_type
		self.row = row
		self.content = row['content']
		self.created_unix = row['created_unix']
		self.created = GogsDbReader.unix_to_human_time(row['created_unix'])
		self.updated = GogsDbReader.unix_to_human_time(row['updated_unix'])

		"""
			Type:
				0: General comment on issue or PR
				1: Reopen something (issue or PR?)
				2: Close something (issue or PR?)
				4: Something (issue or PR?) referenced in a commit message. 
					Only field where commit_sha is not null, so commit sha can be used
			"""

	def get_comment_text(self, issue_map: {int: int}):
		self.content = self.db_reader.replace_references(self.content, issue_map)
		user = self.db_reader.format_user(self.row['name'], self.db_reader.api.find_user_by_email(self.row['email']))

		if self.row['type'] == 1:
			return self.__get_opened_or_closed_comment_text(user, 'reopened')
		elif self.row['type'] == 2:
			return self.__get_opened_or_closed_comment_text(user, 'closed')
		elif self.row['type'] == 4:
			return self.__get_commit_reference_comment_text(user)
		else:  # This should only be type 0
			return self.__get_raw_comment_text(user)

	def __get_raw_comment_text(self, user: str):
		content = f"<sub>This comment was originally placed by {user} on _{self.created}_"
		if self.created != self.updated:
			content += f" and later updated on _{self.updated}_"
		content += f"</sub>\n\n{self.content}"
		return content

	def __get_opened_or_closed_comment_text(self, user: str, new_status: str):
		content = f"<sub>This {self.issue_type} was originally {new_status} by {user} on _{self.created}_"
		if self.created != self.updated:
			content += f" and later updated on _{self.updated}_"

		content += f"</sub>\n\n{self.content}"
		return content

	def __get_commit_reference_comment_text(self, user):
		try:
			return f"{user} referenced this {self.issue_type} from commit {self.row['commit_sha']} on _{self.created}_"
		except KeyError as e:
			print(e)
			return ""
