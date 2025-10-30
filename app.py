from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate, upgrade
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from pytz import timezone, utc
import os
from flask_wtf.file import FileField, FileAllowed
from forms import PostForm, CommentForm, RegisterForm, LoginForm, SearchForm, ProfileForm
import markdown
import re
import json
from PIL import Image
import cloudinary
import cloudinary.uploader

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

# Helper Functions
def linkify_urls(text):
    url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
    return re.sub(
        url_pattern,
        lambda match: f'<a href="{match.group(0)}" target="_blank">{match.group(0)}</a>',
        text
    )

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

# Database Models
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(500), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text, nullable=True)
    icon_url = db.Column(db.String(200), nullable=True)
    posts = db.relationship('Post', backref='author', lazy=True, cascade="all, delete")
    comments = db.relationship('Comment', backref='commenter', lazy=True)
    bookmarks = db.relationship('Bookmark', backref='user', lazy='dynamic')
    notifications = db.relationship('Notification', backref='recipient', lazy='dynamic')

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
    notifications = db.relationship('Notification', backref='post', lazy='dynamic', cascade="all, delete")

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
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete="CASCADE"), nullable=False)

# Routes
@app.route('/', defaults={'page': 1}, methods=['GET', 'POST'])
@app.route('/page/<int:page>', methods=['GET', 'POST'])
def index(page):
    form = PostForm()
    search_form = SearchForm()
    if form.validate_on_submit() and current_user.is_authenticated:
        image_url_str = None # 変数名を変更
        if form.image.data:
            image_url_str = save_picture(form.image.data)

        post = Post(title=form.title.data, content=form.content.data, author=current_user, image_url=image_url_str) # image_filenameをimage_urlに変更
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
                'body': '<span class="text-large">**ここに科目名を入力**</span> 成績:<span class="text-red text-large">**ここに成績を入力**</span> 担当教員:ここに担当教員名を入力\n本文を入力'
            }
        ]
    
    return render_template('index.html', form=form, search_form=search_form, posts=posts, linkify_urls=linkify_urls, md=md, templates=templates, templates_for_js=json.dumps(templates))

@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    comment_form = CommentForm()
    search_form = SearchForm()

    if comment_form.validate_on_submit() and current_user.is_authenticated:
        comment = Comment(content=comment_form.content.data, post=post, commenter=current_user)
        db.session.add(comment)
        
        if current_user != post.author:
            notification = Notification(recipient=post.author, post=post, message=f'あなたの投稿「{post.title}」にコメントが付きました。')
            db.session.add(notification)
        
        db.session.commit()
        # ▼▼▼ ③ ここから修正 ▼▼▼
        # 意図: url_forに _anchor を追加し、リダイレクト先のURLに #comment-ID を付与します。
        # これにより、ブラウザが自動でそのコメントの位置までスクロールします。
        return redirect(url_for('post_detail', post_id=post.id, _anchor=f'comment-{comment.id}'))
        # ▲▲▲ ③ ここまで修正 ▲▲▲

    japan_tz = timezone('Asia/Tokyo')
    post.created_at_jst = post.created_at.replace(tzinfo=utc).astimezone(japan_tz)
    if post.updated_at:
        post.updated_at_jst = post.updated_at.replace(tzinfo=utc).astimezone(japan_tz)
    else:
        post.updated_at_jst = None

    for c in post.comments:
        c.created_at_jst = c.created_at.replace(tzinfo=utc).astimezone(japan_tz)
    
    post.is_bookmarked = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None if current_user.is_authenticated else False
    
    return render_template('detail.html', post=post, comment_form=comment_form, linkify_urls=linkify_urls, md=md, search_form=search_form)

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
        db.session.add(new_bookmark)
        if current_user != post.author:
            notification = Notification(recipient=post.author, post=post, message=f'あなたの投稿「{post.title}」がブックマークされました。')
            db.session.add(notification)
        is_bookmarked = True
    
    db.session.commit()
    return jsonify(is_bookmarked=is_bookmarked)

@app.route('/bookmarks')
@login_required
def show_bookmarks():
    search_form = SearchForm()
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

    return render_template('bookmarks.html', posts=bookmarked_posts, search_form=search_form, md=md, linkify_urls=linkify_urls)

