#!/usr/bin/python3

from functools import wraps
from flask import Flask, render_template, request, redirect, send_file, Response, jsonify, abort
import variables as var
import util
from datetime import datetime
import os
import os.path
import shutil
import random
from werkzeug.utils import secure_filename
import errno
import media
import media.radio
import logging
import time
import constants


class ReverseProxied(object):
    '''Wrap the application in this middleware and configure the
    front-end server to add these headers, to let you quietly bind
    this to a URL other than / and to an HTTP scheme that is
    different than what is used locally.

    In nginx:
    location /myprefix {
        proxy_pass http://192.168.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Scheme $scheme;
        proxy_set_header X-Script-Name /myprefix;
        }

    :param app: the WSGI application
    '''

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        script_name = environ.get('HTTP_X_SCRIPT_NAME', '')
        if script_name:
            environ['SCRIPT_NAME'] = script_name
            path_info = environ['PATH_INFO']
            if path_info.startswith(script_name):
                environ['PATH_INFO'] = path_info[len(script_name):]

        scheme = environ.get('HTTP_X_SCHEME', '')
        if scheme:
            environ['wsgi.url_scheme'] = scheme
        real_ip = environ.get('HTTP_X_REAL_IP', '')
        if real_ip:
            environ['REMOTE_ADDR'] = real_ip
        return self.app(environ, start_response)


web = Flask(__name__)
log = logging.getLogger("bot")

def init_proxy():
    global web
    if var.is_proxified:
        web.wsgi_app = ReverseProxied(web.wsgi_app)

# https://stackoverflow.com/questions/29725217/password-protect-one-webpage-in-flask-app

def check_auth(username, password):
    """This function is called to check if a username /
    password combination is valid.
    """
    return username == var.config.get("webinterface", "user") and password == var.config.get("webinterface", "password")

def authenticate():
    """Sends a 401 response that enables basic auth"""
    global log
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper credentials', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        global log
        auth = request.authorization
        if var.config.getboolean("webinterface", "require_auth") and (not auth or not check_auth(auth.username, auth.password)):
            if auth:
                log.info("web: Failed login attempt, user: %s" % auth.username)
            return authenticate()
        return f(*args, **kwargs)
    return decorated


@web.route("/", methods=['GET'])
@requires_auth
def index():
    folder_path = var.music_folder
    files = util.get_recursive_file_list_sorted(var.music_folder)
    music_library = util.Dir(folder_path)
    for file in files:
        music_library.add_file(file)


    return render_template('index.html',
                           all_files=files,
                           music_library=music_library,
                           os=os,
                           playlist=var.playlist,
                           user=var.user,
                           paused=var.botamusique.is_pause
                           )

@web.route("/playlist", methods=['GET'])
@requires_auth
def playlist():
    if var.playlist.length() == 0:
        return jsonify({'items': [render_template('playlist.html',
                               m=False,
                               index=-1
                               )]
                        })

    items = []

    for index, item in enumerate(var.playlist):
         items.append(render_template('playlist.html',
                                     index=index,
                                     m=item,
                                     playlist=var.playlist
                                     )
                     )

    return jsonify({ 'items': items })

def status():
    if (var.playlist.length() > 0):
        return jsonify({'ver': var.playlist.version,
                        'empty': False,
                        'play': not var.botamusique.is_pause,
                        'mode': var.playlist.mode})
    else:
        return jsonify({'ver': var.playlist.version,
                        'empty': True,
                        'play': False,
                        'mode': var.playlist.mode})


