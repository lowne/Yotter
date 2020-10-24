import requests
from requests_futures.sessions import FuturesSession
import datetime
from dateutil.parser import parse as dateparse
from humanize import naturaldelta
import functools
import operator
import math
import json
import feedparser
from app import fscache
from youtube_search import YoutubeSearch

import sys
import os
__ytl_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'youtube-local')
sys.path.append(__ytl_dir)
import youtube


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


ATTRFLAG = dict()

proxy_url_mappers = {
  'proxy_image': lambda u: u,
  'proxy_stream': lambda u: u,
}

# class decorator
def propgroups(cl):
    propnames = [prop for props in cl.__propgroups__.values() for prop in props]
    cl.__propnames__ = propnames
    if not getattr(cl, '__proxyprops__'): cl.__proxyprops__ = {}
    cl_init = cl.__init__

    @functools.wraps(cl_init)
    def init(self, *args, **kwargs):
        cl_init(self, *args)
        for k, v in kwargs.items():
            if k not in propnames: raise TypeError(f"__init__ got an unexpected keyword argument '{k}'")
            setattr(self, k, v)  # including None for uninteresting props
    cl.__init__ = init

    def store_if_absent(self, prop, val):
        if getattr(self, f'_{prop}', ATTRFLAG) is not ATTRFLAG: setattr(self, prop, val)
    cl._store_if_absent = store_if_absent


    for grp, props in cl.__propgroups__.items():
        # use a default arg to capture the value in the closure
        # https://stackoverflow.com/a/54289183

        def setcache(self, grp=grp, props=props):
            d = dict()
            for prop in props:
                ivar = f'_{prop}'
                if not hasattr(self, ivar): return
                d[prop] = getattr(self, ivar)
            getattr(self, f'_get_{grp}').set_cache(self, d)
        setattr(cl, f'_set_{grp}', setcache)

        def overridecache(self, grp=grp):
            getattr(self, f'_set_{grp}')()
            getattr(cl, f'_get_{grp}').cache_timeout = 99999999
        setattr(cl, f'_override_{grp}', overridecache)

        def delcache(self, grp=grp):
            getattr(self, f'_get_{grp}').del_cache(self)
        setattr(cl, f'_det_{grp}', delcache)

        for prop in props:
            def pget(self, grp=grp, prop=prop):
                ivar = f'_{prop}'
                if not hasattr(self, ivar):  # first access (or invalidated) - rebuild cache
                    v = getattr(self, f'_get_{grp}')()[prop]
                    setattr(self, ivar, v)
                    return v
                return getattr(self, ivar)  # return cached result, including None

            # if set to None, it'll be cached - prop is deemed irrelevant foreverafter
            # NOTE: if this changes (e.g. in config), persisted cache must be cleared
            def pset(self, v, grp=grp, prop=prop):
                setattr(self, f'_{prop}', v)
                getattr(self, f'_set_{grp}')()

            proxy_key = cl.__proxyprops__.get(prop, None)
            if proxy_key:
                def pset(self, v, grp=grp, prop=prop, proxy_key=proxy_key):
                    setattr(self, f'_{prop}', proxy_url_mappers[proxy_key](v))
                    getattr(self, f'_set_{grp}')()

            def pdel(self, grp=grp, prop=prop):  # invalidate the cache and rebuild on next access
                delattr(self, prop)
                getattr(self, f'_del_{grp}')()

            setattr(cl, prop, property(pget, pset, pdel, f'property {prop} in group {grp}'))
    return cl


BASE_URL = 'https://www.youtube.com'


def fix_ytlocal_url(url):
    return url[1:] if url.startswith('/http') else url


