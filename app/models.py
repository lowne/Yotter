from functools import wraps
from datetime import datetime
from app import db, login, fscache
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.ext.associationproxy import association_proxy
from app.youtubeng import ytngVideo, ytngChannel, ytngPlaylist, unique_constructor, prop_mappers, logged


####################################################################
# https://github.com/sqlalchemy/sqlalchemy/wiki/UniqueObject
def _unique(session, cls, hashfunc, queryfunc, constructor, arg, kw):
    cache = getattr(session, '_unique_cache', None)
    if cache is None:
        session._unique_cache = cache = {}

    key = (cls, hashfunc(*arg, **kw))
    if key in cache:
        return cache[key]
    else:
        with session.no_autoflush:
            q = session.query(cls)
            q = queryfunc(q, *arg, **kw)
            obj = q.first()
            if not obj:
                obj = constructor(*arg, **kw)
                session.add(obj)
        cache[key] = obj
        return obj


def lunique_constructor(session=None, hash=None, query=None):
    def decorate(cls):
        def _null_init(self, *arg, **kw):
            pass

        @wraps(cls)
        def __new__(cls, bases, *arg, **kw):
            # no-op __new__(), called
            # by the loading procedure
            if not arg and not kw:
                return object.__new__(cls)

            sess = session()

            def constructor(*arg, **kw):
                obj = object.__new__(cls)
                obj._unique_init(*arg, **kw)
                return obj

            return _unique(sess, cls, hash, query, constructor, arg, kw)

        # note: cls must be already mapped for this part to work
        cls._unique_init = cls.__init__
        cls.__init__ = _null_init
        cls.__new__ = classmethod(__new__)
        return cls

    return decorate


####################################################################

user_channel_assoc = db.Table('user_channel_assoc',
                              db.Column('channel_rowid', db.Integer, db.ForeignKey('yt_channel.rowid')),
                              db.Column('user_rowid', db.Integer, db.ForeignKey('user.rowid'))
                              )  # Association: CHANNEL --followed by--> [USERS]


user_playlist_assoc = db.Table('user_playlist_assoc',
                               db.Column('playlist_rowid', db.Integer, db.ForeignKey('yt_playlist.rowid')),
                               db.Column('user_rowid', db.Integer, db.ForeignKey('user.rowid'))
                               )  # Association: PLAYLIST --followed by--> [USERS]


@unique_constructor(session=db.session,
                    hash=lambda username, **kw: username,
                    query=lambda query, username, **kw: query.filter(User.username == username)
                    )
class User(UserMixin, db.Model):
    rowid = db.Column(db.Integer, primary_key=True)
    def get_id(self): return self.rowid
    username = db.Column(db.String(64), index=True, unique=True, nullable=False)
    created_on = db.Column(db.DateTime(), default=datetime.utcnow, nullable=False)
    # updated_on = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)
    password_hash = db.Column(db.String(128))
    last_seen = db.Column(db.DateTime(), default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False, nullable=True)
    is_restricted = db.Column(db.Boolean, default=False, nullable=True)

    yt_followed_channels = db.relationship("ytChannel", collection_class=set, secondary=user_channel_assoc, back_populates="followers", lazy=True)
    # proxy the 'cid' attribute from the 'yt_followed_channels' relationship
    yt_followed_cids = association_proxy('yt_followed_channels', 'id', creator=lambda id: ytChannel(id=id))

    yt_followed_playlists = db.relationship("ytPlaylist", collection_class=set, secondary=user_playlist_assoc, back_populates="followers", lazy=True)
    yt_followed_pids = association_proxy('yt_followed_playlists', 'id', creator=lambda id: ytPlaylist(id=id))

    def __repr__(self): return f'<User {self.username}>'

    def set_last_seen(self):
        self.last_seen = datetime.utcnow()

    def set_admin_user(self):
        self.is_admin = True

    def set_restricted_user(self):
        self.is_restricted = True

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login.user_loader
def load_user(rowid):
    return User.query.get(int(rowid))


class ytMixin(object):
    def __repr__(self): return f"<{self.__class__.__name__} {getattr(self,'id','?')}>"

    rowid = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String(64), index=True, unique=True, nullable=False)
    created_on = db.Column(db.DateTime(), default=datetime.utcnow, nullable=False)
    # updated_on = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    @logged
    def __init__(self, id):
        sobj = super()
        return getattr(sobj, '_unique_init', sobj.__init__)(id)
        # return super().__init__(id)


@unique_constructor(session=db.session,
                    hash=lambda id, **kw: id,
                    query=lambda query, id, **kw: query.filter(ytChannel.id == id)
                    )
class ytChannel(ytMixin, ytngChannel, db.Model):
    __tablename__ = 'yt_channel'
    is_allowed = db.Column(db.Boolean, default=False, index=True, nullable=True)
    is_blocked = db.Column(db.Boolean, default=False, index=True, nullable=True)
    followers = db.relationship('User', collection_class=set, secondary=user_channel_assoc, back_populates="yt_followed_channels", lazy=True)
    follower_usernames = association_proxy('followers', 'username', creator=lambda username: User(username=username))


@unique_constructor(session=db.session,
                    hash=lambda id, **kw: id,
                    query=lambda query, id, **kw: query.filter(ytPlaylist.id == id)
                    )
class ytPlaylist(ytMixin, ytngPlaylist, db.Model):
    __tablename__ = 'yt_playlist'
    is_allowed = db.Column(db.Boolean, default=False, index=True, nullable=True)
    # is_blocked = db.Column(db.Boolean, default=False, index=True, nullable=True)
    followers = db.relationship('User', collection_class=set, secondary=user_playlist_assoc, back_populates="yt_followed_playlists", lazy=True)
    follower_usernames = association_proxy('followers', 'username', creator=lambda username: User(username=username))


@unique_constructor(session=db.session,
                    hash=lambda id, **kw: id,
                    query=lambda query, id, **kw: query.filter(ytVideo.id == id)
                    )
class ytVideo(ytMixin, ytngVideo, db.Model):
    __tablename__ = 'yt_video'

