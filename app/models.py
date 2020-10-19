from datetime import datetime
from app import db, login
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'))
)

channel_association = db.Table('channel_association',
    db.Column('channel_id', db.Integer, db.ForeignKey('channel.id')),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'))
) # Association: CHANNEL --followed by--> [USERS]


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    password_hash = db.Column(db.String(128))
    last_seen = db.Column(db.DateTime, default=datetime.utcnow())
    is_admin = db.Column(db.Boolean, default=False, nullable=True)

    def __repr__(self):
        return '<User {}>'.format(self.username)

    def set_last_seen(self):
        self.last_seen = datetime.utcnow()

    def set_admin_user(self):
        self.is_admin = True

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def follow(self, user):
        if not self.is_following(user):
            self.followed.append(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.followed.remove(user)

    def is_following(self, user):
        return self.followed.filter(
            followers.c.followed_id == user.id).count() > 0

    def following_list(self):
        return self.followed.all()

    # YOUTUBE
    def youtube_following_list(self):
        return self.youtubeFollowed.all()

    def is_following_yt(self, cid):
        temp_cid = youtubeFollow.query.filter_by(channelId = cid).first()
        if temp_cid is None:
            return False
        else:
            following = self.youtube_following_list()
            for f in following:
                if f.channelId == cid:
                    return True
        return False

    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'), lazy='dynamic')

    youtubeFollowed = db.relationship("youtubeFollow",
        secondary=channel_association,
        back_populates="followers",
        lazy='dynamic')


@login.user_loader
def load_user(id):
    return User.query.get(int(id))

class ytPost():
    channelName = 'Error'
    channelUrl = '#'
    channelId = '@'
    videoUrl = '#'
    videoTitle = '#'
    videoThumb = '#'
    description = "LOREM IPSUM"
    date = 'None'
    views = 'NaN'
    id = 'isod'


class youtubeFollow(db.Model):
    __tablename__ = 'channel'
    id = db.Column(db.Integer, primary_key=True)
    channelId = db.Column(db.String(30), nullable=False)
    channelName = db.Column(db.String(100))
    followers = db.relationship('User',
                                secondary=channel_association,
                                back_populates="youtubeFollowed")

    def __repr__(self):
        return '<youtubeFollow {}>'.format(self.channelName)

