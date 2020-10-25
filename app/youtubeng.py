import requests
from requests_futures.sessions import FuturesSession
import datetime
from dateutil.parser import parse as dateparse
from humanize import naturaldelta, intword
from functools import wraps
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

    @wraps(cl_init)
    def init(self, *args, **kwargs):
        cl_init(self, *args)
        for k, v in kwargs.items():
            if k not in propnames: raise TypeError(f"__init__ got an unexpected keyword argument '{k}'")
            setattr(self, k, v)  # including None for uninteresting props
    cl.__init__ = init

    def store_if_absent(self, prop, val):
        if getattr(self, f'_{prop}', ATTRFLAG) is not ATTRFLAG: setattr(self, prop, val)
    cl._store_if_absent = store_if_absent

    def return_error(self, grp, error):
        resp, attrs, grpkeys = {}, {}, self.__propgroups__.get(grp, [])
        for k, v in self.__invalid_data__.items():
            if v == '__error__': v = error
            if k in grpkeys: resp[k] = v
            else: attrs[k] = v
        for k, v in attrs.items(): setattr(self, k, v)
        return resp
    cl._return_error = return_error

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
        setattr(cl, f'_del_{grp}', delcache)

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
    __propgroups__ = {'oembed': ['invalid', 'title', 'thumbnail', 'channel_name', 'channel_url'], 'ch_id': ['cid'],
                      'page': ['published', 'duration', 'is_live', 'description', 'view_count', 'rating', 'rating_count', 'tags', 'related_videos', 'av_sources', 'audio_sources', 'caption_sources'],
                      'from_lists': ['badges'],
                      'ts_human': ['timestamp_human'],
                      'NYI': ['is_upcoming']}

    __proxyprops__ = {'thumbnail': 'proxy_image'}

    __invalid_data__ = {'invalid': True, 'title': '__error__', 'thumbnail': '', 'channel_name': '', 'channel_url': '', 'cid': 'NOTFOUND',
                        'published': datetime.datetime.strptime('1970-01-01', '%Y-%m-%d'), 'duration': '--', 'is_live': False, 'description': 'Invalid video ID',
                        'view_count': 0, 'rating': 0, 'rating_count': 0, 'tags': [], 'related_videos': [], 'av_sources': [], 'audio_sources': [], 'caption_sources': [],
                        'badges': [], 'timestamp_human': 'never'}

    def __repr__(self): return f"<ytVideo {self.id}>"
    # def __hash__(self): return hash(self.id)

    def __init__(self, id):
        self.id = id

    @fscache.memoize(timeout=86400)
    def _get_oembed(self):
        with FuturesSession() as session:
            resp = session.get(f"https://www.youtube.com/oembed?format=json&url=http%3A%2F%2Fyoutu.be%2F{self.id}").result()
            if resp.status_code != 200: return self._return_error('oembed', resp.text)
            info = json.loads(resp.content)
            return {'invalid': False, 'title': info['title'], 'thumbnail': info['thumbnail_url'], 'channel_name': info['author_name'], 'channel_url': info['author_url']}

    @fscache.memoize(timeout=86400 * 7)
    def _get_ch_id(self): return {'cid': youtube.channel.get_channel_id(self.channel_url)}

    @fscache.memoize(timeout=3600 * 2)
    def _get_page(self):
        info = youtube.watch.extract_info(self.id, False, playlist_id=None, index=None)

        print(json.dumps(info,indent=2))
        # with open('samples/yt-local.watch.extract_info.json','w') as f:
        #     f.write(json.dumps(info, indent=2))

        error = info['playability_error'] or info['error']
        if error: return self._return_error('page', error)

        def make_video_source(fmt):
            return {
                'src': proxy_url_mappers['proxy_stream'](fmt['url']),
                'type': f"video/{fmt['ext']}",
                'quality': fmt['quality'],
                'height': fmt['height'],
                'width': fmt['width'],
            }

        def make_audio_source(fmt):
            return {
                'src': proxy_url_mappers['proxy_stream'](fmt['url']),
                'type': f"audio/{fmt['ext']}",
                'quality': f"{fmt['audio_bitrate']}kpbs",
                'bitrate': fmt['audio_bitrate'],
            }

        # filter out invalid sources
        formats = [fmt for fmt in info['formats'] if all(fmt[attr] for attr in ('itag', 'ext', 'url'))]
        # sort by resolution
        av_formats = [fmt for fmt in formats if fmt['quality'] and fmt['acodec'] and fmt['vcodec']]
        av_sources = [make_video_source(fmt) for fmt in av_formats]
        av_sources.sort(key=operator.itemgetter('quality'), reverse=True)
        video_sources = [make_video_source(fmt) for fmt in formats if fmt not in av_formats and fmt['quality'] and fmt['vcodec'] and not fmt['acodec']]
        video_sources.sort(key=operator.itemgetter('quality'), reverse=True)
        audio_sources = [make_audio_source(fmt) for fmt in formats if fmt not in av_formats and fmt['acodec'] and fmt['audio_bitrate'] and not fmt['vcodec']]
        # sort by bitrate
        audio_sources.sort(key=operator.itemgetter('bitrate'), reverse=True)

        # [TODO] this uses ytlocal's settings.txt, but it's a lot to bring in
        caption_sources = youtube.watch.get_subtitle_sources(info)
        for caption in caption_sources:
            caption['src'] = proxy_url_mappers['proxy_image'](fix_ytlocal_url(caption['url']))

        likes, dislikes, rating = info['like_count'], info['dislike_count'], 50
        votes = likes + dislikes
        if votes > 0: rating = int(likes / (votes) * 100)
        is_live = info['live']
        if is_live: duration = 'LIVE'
        else: duration = str(datetime.timedelta(seconds=info['duration']))

        related = []
        for item in info['related_videos']:
            if item['type'] == 'video':
                video = ytVideo(item['id'])
                video.title = item['title']
                video.thumbnail = item['thumbnail']
                video.channel_name = info['author']
                video.channel_url = info['author_url']
                video.cid = info['author_id']
                video.timestamp_human = item['time_published']
                video._override_ts_human()  # we can never call .timestamp_human again as the video lacks a .published
                video.view_count = item['view_count']
                video.duration = item['duration']  # TODO live
                video.badges = item['badges']
                video._override_from_lists()
                related.append(video)

        # override everything else
        self._del_ts_human()  # we have .published again
        self.title = info['title']
        self.channel_name = info['author']
        self.channel_url = info['author_url']
        self.cid = info['author_id']
        return {
            'published': dateparse(info['time_published']),
            'duration': duration,
            'is_live': is_live,
            'description': info['description'],
            'view_count': info['view_count'],
            'rating': rating,
            'rating_count': votes,
            'tags': info['tags'],
            'related_videos': related,
            'av_sources': av_sources,
            'audio_sources': audio_sources,
            'caption_sources': caption_sources,
        }

    @fscache.memoize(timeout=1)
    def _get_from_lists(self): return {'badges': []}

    def get_comments(self, sort=0, offset=0):
        comments = youtube.comments.video_comments(self.id, sort=0, offset=0, lc='', secret_key='')
        if comments is None: return []
        comments.sort(key=lambda x: x['likes'], reverse=True)
        for cmnt in comments:
            cmnt['thumbnail'] = proxy_url_mappers['proxy_image'](cmnt['thumbnail'])
        return comments

    @fscache.memoize(timeout=1)
    def _get_NYI(self): pass

    @fscache.memoize(timeout=1)
    def _get_ts_human(self):
        # TODO 'Scheduled', 'LIVE'
        return {'timestamp_human': f'{naturaldelta(utcnow() - self.published)} ago'}

    @property
    def views_human(self): return intword(self.view_count)


