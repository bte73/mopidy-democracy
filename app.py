#!/usr/bin/env python3
import functools
import json
from time import sleep

from flask import Flask, render_template, redirect, request, flash
from flask_login import LoginManager, current_user, login_required, logout_user, login_user
from flask_socketio import SocketIO, disconnect, emit
from peewee import DoesNotExist, SqliteDatabase

from config import SECRET_KEY, MOPIDY_HOST, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, DEBUG, DB, LDAP_HOST
from models import db_init, User
from mopidy import Mopidy
from utils import ldap_auth

app = Flask(__name__)
app.secret_key = SECRET_KEY
socketio = SocketIO(app)
login_manager = LoginManager()
login_manager.init_app(app)


def ws_login_required(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            disconnect()
        else:
            return f(*args, **kwargs)

    return wrapped


@app.route("/")
def index():
    return render_template('music.html')


@socketio.on('refresh')
def mopidy_refresh():
    track = mopidy.get_current_track()
    if track:
        emit('track', json.dumps({
            'title': track['name'],
            'artists': ', '.join(artist['name'] for artist in track['artists']),
            'album': track['album']['name'],
            'art': track['art']
        }))
    else:
        emit({})


@socketio.on('search')
def search(data):
    if data.get('query'):
        results = mopidy.search(data['query'])
        try:
            results = results['result'][1]['tracks'][:15]
            emit('search results', json.dumps(results))
        except Exception as e:
            pass


@socketio.on('request')
@ws_login_required
def request(data):
    mopidy.add_track(data['uri'])


@socketio.on('admin')
@ws_login_required
def mopidy_ws(data):
    if not current_user.admin:
        disconnect()
    action = data.pop('action')
    if action == 'play':
        mopidy.play()
    elif action == 'pause':
        mopidy.pause()
    elif action == 'next':
        mopidy.next()
    elif action == 'prev':
        mopidy.previous()
    elif action == 'volup':
        mopidy.fade(4)
    elif action == 'voldown':
        mopidy.fade(-4)
    elif action == 'fadedown':
        mopidy.fade(-20)
    elif action == 'fadeup':
        mopidy.fade(20)


@login_manager.user_loader
def load_user(user_id):
    return User.get(id=user_id)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect('/')


@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    created = False
    try:
        user = User.get(username=username)
    except DoesNotExist:
        if LDAP_HOST:
            user = ldap_auth(username, password)
            created = True
    if user:
        if created or user.check_password(password):
            login_user(user)
            flash('Logged in successfully.')
    if not user:
        flash('Invalid credentials.')
    return redirect('/')


# This hook ensures that a connection is opened to handle any queries
# generated by the request.
@app.before_request
def _db_connect():
    if not type(DB) == SqliteDatabase:
        DB.connect()


# This hook ensures that the connection is closed when we've finished
# processing the request.
@app.teardown_request
def _db_close(exc):
    if not type(DB) == SqliteDatabase:
        if not DB.is_closed():
            DB.close()


if __name__ == "__main__":
    db_init()
    mopidy = Mopidy(MOPIDY_HOST, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    socketio.run(app, debug=DEBUG)
