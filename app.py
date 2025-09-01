from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from pytz import timezone, utc
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
import os
from flask_wtf.file import FileField, FileAllowed
from forms import PostForm, CommentForm, RegisterForm, LoginForm, SearchForm, ProfileForm
import markdown
import re
import json

# ▼▼▼ ここに貼り付ける ▼▼▼
def linkify_urls(text):
    """テキスト内のURLを<a>タグに変換する関数"""
    url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
    return re.sub(
        url_pattern,
        lambda match: f'<a href="{match.group(0)}" target="_blank">{match.group(0)}</a>',
        text
    )
# ▲▲▲ ここまで ▲▲▲

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///site.db')
db = SQLAlchemy(app)
md = markdown.Markdown() # md変数にMarkdownのインスタンスを代入
migrate = Migrate(app, db)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# データベースモデルの定義
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(500), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True)
    icon_url = db.Column(db.String(200), nullable=True)
    posts = db.relationship(
        'Post', 
        backref='author', 
        lazy=True, 
        cascade="all, delete", 
    )
    comments = db.relationship('Comment', backref='commenter', lazy=True)
    bookmarks = db.relationship('Bookmark', backref='user', lazy='dynamic')
    notifications = db.relationship('Notification', backref='recipient', lazy='dynamic')

    def get_username_class(self):
        if self.is_admin:
            return 'admin-username'
        return ''

    def has_unread_notifications(self):
        return self.notifications.filter_by(is_read=False).count() > 0

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.icon_url:
            self.icon_url = url_for('static', filename='icons/default_icon.png')

    def __repr__(self):
        return f'<User {self.username}>'
    
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False) # <-- ここに追加
    comments = db.relationship('Comment', backref='post', lazy=True, cascade="all, delete")
    bookmarks = db.relationship(
        'Bookmark', 
        backref='post', 
        lazy='dynamic', 
        cascade="all, delete", 
    )
    notifications = db.relationship('Notification', backref='post', lazy='dynamic', cascade="all, delete")

    def __repr__(self):
        return f'<Post {self.id}>'

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False) # <-- ここに追記

    def __repr__(self):
        return f'<Comment {self.id}>'
        
class Bookmark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='_user_post_uc'),)

    def __repr__(self):
        return f'<Bookmark user_id={self.user_id}, post_id={self.post_id}>'

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), nullable=False)

    def __repr__(self):
        return f'<Notification recipient_id={self.recipient_id}, post_id={self.post_id}>'

@app.route('/', defaults={'page': 1}, methods=['GET', 'POST'])
@app.route('/page/<int:page>', methods=['GET', 'POST'])
def index(page):
    form = PostForm()
    search_form = SearchForm()
    if form.validate_on_submit() and current_user.is_authenticated:
        post = Post(title=form.title.data, content=form.content.data, author=current_user)
        db.session.add(post)
        db.session.commit()
        return redirect(url_for('index'))

    posts_per_page = 5
    posts = Post.query.order_by(Post.created_at.desc()).paginate(
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
                'body': '**ここに科目を入力(**は消さないこと)**　成績:**ここに成績を入力(**は消さないこと)**\n本文を入力'
            }
        ]
    
    return render_template('index.html', form=form, search_form=search_form, posts=posts, linkify_urls=linkify_urls, md=md, templates=templates, templates_for_js=json.dumps(templates))
@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    form = CommentForm()
    search_form = SearchForm()

    if form.validate_on_submit() and current_user.is_authenticated:
        comment = Comment(content=form.content.data, post=post, commenter=current_user)
        db.session.add(comment)
        db.session.commit()
        
        if current_user != post.author:
            notification = Notification(recipient=post.author, post=post, message=f'あなたの投稿「{post.title}」にコメントが付きました。')
            db.session.add(notification)
            db.session.commit()

        return redirect(url_for('post_detail', post_id=post.id))

    japan_tz = timezone('Asia/Tokyo')
    post.created_at_jst = post.created_at.replace(tzinfo=utc).astimezone(japan_tz)
    if post.updated_at:
        post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
    else:
        post.updated_at_jst = None

    for comment in post.comments:
        comment.created_at_jst = comment.created_at.replace(tzinfo=utc).astimezone(japan_tz)
    
    post.is_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None if current_user.is_authenticated else False
    
    return render_template('detail.html', post=post, form=form, linkify_urls=linkify_urls, md=md, search_form=search_form)

