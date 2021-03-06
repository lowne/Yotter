"""watch progress

Revision ID: 5db87d774e44
Revises: 6a0abbea9058
Create Date: 2020-10-31 13:20:43.330452

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5db87d774e44'
down_revision = '6a0abbea9058'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('user_video_assoc',
    sa.Column('user_rowid', sa.Integer(), nullable=False),
    sa.Column('video_rowid', sa.Integer(), nullable=False),
    sa.Column('created_on', sa.DateTime(), nullable=False),
    sa.Column('updated_on', sa.DateTime(), nullable=True),
    sa.Column('watched_progress', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['user_rowid'], ['user.rowid'], ),
    sa.ForeignKeyConstraint(['video_rowid'], ['yt_video.rowid'], ),
    sa.PrimaryKeyConstraint('user_rowid', 'video_rowid')
    )
    op.add_column('yt_video', sa.Column('duration', sa.Integer(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('yt_video', 'duration')
    op.drop_table('user_video_assoc')
    # ### end Alembic commands ###
