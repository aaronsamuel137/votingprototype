onOpened = function() {
    connected = true;
    //sendMessage('opened');
};

onMessage = function(message) {
    update = $.parseJSON(message.data);
    if (update.new_vote === true)
        for (var i = 0; i < 3; i++) {
            var btn = document.getElementById(update.old_vote[i][0] + '_name');
            btn.setAttribute('id', update.votes[i][0] + '_name')
            btn.innerHTML = update.votes[i][0];
            btn.disabled = false;
            document.getElementById(update.old_vote[i][0]).innerHTML = 0;
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
            document.getElementById(update.votes[i][0]).innerHTML=update.votes[i][1];
        }

};

onError = function(err) {
    // alert(err);
};

onClose = function() {
    // alert("close");
    // connected = false;
};

