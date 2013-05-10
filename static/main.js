onOpened = function() {
    connected = true;
    //sendMessage('opened');
};

onMessage = function(message) {
    update = $.parseJSON(message.data);
        
    if (update.new_vote === true)

        for (var i = 0; i < update.votes.length; i++) {
            var song_name = document.getElementById('song' + i);
            song_name.innerHTML = update.votes[i].song;
            var artist = document.getElementById('artist' + i);
            artist.innerHTML = update.votes[i].artist;
            var num_votes = document.getElementById('votes' + i);
            num_votes.innerHTML = update.votes[i].votes;

            var btn = document.getElementById('button' + i);
            btn.disabled = false;
            btn.style.background='white';

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
        for (var i = 0; i < update.votes.length; i++) {
            document.getElementById('votes' + i).innerHTML = update.votes[i].votes;
        }

};

onError = function(err) {
    // alert(err);
};

onClose = function() {
    //connected = false;
}
