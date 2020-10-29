from datetime import datetime
import json
import re
import urllib
from functools import wraps
from operator import attrgetter
import bleach

import requests
from flask import Response
from flask import render_template, flash, redirect, url_for, request, send_from_directory, Markup
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.datastructures import Headers
from werkzeug.urls import url_parse
from werkzeug.utils import secure_filename

from app import app, db, yotterconfig, cache, fscache
from app.forms import LoginForm, RegistrationForm, EmptyForm, SearchForm, ChannelForm
from app.models import User, dbChannel, dbPlaylist, ytChannel, ytPlaylist, ytVideo
from app.youtubeng import prop_mappers, logged

# FIXME deprecated
from youtube import search as yts


utcnow = datetime.utcnow

##########################
#         Config         #
##########################
config = yotterconfig.config


def _fix_thumbnail_hq(url): return url.replace('hqdefault', 'mqdefault')


if config.external_proxy:
    def ext_proxy_mapper(url):
        parsed = urllib.parse.urlparse(url)._asdict()
        parsed['url'] = url
        encoded = {key + '_encoded': urllib.parse.quote_plus(value) for (key, value) in parsed.items()}
        joined = dict(parsed, **encoded)
        return config.external_proxy.format(**joined)
    if config.proxy_images: prop_mappers['map_image_url'] = lambda url: ext_proxy_mapper(_fix_thumbnail_hq(url))
    if config.proxy_videos: prop_mappers['map_stream_url'] = ext_proxy_mapper
else:
    if config.proxy_images: prop_mappers['map_image_url'] = logged(lambda url: url_for('ytimg', url=_fix_thumbnail_hq(url)))
    else: prop_mappers['map_image_url'] = _fix_thumbnail_hq
    if config.proxy_videos: prop_mappers['map_stream_url'] = lambda url: url_for('ytstream', url=url)


class instance_data:
    total_users = 0
    active_users = 0
    max_users = 0
    registrations_allowed = False

    @classmethod
    def update(cls):
        with db.session.no_autoflush:
            q_users = db.session.query(User)
            n_users = q_users.count()
            users, now, n_active = q_users.all(), utcnow(), 0
            for u in users:
                s = (now - u.last_seen).total_seconds()
                if s < (25 * 60): n_active = n_active + 1
        cls.total_users = n_users
        cls.active_users = n_active
        cls.max_users = max(n_users, config.max_instance_users)
        cls.registrations_allowed = not config.maintenance_mode and not config.max_instance_users == 0 and n_users < config.max_instance_users
        return cls
instance_data.update()


def check_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if config.require_login and not current_user.is_authenticated: return app.login_manager.unauthorized()
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin: return redir_error(404)
        return f(*args, **kwargs)
    return decorated


##########################
#          Routes        #
##########################

@app.route('/')
@app.route('/index')
def index():
    try:
        if current_user.is_admin: return redirect(url_for('manage_admin_lists'))
    except: pass
    if current_user.is_authenticated: return redirect(url_for('ytfeed'))
    if config.require_login: return app.login_manager.unauthorized()
    if config.restricted_mode: return redirect(url_for('ytgallery'))
    return redirect(url_for('ytsearch'))


@app.route('/gallery', methods=['GET'])
def ytgallery():
    channels = get_admin_list(ytChannel, is_allowed=True)
    playlists = get_admin_list(ytPlaylist, is_allowed=True)
    return render_template('ytgallery.html', channels=channels, playlists=playlists)


@app.route('/feed', methods=['GET', 'POST'])
@login_required
def ytfeed():
    max_days = 365
    # start_time = time.time()
    videos = []
    for cid in current_user.yt_followed_channel_ids: videos.extend(ytChannel(cid).get_recent_videos(max_days=max_days))
    for pid in current_user.yt_followed_playlist_ids: videos.extend(ytPlaylist(pid).get_recent_videos(max_days=max_days))
    videos.sort(key=attrgetter('published'), reverse=True)
    # print("--- {} seconds fetching youtube feed---".format(time.time() - start_time))
    return render_template('ytfeed.html', videos=videos[:50], include_channel_header=True)


@app.route('/subscriptions', methods=['GET', 'POST'])
@login_required
def ytsubscriptions():
    form = EmptyForm()
    return render_template('ytsubscriptions.html', form=form, channels=current_user.yt_followed_channels, playlists=current_user.yt_followed_playlists)


