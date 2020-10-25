import datetime
import json
import re
import time
import urllib
from concurrent.futures import as_completed

import bleach
import feedparser
import requests
from flask import Response
from flask import render_template, flash, redirect, url_for, request, send_from_directory, Markup
from flask_login import login_user, logout_user, current_user, login_required
from requests_futures.sessions import FuturesSession
from werkzeug.datastructures import Headers
from werkzeug.urls import url_parse
from werkzeug.utils import secure_filename
from youtube_search import YoutubeSearch

from app import app, db, yotterconfig, cache, fscache
from app.forms import LoginForm, RegistrationForm, EmptyForm, SearchForm, ChannelForm
from app.models import User, ytChannel, ytVideo
from youtube import comments, channel as ytch, search as yts
from youtube import watch as ytwatch
from youtube import yt_data_extract
from youtube.channel import post_process_channel_info

from app.youtubeng import get_recent_videos, proxy_url_mappers, get_channel_for_urlpath




#########################################

#########################################

##########################
#### Config variables ####
##########################
config = yotterconfig.get_config()
def _fix_thumbnail_hq(url): return url.replace('hqdefault', 'mqdefault')


if config.external_proxy:
    def ext_proxy_mapper(url):
        parsed = urllib.parse.urlparse(url)._asdict()
        parsed['url'] = url
        encoded = {key + '_encoded': urllib.parse.quote_plus(value) for (key, value) in parsed.items()}
        joined = dict(parsed, **encoded)
        return config.external_proxy.format(**joined)
    if config.proxy_images: proxy_url_mappers['proxy_image'] = lambda url: ext_proxy_mapper(_fix_thumbnail_hq(url))
    if config.proxy_videos: proxy_url_mappers['proxy_stream'] = ext_proxy_mapper
else:
    if config.proxy_images: proxy_url_mappers['proxy_image'] = lambda url: url_for('ytimg', url=_fix_thumbnail_hq(url))
    if config.proxy_videos: proxy_url_mappers['proxy_stream'] = lambda url: url_for('stream', url=url)



##########################
#### Global variables ####
##########################

@app.route('/')
@app.route('/index')
@login_required
@cache.cached(timeout=50, key_prefix='home')
def index():
    return render_template('home.html', config=config)


#########################
#### Youtube Logic ######
#########################
@app.route('/youtube', methods=['GET', 'POST'])
@login_required
def youtube():
    followCount = len(current_user.yt_followed_channels)
    start_time = time.time()
    cids = current_user.yt_followed_cids
    videos = get_recent_videos(cids, max_days = 30, max_per_channel = 10)
    print("--- {} seconds fetching youtube feed---".format(time.time() - start_time))
    return render_template('youtube.html', title="Yotter | Youtube", videos=videos, followCount=followCount,
                           config=config)


@app.route('/ytfollowing', methods=['GET', 'POST'])
@login_required
def ytfollowing():
    form = EmptyForm()
    channels = current_user.yt_followed_channels
    count = len(channels)
    return render_template('ytfollowing.html', form=form, channels=channels, count=count, config=config)


@app.route('/ytsearch', methods=['GET', 'POST'])
@login_required
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

        next_page = "/ytsearch?q={q}&s={s}&p={p}".format(q=query, s=sort, p=int(page) + 1)
        if int(page) == 1:
            prev_page = "/ytsearch?q={q}&s={s}&p={p}".format(q=query, s=sort, p=1)
        else:
            prev_page = "/ytsearch?q={q}&s={s}&p={p}".format(q=query, s=sort, p=int(page) - 1)

        for video in results['videos']:
            video['videoThumb'] = proxy_image_url(video['videoThumb'])

        for channel in results['channels']:
            channel['thumbnail'] = proxy_image_url(channel['thumbnail'])

        return render_template('ytsearch.html', form=form, btform=button_form, results=results,
                               config=config, npage=next_page,
                               ppage=prev_page)
    else:
        return render_template('ytsearch.html', form=form, results=False)


@app.route('/ytfollow/<channelId>', methods=['POST'])
@login_required
def ytfollow(channelId):
    followYoutubeChannel(channelId)
    return redirect(request.referrer)


