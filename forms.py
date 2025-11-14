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

GRADE_CHOICES = [
    ('', '--- 学年を選択 ---'),
    ('1年', '1年'),
    ('2年', '2年'),
    ('3年', '3年'),
    ('4年', '4年'),
    ('大学院生', '大学院生'),
    ('教職員', '教職員'),
    ('その他', 'その他')
]

CATEGORY_CHOICES = [
    ('', '--- 類を選択 ---'),
    ('I類', 'I類 (情報系)'),
    ('II類', 'II類 (融合系)'),
    ('III類', 'III類 (理工系)')
]

# JSでフィルタリングするための全クラスリスト
CLASS_CHOICES = [
    ('', '--- クラスを選択 ---'),
    # 1年生用
    ('1クラス', '1クラス'), ('2クラス', '2クラス'), ('3クラス', '3クラス'),
    ('4クラス', '4クラス'), ('5クラス', '5クラス'), ('6クラス', '6クラス'),
    ('7クラス', '7クラス'), ('8クラス', '8クラス'), ('9クラス', '9クラス'),
    ('10クラス', '10クラス'), ('11クラス', '11クラス'), ('12クラス', '12クラス'),
    # 2年生 I類用
    ('Aクラス', 'Aクラス (I類)'), ('Bクラス', 'Bクラス (I類)'), ('Cクラス', 'Cクラス (I類)'),
    # 2年生 II類用
    ('I1', 'I1 (II類)'), ('I2', 'I2 (II類)'), ('I3', 'I3 (II類)'),
    ('I4', 'I4 (II類)'), ('I5', 'I5 (II類)'), ('I6', 'I6 (II類)'),
    ('Mエリア', 'Mエリア (II類)')
]

# [cite_start]画像 [cite: 1] から読み取ったプログラムリスト
PROGRAM_CHOICES = [
    ('', '--- プログラムを選択 ---'),
    ('未決定', '未決定'),
    # I類
    ('メディア情報学プログラム', 'メディア情報学プログラム (I類)'),
    ('経営・社会情報学プログラム', '経営・社会情報学プログラム (I類)'),
    ('情報数理工学プログラム', '情報数理工学プログラム (I類)'),
    ('コンピュータサイエンスプログラム', 'コンピュータサイエンスプログラム (I類)'),
    ('デザイン思考・データサイエンスプログラム', 'デザイン思考・データサイエンスプログラム (I類)'),
    # II類
    ('セキュリティ情報学プログラム', 'セキュリティ情報学プログラム (II類)'),
    ('情報通信工学プログラム', '情報通信工学プログラム (II類)'),
    ('電子情報学プログラム', '電子情報学プログラム (II類)'),
    ('計測・制御システムプログラム', '計測・制御システムプログラム (II類)'),
    ('先端ロボティクスプログラム', '先端ロボティクスプログラム (II類)'),
    # III類
    ('機械システムプログラム', '機械システムプログラム (III類)'),
    ('電子工学プログラム', '電子工学プログラム (III類)'),
    ('光工学プログラム', '光工学プログラム (III類)'),
    ('物理工学プログラム', '物理工学プログラム (III類)'),
    ('化学生命工学プログラム', '化学生命工学プログラム (III類)')
]

MAJOR_CHOICES = [
    ('', '--- 専攻を選択 ---'),
    ('情報学専攻', '情報学専攻 (I類から)'),
    ('情報・ネットワーク工学専攻', '情報・ネットワーク工学専攻 (II類から)'),
    ('機械知能システム学専攻', '機械知能システム学専攻 (III類から)'),
    ('基盤理工学専攻', '基盤理工学専攻 (III類から)')
]

class ProfileForm(FlaskForm):
    username = StringField('ユーザー名', validators=[DataRequired(), Length(min=2, max=20)])
    bio = TextAreaField('自己紹介')
    icon = FileField('新しいアイコン', validators=[FileAllowed(['jpg', 'png', 'gif','heic', 'heif'], '画像ファイルのみ')])
    tags = StringField('タグ')
    grade = SelectField('学年', choices=GRADE_CHOICES, default='')
    category = SelectField('類', choices=CATEGORY_CHOICES, default='')
    user_class = SelectField('クラス', choices=CLASS_CHOICES, default='')
    program = SelectField('プログラム', choices=PROGRAM_CHOICES, default='')
    major = SelectField('専攻（大学院）', choices=MAJOR_CHOICES, default='')
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
