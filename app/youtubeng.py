import requests
from requests_futures.sessions import FuturesSession
import datetime
import functools
import operator
import json
import feedparser
from app import fscache
from youtube_search import YoutubeSearch
import youtube

# class decorator
def propgroups(cl):
    cl.__propnames__ = [prop for props in cl.__propgroups__.values() for prop in props]
    cl_init = cl.__init__
    @functools.wraps(cl_init)
    def init(self, *args, **kwargs):
        cl_init(self, *args)
        for k,v in kwargs.items():
            if k not in cl.__propnames__: raise TypeError(f"__init__ got an unexpected keyword argument '{k}'")
            setattr(self, k, v)  # including None for uninteresting props
    cl.__init__ = init
    for grp, props in cl.__propgroups__.items():
        # use a default arg to capture the value in the closure
        # https://stackoverflow.com/a/54289183
        def setcache(self, grp=grp, props=props):
            d = dict()
            for prop in props:
                ivar = f'_{prop}'
                if not hasattr(self, ivar): return
                d[prop] = getattr(self, ivar)
            getattr(self, f'_get_{grp}').set_cache(self,d)
        def delcache(self, grp=grp):
            getattr(self, f'_get_{grp}').del_cache(self)
        setattr(cl, f'_set_{grp}', setcache)
        setattr(cl, f'_det_{grp}', delcache)
        for prop in props:
            print('add prop ',prop)
            def pget(self, grp=grp, prop=prop):
                ivar = f'_{prop}'
                if not hasattr(self, ivar):  #first access (or invalidated) - rebuild cache
                    v = getattr(self, f'_get_{grp}')()[prop]
                    setattr(self, ivar, v)
                    return v
                return getattr(self, ivar)  #return cached result, including None
            def pset(self, v, grp=grp, prop=prop):
            # if set to None, it'll be cached - prop is deemed irrelevant foreverafter
            # NOTE: if this changes (e.g. in config), persisted cache must be cleared
                setattr(self, f'_{prop}', v)
                getattr(self, f'_set_{grp}')()
            def pdel(self, grp=grp, prop=prop):  # invalidate the cache and rebuild on next access
                delattr(self, prop)
                getattr(self, f'_del_{grp}')()
            setattr(cl, prop, property(pget, pset, pdel, f'property {prop} in group {grp}'))
    return cl

@propgroups
class ytVideo:
    __propgroups__ = {'oembed': ['title', 'thumbnail', 'channel_name', 'channel_url'], 'ch_id': ['cid'], 'page': ['published', 'updated', 'description', 'views', 'rating'], 'NYI':[ 'is_live', 'is_upcoming']}
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
    @fscache.memoize(timeout=86400*7)
    def _get_ch_id(self): return {'cid': youtube.channel.get_channel_id(self.channel_url)}

    @fscache.memoize(timeout=1)
    def _get_page(self): pass

    @fscache.memoize(timeout=1)
    def _get_NYI(self): pass

    @property
    def timestamp_human(self):
        # TODO 'Scheduled', 'LIVE'
        return timedelta_human_str(datetime.datetime.now() - self.published)


# rick=ytVideo('7ZjBiDVoTTE')

# class ytVideoBORINGZZZZZ():
#     def __repr__(self): return f"<ytVideo {self.id}>"
#     def __init__(self, id, title=None, thumbnail=None):
#         self.id = id
#         if title: self.title = title
#         if thumbnail: self.thumbnail = thumbnail

#     @property
#     def title(self):
#         return self._title or self._get_info_basic()['title']
#     @title.setter
#     def title(self, title):
#         self._title = title
#         self._cache_info_basic()

#     @property
#     def thumbnail(self): return self._thumbnail or self._get_info_basic()['thumbnail']
#     @thumbnail.setter
#     def thumbnail(self, thumbnail):
#         self._thumbnail = thumbnail
#         self._cache_info_basic()

#     def _cache_info_basic(self):
#         if self._thumbnail and self._title:
#             self._get_info_basic.set_cache({'title': self._title, 'thumbnail': self._thumbnail}, self)

#     @fscache.memoize(timeout=86400)
#     def _get_info_basic(self):
#         with FuturesSession() as session:
#             resp = future.get(f"https://www.youtube.com/oembed?format=json&url=http%3A%2F%2Fyoutu.be%2F{self.id}").result()
#             info = json.loads(resp.content)
#             return {'title': info['title'], 'thumbnail': info['thumbnail_url']}

