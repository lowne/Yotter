from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.widgets.core import Input
from markupsafe import Markup
from wtforms.validators import ValidationError, DataRequired, EqualTo
from app.models import User



class IconSubmitInput(Input):
    """
    Renders a submit button with a custom icon.
    <button type="submit">
      <i class="{icon} icon"></i>
      {label}
    </button>
    """

    def __call__(self, field, icon, **kwargs):
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('value', field.label.text)
        # if 'value' not in kwargs:
        #     kwargs['value'] = field._value()
        if 'required' not in kwargs and 'required' in getattr(field, 'flags', []):
            kwargs['required'] = True
        html=f'<button type="submit" {self.html_params(name=field.name, **kwargs)}><i class="{icon} icon"></i>{kwargs["value"]}</button>'
        return Markup(html)


class IconSubmitField(BooleanField):
    widget = IconSubmitInput()


class LoginForm(FlaskForm):
    style={'class': 'ui primary button'}
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In', render_kw=style)


class ChannelForm(FlaskForm):
    search = StringField('')
    submit = SubmitField('Search')


class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    password2 = PasswordField(
        'Repeat Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user is not None:
            raise ValidationError('Please use a different username.')

class EmptyForm(FlaskForm):
    submit = IconSubmitField('Submit')
