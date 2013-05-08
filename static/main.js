onOpened = function() {
    connected = true;
    //sendMessage('opened');
};

onMessage = function(message) {
    update = $.parseJSON(message.data);
    if (update.new_vote === true)
        for (var i = 0; i < 3; i++) {
            var song_name = document.getElementById('song' + i);
            song_name.innerHTML = update.votes[i].song;
            var artist = document.getElementById('artist' + i);
            artist.innerHTML = update.votes[i].artist;
            var votes = document.getElementById('votes' + i);
            votes.innerHTML = "Current Number of Votes " + update.votes[i].votes;

            var btn = document.getElementById('button' + i);
            btn.disabled = false;

            document.getElementById('message').innerHTML = "";
            btn.onclick = (function() {
                var currentI = i;
                return function() {
                    document.getElementById("vote").value=update.votes[currentI].vote_order;
                    document.button_submit.submit();
                }

            })();
        }
    else
        for (var i = 0; i < 3; i++) {
            document.getElementById('votes' + i).innerHTML = "Current Number of Votes " + update.votes[i].votes;
        }

};

onError = function(err) {
    // alert(err);
};

onClose = function() {
    //reconnect();
};


