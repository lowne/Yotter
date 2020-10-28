from datetime import datetime
from app import db, login
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.ext.associationproxy import association_proxy
from app.youtubeng import ytVideo, ytChannel, ytPlaylist
utcnow=datetime.utcnow

user_channel_assoc = db.Table('user_channel_assoc',
                              db.Column('channel_rowid', db.Integer, db.ForeignKey('yt_channel.rowid')),
                              db.Column('user_rowid', db.Integer, db.ForeignKey('user.rowid'))
                              )  # Association: CHANNEL --followed by--> [USERS]


user_playlist_assoc = db.Table('user_playlist_assoc',
                               db.Column('playlist_rowid', db.Integer, db.ForeignKey('yt_playlist.rowid')),
                               db.Column('user_rowid', db.Integer, db.ForeignKey('user.rowid'))
                               )  # Association: PLAYLIST --followed by--> [USERS]


class User(UserMixin, db.Model):
    rowid = db.Column(db.Integer, primary_key=True)
    def get_id(self): return str(self.rowid)
    username = db.Column(db.String(64), index=True, unique=True, nullable=False)
    created_on = db.Column(db.DateTime(), default=utcnow, nullable=False)
    # updated_on = db.Column(db.DateTime(), default=utcnow, onupdate=utcnow)
    password_hash = db.Column(db.String(128))
    last_seen = db.Column(db.DateTime(), default=utcnow)
    is_admin = db.Column(db.Boolean, default=False, nullable=True)
    is_restricted = db.Column(db.Boolean, default=False, nullable=True)

    db_followed_channels = db.relationship("dbChannel", collection_class=set, secondary=user_channel_assoc, back_populates="followers", lazy=True)
    # proxy the 'cid' attribute from the 'yt_followed_channels' relationship
    yt_followed_channel_ids = association_proxy('db_followed_channels', 'id', creator=lambda id: dbChannel(id=id))

    @property
    def yt_followed_channels(self): return frozenset([ytChannel(id) for id in self.yt_followed_channel_ids])

    db_followed_playlists = db.relationship("dbPlaylist", collection_class=set, secondary=user_playlist_assoc, back_populates="followers", lazy=True)
    yt_followed_playlist_ids = association_proxy('db_followed_playlists', 'id', creator=lambda id: dbPlaylist(id=id))

    @property
    def yt_followed_playlists(self): return frozenset([ytPlaylist(id) for id in self.yt_followed_playlist_ids])

    def __repr__(self): return f'<User {self.username}>'

    def set_last_seen(self):
        self.last_seen = utcnow()

    def set_admin_user(self):
        self.is_admin = True

    def set_restricted_user(self):
        self.is_restricted = True

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login.user_loader
def load_user(uid):
    user = User.query.get(int(uid))
    if user: user.set_last_seen()
    return user


class dbBase(object):
    def __repr__(self): return f"<{self.__class__.__name__} {getattr(self,'id','?')}>"
    rowid = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String(64), index=True, unique=True, nullable=False)
    created_on = db.Column(db.DateTime(), default=utcnow, nullable=False)


class dbChannel(dbBase, db.Model):
    __tablename__ = 'yt_channel'
    is_allowed = db.Column(db.Boolean, default=False, index=True, nullable=True)
    is_blocked = db.Column(db.Boolean, default=False, index=True, nullable=True)
    followers = db.relationship('User', collection_class=set, secondary=user_channel_assoc, back_populates="db_followed_channels", lazy=True)
    # follower_usernames = association_proxy('followers', 'username', creator=lambda username: User(username=username))


class dbPlaylist(dbBase, db.Model):
    __tablename__ = 'yt_playlist'
    is_allowed = db.Column(db.Boolean, default=False, index=True, nullable=True)
    # is_blocked = db.Column(db.Boolean, default=False, index=True, nullable=True)
    followers = db.relationship('User', collection_class=set, secondary=user_playlist_assoc, back_populates="db_followed_playlists", lazy=True)
    # follower_usernames = association_proxy('followers', 'username', creator=lambda username: User(username=username))


class dbVideo(dbBase, db.Model):
    __tablename__ = 'yt_video'


def link_db(cls, dbcls):
    def dbget(self):
        if hasattr(self, '_db_obj'): return getattr(self, '_db_obj')
        with db.session.no_autoflush:
            obj = db.session.query(dbcls).filter(dbcls.id == self.id).first() or dbcls(id=self.id)
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
