from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError
from flask_wtf.file import FileField, FileAllowed

class PostForm(FlaskForm):
    title = StringField('タイトル', validators=[DataRequired()])
    content = TextAreaField('本文', validators=[DataRequired()])
    image = FileField('画像', validators=[FileAllowed(['jpg', 'png', 'gif', 'jpeg','heic', 'heif'], '画像ファイルのみ！')]) # <-- この行を追加
    tags = StringField('タグ')
    submit = SubmitField('投稿')

class CommentForm(FlaskForm):
    content = TextAreaField('コメント', validators=[DataRequired(), Length(min=1)])
    submit = SubmitField('コメントする')

class RegisterForm(FlaskForm):
    username = StringField('ユーザー名', validators=[DataRequired(), Length(min=2, max=20)])
    password = PasswordField('パスワード', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('パスワード（確認）', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('登録')

    def validate_username(self, username):
        # この部分はapp.pyのUserモデルに依存するため、後で修正が必要になる場合があります
        pass

class LoginForm(FlaskForm):
    username = StringField('ユーザー名', validators=[DataRequired()])
    password = PasswordField('パスワード', validators=[DataRequired()])
    submit = SubmitField('ログイン')

class SearchForm(FlaskForm):
    search_query = StringField('検索', validators=[DataRequired()])
    submit = SubmitField('検索')

class ProfileForm(FlaskForm):
    username = StringField('ユーザー名', validators=[DataRequired(), Length(min=2, max=20)])
    bio = TextAreaField('自己紹介')
    icon = FileField('新しいアイコン', validators=[FileAllowed(['jpg', 'png', 'gif','heic', 'heif'], '画像ファイルのみ')])
    tags = StringField('タグ')
    submit = SubmitField('更新')

    def validate_username(self, username):
        # この部分はapp.pyのUserモデルに依存するため、後で修正が必要になる場合があります
        pass
