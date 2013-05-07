onOpened = function() {
    connected = true;
    //sendMessage('opened');
};

onMessage = function(message) {
    update = $.parseJSON(message.data);
    if (update.new_vote === true)
        for (var i = 0; i < 3; i++) {
            var btn = document.getElementById('song' + i);
            btn.innerHTML = update.votes[i][0];
            btn.disabled = false;
            document.getElementById('votes' + i).innerHTML = 0;
            document.getElementById('message').innerHTML = "";
            btn.onclick = (function() {
                var currentI = i;
                return function() {
                    document.getElementById("vote").value=update.votes[currentI][0];
                    document.button_submit.submit();
                }

            })();
        }
    else
        for (var i = 0; i < 3; i++) {
            document.getElementById('votes' + i).innerHTML=update.votes[i][1];
        }

};

onError = function(err) {
    // alert(err);
};

onClose = function() {
    //reconnect();
};