# FIXME
@app.route('/search', methods=['GET', 'POST'])
@check_login
def ytsearch():
    form = ChannelForm()
    button_form = EmptyForm()
    query = request.args.get('q', None)
    sort = request.args.get('s', None)
    if sort != None:
        sort = int(sort)
    else:
        sort = 0

    page = request.args.get('p', None)
    if page == None:
        page = 1

    if query:
        autocorrect = 1
        filters = {"time": 0, "type": 0, "duration": 0}
        results = yts.search_by_terms(query, page, autocorrect, sort, filters)

        next_page = "/search?q={q}&s={s}&p={p}".format(q=query, s=sort, p=int(page) + 1)
        if int(page) == 1:
            prev_page = "/search?q={q}&s={s}&p={p}".format(q=query, s=sort, p=1)
        else:
            prev_page = "/search?q={q}&s={s}&p={p}".format(q=query, s=sort, p=int(page) - 1)

        for video in results['videos']:
            video['videoThumb'] = proxy_image_url(video['videoThumb'])

        for channel in results['channels']:
            channel['thumbnail'] = proxy_image_url(channel['thumbnail'])

        return render_template('ytsearch.html', form=form, btform=button_form, results=results,
                               config=config, npage=next_page,
                               ppage=prev_page)
    else:
        return render_template('ytsearch.html', form=form, results=False)


@app.route('/c/<custom>', methods=['GET'])
@check_login
def ytchannel_custom(custom):
    return _channel_page(request, ytChannel.for_urlpath(request.path))


@app.route('/user/<username>', methods=['GET'])
@check_login
def ytchannel_username(username):
    return _channel_page(request, ytChannel.for_urlpath(request.path))


@app.route('/channel/<cid>', methods=['GET'])
@check_login
def ytchannel(cid):
    return _channel_page(request, ytChannel(cid))


def _channel_page(request, ch):
    with db.session.no_autoflush:
        if (config.restricted_mode and (not current_user.is_authenticated or current_user.is_restricted) and not ch.is_allowed) or (not current_user.is_admin and ch.is_blocked):
            ch = ytChannel('NOTFOUND')._make_error('Channel not found')
        form = ChannelForm()  # TODO
        page = int(request.args.get('page', 1))
        sort = int(request.args.get('sort', 3))
        videos = ch.get_videos(page=page, sort=sort)
        next_page, prev_page = None, None
        if page < ch.num_video_pages: next_page = f'{request.path}?sort={sort}&page={page + 1}'
        if page > 1: prev_page = f'{request.path}?sort={sort}&page={page - 1}'
        return render_template('ytchannel.html', show_admin_actions=True, form=form, channel=ch, videos=videos, next_page=next_page, prev_page=prev_page)


@app.route('/playlist/<pid>', methods=['GET'])
@check_login
def ytplaylist(pid):
    return _playlist_page(request, pid)


@app.route('/playlist')
def playlist_arg():
    return _playlist_page(request, request.args.get('list', 'NOTFOUND'))


def _playlist_page(request, pid):
    pl = ytPlaylist(pid)
    ch = ytChannel(pl.cid)
    with db.session.no_autoflush:
        if (config.restricted_mode and (not current_user.is_authenticated or current_user.is_restricted) and (not pl.is_allowed or ch.is_allowed)) or ch.is_blocked:  # or pl.is_blocked:
            pl = ytPlaylist('NOTFOUND')._make_error('Playlist not found')
            ch = ytChannel('NOTFOUND')._make_error('Channel not found')


        form = ChannelForm() # TODO

        page = request.args.get('page', 1)
        videos = pl.get_videos(page=page)

        next_page, prev_page = None, None
        if page < pl.num_video_pages: next_page = f'{request.path}?page={page + 1}'
        if page > 1: prev_page = f'{request.path}?page={page - 1}'

        return render_template('ytplaylist.html', show_admin_actions=True, form=form, playlist=pl, channel=ch, videos=videos, include_channel_header=True, next_page=next_page, prev_page=prev_page)