@propgroups
class ytVideo:
    __propgroups__ = {'oembed': ['title', 'thumbnail', 'channel_name', 'channel_url'], 'ch_id': ['cid'],
                      'page': ['published', 'updated', 'duration', 'description', 'views', 'rating'],
                      'ts_human': ['timestamp_human'],
                      'NYI': ['is_live', 'is_upcoming']}

    __proxyprops__ = {'thumbnail': 'proxy_image'}

    def __repr__(self): return f"<ytVideo {self.id}>"
    # def __hash__(self): return hash(self.id)

    def __init__(self, id):
        self.id = id

    @fscache.memoize(timeout=86400)
    def _get_oembed(self):
        with FuturesSession() as session:
            resp = session.get(f"https://www.youtube.com/oembed?format=json&url=http%3A%2F%2Fyoutu.be%2F{self.id}").result()
            info = json.loads(resp.content)
            return {'title': info['title'], 'thumbnail': info['thumbnail_url'], 'channel_name': info['author_name'], 'channel_url': info['author_url']}

    @fscache.memoize(timeout=86400 * 7)
    def _get_ch_id(self): return {'cid': youtube.channel.get_channel_id(self.channel_url)}

    @fscache.memoize(timeout=1)
    def _get_page(self): pass

    @fscache.memoize(timeout=1)
    def _get_NYI(self): pass

    @fscache.memoize(timeout=1)
    def _get_ts_human(self):
        # TODO 'Scheduled', 'LIVE'
        return {'timestamp_human': f'{naturaldelta(utcnow() - self.published)} ago'}

# def timedelta_human_str(delta):
#     if delta.days >= 7: return f"{int(delta.days/7)}w"
#     if delta.days > 0: return f"{delta.days}d"
#     elif delta.seconds >= 3600: return f"{int(delta.seconds/3600)}h"
#     else: return f"{int(delta.seconds/60)}m"


YT_CHANNEL_INVALID_DATA = {'invalid': True, 'name': '--invalid channel id--', 'url': '', 'avatar': '', 'sub_count': 0, 'view_count': 0,
                           'joined': datetime.datetime.strptime('1970-01-01', '%Y-%m-%d'), 'description': '--channel does not exist--', 'links': []}


