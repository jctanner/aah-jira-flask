#!/usr/bin/env python

import argparse
import os
import re
import time
import urllib3

from datetime import datetime
from datetime import timezone

import requests
import requests_cache

from github import Auth
from github import Github
from github import Consts
from github.Requester import Requester

from logzero import logger
from git import Repo


#requests_cache.install_cache('/tmp/demo_cache')
requests_cache.install_cache('demo_cache')


'''
# define the projects
REPOS = [
    'pulp/pulpcore',
    'pulp/pulp_ansible',
    'pulp/pulp_container',
    'pulp/oci_env',
    'ansible/ansible-hub-ui',
    'ansible/galaxy_ng',
    #'ansible/galaxy-deploy',
    'ansible/galaxy-importer',
    'ansible/galaxykit',
    #'ansible/aap-gateway',
    'ansible/django-ansible-base',
    'encode/django-rest-framework',
]
'''


class GitCacher:

    cachedir = '.cache'

    def __init__(self, repo_full_names):
        self.repo_full_names = repo_full_names
        if not os.path.exists(self.cachedir):
            os.makedirs(self.cachedir)
        self.repos = {}

    def get_repository(self, repo_full_name):
        if repo_full_name in self.repos:
            return self.repos[repo_full_name]

        token = os.environ.get('GITHUB_TOKEN')

        repo_dir = os.path.join(self.cachedir, repo_full_name.replace('/', '__'))
        repo_url = f'https://{token}@github.com/' + repo_full_name

        if not os.path.exists(repo_dir):
            repo = Repo.clone_from(repo_url, repo_dir)
        else:
            repo = Repo(repo_dir)
        self.repos[repo_full_name] = repo
        return repo

    def get_commit_message(self, repo_full_name, commit_sha):
        repo = self.get_repository(repo_full_name)
        try:
            commit = repo.commit(commit_sha)
            return commit.message
        except ValueError:
            return None


class UserEvent:

    _jiras = None

    def __init__(self, login=None, repo=None, issue=None, pull=None, event_name=None, timestamp=None):
        self.login = login
        self.repo = repo
        self.issue = issue
        self.pull = pull
        self.event_name = event_name
        self.timestamp = timestamp

        self.process_jiras()

    def __str__(self):
        return f'{self.ts} ({self.repo.full_name} #{self.number}) "{self.title}" [{self.event_name}]'

    def __repr__(self):
        return f'<UserEvent {self.__str__()}>'

    def process_jiras(self):
        pattern = r'https://issues\.redhat\.com/browse/[A-Z]+-\d+'
        matches = re.findall(pattern, self.title + " " + self.body)
        if matches:
            self._jiras = matches

    @property
    def jira_keys(self):
        if not self.jiras:
            return ''
        keys = [x.split('/')[-1] for x in self.jiras]
        return ','.join(keys)

    @property
    def ts(self):
        return self.timestamp.isoformat().split('T')[0]

    @property
    def full_ts(self):
        return self.timestamp.isoformat()

    @property
    def html_url(self):
        return self.issue.html_url

    @property
    def title(self):
        return self.issue.title or ''

    @property
    def number(self):
        return self.issue.number

    @property
    def body(self):
        return self.issue.body or ''

    @property
    def jiras(self):
        return self._jiras


class GithubRequesterOverride(Requester):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def requestJsonAndCheck(self, *args, **kwargs):
        logger.debug(f'FETCH {args[1]}')
        headers = {'Authorization': f'token {self.auth.token}'}
        url = args[1]
        if not url.startswith(self.base_url):
            url = self.base_url + args[1]
        method = args[0].lower()
        func = getattr(requests, method)

        while True:

            try:
                rr = func(url, headers=headers, timeout=2)
                break
            except urllib3.exceptions.MaxRetryError as e:
                logger.debug(f'sleeping 10s after maxretryerror: {e}')
                time.sleep(10)
            except urllib3.exceptions.NewConnectionError as e:
                logger.debug(f'sleeping 10s after newconnectionerror: {e}')
                time.sleep(10)
            except requests.exceptions.ConnectionError as e:
                logger.debug(f'sleeping 10s after connectionerror: {e}')
                time.sleep(10)
            except Exception as e:
                #print(e)
                #import epdb; epdb.st()
                raise e
                break

        if rr.status_code == 401:
            raise Exception(rr.text)
        return dict(rr.headers), rr.json()


class GithubOverride(Github):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._Github__requester = GithubRequesterOverride(
            kwargs['auth'],
            Consts.DEFAULT_BASE_URL,
            Consts.DEFAULT_TIMEOUT,
            Consts.DEFAULT_USER_AGENT,
            Consts.DEFAULT_PER_PAGE,
            True,
            3,
            None,
            Consts.DEFAULT_SECONDS_BETWEEN_REQUESTS,
            Consts.DEFAULT_SECONDS_BETWEEN_WRITES,
        )