@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        abort(403)

    form = PostForm() # まず空のフォームを作成
    search_form = SearchForm()

    if form.validate_on_submit():
        post.title = form.title.data
        post.content = form.content.data
        if form.image.data:
            # ▼▼▼ ここから追加 ▼▼▼
                # 古い画像があればURLを取得し、Cloudinaryから削除
            if post.image_url:
                delete_from_cloudinary(post.image_url)
            # ▲▲▲ ここまで ▲▲▲
            image_url_str = save_picture(form.image.data)
            post.image_url = image_url_str # image_filenameをimage_urlに変更
        db.session.commit()
        return redirect(url_for('post_detail', post_id=post.id))

    elif request.method == 'GET': # GETリクエスト（ページを最初に開いた時）
        # フォームに現在の投稿データをセットする
        form.title.data = post.title
        form.content.data = post.content

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
        # パース成功時、データをJSON文字列に変換
        uec_review_data_json = json.dumps(uec_review_data)
        # ※この時点では元の post.content (テキストエリアの値) は変更しない
        # JavaScript側でこのJSONを読み取ってフォームを動的に生成する
    # ▲▲▲ 追加ここまで ▲▲▲

    return render_template('edit.html', form=form, post=post, search_form=search_form, md=md, templates=templates, templates_for_js=json.dumps(templates), linkify_urls=linkify_urls,uec_review_data_json=uec_review_data_json)
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
    post_id = comment.post_id # 投稿IDを先に取得しておく
    if comment.commenter == current_user or comment.post.author == current_user or current_user.is_admin:
        db.session.delete(comment)
        db.session.commit()
        # リダイレクトの代わりに、成功のJSONを返す
        remaining_comments = Comment.query.filter_by(post_id=post_id).count()
        return jsonify({'status': 'success', 'remaining_comments': remaining_comments})
    else:
        abort(403)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegisterForm()
    search_form = SearchForm()
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
        else:
            flash('ユーザー名またはパスワードが正しくありません。')
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

    if form.validate_on_submit():
        search_query = form.search_query.data
    elif request.method == 'GET' and request.args.get('search_query'):
        search_query = request.args.get('search_query')
        form.search_query.data = search_query

    if search_query:
        posts_query = Post.query.filter(
            (Post.title.like(f'%{search_query}%')) | (Post.content.like(f'%{search_query}%'))
        ).order_by(Post.created_at.desc())
        posts = posts_query.paginate(page=page, per_page=5, error_out=False)

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
        posts = db.paginate(db.select(Post).where(False), page=page, per_page=5, error_out=False)

    return render_template('search_results.html',
                           form=form,
                           posts=posts,
                           search_query=search_query,
                           md=md,
                           search_form=form,
                           linkify_urls=linkify_urls)

@app.route('/profile/edit/<string:username>', methods=['GET', 'POST'])
@login_required
def edit_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user != current_user:
        abort(403)
    
    form = ProfileForm(obj=user)
    search_form = SearchForm()
    
    if form.validate_on_submit():
        user.username = form.username.data
        user.bio = form.bio.data
        
        if form.icon.data:
            # ▼▼▼ ここから追加 ▼▼▼
            # 古いアイコンがあればURLを取得し、Cloudinaryから削除
            if user.icon_url:
                delete_from_cloudinary(user.icon_url)
            # ▲▲▲ ここまで ▲▲▲
            # Cloudinaryにアイコンを保存し、URLを取得
            icon_url = save_icon(form.icon.data)
            user.icon_url = icon_url
        
        db.session.commit()
        return redirect(url_for('user_profile', username=user.username))
    
    return render_template('edit_profile.html', form=form, search_form=search_form, user=user)

@app.route('/user/<string:username>')
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    
    active_tab = request.args.get('active_tab', 'posts')
    post_page = request.args.get('post_page', 1, type=int)
    comment_page = request.args.get('comment_page', 1, type=int)
    
    posts = Post.query.filter_by(author=user).order_by(Post.created_at.desc()).paginate(
        page=post_page, per_page=5, error_out=False
    )
    comments = Comment.query.filter_by(commenter=user).order_by(Comment.created_at.desc()).paginate(
        page=comment_page, per_page=5, error_out=False
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

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        abort(403)
    search_form = SearchForm()
    all_users = User.query.all()
    all_posts = Post.query.all()
    all_comments = Comment.query.all()
    return render_template('admin_dashboard.html', users=all_users, posts=all_posts, comments=all_comments, search_form=search_form)

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
    search_form = SearchForm()
    notifications = Notification.query.filter_by(recipient=current_user).order_by(Notification.timestamp.desc()).all()
    
    for n in notifications:
        n.is_read = True
    db.session.commit()
    
    return render_template('notifications.html', notifications=notifications, search_form=search_form, md=md, linkify_urls=linkify_urls)



if __name__ == '__main__':
    app.run(debug=True)
