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
from forms import NotificationSettingsForm
import requests

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
    has_unread_kairanban = False 

    # 認証済みユーザーの場合のみ、開発者チェックと回覧板チェックを行う
    if current_user.is_authenticated:
        if current_user.username == '二酸化ケイ素':
            is_developer = True
        
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
        user_custom_tags = {tag.name for tag in current_user.tags} 
        
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
                    break 

    return dict(
        search_form=search_form, 
        is_developer=is_developer,
        has_unread_kairanban=has_unread_kairanban 
    )

# 1. アプリケーションで許可するHTMLタグを定義します
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'ol', 'ul', 'li', 'a', 'span', 'hr',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'code', 'blockquote',
]

# 2. 許可するタグに付随する属性を定義します
ALLOWED_ATTRIBUTES = {
    'a': ['href', 'target'], 
    'span': ['class']        
}

# 3. BleachのLinkerを設定
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

    # ステップ2: linkifyコールバックを定義
    def add_target_blank(attrs, new=False):
        attrs[(None, 'target')] = '_blank'
        return attrs

    # ステップ3: bleach.linkify() で先にリンク化する
    linked_html = bleach.linkify(
        html,
        callbacks=[add_target_blank],
        skip_tags=['a', 'pre', 'code'] 
    )

    # ステップ4: bleach.clean() で最後に全体を消毒する
    sanitized_html = bleach.clean(
        linked_html,
        tags=ALLOWED_TAGS,       
        attributes=ALLOWED_ATTRIBUTES
    )

    return sanitized_html

# タグ処理ヘルパー関数
def get_or_create_tags_from_string(tag_string):
    tag_objects = []
    if not tag_string:
        return tag_objects

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
    if not content.strip().startswith('<span class="text-large">**'):
        return None 

    subjects = []
    reviews = re.split(r'\n\s*---\s*\n', content.strip())
    
    pattern = re.compile(
        r'<span class="text-large">\*\*(.*?)\*\*</span>\s*'
        r'成績:<span class="text-red text-large">\*\*(.*?)\*\*</span>\s*'
        r'担当教員:(.*?)\n'
        r'(.*?)(?=\Z)', 
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
            
            subjects.append({
                'subject': subject.strip(),
                'grade': grade.strip(),
                'teacher': teacher.strip(),
                'body': body.strip()
            })

    return subjects if subjects else None

def save_picture(form_picture):
    upload_result = cloudinary.uploader.upload(form_picture, folder="post_images", width=500, height=500, crop="limit")
    return upload_result.get('secure_url')

def save_icon(form_icon):
    upload_result = cloudinary.uploader.upload(form_icon, 
                                               folder="profile_icons", 
                                               width=150, 
                                               height=150, 
                                               crop="fill", 
                                               gravity="face")
    return upload_result.get('secure_url')

def delete_from_cloudinary(image_url):
    if not image_url:
        return 
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

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    last_used = db.Column(db.DateTime, default=datetime.utcnow)

kairanban_tags = db.Table('kairanban_tags',
    db.Column('kairanban_id', db.Integer, db.ForeignKey('kairanban.id', ondelete="CASCADE"), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id', ondelete="CASCADE"), primary_key=True)
)

class Kairanban(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False) 
    author_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    
    author = db.relationship('User', backref='kairanbans')
    tags = db.relationship('Tag', secondary=kairanban_tags, lazy='subquery',
        backref=db.backref('kairanbans', lazy=True), cascade="all, delete")
    
    checks = db.relationship('KairanbanCheck', backref='kairanban', lazy='dynamic', cascade="all, delete")
    notifications = db.relationship('Notification', back_populates='kairanban', lazy='dynamic', cascade="all, delete")

class KairanbanCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    kairanban_id = db.Column(db.Integer, db.ForeignKey('kairanban.id', ondelete="CASCADE"), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='kairanban_checks')
    __table_args__ = (db.UniqueConstraint('user_id', 'kairanban_id', name='_user_kairanban_uc'),)


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
    posts = db.relationship('Post', backref='author', lazy=True, cascade="all, delete")
    comments = db.relationship('Comment', backref='commenter', lazy=True)
    bookmarks = db.relationship('Bookmark', backref='user', lazy='dynamic')
    notifications = db.relationship('Notification', backref='recipient', lazy='dynamic')
    
    tags = db.relationship('Tag', secondary=user_tags, lazy='subquery',
        backref=db.backref('users', lazy=True), cascade="all, delete")
    
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
    subscription_json = db.Column(db.Text, nullable=False)
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
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), nullable=True)
    kairanban_id = db.Column(db.Integer, db.ForeignKey('kairanban.id', ondelete="CASCADE"), nullable=True)
    
    post = db.relationship('Post', back_populates='notifications')
    kairanban = db.relationship('Kairanban', back_populates='notifications')

