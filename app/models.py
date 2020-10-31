from datetime import datetime
from app import db, login
from flask_login import AnonymousUserMixin, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.ext.associationproxy import association_proxy
from app.youtubeng import ytVideo, ytChannel, ytPlaylist
utcnow = datetime.utcnow


class AnonymousUser(AnonymousUserMixin):
    is_admin = False
    is_restricted = True
    yt_channel_subscriptions = frozenset()
    yt_subscribed_channel_ids = frozenset()
    yt_subscribed_channels = frozenset()
    yt_playlist_follows = frozenset()
    yt_followed_playlist_ids = frozenset()
    yt_followed_playlists = frozenset()
    def get_video_watched_progress(self, vid): return 0
    def set_video_watched_progress(self, vid, progress, duration): return
    def has_watched_video(self, vid): return False


login.anonymous_user = AnonymousUser


class User(UserMixin, db.Model):
    def __repr__(self): return f'<User {self.username}>'
    rowid = db.Column(db.Integer, primary_key=True)
    def get_id(self): return str(self.rowid)
    username = db.Column(db.String(64), index=True, unique=True, nullable=False)
    created_on = db.Column(db.DateTime(), default=utcnow, nullable=False)
    # updated_on = db.Column(db.DateTime(), default=utcnow, onupdate=utcnow)
    password_hash = db.Column(db.String(128))
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)
    last_seen = db.Column(db.DateTime(), default=utcnow)
    def set_last_seen(self): self.last_seen = utcnow()
    is_admin = db.Column(db.Boolean, default=False, nullable=True)
    is_restricted = db.Column(db.Boolean, default=False, nullable=True)
    # def set_restricted_user(self): self.is_restricted = True

    yt_channel_subscriptions = db.relationship('dbChannelSubscription', collection_class=set, back_populates='user', lazy=True, cascade="all, delete, delete-orphan")
    # proxy the 'cid' attribute (which is in turn proxied) from the 'yt_channel_subscriptions' relationship
    yt_subscribed_channel_ids = association_proxy('yt_channel_subscriptions', 'cid', creator=lambda id: dbChannelSubscription(cid=id), cascade_scalar_deletes=True)
    @property
    def yt_subscribed_channels(self): return frozenset([ytChannel(id) for id in self.yt_subscribed_channel_ids])

    def get_channel_subscription_time(self, cid):
        for sub in self.yt_channel_subscriptions:
            if sub.cid == cid: return sub.created_on

    yt_playlist_follows = db.relationship('dbPlaylistFollow', collection_class=set, back_populates='user', lazy=True, cascade="all, delete, delete-orphan")
    yt_followed_playlist_ids = association_proxy('yt_playlist_follows', 'pid', creator=lambda id: dbPlaylistFollow(pid=id), cascade_scalar_deletes=True)

    @property
    def yt_followed_playlists(self): return frozenset([ytPlaylist(id) for id in self.yt_followed_playlist_ids])

    def get_playlist_follow_time(self, pid):
        for fol in self.yt_playlist_follows:
            if fol.pid == pid: return fol.created_on

    yt_videos_watched = db.relationship('dbVideoWatched', collection_class=set, back_populates='user', lazy=True, cascade='all, delete, delete-orphan')
    yt_watched_video_ids = association_proxy('yt_videos_watched', 'vid', creator=lambda id: dbVideoWatched(vid=id), cascade_scalar_deletes=True)

    @property
    def yt_watched_videos(self):
        res = []
        for db_video_watched in self.yt_videos_watched:
            if db_video_watched.duration * 0.9 < db_video_watched.watched_progress:
                res.append(ytVideo(db.db_video_watched.vid))
        return frozenset(res)

    def _get_vw(self, vid):
        for w in self.yt_videos_watched:
            if w.vid == vid: return w

    def get_video_last_watched(self, vid):
        vw = self._get_vw(vid)
        return vw.updated_on if vw else None

    def get_video_watched_progress(self, vid):
        vw = self._get_vw(vid)
        return vw.watched_progress if vw else 0

    def set_video_watched_progress(self, vid, progress, duration):
        vw = self._get_vw(vid)
        if not vw:
            vw = dbVideoWatched(user=self, vid=vid, duration=duration, watched_progress=progress)
            db.session.add(vw)
        else:
            vw.watched_progress = progress
            vw.duration = duration
        db.session.commit()

    def has_watched_video(self, vid):
        vw = self._get_vw(vid)
        print(f'HAS {self} watched {vid}? ={vw}')
        if vw:
            print(dir(vw))
            print(vw.duration)
            print(vw.watched_progress)
        return (vw.duration or 99999) * 0.9 < vw.watched_progress if vw else False


@login.user_loader
def load_user(uid):
    user = User.query.get(int(uid))
    if user: user.set_last_seen()
    return user


