from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_, desc
from flask_migrate import Migrate, upgrade
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from pytz import timezone, utc
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass # 本番環境（Render）ではエラーを無視する
from flask_wtf.file import FileField, FileAllowed
from forms import (PostForm, CommentForm, RegisterForm, LoginForm, SearchForm, ProfileForm, KairanbanForm, 
                   GRADE_CHOICES, CATEGORY_CHOICES, CLASS_CHOICES, PROGRAM_CHOICES, MAJOR_CHOICES,
                   BooleanField, NotificationSettingsForm, GoalForm)
import markdown
import re
import json
from PIL import Image
import cloudinary
import cloudinary.uploader
import bleach
from bleach.linkifier import Linker
from forms import NotificationSettingsForm
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

cloudinary.config(
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'), 
    api_key = os.environ.get('CLOUDINARY_API_KEY'), 
    api_secret = os.environ.get('CLOUDINARY_API_SECRET'),
    secure = True
)

app = Flask(__name__)
import secrets
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(16))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///site.db')
db = SQLAlchemy(app)
md = markdown.Markdown(extensions=['nl2br'])
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@app.after_request
def add_header(response):
    """
    ブラウザやサーバーにページをキャッシュさせない設定。
    これにより、Aさんの画面がBさんに表示される事故を防ぎます。
    """
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

# --- OneSignalの設定 ---
app.config['ONESIGNAL_APP_ID'] = os.environ.get('ONESIGNAL_APP_ID')
app.config['ONESIGNAL_API_KEY'] = os.environ.get('ONESIGNAL_API_KEY')

ONESIGNAL_APP_ID = app.config['ONESIGNAL_APP_ID']
ONESIGNAL_API_KEY = app.config['ONESIGNAL_API_KEY']

@app.context_processor
def inject_common_vars():
    search_form = SearchForm()
    is_developer = False
    has_unread_kairanban = False 

    if current_user.is_authenticated:
        if current_user.username == '二酸化ケイ素':
            is_developer = True
        
        base_query = Kairanban.query.filter(Kairanban.expires_at > datetime.utcnow())
        user_status_tags = {
            current_user.grade, current_user.category, current_user.user_class, 
            current_user.program, current_user.major
        }
        user_custom_tags = {tag.name for tag in current_user.tags} 
        user_all_tag_names = {tag for tag in user_status_tags.union(user_custom_tags) if tag}

        if user_all_tag_names:
            target_kairanbans_query = base_query.join(kairanban_tags).join(Tag).filter(
                Tag.name.in_(user_all_tag_names)
            )
            checked_ids = {c.kairanban_id for c in KairanbanCheck.query.filter_by(user_id=current_user.id)}
            target_kairanbans = target_kairanbans_query.all()
            for k in target_kairanbans:
                if k.author_id != current_user.id and k.id not in checked_ids:
                    has_unread_kairanban = True
                    break 

    return dict(
        search_form=search_form, 
        is_developer=is_developer,
        has_unread_kairanban=has_unread_kairanban 
    )

ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'ol', 'ul', 'li', 'a', 'span', 'hr',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'code', 'blockquote',
]
ALLOWED_ATTRIBUTES = {'a': ['href', 'target'], 'span': ['class']}
linker = Linker(callbacks=[lambda attrs, new: attrs.update({(None, 'target'): '_blank'})])

@app.template_filter('safe_markdown')
def safe_markdown_filter(text):
    if not text: return ""

    def replace_mention(match):
        original_text = match.group(0) # 例: @二酸化ケイ素さん
        candidate = match.group(1)     # 例: 二酸化ケイ素さん
        
        # 1. そのままの名前でユーザーが存在するかチェック
        user = User.query.filter_by(username=candidate).first()
        if user:
            return f'[@{candidate}]({url_for("user_profile", username=candidate)})'
        
        # 2. 存在しない場合、末尾から1文字ずつ削ってチェックする (敬称対策)
        # 例: "二酸化ケイ素さん" -> "二酸化ケイ素" -> ヒット！
        for i in range(1, len(candidate)):
            sub_candidate = candidate[:-i]
            suffix = candidate[-i:] # 削った部分 (例: "さん")
            
            # 念のため1文字以下のユーザー名は無視するなどの制限も可能ですが、一旦そのまま検索
            user = User.query.filter_by(username=sub_candidate).first()
            if user:
                # ユーザー名部分はリンクにし、削った部分(敬称)はそのままテキストとして後ろにつける
                return f'[@{sub_candidate}]({url_for("user_profile", username=sub_candidate)}){suffix}'

        # 3. 結局見つからなければそのまま表示
        return original_text
    
    # 正規表現で @(...) をキャッチ
    text = re.sub(r'@([a-zA-Z0-9_一-龠ぁ-んァ-ヶー]+)', replace_mention, text)
    
    html = md.convert(text)
    def add_target_blank(attrs, new=False):
        attrs[(None, 'target')] = '_blank'
        return attrs
    linked_html = bleach.linkify(html, callbacks=[add_target_blank], skip_tags=['a', 'pre', 'code'])
    return bleach.clean(linked_html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)

def get_or_create_tags_from_string(tag_string):
    tag_objects = []
    if not tag_string: return tag_objects
    tag_names = [name.strip() for name in tag_string.split(',') if name.strip()]
    for name in tag_names:
        tag = Tag.query.filter_by(name=name).first()
        if not tag:
            tag = Tag(name=name, last_used=datetime.utcnow())
            db.session.add(tag)
        else:
            tag.last_used = datetime.utcnow()
        tag_objects.append(tag)
    db.session.commit()
    return tag_objects