@app.route('/bookmark_post/<int:post_id>', methods=['POST'])
@login_required
def bookmark_post(post_id):
    post = Post.query.get_or_404(post_id)
    bookmark = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first()
    
    if bookmark:
        db.session.delete(bookmark)
        db.session.commit()
        is_bookmarked = False
    else:
        new_bookmark = Bookmark(user_id=current_user.id, post_id=post.id)
        db.session.add(new_bookmark)
        db.session.commit()
        
        if current_user != post.author:
            notification = Notification(recipient=post.author, post=post, message=f'あなたの投稿「{post.title}」がブックマークされました。')
            db.session.add(notification)
            db.session.commit()
        is_bookmarked = True
    
    return jsonify(is_bookmarked=is_bookmarked)

@app.route('/bookmarks')
@login_required
def show_bookmarks():
    search_form = SearchForm()
    bookmarked_posts = Post.query.join(Bookmark, Post.id == Bookmark.post_id).filter(Bookmark.user_id == current_user.id).order_by(Bookmark.timestamp.desc()).all()
    
    japan_tz = timezone('Asia/Tokyo')
    for post in bookmarked_posts:
        post.created_at_jst = post.created_at.replace(tzinfo=utc).astimezone(japan_tz)
        if post.updated_at:
            post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
        else:
            post.updated_at_jst = None
        post.is_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None if current_user.is_authenticated else False

    return render_template('bookmarks.html', posts=bookmarked_posts, search_form=search_form, md=md)

@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        return "投稿者以外は編集できません。", 403
    
    form = PostForm(obj=post)
    search_form = SearchForm()
    
    if form.validate_on_submit():
        post.title = form.title.data
        post.content = form.content.data
        db.session.commit()
        return redirect(url_for('post_detail', post_id=post.id))

    templates = [
        {
            'name': 'UECreview',
            'title': f'○年 ○期 {current_user.username}の授業review',
            'body': '**ここに科目を入力(**は消さないこと)**　成績:**ここに成績を入力(**は消さないこと)**\n本文を入力'
        }
    ]
    
    return render_template('edit.html', form=form, post=post, search_form=search_form, templates=templates, templates_for_js=json.dumps(templates))

@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author == current_user or current_user.is_admin:
        db.session.delete(post)
        db.session.commit()
        return redirect(url_for('index'))
    else:
        return "投稿者または管理者以外は削除できません。", 403