@propgroups
class ytChannel:
    # all_videos should prolly be a method with page
    # __propgroups__ = {'from_search': ['name', 'avatar', 'sub_count', 'invalid'], 'feed': ['recent_videos'],
    #                   'about_page': ['joined', 'descrption', 'view_count', 'links'], 'NYI': ['playlists', 'all_videos']}

    __propgroups__ = {'about_page': ['invalid', 'name', 'avatar', 'sub_count', 'joined', 'descrption', 'view_count', 'links'],
                      'mf_numvids': ['num_videos', 'num_video_pages'],
                      'feed': ['recent_videos'], 'NYI': ['playlists', 'all_videos']}

    __proxyprops__ = {'avatar': 'proxy_image'}

    def __repr__(self): return f"<ytChannel {self.cid}>"
    # def __hash__(self): return hash(repr(self))

    def __init__(self, cid, user=None, custom=None):
        self.cid = cid
        if user: self.url = f'{BASE_URL}/user/{user}'
        elif custom: self.url = f'{BASE_URL}/c/{custom}'
        else: self.url = f'{BASE_URL}/channel/{cid}'

    @fscache.memoize(timeout=86400 * 7)
    def _get_from_search(self):
        # https://github.com/pluja/youtube_search-fork/blob/master/youtube_search/__init__.py#L60
        # it's just wrong...
        try: info = YoutubeSearch.channelInfo(self.cid, includeVideos=False)[0]
        except KeyError as ke:
            print("KeyError: {}: channel '{}' could not be found".format(ke, self.cid))
            info = {
                # 'id': id,
                'name': '--invalid channel id--',
                'avatar': '',
                'subCount': 'unavailable',
                'invalid': True,
            }
        return {'name': info['name'], 'avatar': info['avatar'], 'sub_count': info['subCount'], 'invalid': info.get('invalid', False)}

    @fscache.memoize(timeout=3600 * 2)
    def _get_feed(self):
        now = utcnow()
        videos = []
        with FuturesSession() as session:
            resp = session.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={self.cid}").result()
            rssFeed = feedparser.parse(resp.content)
            try: published = dateparse(rssFeed.feed.published)
            except (AttributeError, ValueError): published = now
            for entry in rssFeed.entries:
                video = ytVideo(entry.yt_videoid)
                video.title = entry.title
                video.thumbnail = entry.media_thumbnail[0]['url']
                video.channel_name = entry.author_detail.name
                video.channel_url = entry.author_detail.href
                video.cid = entry.yt_channelid
                # If youtube rss does not have parsed time, generate it. Else set time to 0.
                try: video.published = dateparse(entry.published)
                except ValueError: video.published = now
                try: video.updated = dateparse(entry.updated)
                except (AttributeError, ValueError): video.updated = now
                video.description = entry.summary_detail.value
                # video.description = re.sub(r'^https?:\/\/.*[\r\n]*', '', video.description[0:120] + "...",
                #                            flags=re.MULTILINE)
                video.views = entry.media_statistics['views']
                video.rating = int(float(entry.media_starrating['average']) / float(entry.media_starrating['max']) * 100)
                videos.append(video)
        # return {'published': published, 'recent_videos': videos}
        self._store_if_absent('joined', published)
        # if not hasattr(self, '_url') or getattr(self, '_url') is None: self.url = rssFeed.feed.author_detail.href
        self._store_if_absent('name', rssFeed.feed.author_detail.name)
        return {'recent_videos': videos}

    @fscache.memoize(timeout=1)
    def _get_about_page(self):
        polymer = youtube.channel.get_channel_tab(self.cid, tab='about', print_status=False)
        info = youtube.yt_data_extract.extract_channel_info(json.loads(polymer), 'about')

        if info['error'] == 'This channel does not exist': return YT_CHANNEL_INVALID_DATA
        elif info['error'] is not None: raise RuntimeError(info['error'])

        # links is a list of tuples (text, url)
        joined = datetime.datetime.strptime(info['date_joined'], '%Y-%m-%d')

        # TODO check avatar url
        return {'invalid': False, 'name': info['channel_name'], 'avatar': info['avatar'],
                'sub_count': info['approx_subscriber_count'], 'joined': joined,
                'description': info['description'], 'view_count': info['view_count'], 'links': info['links']}

    @fscache.memoize(timeout=60 * 30)
    def _get_mf_numvids(self):
        numvids = youtube.channel.get_number_of_videos_channel(self.cid)
        return {'num_videos': numvids, 'num_video_pages': math.ceil(numvids / 30)}

    def get_videos(self, page=1, sort=3):
        view = 1 # not sure what this this
        polymer = youtube.channel.get_channel_tab(self.cid, page, sort, 'videos', view)
        info = youtube.yt_data_extract.extract_channel_info(json.loads(polymer), 'videos')

        if info['error'] is not None: raise RuntimeError(info['error'])

        print(json.dumps(info, indent=2))
        videos = []

        for item in info['items']:
            if item['type'] == 'video':
                video = ytVideo(item['id'])
                video.title = item['title']
                video.thumbnail = item['thumbnail']
                video.channel_name = info['channel_name']
                video.channel_url = info['channel_url']
                video.cid = self.cid
                video.timestamp_human = item['time_published']
                video._override_ts_human() # we can never call .timestamp_human again as the video lacks a .published
                video.views = item['view_count']
                video.duration = item['duration'] #TODO live
                videos.append(video)
        return videos



    def get_recent_videos(self, max_n=999, max_days=30):
        videos = []
        now = utcnow()
        for v in self.recent_videos:  # relies on recent_videos (and, in turn, youtube's rss feed) to be property sorted
            if (now - v.published).days > max_days: break
            if len(videos) >= max_n: break
            videos.append(v)
        return videos


def get_channel(url):
    cid = get_cid(url)
    if cid is not None: return ytChannel(cid)
    ch = ytChannel('NOTFOUND')
    for k, v in YT_CHANNEL_INVALID_DATA.items(): setattr(ch, k, v)
    return ch


@fscache.memoize(timeout=86400 * 7)
def get_cid(url): return youtube.channel.get_channel_id(url)


def get_recent_videos(cids, max_per_channel=99, max_days=9999):
    videos = []
    for cid in cids: videos.extend(ytChannel(cid).get_recent_videos(max_n=max_per_channel, max_days=max_days))
    videos.sort(key=operator.attrgetter('published'), reverse=True)
    return videos