@web.route("/post", methods=['POST'])
@requires_auth
def post():
    global log

    folder_path = var.music_folder
    if request.method == 'POST':
        if request.form:
            log.debug("web: Post request from %s: %s" % ( request.remote_addr, str(request.form)))
        if 'add_file_bottom' in request.form and ".." not in request.form['add_file_bottom']:
            path = var.music_folder + request.form['add_file_bottom']
            if os.path.isfile(path):
                item = {'type': 'file',
                        'path' : request.form['add_file_bottom'],
                        'title' : '',
                        'user' : 'Remote Control'}
                item = var.playlist.append(util.attach_music_tag_info(item))
                log.info('web: add to playlist(bottom): ' + util.format_debug_song_string(item))

        elif 'add_file_next' in request.form and ".." not in request.form['add_file_next']:
            path = var.music_folder + request.form['add_file_next']
            if os.path.isfile(path):
                item = {'type': 'file',
                        'path' : request.form['add_file_next'],
                        'title' : '',
                        'user' : 'Remote Control'}
                item = var.playlist.insert(
                    var.playlist.current_index + 1,
                    item
                )
                log.info('web: add to playlist(next): ' + util.format_debug_song_string(item))

        elif ('add_folder' in request.form and ".." not in request.form['add_folder']) or ('add_folder_recursively' in request.form and ".." not in request.form['add_folder_recursively']):
            try:
                folder = request.form['add_folder']
            except:
                folder = request.form['add_folder_recursively']

            if not folder.endswith('/'):
                folder += '/'

            print('folder:', folder)

            if os.path.isdir(var.music_folder + folder):

                files = util.get_recursive_file_list_sorted(var.music_folder)
                music_library = util.Dir(folder_path)
                for file in files:
                    music_library.add_file(file)

                if 'add_folder_recursively' in request.form:
                    files = music_library.get_files_recursively(folder)
                else:
                    files = music_library.get_files(folder)

                files = list(map(lambda file:
                    {'type':'file',
                     'path': os.path.join(folder, file),
                     'user':'Remote Control'}, files))

                files = var.playlist.extend(files)

                for file in files:
                    log.info("web: add to playlist: %s" %  util.format_debug_song_string(file))


        elif 'add_url' in request.form:
            music = {'type':'url',
                                 'url': request.form['add_url'],
                                 'user': 'Remote Control',
                                 'ready': 'validation'}
            music = var.botamusique.validate_music(music)
            if music:
                var.playlist.append(music)
                log.info("web: add to playlist: " + util.format_debug_song_string(music))
                if var.playlist.length() == 2:
                    # If I am the second item on the playlist. (I am the next one!)
                    var.botamusique.async_download_next()

        elif 'add_radio' in request.form:
            url = request.form['add_radio']
            music = var.playlist.append({'type': 'radio',
                                 'url': url,
                                 'user': "Remote Control"})
            log.info("web: fetching radio server description")
            music["name"] = media.radio.get_radio_server_description(url)
            log.info("web: add to playlist: " + util.format_debug_song_string(music))

        elif 'delete_music' in request.form:
            music = var.playlist[int(request.form['delete_music'])]
            log.info("web: delete from playlist: " + util.format_debug_song_string(music))

            if var.playlist.length() >= int(request.form['delete_music']):
                index = int(request.form['delete_music'])

                if index == var.playlist.current_index:
                    var.playlist.remove(index)

                    if index < len(var.playlist):
                        if not var.botamusique.is_pause:
                            var.botamusique.interrupt_playing()
                            var.playlist.current_index -= 1
                            # then the bot will move to next item

                    else:  # if item deleted is the last item of the queue
                        var.playlist.current_index -= 1
                        if not var.botamusique.is_pause:
                            var.botamusique.interrupt_playing()
                else:
                    var.playlist.remove(index)


        elif 'play_music' in request.form:
            music = var.playlist[int(request.form['play_music'])]
            log.info("web: jump to: " + util.format_debug_song_string(music))

            if len(var.playlist) >= int(request.form['play_music']):
                var.botamusique.interrupt_playing()
                var.botamusique.launch_music(int(request.form['play_music']))

        elif 'delete_music_file' in request.form and ".." not in request.form['delete_music_file']:
            path = var.music_folder + request.form['delete_music_file']
            if os.path.isfile(path):
                log.info("web: delete file " + path)
                os.remove(path)

        elif 'delete_folder' in request.form and ".." not in request.form['delete_folder']:
            path = var.music_folder + request.form['delete_folder']
            if os.path.isdir(path):
                log.info("web: delete folder " + path)
                shutil.rmtree(path)
                time.sleep(0.1)

        elif 'action' in request.form:
            action = request.form['action']
            if action == "randomize":
                var.botamusique.interrupt_playing()
                var.playlist.set_mode("random")
                var.db.set('playlist', 'playback_mode', "random")
                log.info("web: playback mode changed to random.")
            if action == "one-shot":
                var.playlist.set_mode("one-shot")
                var.db.set('playlist', 'playback_mode', "one-shot")
                log.info("web: playback mode changed to one-shot.")
            if action == "repeat":
                var.playlist.set_mode("repeat")
                var.db.set('playlist', 'playback_mode', "repeat")
                log.info("web: playback mode changed to repeat.")
            elif action == "stop":
                var.botamusique.stop()
            elif action == "pause":
                var.botamusique.pause()
            elif action == "resume":
                var.botamusique.resume()
            elif action == "clear":
                var.botamusique.clear()
            elif action == "volume_up":
                if var.botamusique.volume_set + 0.03 < 1.0:
                    var.botamusique.volume_set = var.botamusique.volume_set + 0.03
                else:
                    var.botamusique.volume_set = 1.0
                var.db.set('bot', 'volume', str(var.botamusique.volume_set))
                log.info("web: volume up to %d" % (var.botamusique.volume_set * 100))
            elif action == "volume_down":
                if var.botamusique.volume_set - 0.03 > 0:
                    var.botamusique.volume_set = var.botamusique.volume_set - 0.03
                else:
                    var.botamusique.volume_set = 0
                var.db.set('bot', 'volume', str(var.botamusique.volume_set))
                log.info("web: volume up to %d" % (var.botamusique.volume_set * 100))

    return status()

