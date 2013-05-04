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
import hashlib
import hmac

from VoteRecord import VoteRecord
from Input import Input
from BetaSignups import BetaSignups

from google.appengine.ext import db
from google.appengine.api import memcache
from google.appengine.api import channel



### Globals ###

# These are key names for memcache
QUEUE = "queue"
VOTE = "vote"
LOGGED_IN = "logged_in"

# This is the event name the will be stored in the db
EVENT = "testing"

# These are random strings for generating the channel tokens
CHANNEL_KEY = "klsjht3q48o7faekrgh3i7qk4jbrqb"
ADMIN_KEY = "kjglh53079gyhiernil37rfu4trtbg"



### Useful functions ###

def escape_html(s):
    s = s.replace("&", "&amp;")
    return cgi.escape(s, quote = True)

# shortcut function for rendering jinja templates
def render_str(template, **params):
    t = jinja_env.get_template(template)
    return t.render(params)

def make_cookie(n):
    return''.join(random.choice(string.letters + string.digits) for a in range(n))

# adjust to our time zone
def tz_adjust(entries):
    for e in entries:
        e.created = e.created + datetime.timedelta(hours = -6)




### Main Code ###


# set up a directory for jinja html templates
template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir),
                               autoescape = True)



### Handlers ###


# A parent class for all handlers with some useful methods
class MainHandler(webapp2.RequestHandler):

    # Call this to render a template
    def render(self, template, **kw):
        self.response.out.write(render_str(template, **kw))

    # Returns a token for channel communication
    def get_token(self, admin=False):
        if admin:
            cookie_name = 'admin'
            key = ADMIN_KEY
        else:
            cookie_name = 'user'
            key = CHANNEL_KEY

        cookie = self.request.cookies.get(cookie_name)
        if not cookie:
            cookie = make_cookie(20)
            self.response.headers.add_header('Set-Cookie', '%s=%s; Path=/' % (cookie_name, cookie))
        client_id = cookie + key
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

    # Format the message in json to send over channel
    def get_message(self, votes, new_vote, old_vote):
        if new_vote:
            vote = {'votes': votes, 'new_vote': new_vote, 'old_vote': old_vote}
        else:
            vote = {'votes': votes, 'new_vote': new_vote}
        return json.dumps(vote)

    # Send message to all channels
    def send_update(self, votes, new_vote=False, old_vote=None):
        message = self.get_message(votes, new_vote, old_vote)
        logged_in = memcache.get(LOGGED_IN)
        if logged_in:
            for client_id in logged_in:
                if not new_vote or not ADMIN_KEY in client_id:
                    channel.send_message(client_id, message)


class LandingHandler(MainHandler):
    def get(self):
        self.render('landing.html')

    def post(self):
        email = self.request.get('signup')
        a = BetaSignups(email = email)
        a.put()
        self.render('landing.html', message = "Thanks for signing up! We'll email you when the beta is ready")


# Voting interface
class VoteHandler(MainHandler):
    def get(self):
        token = self.get_token()
        songs = memcache.get(VOTE)

        if not songs:
            self.redirect('/no_vote')

        message = ""
        voted = False

        json_songs = {'songs': songs, 'voted': voted}
        self.render('vote2.html', songs = json.dumps(json_songs),
                                  token = token,
                                  message = message)

    def post(self):
        suggestion = self.request.get('suggestion')
        if suggestion:
            a = Input(suggestion = suggestion, event = EVENT)
            a.put()
            message = "Thanks for your input!"
        else:
            message = "Thanks for your vote!<br>You will be able to vote again on the next song"
        vote = self.request.get('vote')

        logging.error(vote)
        if vote:
            self.vote(vote)

        # if coming from queue page, redirect us back
        from_queue = self.request.get('from_queue')
        if from_queue:
            self.redirect('/queue')

        # else register the vote normally
        else:
            voted = True
            songs = memcache.get(VOTE)
            token = self.get_token()
            json_songs = {'songs': songs, 'voted': voted}
            self.render('vote2.html', songs = json.dumps(json_songs),
                                      token = token,
                                      message = message)

    def vote(self, vote):
        songs = memcache.get(VOTE)
        if songs:
            for song in songs:
                if song[0] == vote:
                    song[1] += 1
                    break
        self.send_update(songs)
        memcache.set(VOTE, songs)

class NoVoteHandler(MainHandler):
    def get(self):
        token = self.get_token()
        self.render('/no_vote.html', token = token)