def send_onesignal_notification(user_ids, title, content, url=None):
    """OneSignal経由でプッシュ通知を送信"""
    try:
        api_key = os.environ.get('ONESIGNAL_API_KEY')
        app_id = os.environ.get('ONESIGNAL_APP_ID')
        
        if not api_key or not app_id:
            print("OneSignal API Key or App ID is missing.")
            return

        header = {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Basic {api_key}"
        }

        # user_ids はリスト形式 (例: ['5', '12'])
        target_ids = [str(uid) for uid in user_ids]

        payload = {
            "app_id": app_id,
            "headings": {"en": title},
            "contents": {"en": content},
            "include_aliases": {"external_id": target_ids}, # ステップ1で登録したID宛に送る
            "target_channel": "push",
        }
        
        if url:
            payload["url"] = url

        req = requests.post("https://onesignal.com/api/v1/notifications", headers=header, data=json.dumps(payload))
        print(f"OneSignal Response: {req.status_code} {req.text}")

    except Exception as e:
        print(f"OneSignal Error: {e}")

# Routes
@app.route('/', defaults={'page': 1}, methods=['GET', 'POST'])
@app.route('/page/<int:page>', methods=['GET', 'POST'])
def index(page):
    form = PostForm()
    if form.validate_on_submit() and current_user.is_authenticated:
        image_url_str = None 
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
    
    return render_template('index.html', form=form, posts=posts,  md=md, templates=templates, templates_for_js=json.dumps(templates))

