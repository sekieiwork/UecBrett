from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SubmitField, SelectField
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

AFFILIATION_CHOICES = [
    ('', '（未設定）'),
    ('1年1クラス', '1年1クラス'), ('1年2クラス', '1年2クラス'),
    ('1年3クラス', '1年3クラス'), ('1年4クラス', '1年4クラス'),
    ('1年5クラス', '1年5クラス'), ('1年6クラス', '1年6クラス'),
    ('1年7クラス', '1年7クラス'), ('1年8クラス', '1年8クラス'),
    ('1年9クラス', '1年9クラス'), ('1年10クラス', '1年10クラス'),
    ('1年11クラス', '1年11クラス'), ('1年12クラス', '1年12クラス'),
    ('---I', '--- [ I類 ] ---'),
    ('メディア情報学プログラム', 'メディア情報学プログラム'),
    ('経営・社会情報学プログラム', '経営・社会情報学プログラム'),
    ('情報数理工学プログラム', '情報数理工学プログラム'),
    ('コンピュータサイエンスプログラム', 'コンピュータサイエンスプログラム'),
    ('デザイン思考・データサイエンスプログラム', 'デザイン思考・データサイエンスプログラム'),
    ('---II', '--- [ II類 ] ---'),
    ('セキュリティ情報学プログラム', 'セキュリティ情報学プログラム'),
    ('情報通信工学プログラム', '情報通信工学プログラム'),
    ('電子情報学プログラム', '電子情報学プログラム'),
    ('計測・制御システムプログラム', '計測・制御システムプログラム'),
    ('先端ロボティクスプログラム', '先端ロボティクスプログラム'),
    ('---III', '--- [ III類 ] ---'),
    ('機械システムプログラム', '機械システムプログラム'),
    ('電子工学プログラム', '電子工学プログラム'),
    ('光工学プログラム', '光工学プログラム'),
    ('物理工学プログラム', '物理工学プログラム'),
    ('化学生命工学プログラム', '化学生命工学プログラム'),
    ('---Other', '--- [ その他 ] ---'),
    ('大学院生', '大学院生'),
    ('教職員', '教職員'),
    ('その他', 'その他'),
]

class ProfileForm(FlaskForm):
    username = StringField('ユーザー名', validators=[DataRequired(), Length(min=2, max=20)])
    bio = TextAreaField('自己紹介')
    icon = FileField('新しいアイコン', validators=[FileAllowed(['jpg', 'png', 'gif','heic', 'heif'], '画像ファイルのみ')])
    tags = StringField('タグ')
    affiliation = SelectField('所属',choices=AFFILIATION_CHOICES, default='',validators=[]) # 必須ではない
    submit = SubmitField('更新')

    def validate_username(self, username):
        # この部分はapp.pyのUserモデルに依存するため、後で修正が必要になる場合があります
        pass

class KairanbanForm(FlaskForm):
    content = TextAreaField('本文', validators=[DataRequired()])
    tags = StringField('対象タグ (カンマ区切り)')
    
    # 1日～31日の選択肢を生成
    days_choices = [(str(i), f'{i} 日間') for i in range(1, 32)]
    expires_in_days = SelectField(
        '表示期間', 
        choices=days_choices, 
        default='7', # デフォルト7日
        validators=[DataRequired()]
    )

    
    submit = SubmitField('送信')