# Our interface for controlling the app
class QueueHandler(MainHandler):
    def get(self):

        # Get all values we need from db and memcache
        queue = memcache.get(QUEUE)
        vote_songs = memcache.get(VOTE)
        users = memcache.get(LOGGED_IN)
        if not users:
            users = []

        suggestions = list(db.GqlQuery("SELECT * FROM Input WHERE event ='" + EVENT + "' ORDER BY created DESC"))
        vote_db = list(db.GqlQuery("SELECT * FROM VoteRecord WHERE event ='" + EVENT + "'"))
        vote_db = [vote.unpack() for vote in vote_db]
        tz_adjust(suggestions)

        # our token for channel communication
        token = self.get_token(admin=True)

        # If we don't have any songs in queue, add test songs
        if not queue:
            queue = ["Thrift Shop - Macklemore",
                     "Thriller - Michael Jackson",
                     "Mirrors - Justin Timberlake",
                     "I'm on a Boat - T-Pain",
                     "Harlem Shake - Baauer",
                     "DeadMau5 - Strobe"]
            memcache.set(QUEUE, queue)

        # If we don't have a vote ready, add a test vote
        if not vote_songs:
            vote_songs = [["Awesome Song1", 0],
                          ["Awesome Song2", 0],
                          ["Awesome Song3", 0]]
            memcache.set(VOTE, vote_songs)

        self.render('queue.html', songs = queue,
                                  vote_songs = vote_songs,
                                  token = token,
                                  users = users,
                                  suggestions = suggestions,
                                  vote_db = vote_db)

    def post(self):

        # get values from db and memcache
        queue = memcache.get(QUEUE)
        vote_songs = memcache.get(VOTE)
        if not queue:
            queue = []
        if not vote_songs:
            vote_songs = []

        # if removing a song from the queue,
        # just remove it and refresh the page
        remove = self.request.get('remove')
        if remove:
            queue.remove(remove)
            memcache.set(QUEUE, queue)
            self.redirect('/queue')

        # otherwise get remaining values from http request
        name = self.request.get('name')
        artist = self.request.get('artist')
        genre = self.request.get('genre')
        index = self.request.get('position')
        index = self.validate_position(index, len(queue))

        # add new song to queue
        if name:
            if artist:
                song = [name, artist]
                queue.insert(index, ' - '.join(song))
            else:
                queue.insert(index, name)
            memcache.set(QUEUE, queue)
            self.redirect('/queue')

    # helper function, makes sure position is an int
    # if not just return last index of queue by default
    def validate_position(self, index, queue_length):
        if index.isdigit():
            return int(index)
        else:
            return queue_length


# Handles 'generate next vote' button
class NextHandler(MainHandler):
    def post(self):
        # get current queue and vote data
        songs = memcache.get(QUEUE)
        old_vote = memcache.get(VOTE)

        # store old vote data in db
        if old_vote:
            vote_db_entry = VoteRecord(votes = json.dumps(old_vote), event = EVENT)
            vote_db_entry.put()

        # store new vote data in memcache so it will be broadcast
        # this is the top three songs on queue
        top = songs[:3]
        vote = [[song, 0] for song in top]
        memcache.set(VOTE, vote)

        # update the queue so the top three songs are removed
        queue = songs[3:]
        memcache.set(QUEUE, queue)

        # send message to all channels to update
        self.send_update(vote, True, old_vote)

        self.redirect('/queue')


# To clear all users
class ClearHandler(MainHandler):
    def post(self):
        users = memcache.get(LOGGED_IN)
        for user in users:
            self.response.headers.add_header('Set-Cookie', 'user=%s; Path=/' % '')
        memcache.set(LOGGED_IN, [])
        self.redirect('/queue')

# For testing
class TestHandler(MainHandler):
    def get(self):
        lst = {}
        lst["iam"] = [1,2,3]
        logging.error(json.dumps(lst))
        self.render('/test.html', message = "test", lst =json.dumps(lst))

# Not used yet, but might be able to moniter channels eventually
"""
class ChannelConnectedHandler(MainHandler):
    def post(self):
        client_id = self.request.get('from')
        self.send_update()
"""
    

app = webapp2.WSGIApplication([
    ('/', LandingHandler),
    ('/vote', VoteHandler),
    ('/queue', QueueHandler),
    ('/next', NextHandler),
    ('/clear', ClearHandler),
    ('/test', TestHandler),
    ('/no_vote', NoVoteHandler)
    #('/_ah/channel/connected/', ChannelConnectedHandler)
], debug=True)