class GithubClient():

    def __init__(self, token=None):
        self.token = token
        auth = Auth.Token(self.token)

        #self.g = Github(auth=auth)
        #self.g.__requester = GithubRequestor(token=self.token)

        self.g = GithubOverride(auth=auth)

    def search_issues(self, query, grepo=None):
        # GET https://api.github.com/search/issues?q=commenter:foobar
        # GET https://api.github.com/search/issues?q=commenter:foobar+repo:owner/repo
        # GET https://api.github.com/search/issues?q=type:pr+reviewed-by:foobar
        # GET https://api.github.com/search/issues?q=type:pr+reviewed-by:foobar+repo:owner/repo

        next_url = 'https://api.github.com/search/issues?q=' + query
        while next_url:
            logger.info(f'FETCH {next_url}')
            rr = requests.get(next_url, headers={'Authorization': f'token {self.token}'})
            items = rr.json()['items']
            for item in items:
                number = item['number']
                yield grepo.get_issue(number)

            if not rr.headers.get('Link'):
                break
            links = rr.headers.get('Link')
            if 'next' not in rr.links:
                break
            next_url = rr.links['next']['url']

    def get_repository(self, path):
        repo = self.g.get_repo(path)
        if repo is None or repo.name is None:
            raise Exception(f'failed to fetch {path}')
        return repo

        for x in self.g.search_repositories(path):
            if x.full_name == path:
                return x


    def find_user_events(self, repos, login, start=None, end=None):
        matches = set()

        for repo in repos:
            logger.info(f'PROCESS {repo}')
            try:
                grepo = self.get_repository(repo)
            except Exception as e:
                logger.exception(e)
                continue

            for issue in grepo.get_issues(creator=login, state='all'):
                matches.add((grepo, issue))

            for issue in self.search_issues(f'commenter:{login}+repo:{repo}', grepo=grepo):
                matches.add((grepo, issue))

            for issue in self.search_issues(f'type=pr+reviewed-by:{login}+repo:{repo}', grepo=grepo):
                matches.add((grepo, issue))

        matches = list(matches)
        matches = sorted(matches, key=lambda x: (x[0].name, x[1].number))

        #class UserEvent:
        #    def __init__(self, login=None, repo=None, issue=None, event_name=None, timestamp=None):

        events = []
        total = len(matches)
        counter = 0
        for grepo, match in matches:
            counter += 1
            logger.info(f'{total}|{counter} {grepo} {match}')

            if match.pull_request:
                pr = grepo.get_pull(match.number)
            else:
                pr = None

            if match.user.login == login:
                #events.append((match.created_at, 'opened', grepo, match, match.title))
                ev = UserEvent(timestamp=match.created_at, event_name='opened', repo=grepo, issue=match, pull=pr)
                events.append(ev)

                if match.state == 'closed':
                    #events.append((match.closed_at, 'closed', grepo, match, match.title))
                    ev = UserEvent(timestamp=match.closed_at, event_name='closed', repo=grepo, issue=match, pull=pr)
                    events.append(ev)

            for comment in match.get_comments():
                if comment.user.login == login:
                    #events.append((comment.created_at, 'commented', grepo, match, match.title))
                    ev = UserEvent(timestamp=comment.created_at, event_name='commented', repo=grepo, issue=match, pull=pr)
                    events.append(ev)

            if match.pull_request:
                pr = grepo.get_pull(match.number)

                for review_comment in pr.get_review_comments():
                    if review_comment.user.login == login:
                        #events.append((review_comment.created_at, 'review_commented', grepo, match, match.title))
                        ev = UserEvent(
                            timestamp=review_comment.created_at,
                            event_name='review_commented',
                            repo=grepo, issue=match,
                            pull=pr
                        )
                        events.append(ev)

                for commit in pr.get_commits():
                    author = commit.author
                    if author is None:
                        author = commit.committer
                    if author is None:
                        continue
                    if author.login != login:
                        continue
                    ts = commit.commit.committer.date
                    #events.append((ts, 'committed', grepo, match, match.title))
                    ev = UserEvent(timestamp=ts, event_name='committed', repo=grepo, issue=match, pull=pr)
                    events.append(ev)

        events = sorted(events, key=lambda x: x.timestamp)
        if start:
            events = [x for x in events if x.timestamp >= start]
        if end:
            events = [x for x in events if x.timestamp <= end]

        return events


