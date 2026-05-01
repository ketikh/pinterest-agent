"""Authentication routes: login, logout."""

import os

import bcrypt
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, Length

from ..extensions import db, login_manager
from . import auth_bp


class LoginForm(FlaskForm):
    username = StringField(
        "სახელი",
        validators=[DataRequired(), Length(min=1, max=64)],
    )
    password = PasswordField(
        "პაროლი",
        validators=[DataRequired(), Length(min=6, max=128)],
    )


# ---------------------------------------------------------------------------
# User loader (required by Flask-Login)
# ---------------------------------------------------------------------------

@login_manager.user_loader
def load_user(user_id: str):
    from ..ai_content.models import User

    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("ai_content.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        from ..ai_content.models import User

        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=True)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("ai_content.dashboard"))

        flash("სახელი ან პაროლი არასწორია.", "danger")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("გამოსვლა წარმატებით.", "info")
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# CLI: create first admin user
# ---------------------------------------------------------------------------

import click
from flask import current_app


@auth_bp.cli.command("create-admin")
@click.option("--username", prompt=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def create_admin(username: str, password: str) -> None:
    """Create the first admin user."""
    from ..ai_content.models import User

    existing = User.query.filter_by(username=username).first()
    if existing:
        click.echo(f"User '{username}' already exists.")
        return

    user = User(username=username, role="admin")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f"Admin user '{username}' created.")
