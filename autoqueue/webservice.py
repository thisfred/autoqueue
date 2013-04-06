"""Autoqueue similarity service.

Copyright 2013 Eric Casteleijn <thisfred@gmail.com>,

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2, or (at your option)
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301  USA.
"""
import json
import dbus
import subprocess
from webob import Request, Response, exc
from urllib2 import quote, unquote
import re

OK = '200 OK'
HTML = ('content-type', 'text/html')
GET = 'GET'
POST = 'POST'

TEMPLATE = """
<html>
<head>
<title>autoqueue web frontend - party like it's 1992</title>
</head>
<body>
%s
</body>
</html>
"""

LOGIN_FORM = TEMPLATE % """
<form action="%(url)s" method="POST">
    <input type="text" name="name" /><br />
    <input type="submit" value="log in" />
</form>
"""

LOGOUT_FORM = TEMPLATE % """
<form action="%(url)s" method="POST">
    <input type="submit" value="log out" />
</form>
"""

SEARCH_FORM = """
<br /><br /><strong>search</strong><br /><br />
<form action="%(url)s" method="POST">
    artist: <input type="text" name="query_artist" />
    and/or title: <input type="text" name="query_title" /><br />
    <input type="submit" value="search"/>
</form>
"""

ACTION_BUTTON = """
<form action="%(url)s" method="POST">
    <input type="submit" value="%(name)s"/>
</form>
"""

ACTION_URL = '%s/users/%s/%s/%s'

ACTION_ROW = (
    '<tr><td>%(before_action)s</td><td>%(title_or_filename)s</td>'
    '<td>%(after_action)s</td></tr>')

bus = dbus.SessionBus()
sim = bus.get_object(
    'org.autoqueue', '/org/autoqueue/Similarity',
    follow_name_owner_changes=False)
SIMILARITY = dbus.Interface(
    sim, dbus_interface='org.autoqueue.SimilarityInterface')


def get_song_row(req, track):
    if 'id' in track:
        # history + now playing
        if track['loved']:
            after_url = ACTION_URL % (
                req.application_url, req.vars['user_id'], 'meh', track['id'])
            before_action = ''
            after_action = ACTION_BUTTON % {
                'url': after_url, 'name': 'stop &lt;3ing'}
        elif track['hated']:
            before_url = ACTION_URL % (
                req.application_url, req.vars['user_id'], 'meh', track['id'])
            before_action = ACTION_BUTTON % {
                'url': before_url, 'name': "don't h8"}
            after_action = ''
        else:
            before_url = ACTION_URL % (
                req.application_url, req.vars['user_id'], 'hate', track['id'])
            before_action = ACTION_BUTTON % {
                'url': before_url, 'name': 'h8'}
            after_url = ACTION_URL % (
                req.application_url, req.vars['user_id'], 'love', track['id'])
            after_action = ACTION_BUTTON % {
                'url': after_url, 'name': '&lt;3'}
    else:
        # search results
        before_action = ''
        after_url = ACTION_URL % (
            req.application_url, req.vars['user_id'], 'request',
            quote(track['filename'].encode('utf-8'), safe=''))
        after_action = ACTION_BUTTON % {'url': after_url, 'name': 'request'}
    try:
        return (ACTION_ROW % {
            'title_or_filename': get_title_or_filename(track),
            'before_action': before_action,
            'after_action': after_action}).encode('utf-8')
    except UnicodeDecodeError:
        return ''


def get_title_or_filename(track):
    if track.get('title'):
        if track['artist']:
            return '<a href="http://last.fm/music/%s">%s</a> - %s' % (
                quote(track['artist'].encode('utf-8')), track['artist'] or '',
                track['title'])
    return track['filename'].split('/')[-1]


def song_table(req, array):
    return '<table>\n%s</table>' % (
        '\n'.join([get_song_row(req, s) for s in array]),)


def index(req, start_response):
    res = Response()
    if req.method == GET:
        res.body = LOGIN_FORM % {'url': req.url}
        return res
    if req.method == POST:
        name = req.params.get('name', '').strip()
        user_id = SIMILARITY.join(name)
        return exc.HTTPSeeOther(
            location=req.application_url + '/users/%s/' % user_id)


def update_statuses(track, user_info):
    track['loved'] = track['filename'] in user_info.get('loved', {})
    track['hated'] = track['filename'] in user_info.get('hated', {})
    return track