#     @property
#     def published(self): return self._published or self._get_info()['published']
#     @published.setter
#     def published(self, published):
#         self._published = published
#         self._cache_info()

#     @property
#     def description(self): return self._description or self._get_info()['description']
#     @description.setter
#     def description(self, description):
#         self._description = description
#         self._cache_info()

#     @property
#     def views(self): return self._views or self._get_info()['views']
#     @views.setter
#     def views(self, views):
#         self._views = views
#         self._cache_info()

#     @property
#     def rating(self): return self._rating or self._get_info()['rating']
#     @rating.setter
#     def rating(self, rating):
#         self._rating = rating
#         self._cache_info()

#     def _cache_info(self):
#         if self._published and self._description and self._views and self._rating:
#             self._get_info.set_cache({'published': self._published, 'description': self._description, 'views': self._views, 'rating': self._rating})
#     @fscache.memoize(timeout=86400)
#     def _get_info(self):
#         return {}

def timedelta_human_str(delta):
    if delta.days >=  7: return f"{int(delta.days/7)}w"
    if delta.days > 0: return f"{delta.days}d"
    elif delta.seconds >= 3600: return f"{int(delta.seconds/3600)}h"
    else: return f"{int(delta.seconds/60)}m"


@propgroups
class ytChannel:
    # all_videos should prolly be a method with page
    __propgroups__ = {'from_search': ['name', 'avatar', 'sub_count', 'invalid'], 'feed': ['published', 'recent_videos'], 'page': ['banner', 'descrption', 'playlists', 'all_videos']}
    def __repr__(self): return f"<ytChannel {self.cid}>"
    # def __hash__(self): return hash(repr(self))
    def __init__(self, cid):
        self.cid = cid
    @fscache.memoize(timeout=86400*7)
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

    @fscache.memoize(timeout=3600*2)
    def _get_feed(self):
        now = datetime.datetime.now()
        with FuturesSession() as session:
            resp = session.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={self.cid}").result()
            rssFeed = feedparser.parse(resp.content)
            try:
                published = datetime.datetime.strptime(rssFeed.feed.published, '%Y-%m-%dT%H:%M:%S%z')
            except:
                published = now
            videos = []
            for entry in rssFeed.entries:
                video = ytVideo(entry.yt_videoid)
                video.title = entry.title
                video.thumbnail = entry.media_thumbnail[0]['url']
                video.channel_name = entry.author_detail.name
                video.channel_url = entry.author_detail.href
                video.cid = entry.yt_channelid
                try: video.published = datetime.datetime(entry.published_parsed)
                except:
                    # If youtube rss does not have parsed time, generate it. Else set time to 0.
                    try: video.published = datetime.datetime.strptime(entry.published, '%Y-%m-%dT%H:%M:%S%z')
                    except: video.published = now
                try: video.updated = datetime.datetime.strptime(entry.updated, '%Y-%m-%dT%H:%M:%S%z')
                except: video.updated = video.published
                video.description = entry.summary_detail.value
                # video.description = re.sub(r'^https?:\/\/.*[\r\n]*', '', video.description[0:120] + "...",
                #                            flags=re.MULTILINE)
                video.views = entry.media_statistics['views']
                video.rating = int(float(entry.media_starrating['average'])/float(entry.media_starrating['max']) * 100)
                videos.append(video)
        return {'published': published, 'recent_videos': videos}

    def get_recent_videos(self, max_n=999, max_days=7):
        videos = []
        now = datetime.datetime.now()
        for v in self.recent_videos:  # relies on recent_videos (and, in turn, youtube's rss feed) to be property sorted
            if (now - v.published).days > max_days: break
            if len(videos) >= max_n: break
            videos.append(v)
        return videos


@fscache.memoize(timeout=86400*7)
def get_cid(url): return youtube.channel.get_channel_id(url)

def get_recent_videos(cids, max_per_channel=99, max_days=9999):
    videos = []
    for cid in cids: videos.extend(ytChannel(cid).get_recent_videos(max_n=max_per_channel, max_days=max_days))
    videos.sort(key=operator.attrgetter('published'), reverse=True)
    return videos