# def timedelta_human_str(delta):
#     if delta.days >= 7: return f"{int(delta.days/7)}w"
#     if delta.days > 0: return f"{delta.days}d"
#     elif delta.seconds >= 3600: return f"{int(delta.seconds/3600)}h"
#     else: return f"{int(delta.seconds/60)}m"



@propgroups
class ytChannel:
    # all_videos should prolly be a method with page
    # __propgroups__ = {'from_search': ['name', 'avatar', 'sub_count', 'invalid'], 'feed': ['recent_videos'],
    #                   'about_page': ['joined', 'descrption', 'view_count', 'links'], 'NYI': ['playlists', 'all_videos']}

    __propgroups__ = {'about_page': ['invalid', 'name', 'avatar', 'sub_count', 'joined', 'description', 'view_count', 'links'],
                      'mf_numvids': ['num_videos', 'num_video_pages'],
                      'feed': ['recent_videos'], 'NYI': ['playlists', 'all_videos']}

    __proxyprops__ = {'avatar': 'proxy_image'}

    __invalid_data__ = {'invalid': True, 'name': '--invalid channel id--', 'url': '', 'avatar': '', 'sub_count': 0, 'view_count': 0,
                        'joined': datetime.datetime.strptime('1970-01-01', '%Y-%m-%d'), 'description': '--channel does not exist--', 'links': [],
                        'num_videos': 0, 'num_video_pages': 1, 'recent_videos': []}

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

    # @fscache.memoize(timeout=3600 * 2)
    @fscache.memoize(timeout=3)
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
                # try: video.updated = dateparse(entry.updated)
                # except (AttributeError, ValueError): video.updated = now
                video.description = entry.summary_detail.value
                # video.description = re.sub(r'^https?:\/\/.*[\r\n]*', '', video.description[0:120] + "...",
                #                            flags=re.MULTILINE)
                video.view_count = entry.media_statistics['views']
                video.rating = int(float(entry.media_starrating['average']) / float(entry.media_starrating['max']) * 100)
                video.badges = []
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

        # if info['error'] == 'This channel does not exist': return YT_CHANNEL_INVALID_DATA
        # elif info['error'] is not None: raise RuntimeError(info['error'])
        if info['error']: return self._return_error('about_page', info['error'])
        # links is a list of tuples (text, url)
        joined = dateparse(info['date_joined'])

        # TODO check avatar url
        return {'invalid': False, 'name': info['channel_name'], 'avatar': info['avatar'],
                'sub_count': info['approx_subscriber_count'], 'joined': joined,
                'description': info['description'], 'view_count': info['view_count'], 'links': info['links']}

    @fscache.memoize(timeout=60 * 30)
    def _get_mf_numvids(self):
        numvids = youtube.channel.get_number_of_videos_channel(self.cid)
        return {'num_videos': numvids, 'num_video_pages': math.ceil(numvids / 30)}

    def get_videos(self, page=1, sort=3):
        videos = []
        if self.invalid: return videos
        view = 1 # not sure what this this
        polymer = youtube.channel.get_channel_tab(self.cid, page, sort, 'videos', view)
        info = youtube.yt_data_extract.extract_channel_info(json.loads(polymer), 'videos')

        if info['error'] is not None: raise RuntimeError(info['error'])

        print(json.dumps(info, indent=2))

        for item in info['items']:
            if item['type'] == 'video':
                video = ytVideo(item['id'])
                video.title = item['title']
                video.thumbnail = item['thumbnail']
                video.channel_name = info['channel_name']
                video.channel_url = info['channel_url']
                video.cid = self.cid
                video.timestamp_human = item['time_published']
                video._override_ts_human()  # we can never call .timestamp_human again as the video lacks a .published
                video.view_count = item['view_count']
                video.duration = item['duration']  # TODO live
                video.badges = item['badges']
                video._override_from_lists()
                videos.append(video)
        return videos



    def get_recent_videos(self, max_n=999, max_days=30):
        videos = []
        if self.invalid: return videos
        now = utcnow()
        for v in self.recent_videos:  # relies on recent_videos (and, in turn, youtube's rss feed) to be property sorted
            if (now - v.published).days > max_days: break
            if len(videos) >= max_n: break
            videos.append(v)
        return videos


def get_channel_for_urlpath(path):
    cid = get_cid_for_urlpath(path)
    # print(cid)
    # raise RuntimeError('haha')
    if cid is not None: return ytChannel(cid)
    ch = ytChannel('NOTFOUND')
    ch._return_error('__none',f"invalid path '{path}'")
    # for k, v in YT_CHANNEL_INVALID_DATA.items(): setattr(ch, k, v)
    return ch


@fscache.memoize(timeout=86400 * 7)
def get_cid_for_urlpath(path): return youtube.channel.get_channel_id(f'{BASE_URL}/{path}')


def get_recent_videos(cids, max_per_channel=99, max_days=9999):
    videos = []
    for cid in cids: videos.extend(ytChannel(cid).get_recent_videos(max_n=max_per_channel, max_days=max_days))
    videos.sort(key=operator.attrgetter('published'), reverse=True)
    return videos