def users(req, start_response):
    res = Response()
    user_info_blob = SIMILARITY.get_user_info(int(req.vars['user_id']))
    user_info = json.loads(user_info_blob)
    player_info_blob = SIMILARITY.get_player_info()
    player_info = json.loads(player_info_blob)
    body = ''
    history = player_info['history']
    for track in history:
        update_statuses(track, user_info)
    now = player_info['now_playing']
    if now:
        update_statuses(now, user_info)
        now = [now]
    else:
        now = []
    body += song_table(req, history + now)
    body += SEARCH_FORM % {'url': req.url + 'search/'}
    if player_info.get('requests'):
        body += '<br /><br /><strong>requests</strong><br /><br />'
        body += '<br />'.join(
            ['%s' % (filename.encode('utf-8'),) for filename in
             player_info['requests']])

    body += '<br /><br />'
    body += LOGOUT_FORM % {'url': req.url + 'leave/'}
    res.body = (TEMPLATE % body)
    return res


def leave(req, start_response):
    user_id = req.vars['user_id']
    SIMILARITY.leave(int(user_id))
    return exc.HTTPSeeOther(location=req.application_url)


def love(req, start_response):
    user_id = req.vars['user_id']
    SIMILARITY.love(int(user_id), int(req.vars['track_id']))
    return exc.HTTPSeeOther(
        location=req.application_url + '/users/%s/' % user_id)


def hate(req, start_response):
    user_id = req.vars['user_id']
    SIMILARITY.hate(int(user_id), int(req.vars['track_id']))
    return exc.HTTPSeeOther(
        location=req.application_url + '/users/%s/' % user_id)


def meh(req, start_response):
    user_id = req.vars['user_id']
    SIMILARITY.meh(int(user_id), int(req.vars['track_id']))
    return exc.HTTPSeeOther(
        location=req.application_url + '/users/%s/' % user_id)


def request(req, start_response):
    user_id = req.vars['user_id']
    SIMILARITY.add_request(int(user_id), unquote(req.vars['filename']))
    return exc.HTTPSeeOther(
        location=req.application_url + '/users/%s/' % user_id)


def loved(req, start_response):
    res = Response()
    user_info_blob = SIMILARITY.get_user_info(int(req.vars['user_id']))
    user_info = json.loads(user_info_blob)
    body = ''
    body += song_table(req, user_info.get('loved', {}).values())
    res.body = (TEMPLATE % body).encode('utf-8')
    return res


def hated(req, start_response):
    res = Response()
    user_info_blob = SIMILARITY.get_user_info(int(req.vars['user_id']))
    user_info = json.loads(user_info_blob)
    body = ''
    body += song_table(req, user_info.get('hated', {}).values())
    res.body = (TEMPLATE % body).encode('utf-8')
    return res


def search(req, start_response):
    artist = req.params.get('query_artist', '').strip()
    title = req.params.get('query_title', '').strip()
    if artist and title:
        query = '&(artist=%s, title=%s)' % (artist, title)
    elif artist:
        query = 'artist=%s' % (artist,)
    else:
        query = 'title=%s' % (title,)

    res = Response()
    user_info_blob = SIMILARITY.get_user_info(int(req.vars['user_id']))
    user_info = json.loads(user_info_blob)
    cmd = subprocess.Popen(
        ['quodlibet', '--print-query=%s' % (query,)], stdout=subprocess.PIPE,
        bufsize=-1)
    filenames = cmd.communicate()[0].split('\n')
    tracks = [
        update_statuses({'filename': f}, user_info) for f in filenames if f]
    body = ''
    body += song_table(req, tracks)
    res.body = (TEMPLATE % body).encode('utf-8')
    return res


def requests(req, start_response):
    pass


URLS = [
    (r'^/$', index),
    (r'^/users/(?P<user_id>\d+)/?$', users),
    (r'^/users/(?P<user_id>\d+)/leave/?$', users),
    (r'^/users/(?P<user_id>\d+)/love/(?P<track_id>\d+)/?$', love),
    (r'^/users/(?P<user_id>\d+)/hate/(?P<track_id>\d+)/?$', hate),
    (r'^/users/(?P<user_id>\d+)/meh/(?P<track_id>\d+)/?$', meh),
    (r'^/users/(?P<user_id>\d+)/request/(?P<filename>.*)/?$', request),
    (r'^/users/(?P<user_id>\d+)/loved/?$', loved),
    (r'^/users/(?P<user_id>\d+)/hated/?$', hated),
    (r'^/users/(?P<user_id>\d+)/search/?$', search),
    (r'^/users/(?P<user_id>\d+)/requests/?$', requests)]


def application(environ, start_response):
    req = Request(environ)
    path = req.path_info
    try:
        for regex, handler in URLS:
            match = re.search(regex, path)
            if match is not None:
                req.vars = match.groupdict()
                resp = handler(req, start_response)
                break
        else:
            raise exc.HTTPNotFound('%s not found' % path)
    except exc.HTTPException, e:
        resp = e
    return resp(environ, start_response)


if __name__ == '__main__':
    from wsgiref.simple_server import make_server
    srv = make_server('10.0.0.2', 8888, application)
    srv.serve_forever()
