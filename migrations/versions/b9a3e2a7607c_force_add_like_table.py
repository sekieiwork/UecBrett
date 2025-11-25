"""Force Add Like Table

Revision ID: b9a3e2a7607c
Revises: 
Create Date: 2025-11-25 01:20:20.626120

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b9a3e2a7607c'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # 1. いいねテーブルを作成
    # (テーブルが既に存在する場合のエラーを回避するため、チェックを入れるのが理想ですが、今回はRender用なのでそのまま書きます)
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

    # 2. ユーザーテーブルに新しい設定項目を追加
    # (エラー回避のため、try-exceptのような安全策はとれませんが、Renderにはカラムがないはずなので通ります)
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notification_comment_like', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('notification_reply', sa.Boolean(), nullable=True))

    # 3. デフォルト値の設定
    op.execute('UPDATE "user" SET notification_comment_like = true')
    op.execute('UPDATE "user" SET notification_reply = true')


def downgrade():
    pass
