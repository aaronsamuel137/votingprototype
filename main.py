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
LIKES = "likes"
ADMIN = "admin"
SORTED_LIKES = "likes_by_number"
OLD_COOKIES = 'old_cookies'

# This is the event name the will be stored in the db
EVENT = "testing"

# These are random strings for generating the channel tokens
CHANNEL_KEY = "klsjht3q48o7faekrgh3i7qk4jbrqb"
ADMIN_KEY = "kjglh53079gyhiernil37rfu4trtbg"

# These are for interfacing with the facebook app
FACEBOOK_APP_ID = "460990543975721"
FACEBOOK_APP_SECRET = "fe38d6dd8f118e20c99378f5151d28d1"
PERMISSIONS = "user_likes" #,friends_likes,user_events"

TEST_QUEUE = [{'song': "Thrift Shop", 'artist': "Macklemore"},
              {'song': "Thriller", 'artist': "Michael Jackson"},
              {'song': "Mirrors", 'artist': "Justin Timberlake"},
              {'song': "I'm on a Boat", 'artist': "T-Pain"},
              {'song': "Harlem Shake", 'artist': "Baauer"},
              {'song': "Strobe", 'artist': "DeadMau5"}]

TEST_VOTE = [{'song': "Awesome Song1", 'artist': "Awesome Artist1", 'votes': 0, 'vote_order': 1},
             {'song': "Awesome Song2", 'artist': "Awesome Artist2", 'votes': 0, 'vote_order': 2},
             {'song': "Awesome Song3", 'artist': "Awesome Artist3", 'votes': 0, 'vote_order': 3}]


### Main Code ###


# set up a directory for jinja html templates
template_dir = os.path.join(os.path.dirname(__file__), 'templates')
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir),
                               autoescape = True)

# shortcut function for rendering jinja templates
def render_str(template, **params):
    t = jinja_env.get_template(template)
    return t.render(params)

# for counting anonymous users
count = 0
def counter():
    global count
    count += 1
    return count

def get_from_cache(key):
    cached = memcache.get(key)
    if cached:
        return cached


# keeps track of who has voted
has_voted = {}

### Handlers ###


# A parent class for all handlers with some useful methods
class MainHandler(webapp2.RequestHandler):

    # Call this to render a template
    def render(self, template, **kw):
        self.response.out.write(render_str(template, **kw))

    # returns a token for channel communication,
    # as well as the kind of user (facebook, anonymous, or admin)
    def get_token(self, is_admin=False):
        # get id for which kind of login
        # for anonymous and admin, just use the cookie
        # for FB, use the FB user id
        user_cookie = self.request.cookies.get('user')     
        admin_cookie = self.request.cookies.get('admin')
        fb_user = self.current_user
        channels = memcache.get(CHANNELS)
        if not channels:
            channels = {}

        logging.error(channels)

        if is_admin:
            if not admin_cookie:
                admin_cookie = util.make_cookie(20)
                self.response.headers.add_header('Set-Cookie', 'admin=%s; Path=/' % admin_cookie)

                admin_channels = memcache.get(ADMIN)
                if admin_channels:
                    if admin_cookie + ADMIN_KEY not in admin_channels:
                        admin_channels.append(admin_cookie + ADMIN_KEY)
                else:
                    admin_channels = [admin_cookie + ADMIN_KEY]
                memcache.set(ADMIN, admin_channels)

            if admin_cookie in channels:
                return self.existing_token(channels, admin_cookie, 'admin')

            client_id = admin_cookie + ADMIN_KEY
            token = channel.create_channel(client_id)
            name = "Admin"
            channel_id = admin_cookie
            user_type = 'admin'

        elif fb_user:
            if fb_user.id in channels:
                return self.existing_token(channels, fb_user.id, 'facebook')

            else:
                client_id = fb_user.id + CHANNEL_KEY
                token = channel.create_channel(client_id)
                name = fb_user.name
                channel_id = fb_user.id
                user_type = 'facebook'

        elif user_cookie:
            if user_cookie in channels:
                return self.existing_token(channels, user_cookie, 'anonymous')

            else:
                client_id = user_cookie + CHANNEL_KEY
                token = channel.create_channel(client_id)
                name = "User" + str(counter())
                channel_id = user_cookie
                user_type = 'anonymous'
        
        else:
            token = channel_id = client_id = name = user_type = None
            self.redirect('/login')

        if channel_id and channel_id not in channels:
            channels[channel_id] = {'token': token,
                                    'client_id': client_id,
                                    'admin': is_admin,
                                    'name': name,
                                    'inactive': False}
        
        memcache.set(CHANNELS, channels)
        self.update_channels()
        logging.error(channels)
        return token, user_type

    def existing_token(self, channels, channel_id, user_type):
        return channels[channel_id]['token'], user_type



    # Format the message in json to send over channel
    def get_message(self, votes, new_vote):
        message = {'votes': votes, 'new_vote': new_vote, 'kind': 'votes'}
        return json.dumps(message)

    # Send message to all channels
    def send_update(self, votes, new_vote=False, from_queue=False):
        message = self.get_message(votes, new_vote)
        channels = memcache.get(CHANNELS)
        if channels:
            if from_queue:
                for token in channels:
                    if channels[token]['admin'] == False:
                        channel.send_message(channels[token]['client_id'], message)
            else:
                for token in channels:
                    channel.send_message(channels[token]['client_id'], message)

    # send message to refresh dataview if new FB likes are added
    def update_facebook_likes(self):
        admin_channels = memcache.get(ADMIN)
        util.sort_likes()
        likes = memcache.get(LIKES)
        message = json.dumps({'likes': likes, 'kind': 'likes'})
        if admin_channels:
            for admin_token in admin_channels:
                channel.send_message(admin_token, message)

    # send message to refresh dataview if channels open or close
    def update_channels(self):
        admin_channels = memcache.get(ADMIN)
        channels = memcache.get(CHANNELS)
        message = json.dumps({'channels': channels, 'kind': 'channels'})
        if admin_channels:
            for admin_token in admin_channels:
                channel.send_message(admin_token, message)

    # Returns the logged in Facebook user, or None if unconnected
    @property
    def current_user(self):
        if not hasattr(self, '_current_user'):
            self._current_user = None
            user_id = util.parse_cookie(self.request.cookies.get('fb_user'))
            if user_id:
                self._current_user = User.get_by_key_name(user_id)
        return self._current_user


