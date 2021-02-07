import logging
import os
import time
from datetime import datetime

import click
import requests
from jose import jwt

from classes.Configuration import Configuration


class GithubAppApi(object):
	logger = logging.getLogger(__name__)
	base = "https://api.github.com/"
	mockup_request_result = dict(number=42, id=1, name="Example Label", color="f29513")
	continue_after_error = False

	def __init__(self, conf: Configuration):
		self.users = dict()
		self.conf = conf
		self.owner = self.conf.get("github", "username")
		self.repo = self.conf.get("github", "repository")
		self.app_id = self.conf.get("github", "app_id")
		self.key_file = self.conf.get("github", "key_file")

		self.create_pr = self.conf.get_or_default("migration", "pull_requests", "migrate")
		self.jwt_token = self._get_jwt_token()
		self._authenticate_app()
		self.labels = None
		self.milestones_by_title = None
		self.consider_rate_limit = self.conf.get_or_default(False, "migration", "slow")

		self.__dry_run = self.conf.get_or_default(True, "migration", "dryrun")
		if self.__dry_run:
			self.logger.info("Dryrun instruction received, Not making changes on Github.")

	def create_issue(self, title: str, body: str, assignees: [str] or None, milestone: int, labels: [any]):
		"""
		See https://docs.github.com/en/rest/reference/issues#create-an-issue

		:param title:           Required. The title of the issue.
		:param body:            The contents of the issue.
		:param assignees:       Logins for Users to assign to this issue.
		:param milestone:       The number of the milestone to associate this issue
		:param labels:          Labels to associate with this issue.
		:return:                Integer ID of the created issue
		"""
		request_body = dict(title=title)
		for k, v in [("body", body), ("assignees", assignees), ("milestone", milestone), ("labels", labels)]:
			if v is not None:
				request_body[k] = v

		status, result = self.__post(self.__get_repo_url('issues'), request_body)

		if status:
			self.logger.debug(f"Created issue {title}")
			return result["number"]
		else:
			if 'errors' in result:
				for e in result['errors']:
					if 'field' in e and e['field'] == 'assignees' and 'value' in e:
						assignees.remove(e['value'])
						self.logger.debug(
							f"{e['value']} is an invalid assignee according to Github. "
							f"Trying again to create issue without assigning")
						return self.create_issue(title, body, assignees, milestone, labels)
			elif self.__print_error(f"Failed to create issue {title}", result):
				return self.create_issue(title, body, assignees, milestone, labels)

	def update_issue_state(
			self, issue_number: int,
			state: str or None,
			labels: [any] or None,
			assignees: [str] or None,
			milestone: int or None
	) -> int:
		"""
		See https://docs.github.com/en/rest/reference/issues#update-an-issue

		Note:
		Every pull request is an issue, but not every issue is a pull request. For this reason, "shared" actions
		for both features, like manipulating assignees, labels and milestones, are provided within the Issues API.

		:param issue_number:    issue_number parameter
		:param state:           State of the issue. Either open or closed.
		:param labels:          A list of labels for this issue or pull request
		:param assignees:       Logins for Users to assign to this issue. Pass one or more user logins to replace
								the set of assignees on this Issue. Send an empty array ([]) to clear all assignees
								from the Issue. NOTE: Only users with push access can set assignees for new issues.
								Assignees are silently dropped otherwise.
		:param milestone:       undefined

		:return:                None
		"""
		request_body = dict()
		if state is not None:
			request_body['state'] = state
		if labels is not None:
			request_body['labels'] = labels
		if assignees is not None:
			request_body['assignees'] = assignees
		if milestone is not None:
			request_body['milestone'] = milestone

		status, result = self.__patch(self.__get_repo_url(f'issues/{issue_number}'), request_body)
		if status:
			return result['number']
		else:
			if 'errors' in result:
				for e in result['errors']:
					if 'field' in e and e['field'] == 'assignees' and 'value' in e:
						assignees.remove(e['value'])
						self.logger.debug(
							f"{e['value']} is an invalid assignee according to Github. "
							f"Trying again to update issue without assigning")
						return self.update_issue_state(issue_number, state, labels, assignees, milestone)
			elif self.__print_error(f"Failed to update issue", result):
				return self.update_issue_state(issue_number, state, labels, assignees, milestone)

	def create_issue_comment(self, issue_id: int, body: str):
		"""
		See https://docs.github.com/en/rest/reference/issues#create-an-issue-comment

		:param issue_id:    Required. issue_number parameter
		:param body:        Required. The contents of the comment.
		:return:            Integer ID of the created comment
		"""
		status, result = self.__post(self.__get_repo_url(f'issues/{issue_id}/comments'), dict(body=body))
		if status:
			self.logger.debug("Successfully created issue comment")
			return result['id']
		else:
			if self.__print_error("Failed to update issue", result):
				return self.create_issue_comment(issue_id, body)

	def try_create_pull_request(self, title: str, head: str, base: str, body: str):
		"""
		See https://docs.github.com/en/rest/reference/pulls#create-a-pull-request

		:param title:   The title of the new pull request.
		:param head:    Required. The name of the branch where your changes are implemented.
						For cross-repository pull requests in the same network,
						namespace head with a user like this: username:branch.
		:param base:    Required. The name of the branch you want the changes pulled into.
						This should be an existing branch on the current repository.
						You cannot submit a pull request to one repository that requests
						a merge to a base of another repository.
		:param body:    The contents of the pull request.
		:return:        Integer pull request number of the created pull request
		"""
		request_body = dict(title=title, head=head, base=base)

		if body is not None:
			request_body['body'] = body

		status, result = self.__post(self.__get_repo_url('pulls'), request_body)
		if status:
			self.logger.debug("Successfully created pull request")
			return result['number']
		else:
			# We were never sure if we could create this as a PR to begin with
			self.logger.debug("Tried creating pull request, but head or base branch seem to be missing")
			return None

	def create_milestone(self, title: str, description: str, due_on: str, state: str = "open"):
		"""
		See https://docs.github.com/en/rest/reference/issues#create-a-milestone

		:param title:       Required. The title of the milestone.
		:param description: A description of the milestone.
		:param due_on:      The milestone due date. This is a timestamp in ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ.
		:param state:       The state of the milestone. Either open or closed.
		:return:            Integer ID of the created milestone
		"""

		milestone = self.__get_number_for_milestone_if_exists(title)
		if milestone is not None:
			self.logger.debug(f"Milestone {title} already exists on Github")
			return milestone
		else:
			request_body = dict(title=title)
			for k, v in [("description", description), ("due_on", due_on), ("state", state)]:
				if v is not None:
					request_body[k] = v

			status, result = self.__post(self.__get_repo_url('milestones'), request_body)
			if status:
				self.logger.debug(f"Created milestone {title}")
				return result['number']
			else:
				if self.__print_error(f"Failed to create milestone {title}", result):
					return self.create_milestone(title, description, due_on, state)

	def __get_number_for_milestone_if_exists(self, title: str):
		if self.milestones_by_title is None:
			status, milestones = self.__get(self.__get_repo_url('milestones'), dict(state='all'))

			if status:
				self.logger.debug("Milestones loaded from Github")
				self.milestones_by_title = dict()

				for m in milestones:
					self.milestones_by_title[m['title']] = m

		return self.milestones_by_title[title]['number'] if title in self.milestones_by_title else None

	def create_label_if_not_exists(self, name, color):
		"""
		See https://docs.github.com/en/rest/reference/issues#create-a-label

		:param name: The name of the label. Emoji can be added to label names, using either native emoji or colon-style
						markup. For example, typing :strawberry: will render the emoji :strawberry:. For a full list
						of available emoji and codes, see emoji-cheat-sheet.com.
		:param color: The hexadecimal color code for the label, without the leading #.
		:return: Label JSON object
		"""
		label = self._label_exists(name)
		if label is not None:
			self.logger.debug(f"Label {name} already exists")
			return label
		else:
			request_body = dict(name=name)
			if color is not None:
				request_body["color"] = color.replace('#', '')

			status, result = self.__post(self.__get_repo_url('labels'), request_body)
			if status:
				self.logger.debug(f"Created label {name}")
				return result
			else:
				if self.__print_error(f"Failed to create label {name} and the label did not yet exist", result):
					return self.create_label_if_not_exists(name, color)

	def _label_exists(self, label_name: str):
		if self.labels is None:
			status, result = self.__get(self.__get_repo_url('labels'))
			if status:
				self.labels = result
			else:
				if self.__print_error("Could not retrieve labels", result):
					return self._label_exists(label_name)
				return None

		for label in self.labels:
			if label["name"] == label_name:
				return label

		return None

	def __get_contributors(self):
		status, result = self.__get(self.__get_repo_url('contributors'))
		if status:
			return dict([(result['email'], result['login']) for user in result if 'email' in user])
		return dict()

	def __find_user_by_email(self, email):
		email = email.lower()
		status, result = self.__get('search/users', dict(q=email))
		if status:
			users = result['items']
			for user in users:
				user_json = requests.get(user['url'], headers=self.headers).json()
				if user_json['email'] is not None and user_json['email'].lower() == email:
					self.logger.debug(f"Found Github user {user['login']} for e-mail address {email}")
					return user['login']

		self.logger.debug(f"No Github user found for e-mail address {email}")
		return None

	def find_user_by_email(self, email: str):
		email = email.lower()
		if email in self.users:
			return self.users[email]
		else:
			# Intentionally set e-mail to None in dict, to avoid further requests for this e-mail
			user = self.__find_user_by_email(email)
			self.users[email] = user
			return user

	def __get_repo_url(self, path):
		return f'repos/{self.owner}/{self.repo}/{path}'

	def __post(self, path, request_body):
		if self.__dry_run:
			self.logger.debug("Not performing POST request to Github because dry-run is enabled")
			return True, self.mockup_request_result

		result = requests.post(
			self.base + path,
			json=request_body,
			headers=self.headers
		)

		status, wait = self.__verify_result(result)
		if not status and wait >= 0:
			time.sleep(wait)
			self.__post(path, request_body)
		else:
			if self.consider_rate_limit:
				time.sleep(1)
			return status, result.json()

	def __patch(self, path, request_body):
		if self.__dry_run:
			self.logger.debug("Not performing PATCH request to Github because dry-run is enabled")
			return True, self.mockup_request_result

		result = requests.patch(
			self.base + path,
			json=request_body,
			headers=self.headers
		)

		status, wait = self.__verify_result(result)
		if not status and wait >= 0:
			time.sleep(wait)
			self.__patch(path, request_body)
		else:
			if self.consider_rate_limit:
				time.sleep(1)
			return status, result.json()

	def __get(self, path, params=None):
		use_params = dict() if params is None else params

		result = requests.get(
			self.base + path,
			params=use_params,
			headers=self.headers
		)

		status, wait = self.__verify_result(result)
		if not status and wait >= 0:
			time.sleep(wait)
			self.__get(path, params)
		else:
			return status, result.json()

	def __verify_result(self, response: requests.Response) -> (bool, int):
		"""
		Checks if the response yielded a success code. If not, checks if a rate limit suggestion is provided. If
		neither is the case, assume an error
		:param response:    Requests response
		:return:            Tuple with first element success status and second element the number of seconds to wait
							before trying again, or -1 if a general error occurred
		"""
		if response.status_code in [200, 201]:  # Success / Created
			return True, 0
		else:
			if 'Retry-After' in response.headers:
				self.logger.debug(f"Reached API rate limit. Trying again in {response.headers['Retry-After']} seconds")
				return False, response.headers['Retry-After']
			else:
				self.logger.debug(f"Got response code {response.status_code}: {response.raw}")
				return False, -1

	def __print_error(self, msg: str, response: dict):
		for k in response:
			msg += f"\n\t{k}: {response[k]}"

		if self.continue_after_error:
			self.logger.debug(msg)
		else:
			self.logger.warning("\n\n" + msg)
			reply = click.prompt(
				"Do you want to try again ('t'/'try'), continue and ignore ('i'/'ignore'), "
				"without ignoring ('c'/'continue') or stop ('q'/'quit') here?")
			while reply.lower() not in ['t', 'try', 'i', 'ignore', 'c', 'continue', 'q']:
				reply = click.prompt("Not understood, type 't', 'i', 'c' or 'q'")
			if reply.lower() in ['t', 'try']:
				return True
			elif reply.lower() in ['i', 'ignore']:
				self.continue_after_error = True
			elif reply.lower() in ['c', 'continue']:
				return False
			else:
				exit(0)

	@staticmethod
	def _create_default_headers(auth: str):
		return {'Accept': 'application/vnd.github.v3+json', 'Authorization': auth}

	@staticmethod
	def _create_token_headers(token):
		return GithubAppApi._create_default_headers(f'Token {token}')

	@staticmethod
	def _create_jwt_headers(jwt_token):
		return GithubAppApi._create_default_headers(f'Bearer {jwt_token}')

	def _authenticate_app(self):
		jwt_headers = self._create_jwt_headers(self.jwt_token)
		result = requests.get(self.base + 'app/installations', headers=jwt_headers).json()
		if 'message' in result:
			self.logger.critical(f"Github returned the following message: {result['message']}.")
			self.logger.critical("Please check the provided Github App ID and private key file")
			exit(2)
		if len(result) == 0:
			self.logger.critical("No installations found for Github App. Assign an installation to this app before continuing")
			exit(3)

		application_id = result[0]["id"]

		# Activate installation
		requests.get(self.base + f'app/installations/{application_id}', headers=jwt_headers)

		# Get Authorization token for installation
		token_result = requests.post(
			self.base + f'app/installations/{application_id}/access_tokens', headers=jwt_headers).json()

		if "issues" not in token_result["permissions"] or token_result["permissions"]["issues"] != 'write':
			self.logger.critical("Enable write permissions for issues in Github app before using this application")
			exit(4)
		if self.create_pr:
			if 'pull_requests' not in token_result["permissions"] or token_result["permissions"]['pull_requests'] != 'write':
				self.logger.critical(
					"Enable write permissions for pull requests in Github app before using this application, "
					"or disable migration of pull requests in arguments")
				exit(5)

			if 'contents' not in token_result['permissions'] or token_result['permissions']['contents'] != 'write':
				self.logger.warning(
					"You have requested migration of pull requests, but the Github app has no write permission on contents.\n"
					"To create a pull request, the Github app will need this permission. Without this permission, all "
					"pull requests will be created as issues, even if both branches are present.")

				response = 'random'
				while response not in ['Y', 'n']:
					response = input("Do you want to continue and migrate all pull requests as issues? (Y/n): ")

				if response == 'n':
					exit(0)

		self.token = token_result['token']
		self.headers = self._create_token_headers(self.token)

		for r in result:
			repositories = requests.get(r['repositories_url'], headers=self.headers).json()
			for repo in repositories['repositories']:
				if self.repo == repo['name'].lower():
					# All is good
					return

		self.logger.critical(f"Your github app is not installed yet, or does not have access to the repository {self.repo}")
		exit(6)

	def _get_jwt_token(self):
		if not os.path.exists(self.key_file):
			self.logger.critical(f"Key file {self.key_file} does not exist")
			exit(5)
		with open(self.key_file, 'r') as key_file_in:
			private_pem = key_file_in.read()

		payload = {
			"iat": int(datetime.timestamp(datetime.now())),
			"exp": int(datetime.timestamp(datetime.now())) + (9 * 60),
			"iss": self.app_id
		}
		self.logger.debug(f"Generating JWT code for Github app {self.app_id} to access Github API")
		return jwt.encode(payload, private_pem, algorithm="RS256")
