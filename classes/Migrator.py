from click import progressbar
import logging
from classes.Configuration import Configuration
from classes.GithubAppApi import GithubAppApi
from classes.GogsDbReader import GogsDbReader
from classes.gogs_model.Issue import Issue
from classes.gogs_model.PullRequest import PullRequest


class Migrator(object):
	logger = logging.getLogger(__name__)

	def __init__(self, configuration: Configuration):
		self.configuration = configuration
		self.api = GithubAppApi(self.configuration)
		self.gogs = GogsDbReader(self.api, self.configuration)

		self.milestone_map = dict()
		self.issue_map = dict()
		self.issues = list()
		self.uploaded_as_pull = list()

		self.__migrate_labels = self.configuration.get_or_default(False, "migration", "labels")
		self.__migrate_milestones = self.configuration.get_migrate_milestones()
		self.__migrate_issues = self.configuration.get_migrate_issues()
		self.__migrate_pull_requests = self.configuration.get_migrate_pull_requests()

		self.start_migration()

	def start_migration(self):
		self.check_user_mapping()

		if self.__migrate_labels:
			self.logger.info("Migrating labels")
			self.migrate_labels()
			self.logger.info("Finished migrating labels")
		else:
			self.logger.info("Skipping labels")

		if self.__migrate_milestones:
			self.logger.info("Migrating milestones")
			self.migrate_milestones()
			self.logger.info("Finished migrating milestones")
		else:
			self.logger.info("Skipping milestones")

		if self.__migrate_issues or self.__migrate_pull_requests:
			if self.__migrate_issues and self.__migrate_pull_requests:
				self.logger.info("Migrating issues and pull requests")
			elif self.__migrate_issues:
				self.logger.info("Migrating issues")
			else:
				self.logger.info("Migrating pull requests")
			self.migrate_issues()

			self.logger.info("Migrating comments")
			self.migrate_issue_comments()
		else:
			self.logger.info("Skipping issues and pull requests")

	def check_user_mapping(self):
		repo_users = self.gogs.get_users_for_repository()
		missing_users = [user for user in repo_users if self.api.find_user_by_email(user['email']) is None]

		if len(missing_users):
			self.logger.info("No Github accounts were found for the following Gogs users:")
			for missing in missing_users:
				self.logger.info(f"\t{missing['name']} ({missing['full_name']}, {missing['email']})")
			self.logger.info(
				"\nYou can manually map Gogs users to Github accounts by creating a file `github-accounts` (without extension),"
				" adding one line `gogs-username <space> `github-username` for each user to be mapped, or you can continue "
				"without these users.")

			response = None
			while response not in ["Y", "n"]:
				response = input("Do you want to continue without these users? (Y/n)\n")

			if response == "n":
				exit(0)

	def migrate_labels(self) -> None:
		labels = self.gogs.get_labels()
		for label in labels:
			self.api.create_label_if_not_exists(label['name'], label['color'])

	def migrate_milestones(self) -> None:
		milestones = self.gogs.get_milestones()
		with progressbar(milestones, item_show_func=lambda m: m['name'] if m is not None else None) as milestone_bar:
			for milestone in milestone_bar:
				_id = self.api.create_milestone(milestone['name'], milestone['content'], milestone['deadline'], milestone['state'])
				self.milestone_map[milestone['id']] = _id
				self.logger.debug(f"Milestone {milestone['id']} now has ID {_id} on Github")

	def migrate_issues(self) -> None:
		self.issues = [
			PullRequest(self.api, self.gogs, row)
			if row["is_pull"] == 1
			else Issue(self.api, self.gogs, row)
			for row in self.gogs.get_issues()
		]

		with progressbar(self.issues, item_show_func=lambda i: i.name if i is not None else None) as issues_bar:
			for issue in issues_bar:
				index = None

				if issue.is_pull:
					if not self.configuration.migrate_by_state(issue, "pull_requests", "migrate"):
						self.logger.debug(f"Not migrating pull request {issue.name}")
						self.issue_map[issue.index] = None
						continue
					else:
						index = self.__try_migrate_as_pull_request(issue)

					if index is None and self.configuration.migrate_by_state(issue, "pull_requests", "as_issue", "migrate"):
						self.logger.debug(f"Failed to create as pull request. Migrating as issue")
						index = self.__migrate_as_issue(issue)
					else:
						self.uploaded_as_pull.append(index)
						if index is None:
							self.logger.debug(f"Failed to migrate as pull request")
						else:
							self.logger.debug(f"Pull request successfully migrated. Index #{issue.index} is #{index} on Github")

				elif self.configuration.migrate_by_state(issue, "issues", "migrate"):
					index = self.__migrate_as_issue(issue)
					self.logger.debug(f"Issue successfully migrated. Index #{issue.index} is #{index} on Github")

				self.issue_map[issue.index] = index

	def __try_migrate_as_pull_request(self, issue: PullRequest):
		index = self.api.try_create_pull_request(
			issue.name,
			issue.head,
			issue.base,
			issue.get_pull_request_content(self.issue_map)
		)

		if index is not None:
			# We cannot set these values using the create PR API, since these are attributes PR's have in common
			# with issues. Instead, we will update them if we have to.
			kwargs = dict(labels=None, assignees=None, milestone=None, state=None)

			if self.__migrate_labels:
				kwargs['labels'] = issue.load_labels_for_issue()
			self.logger.debug(f"Adding labels {kwargs['labels']} to pull request")
			if issue.get_github_assignees() is not None and self.configuration.migrate_by_state(
					issue, "pull_requests", "assignees"):
				kwargs['assignees'] = issue.get_github_assignees()
			self.logger.debug(f"Assigning pull request to {kwargs['assignees']}")
			if issue.milestone_id is not None and self.configuration.migrate_by_state(issue, "pull_requests", "milestones"):
				kwargs['milestone'] = self.milestone_map[issue.milestone_id]
				self.logger.debug(f"Adding milestone {kwargs['milestone']} to pull request")

			if len(kwargs):
				self.api.update_issue_state(index, **kwargs)

		return index

	def __migrate_as_issue(self, issue: Issue):
		"""Migrate an issue, or a pull request that could not be created as a pull request"""
		title = f"[PULL REQUEST] {issue.name}" if issue.is_pull else issue.name
		milestone = assignees = None

		if self.__migrate_milestones and issue.milestone_id is not None and self.configuration.add_property_by_state(
				issue, "milestones"):
			milestone = self.milestone_map[issue.milestone_id]
			self.logger.debug(f"Adding milestone {milestone} to issue/pull request")

		labels = issue.load_labels_for_issue() if self.__migrate_labels else None
		if labels is not None:
			self.logger.debug(f"Adding labels {labels} to issue/pull request")

		if self.configuration.add_property_by_state(issue, "assignees"):
			assignees = issue.get_github_assignees()
			self.logger.debug(f"Assigning issue/pull request to {assignees}")

		index = self.api.create_issue(
			title,
			issue.get_issue_content(self.issue_map),
			assignees,
			milestone,
			labels
		)

		return index

	def migrate_issue_comments(self):
		with progressbar(
				self.issues,
				item_show_func=lambda i: f"{i.name} ({len(i.comments)} issue comments)" if i is not None else None
		) as issues_bar:
			for issue in issues_bar:
				issue_number = self.issue_map[issue.index]

				if issue_number is None:
					self.logger.debug(f"Issue/pull request {issue.index} was not migrated. Skipping comments")
					continue

				issue.load_comments_for_issue()
				self.logger.debug(
					f"{len(issue.comments)} comments loaded for issue/pull request #{issue.index} (-> #{issue_number})")

				for comment in issue.comments:
					self.api.create_issue_comment(issue_number, comment.get_comment_text(self.issue_map))
					if comment.row['type'] == 1:
						# Issue (re)opened
						self.logger.debug(f"Reopening #{issue.index} (-> #{issue_number})")
						self.api.update_issue_state(issue_number, 'open', None, None, None)
					elif comment.row['type'] == 2:
						# Issue closed
						self.logger.debug(f"Closing #{issue.index} (-> #{issue_number})")
						self.api.update_issue_state(issue_number, 'closed', None, None, None)