def display_groups_events(events, prefix='\t\t'):
    #    print(f'\t\t{event.ts} {event.event_name}')

    buckets = {}
    for x in events:
        if x.ts not in buckets:
            buckets[x.ts] = {}
        if x.event_name not in buckets[x.ts]:
            buckets[x.ts][x.event_name] = 0
        buckets[x.ts][x.event_name] += 1

    bkeys = sorted(list(buckets.keys()))
    for bkey in bkeys:
        enames = sorted(list(buckets[bkey].keys()))
        if 'opened' in enames:
            enames.remove('opened')
            enames.insert(0, 'opened')
        if 'closed' in enames:
            enames.remove('closed')
            enames.append('closed')
        for ename in enames:
            ecount = buckets[bkey][ename]
            print(f'{prefix}{bkey} {ename} x{ecount}')


def summarize_events(events, git_cacher=None, login=None):
    imap = {}

    for event in events:
        key = (event.repo.full_name, event.issue.number)
        if key not in imap:
            imap[key] = {'start': event.timestamp, 'stop': event.timestamp, 'events': []}
        if event.timestamp < imap[key]['start']:
            imap[key]['start'] = event.timestamp
        if event.timestamp > imap[key]['stop']:
            imap[key]['stop'] = event.timestamp
        imap[key]['events'].append(event)

    sorted_keys = list(imap.keys())
    sorted_keys = sorted(sorted_keys, key=lambda x: imap[x]['start'])

    prs_created = 0
    prs_collaborated = 0
    prs_merged = 0

    for idk,skey in enumerate(sorted_keys):
        ival = imap[skey]

        e0 = ival['events'][0]
        issue = e0.issue
        pr = e0.pull
        is_merged = 'N/A'
        merged_by = 'N/A'
        if pr is not None:
            if pr.user.login == login:
                prs_created += 1
            else:
                prs_collaborated += 1

            is_merged = pr.is_merged()
            if pr.merged_by is not None:
                if pr.merged_by.login == login:
                    prs_merged += 1
                merged_by = pr.merged_by.login

        start = ival["start"].isoformat().split('T')[0]
        finish = ival["stop"].isoformat().split('T')[0]

        print('-' * 100)
        print(f'{idk+1}. {issue.html_url} {start} -> {finish}')
        #print(f'\tcreator: {issue.user.login} "{issue.user.name}"')
        print(f'\tcreator:{issue.user.login}')
        print(f'\tstate:{issue.state}')
        print(f'\tmerged:{is_merged} by:{merged_by}')
        print(f'\ttitle: {issue.title}')
        if e0.jiras:
            print(f'\tjiras ...')
            for jira in e0.jiras:
                print(f'\t\t{jira}')

        print(f'\tevents ...')
        display_groups_events(ival['events'], prefix='\t\t')

        # the final commit message(s)? ...
        if is_merged and pr is not None and pr.user.login == login:
            # The final repository commit is the merge_commit_sha ...
            message = git_cacher.get_commit_message(e0.repo.full_name, e0.pull.merge_commit_sha)
            if message is not None:
                print('\tcommit message ...')
                lines = message.split('\n')
                for line in lines:
                    if not line.strip():
                        continue
                    print('\t\t' + line.rstrip())

    print('###########################')
    print(f'PRs created: {prs_created}')
    print(f'PRs collaborated: {prs_collaborated}')
    print(f'PRs merged: {prs_merged}')


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--login', help="the github username to search for", required=True)
    parser.add_argument('--start-date', help="starting date range YYYY-MM-DD")
    parser.add_argument('--end-date', help="ending date range YYYY-MM-DD")
    args = parser.parse_args()

    token = os.environ.get('GITHUB_TOKEN')
    gc = GithubClient(token=token)

    # define the projects
    repos = [
        'dynaconf/dynaconf',
        'pulp/pulpcore',
        'pulp/pulp_ansible',
        'pulp/pulp_container',
        'pulp/oci_env',
        'ansible/ansible-hub-ui',
        'ansible/galaxy_ng',
        'ansible/galaxy-deploy',
        'ansible/galaxy-importer',
        'ansible/galaxykit',
        'ansible/aap-gateway',
        'ansible/django-ansible-base',
        'encode/django-rest-framework',
    ]

    start_date = args.start_date
    end_date = args.end_date

    if start_date is not None:
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
        start_date = start_date.replace(tzinfo=timezone.utc)
    if end_date is not None:
        end_date = datetime.strptime(end_date, "%Y-%m-%d")
        end_date = end_date.replace(tzinfo=timezone.utc)

    git_cacher = GitCacher(repo_full_names=repos)
    events = gc.find_user_events(repos, args.login, start=start_date, end=end_date)
    summarize_events(events, git_cacher=git_cacher, login=args.login)


if __name__ == "__main__":
    main()
