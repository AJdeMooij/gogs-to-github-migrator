This is a command line tool for migrating labels, milestones, issues, and pull requests from a Gogs MySQL database to Github.
This tool requires read access on the Gogs database, and the creation and authentication of a [GitHub App](https://docs.github.com/en/developers/apps), which should be installed by the user or organization under whose name the migrated issues and pull requests will appear. 

**WARNING**: Issues cannot be deleted from Github after creation. Test this code on a repository that can be deleted,
before running in a production environment. This code comes with absolutely no warranties; run at your own risk.

## Description
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

The tool is highly configurable using the `migration-settings.toml` file, which contains comments to explain all the settings.

**Be careful** allowing @mentions and assigning of issues and pull requests, as by default Github will send an e-mail for each event. Ask users to unsubscribe from the repository first, by clicking the `watch` button on the repository and clicking `ignore` if you want to use these settings.

### A note on rate limiting
Github has a rate limit. This tool makes, what the
[documentation](https://docs.github.com/en/rest/guides/best-practices-for-integrators#dealing-with-abuse-rate-limits)
would call, "a large number of `POST`, `PATCH`, or `PUT`" requests. 

The configuration file contains an option to enable `slow` mode, which will follow Github's advice to "wait at least 
one second between each request".

For lower number of issues, pull requests and comments, slow mode may not be necessary. However, Github does not
indicate how many if these requests are officially allowed by the API in a certain unit-time. Moreover, Github also says:

>Requests that create content which triggers notifications, such as issues, comments and pull requests, may be further limited and will not include a Retry-After header in the response. Please create this content at a reasonable pace to avoid further limiting.

So even with slow mode enabled, the Github API may decide to block the application during the migration process.

## Preparation
If you do not yet have a GitHub repository to which your Gogs repository should be migrated, create one with your preferred name. Use the Git command line interface to first push all branches you want to keep to the new repository.

First, add the Github repository as a new remote
```shell
 git remote add github <repository url>
 ```

Then, for each branch:
```shell
 git push github <branch>
```

Any pull request on Gogs will be recreated as an issue instead of a pull request, unless both the head and base branch for that pull request are present on Github under the same name, due to limitations of the Github API.

### Creating and installing a Github App
The migrator tool requires a GitHub App to authenticate. This app does not have to be installed on any server, so follow the instructions in Section 2 and 3 of [this GitHub App Guide](https://docs.github.com/en/developers/apps/setting-up-your-development-environment-to-create-a-github-app#step-2-register-a-new-github-app) to register a new app. You will need your App ID and private key (referenced in this tutorial) later to invoke the migrator script.

You will need to grant write permissions on `Issues` and, if you want to create pull requests, on `Pull requests`.

When asked where this App can be installed, select `Any account` if you want to run the migration under an organization. Keep in mind that the owner of the installation's profile image will be shown on all actions performed by this bot.

Next, [install your app](https://docs.github.com/en/developers/apps/setting-up-your-development-environment-to-create-a-github-app#step-7-install-the-app-on-your-account) to the user or organization the migrated issues and pull requests should appear under, and grant the permissions at least to the repository to which you wish to migrate.
### Installation (Linux)
This tool runs in Python.

(Optional:) Create a virtual environment
```shell
$ virtualenv gogstogithub
$ . gogstogithub/bin/activate
```

Clone this repository (assuming to a directory called `gogs-to-github` for this tutorial)

```shell
$ cd gogs-to-github
$ pip install --editable .
```

Test if the installation finished successfully:

```shell
$ python3 gogs-to-github --version
```

If the terminal shows the version number of the gogs-to-github tool, installation has finished successfully.