class LoginHandler(MainHandler):
    def get(self):
        self.render('login.html')

    # for handling annoymous logins
    # facebook logins use FBLoginHandler
    def post(self):
        cookie = util.make_cookie(20)
        self.response.headers.add_header('Set-Cookie', 'user=%s; Path=/' % cookie)
        self.redirect('/vote')


class FBLoginHandler(MainHandler):
    def get(self):
        # code sent from FB
        verification_code = self.request.get('code')

        # get our root path
        url = self.request.path_url

        # args passed to url encode for facebook login
        args = dict(client_id = FACEBOOK_APP_ID,
                    redirect_uri = url,
                    scope = PERMISSIONS)

        # if we are redirected back from FB
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
            if not likes_list:
                likes_list = {}
            likes_list[profile['name']] = music_likes
            memcache.set(LIKES, likes_list)
            util.sort_likes()

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

        # if we have no code from FB, go to FB for auth code
        else:
            self.redirect(
                "https://graph.facebook.com/oauth/authorize?" +
                urllib.urlencode(args))


class LogoutHandler(MainHandler):
    def get(self):
        channels = memcache.get(CHANNELS)
        if channels:

            # If FB login
            fb_user = self.current_user
            cookie = self.request.cookies.get('user')
            if fb_user:
                channel_id = fb_user.id
                util.set_cookie(self.response, "fb_user", "")     
                likes = memcache.get(LIKES)
                if likes:
                    likes.pop(fb_user.name, None)
                    util.sort_likes()
                    memcache.set(LIKES, likes)
            
            # If anonymous login
            else:
                channel_id = cookie
                self.response.headers.add_header('Set-Cookie', 'user=%s; Path=/' % '')

            for channel in channels:
                if channel == channel_id:
                    channels.pop(channel, None)                    
                    memcache.set(CHANNELS, channels)
                    self.update_channels()
                    break
             
            self.update_channels()
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
        token, user_type = self.get_token()
        msg = self.request.get('message')
        if msg:
            message = msg
        else:
            message = ""

        if has_voted.get(token):
            voted = True
        else:
            voted = False
        self.render_vote(message, voted, token, user_type)

    def post(self):
        token, user_type = self.get_token()
        # if we get a suggestion, add to db
        suggestion = self.request.get('suggestion')
        if suggestion:
            a = Input(suggestion = suggestion, event = EVENT)
            a.put()
            message = "Thanks for your input!"  
            voted = False
            self.update_channels()
            self.render_vote(message, voted, token, user_type)
        
        # else handle the vote
        else:
            message = "Thanks for your vote!<br>You will be able to vote again on the next song"
            voted = True


            from_queue = self.request.get('from_queue')
            vote = self.request.get('vote')

            # if from admin page redirect us back
            if from_queue and vote:
                self.vote(vote)
                self.redirect('/queue')

            # else make sure people can't vote twice
            # and render the vote page again
            elif vote:
                if not has_voted.get(token):
                    has_voted[token] = True
                    self.vote(vote)
                else:
                    message = "You will be able to vote again on the next song"

            self.render_vote(message, voted, token, user_type)

    def render_vote(self, message, voted, token, user_type):
        # get the current vote or redirect to no vote page
        songs = memcache.get(VOTE)
        if not songs:
            self.redirect('/no_vote')

        if user_type == 'facebook':
            welcome = "You are logged in as " + self.current_user.name
        else:
            welcome = ""

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
        token, user_type = self.get_token()
        self.render('/no_vote.html', token = token)


