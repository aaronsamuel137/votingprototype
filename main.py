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
import util
import urllib2
import urllib
import urlparse
import facebook

from User import User
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
CHANNELS = "channels"
OLD_CHANNELS = "old channels"
LIKES = "likes"
ADMIN = "admin"

# This is the event name the will be stored in the db
EVENT = "testing"

# These are random strings for generating the channel tokens
CHANNEL_KEY = "klsjht3q48o7faekrgh3i7qk4jbrqb"
ADMIN_KEY = "kjglh53079gyhiernil37rfu4trtbg"

# These are for interfacing with the facebook app
FACEBOOK_APP_ID = "460990543975721"
FACEBOOK_APP_SECRET = "fe38d6dd8f118e20c99378f5151d28d1"
PERMISSIONS = "user_likes" #,friends_likes,user_events"


### Main Code ###


# set up a directory for jinja html templates
template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir),
                               autoescape = True)

# shortcut function for rendering jinja templates
def render_str(template, **params):
    t = jinja_env.get_template(template)
    return t.render(params)

def counter():
    global count
    count += 1
    return count

count = 0
has_voted = {}


### Handlers ###


# A parent class for all handlers with some useful methods
class MainHandler(webapp2.RequestHandler):

    # Call this to render a template
    def render(self, template, **kw):
        self.response.out.write(render_str(template, **kw))

    # Returns a token for channel communication
    def get_token(self):
        cookie = self.request.cookies.get('user')
        if cookie:            
            client_id = cookie + CHANNEL_KEY
            token = channel.create_channel(client_id)
            self.add_channel(client_id)
        else:
            token = None
            self.redirect('/login')

        return token, client_id

    def get_admin_token(self):
        cookie = self.request.cookies.get('admin')
        if not cookie:
            cookie = util.make_cookie(20)
            self.response.headers.add_header('Set-Cookie', 'admin=%s; Path=/' % cookie)
            
            admin_channels = memcache.get(ADMIN)
            if admin_channels: 
                admin_channels.append(cookie + ADMIN_KEY)
            else:
                admin_channels = [cookie + ADMIN_KEY]
            memcache.set(ADMIN, admin_channels)

        client_id = cookie + ADMIN_KEY
        token = channel.create_channel(client_id)
        self.add_channel(client_id, admin=True)

        return token

    def add_channel(self, client_id, admin=False, fb_user=None):
        channels = memcache.get(CHANNELS)
        if not channels:
            channels = {}
        if client_id not in channels:
            has_voted[client_id] = False
            if fb_user:
                channels[client_id] = fb_user
            elif admin:
                channels[client_id] = "Admin"
            else:
                channels[client_id] = "User" + str(counter())
        memcache.set(CHANNELS, channels)

    def get_token_fb(self, fb_user):
        client_id = fb_user.id + CHANNEL_KEY
        token = channel.create_channel(client_id)
        self.add_channel(client_id, fb_user=fb_user.name)
        self.update_channels()
        return token, client_id

    def get_id(self):
        cookie = self.request.cookies.get('user')
        if cookie:
            return cookie + CHANNEL_KEY

    # Format the message in json to send over channel
    def get_message(self, votes, new_vote, old_vote):
        if new_vote:
            message = {'votes': votes, 'new_vote': new_vote, 'old_vote': old_vote, 'kind': 'votes'}
        else:
            message = {'votes': votes, 'new_vote': new_vote, 'kind': 'votes'}
        return json.dumps(message)

    # Send message to all channels
    def send_update(self, votes, new_vote=False, old_vote=None):
        message = self.get_message(votes, new_vote, old_vote)
        channels = memcache.get(CHANNELS)
        if channels:
            for client_id in channels:
                channel.send_message(client_id, message)

    def update_facebook_likes(self):
        admin_channels = memcache.get(ADMIN)
        likes = memcache.get(LIKES)
        message = json.dumps({'likes': likes, 'kind': 'likes'})
        if admin_channels:
            for admin in admin_channels:
                channel.send_message(admin, message)

    def update_channels(self):
        admin_channels = memcache.get(ADMIN)
        channels = memcache.get(CHANNELS)
        logging.error(admin_channels)
        message = json.dumps({'channels': channels, 'kind': 'channels'})
        if admin_channels:
            for admin in admin_channels:
                channel.send_message(admin, message)

    @property
    def current_user(self):
        """Returns the logged in Facebook user, or None if unconnected."""
        if not hasattr(self, '_current_user'):
            self._current_user = None
            user_id = util.parse_cookie(self.request.cookies.get('fb_user'))
            if user_id:
                self._current_user = User.get_by_key_name(user_id)
        return self._current_user


class LoginHandler(MainHandler):
    def get(self):
        self.render('login.html')

    def post(self):
        cookie = util.make_cookie(20)
        self.response.headers.add_header('Set-Cookie', 'user=%s; Path=/' % cookie)
        self.update_channels()
        self.redirect('/vote')


