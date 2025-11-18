from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_
from flask_migrate import Migrate, upgrade
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from pytz import timezone, utc
import os
from flask_wtf.file import FileField, FileAllowed
from forms import PostForm, CommentForm, RegisterForm, LoginForm, SearchForm, ProfileForm, KairanbanForm
from forms import (PostForm, CommentForm, RegisterForm, LoginForm, SearchForm, ProfileForm, KairanbanForm, 
                   GRADE_CHOICES, CATEGORY_CHOICES, CLASS_CHOICES, PROGRAM_CHOICES, MAJOR_CHOICES,
                   BooleanField)
import markdown
import re
import json
from PIL import Image
import cloudinary
import cloudinary.uploader
import bleach
from bleach.linkifier import Linker
from pywebpush import webpush, WebPushException
from forms import NotificationSettingsForm



cloudinary.config(
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'), 
    api_key = os.environ.get('CLOUDINARY_API_KEY'), 
    api_secret = os.environ.get('CLOUDINARY_API_SECRET'),
    secure = True
)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
# 元の状態に戻す
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///site.db')
db = SQLAlchemy(app)
md = markdown.Markdown(extensions=['nl2br'])
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@app.context_processor
def inject_common_vars():
    """
    全てのテンプレートに共通の変数を自動で渡す
    """
    search_form = SearchForm()
    is_developer = False
    has_unread_kairanban = False # <-- まずFalseで初期化

    # 認証済みユーザーの場合のみ、開発者チェックと回覧板チェックを行う
    if current_user.is_authenticated:
        if current_user.username == '二酸化ケイ素':
            is_developer = True
        
        # --- (ここからインデントして 'if' の中に入れる) ---
        # 1. 期限切れでない回覧板
        base_query = Kairanban.query.filter(Kairanban.expires_at > datetime.utcnow())
            
        # 2a. 自分の「ステータスタグ」をセットで取得
        user_status_tags = {
            current_user.grade, 
            current_user.category, 
            current_user.user_class, 
            current_user.program, 
            current_user.major
        }
        # 2b. 自分の「カスタムタグ」をセットで取得
        user_custom_tags = {tag.name for tag in current_user.tags} #
        
        # 2c. 結合 (Noneや空文字を除外)
        user_all_tag_names = {tag for tag in user_status_tags.union(user_custom_tags) if tag}

        target_kairanbans_query = base_query.filter(Kairanban.id < 0) # デフォルトは空
        if user_all_tag_names:
            # 2d. タグ名(Tag.name)でKairanbanを検索
            target_kairanbans_query = base_query.join(kairanban_tags).join(Tag).filter(
                Tag.name.in_(user_all_tag_names)
            )
               
            # 3. チェック済みのIDを取得
            checked_ids = {c.kairanban_id for c in KairanbanCheck.query.filter_by(user_id=current_user.id)}
                
            # 4. 1件ずつチェック
            target_kairanbans = target_kairanbans_query.all()
            for k in target_kairanbans:
                if k.author_id != current_user.id and k.id not in checked_ids:
                    has_unread_kairanban = True
                    break # 1件でも未チェックがあればループ終了
        # --- (ここまでインデント) ---

    return dict(
        search_form=search_form, 
        is_developer=is_developer,
        has_unread_kairanban=has_unread_kairanban 
    )

# 1. アプリケーションで許可するHTMLタグを定義します
# (Markdownが生成するもの + UECreviewで使うspan)
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'ol', 'ul', 'li', 'a', 'span', 'hr',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'code', 'blockquote',
]

# 2. 許可するタグに付随する属性を定義します
ALLOWED_ATTRIBUTES = {
    'a': ['href', 'target'], # リンク
    'span': ['class']        # UECreviewの <span class="text-red"> 用
}

# 3. BleachのLinkerを設定（自動でリンクに target="_blank" を追加）
linker = Linker(callbacks=[
    lambda attrs, new: attrs.update({(None, 'target'): '_blank'})
])

# 4. 「safe_markdown」という名前のカスタムフィルターを定義
@app.template_filter('safe_markdown')
def safe_markdown_filter(text):
    if not text:
        return ""

    # ステップ1: まずMarkdownをHTMLに変換する
    html = md.convert(text)

    # ▼▼▼ ▼▼▼ [修正] 処理の順序を入れ替えます ▼▼▼ ▼▼▼

    # ステップ2: linkifyコールバックを定義 (target="_blank" を追加)
    def add_target_blank(attrs, new=False):
        # (None, 'target'): '_blank' を attrs に追加
        attrs[(None, 'target')] = '_blank'
        return attrs

    # ステップ3: bleach.linkify() で先にリンク化する
    # (リンク化をスキップするのは 'a', 'pre', 'code' タグの中だけ)
    linked_html = bleach.linkify(
        html,
        callbacks=[add_target_blank],
        skip_tags=['a', 'pre', 'code'] # <-- ALLOWED_TAGS から変更
    )

    # ステップ4: bleach.clean() で最後に全体を消毒する
    # (ALLOWED_TAGS と ALLOWED_ATTRIBUTES を使う)
    sanitized_html = bleach.clean(
        linked_html,
        tags=ALLOWED_TAGS,       
        attributes=ALLOWED_ATTRIBUTES
    )

    return sanitized_html