def followYoutubeChannel(channelId):
    chan = ytChannel(cid=channelId)
    if chan in current_user.yt_followed_channels: # already followed
        flash(f'Already following "{chan.name}"', 'error')
        return False
    if chan.invalid:
        flash(f'Channel id "{channelId}" is not valid', 'error')
        return False
    current_user.yt_followed_channels.add(chan)
    db.session.commit()
    flash(f'"{chan.name}" followed!', 'success')
    return True


@app.route('/ytunfollow/<channelId>', methods=['POST'])
@login_required
def ytunfollow(channelId):
    unfollowYoutubeChannel(channelId)
    return redirect(request.referrer)


def unfollowYoutubeChannel(channelId):
    chan = ytChannel(cid=channelId)
    if chan not in current_user.yt_followed_channels:  # already unfollowed
        flash(f'Already not following "{chan.name}"', 'error')
        return False
    current_user.yt_followed_channels.remove(chan)
    db.session.commit()
    if chan.invalid:
        flash(f'Channel id "{channelId}" is not valid', 'error')
        return False
    flash(f'"{chan.name}" unfollowed', 'info')
    return True


@app.route('/c/<id>', methods=['GET'])
@login_required
def channel_custom(id):
    return _channel_page(request, get_channel_for_urlpath(request.path))


@app.route('/user/<id>', methods=['GET'])
@login_required
def channel_username(id):
    return _channel_page(request, get_channel_for_urlpath(request.path))


@app.route('/channel/<id>', methods=['GET'])
@login_required
def channel(id):
    return _channel_page(request, ytChannel(id))


def _channel_page(request, ch):
    form = ChannelForm()
    button_form = EmptyForm()

    page = request.args.get('page', None) or 1
    sort = request.args.get('sort', None) or 3

    videos = ch.get_videos(page=page, sort=sort)

    next_page, prev_page = None, None
    if page < ch.num_video_pages: next_page = f'{request.path}?sort={sort}&page={page + 1}'
    if page > 1: prev_page = f'{request.path}?sort={sort}&page={page - 1}'
    print(ch.num_video_pages)
    print(next_page)
    print(prev_page)

    return render_template('channel.html', form=form, btform=button_form, channel=ch, videos=videos,
                           config=config, next_page=next_page, prev_page=prev_page)


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
@login_required
def v_id(id):
    return _video_page(request, ytVideo(id))

@app.route('/watch', methods=['GET'])
@login_required
def watch():
    vid = request.args.get('v', None)
    if not vid: return redirect(url_for('error/405'))
    return _video_page(request, ytVideo(vid))


def _video_page(request, video):
    # Markup description
    description = Markup(bleach.linkify(video.description.replace("\n", "<br>")))

    return render_template("video.html", video=video, description=description, config=config, comments=[])


def markupString(string):
    string = string.replace("\n\n", "<br><br>").replace("\n", "<br>")
    string = bleach.linkify(string)
    string = string.replace("https://youtube.com/", "")
    string = string.replace("https://www.youtube.com/", "")
    string = string.replace("https://twitter.com/", "/u/")
    return Markup(string)


## PROXY videos through Yotter server to the client.
@app.route('/stream/<path:url>', methods=['GET', 'POST'])
@login_required
def stream(url):
    # This function proxies the video stream from GoogleVideo to the client.
    headers = Headers()
    if (url):
        s = requests.Session()
        s.verify = True
        req = s.get(url, stream=True)
        headers.add('Range', request.headers['Range'])
        headers.add('Accept-Ranges', 'bytes')
        headers.add('Content-Length', str(int(req.headers['Content-Length']) + 1))
        response = Response(req.iter_content(chunk_size=10 * 1024), mimetype=req.headers['Content-Type'],
                            content_type=req.headers['Content-Type'], direct_passthrough=True, headers=headers)
        # enable browser file caching with etags
        response.cache_control.public = True
        response.cache_control.max_age = int(60000)
        return response
    else:
        flash("Something went wrong loading the video... Try again.")
        return redirect(url_for('youtube'))


def download_file(streamable):
    with streamable as stream:
        stream.raise_for_status()
        for chunk in stream.iter_content(chunk_size=8192):
            yield chunk