@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.commenter == current_user or comment.post.author == current_user or current_user.is_admin:
        post_id = comment.post.id
        db.session.delete(comment)
        db.session.commit()
        return redirect(url_for('post_detail', post_id=post_id))
    else:
        return "投稿者、コメント投稿者、または管理者以外は削除できません。", 403

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegisterForm()
    search_form = SearchForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        user = User(username=form.username.data, password=hashed_password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html', form=form, search_form=search_form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    search_form = SearchForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
            return redirect(url_for('index'))
    return render_template('login.html', form=form, search_form=search_form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/search', methods=['GET', 'POST'])
@app.route('/search/page/<int:page>', methods=['GET', 'POST'])
def search(page=1):
    form = SearchForm()
    search_query = None
    posts = None

    # 新規検索(POST)かページ移動(GET)かを判断
    if form.validate_on_submit():
        search_query = form.search_query.data
    elif request.method == 'GET' and request.args.get('search_query'):
        search_query = request.args.get('search_query')
        form.search_query.data = search_query # ページ移動後も検索ボックスにクエリを残す

    if search_query:
        # 検索クエリがある場合のみ、DB検索とデータ処理を行う
        posts_query = Post.query.filter(
            (Post.title.like(f'%{search_query}%')) | (Post.content.like(f'%{search_query}%'))
        ).order_by(Post.created_at.desc())

        posts = posts_query.paginate(page=page, per_page=5, error_out=False)

        # 投稿データの時刻情報などを追加する処理
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
        # 検索していない場合は、空のページネーションオブジェクトを作成
        posts = db.paginate(db.select(Post).where(False), page=page, per_page=5, error_out=False)

    return render_template('search_results.html',
                           form=form,
                           posts=posts,
                           search_query=search_query,
                           md=md, # 以前の修正を反映
                           search_form=form,
                           linkify_urls=linkify_urls)

@app.route('/profile/edit/<string:username>', methods=['GET', 'POST'])
@login_required
def edit_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user != current_user:
        return "他人のプロフィールは編集できません。", 403
    
    form = ProfileForm(obj=current_user)
    search_form = SearchForm()
    
    if form.validate_on_submit():
        current_user.username = form.username.data
        current_user.bio = form.bio.data
        
        if form.icon.data:
            filename = secure_filename(form.icon.data.filename)
            upload_folder = os.path.join(app.root_path, 'static/icons')
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
            
            file_path = os.path.join(upload_folder, filename)
            form.icon.data.save(file_path)
            current_user.icon_url = url_for('static', filename=f'icons/{filename}')
        
        db.session.commit()
        return redirect(url_for('user_profile', username=current_user.username))
    
    elif request.method == 'GET':
        form.username.data = current_user.username
        form.bio.data = current_user.bio
    
    return render_template('edit_profile.html', form=form, search_form=search_form, user=user)

@app.route('/user/<string:username>')
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    
    active_tab = request.args.get('active_tab', 'posts')
    post_page = request.args.get('post_page', 1, type=int)
    comment_page = request.args.get('comment_page', 1, type=int)
    
    posts_per_page = 5
    
    posts = Post.query.filter_by(author=user).order_by(Post.created_at.desc()).paginate(
        page=post_page, per_page=posts_per_page, error_out=False
    )
    comments = Comment.query.filter_by(commenter=user).order_by(Comment.created_at.desc()).paginate(
        page=comment_page, per_page=posts_per_page, error_out=False
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
    
    search_form = SearchForm()
    
    return render_template('profile.html', user=user, posts=posts, comments=comments, active_tab=active_tab, linkify_urls=linkify_urls, md=md, search_form=search_form)

# 管理者のみがアクセスできる管理画面
@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        abort(403)

    search_form = SearchForm() # ここでSearchFormを初期化
    all_users = User.query.all()
    all_posts = Post.query.all()
    all_comments = Comment.query.all()

    return render_template(
        'admin_dashboard.html', 
        users=all_users, 
        posts=all_posts,
        comments=all_comments,
        search_form=search_form # テンプレートにsearch_formを渡す
    )

# 管理者によるコメントの強制削除
@app.route('/admin/delete_comment/<int:comment_id>', methods=['POST'])
@login_required
def admin_delete_comment(comment_id):
    if not current_user.is_admin:
        abort(403)
    
    comment = Comment.query.get_or_404(comment_id)
    post_id = comment.post_id
    db.session.delete(comment)
    db.session.commit()
    
    flash('コメントを削除しました。', 'success')
    return redirect(url_for('admin_dashboard')) # 削除後は管理者ダッシュボードに戻る

# 投稿を強制的に削除するルート
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

# ユーザーを削除するルート（注意: ユーザーの削除は関連データも削除する必要があります）
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
    search_form = SearchForm()
    
    # 最新の5件の通知を取得
    notifications = Notification.query.filter_by(recipient=current_user).order_by(Notification.timestamp.desc()).limit(5).all()
    
    # 取得した通知をすべて既読にする
    for notification in notifications:
        notification.is_read = True
    db.session.commit()
    
    return render_template('notifications.html', notifications=notifications, search_form=search_form)


if __name__ == '__main__':
    app.run(debug=True)