@app.route('/_user/<what>/<action>/<id>', methods=['POST'])
@login_required
def yt_user_action(what, action, id):
    if what == 'channel':
        ids = current_user.yt_followed_channel_ids
        # objs = current_user.yt_followed_channels
        obj = ytChannel(id)
        name = obj.name
    elif what == 'playlist':
        ids = current_user.yt_followed_playlist_ids
        # objs = current_user.yt_followed_playlists
        obj = ytPlaylist(id)
        name = obj.title
    else: return redir_error(405)
    if action != 'add' and action != 'remove': return redir_error(405)
    if obj.invalid: flash(f'{what} id "{id}" is not valid', 'error')
    else:
        curr = id in ids
        wanted = action == 'add'
        if curr == wanted: flash(f'"{name}" already {"" if wanted else "not "} followed', 'error')
        else:
            if wanted:
                ids.add(id)
                flash(f'"{name} is now followed!', 'success')
            else:
                ids.remove(id)
                flash(f'"{name} is not followed anymore', 'info')
            db.session.commit()
    return redirect(request.referrer)

def get_best_urls(urls):
    '''Gets URLS in youtube format (format_id, url, height) and returns best ones for yotter'''
    best_formats = ["22", "18", "34", "35", "36", "37", "38", "43", "44", "45", "46"]
    best_urls = []
    for url in urls:
        for f in best_formats:
            if url['format_id'] == f:
                best_urls.append(url)
    return best_urls


def get_live_urls(urls):
    """Gets URLS in youtube format (format_id, url, height) and returns best ones for yotter"""
    best_formats = ["91", "92", "93", "94", "95", "96"]
    best_urls = []
    for url in urls:
        for f in best_formats:
            if url['format_id'] == f:
                best_urls.append(url)
    return best_urls


@app.route('/v/<id>', methods=['GET'])
@check_login
def ytvideo(id):
    return _video_page(request, ytVideo(id))


@app.route('/watch', methods=['GET'])
@check_login
def watch():
    vid = request.args.get('v', None)
    if not vid: return redir_error(405)
    return _video_page(request, ytVideo(vid))


def _video_page(request, video):
    ch = ytChannel(video.cid)
    # TODO check allow playlists
    if (config.restricted_mode and (not current_user.is_authenticated or current_user.is_restricted) and not ch.is_allowed) or ch.is_blocked:
        video = ytVideo('NOTFOUND')._make_error('Video not found')

    # Markup description
    description = Markup(bleach.linkify(video.description.replace("\n", "<br>")))

    return render_template('ytvideo.html', video=video, description=description, config=config, comments=[])


def markupString(string):
    string = string.replace("\n\n", "<br><br>").replace("\n", "<br>")
    string = bleach.linkify(string)
    string = string.replace("https://youtube.com/", "")
    string = string.replace("https://www.youtube.com/", "")
    string = string.replace("https://twitter.com/", "/u/")
    return Markup(string)


## PROXY videos through Yotter server to the client.
@app.route('/stream/<path:url>', methods=['GET', 'POST'])
@check_login
def ytstream(url):
    # This function proxies the video stream from GoogleVideo to the client.
    headers = Headers()
    if (url):
        s = requests.Session()
        s.verify = True
        req = s.get(url, stream=True)
        headers.add('Range', request.headers['Range'])
        headers.add('Accept-Ranges', 'bytes')
        # headers.add('Content-Length', str(int(req.headers['Content-Length']) + 1))
        headers.add('Content-Length', req.headers['Content-Length'])
        response = Response(req.iter_content(chunk_size=10 * 1024), mimetype=req.headers['Content-Type'],
                            content_type=req.headers['Content-Type'], direct_passthrough=True, headers=headers)
        # enable browser file caching with etags
        response.cache_control.public = True
        response.cache_control.max_age = int(60000)
        return response
    else:
        flash("Something went wrong loading the video... Try again.")
        return redir_error(500)


def download_file(streamable):
    with streamable as stream:
        stream.raise_for_status()
        for chunk in stream.iter_content(chunk_size=8192):
            yield chunk

# Proxy yt images through server
@fscache.memoize(timeout=86400)
@app.route('/ytimg/<path:url>')
@check_login
def ytimg(url):
    pic = requests.get(url, stream=True)
    response = Response(pic, mimetype=pic.headers['Content-Type'], direct_passthrough=True)
    # extend browser file caching with etags (ytimg uses 7200)
    response.cache_control.public = True
    response.cache_control.max_age = int(60000)
    return response