def parse_review_for_editing(content):
    if not content.strip().startswith('<span class="text-large">**'): return None 
    subjects = []
    reviews = re.split(r'\n\s*---\s*\n', content.strip())
    pattern = re.compile(
        r'<span class="text-large">\*\*(.*?)\*\*</span>\s*成績:<span class="text-red text-large">\*\*(.*?)\*\*</span>\s*担当教員:(.*?)\n(.*?)(?=\Z)', 
        re.DOTALL 
    )
    placeholders = ['ここに科目名を入力', 'ここに担当教員名を入力', '本文を入力']
    for review_text in reviews:
        match = pattern.search(review_text.strip())
        if match:
            subject, grade, teacher, body = match.groups()
            subject = '' if subject == placeholders[0] else subject
            teacher = '' if teacher == placeholders[1] else teacher
            body = '' if body == placeholders[2] else body
            subjects.append({'subject': subject.strip(), 'grade': grade.strip(), 'teacher': teacher.strip(), 'body': body.strip()})
    return subjects if subjects else None

def save_picture(form_picture):
    upload_result = cloudinary.uploader.upload(
        form_picture, 
        folder="post_images", 
        width=2048, height=2048,
        crop="limit",
        quality="auto",       # 画質を人間の目に劣化がわからないレベルで自動調整
        fetch_format="auto"   # ブラウザに合わせて最適な形式(WebPなど)に変換
    )
    return upload_result.get('secure_url')

def save_icon(form_icon):
    upload_result = cloudinary.uploader.upload(form_icon, folder="profile_icons", width=150, height=150, crop="fill", gravity="face")
    return upload_result.get('secure_url')

def delete_from_cloudinary(image_url):
    if not image_url: return 
    try:
        public_id_with_ext = '/'.join(image_url.split('/')[-2:])
        public_id = os.path.splitext(public_id_with_ext)[0]
        cloudinary.uploader.destroy(public_id)
    except Exception as e:
        print(f"Error deleting image from Cloudinary: {e}")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Models
post_tags = db.Table('post_tags',
    db.Column('post_id', db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id', ondelete="CASCADE"), primary_key=True)
)
user_tags = db.Table('user_tags',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id', ondelete="CASCADE"), primary_key=True)
)
kairanban_tags = db.Table('kairanban_tags',
    db.Column('kairanban_id', db.Integer, db.ForeignKey('kairanban.id', ondelete="CASCADE"), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id', ondelete="CASCADE"), primary_key=True)
)

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    last_used = db.Column(db.DateTime, default=datetime.utcnow)

class Kairanban(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False) 
    author_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    author = db.relationship('User', backref='kairanbans')
    tags = db.relationship('Tag', secondary=kairanban_tags, lazy='subquery', backref=db.backref('kairanbans', lazy=True), cascade="all, delete")
    checks = db.relationship('KairanbanCheck', backref='kairanban', lazy='dynamic', cascade="all, delete")
    notifications = db.relationship('Notification', back_populates='kairanban', lazy='dynamic', cascade="all, delete")

class KairanbanCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    kairanban_id = db.Column(db.Integer, db.ForeignKey('kairanban.id', ondelete="CASCADE"), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='kairanban_checks')
    __table_args__ = (db.UniqueConstraint('user_id', 'kairanban_id', name='_user_kairanban_uc'),)

class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='_user_post_like_uc'),)

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(500), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True)
    icon_url = db.Column(db.String(200), nullable=True)
    affiliation = db.Column(db.String(100), nullable=True)
    grade = db.Column(db.String(50), nullable=True)
    category = db.Column(db.String(50), nullable=True)
    user_class = db.Column(db.String(50), nullable=True)
    program = db.Column(db.String(100), nullable=True)
    major = db.Column(db.String(100), nullable=True)
    push_notifications_enabled = db.Column(db.Boolean, default=False)
    notification_comment_like = db.Column(db.Boolean, default=True)
    notification_reply = db.Column(db.Boolean, default=True)
    
    posts = db.relationship('Post', backref='author', lazy=True, cascade="all, delete")
    comments = db.relationship('Comment', backref='commenter', lazy=True, cascade="all, delete")
    bookmarks = db.relationship('Bookmark', backref='user', lazy='dynamic', cascade="all, delete")
    notifications = db.relationship('Notification', backref='recipient', lazy='dynamic', cascade="all, delete")
    likes = db.relationship('Like', backref='user', lazy='dynamic', cascade="all, delete")
    tags = db.relationship('Tag', secondary=user_tags, lazy='subquery', backref=db.backref('users', lazy=True), cascade="all, delete")
    
    def get_username_class(self): return 'admin-username' if self.is_admin else ''
    def has_unread_notifications(self): return self.notifications.filter_by(is_read=False).count() > 0

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
    likes = db.relationship('Like', backref='post', lazy='dynamic', cascade="all, delete")
    tags = db.relationship('Tag', secondary=post_tags, lazy='subquery', backref=db.backref('posts', lazy=True), cascade="all, delete")

class UserSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    subscription_json = db.Column(db.Text, nullable=False)
    user = db.relationship('User', backref=db.backref('subscriptions', lazy='dynamic', cascade="all, delete"))

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id', ondelete="CASCADE"), nullable=True)
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy='dynamic', cascade="all, delete")

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
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), nullable=True)
    kairanban_id = db.Column(db.Integer, db.ForeignKey('kairanban.id', ondelete="CASCADE"), nullable=True)
    post = db.relationship('Post', back_populates='notifications')
    kairanban = db.relationship('Kairanban', back_populates='notifications')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref='received_messages')

class StudyLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    subject = db.Column(db.String(100), nullable=False) # 科目名
    duration = db.Column(db.Integer, nullable=False) # 分単位
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    
    user = db.relationship('User', backref='study_logs')

class FinanceLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    item_name = db.Column(db.String(100), nullable=False) # 項目名
    amount = db.Column(db.Integer, nullable=False) # 金額
    type = db.Column(db.String(10), nullable=False) # 'expense' (支出) or 'income' (収入)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    user = db.relationship('User', backref='finance_logs')

class Goal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    study_goal = db.Column(db.Integer, default=0) # 月間目標時間(分)
    savings_goal = db.Column(db.Integer, default=0) # 月間貯金目標(円)
    user = db.relationship('User', backref=db.backref('goal', uselist=False, cascade="all, delete"))

class ToDoItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    task = db.Column(db.String(200), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    due_date = db.Column(db.Date, nullable=True) 
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    user = db.relationship('User', backref='todos')
# --- OneSignal連携関数 ---
def send_onesignal_notification(user_ids, title, message, url=None):
    """OneSignalへプッシュ通知を送信 (requests版)"""
    if not ONESIGNAL_APP_ID or not ONESIGNAL_API_KEY:
        print("OneSignal Error: Keys are missing.")
        return

    header = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Basic {ONESIGNAL_API_KEY}"
    }
    target_external_user_ids = [f"user_{uid}" for uid in user_ids]
    payload = {
        "app_id": ONESIGNAL_APP_ID,
        "include_aliases": {"external_id": target_external_user_ids},
        "target_channel": "push",
        "headings": {"en": title},
        "contents": {"en": message},
        "url": url if url else ""
    }
    try:
        print(f"OneSignal Sending to: {target_external_user_ids}", flush=True)
        req = requests.post("https://onesignal.com/api/v1/notifications", headers=header, data=json.dumps(payload))
        print(f"OneSignal Response: {req.status_code} {req.text}", flush=True)
    except Exception as e:
        print(f"OneSignal Error: {e}", flush=True)

def process_mentions(content, source_obj):
    mentioned_names = set(re.findall(r'@([a-zA-Z0-9_一-龠ぁ-んァ-ヶー]+)', content))
    sender = current_user
    for name in mentioned_names:
        target_user = User.query.filter_by(username=name).first()
        if target_user and target_user != sender:
            if isinstance(source_obj, Post):
                message = f'{sender.username}さんが投稿であなたをメンションしました:「{source_obj.title}」'
                link_url = url_for('post_detail', post_id=source_obj.id, _external=True)
                n_post_id = source_obj.id
            elif isinstance(source_obj, Comment):
                message = f'{sender.username}さんがコメントであなたをメンションしました'
                link_url = url_for('post_detail', post_id=source_obj.post_id, _external=True)
                n_post_id = source_obj.post_id
            else: continue

            notification = Notification(
                recipient=target_user, 
                message=message, 
                post_id=n_post_id,
                is_read=False 
            )
            db.session.add(notification)
            
            if target_user.push_notifications_enabled:
                send_onesignal_notification(user_ids=[target_user.id], title="メンションされました", message=message, url=link_url)
    db.session.commit()

# Routes
@app.route('/', defaults={'page': 1}, methods=['GET', 'POST'])
@app.route('/page/<int:page>', methods=['GET', 'POST'])
def index(page):
    form = PostForm()
    if form.validate_on_submit() and current_user.is_authenticated:
        image_url_str = None 
        if form.image.data:
            file_size = len(form.image.data.read())
            form.image.data.seek(0) # 読み込んだカーソルを先頭に戻す（重要）
            
            if file_size > 500 * 1024:
                flash('画像サイズが大きすぎます(上限500KB)。圧縮してアップロードしてください。')
                return redirect(url_for('index'))
            image_url_str = save_picture(form.image.data)
        post = Post(title=form.title.data, content=form.content.data, author=current_user, image_url=image_url_str)
        post.tags = get_or_create_tags_from_string(form.tags.data)
        db.session.add(post)
        db.session.commit()
        process_mentions(post.content, post)
        return redirect(url_for('index'))

    posts_per_page = 40
    sort_by = request.args.get('sort_by', 'newest')
    query = Post.query
    if sort_by == 'likes':
        query = query.outerjoin(Like).group_by(Post.id).order_by(func.count(Like.id).desc(), Post.created_at.desc())
    elif sort_by == 'bookmarks':
        query = query.outerjoin(Bookmark).group_by(Post.id).order_by(func.count(Bookmark.id).desc(), Post.created_at.desc())
    else:
        query = query.order_by(func.coalesce(Post.updated_at, Post.created_at).desc())
        
    posts = query.paginate(page=page, per_page=posts_per_page, error_out=False)
    japan_tz = timezone('Asia/Tokyo')
    for post in posts.items:
        post.created_at_jst = post.created_at.replace(tzinfo=utc).astimezone(japan_tz)
        if post.updated_at:
            post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
        else: post.updated_at_jst = None
        if current_user.is_authenticated:
            post.is_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None
            post.is_liked = Like.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None
        else:
            post.is_bookmarked = False
            post.is_liked = False

    templates = []
    if current_user.is_authenticated:
        templates = [{'name': 'UECreview', 'title': f'○年 ○期 {current_user.username}の授業review', 'body': '<span class="text-large">**ここに科目名を入力**</span> 成績:<span class="text-red text-large">**ここに成績を入力**</span> 担当教員:ここに担当教員名を入力\n本文を入力'}]
    return render_template('index.html', form=form, posts=posts,  md=md, templates=templates, templates_for_js=json.dumps(templates), sort_by=sort_by)