class FBLoginHandler(MainHandler):
    def get(self):
        verification_code = self.request.get('code')

        # get our root path
        url = self.request.path_url

        # args passed to url encode for facebook login
        args = dict(client_id = FACEBOOK_APP_ID,
                    redirect_uri = url,
                    scope = PERMISSIONS)


        if verification_code:
            args['client_secret'] = FACEBOOK_APP_SECRET
            args['code'] = verification_code

            query_string = urllib2.urlopen(
                "https://graph.facebook.com/oauth/access_token?" +
                urllib.urlencode(args)).read()
            
            response = urlparse.parse_qs(query_string)
            access_token = response['access_token'][-1]

            # Download the user profile and cache a local instance of the
            # basic profile info
            profile = json.load(urllib.urlopen(
                "https://graph.facebook.com/me?" +
                urllib.urlencode(dict(access_token = access_token))))

            # Get music likes from Facebook
            graph = facebook.GraphAPI(access_token)
            user = graph.get_object('me')
            likes = graph.get_object(user['id'] + '/music')
            music_likes = [like['name'] for like in likes['data']]

            # update list of likes for dataview
            likes_list = memcache.get(LIKES)
            likes_list = {}
            likes_list[profile['name']] = music_likes
            memcache.set(LIKES, likes_list)

            # add user to db
            user = User(key_name = str(profile['id']),
                        id = str(profile['id']),
                        name = profile['name'],
                        access_token = access_token,
                        profile_url = profile['link'],
                        likes = json.dumps(likes['data']))
            user.put()

            util.set_cookie(self.response, 'fb_user', str(profile['id']))
                #expires=time.time() + 30 * 86400)
  
            self.redirect('/vote')

        else:
            self.redirect(
                "https://graph.facebook.com/oauth/authorize?" +
                urllib.urlencode(args))


class LogoutHandler(MainHandler):
    def get(self):
        fb_user = self.current_user
        channels = memcache.get(CHANNELS)
        if fb_user:
            channels.pop(fb_user.id + CHANNEL_KEY, None)
            util.set_cookie(self.response, "fb_user", "") #expires=time.time() - 86400)       
            likes = memcache.get(LIKES)
            likes.pop(fb_user.name, None)
            memcache.set(LIKES, likes)
            self.update_facebook_likes()
        else:
            cookie = self.request.cookies.get('user')
            channels.pop(cookie + CHANNEL_KEY, None)
            self.response.headers.add_header('Set-Cookie', 'user=%s; Path=/' % '')
            self.update_channels()
        memcache.set(CHANNELS, channels)
        self.redirect('/login')

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
        # check if FB login
        # if so, open a channel
        fb_user = self.current_user
        user_cookie = self.request.cookies.get('user')
        if fb_user:
            welcome = "Welcome " + fb_user.name + "!"
            token, client_id = self.get_token_fb(fb_user)           
        
        # check if anonymous login   
        elif user_cookie:
            welcome = "Logged in"
            token, client_id = self.get_token()

        # if not logged in redirect to login
        else:
            token = None
            welcome = None
            self.redirect('/login')

        # get the current vote or redirect to no vote page
        songs = memcache.get(VOTE)
        if not songs:
            self.redirect('/no_vote')

        message = ""
        voted = False

        json_songs = {'songs': songs, 'voted': voted}
        self.render('vote2.html', songs = json.dumps(json_songs),
                                  token = token,
                                  message = message,
                                  welcome = welcome)

    def post(self):
        fb_user = self.current_user
        user_cookie = self.request.cookies.get('user')
        if fb_user:
            welcome = "Welcome " + fb_user.name + "!"
            token, client_id = self.get_token_fb(fb_user)
        
        # check if anonymous login   
        elif user_cookie:
            welcome = "Logged in"
            token, client_id = self.get_token()

        # if not logged in redirect to login
        else:
            token = None
            welcome = None
            client_id = None
            self.redirect('/login')

        # if we get a suggestion, add to db
        suggestion = self.request.get('suggestion')
        if suggestion:
            a = Input(suggestion = suggestion, event = EVENT)
            a.put()
            message = "Thanks for your input!"
            self.update_channels()
        else:
            message = "Thanks for your vote!<br>You will be able to vote again on the next song"


        from_queue = self.request.get('from_queue')
        vote = self.request.get('vote')

        # if from admin page redirect us back
        if from_queue:
            if vote:
                self.vote(vote)
                self.redirect('/queue')

        # else make sure people can't vote twice
        # and render the vote page again
        elif vote:
            if not has_voted.get(client_id):
                has_voted[client_id] = True
                self.vote(vote)

            voted = True
            songs = memcache.get(VOTE)
            json_songs = {'songs': songs, 'voted': voted}
            self.render('vote2.html', songs = json.dumps(json_songs),
                                      token = token,
                                      message = message,
                                      welcome = welcome)

    def vote(self, vote):
        songs = memcache.get(VOTE)
        if songs:
            for song in songs:
                if song['vote_order'] == int(vote):
                    song['votes'] += 1
                    break
        self.send_update(songs)
        memcache.set(VOTE, songs)