#########################
#### General Logic ######
#########################
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if not instance_data.update().registrations_allowed: return redirect(url_for('settings'))

    form = RegistrationForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash("This username is taken! Try with another.")
            return redirect(request.referrer)

        user = User(username=form.username.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Congratulations, you are now a registered user!')
        return redirect(url_for('login'))

    return render_template('register.html', title='Register', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password')
            return redirect(url_for('login'))
        if user.username == config.admin_user:
            user.set_admin_user()
        login_user(user, remember=form.remember_me.data)
        user.set_last_seen()
        db.session.commit()
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('index')
        return redirect(next_page)
    return render_template('login.html', title='Login', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/settings')
def settings():
    # if current_user.is_admin: pass
    # if not current_user.is_restricted: instance_data.update()
    return render_template('settings.html', title='Settings', config=config, data=instance_data.update())


# Export data into a JSON file. Later you can import the data.
@app.route('/settings/export', methods=['POST'])
@login_required
def export_user_data():
    # cids = current_user.yt_followed_channel_ids
    data = {'description': 'Yotter data export', 'username': current_user.username,
            'followed_channel_ids': list(current_user.yt_followed_channel_ids),
            'followed_playlist_ids': list(current_user.yt_followed_playlist_ids)}
    filename = 'yotter_data_export.json'
    try:
        with open(f'app/{filename}', 'w') as outfile:
            json.dump(data, outfile)
        return send_from_directory('.', filename, as_attachment=True)
    except: return redir_error(500)


@app.route('/settings/import', methods=['GET', 'POST'])
@login_required
def import_user_data():
    if 'file' not in request.files:  # check if the post request has the file part
        flash('No file sent')
        return redirect(url_for('settings'))
    file = request.files['file']
    if file.filename == '':  # if user does not select file, browser also submit an empty part without filename
        flash('No selected file')
        return redirect(url_for('settings'))
    content = file.read().decode()
    option = request.form['import_format']
    if option == 'yotter':
        data = json.loads(content)
        for cid in data['followed_channel_ids']: current_user.yt_followed_channel_ids.add(cid)
        for pid in data['followed_playlist_ids']: current_user.yt_followed_playlist_ids.add(pid)
    elif option == 'youtube':
        channel_data = re.findall('(UC[a-zA-Z0-9_-]{22})|(?<=user/)[a-zA-Z0-9_-]+', content)
        for cid in channel_data: current_user.yt_followed_channel_ids.add(cid)
        # TODO playlists?
    db.session.commit()
    return redirect(request.referrer)


@app.route('/settings/delete_subscriptions', methods=['POST'])
@login_required
def delete_user_subscriptions():
    # for cid in list(current_user.yt_followed_channel_ids): current_user.yt_followed_channel_ids.remove(cid)
    # print(current_user.yt_followed_channel_ids)
    current_user.yt_followed_channel_ids.clear()
    current_user.yt_followed_playlist_ids.clear()
    db.session.commit()
    return redirect(request.referrer)


@app.route('/settings/delete_user', methods=['POST'])
@login_required
def delete_user():
    user = User.query.filter_by(username=current_user.username).first()
    db.session.delete(user)
    db.session.commit()
    logout_user()
    return redirect(url_for('index'))


#########################
#         admin         #
#########################
def get_admin_list(cls, **kw):
    dbcls = dbChannel if cls==ytChannel else dbPlaylist
    return [cls(o.id) for o in dbcls.query.filter_by(**kw).all()]


@app.route('/_admin/manage_lists')
@admin_required
def manage_admin_lists():
    blocked_channels = get_admin_list(ytChannel, is_blocked=True)
    allowed_channels = get_admin_list(ytChannel, is_allowed=True)
    allowed_playlists = get_admin_list(ytPlaylist, is_allowed=True)
    return render_template('ytadmin.html', show_admin_actions=True, blocked_channels=blocked_channels, allowed_channels=allowed_channels, allowed_playlists=allowed_playlists)

@app.route('/_admin/<what>/<where>/<action>/<id>', methods=['POST'])
@admin_required
def yt_admin_action(what, where, action, id):
    if where != 'allowed' and where != 'blocked': return redir_error(405)
    opposite = 'blocked' if where == 'allowed' else 'allowed'
    if what == 'channel':
        obj = ytChannel(id)
        name = obj.name
    elif what == 'playlist':
        obj = ytPlaylist(id)
        name = obj.title
    else: return redir_error(405)
    if action != 'add' and action != 'remove': return redir_error(405)
    if obj.invalid: flash(f'{what.capitalize()} id "{id}" is not valid', 'error')
    else:
        curr = getattr(obj, f'is_{where}')
        wanted = action == 'add'
        if curr == wanted: flash(f'{what.capitalize()} "{name}" already {"" if wanted else "not "} {where}', 'error')
        else:
            setattr(obj, f'is_{where}', wanted)
            if what == 'channel' and wanted: setattr(obj, f'is_{opposite}', False)
            db.session.commit()
            if wanted: flash(f'{what.capitalize()} "{name}" is now {where}!', 'success')
            else: flash(f'{what.capitalize()} "{name}" is not {where} anymore', 'info')
    return redirect(request.referrer)


@app.route('/_admin/export_lists', methods=['POST'])
@admin_required
def export_admin_lists():
    blocked_channels = dbChannel.query.filter_by(is_blocked=True).all()
    allowed_channels = dbChannel.query.filter_by(is_allowed=True).all()
    allowed_playlists = dbPlaylist.query.filter_by(is_allowed=True).all()
    data = {'description': 'Yotter restricted mode lists export', 'server_name': config.server_name,
            'blocked_channel_ids': [ch.id for ch in blocked_channels],
            'allowed_channel_ids': [ch.id for ch in allowed_channels],
            'allowed_playlist_ids': [pl.id for pl in allowed_playlists],
            }
    filename = 'yotter_admin_export.json'
    try:
        with open(f'app/{filename}', 'w') as outfile:
            json.dump(data, outfile)
        return send_from_directory('.', filename, as_attachment=True)
    except: return redir_error(500)


@app.route('/_admin/import_lists', methods=['GET', 'POST'])
@admin_required
def import_admin_lists():
    if 'file' not in request.files:  # check if the post request has the file part
        flash('No file sent')
        return redirect(url_for('settings'))
    file = request.files['file']
    if file.filename == '':  # if user does not select file, browser also submit an empty part without filename
        flash('No selected file')
        return redirect(url_for('settings'))
    content = file.read().decode()
    data = json.loads(content)
    for cid in data['blocked_channel_ids']: ytChannel(cid).is_blocked = True
    for cid in data['allowed_channel_ids']: ytChannel(cid).is_allowed = True
    for pid in data['allowed_playlist_ids']: ytPlaylist(pid).is_allowed = True
    db.session.commit()
    flash(f"imported {len(data['blocked_channel_ids'])} blocked channels, {len(data['allowed_channel_ids'])} allowed channels, {len(data['allowed_playlist_ids'])} allowed playlists", 'success')
    return redirect(request.referrer)


@app.route('/_admin/clear_inactive_users', methods=['POST'])
@admin_required
def clear_inactive_users():
    users, toremove, now, max_delta = db.session.query(User).all(), [], utcnow(), config.max_old_user_days * 86400
    for u in users:
        if u.is_admin: continue
        delta = (now - u.last_seen).total_seconds()
        if delta > max_delta:
            flash(f'Deleted user {u.username} - inactive for {int(delta/86400)} days', 'warning')
            toremove.append(u)
    for u in toremove: db.session.delete(u)
    db.session.commit()
    return redirect(request.referrer)


@app.route('/_admin/purge_cache', methods=['POST'])
@admin_required
def purge_cache():
    fscache.clear()
    cache.clear()
    flash(f'Cache purged', 'warning')
    return redirect(request.referrer)


@app.route('/_admin/purge_db', methods=['POST'])
@admin_required
def purge_db():
    toremove = []
    channels = db.session.query(dbChannel).all()
    for ch in channels:
        if not ch.is_allowed and not ch.is_blocked and not ch.followers: toremove.append(ch)
    playlists = db.session.query(dbPlaylist).all()
    for pl in playlists:
        if not pl.is_allowed and not pl.followers: toremove.append(pl)
    for o in toremove: db.session.delete(o)
    db.session.commit()
    flash(f'Purged {len(toremove)} entries from the database', 'warning')
    return redirect(request.referrer)


@app.route('/error/<int:errno>')
def error(errno):
    return render_template('{}.html'.format(str(errno)), config=config)


def redir_error(errno):
    return redirect(url_for('error', errno=errno))
