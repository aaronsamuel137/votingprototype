onOpened = function() {
    connected = true;
    //sendMessage('opened');
};

onMessage = function(message) {
    update = eval('(' + message.data + ')');
    for (var i = 0; i < update.length; i++) {
        document.getElementById(update[i][0]).innerHTML=update[i][1];
    }
};

onError = function(err) {
    // alert(err);
};

onClose = function() {
    // alert("close");
    // connected = false;
};