@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    
    # クエリパラメータでソート順を取得 (デフォルトは 'oldest')
    sort_comments = request.args.get('sort_comments', 'oldest')
    
    # コメントの並び替え
    if sort_comments == 'newest':
        post.comments.sort(key=lambda c: c.created_at, reverse=True) # 新しい順
    else:
        post.comments.sort(key=lambda c: c.created_at, reverse=False) # 古い順 (デフォルト)

    comment_form = CommentForm()
    if comment_form.validate_on_submit() and current_user.is_authenticated:
        comment = Comment(content=comment_form.content.data, post=post, commenter=current_user)
        db.session.add(comment)
        db.session.commit()
        print(f"DEBUG: Comment by {current_user.id} on Post by {post.author.id}", flush=True)
        
        if current_user != post.author:
            if post.author.notification_comment_like:
                notification = Notification(recipient=post.author, post=post, message=f'あなたの投稿「{post.title}」にコメントが付きました。')
                db.session.add(notification)

                if post.author.push_notifications_enabled:
                    send_onesignal_notification(
                        user_ids=[post.author.id],
                        title="新しいコメント",
                        message=f'投稿「{post.title}」にコメントが付きました',
                        url=url_for('post_detail', post_id=post.id, _external=True)
                    )
        process_mentions(comment.content, comment)
        db.session.commit()
        return redirect(url_for('post_detail', post_id=post.id, _anchor=f'comment-{comment.id}'))
    
    japan_tz = timezone('Asia/Tokyo')
    post.created_at_jst = post.created_at.replace(tzinfo=utc).astimezone(japan_tz)
    if post.updated_at: post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
    else: post.updated_at_jst = None
    for c in post.comments: c.created_at_jst = c.created_at.replace(tzinfo=utc).astimezone(japan_tz)
    
    if current_user.is_authenticated:
        post.is_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None
        post.is_liked = Like.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None
    else:
        post.is_bookmarked = False
        post.is_liked = False
    
    # テンプレートに sort_comments を渡す
    return render_template('detail.html', post=post, comment_form=comment_form, md=md, sort_comments=sort_comments)

@app.route('/like/<int:post_id>', methods=['POST'])
@login_required
def toggle_like(post_id):
    post = Post.query.get_or_404(post_id)
    like = Like.query.filter_by(user_id=current_user.id, post_id=post.id).first()
    if like:
        db.session.delete(like)
        is_liked = False
    else:
        like = Like(user_id=current_user.id, post_id=post.id)
        db.session.add(like)
        is_liked = True
        if current_user != post.author:
            if post.author.notification_comment_like:
                message = f'あなたの投稿「{post.title}」にいいねが付きました。'
                notification = Notification(recipient=post.author, post=post, message=message)
                db.session.add(notification)
                if post.author.push_notifications_enabled:
                    send_onesignal_notification(user_ids=[post.author.id], title="新しいいいね", message=message, url=url_for('post_detail', post_id=post.id, _external=True))
    db.session.commit()
    return jsonify({'is_liked': is_liked, 'count': post.likes.count()})

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
        if post.updated_at: post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
        else: post.updated_at_jst = None
        post.is_bookmarked = True
        post.is_liked = Like.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None
    return render_template('bookmarks.html', posts=bookmarked_posts, md=md)

@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user: abort(403)
    form = PostForm()
    if form.validate_on_submit():
        post.title = form.title.data
        post.content = form.content.data
        post.tags.clear()
        post.tags = get_or_create_tags_from_string(form.tags.data)
        if form.image.data:
            file_size = len(form.image.data.read())
            form.image.data.seek(0)
            
            if file_size > 500 * 1024:
                flash('画像サイズが大きすぎます(上限500KB)。')
                return redirect(url_for('edit_post', post_id=post.id))
            if post.image_url: delete_from_cloudinary(post.image_url)
            image_url_str = save_picture(form.image.data)
            post.image_url = image_url_str
        db.session.commit() 
        for bookmark in post.bookmarks.all():
            if bookmark.user_id != current_user.id:
                notification = Notification(recipient=bookmark.user, post=post, message="あなたがブックマークした投稿に変更がありました。")
                db.session.add(notification)
        db.session.commit() 
        return redirect(url_for('post_detail', post_id=post.id))
    elif request.method == 'GET': 
        form.title.data = post.title
        form.content.data = post.content
        form.tags.data = ','.join([tag.name for tag in post.tags])
    templates = [{'name': 'UECreview', 'title': f'○年 ○期 {current_user.username}の授業review', 'body': '<span class="text-large">**ここに科目名を入力**</span> 成績:<span class="text-red text-large">**ここに成績を入力**</span> 担当教員:ここに担当教員名を入力\n本文を入力'}]
    uec_review_data = parse_review_for_editing(post.content)
    uec_review_data_json = None
    if uec_review_data: uec_review_data_json = json.dumps(uec_review_data)
    return render_template('edit.html', form=form, post=post, md=md, templates=templates, templates_for_js=json.dumps(templates), uec_review_data_json=uec_review_data_json)

