import json
import dbus
from webob import Request, Response, exc
import re

OK = '200 OK'
HTML = ('content-type', 'text/html')
GET = 'GET'
POST = 'POST'

TEMPLATE = """
<html>
<head>
<title>autoqueue</title>
</head>
<body>
%s
</body>
</html>
"""

LOGIN_FORM = TEMPLATE % """
<html>
    <form action="%(url)s" method="POST">
        <input type="text" name="name" />
        <input type="submit" />
    </form>
</html>
"""

bus = dbus.SessionBus()
sim = bus.get_object(
    'org.autoqueue', '/org/autoqueue/Similarity',
    follow_name_owner_changes=False)
SIMILARITY = dbus.Interface(
    sim, dbus_interface='org.autoqueue.SimilarityInterface')


def get_action(req, track):
    ACTION_URL = '<a href="%s/users/%s/%s/%s">%s</a>'
    if track['loved']:
        return ACTION_URL % (
            req.application_url, req.vars['user_id'], 'meh',
            track['id'], 'lose the &lt;3')
    if track['hated']:
        return ACTION_URL % (
            req.application_url, req.vars['user_id'], 'meh',
            track['id'], "don't h8")
    return '%s %s' % (
        ACTION_URL % (
            req.application_url, req.vars['user_id'], 'love',
            track['id'], '&lt;3'),
        ACTION_URL % (
            req.application_url, req.vars['user_id'], 'hate',
            track['id'], 'h8'))


def get_title_or_filename(track):
    if track['title']:
        return '%s - %s' % (track['artist'] or '', track['title'])
    return track['filename'].split('/')[-1]


def song_row(req, track):
    return '<tr><td>%s</td><td>%s</td></tr>' % (
        get_title_or_filename(track), get_action(req, track))


def song_table(req, array):
    return '<table>\n%s</table>' % (
        '\n'.join([song_row(req, s) for s in array]),)


def index(req, start_response):
    res = Response()
    if req.method == GET:
        res.body = LOGIN_FORM % {'url': req.url}
        return res
    if req.method == POST:
        name = req.POST['name'].strip()
        user_id = SIMILARITY.join(name)
        return exc.HTTPSeeOther(
            location=req.application_url + '/users/%s/' % user_id)


def update_statuses(track, user_info):
    track['loved'] = track['filename'] in user_info.get('loved', {})
    track['hated'] = track['filename'] in user_info.get('hated', {})


def users(req, start_response):
    res = Response()
    user_info_blob = SIMILARITY.get_user_info(req.vars['user_id'])
    user_info = json.loads(user_info_blob)
    player_info_blob = SIMILARITY.get_player_info()
    player_info = json.loads(player_info_blob)
    body = ''
    history = player_info['history']
    for track in history:
        update_statuses(track, user_info)
    body += song_table(req, history)
    now = player_info['now_playing']
    if now:
        update_statuses(now, user_info)
        body += song_table(req, [now])
    queue = player_info['queue']
    for track in queue:
        update_statuses(track, user_info)
    body += song_table(req, queue)
    body += (
        '\n<a href="%(url)s/users/%(user_id)s/loved">loved</a> '
        '<a href="%(url)s/users/%(user_id)s/hated">hated</a><br />\n' % {
            'user_id': req.vars['user_id'],
            'url': req.application_url})
    res.body = (TEMPLATE % body).encode('utf-8')
    return res


def love(req, start_response):
    user_id = req.vars['user_id']
    SIMILARITY.love(user_id, req.vars['track_id'])
    return exc.HTTPSeeOther(
        location=req.application_url + '/users/%s/' % user_id)


def hate(req, start_response):
    user_id = req.vars['user_id']
    SIMILARITY.hate(user_id, req.vars['track_id'])
    return exc.HTTPSeeOther(
        location=req.application_url + '/users/%s/' % user_id)


def meh(req, start_response):
    user_id = req.vars['user_id']
    SIMILARITY.meh(user_id, req.vars['track_id'])
    return exc.HTTPSeeOther(
        location=req.application_url + '/users/%s/' % user_id)


def loved(req, start_response):
    res = Response()
    user_info_blob = SIMILARITY.get_user_info(req.vars['user_id'])
    user_info = json.loads(user_info_blob)
    body = ''
    body += song_table(req, user_info.get('loved', {}).values())
    res.body = (TEMPLATE % body).encode('utf-8')
    return res


def hated(req, start_response):
    res = Response()
    user_info_blob = SIMILARITY.get_user_info(req.vars['user_id'])
    user_info = json.loads(user_info_blob)
    body = ''
    body += song_table(req, user_info.get('hated', {}).values())
    res.body = (TEMPLATE % body).encode('utf-8')
    return res


def requests(req, start_response):
    pass


URLS = [
    (r'^/$', index),
    (r'^/users/(?P<user_id>\d+)/?$', users),
    (r'^/users/(?P<user_id>\d+)/love/(?P<track_id>\d+)?$', love),
    (r'^/users/(?P<user_id>\d+)/hate/(?P<track_id>\d+)?$', hate),
    (r'^/users/(?P<user_id>\d+)/meh/(?P<track_id>\d+)?$', meh),
    (r'^/users/(?P<user_id>\d+)/loved/?$', loved),
    (r'^/users/(?P<user_id>\d+)/hated/?$', hated),
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
    srv = make_server('localhost', 8888, application)
    srv.serve_forever()