# Our interface for controlling the app
class QueueHandler(MainHandler):
    def get(self):
        self.render_queue()

    def post(self): 
        queue = memcache.get(QUEUE)
        name = self.request.get('name')
        artist = self.request.get('artist')
        message = ""

        # if removing a song from the queue,
        # just remove it and render the page
        remove = self.request.get('remove')
        if remove:
            for i, song in enumerate(queue):
                if song['song'] == remove:
                    queue.pop(i)
            memcache.set(QUEUE, queue)

        # otherwise get remaining values from http request
        # for inserting into queue
        elif queue:
            index = self.validate_position(self.request.get('position'), len(queue))
            if name and artist:
                queue.insert(index, {'song': name, 'artist': artist})
                memcache.set(QUEUE, queue)
            else:
                message = "name and artist required"

        # if no queue, create one with this song
        else:
            queue = [{'song': name, 'artist': artist}]
            memcache.set(QUEUE, queue)

        self.render_queue(message)

    def render_queue(self, message=""):
        # Get queue and votes from memcache or initialize to test values
        queue = memcache.get(QUEUE)
        if not queue:
            queue = TEST_QUEUE
            memcache.set(QUEUE, queue)

        vote_songs = memcache.get(VOTE)
        if not vote_songs:
            vote_songs = TEST_VOTE
            memcache.set(VOTE, vote_songs)
            self.send_update(vote_songs)

        # get user suggestions from DB
        suggestions = list(db.GqlQuery("SELECT * FROM Input WHERE event ='" + EVENT + "' ORDER BY created DESC"))
        util.tz_adjust(suggestions)

        # our token for channel communication
        token, user_type = self.get_token(is_admin=True)

        channels = memcache.get(CHANNELS)
        users = []
        for user in channels:
            if channels[user]['inactive'] == False:
                users.append(channels[user]['name'])
  
        # get FB likes
        likes = memcache.get(SORTED_LIKES)
        if likes:
            length = len(likes)
        else:
            length = 0
            likes = []
            
        self.render('queue.html', songs = queue,
                                  vote_songs = vote_songs,
                                  token = token,
                                  users = users,
                                  suggestions = suggestions,
                                  likes = likes,
                                  length = length,
                                  message = message)

    # helper function, makes sure position is an int
    # if not just return last index of queue by default
    def validate_position(self, index, queue_length=0):
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
        for token in has_voted:
            has_voted[token] = False

        # send message to all channels to update
        self.send_update(vote, True)

        self.redirect('/queue')


# To clear all users
# mostly for testing purposes
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

        global count
        count = 0
        memcache.set(LIKES, {})
        memcache.set(SORTED_LIKES, {})
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
        """
        client_id = self.request.get('from')
        channels = memcache.get(CHANNELS)
        if channels and client_id:
            for channel in channels:
                if channels[channel]['client_id'] == client_id and channels[channel]['inactive'] == True:
                    channels[channel]['inactive'] = False
                    self.update_channels()
                    memcache.set(CHANNELS, channels)
                    break
        """


# if a channel disconnects, update the dataview
class ChannelDisconnectedHandler(MainHandler):
    pass
    """
    def post(self):
        client_id = self.request.get('from')
        channels = memcache.get(CHANNELS)
        if channels and client_id:
            for channel in channels:
                if channels[channel]['client_id'] == client_id:
                    channels.pop(channel, None)
                    self.update_channels()
                    memcache.set(CHANNELS, channels)
                    break
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