#!/usr/bin/env python

import argparse
import os
import re
from datetime import datetime
from datetime import timezone

import requests
import requests_cache

from github import Auth
from github import Github
from github import Consts
from github.Requester import Requester

from logzero import logger


requests_cache.install_cache('/tmp/demo_cache')


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


class UserEvent:

    _jiras = None

    def __init__(self, login=None, repo=None, issue=None, event_name=None, timestamp=None):
        self.login = login
        self.repo = repo
        self.issue = issue
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
        try:
            rr = func(url, headers=headers)
        except Exception as e:
            import epdb; epdb.st()
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
        if repo is None:
            import epdb; epdb.st()
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
            except:
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

            if match.user.login == login:
                #events.append((match.created_at, 'opened', grepo, match, match.title))
                ev = UserEvent(timestamp=match.created_at, event_name='opened', repo=grepo, issue=match)
                events.append(ev)

                if match.state == 'closed':
                    #events.append((match.closed_at, 'closed', grepo, match, match.title))
                    ev = UserEvent(timestamp=match.closed_at, event_name='closed', repo=grepo, issue=match)
                    events.append(ev)

            for comment in match.get_comments():
                if comment.user.login == login:
                    #events.append((comment.created_at, 'commented', grepo, match, match.title))
                    ev = UserEvent(timestamp=comment.created_at, event_name='commented', repo=grepo, issue=match)
                    events.append(ev)

            if match.pull_request:
                pr = grepo.get_pull(match.number)

                for review_comment in pr.get_review_comments():
                    if review_comment.user.login == login:
                        #events.append((review_comment.created_at, 'review_commented', grepo, match, match.title))
                        ev = UserEvent(timestamp=review_comment.created_at, event_name='review_commented', repo=grepo, issue=match)
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
                    ev = UserEvent(timestamp=ts, event_name='committed', repo=grepo, issue=match)
                    events.append(ev)

        events = sorted(events, key=lambda x: x.timestamp)
        if start:
            events = [x for x in events if x.timestamp >= start]
        if end:
            events = [x for x in events if x.timestamp <= end]

        return events


def summarize_events(events):
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

    for idk,skey in enumerate(sorted_keys):
        # repo/number [start] -> [end] 
        #   title ...
        #   jiras ...
        ival = imap[skey]

        e0 = ival['events'][0]
        issue = e0.issue

        start = ival["start"].isoformat().split('T')[0]
        finish = ival["stop"].isoformat().split('T')[0]

        print('-' * 100)
        print(f'{idk+1}. {issue.html_url} {start} -> {finish}')
        print(f'\t{issue.title}')
        if e0.jiras:
            print(f'\tjiras ...')
            for jira in e0.jiras:
                print(f'\t\t{jira}')

        print(f'\tevents ...')
        for event in ival['events']:
            print(f'\t\t{event.ts} {event.event_name}')


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

    events = gc.find_user_events(repos, args.login, start=start_date, end=end_date)
    summarize_events(events)


if __name__ == "__main__":
    main()
