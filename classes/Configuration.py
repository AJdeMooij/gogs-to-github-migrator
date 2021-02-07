import sys
import toml


class Configuration(object):
	required_fields = dict(
		gogs=["host", "database", "username", "repository"],
		github=["username", "repository", "app_id", "key_file"]
	)

	def __init__(self, configuration_file):
		self.conf = toml.load(configuration_file)

		for parent, fields in self.required_fields.items():
			self.__verify_required_fields_present(parent, fields)

	def __verify_required_fields_present(self, parent: str, fields: [str]) -> None:
		if parent not in self.conf:
			print(f"Specified configuration file has no `{parent}` configuration", file=sys.stderr)
			exit(10)

		missing = [x for x in fields if x not in self.conf[parent]]
		if len(missing):
			print(f"The following keys are missing from the `{parent}` configuration:", file=sys.stderr)
			for m in missing:
				print(f"\t{m}", file=sys.stderr)
			exit(10)

	def get_or_default(self, default: any, *path: str):
		try:
			return self.get(*path)
		except KeyError:
			return default

	def get(self, *path: str):
		element = self.conf
		for key in path:
			element = element[key]

		return element

	def get_migrate_milestones(self):
		add_pull_requests = len(self.get_or_default([], "migration", "pull_requests", "milestones"))
		add_issue_pull_requests = len(self.get_or_default([], "migration", "pull_requests", "as_issue", "milestones"))
		add_issues = len(self.get_or_default([], "migration", "issues", "milestones"))

		return add_pull_requests or add_issue_pull_requests or add_issues

	def get_migrate_issues(self):
		return len(self.get_or_default([], "migration", "issues", "migrate"))

	def get_migrate_pull_requests(self):
		return \
			len(self.get_or_default([], "migration", "pull_requests", "migrate")) or \
			len(self.get_or_default([], "migration", "pull_requests", "as_issue", "migrate"))

	def migrate_by_state(self, issue, *path: str) -> bool:
		"""
		Checks if an issue of any type should be migrated, or if attributes should be set after migration,
		based on the state (open|closed) of the issue

		:param issue:   Issue to potentially migrate or to set properties on
		:param path:    Property path, within the `migration` group (do not include `migration` in the path)
		:return:        True iff issue or property should be migrated
		"""
		return ('closed' if issue.is_closed else 'open') in self.get_or_default(False, "migration", *path)

	def add_property_by_state(self, issue, prop: str) -> bool:
		"""
		Checks if a property should be added to a migrated issue, depending on whether this issue is a pull request or
		an issue. Should only be used after creation of pull request as pull request has failed.
		
		:param issue:   Issue to potentially set properties on
		:param prop:    Property to verify (e.g. "milestones" or "assignees")
		:return:        True iff the property should be migrated for the given issue
		"""
		if issue.is_pull:
			return self.migrate_by_state(issue, "pull_requests", "as_issue", prop)
		else:
			return self.migrate_by_state(issue, "issues", prop)