# ▼▼▼タグ処理ヘルパー関数 ▼▼▼
def get_or_create_tags_from_string(tag_string):
    """
    "tag1,tag2, tag3" のようなカンマ区切りの文字列をパースし、
    Tagオブジェクトのリストを返す。
    新しいタグはDBに作成し、last_usedを更新する。
    """
    tag_objects = []
    if not tag_string:
        return tag_objects

    # "tag1, tag2 , tag3" -> ["tag1", "tag2", "tag3"]
    tag_names = [name.strip() for name in tag_string.split(',') if name.strip()]
    
    for name in tag_names:
        tag = Tag.query.filter_by(name=name).first()
        if not tag:
            # 新しいタグを作成
            tag = Tag(name=name, last_used=datetime.utcnow())
            db.session.add(tag)
        else:
            # 既存タグの last_used を更新
            tag.last_used = datetime.utcnow()
        
        tag_objects.append(tag)
        
    db.session.commit() # このセッションで追加されたタグをコミット
    return tag_objects
# ▲▲▲ [追加] ここまで ▲▲▲


def parse_review_for_editing(content):
    """
    保存されたHTML/Markdown形式のUECreview本文をパースし、
    編集フォーム用の辞書のリストに変換する。
    """
    
    # UECreview形式かの簡易判定
    if not content.strip().startswith('<span class="text-large">**'):
        return None # UECreview形式ではない

    subjects = []
    # 投稿を "---" (ハイフン3つ) で分割（科目ごとのレビューに分ける）
    reviews = re.split(r'\n\s*---\s*\n', content.strip())
    
    # パース用の正規表現パターン
    # (科目名), (成績), (担当教員), (本文) をキャプチャする
    pattern = re.compile(
        r'<span class="text-large">\*\*(.*?)\*\*</span>\s*'
        r'成績:<span class="text-red text-large">\*\*(.*?)\*\*</span>\s*'
        r'担当教員:(.*?)\n'
        r'(.*?)(?=\Z)', # \Z は文字列の絶対的な末尾
        re.DOTALL # DOTALLで '.' が改行にもマッチするようにする
    )

    placeholders = ['ここに科目名を入力', 'ここに担当教員名を入力', '本文を入力']

    for review_text in reviews:
        match = pattern.search(review_text.strip())
        if match:
            subject, grade, teacher, body = match.groups()
            
            # プレースホルダーだったら空文字列 '' に変換
            subject = '' if subject == placeholders[0] else subject
            teacher = '' if teacher == placeholders[1] else teacher
            body = '' if body == placeholders[2] else body
            
            subjects.append({
                'subject': subject.strip(),
                'grade': grade.strip(),
                'teacher': teacher.strip(),
                'body': body.strip()
            })

    return subjects if subjects else None

def save_picture(form_picture):
    # Cloudinaryに画像をアップロード
    upload_result = cloudinary.uploader.upload(form_picture, folder="post_images", width=500, height=500, crop="limit")
    # アップロードされた画像の安全なURLを返す
    return upload_result.get('secure_url')

def save_icon(form_icon):
    # Cloudinaryにアイコンをアップロード（150x150の正方形に顔を認識してクロップ）
    upload_result = cloudinary.uploader.upload(form_icon, 
                                               folder="profile_icons", 
                                               width=150, 
                                               height=150, 
                                               crop="fill", 
                                               gravity="face")
    # アップロードされた画像の安全なURLを返す
    return upload_result.get('secure_url')

def delete_from_cloudinary(image_url):
    if not image_url:
        return # URLがなければ何もしない
    try:
        # URLからpublic_idを抽出します (例: .../upload/v123/folder/file.jpg -> folder/file)
        public_id_with_ext = '/'.join(image_url.split('/')[-2:])
        public_id = os.path.splitext(public_id_with_ext)[0]
        # Cloudinaryに削除を命令
        cloudinary.uploader.destroy(public_id)
    except Exception as e:
        # エラーが起きてもプログラムは止めないように、ログだけ表示（任意）
        print(f"Error deleting image from Cloudinary: {e}")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ▼▼▼ [修正] タグモデル定義を User/Post クラスの「前」に移動 ▼▼▼