@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author == current_user or current_user.is_admin:
        if post.image_url: delete_from_cloudinary(post.image_url)
        db.session.delete(post)
        db.session.commit()
        return redirect(url_for('index'))
    else: abort(403)

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
    else: abort(403)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('index'))
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
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember_me.data)
            return redirect(url_for('index'))
        else: flash('ユーザー名またはパスワードが正しくありません。')
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
    sort_by = request.args.get('sort_by', 'newest') 
    
    if form.validate_on_submit():
        search_query = form.search_query.data
    elif request.method == 'GET' and request.args.get('search_query'):
        search_query = request.args.get('search_query')
        form.search_query.data = search_query

    posts = None
    users = None
    
    if search_query:
        tag_match = Tag.query.filter(Tag.name.ilike(search_query)).first()
        like_query = f'%{search_query}%'
        posts_query_builder = Post.query.filter((Post.title.like(like_query)) | (Post.content.like(like_query)))
        users_query_builder = User.query.filter(or_(User.username.like(like_query), User.grade == search_query, User.category == search_query, User.user_class == search_query, User.program == search_query, User.major == search_query))
        if tag_match:
            post_tag_query = Post.query.join(post_tags).join(Tag).filter(Tag.id == tag_match.id)
            posts_query_builder = posts_query_builder.union(post_tag_query)
            user_tag_query = User.query.join(user_tags).join(Tag).filter(Tag.id == tag_match.id)
            users_query_builder = users_query_builder.union(user_tag_query)

        if sort_by == 'likes':
            posts = posts_query_builder.outerjoin(Like).group_by(Post.id).order_by(func.count(Like.id).desc(), Post.created_at.desc())
        elif sort_by == 'bookmarks':
            posts = posts_query_builder.outerjoin(Bookmark).group_by(Post.id).order_by(func.count(Bookmark.id).desc(), Post.created_at.desc())
        else:
            posts = posts_query_builder.order_by(Post.created_at.desc())

        posts = posts.paginate(page=post_page, per_page=40, error_out=False)
        users = users_query_builder.order_by(User.username.asc()).paginate(page=user_page, per_page=40, error_out=False)
        japan_tz = timezone('Asia/Tokyo')
        for post in posts.items:
            post.created_at_jst = post.created_at.replace(tzinfo=utc).astimezone(japan_tz)
            if post.updated_at: post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
            else: post.updated_at_jst = None
            if current_user.is_authenticated:
                post.is_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None
                post.is_liked = Like.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None
            else:
                post.is_bookmarked = False
                post.is_liked = False
    else:
        posts = db.paginate(db.select(Post).where(False), page=post_page, per_page=40, error_out=False)
        users = db.paginate(db.select(User).where(False), page=user_page, per_page=40, error_out=False)

    return render_template('search_results.html', search_form=form, posts=posts, users=users, search_query=search_query, active_tab=active_tab, md=md, sort_by=sort_by)

@app.route('/profile/edit/<string:username>', methods=['GET', 'POST'])
@login_required
def edit_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user != current_user: abort(403)
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
        if user.grade == '大学院生': user.major = form.major.data
        else: user.major = None 
        user.tags.clear()
        user.tags = get_or_create_tags_from_string(form.tags.data)
        if form.icon.data:
            if user.icon_url: delete_from_cloudinary(user.icon_url)
            icon_url = save_icon(form.icon.data)
            user.icon_url = icon_url
        db.session.commit() 
        if original_username != new_username:
            logout_user() 
            flash(f'ユーザー名が「{new_username}」に変更されました。新しいユーザー名で再度ログインしてください。')
            return redirect(url_for('login'))
        else: return redirect(url_for('user_profile', username=user.username))
    elif request.method == 'GET': form.tags.data = ','.join([tag.name for tag in user.tags])
    return render_template('edit_profile.html', form=form, user=user)

@app.route('/user/<string:username>')
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    active_tab = request.args.get('active_tab', 'posts')
    post_page = request.args.get('post_page', 1, type=int)
    comment_page = request.args.get('comment_page', 1, type=int)
    posts = Post.query.filter_by(author=user).order_by(Post.created_at.desc()).paginate(page=post_page, per_page=40, error_out=False)
    comments = Comment.query.filter_by(commenter=user).order_by(Comment.created_at.desc()).paginate(page=comment_page, per_page=40, error_out=False)
    japan_tz = timezone('Asia/Tokyo')
    for post in posts.items:
        post.created_at_jst = post.created_at.replace(tzinfo=utc).astimezone(japan_tz)
        if post.updated_at: post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
        else: post.updated_at_jst = None
        post.is_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None if current_user.is_authenticated else False
        post.is_liked = Like.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None if current_user.is_authenticated else False 
    for comment in comments.items:
        comment.created_at_jst = comment.created_at.replace(tzinfo=utc).astimezone(japan_tz)
    return render_template('profile.html', user=user, posts=posts, comments=comments, active_tab=active_tab,  md=md)

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin: abort(403)
    all_users = User.query.all()
    all_posts = Post.query.all()
    all_comments = Comment.query.all()
    return render_template('admin_dashboard.html', users=all_users, posts=all_posts, comments=all_comments)