class dbChannelSubscription(db.Model):
    __tablename__ = 'user_channel_assoc'
    user_rowid = db.Column(db.Integer, db.ForeignKey('user.rowid'), primary_key=True)
    channel_rowid = db.Column(db.Integer, db.ForeignKey('yt_channel.rowid'), primary_key=True)
    created_on = db.Column(db.DateTime(), default=utcnow, nullable=False)
    db_channel = db.relationship('dbChannel', back_populates='user_subscriptions', lazy=True)
    cid = association_proxy('db_channel', 'id', creator=lambda id: dbChannel.load(id))
    user = db.relationship('User', back_populates='yt_channel_subscriptions', lazy=True)


class dbPlaylistFollow(db.Model):
    __tablename__ = 'user_playlist_assoc'
    user_rowid = db.Column(db.Integer, db.ForeignKey('user.rowid'), primary_key=True)
    playlist_rowid = db.Column(db.Integer, db.ForeignKey('yt_playlist.rowid'), primary_key=True)
    created_on = db.Column(db.DateTime(), default=utcnow, nullable=False)
    db_playlist = db.relationship('dbPlaylist', back_populates='user_follows', lazy=True)
    pid = association_proxy('db_playlist', 'id', creator=lambda id: dbPlaylist.load(id))
    user = db.relationship('User', back_populates='yt_playlist_follows', lazy=True)


class dbVideoWatched(db.Model):
    __tablename__ = 'user_video_assoc'
    user_rowid = db.Column(db.Integer, db.ForeignKey('user.rowid'), primary_key=True)
    video_rowid = db.Column(db.Integer, db.ForeignKey('yt_video.rowid'), primary_key=True)
    created_on = db.Column(db.DateTime(), default=utcnow, nullable=False)
    updated_on = db.Column(db.DateTime(), default=utcnow, onupdate=utcnow)
    watched_progress = db.Column(db.Integer, default=0)
    db_video = db.relationship('dbVideo', back_populates='user_watch_entries', lazy=True)
    vid = association_proxy('db_video', 'id', creator=lambda id: dbVideo.load(id))
    duration = association_proxy('db_video', 'duration')
    user = db.relationship('User', back_populates='yt_videos_watched', lazy=True)


class dbBase(object):
    def __repr__(self): return f"<{self.__class__.__name__} {getattr(self,'id','?')}>"
    rowid = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String(64), index=True, unique=True, nullable=False)
    created_on = db.Column(db.DateTime(), default=utcnow, nullable=False)

    @classmethod
    def load(cls, id):
        with db.session.no_autoflush:
            return db.session.query(cls).filter(cls.id == id).first() or cls(id=id)


class dbChannel(dbBase, db.Model):
    __tablename__ = 'yt_channel'
    is_allowed = db.Column(db.Boolean, default=False, index=True, nullable=True)
    is_blocked = db.Column(db.Boolean, default=False, index=True, nullable=True)
    user_subscriptions = db.relationship('dbChannelSubscription', collection_class=set, back_populates='db_channel', lazy=True)
    subscribers = association_proxy('user_subscriptions', 'user')
    # followers = db.relationship('User', collection_class=set, secondary=user_channel_assoc, back_populates="db_followed_channels", lazy=True)


class dbPlaylist(dbBase, db.Model):
    __tablename__ = 'yt_playlist'
    is_allowed = db.Column(db.Boolean, default=False, index=True, nullable=True)
    # is_blocked = db.Column(db.Boolean, default=False, index=True, nullable=True)
    user_follows = db.relationship('dbPlaylistFollow', collection_class=set, back_populates='db_playlist', lazy=True)
    followers = association_proxy('user_follows', 'user')


class dbVideo(dbBase, db.Model):
    __tablename__ = 'yt_video'
    duration = db.Column(db.Integer, default=99999)
    user_watch_entries = db.relationship('dbVideoWatched', collection_class=set, back_populates='db_video', lazy=True)
    watchers = association_proxy('user_watch_entries', 'user')

def link_db(cls, dbcls):
    def dbget(self):
        if hasattr(self, '_db_obj'): return getattr(self, '_db_obj')
        obj = dbcls.load(self.id)
        setattr(self, '_db_obj', obj)
        return obj
    setattr(cls, 'db_obj', property(dbget, None, None, f'db-backed object'))
    # for prop in db.class_mapper(dbcls).column_attrs.keys():
    # also proxy relationships
    for prop in db.class_mapper(dbcls).attrs.keys():
        def pget(self, prop=prop):
            return getattr(self.db_obj, prop)

        def pset(self, v, prop=prop):
            setattr(self.db_obj, prop, v)
            db.session.add(self.db_obj)  # only commit to db when a column is set
            db.session.commit()

        if prop != 'id': setattr(cls, prop, property(pget, pset, None, f'db-backed property {prop}'))


link_db(ytChannel, dbChannel)
link_db(ytPlaylist, dbPlaylist)
link_db(ytVideo, dbVideo)

