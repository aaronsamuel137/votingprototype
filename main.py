#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import webapp2
import jinja2
import os
import cgi
import datetime
import time
import logging
import random
import string
import json

from google.appengine.ext import db
from google.appengine.api import memcache
from google.appengine.api import channel
#from google.appengine.api import users

# set up a directory for jinja html templates
template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir),
                               autoescape = True)


# Globals
QUEUE = "queue"
VOTE = "vote"
LOGGED_IN = "logged_in"
TOKEN = "token"
CHANNEL_KEY = "klsjht3q48o7faekrgh3i7qk4jbrqb"

def escape_html(s):
	s = s.replace("&", "&amp;")
	return cgi.escape(s, quote = True)

# shortcut function for rendering jinja templates
def render_str(template, **params):
	t = jinja_env.get_template(template)
	return t.render(params)

def make_cookie(n):
    return''.join(random.choice(string.letters + string.digits) for a in range(n))

# Input table, not used in this version so far
class Input(db.Model):
	user_input = db.StringProperty(required = True)
	event = db.StringProperty()
	created = db.DateTimeProperty(auto_now_add = True)

	# this function is called in dataview.html for each entry
	def render_input(self):
		self._render_text = self.user_input.replace('\n', '<br>')
		co_time = MST()
		t = transform_time(self.created, co_time)
		return render_str("input_view.html", time = t, content = self.user_input)

# A parent class for all handlers with some useful methods
# just call self.render( <template name>, <arguments> ) to
# render a page from any handler
class MainHandler(webapp2.RequestHandler):
    def render(self, template, **kw):
        self.response.out.write(render_str(template, **kw))

    def login(self, admin=False):
        if admin:
            cookie_name = 'admin'
        else:
            cookie_name = 'user'
        cookie = self.request.cookies.get(cookie_name)
        if not cookie:
            cookie = make_cookie(20)
            self.response.headers.add_header('Set-Cookie', '%s=%s; Path=/' % (cookie_name, cookie))
        client_id = cookie + CHANNEL_KEY
        token = channel.create_channel(client_id)

        logged_in = memcache.get(LOGGED_IN)
        if logged_in:
            if client_id not in logged_in:
                logged_in.append(client_id)
        else:
            logged_in = [client_id]
        memcache.set(LOGGED_IN, logged_in)
        return token

    def get_id(self):
        cookie = self.request.cookies.get('user')
        if cookie:
            return cookie + CHANNEL_KEY

    def get_message(self, votes):
        return json.dumps(votes)

    def send_update(self, votes):
        message = self.get_message(votes)
        logged_in = memcache.get(LOGGED_IN)
        if logged_in:
            for client_id in logged_in:
                channel.send_message(client_id, message)

class VoteHandler(MainHandler):
    def get(self):
        token = self.login()
        vote = self.request.get('vote')
        songs = memcache.get(VOTE)
        if not songs:
            songs = [["Thrift Shop - Macklemore", 0],
                     ["Thriller - Michael Jackson", 0],
                     ["Mirrors - Justin Timberlake", 0]]
            memcache.set(VOTE, songs)
        self.render('vote.html', songs = songs, token = token, user = self.get_id())

    def post(self):
        vote = self.request.get('vote')
        if vote:
            self.vote(vote)
        from_queue = self.request.get('from_queue')
        if from_queue:
            self.redirect('/queue')
        else:
            self.redirect('/vote')

    def vote(self, vote):
        songs = memcache.get(VOTE)
        if songs:
            for song in songs:
                if song[0] == vote:
                    song[1] += 1
                    break
        self.send_update(songs)
        memcache.set(VOTE, songs)

class ThanksHandler(MainHandler):
    def get(self):
        songs = memcache.get(VOTE)
        self.render('thanks.html', songs = songs)

class QueueHandler(MainHandler):
    def get(self):
        queue = memcache.get(QUEUE)
        vote_songs = memcache.get(VOTE)
        users = memcache.get(LOGGED_IN)
        token = self.login(admin=True)
        if not users:
            users = []
        if not queue:
            queue = ["Thrift Shop - Macklemore",
                     "Thriller - Michael Jackson",
                     "Mirrors - Justin Timberlake"]
            memcache.set(QUEUE, queue)
        if not vote_songs:
            vote_songs = []
        self.render('queue.html', songs = queue, vote_songs = vote_songs, token = token, users = users)

    def post(self):
        queue = memcache.get(QUEUE)
        vote_songs = memcache.get(VOTE)
        if not queue:
            queue = []
        if not vote_songs:
            vote_songs = []
        remove = self.request.get('remove')
        if remove:
            queue.remove(remove)
            memcache.set(QUEUE, queue)
            self.redirect('/queue')

        name = self.request.get('name')
        artist = self.request.get('artist')
        genre = self.request.get('genre')
        index = self.request.get('position')
        index = self.validate_position(index, len(queue))

        if name:
            if artist:
                song = [name, artist]
                queue.insert(index, ' - '.join(song))
            else:
                queue.insert(index, name)
            memcache.set(QUEUE, queue)
            self.redirect('/queue')

    def validate_position(self, index, queue_length):
        if index.isdigit():
            return int(index)
        else:
            return queue_length


class NextHandler(MainHandler):
    def post(self):
        songs = memcache.get(QUEUE)
        songs = songs[:3]
        vote = [[song, 0] for song in songs]
        memcache.set(VOTE, vote)
        self.redirect('/queue')

class ClearHandler(MainHandler):
    def post(self):
        users = memcache.get(LOGGED_IN)
        for user in users:
            self.response.headers.add_header('Set-Cookie', 'user=%s; Path=/' % '')
        memcache.set(LOGGED_IN, [])
        self.redirect('/queue')

# add new pages here
app = webapp2.WSGIApplication([
    ('/', VoteHandler),
    ('/vote', VoteHandler),
    ('/queue', QueueHandler),
    ('/thanks', ThanksHandler),
    ('/next', NextHandler),
    ('/clear', ClearHandler)
], debug=True)