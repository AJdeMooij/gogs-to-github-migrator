from setuptools import setup

setup(
	name='GogsToGithubMigrator',
	version='1.0',
	py_modules=['gogs-to-github'],
	install_requires=[
		'click~=7.1.2',
		'mysql~=0.0.2',
		'mysql-connector-python~=8.0.22',
		'python-jose~=3.2.0',
		'requests~=2.25.0',
		'setuptools~=51.3.1',
		'toml~=0.10.2'
	],
	entry_points='''
		[console_scripts]
		gogs-to-github=migrator:migrate
	'''
)