@app.route('/admin/delete_comment/<int:comment_id>', methods=['POST'])
@login_required
def admin_delete_comment(comment_id):
    if not current_user.is_admin: abort(403)
    comment = Comment.query.get_or_404(comment_id)
    db.session.delete(comment)
    db.session.commit()
    flash('コメントを削除しました。', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_post/<int:post_id>', methods=['POST'])
@login_required
def admin_delete_post(post_id):
    if not current_user.is_admin: abort(403)
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash('投稿を削除しました。')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin: abort(403)
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('ユーザーを削除しました。')
    return redirect(url_for('admin_dashboard'))


@app.route('/notifications')
@login_required
def show_notifications():
    notifications = Notification.query.filter_by(recipient=current_user).order_by(Notification.timestamp.desc()).all()
    for n in notifications: n.is_read = True
    db.session.commit()
    return render_template('notifications.html', notifications=notifications, md=md)

@app.route('/api/recent-tags')
@login_required
def get_recent_tags():
    recent_tags_query = Tag.query.order_by(Tag.last_used.desc()).limit(5).all()
    popular_tags_query = db.session.query(Tag, func.count(post_tags.c.post_id).label('post_count')).join(post_tags, Tag.id == post_tags.c.tag_id).group_by(Tag.id).order_by(func.count(post_tags.c.post_id).desc()).limit(5).all()
    combined_tags = {} 
    for tag in recent_tags_query: combined_tags[tag.name] = tag
    for tag, count in popular_tags_query:
        if tag.name not in combined_tags: combined_tags[tag.name] = tag
    tag_names = [tag.name for tag in combined_tags.values()][:5]
    return jsonify(tag_names)

@app.route('/kairanban', methods=['GET', 'POST'])
@login_required
def kairanban_index():
    japan_tz = timezone('Asia/Tokyo')
    is_developer = False
    if current_user.is_authenticated and current_user.username == '二酸化ケイ素': is_developer = True
    form = KairanbanForm()
    if form.validate_on_submit(): 
        try:
            days = int(form.expires_in_days.data)
            expires_at_datetime = datetime.utcnow() + timedelta(days=days)
            new_kairanban = Kairanban(content=form.content.data, author=current_user, expires_at=expires_at_datetime)
            db.session.add(new_kairanban) 
            new_kairanban.tags = get_or_create_tags_from_string(form.tags.data) 
            db.session.flush() 
            target_tag_names = {tag.name for tag in new_kairanban.tags}
            recipients = []
            if target_tag_names:
                custom_tag_recipients_query = User.query.join(user_tags).join(Tag).filter(Tag.name.in_(target_tag_names))
                status_tag_conditions = []
                for tag_name in target_tag_names:
                    status_tag_conditions.append(User.grade == tag_name)
                    status_tag_conditions.append(User.category == tag_name)
                    status_tag_conditions.append(User.user_class == tag_name)
                    status_tag_conditions.append(User.program == tag_name)
                    status_tag_conditions.append(User.major == tag_name)
                status_tag_recipients_query = User.query.filter(or_(*status_tag_conditions))
                recipients = custom_tag_recipients_query.union(status_tag_recipients_query).distinct().all()
            recipient_ids_for_push = []
            for user in recipients:
                if user.id != current_user.id:
                    notification = Notification(recipient=user, kairanban=new_kairanban, message=f'回覧板「{new_kairanban.content[:20]}...」が届きました。')
                    db.session.add(notification)
                    if user.push_notifications_enabled: recipient_ids_for_push.append(user.id)
            if recipient_ids_for_push:
                send_onesignal_notification(user_ids=recipient_ids_for_push, title="新しい回覧板", message=f'回覧板「{new_kairanban.content[:20]}...」が届きました', url=url_for('kairanban_index', _external=True))
            db.session.commit()
            flash('回覧板を送信しました。')
            return redirect(url_for('kairanban_index'))
        except ValueError: flash('日数の値が無効です。')
    
    base_query = Kairanban.query.filter(Kairanban.expires_at > datetime.utcnow())
    show_all = request.args.get('show_all')
    kairanbans_query = None
    if not current_user.is_authenticated: kairanbans_query = base_query
    elif is_developer or show_all: kairanbans_query = base_query
    else:
        user_status_tags = {current_user.grade, current_user.category, current_user.user_class, current_user.program, current_user.major}
        user_custom_tags = {tag.name for tag in current_user.tags}
        user_all_tag_names = {tag for tag in user_status_tags.union(user_custom_tags) if tag}
        if user_all_tag_names:
            kairanbans_query = base_query.join(kairanban_tags).join(Tag).filter(Tag.name.in_(user_all_tag_names))
        else: kairanbans_query = base_query.filter(Kairanban.id < 0) 
    
    kairanbans = kairanbans_query.order_by(Kairanban.created_at.desc()).all() if kairanbans_query else []
    checked_ids = set()
    if current_user.is_authenticated:
        checked_ids = {c.kairanban_id for c in KairanbanCheck.query.filter_by(user_id=current_user.id)}
        kairanbans.sort(key=lambda k: k.created_at, reverse=True)
        kairanbans.sort(key=lambda k: k.id in checked_ids)
    for k in kairanbans: k.check_count = k.checks.count()
    status_tags = {'grade': {c[0] for c in GRADE_CHOICES if c[0]}, 'category': {c[0] for c in CATEGORY_CHOICES if c[0]}, 'class': {c[0] for c in CLASS_CHOICES if c[0]}, 'program': {c[0] for c in PROGRAM_CHOICES if c[0]}, 'major': {c[0] for c in MAJOR_CHOICES if c[0]}}
    return render_template('kairanban.html', form=form, kairanbans=kairanbans, checked_ids=checked_ids,japan_tz=japan_tz,utc=utc, show_all=show_all,status_tags=status_tags)

@app.route('/hub')
@login_required
def hub_index():
    # 天気予報や学習記録のデータがあればここで取得して渡す
    return render_template('multifunctionalhub.html')

@app.route('/kairanban/check/<int:kairanban_id>', methods=['POST'])
@login_required
def check_kairanban(kairanban_id):
    kairanban = Kairanban.query.get_or_404(kairanban_id)
    existing_check = KairanbanCheck.query.filter_by(user_id=current_user.id, kairanban_id=kairanban_id).first()
    is_checked = False
    if existing_check:
        db.session.delete(existing_check)
        is_checked = False
    else:
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
    if kairanban.author != current_user and not current_user.is_admin: abort(403) 
    db.session.delete(kairanban)
    db.session.commit()
    flash('回覧板を撤回しました。')
    return redirect(url_for('kairanban_index'))

@app.route('/manifest.json')
def manifest(): return app.send_static_file('manifest.json')

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = NotificationSettingsForm()
    settings_open = request.args.get('settings_open') == '1'
    if form.validate_on_submit():
        settings_open = True 
        current_user.push_notifications_enabled = form.enable_push.data
        current_user.notification_comment_like = form.enable_comment_like.data
        current_user.notification_reply = form.enable_reply.data
        db.session.commit()
        if not form.enable_push.data:
            UserSubscription.query.filter_by(user_id=current_user.id).delete()
            db.session.commit()
            flash('プッシュ通知設定を無効にしました。')
        else: flash('プッシュ通知設定を有効にしました。')
        return redirect(url_for('settings', settings_open=1))
    form.enable_push.data = current_user.push_notifications_enabled
    form.enable_comment_like.data = current_user.notification_comment_like
    form.enable_reply.data = current_user.notification_reply
    return render_template('settings.html', form=form, settings_open=settings_open)

@app.route('/OneSignalSDKWorker.js')
def onesignal_worker(): return app.send_static_file('OneSignalSDKWorker.js')

@app.route('/api/ogp')
def get_ogp():
    url = request.args.get('url')
    if not url: return jsonify({'error': 'No URL provided'}), 400
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        resp = requests.get(url, headers=headers, timeout=3)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            og_title = soup.find('meta', property='og:title')
            og_image = soup.find('meta', property='og:image')
            og_desc = soup.find('meta', property='og:description')
            title = og_title['content'] if og_title else (soup.title.string if soup.title else url)
            image = og_image['content'] if og_image else None
            description = og_desc['content'] if og_desc else ''
            
            parsed = urlparse(url)
            domain = parsed.netloc
            if not title: title = domain
            if not image:
                if domain in ['x.com', 'twitter.com', 'www.x.com', 'www.twitter.com']:
                    path_parts = parsed.path.strip('/').split('/')
                    if len(path_parts) >= 1:
                        username = path_parts[0]
                        image = f"https://unavatar.io/twitter/{username}"
                if not image:
                    image = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
            
            return jsonify({'title': title, 'image': image, 'description': description, 'url': url})
    except Exception as e:
        print(f"OGP Fetch Error: {e}")
        return jsonify({'error': 'Failed to fetch'}), 400
    
# ▼▼▼ 学習記録機能用のルート ▼▼▼
# ▼▼▼ 学習記録API (削除機能を追加) ▼▼▼
@app.route('/api/study_log', methods=['GET', 'POST'])
@login_required
def api_study_log():
    if request.method == 'POST':
        data = request.get_json()
        
        # 削除アクションの場合
        if data.get('action') == 'delete':
            log_id = data.get('id')
            log = StudyLog.query.get(log_id)
            if log and log.user_id == current_user.id:
                db.session.delete(log) # これで完全に消えます
                db.session.commit()
                return jsonify({'status': 'success'})
            return jsonify({'error': 'Not found'}), 404

        # 登録アクションの場合
        subject = data.get('subject')
        duration = data.get('duration')
        
        if not subject or not duration:
            return jsonify({'error': 'Invalid data'}), 400
            
        try:
            duration_int = int(duration)
            new_log = StudyLog(user_id=current_user.id, subject=subject, duration=duration_int)
            db.session.add(new_log)
            db.session.commit()
            return jsonify({'status': 'success', 'message': '記録しました'})
        except ValueError:
            return jsonify({'error': 'Invalid duration'}), 400

    elif request.method == 'GET':
        # 直近20件を取得
        logs = StudyLog.query.filter_by(user_id=current_user.id).order_by(StudyLog.timestamp.desc()).limit(20).all()
        
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_logs = StudyLog.query.filter(StudyLog.user_id == current_user.id, StudyLog.timestamp >= today_start).all()
        total_minutes = sum(log.duration for log in today_logs)
        
        log_list = [{
            'id': log.id, # 削除用にIDも返す
            'subject': log.subject,
            'duration': log.duration,
            'date': log.timestamp.replace(tzinfo=utc).astimezone(timezone('Asia/Tokyo')).strftime('%m/%d %H:%M')
        } for log in logs]
        
        return jsonify({'logs': log_list, 'total_today': total_minutes})

@app.route('/activity_log')
@login_required
def activity_log_page():
    return render_template('activity_log.html')

# ▼▼▼ToDo API ▼▼▼
@app.route('/api/todo', methods=['GET', 'POST'])
@login_required
def api_todo():
    if request.method == 'POST':
        data = request.get_json()
        action = data.get('action')
        
        if action == 'add':
            task_content = data.get('task')
            date_str = data.get('date') # 日付文字列 (YYYY-MM-DD)
            
            # 日付変換処理
            due_date_obj = None
            if date_str:
                try:
                    due_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    pass # 日付形式がおかしい場合は無視（None）

            new_todo = ToDoItem(user_id=current_user.id, task=task_content, due_date=due_date_obj)
            db.session.add(new_todo)
            
        elif action == 'toggle':
            todo = ToDoItem.query.get(data.get('id'))
            if todo and todo.user_id == current_user.id:
                todo.is_completed = not todo.is_completed
        elif action == 'delete':
            todo = ToDoItem.query.get(data.get('id'))
            if todo and todo.user_id == current_user.id:
                db.session.delete(todo)
                
        db.session.commit()
        return jsonify({'status': 'success'})

    # GET
    todos = ToDoItem.query.filter_by(user_id=current_user.id).order_by(ToDoItem.timestamp.desc()).all()
    return jsonify([{
        'id': t.id, 
        'task': t.task, 
        'is_completed': t.is_completed,
        # 日付があれば文字列化して返す
        'date': t.due_date.strftime('%Y/%m/%d') if t.due_date else None
    } for t in todos])

# ▼▼▼目標設定ページ ▼▼▼
@app.route('/activity_log/settings', methods=['GET', 'POST'])
@login_required
def activity_settings():
    # ユーザーの目標を取得、なければ作成
    goal = current_user.goal
    if not goal:
        goal = Goal(user_id=current_user.id)
        db.session.add(goal)
        db.session.commit()
    
    form = GoalForm(obj=goal)
    if form.validate_on_submit():
        goal.study_goal = form.study_goal.data
        goal.savings_goal = form.savings_goal.data
        db.session.commit()
        flash('目標を更新しました！')
        return redirect(url_for('activity_log_page'))
        
    return render_template('activity_settings.html', form=form)

# ▼▼▼  活動状況のサマリーAPI (トップ部分用) ▼▼▼
@app.route('/api/activity_summary')
@login_required
def api_activity_summary():
    # 1. 今月の学習時間
    start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    study_logs = StudyLog.query.filter(StudyLog.user_id == current_user.id, StudyLog.timestamp >= start_of_month).all()
    current_study_min = sum(log.duration for log in study_logs)
    
    # 2. 財務 (今月の収支 & 全期間の総資産)
    finance_logs_month = FinanceLog.query.filter(FinanceLog.user_id == current_user.id, FinanceLog.timestamp >= start_of_month).all()
    month_income = sum(l.amount for l in finance_logs_month if l.type == 'income')
    month_expense = sum(l.amount for l in finance_logs_month if l.type == 'expense')
    month_balance = month_income - month_expense
    
    all_finance = FinanceLog.query.filter_by(user_id=current_user.id).all()
    total_income = sum(l.amount for l in all_finance if l.type == 'income')
    total_expense = sum(l.amount for l in all_finance if l.type == 'expense')
    total_assets = total_income - total_expense

    # 3. 継続日数 (簡易的に「記録があるユニークな日数」または「最終更新からの連続」など。ここでは今月の記録日数)
    # 学習または財務の記録がある日を数える
    active_days = set()
    for l in study_logs: active_days.add(l.timestamp.date())
    for l in finance_logs_month: active_days.add(l.timestamp.date())
    streak_days = len(active_days)

    # 4. ToDo消化率
    todos = ToDoItem.query.filter_by(user_id=current_user.id).all()
    total_todos = len(todos)
    done_todos = len([t for t in todos if t.is_completed])
    
    # 目標取得
    goal = current_user.goal
    study_target = goal.study_goal if goal else 0
    savings_target = goal.savings_goal if goal else 0

    return jsonify({
        'study': {'current': current_study_min, 'target': study_target},
        'finance': {'month_balance': month_balance, 'total_assets': total_assets, 'target': savings_target},
        'streak': streak_days,
        'todo': {'done': done_todos, 'total': total_todos}
    })

# ▼▼▼ 財務API ▼▼▼
@app.route('/api/finance', methods=['GET', 'POST'])
@login_required
def api_finance():
    if request.method == 'POST':
        data = request.get_json()
        
        # 削除アクション
        if data.get('action') == 'delete':
            log_id = data.get('id')
            log = FinanceLog.query.get(log_id)
            if log and log.user_id == current_user.id:
                db.session.delete(log) # これで完全に消えます
                db.session.commit()
                return jsonify({'status': 'success'})
            return jsonify({'error': 'Not found'}), 404

        # 登録アクション
        try:
            amount = int(data.get('amount'))
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid amount'}), 400

        new_log = FinanceLog(
            user_id=current_user.id,
            item_name=data.get('item_name'),
            amount=amount,
            type=data.get('type')
        )
        db.session.add(new_log)
        db.session.commit()
        return jsonify({'status': 'success'})
    
    # GET
    start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_logs = FinanceLog.query.filter(FinanceLog.user_id == current_user.id, FinanceLog.timestamp >= start_of_month).all()
    m_income = sum(l.amount for l in monthly_logs if l.type == 'income')
    m_expense = sum(l.amount for l in monthly_logs if l.type == 'expense')
    month_total = m_income - m_expense

    logs = FinanceLog.query.filter_by(user_id=current_user.id).order_by(FinanceLog.timestamp.desc()).limit(20).all()
    log_list = [{
        'id': l.id, # 削除用にIDも返す
        'item': l.item_name, 'amount': l.amount, 'type': l.type,
        'date': l.timestamp.replace(tzinfo=utc).astimezone(timezone('Asia/Tokyo')).strftime('%m/%d')
    } for l in logs]
    
    return jsonify({'logs': log_list, 'month_total': month_total})



if __name__ == '__main__':
    app.run(debug=True)