# 1. Post と Tag の中間テーブル (多対多)
post_tags = db.Table('post_tags',
    db.Column('post_id', db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id', ondelete="CASCADE"), primary_key=True)
)

# 2. User と Tag の中間テーブル (多対多)
user_tags = db.Table('user_tags',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id', ondelete="CASCADE"), primary_key=True)
)

# 3. Tagモデル
class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    # 最後に使われた日時 (「最近使用したタグ」機能のため)
    last_used = db.Column(db.DateTime, default=datetime.utcnow)

# 4. Kairanban と Tag の中間テーブル (多対多)
kairanban_tags = db.Table('kairanban_tags',
    db.Column('kairanban_id', db.Integer, db.ForeignKey('kairanban.id', ondelete="CASCADE"), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id', ondelete="CASCADE"), primary_key=True)
)

# 5. Kairanbanモデル
class Kairanban(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # 投稿時に created_at + N日 で設定する
    expires_at = db.Column(db.DateTime, nullable=False) 
    author_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    
    author = db.relationship('User', backref='kairanbans')
    tags = db.relationship('Tag', secondary=kairanban_tags, lazy='subquery',
        backref=db.backref('kairanbans', lazy=True), cascade="all, delete")
    
    # どのユーザーがチェックしたか (KairanbanCheckモデルとの連携)
    checks = db.relationship('KairanbanCheck', backref='kairanban', lazy='dynamic', cascade="all, delete")
    notifications = db.relationship('Notification', back_populates='kairanban', lazy='dynamic', cascade="all, delete")

# 6. Kairanban確認チェックモデル
class KairanbanCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    kairanban_id = db.Column(db.Integer, db.ForeignKey('kairanban.id', ondelete="CASCADE"), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='kairanban_checks')
    __table_args__ = (db.UniqueConstraint('user_id', 'kairanban_id', name='_user_kairanban_uc'),)


# Database Models
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(500), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True)
    icon_url = db.Column(db.String(200), nullable=True)
    affiliation = db.Column(db.String(100), nullable=True)
    grade = db.Column(db.String(50), nullable=True)      # 学年 (例: '1年', '大学院生')
    category = db.Column(db.String(50), nullable=True)   # 類 (例: 'I類', 'II類')
    user_class = db.Column(db.String(50), nullable=True) # クラス (例: '1クラス', 'Aクラス')
    program = db.Column(db.String(100), nullable=True)   # プログラム (例: 'メディア情報学プログラム')
    major = db.Column(db.String(100), nullable=True)
    #dark_mode = db.Column(db.Boolean, default=False)
    push_notifications_enabled = db.Column(db.Boolean, default=False)
    push_notifications_enabled = db.Column(db.Boolean, default=False)
    posts = db.relationship('Post', backref='author', lazy=True, cascade="all, delete")
    comments = db.relationship('Comment', backref='commenter', lazy=True)
    bookmarks = db.relationship('Bookmark', backref='user', lazy='dynamic')
    notifications = db.relationship('Notification', backref='recipient', lazy='dynamic')
    
    # ▼▼▼ [修正] 'user_tags' を使うように
    tags = db.relationship('Tag', secondary=user_tags, lazy='subquery',
        backref=db.backref('users', lazy=True), cascade="all, delete")
    # ▲▲▲ [修正] ここまで ▲▲▲
    
    def get_username_class(self):
        return 'admin-username' if self.is_admin else ''

    def has_unread_notifications(self):
        return self.notifications.filter_by(is_read=False).count() > 0

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    comments = db.relationship('Comment', backref='post', lazy=True, cascade="all, delete")
    bookmarks = db.relationship('Bookmark', backref='post', lazy='dynamic', cascade="all, delete")
    notifications = db.relationship('Notification', back_populates='post', lazy='dynamic', cascade="all, delete")
    
    tags = db.relationship('Tag', secondary=post_tags, lazy='subquery',
        backref=db.backref('posts', lazy=True), cascade="all, delete")
    
class UserSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    subscription_json = db.Column(db.Text, nullable=False) # JSON文字列として保存
    user = db.relationship('User', backref=db.backref('subscriptions', lazy='dynamic', cascade="all, delete"))
    

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)

class Bookmark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='_user_post_uc'),)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # 1. post_id を「必須ではない」に変更
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), nullable=True)
    
    # 2. kairanban_id を新しく追加 
    kairanban_id = db.Column(db.Integer, db.ForeignKey('kairanban.id', ondelete="CASCADE"), nullable=True)
    
    # 3. Postモデルへのリレーションシップを修正 (nullable=Trueに対応)
    post = db.relationship('Post', back_populates='notifications') # 元の行を変更

    # 4. Kairanbanモデルへのリレーションシップを新しく追加
    kairanban = db.relationship('Kairanban', back_populates='notifications')

# Routes
@app.route('/', defaults={'page': 1}, methods=['GET', 'POST'])
@app.route('/page/<int:page>', methods=['GET', 'POST'])
def index(page):
    form = PostForm()
    if form.validate_on_submit() and current_user.is_authenticated:
        image_url_str = None # 変数名を変更
        if form.image.data:
            image_url_str = save_picture(form.image.data)

        post = Post(title=form.title.data, content=form.content.data, author=current_user, image_url=image_url_str)
        post.tags = get_or_create_tags_from_string(form.tags.data)
        
        db.session.add(post)
        db.session.commit()
        return redirect(url_for('index'))

    posts_per_page = 40

    order_by_clause = func.coalesce(Post.updated_at, Post.created_at).desc()
    posts = Post.query.order_by(order_by_clause).paginate(
        page=page, per_page=posts_per_page, error_out=False
    )
    
    japan_tz = timezone('Asia/Tokyo')
    for post in posts.items:
        post.created_at_jst = post.created_at.replace(tzinfo=utc).astimezone(japan_tz)
        if post.updated_at:
            post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
        else:
            post.updated_at_jst = None
        
        post.is_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None if current_user.is_authenticated else False

    templates = []
    if current_user.is_authenticated:
        templates = [
            {
                'name': 'UECreview',
                'title': f'○年 ○期 {current_user.username}の授業review',
                'body': '<span class="text-large">**ここに科目名を入力**</span> 成績:<span class="text-red text-large">**ここに成績を入力**</span> 担当教員:ここに担当教員名を入力\n本文を入力'
            }
        ]
    
    # ▼▼▼ ★ 修正 ★ ▼▼▼ (search_form=search_form を削除)
    return render_template('index.html', form=form, posts=posts,  md=md, templates=templates, templates_for_js=json.dumps(templates))