@web.route('/upload', methods=["POST"])
def upload():
    global log

    files = request.files.getlist("file[]")
    if not files:
        return redirect("./", code=406)

    #filename = secure_filename(file.filename).strip()
    for file in files:
        filename = file.filename
        if filename == '':
            return redirect("./", code=406)

        targetdir = request.form['targetdir'].strip()
        if targetdir == '':
            targetdir = 'uploads/'
        elif '../' in targetdir:
            return redirect("./", code=406)

        log.info('web: Uploading file from %s:' % request.remote_addr)
        log.info('web: - filename: ' + filename)
        log.info('web: - targetdir: ' + targetdir)
        log.info('web:  - mimetype: ' + file.mimetype)

        if "audio" in file.mimetype:
            storagepath = os.path.abspath(os.path.join(var.music_folder, targetdir))
            print('storagepath:',storagepath)
            if not storagepath.startswith(os.path.abspath(var.music_folder)):
                return redirect("./", code=406)

            try:
                os.makedirs(storagepath)
            except OSError as ee:
                if ee.errno != errno.EEXIST:
                    return redirect("./", code=500)

            filepath = os.path.join(storagepath, filename)
            log.info(' - filepath: ' + filepath)
            if os.path.exists(filepath):
                return redirect("./", code=406)

            file.save(filepath)
        else:
            return redirect("./", code=409)

    return redirect("./", code=302)


@web.route('/download', methods=["GET"])
def download():
    global log

    if 'file' in request.args:
        requested_file = request.args['file']
        log.info('web: Download of file %s requested from %s:' % (requested_file, request.remote_addr))
        if '../' not in requested_file:
            folder_path = var.music_folder
            files = util.get_recursive_file_list_sorted(var.music_folder)

            if requested_file in files:
                filepath = os.path.join(folder_path, requested_file)
                try:
                    return send_file(filepath, as_attachment=True)
                except Exception as e:
                    log.exception(e)
                    abort(404)
    elif 'directory' in request.args:
        requested_dir = request.args['directory']
        folder_path = var.music_folder
        requested_dir_fullpath = os.path.abspath(os.path.join(folder_path, requested_dir)) + '/'
        if requested_dir_fullpath.startswith(folder_path):
            if os.path.samefile(requested_dir_fullpath, folder_path):
                prefix = 'all'
            else:
                prefix = secure_filename(os.path.relpath(requested_dir_fullpath, folder_path))
            zipfile = util.zipdir(requested_dir_fullpath, prefix)
            try:
                return send_file(zipfile, as_attachment=True)
            except Exception as e:
                log.exception(e)
                abort(404)

    return redirect("./", code=400)


if __name__ == '__main__':
    web.run(port=8181, host="127.0.0.1")
