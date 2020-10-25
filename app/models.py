from functools import wraps
from datetime import datetime
from app import db, login, fscache
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.ext.associationproxy import association_proxy
from app.youtubeng import ytVideo, ytChannel


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


def unique_constructor(scoped_session, hashfunc, queryfunc):
    def decorate(cls):
        def _null_init(self, *arg, **kw):
            pass

        @wraps(cls)
        def __new__(cls, bases, *arg, **kw):
            # no-op __new__(), called
            # by the loading procedure
            if not arg and not kw:
                return object.__new__(cls)

            session = scoped_session()

            def constructor(*arg, **kw):
                obj = object.__new__(cls)
                obj._init(*arg, **kw)
                return obj

            return _unique(session, cls, hashfunc, queryfunc, constructor, arg, kw)

        # note: cls must be already mapped for this part to work
        cls._init = cls.__init__
        cls.__init__ = _null_init
        cls.__new__ = classmethod(__new__)
        return cls

    return decorate
####################################################################


user_channel_assoc = db.Table('user_channel_assoc',
                              db.Column('channel_id', db.Integer, db.ForeignKey('yt_channel.id')),
                              db.Column('user_id', db.Integer, db.ForeignKey('user.id'))
                              )  # Association: CHANNEL --followed by--> [USERS]


@unique_constructor(db.session,
                    lambda username: username,
                    lambda query, username: query.filter(User.username == username)
                    )
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    password_hash = db.Column(db.String(128))
    last_seen = db.Column(db.DateTime, default=datetime.utcnow())
    is_admin = db.Column(db.Boolean, default=False, nullable=True)
    is_restricted = db.Column(db.Boolean, default=False, nullable=True)
    yt_followed_channels = db.relationship("ytChannel", collection_class=set, secondary=user_channel_assoc, back_populates="followers", lazy=True)
    # proxy the 'cid' attribute from the 'yt_followed_channels' relationship
    yt_followed_cids = association_proxy('yt_followed_channels', 'cid', creator=lambda cid: ytChannel(cid=cid))

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


@unique_constructor(db.session,
                    lambda cid: cid,
                    lambda query, cid: query.filter(ytChannel.cid == cid)
                    )
class ytChannel(ytChannel, db.Model):
    __tablename__ = 'yt_channel'
    id = db.Column(db.Integer, primary_key=True)
    cid = db.Column(db.String(30), index=True, unique=True)
    # channelName = db.Column(db.String(100))
    followers = db.relationship('User', collection_class=set, secondary=user_channel_assoc, back_populates="yt_followed_channels", lazy=True)
    follower_usernames = association_proxy('followers', 'username', creator=lambda username: User(username=username))
    def __repr__(self): return f'<ytChannel {self.cid}>'


@login.user_loader
def load_user(id):
    return User.query.get(int(id))