@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    comment_form = CommentForm()

    if comment_form.validate_on_submit() and current_user.is_authenticated:
        comment = Comment(content=comment_form.content.data, post=post, commenter=current_user)
        db.session.add(comment)
        
        # サイト内通知の作成のみ (Web Push送信は削除)
        if current_user != post.author:
            notification = Notification(recipient=post.author, post=post, message=f'あなたの投稿「{post.title}」にコメントが付きました。')
            db.session.add(notification)

            send_onesignal_notification(
                user_ids=[post.author.id],
                title="新しいコメント",
                content=f"あなたの投稿「{post.title}」にコメントが付きました。",
                url=url_for('post_detail', post_id=post.id, _external=True)
            )
        
        previous_commenters = db.session.query(User).join(Comment).filter(
            Comment.post_id == post.id
        ).distinct().all()

        for user in previous_commenters:
            if user.id == current_user.id:
                continue
            if user.id == post.author.id:
                continue
            
            if comment.commenter == post.author:
                notification = Notification(
                    recipient=user, 
                    post=post, 
                    message="あなたがコメントした投稿に投稿者がコメントしました。" 
                )
                db.session.add(notification)
                send_onesignal_notification(
                    user_ids=[user.id],
                    title="コメントの返信",
                    content="あなたがコメントした投稿に投稿者がコメントしました。",
                    url=url_for('post_detail', post_id=post.id, _external=True)
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
            # サイト内通知の作成のみ
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

    return render_template('bookmarks.html', posts=bookmarked_posts, md=md)

@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        abort(403)

    form = PostForm()

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
            
        db.session.commit() 

        # サイト内通知の作成のみ (Web Push送信は削除)
        for bookmark in post.bookmarks.all():
            if bookmark.user_id != current_user.id:
                notification = Notification(
                    recipient=bookmark.user,
                    post=post,
                    message="あなたがブックマークした投稿に変更がありました。"
                )
                db.session.add(notification)
        
        db.session.commit() 

        return redirect(url_for('post_detail', post_id=post.id))

    elif request.method == 'GET': 
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
        tag_match = Tag.query.filter(Tag.name.ilike(search_query)).first()
        like_query = f'%{search_query}%'
        
        posts_query_builder = Post.query.filter(
            (Post.title.like(like_query)) | (Post.content.like(like_query))
        )
        users_query_builder = User.query.filter(
            or_(
                User.username.like(like_query), 
                User.grade == search_query,       
                User.category == search_query,  
                User.user_class == search_query, 
                User.program == search_query,    
                User.major == search_query       
            )
        )

        if tag_match:
            post_tag_query = Post.query.join(post_tags).join(Tag).filter(Tag.id == tag_match.id)
            posts_query_builder = posts_query_builder.union(post_tag_query)
            user_tag_query = User.query.join(user_tags).join(Tag).filter(Tag.id == tag_match.id)
            users_query_builder = users_query_builder.union(user_tag_query)

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
            user.major = None 
        
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
    
    return render_template('profile.html', user=user, posts=posts, comments=comments, active_tab=active_tab,  md=md)

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        abort(403)
    all_users = User.query.all()
    all_posts = Post.query.all()
    all_comments = Comment.query.all()
    
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


@app.route('/api/recent-tags')
@login_required
def get_recent_tags():
    recent_tags_query = Tag.query.order_by(Tag.last_used.desc()).limit(5).all()

    popular_tags_query = db.session.query(
        Tag, func.count(post_tags.c.post_id).label('post_count')
    ).join(
        post_tags, Tag.id == post_tags.c.tag_id
    ).group_by(
        Tag.id
    ).order_by(
        func.count(post_tags.c.post_id).desc()
    ).limit(5).all()

    combined_tags = {} 

    for tag in recent_tags_query:
        combined_tags[tag.name] = tag

    for tag, count in popular_tags_query:
        if tag.name not in combined_tags:
            combined_tags[tag.name] = tag

    tag_names = [tag.name for tag in combined_tags.values()][:5]

    return jsonify(tag_names)

@app.route('/kairanban', methods=['GET', 'POST'])
@login_required
def kairanban_index():
    """
    回覧板ページ (表示と作成)
    """
    japan_tz = timezone('Asia/Tokyo')
    
    is_developer = False
    if current_user.is_authenticated and current_user.username == '二酸化ケイ素':
        is_developer = True

    form = KairanbanForm()
    
    if form.validate_on_submit(): 
        try:
            days = int(form.expires_in_days.data)
            expires_at_datetime = datetime.utcnow() + timedelta(days=days)
            
            new_kairanban = Kairanban(
                content=form.content.data,
                author=current_user,
                expires_at=expires_at_datetime
            )
            
            db.session.add(new_kairanban) 
            new_kairanban.tags = get_or_create_tags_from_string(form.tags.data) 
            db.session.flush() 
            
            target_tag_names = {tag.name for tag in new_kairanban.tags}

            recipients = []

            if target_tag_names:
                custom_tag_recipients_query = User.query.join(user_tags).join(Tag).filter(
                    Tag.name.in_(target_tag_names)
                )
                
                status_tag_conditions = []
                for tag_name in target_tag_names:
                    status_tag_conditions.append(User.grade == tag_name)
                    status_tag_conditions.append(User.category == tag_name)
                    status_tag_conditions.append(User.user_class == tag_name)
                    status_tag_conditions.append(User.program == tag_name)
                    status_tag_conditions.append(User.major == tag_name)
                
                status_tag_recipients_query = User.query.filter(or_(*status_tag_conditions))
                recipients = custom_tag_recipients_query.union(status_tag_recipients_query).distinct().all()

            # サイト内通知の作成のみ (Web Push送信は削除)
            for user in recipients:
                if user.id != current_user.id:
                    notification = Notification(
                        recipient=user,
                        kairanban=new_kairanban, 
                        message=f'回覧板「{new_kairanban.content[:20]}...」が届きました。'
                    )
                    db.session.add(notification)
            
            db.session.commit()
            flash('回覧板を送信しました。')
            return redirect(url_for('kairanban_index'))
            
        except ValueError:
            flash('日数の値が無効です。')

    base_query = Kairanban.query.filter(Kairanban.expires_at > datetime.utcnow())
    
    show_all = request.args.get('show_all')
    kairanbans_query = None

    if not current_user.is_authenticated:
        kairanbans_query = base_query
    elif is_developer or show_all:
        kairanbans_query = base_query
    else:
        user_status_tags = {
            current_user.grade, 
            current_user.category, 
            current_user.user_class, 
            current_user.program, 
            current_user.major
        }
        user_custom_tags = {tag.name for tag in current_user.tags}
        user_all_tag_names = {tag for tag in user_status_tags.union(user_custom_tags) if tag}
        
        if user_all_tag_names:
            kairanbans_query = base_query.join(kairanban_tags).join(Tag).filter(
                Tag.name.in_(user_all_tag_names)
            )
        else:
            kairanbans_query = base_query.filter(Kairanban.id < 0) 

    
    kairanbans = kairanbans_query.order_by(Kairanban.created_at.desc()).all() if kairanbans_query else []

    checked_ids = set()
    if current_user.is_authenticated:
        checked_ids = {c.kairanban_id for c in KairanbanCheck.query.filter_by(user_id=current_user.id)}
        
        kairanbans.sort(key=lambda k: k.created_at, reverse=True)
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
    
    existing_check = KairanbanCheck.query.filter_by(
        user_id=current_user.id, 
        kairanban_id=kairanban_id
    ).first()
    
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
    
    if kairanban.author != current_user and not current_user.is_admin:
        abort(403) 
    
    db.session.delete(kairanban)
    db.session.commit()
    flash('回覧板を撤回しました。')
    return redirect(url_for('kairanban_index'))



@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = NotificationSettingsForm()
    settings_open = request.args.get('settings_open') == '1'
    
    if form.validate_on_submit():
        settings_open = True 
        current_user.push_notifications_enabled = form.enable_push.data
        db.session.commit()
        
        if not form.enable_push.data:
            UserSubscription.query.filter_by(user_id=current_user.id).delete()
            db.session.commit()
            flash('プッシュ通知設定を無効にしました。')
        else:
            flash('プッシュ通知設定を有効にしました。')
        
        return redirect(url_for('settings', settings_open=1))
       
    form.enable_push.data = current_user.push_notifications_enabled
    
    return render_template('settings.html', form=form, settings_open=settings_open)

# ▼▼▼ OneSignal用のService Workerを配信するルート ▼▼▼
@app.route('/OneSignalSDKWorker.js')
def onesignal_sdk_worker():
    return app.send_static_file('OneSignalSDKWorker.js')

if __name__ == '__main__':
    app.run(debug=True)