"""Fix Render DB schema

Revision ID: fix_render_db
Revises: 
Create Date: 2025-11-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = 'fix_render_db'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # データベースの現状を確認するための準備
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    tables = inspector.get_table_names()

    # 1. 'like' テーブルが無ければ作成する
    if 'like' not in tables:
        op.create_table('like',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('post_id', sa.Integer(), nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['post_id'], ['post.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'post_id', name='_user_post_like_uc')
        )

    # 2. 'user' テーブルにカラムを追加する
    # (userテーブル自体は絶対あるはずなので、カラムの存在チェックをして追加)
    user_columns = [col['name'] for col in inspector.get_columns('user')]
    
    if 'notification_comment_like' not in user_columns:
        with op.batch_alter_table('user', schema=None) as batch_op:
            batch_op.add_column(sa.Column('notification_comment_like', sa.Boolean(), nullable=True))
    
    if 'notification_reply' not in user_columns:
        with op.batch_alter_table('user', schema=None) as batch_op:
            batch_op.add_column(sa.Column('notification_reply', sa.Boolean(), nullable=True))

    # 3. データのデフォルト値を設定 (エラー回避のためSQLで直接実行)
    # カラム追加直後はNULLになっているので、True(有効)に更新する
    op.execute('UPDATE "user" SET notification_comment_like = true')
    op.execute('UPDATE "user" SET notification_reply = true')

def downgrade():
    pass