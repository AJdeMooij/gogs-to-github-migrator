import logging
import os
import time

import click

from classes.Configuration import Configuration
from classes.Migrator import Migrator


@click.command()
@click.option(
	"--config",
	type=click.Path(exists=True),
	required=True,
	help="Specify the location of the configuration (TOML) file", default='migration-settings.toml')
@click.version_option()
def migrate(config):
	"""Command line tool for migrating labels, milestones, issues, and pull requests from a Gogs MySQL database to Github.
	Requires read access on the Gogs database, and a Github app with write access on issues and pull requests to the
	target repository.

	This is a command line tool for migrating labels, milestones, issues, and pull requests from a Gogs MySQL database
	to Github.
	This tool requires read access on the Gogs database, and the creation and authentication of a
	GitHub App, which should be installed by the user or organization under whose name the migrated issues and pull
	requests will appear.

	**WARNING**: Issues cannot be deleted from Github after creation. Test this code on a repository that can be deleted,
	before running in a production environment. This code comes with absolutely no warranties; run at your own risk.

	This tool can copy all milestones, issues and pull requests from the Gogs database to Github, and can try to assign all
	labels and milestones again. Each of the comments, as well as references from commit messages, are added to the
	issues and pull requests, with a small comment on the original author and post time.

	Pull requests require both the base and head branch to be present in the new repository. This tool will try to
	migrate pull requests this way, but if either branch is missing, can create the original pull request as an issue,
	as to keep the discussion on that pull request.

	This tool tries to update all references between pull requests and issues, and tries to match Gogs users to Github
	users. For this latter part, the e-mail address known to Gogs needs to be associated with and public on the
	corresponding user's Github profile, as otherwise the Github API will not find the user for that e-mail address.
	A manual mapping can be specified in a `github-accounts` text file as well.

	The tool is highly configurable using the `migration-settings.toml` file, which contains comments
	to explain all the settings.

	Be careful allowing @mentions and assigning of issues and pull requests, as by default Github will send an e-mail
	for each event. Ask users to unsubscribe from the repository first, by clicking the `watch` button on the
	repository and clicking `ignore` if you want to use these settings.
	"""
	os.makedirs("log", exist_ok=True)

	logger = logging.getLogger()
	logger.setLevel(logging.DEBUG)

	ch = logging.StreamHandler()
	ch.setLevel(logging.INFO)

	fh = logging.FileHandler(filename=f"log/migration-{time.strftime('%Y_%m_%dT%H_%M_%S.log')}")
	fh.setLevel(logging.DEBUG)
	fh.setFormatter(logging.Formatter(fmt='%(asctime)s %(module)s (%(levelname)s)\n\t%(message)s'))

	logger.addHandler(ch)
	logger.addHandler(fh)

	Migrator(Configuration(click.format_filename(config)))


if __name__ == "__main__":
	migrate()