class NoVoteHandler(MainHandler):
    def get(self):
        fb_user = self.current_user
        if fb_user:
            token, client_id = self.get_token_fb()
        else:
            token, client_id = self.get_token()
        self.render('/no_vote.html', token = token)


# Our interface for controlling the app
class QueueHandler(MainHandler):
    def get(self):

        # Get all values we need from db and memcache
        queue = memcache.get(QUEUE)
        vote_songs = memcache.get(VOTE)

        suggestions = list(db.GqlQuery("SELECT * FROM Input WHERE event ='" + EVENT + "' ORDER BY created DESC"))
        #vote_db = list(db.GqlQuery("SELECT * FROM VoteRecord WHERE event ='" + EVENT + "'"))
        #vote_db = [vote.unpack() for vote in vote_db]
        util.tz_adjust(suggestions)

        # our token for channel communication
        token = self.get_admin_token()

        # If we don't have any songs in queue, add test songs
        if not queue:
            queue = [{'song': "Thrift Shop", 'artist': "Macklemore"},
                     {'song': "Thriller", 'artist': "Michael Jackson"},
                     {'song': "Mirrors", 'artist': "Justin Timberlake"},
                     {'song': "I'm on a Boat", 'artist': "T-Pain"},
                     {'song': "Harlem Shake", 'artist': "Baauer"},
                     {'song': "Strobe", 'artist': "DeadMau5"}]
            memcache.set(QUEUE, queue)

        # If we don't have a vote ready, add a test vote
        if not vote_songs:
            vote_songs = [{'song': "Awesome Song1", 'artist': "Awesome Artist1", 'votes': 0, 'vote_order': 1},
                          {'song': "Awesome Song2", 'artist': "Awesome Artist2", 'votes': 0, 'vote_order': 2},
                          {'song': "Awesome Song3", 'artist': "Awesome Artist3", 'votes': 0, 'vote_order': 3}]

            memcache.set(VOTE, vote_songs)
            self.send_update(vote_songs)

        users = memcache.get(CHANNELS)
        likes = memcache.get(LIKES)
        if not likes:
            likes = {'No Facebook logins': []}
        self.render('queue.html', songs = queue,
                                  vote_songs = vote_songs,
                                  token = token,
                                  users = users,
                                  suggestions = suggestions,
                                  likes = likes)
                                  #vote_db = vote_db)

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
            for i, song in enumerate(queue):
                if song['song'] == remove:
                    queue.pop(i)
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
        vote = []
        for i, song in enumerate(top):
            song['votes'] = 0
            song['vote_order'] = i + 1
            vote.append(song)
        memcache.set(VOTE, vote)

        # update the queue so the top three songs are removed
        queue = songs[3:]
        memcache.set(QUEUE, queue)

        # let clients vote again
        for client in has_voted:
            has_voted[client] = False

        # send message to all channels to update
        self.send_update(vote, True, old_vote)

        self.redirect('/queue')


# To clear all users
class ClearHandler(MainHandler):
    def post(self):
        channels = memcache.get(CHANNELS)
        if channels:
            for user in channels:
                self.response.headers.add_header('Set-Cookie', 'user=%s; Path=/' % '')
                self.response.headers.add_header('Set-Cookie', 'fb_user=%s; Path=/' % '')
            memcache.set(CHANNELS, {})

        admins = memcache.get(ADMIN)
        if admins:
            for admin in admins:
                self.response.headers.add_header('Set-Cookie', 'admin=%s; Path=/' % '')
            memcache.set(ADMIN, [])

        self.redirect('/queue')

# For testing
class TestHandler(MainHandler):
    def get(self):
        lst = {}
        lst["iam"] = [1,2,3]
        logging.error(json.dumps(lst))
        self.render('/test.html', message = "test", lst =json.dumps(lst))


class ChannelConnectedHandler(MainHandler):
    def post(self):
        pass

class ChannelDisconnectedHandler(MainHandler):
    def post(self):
        pass
        """
        client_id = self.request.get('from')
        channels = memcache.get(CHANNELS)
        old_channels = memcache.get(OLD_CHANNELS)
        if channels:
            try:
                channel_name = channels[client_id]
            except:
                pass
            channels.pop(client_id, None)
            try:
                old_channels[client_id] = channel_name
            except:
                old_channels = {}   
        self.update_channels()
        memcache.set(CHANNELS, channels)
        memcache.set(OLD_CHANNELS, old_channels)
        """

    

app = webapp2.WSGIApplication([
    ('/', LandingHandler),
    ('/auth/login', FBLoginHandler),
    ('/auth/logout', LogoutHandler),
    ('/login', LoginHandler),
    ('/vote', VoteHandler),
    ('/queue', QueueHandler),
    ('/next', NextHandler),
    ('/clear', ClearHandler),
    ('/test', TestHandler),
    ('/no_vote', NoVoteHandler),
    ('/_ah/channel/connected/', ChannelConnectedHandler),
    ('/_ah/channel/disconnected/', ChannelDisconnectedHandler)
], debug=True)