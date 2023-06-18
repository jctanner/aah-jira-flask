function childrenToHTML(parent_key, imap, keynames, level) {

    if ( level > 20) {
        return "";
    }

    let colormap = {
        "X": "ilightsteelblue",
        "E": "gold",
        //"S": "burlywood",
        "S": "lightblue",
        "F": "lightgreen",
        //"T": "#888888",
        "T": "gainsboro",
        "B": "lightcoral",
        "I": "",
    }

    let color = 'lightsteelblue';
    let itype = "X";
    if (imap[parent_key]['type'] !== null) {
        itype = imap[parent_key]['type'].charAt(0).toUpperCase();
        if ( imap[parent_key]['type'] === "Sub-task" ) {
            itype = "ST";
        }
        if ( imap[parent_key]['type'] === "Feature Request" ) {
            itype = "FR";
        }
        if ( imap[parent_key]['type'] === "Spike" ) {
            itype = "SP";
        }
        if (itype in colormap) {
            color = colormap[itype];
        }
    }
    let icon = '(' + itype + ')';

    let HTML = ""
    HTML += '<ul class="nested">';
    HTML += `<li style="background-color: ${color};">`;
    HTML += icon + " "
    if (imap[parent_key]['status'] === 'Closed') {
        HTML += "<s>" + parent_key + " " + imap[parent_key].summary + '</s>\n'
    } else {
        HTML += parent_key + " " + imap[parent_key].summary + '\n'
    }

    for (key of keynames) {
        let ds = imap[key];
        if (ds.parent_key === parent_key) {
            HTML += childrenToHTML(key, imap, keynames, level + 1);
        }
    };

    HTML += "</li>"
    HTML += "</ul>";

    return HTML;
}

function onLoad() {

    document.getElementById('tree').innerHTML = '<div class="spinner"></div>';

    fetch("/api/tickets_tree", {
        method: "GET",
        headers: {'Content-Type': 'application/json'}, 
    }).then(res => res.json()).then(res => {

        let imap = res;

        console.log("Request complete! response:", res, typeof res);
        var newHTML = '<ul class="collapsible">';

        console.log(imap, typeof imap);

        let keynames = [];
        Object.keys(imap).forEach(function(key) {
            keynames.push(key);
        });
        keynames.sort(function(a, b) {
          var pattern = /([A-Z]+)-(\d+)/;
          var aMatches = a.match(pattern);
          var bMatches = b.match(pattern);

          var aPrefix = aMatches[1];
          var bPrefix = bMatches[1];
          var aNumber = parseInt(aMatches[2]);
          var bNumber = parseInt(bMatches[2]);

          if (aPrefix < bPrefix) {
            return -1;
          } else if (aPrefix > bPrefix) {
            return 1;
          } else {
            return aNumber - bNumber;
          }
        });

        let top_parents = [];
        Object.keys(imap).forEach(function(key) {
            let ds = imap[key];
            if (( ds.parent_key === null ) && (! top_parents.includes(key))){
                console.log(ds.parent_key);
                top_parents.push(key);
            }
        });

        top_parents.sort(function(a, b) {
          var pattern = /([A-Z]+)-(\d+)/;
          var aMatches = a.match(pattern);
          var bMatches = b.match(pattern);

          var aPrefix = aMatches[1];
          var bPrefix = bMatches[1];
          var aNumber = parseInt(aMatches[2]);
          var bNumber = parseInt(bMatches[2]);

          if (aPrefix < bPrefix) {
            return -1;
          } else if (aPrefix > bPrefix) {
            return 1;
          } else {
            return aNumber - bNumber;
          }
        });

        console.log('top parents', top_parents);

        if (top_parents.length === 0) {
            for (keyname of keynames) {
                newHTML += childrenToHTML(keyname, imap, keynames, 0);
            }
        } else {
            for (tp of top_parents) {
                newHTML += childrenToHTML(tp, imap, keynames, 0);
            }
        }

        newHTML += '</ul>';
        console.log("done building tree");
        document.getElementById('tree').innerHTML = newHTML;

        /*
        // JavaScript code to handle the collapsible functionality
        var collapsibleItems = document.getElementsByClassName('collapsible');

        Array.from(collapsibleItems).forEach(function(item) {
          item.addEventListener('click', function() {
            console.log('got a click!');
            this.classList.toggle('collapsed');
          });
        });
        */

    });
};