@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    comment_form = CommentForm()

    if comment_form.validate_on_submit() and current_user.is_authenticated:
        comment = Comment(content=comment_form.content.data, post=post, commenter=current_user)
        db.session.add(comment)
        
        # 1. 投稿者に通知 (自分自身が投稿者でない場合)
        if current_user != post.author:
            notification = Notification(recipient=post.author, post=post, message=f'あなたの投稿「{post.title}」にコメントが付きました。')
            db.session.add(notification)
            send_web_push(
                post.author, 
                'コメントが付きました', 
                f'あなたの投稿「{post.title}」にコメントが付きました。',
                url_for('post_detail', post_id=post.id, _anchor=f'comment-{comment.id}', _external=True)
            )
        
        # 2. 他のコメント投稿者に通知
        # この投稿に（このコメント以前に）コメントしたユーザーを重複なく取得
        previous_commenters = db.session.query(User).join(Comment).filter(
            Comment.post_id == post.id
        ).distinct().all()

        # ▼▼▼ [修正] 通知ロジックをここに集約 ▼▼▼
        for user in previous_commenters:
            # 2a. 自分自身には通知しない
            if user.id == current_user.id:
                continue
            # 2b. 投稿者には（上記のロジックで）通知済みなのでスキップ
            if user.id == post.author.id:
                continue
            
            # 2c. 新しいコメントの投稿者が「記事の投稿者」である場合のみ通知
            if comment.commenter == post.author:
                notification = Notification(
                    recipient=user, 
                    post=post, 
                    message="あなたがコメントした投稿に投稿者がコメントしました。" # メッセージを少し変更
                )
                db.session.add(notification)
                send_web_push(
                    user,
                    '投稿者がコメントしました', # タイトルも変更
                    'あなたがコメントした投稿に記事の投稿者がコメントしました。',
                    url_for('post_detail', post_id=post.id, _anchor=f'comment-{comment.id}', _external=True)
                )
        
        db.session.commit()
        return redirect(url_for('post_detail', post_id=post.id, _anchor=f'comment-{comment.id}'))

    japan_tz = timezone('Asia/Tokyo')
    post.created_at_jst = post.created_at.replace(tzinfo=utc).astimezone(japan_tz)
    if post.updated_at:
        post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
    else:
        post.updated_at_jst = None

    for c in post.comments:
        c.created_at_jst = c.created_at.replace(tzinfo=utc).astimezone(japan_tz)
    
    post.is_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None if current_user.is_authenticated else False
    
    # ▼▼▼ ★ 修正 ★ ▼▼▼ (search_form=search_form を削除)
    return render_template('detail.html', post=post, comment_form=comment_form,  md=md)

@app.route('/bookmark_post/<int:post_id>', methods=['POST'])
@login_required
def bookmark_post(post_id):
    post = Post.query.get_or_404(post_id)
    bookmark = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first()
    
    if bookmark:
        db.session.delete(bookmark)
        is_bookmarked = False
    else:
        new_bookmark = Bookmark(user_id=current_user.id, post_id=post.id)
        if current_user != post.author:
            notification = Notification(recipient=post.author, post=post, message=f'あなたの投稿「{post.title}」がブックマークされました。')
            db.session.add(notification)
        is_bookmarked = True
        db.session.add(new_bookmark)
    
    db.session.commit()
    return jsonify(is_bookmarked=is_bookmarked)

@app.route('/bookmarks')
@login_required
def show_bookmarks():
    bookmarked_posts_query = Post.query.join(Bookmark, Post.id == Bookmark.post_id).filter(Bookmark.user_id == current_user.id).order_by(Bookmark.timestamp.desc())
    bookmarked_posts = bookmarked_posts_query.all()
    
    japan_tz = timezone('Asia/Tokyo')
    for post in bookmarked_posts:
        post.created_at_jst = post.created_at.replace(tzinfo=utc).astimezone(japan_tz)
        if post.updated_at:
            post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
        else:
            post.updated_at_jst = None
        post.is_bookmarked = True

    # ▼▼▼ ★ 修正 ★ ▼▼▼ (search_form=search_form を削除)
    return render_template('bookmarks.html', posts=bookmarked_posts, md=md)

@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        abort(403)

    form = PostForm() # まず空のフォームを作成

    if form.validate_on_submit():
        post.title = form.title.data
        post.content = form.content.data
        
        post.tags.clear()
        post.tags = get_or_create_tags_from_string(form.tags.data)
        
        if form.image.data:
            if post.image_url:
                delete_from_cloudinary(post.image_url)
            image_url_str = save_picture(form.image.data)
            post.image_url = image_url_str
            
        db.session.commit() # 投稿内容の変更をコミット

        # ▼▼▼ [修正] 通知ロジックをここに追加 ▼▼▼
        # この投稿をブックマークしているユーザーに通知
        for bookmark in post.bookmarks.all():
            # 編集者（自分）には通知しない
            if bookmark.user_id != current_user.id:
                notification = Notification(
                    recipient=bookmark.user,
                    post=post,
                    message="あなたがブックマークした投稿に変更がありました。"
                )
                db.session.add(notification)
                send_web_push(
                    bookmark.user,
                    '投稿が編集されました',
                    'あなたがブックマークした投稿に変更がありました。',
                    url_for('post_detail', post_id=post.id, _external=True)
                )
        
        db.session.commit() # 通知の追加をコミット
        # ▲▲▲ [修正] ここまで ▲▲▲

        return redirect(url_for('post_detail', post_id=post.id))

    elif request.method == 'GET': # GETリクエスト（ページを最初に開いた時）
        form.title.data = post.title
        form.content.data = post.content
        form.tags.data = ','.join([tag.name for tag in post.tags])

    templates = [
        {
            'name': 'UECreview',
            'title': f'○年 ○期 {current_user.username}の授業review',
            'body': '<span class="text-large">**ここに科目名を入力**</span> 成績:<span class="text-red text-large">**ここに成績を入力**</span> 担当教員:ここに担当教員名を入力\n本文を入力'
        }
    ]

    uec_review_data = parse_review_for_editing(post.content)
    uec_review_data_json = None
    if uec_review_data:
        uec_review_data_json = json.dumps(uec_review_data)
    
    return render_template('edit.html', form=form, post=post, md=md, templates=templates, templates_for_js=json.dumps(templates), uec_review_data_json=uec_review_data_json)

@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author == current_user or current_user.is_admin:
        if post.image_url:
            delete_from_cloudinary(post.image_url)
        db.session.delete(post)
        db.session.commit()
        return redirect(url_for('index'))
    else:
        abort(403)