# Proxy yt images through server
@fscache.memoize(timeout=3600)
@app.route('/ytimg/<path:url>')
@login_required
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
        if user.username == config['admin_user']:
            user.set_admin_user()
            db.session.commit()
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or url_parse(next_page).netloc != '':
            next_page = url_for('index')
        return redirect(next_page)
    return render_template('login.html', title='Sign In', form=form, config=config)


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/settings')
@login_required
@cache.cached(timeout=50, key_prefix='settings')
def settings():
    active = 0
    users = db.session.query(User).all()
    for u in users:
        if u.last_seen == None:
            u.set_last_seen()
            db.session.commit()
        else:
            t = datetime.datetime.utcnow() - u.last_seen
            s = t.total_seconds()
            m = s / 60
            if m < 25:
                active = active + 1

    instanceInfo = {
        "totalUsers": db.session.query(User).count(),
        "active": active,
    }
    return render_template('settings.html', info=instanceInfo, config=config, admin=current_user.is_admin)


'''@app.route('/clear_inactive_users/<phash>')
@login_required
def clear_inactive_users(phash):
    ahash = User.query.filter_by(username=config['admin_user']).first().password_hash
    if phash == ahash:
        users = db.session.query(User).all()
        for u in users:
            if u.username == config['admin_user']:
                continue
            t = datetime.datetime.utcnow() - u.last_seen
            t = math.floor(t.total_seconds())
            max_old_s = config['max_old_user_days']*86400
            if t > max_old_s:
                user = User.query.filter_by(username=u.username).first()
                print("deleted "+u.username)
                db.session.delete(user)
                db.session.commit()
    else:
        flash("You must be admin for this action")
    return redirect(request.referrer)'''


@app.route('/export')
@login_required
# Export data into a JSON file. Later you can import the data.
def export():
    a = exportData()
    if a:
        return send_from_directory('.', 'data_export.json', as_attachment=True)
    else:
        return redirect(url_for('error/405'))


def exportData():
    cids = current_user.yt_followed_channels
    data = {'username': current_user.username, 'description': 'list of followed YouTube channels'}
    data['youtube'] = []

    for cid in cids:
        data.append({
            'channelId': cid
        })

    try:
        with open('app/data_export.json', 'w') as outfile:
            json.dump(data, outfile)
        return True
    except:
        return False


@app.route('/importdata', methods=['GET', 'POST'])
@login_required
def importdata():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.referrer)
        file = request.files['file']
        # if user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file')
            return redirect(request.referrer)
        else:
            option = request.form['import_format']
            if option == 'yotter':
                importYotterSubscriptions(file)
            elif option == 'youtube':
                importYoutubeSubscriptions(file)
            return redirect(request.referrer)

    return redirect(request.referrer)


@app.route('/deleteme', methods=['GET', 'POST'])
@login_required
def deleteme():
    user = User.query.filter_by(username=current_user.username).first()
    db.session.delete(user)
    db.session.commit()
    logout_user()
    return redirect(url_for('index'))


def importYoutubeSubscriptions(file):
    filename = secure_filename(file.filename)
    try:
        data = re.findall('(UC[a-zA-Z0-9_-]{22})|(?<=user/)[a-zA-Z0-9_-]+', file.read().decode('utf-8'))
        for acc in data:
            r = followYoutubeChannel(acc)
    except Exception as e:
        print(e)
        flash("File is not valid.")


def importYotterSubscriptions(file):
    filename = secure_filename(file.filename)
    data = json.load(file)

    for acc in data['youtube']:
        r = followYoutubeChannel(acc['channelId'])


def registrations_allowed():
    if config.maintenance_mode: return False
    if config.max_instance_users == 0: return False
    if db.session.query(User).count() >= config.max_instance_users: return False
    return True


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

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

    return render_template('register.html', title='Register', registrations=registrations_allowed(), form=form, config=config)


@app.route('/status')
def status():
    count = db.session.query(User).count()
    registrations = registrations_allowed()
    # img = url_for('static', filename='img/' + ('open' if registrations else 'close') +'.png')
    return render_template('status.html', title='STATUS', count=count, max=max(count, config.max_instance_users), registrations=registrations)

@app.route('/error/<errno>')
def error(errno):
    return render_template('{}.html'.format(str(errno)), config=config)


def getTimeDiff(t):
    diff = datetime.datetime.now() - datetime.datetime(*t[:6])

    if diff.days == 0:
        if diff.seconds > 3599:
            timeString = "{}h".format(int((diff.seconds / 60) / 60))
        else:
            timeString = "{}m".format(int(diff.seconds / 60))
    else:
        timeString = "{}d".format(diff.days)
    return timeString


