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
from youtube import comments, utils, channel as ytch, search as yts
from youtube import watch as ytwatch

from app.youtubeng import get_recent_videos


#########################################

#########################################

##########################
#### Config variables ####
##########################
config = yotterconfig.get_config()

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
    videos = get_recent_videos(cids, max_days = 5, max_per_channel = 10)
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

@app.route('/channel/<id>', methods=['GET'])
@app.route('/user/<id>', methods=['GET'])
@app.route('/c/<id>', methods=['GET'])
@login_required
def channel(id):
    form = ChannelForm()
    button_form = EmptyForm()

    page = request.args.get('p', None)
    sort = request.args.get('s', None)
    if page is None:
        page = 1
    if sort is None:
        sort = 3

    data = ytch.get_channel_tab_info(id, page, sort)

    for video in data['items']:
        video['thumbnail'] = proxy_image_url(video['thumbnail'])

    data['avatar'] = proxy_image_url(data['avatar'])

    next_page = "/channel/{q}?s={s}&p={p}".format(q=id, s=sort, p=int(page) + 1)
    if int(page) == 1:
        prev_page = "/channel/{q}?s={s}&p={p}".format(q=id, s=sort, p=1)
    else:
        prev_page = "/channel/{q}?s={s}&p={p}".format(q=id, s=sort, p=int(page) - 1)

    return render_template('channel.html', form=form, btform=button_form, data=data,
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


@app.route('/watch', methods=['GET'])
@login_required
def watch():
    id = request.args.get('v', None)
    info = ytwatch.extract_info(id, False, playlist_id=None, index=None)

    vsources = ytwatch.get_video_sources(info, False)
    # Retry 3 times if no sources are available.
    retry = 3
    while retry != 0 and len(vsources) == 0:
        vsources = ytwatch.get_video_sources(info, False)
        retry -= 1

    for source in vsources:
        source['src'] = proxy_video_source_url(source['src'])

    # Parse video formats
    for v_format in info['formats']:
        v_format['url'] = proxy_video_source_url(v_format['url'])
        if v_format['audio_bitrate'] is not None and v_format['vcodec'] is None:
            v_format['audio_valid'] = True

    captions = ytwatch.get_subtitle_sources(info)
    for caption in captions:
        caption['src'] = proxy_image_url(caption['src'])

    # Markup description
    try:
        info['description'] = Markup(bleach.linkify(info['description'].replace("\n", "<br>")))
    except AttributeError or TypeError:
        print(info['description'])

    # Get comments
    videocomments = comments.video_comments(id, sort=0, offset=0, lc='', secret_key='')
    videocomments = utils.post_process_comments_info(videocomments)
    if videocomments is not None:
        videocomments.sort(key=lambda x: x['likes'], reverse=True)
        for cmnt in videocomments:
            cmnt['thumbnail'] = proxy_image_url(cmnt['thumbnail'])

    # Calculate rating %
    if info['like_count']+info['dislike_count']>0:
        info['rating'] = str((info['like_count'] / (info['like_count'] + info['dislike_count'])) * 100)[0:4]
    else:
        info['rating'] = 50.0
    return render_template("video.html", info=info, title='{}'.format(info['title']), config=config,
                           videocomments=videocomments, vsources=vsources, captions=captions)


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


def proxy_url(url, endpoint, proxy_cond):
    if not proxy_cond:
        return url
    if config.external_proxy:
        parsed = urllib.parse.urlparse(url)._asdict()
        parsed['url'] = url
        encoded = {key + '_encoded': urllib.parse.quote_plus(value) for (key, value) in parsed.items()}
        joined = dict(parsed, **encoded)
        return config.external_proxy.format(**joined)
    return url_for(endpoint, url=url)

def proxy_video_source_url(url):
    return proxy_url(url, 'stream', config.proxy_videos)

def proxy_image_url(url):
    return proxy_url(url, 'ytimg', config.proxy_images).replace('hqdefault', 'mqdefault')

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


