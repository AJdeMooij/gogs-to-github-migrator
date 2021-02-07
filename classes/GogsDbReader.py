import os
import re
import sys
from datetime import datetime, timezone
import logging

import click
import mysql.connector
from mysql.connector import Error, ProgrammingError

from classes.Configuration import Configuration
from classes.GithubAppApi import GithubAppApi


class GogsDbReader(object):
	logger = logging.getLogger(__name__)

	def __init__(self, api: GithubAppApi, configuration: Configuration):
		self.configuration = configuration
		self.api = api

		if self.configuration.get_or_default(False, "gogs", "no_password"):
			self.logger.debug("Trying to authenticate to Gogs database without password")
			password = None
		else:
			password = click.prompt(f"Please enter the MySQL password for {self.configuration.get('gogs', 'host')}")

		try:
			self.conn = mysql.connector.connect(
				host=self.configuration.get("gogs", "host"),
				db=self.configuration.get("gogs", "database"),
				user=self.configuration.get("gogs", "username"),
				passwd=password
			)
			self.logger.debug("Authenticated to Gogs database")
		except ProgrammingError as e:
			print(e.msg, file=sys.stderr)
			self.logger.exception("Could not authenticate with Gogs database. Stopping migration")
			exit(1)

		repo = self.configuration.get("gogs", "repository")
		self.repo = repo if type(repo) is int else self.get_repository_id(repo)
		self.users = self.__load_users()
		self.code_language = self.configuration.get_or_default(None, "migration", "default_code_language")
		self.allow_mentions = self.configuration.get_or_default(False, "migration", "mentions")
		self.__load_user_from_file()

	def __load_users(self):
		users = dict()
		cursor = self._select('SELECT distinct name, lower_name, email FROM `user`')
		for user in cursor:
			users[user['name']] = user['email']

		return users

	def __load_user_from_file(self):
		for user in open('github-accounts', 'r'):
			if user.startswith("#"):
				continue
			split = user.replace(os.linesep, '').split(" ")
			if not len(split) == 2:
				self.logger.error(
					f"Could not parse line `{user}` in `github-accounts`. "
					f"Format is `gogs-username <space> github-username`. Skipping.")

			user_email = None
			if split[0].lower() in self.users:
				user_email = self.users[split[0].lower()]

			if user_email is None:
				self.logger.warning(
					f"User {split[0]} could not be mapped to Github user {split[1]} as this user was not found in Gogs. "
					f"Only using for mentions")
				self.api.users[split[0]] = split[1]
			elif user_email in self.api.users:
				self.logger.warning(
					f"User `{split[0]}` was already found on Github through "
					f"email {user_email}, but trying to add for username {split[0]}")
			else:
				self.logger.debug(
					f"Storing mapping between Gogs user {split[0]} and Github user {split[1]} "
					f"with e-mail address {user_email}")
				self.api.users[user_email] = split[1]

	def get_labels(self):
		query = f'SELECT id, name, color FROM `label` WHERE repo_id={self.repo};'
		return self._select(query)

	def get_milestones(self):
		query = f'''
			SELECT id,name, content, is_closed, deadline_unix as deadline, closed_date_unix as closed_date 
			FROM `milestone` 
			WHERE milestone.repo_id={self.repo} 
			ORDER BY id asc
			'''
		result = self._select(query)
		for milestone in result:
			milestone["is_closed"] = bool(milestone["is_closed"])
			milestone["deadline"] = self.unix_to_github_time(milestone["deadline"])
			milestone["closed_date"] = self.unix_to_github_time(milestone["closed_date"])
			milestone["state"] = 'closed' if milestone['is_closed'] else 'open'

		return result

	def get_issues(self):
		query = f'''SELECT issue.id, issue.index, issue.name, issue.content, issue.milestone_id, issue.is_closed,
		issue.is_pull, issue.deadline_unix, issue.created_unix, issue.updated_unix,
			creator.name as creator, assigned.name as assignee
			FROM issue
			LEFT JOIN user creator on issue.poster_id=creator.id
			LEFT JOIN user assigned on issue.assignee_id=assigned.id
			WHERE issue.repo_id = {self.repo}
			ORDER BY issue.created_unix asc
			'''
		return self._select(query)

	def get_comments_for_issue(self, issue_id):
		query = f"""
		SELECT comment.type, comment.content, comment.commit_sha, comment.created_unix, comment.updated_unix, 
		user.name, user.email
		FROM comment 
		LEFT JOIN user on comment.poster_id=user.id WHERE issue_id = {issue_id} 
		ORDER BY comment.created_unix asc
		"""
		return self._select(query)

	def get_label_for_issue(self, issue_id):
		query = f'''
		SELECT distinct label.id, label.name, label.color 
		FROM `issue_label` 
		LEFT JOIN label on label.id = issue_label.label_id 
		WHERE issue_label.issue_id={issue_id}
		'''
		return self._select(query)

	def get_pull_request_for_issue(self, issue_id):
		query = f'''
		SELECT 
			pull_request.type, pull_request.head_branch, pull_request.base_branch, pull_request.has_merged, 
			pull_request.merge_base, pull_request.merged_commit_id, pull_request.merged_unix, user.name 
		FROM pull_request 
		LEFT JOIN user ON pull_request.merger_id=user.id 
		WHERE pull_request.issue_id={issue_id} 
		'''
		return self._select(query)

	def get_users_for_repository(self):
		query = f'''
		SELECT DISTINCT user.id, user.name, user.full_name, user.email 
		FROM `user` 
		RIGHT JOIN `issue_user` 
		on user.id = issue_user.uid 
		WHERE issue_user.repo_id={self.repo}
		'''

		return self._select(query)

	def get_repository_id(self, repo: str) -> int:
		query = f"SELECT `id` FROM `repository` WHERE `lower_name` = '{repo}'"
		result = self._select(query)
		return int(result[0]["id"])

	def _select(self, query) -> list:
		cursor = self.conn.cursor(dictionary=True)
		try:
			cursor.execute(query)
			return cursor.fetchall()
		except Error as e:
			print(f"An error {e} occurred when executing the query {query}")

	@staticmethod
	def unix_to_github_time(unix_time: str or int):
		return GogsDbReader.__unix_to_timestamp(unix_time, '%Y-%m-%dT%H:%M:%SZ')

	@staticmethod
	def unix_to_human_time(unix_time: str or int):
		return GogsDbReader.__unix_to_timestamp(unix_time, "%A %d %B %Y at %H:%M:%S")

	@staticmethod
	def __unix_to_timestamp(unix_time: str or int, format_string: str) -> str or None:
		unix_time_int = int(unix_time)
		if unix_time_int is None:
			return None
		elif 0 < unix_time_int < 253402210800:
			local_tzinfo = datetime.now(timezone.utc).astimezone().tzinfo
			return datetime.fromtimestamp(unix_time_int).replace(tzinfo=local_tzinfo).strftime(format_string)
		else:
			# Weird feature that deadline seems to be set to 253402210800 (time stamp) if not present?
			return None

	def find_github_user_by_name(self, user_name):
		if user_name is not None and user_name.lower() in self.users:
			return self.api.find_user_by_email(self.users[user_name.lower()])

	def replace_references(self, content: str, issue_map: {int: int}):
		for match in re.findall(r'#(\d+)', content):
			if int(match) in issue_map:
				updated_reference = issue_map[int(match)]
				if updated_reference is None:
					updated_reference = "<not_migrated>"
				content = content.replace(f'#{match}', f'#{updated_reference}')

		for match in re.findall(r'@([\w.\d]+)', content):
			new_user = self.find_github_user_by_name(match.lower())
			if new_user is not None:
				content = content.replace(f'@{match}', self.format_user(match, new_user))
				self.logger.debug(f"Replaced @mention of {match} to {new_user}")
			elif match.lower() in self.api.users:
				new_user = self.api.users[match.lower()]
				content = content.replace(f'@{match}', self.format_user(match, new_user))
				self.logger.debug(f"Replaced @mention of {match} to {new_user}. {match} is not a Gogs user")
			elif match.lower() in self.users:
				# Double check that this @ is actually an @mention, and not e.g. a decorator in some code
				self.logger.debug(f"Replaced @mention of {match} to format specified for Github")
				content = content.replace(f'@{match}', self.format_user(match, match))
			else:
				self.logger.debug(f"Found @mention for {match} not present in mapping. Leaving as is")

		return self.__replace_codeblocks(content, self.code_language) if self.code_language is not None else content

	def format_user(self, old_user, new_user: str):
		if new_user is None:
			return f"**{old_user}**"
		else:
			return f'[@{new_user}](https://github.com/{new_user})' if not self.allow_mentions else f'@{new_user}'

	def __replace_codeblocks(self, content, language):
		self.logger.debug(f"Replacing implicit codeblocks to explicit codeblocks using language {language}")
		in_codeblock = False
		new_content = ""
		for line in content.splitlines():
			if line.startswith(" " * 4):
				if not in_codeblock:
					self.logger.debug("Found implicit codeblock line: " + line)
					new_content += f"```{language}\n"
				in_codeblock = True
				new_content += line[4:] + "\n"
			else:
				if not line.strip(" ") == "" and in_codeblock:
					new_content += "```\n"
					in_codeblock = False
				new_content += line + "\n"

		return new_content