@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    post_id = comment.post_id 
    if comment.commenter == current_user or comment.post.author == current_user or current_user.is_admin:
        db.session.delete(comment)
        db.session.commit()
        remaining_comments = Comment.query.filter_by(post_id=post_id).count()
        return jsonify({'status': 'success', 'remaining_comments': remaining_comments})
    else:
        abort(403)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegisterForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user:
            flash('そのユーザー名は既に使用されています。')
            return redirect(url_for('register'))
        hashed_password = generate_password_hash(form.password.data)
        new_user = User(username=form.username.data, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash('登録が完了しました。ログインしてください。')
        return redirect(url_for('login'))
    
    # ▼▼▼ ★ 修正 ★ ▼▼▼ (search_form=search_form を削除)
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember_me.data)
            return redirect(url_for('index'))
        else:
            flash('ユーザー名またはパスワードが正しくありません。')
            
    # ▼▼▼ ★ 修正 ★ ▼▼▼ (search_form=search_form を削除)
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/search', methods=['GET', 'POST'])
def search():
    search_query = None
    form = SearchForm()
    
    active_tab = request.args.get('active_tab', 'posts')
    post_page = request.args.get('post_page', 1, type=int)
    user_page = request.args.get('user_page', 1, type=int)

    if form.validate_on_submit():
        search_query = form.search_query.data
    elif request.method == 'GET' and request.args.get('search_query'):
        search_query = request.args.get('search_query')
        form.search_query.data = search_query

    posts = None
    users = None
    
    if search_query:
        
        # 1. 検索クエリと「完全一致」するタグがあるか探す
        tag_match = Tag.query.filter(Tag.name.ilike(search_query)).first()

        like_query = f'%{search_query}%'
        
        # 2. 投稿(Post)の検索クエリを構築 (ベース)
        posts_query_builder = Post.query.filter(
            (Post.title.like(like_query)) | (Post.content.like(like_query))
        )
        # ▼▼▼ [修正] 3. ユーザー(User)の検索クエリを修正
        users_query_builder = User.query.filter(
            or_(
                User.username.like(like_query), # 従来のユーザー名検索
                User.grade == search_query,       # ステータスタグ (完全一致)
                User.category == search_query,  # 
                User.user_class == search_query, # 
                User.program == search_query,    # 
                User.major == search_query       # 
            )
        )

        # 4. もし「タグ」が見つかったら、検索クエリに追加する
        if tag_match:
            post_tag_query = Post.query.join(post_tags).join(Tag).filter(Tag.id == tag_match.id)
            posts_query_builder = posts_query_builder.union(post_tag_query)
            user_tag_query = User.query.join(user_tags).join(Tag).filter(Tag.id == tag_match.id)
            users_query_builder = users_query_builder.union(user_tag_query)

        # 5. 構築したクエリを実行し、ページネーション
        posts = posts_query_builder.order_by(Post.created_at.desc()).paginate(
            page=post_page, per_page=40, error_out=False
        )
        users = users_query_builder.order_by(User.username.asc()).paginate(
            page=user_page, per_page=40, error_out=False
        )

        japan_tz = timezone('Asia/Tokyo')
        for post in posts.items:
            post.created_at_jst = post.created_at.replace(tzinfo=utc).astimezone(japan_tz)
            if post.updated_at:
                post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
            else:
                post.updated_at_jst = None
            if current_user.is_authenticated:
                post.is_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None
            else:
                post.is_bookmarked = False
    
    else:
        posts = db.paginate(db.select(Post).where(False), page=post_page, per_page=40, error_out=False)
        users = db.paginate(db.select(User).where(False), page=user_page, per_page=40, error_out=False)

    # ▼▼▼ ★ 修正 ★ ▼▼▼ (search_form=form は *削除しない*)
    return render_template('search_results.html',
                           search_form=form,
                           posts=posts,
                           users=users,
                           search_query=search_query,
                           active_tab=active_tab,
                           md=md)
@app.route('/profile/edit/<string:username>', methods=['GET', 'POST'])
@login_required
def edit_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user != current_user:
        abort(403)
    
    original_username = user.username
    
    form = ProfileForm(obj=user)
    
    if form.validate_on_submit():
        
        new_username = form.username.data
        
        user.username = new_username 
        user.bio = form.bio.data

        user.grade = form.grade.data
        user.category = form.category.data
        user.user_class = form.user_class.data
        user.program = form.program.data

        if user.grade == '大学院生':
            user.major = form.major.data
        else:
            user.major = None # 大学院生でなければ専攻はクリア
        
        user.tags.clear()
        user.tags = get_or_create_tags_from_string(form.tags.data)
        
        if form.icon.data:
            if user.icon_url:
                delete_from_cloudinary(user.icon_url)
            icon_url = save_icon(form.icon.data)
            user.icon_url = icon_url
        
        db.session.commit() 
        
        if original_username != new_username:
            logout_user() 
            flash(f'ユーザー名が「{new_username}」に変更されました。新しいユーザー名で再度ログインしてください。')
            return redirect(url_for('login'))
        else:
            return redirect(url_for('user_profile', username=user.username))

    elif request.method == 'GET':
        form.tags.data = ','.join([tag.name for tag in user.tags])
    
    # ▼▼▼ ★ 修正 ★ ▼▼▼ (search_form=search_form を削除)
    return render_template('edit_profile.html', form=form, user=user)

@app.route('/user/<string:username>')
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    
    active_tab = request.args.get('active_tab', 'posts')
    post_page = request.args.get('post_page', 1, type=int)
    comment_page = request.args.get('comment_page', 1, type=int)
    
    posts = Post.query.filter_by(author=user).order_by(Post.created_at.desc()).paginate(
        page=post_page, per_page=40, error_out=False
    )
    comments = Comment.query.filter_by(commenter=user).order_by(Comment.created_at.desc()).paginate(
        page=comment_page, per_page=40, error_out=False
    )
    
    japan_tz = timezone('Asia/Tokyo')
    for post in posts.items:
        post.created_at_jst = post.created_at.replace(tzinfo=utc).astimezone(japan_tz)
        if post.updated_at:
            post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
        else:
            post.updated_at_jst = None
        post.is_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None if current_user.is_authenticated else False
    for comment in comments.items:
        comment.created_at_jst = comment.created_at.replace(tzinfo=utc).astimezone(japan_tz)
    
    # ▼▼▼ ★ 修正 ★ ▼▼▼ (search_form=search_form を削除)
    return render_template('profile.html', user=user, posts=posts, comments=comments, active_tab=active_tab,  md=md)

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        abort(403)
    all_users = User.query.all()
    all_posts = Post.query.all()
    all_comments = Comment.query.all()
    
    # ▼▼▼ ★ 修正 ★ ▼▼▼ (search_form=search_form を削除)
    return render_template('admin_dashboard.html', users=all_users, posts=all_posts, comments=all_comments)

@app.route('/admin/delete_comment/<int:comment_id>', methods=['POST'])
@login_required
def admin_delete_comment(comment_id):
    if not current_user.is_admin:
        abort(403)
    comment = Comment.query.get_or_404(comment_id)
    db.session.delete(comment)
    db.session.commit()
    flash('コメントを削除しました。', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_post/<int:post_id>', methods=['POST'])
@login_required
def admin_delete_post(post_id):
    if not current_user.is_admin:
        abort(403)
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash('投稿を削除しました。')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin:
        abort(403)
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('ユーザーを削除しました。')
    return redirect(url_for('admin_dashboard'))

@app.route('/notifications')
@login_required
def show_notifications():
    notifications = Notification.query.filter_by(recipient=current_user).order_by(Notification.timestamp.desc()).all()
    
    for n in notifications:
        n.is_read = True
    db.session.commit()
    
    return render_template('notifications.html', notifications=notifications, md=md)


#  最近使用したタグ5件を返すAPI 
@app.route('/api/recent-tags')
@login_required
def get_recent_tags():
    # 1. 最近使われたタグ (last_used 順)
    recent_tags_query = Tag.query.order_by(Tag.last_used.desc()).limit(5).all()

    # 2. 人気のタグ (投稿数 順)
    # 投稿 (post_tags) とタグ (Tag) を結合し、投稿IDの数でグループ化・カウント
    popular_tags_query = db.session.query(
        Tag, func.count(post_tags.c.post_id).label('post_count')
    ).join(
        post_tags, Tag.id == post_tags.c.tag_id
    ).group_by(
        Tag.id
    ).order_by(
        func.count(post_tags.c.post_id).desc()
    ).limit(5).all()

    # 3. 結合と重複除去
    combined_tags = {} # dict を使って重複を名前で除去

    # まず最近のタグを入れる (優先)
    for tag in recent_tags_query:
        combined_tags[tag.name] = tag

    # 次に人気のタグを入れる (まだ入っていないものだけ)
    for tag, count in popular_tags_query:
        if tag.name not in combined_tags:
            combined_tags[tag.name] = tag

    # 4. 最終的なリストを返す (最大5件)
    tag_names = [tag.name for tag in combined_tags.values()][:5]

    return jsonify(tag_names)

@app.route('/kairanban', methods=['GET', 'POST'])
@login_required
def kairanban_index():
    """
    回覧板ページ (表示と作成)
    """
    
    # ▼▼▼ ★ 1. タイムゾーンの定義を追加 ★ ▼▼▼
    japan_tz = timezone('Asia/Tokyo')
    
    is_developer = False
    if current_user.is_authenticated and current_user.username == '二酸化ケイ素':
        is_developer = True

    form = KairanbanForm()
    
    # --- POST (回覧板の新規作成) ---
    if form.validate_on_submit(): # L997
        try:
            days = int(form.expires_in_days.data)
            expires_at_datetime = datetime.utcnow() + timedelta(days=days)
            
            new_kairanban = Kairanban(
                content=form.content.data,
                author=current_user,
                expires_at=expires_at_datetime
            )
            
            db.session.add(new_kairanban) # L1010
            
            # タグの処理
            new_kairanban.tags = get_or_create_tags_from_string(form.tags.data) # L1013
            
            db.session.flush() # new_kairanban.id を確定させる
            
            # 1. この回覧板に付けられたタグの「名前」リストを取得 (e.g. {'I類', 'B4'})
            target_tag_names = {tag.name for tag in new_kairanban.tags}

            recipients = []

            if target_tag_names:
                # 2a. カスタムタグ (user_tags) で一致するユーザーを検索
                custom_tag_recipients_query = User.query.join(user_tags).join(Tag).filter(
                    Tag.name.in_(target_tag_names)
                )
                
                # 2b. ステータスタグ (User.gradeなど) で一致するユーザーを検索
                status_tag_conditions = []
                for tag_name in target_tag_names:
                    status_tag_conditions.append(User.grade == tag_name)
                    status_tag_conditions.append(User.category == tag_name)
                    status_tag_conditions.append(User.user_class == tag_name)
                    status_tag_conditions.append(User.program == tag_name)
                    status_tag_conditions.append(User.major == tag_name)
                
                # or_ を使って、いずれかのステータスタグが一致するユーザーを検索
                status_tag_recipients_query = User.query.filter(or_(*status_tag_conditions))
                
                # 2c. クエリを結合(union)して重複を除外
                recipients = custom_tag_recipients_query.union(status_tag_recipients_query).distinct().all()

            # 3. 通知を作成 (作成者本人を除く)
            for user in recipients:
                if user.id != current_user.id:
                    notification = Notification(
                        recipient=user,
                        kairanban=new_kairanban, # リレーションシップ経由で設定
                        message=f'回覧板「{new_kairanban.content[:20]}...」が届きました。'
                    )
                    db.session.add(notification)
                    send_web_push(
                        user,
                        '新しい回覧板が届きました',
                        f'回覧板「{new_kairanban.content[:20]}...」が届きました。',
                        url_for('kairanban_index', _external=True)
                    )
            # ▲▲▲ [ここまでが修正箇所です] ▲▲▲
            
            db.session.commit() # L1057
            flash('回覧板を送信しました。')
            return redirect(url_for('kairanban_index'))
            
        except ValueError:
            flash('日数の値が無効です。')

    # --- GET (回覧板の一覧表示) ---
    
    # 期限切れでないものをベースクエリとする
    base_query = Kairanban.query.filter(Kairanban.expires_at > datetime.utcnow())
    
    # 閲覧権限のフィルタリング
    show_all = request.args.get('show_all')
    kairanbans_query = None

    if not current_user.is_authenticated:
        # 1. ログインしていない (要求仕様: すべて表示)
        kairanbans_query = base_query
    
    elif is_developer or show_all:
        # 2. 開発者または「すべて表示」が押された (すべて表示)
        kairanbans_query = base_query

    else:
        # 3. 通常のログインユーザー (タグが一致するもののみ表示)
        # ▼▼▼ [修正] このブロック(L1046-L1050)を丸ごと置き換え ▼▼▼
        
        # 3a. 自分の「ステータスタグ」をセットで取得
        user_status_tags = {
            current_user.grade, 
            current_user.category, 
            current_user.user_class, 
            current_user.program, 
            current_user.major
        }
        # 3b. 自分の「カスタムタグ」をセットで取得
        user_custom_tags = {tag.name for tag in current_user.tags}
        
        # 3c. 結合 (Noneや空文字を除外)
        user_all_tag_names = {tag for tag in user_status_tags.union(user_custom_tags) if tag}
        
        if user_all_tag_names:
            # 3d. タグ名(Tag.name)でKairanbanを検索
            kairanbans_query = base_query.join(kairanban_tags).join(Tag).filter(
                Tag.name.in_(user_all_tag_names)
            )
        else:
            # ユーザーがタグを持っていない
            kairanbans_query = base_query.filter(Kairanban.id < 0) # (空の結果を返す)
        # ▲▲▲ ここまで修正 ▲▲▲

    
    kairanbans = kairanbans_query.order_by(Kairanban.created_at.desc()).all() if kairanbans_query else []

    # ソート処理 (未チェックを上、チェック済みを下に)
    checked_ids = set()
    if current_user.is_authenticated:
        checked_ids = {c.kairanban_id for c in KairanbanCheck.query.filter_by(user_id=current_user.id)}
        
        # 1. 作成日で降順ソート
        kairanbans.sort(key=lambda k: k.created_at, reverse=True)
        # 2. チェック済み(True)が下に、未チェック(False)が上に来るようにソート
        kairanbans.sort(key=lambda k: k.id in checked_ids)
    for k in kairanbans:
        k.check_count = k.checks.count()

    status_tags = {
        'grade': {c[0] for c in GRADE_CHOICES if c[0]},
        'category': {c[0] for c in CATEGORY_CHOICES if c[0]},
        'class': {c[0] for c in CLASS_CHOICES if c[0]},
        'program': {c[0] for c in PROGRAM_CHOICES if c[0]},
        'major': {c[0] for c in MAJOR_CHOICES if c[0]},
    }

    
    # ▼▼▼ ★ 1. タイムゾーン変数をテンプレートに渡す ★ ▼▼▼
    return render_template('kairanban.html', form=form, kairanbans=kairanbans, checked_ids=checked_ids,japan_tz=japan_tz,utc=utc, show_all=show_all,status_tags=status_tags)

@app.route('/mailbox')
@login_required
def mailbox_index():
    """
    メールボックスページ (開発中)
    """
    return render_template('mailbox.html')

@app.route('/kairanban/check/<int:kairanban_id>', methods=['POST'])
@login_required
def check_kairanban(kairanban_id):
    kairanban = Kairanban.query.get_or_404(kairanban_id)
    
    # 既存のチェックを探す
    existing_check = KairanbanCheck.query.filter_by(
        user_id=current_user.id, 
        kairanban_id=kairanban_id
    ).first()
    
    is_checked = False
    
    if existing_check:
        # チェック済み -> 未チェックに戻す
        db.session.delete(existing_check)
        is_checked = False
    else:
        # 未チェック -> チェック済みにする
        new_check = KairanbanCheck(user_id=current_user.id, kairanban_id=kairanban_id)
        db.session.add(new_check)
        is_checked = True

    db.session.commit()
    new_count = kairanban.checks.count()
    return jsonify({'status': 'success', 'is_checked': is_checked, 'new_count': new_count})

@app.route('/kairanban/delete/<int:kairanban_id>', methods=['POST'])
@login_required
def delete_kairanban(kairanban_id):
    kairanban = Kairanban.query.get_or_404(kairanban_id)
    
    # 差出人本人 または 管理者 のみ削除可能
    if kairanban.author != current_user and not current_user.is_admin:
        abort(403) # 権限がありません
    
    db.session.delete(kairanban)
    db.session.commit()
    flash('回覧板を撤回しました。')
    return redirect(url_for('kairanban_index'))


# 2. Web Push 送信ヘルパー関数を追加
def send_web_push(user, title, body, url=None):
    """指定されたユーザーにWeb Push通知を送信する"""

    if not user.push_notifications_enabled:
        print(f"ユーザー {user.username} はプッシュ通知を無効にしています。")
        return
    
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
    VAPID_CLAIM_EMAIL = os.environ.get('VAPID_CLAIM_EMAIL')
    
    if not VAPID_PRIVATE_KEY or not VAPID_CLAIM_EMAIL:
        print("Web Push VAPIDキーが設定されていません。")
        return

    vapid_claims = {"sub": VAPID_CLAIM_EMAIL} # "mailto:" は不要になりました
    
    payload = {
        'title': title,
        'body': body,
        # _external=True で完全なURLを生成
        'icon': url_for('static', filename='icons/android-chrome-192x192.png', _external=True),
        'data': {
            'url': url or url_for('show_notifications', _external=True)
        }
    }
    payload_json = json.dumps(payload)

    subscriptions = user.subscriptions.all()
    
    for sub_model in subscriptions:
        try:
            subscription_info = json.loads(sub_model.subscription_json)
            webpush(
                subscription_info=subscription_info,
                data=payload_json,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=vapid_claims
            )
        except WebPushException as ex:
            print(f"Web Push送信エラー: {ex}")
            # 購読が無効になっている場合 (例: 410 Gone, 404 Not Found)
            if ex.response and (ex.response.status_code == 410 or ex.response.status_code == 404):
                print(f"購読ID {sub_model.id} は無効なため削除します。")
                db.session.delete(sub_model)
        except Exception as e:
            print(f"予期せぬエラー: {e}")
    
    db.session.commit() # 削除された購読情報をコミット

# 3. sw.js と manifest.json を配信するルートを追加
@app.route('/sw.js')
def service_worker():
    return app.send_static_file('sw.js')

@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

# 4. APIエンドポイント (VAPIDキー取得、購読) を追加
@app.route('/api/vapid_public_key')
@login_required
def get_vapid_public_key():
    public_key = os.environ.get('VAPID_PUBLIC_KEY')
    if not public_key:
        return jsonify({'error': 'VAPID public key not configured'}), 500
    return jsonify({'public_key': public_key})

@app.route('/api/subscribe', methods=['POST'])
@login_required
def subscribe():
    subscription_data = request.get_json()
    if not subscription_data:
        abort(400, 'No subscription data provided')

    subscription_json = json.dumps(subscription_data)
    
    # 既に同じ購読情報がないか確認 (endpointで判定)
    endpoint = subscription_data.get('endpoint')
    existing_sub = UserSubscription.query.filter(
        UserSubscription.subscription_json.like(f'%"{endpoint}"%')
    ).first()

    if existing_sub:
        # 既に存在する場合、ユーザーIDが一致するか確認
        if existing_sub.user_id == current_user.id:
            return jsonify({'status': 'already_subscribed'}), 200
        else:
            # 別のユーザーが使っていた場合は削除
            db.session.delete(existing_sub)
            
    new_sub = UserSubscription(user_id=current_user.id, subscription_json=subscription_json)
    db.session.add(new_sub)
    current_user.push_notifications_enabled = True
    db.session.commit()
    
    return jsonify({'status': 'success'}), 201

@app.route('/api/unsubscribe', methods=['POST'])
@login_required
def unsubscribe():
    subscription_data = request.get_json()
    if not subscription_data or 'endpoint' not in subscription_data:
        abort(400, 'No endpoint data provided')

    endpoint = subscription_data.get('endpoint')

    # エンドポイントに一致する購読情報を検索
    existing_sub = UserSubscription.query.filter(
        UserSubscription.user_id == current_user.id,
        UserSubscription.subscription_json.like(f'%"{endpoint}"%')
    ).first()

    if existing_sub:
        db.session.delete(existing_sub)
        print(f"購読ID {existing_sub.id} を削除しました。")
        
        # もし、このユーザーの他の購読情報が残っていなければ、
        # マスター設定を「無効」にする
        if current_user.subscriptions.count() == 0:
            current_user.push_notifications_enabled = False
            print(f"ユーザー {current_user.username} のプッシュ通知を無効化しました。")

        db.session.commit()
        return jsonify({'status': 'success (deleted)'}), 200
    
    # 既にDBにない場合も「成功」として扱う
    current_user.push_notifications_enabled = False
    db.session.commit()
    return jsonify({'status': 'success (not found)'}), 200

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = NotificationSettingsForm()
    settings_open = request.args.get('settings_open') == '1'
    
    if form.validate_on_submit():
        # (POSTリクエスト時)
        settings_open = True # POST時は開いたままにする
        
        # フォームのチェックボックスの状態をDBに保存
        current_user.push_notifications_enabled = form.enable_push.data
        db.session.commit()
        
        if not form.enable_push.data:
            # もしチェックを外した場合、関連する購読情報をすべて削除する
            UserSubscription.query.filter_by(user_id=current_user.id).delete()
            db.session.commit()
            flash('プッシュ通知を無効にし、すべての購読を解除しました。')
        else:
            flash('設定を更新しました。プッシュ通知を有効にするには、このページの機能でブラウザの許可設定を行ってください。')
        
        # ▼▼▼PRGパターンに戻し、トグル状態をクエリパラメータで渡す ▼▼▼
        return redirect(url_for('settings', settings_open=1))
       

    # (GETリクエスト時)
    # DBの状態をフォームのデフォルト値に設定
    form.enable_push.data = current_user.push_notifications_enabled
    
    # ▼▼▼ [修正] settings_open を渡す ▼▼▼
    return render_template('settings.html', form=form, settings_open=settings_open)

"""@app.route('/api/toggle_dark_mode', methods=['POST'])
@login_required
def toggle_dark_mode():
    try:
        current_user.dark_mode = not current_user.dark_mode
        db.session.commit()
        return jsonify({'status': 'success', 'dark_mode': current_user.dark_mode}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)"""