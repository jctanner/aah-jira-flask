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
        "SG": "skyblue",
    }

    let color = 'lightsteelblue';
    let itype = "X";
    if (imap[parent_key]['type'] !== null) {
        itype = imap[parent_key]['type'].charAt(0).toUpperCase();
        if ( imap[parent_key]['type'] === "Strategic Goal" ) {
            itype = "SG";
        }
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
    let icon = '<span title="' + imap[parent_key]['type']  + '">' + '(' + itype + ')' + '</span>';

    let HTML = ""
    HTML += '<ul class="nested">';
    HTML += `<li style="background-color: ${color};">`;


    let title = "";

    title += "[" + parent_key + "]"
    title += ' (' + imap[parent_key]['status'] + ') '

    if (imap[parent_key].completed !== null) {
        title += " " + "(" + imap[parent_key].completed + ") "
    }
    title += imap[parent_key].summary;

    if (imap[parent_key]['status'] === 'Closed' || imap[parent_key]['status'] === 'Release Pending') {
        title = "<s>" + title + "</s>";
    }
    let href = '<a href="/ui/issues/' + parent_key + '" style="color: inherit; text-decoration: none;">';
    href += title + '</a>';

    HTML += icon + " "
    /*
    if (imap[parent_key]['status'] === 'Closed') {
        HTML += "<s>" + parent_key + " " + imap[parent_key].summary + '</s>\n'
    } else {
        HTML += parent_key + " " + imap[parent_key].summary + '\n'
    }
    */
    HTML += href + '\n';

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

function makeChildTree(parent_key) {

    /*
    queryString = window.location.search;
    const urlParams = new URLSearchParams(queryString);
    let projects = urlParams.getAll("project");
    let showClosed = urlParams.get("showclosed");
    let issue_key = urlParams.get("key");
    let project = urlParams.get("project");
    let showProgress = urlParams.get("progress");

    if (showClosed === null || showClosed === "") {
        const url = new URL(window.location.href);
        url.searchParams.set("showclosed", "1");
        history.replaceState(null, '', url.toString());
        showClosed = "1";
    }
    */

    showClosed = true;

    document.getElementById('tree').innerHTML = '<div class="spinner"></div>';

    let api_url = `/api/ticket_child_tree/${parent_key}`;

    fetch(api_url, {
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

        /*
        let top_parents = [];
        Object.keys(imap).forEach(function(key) {
            let ds = imap[key];
            if ((( ds.parent_key === null ) && (! top_parents.includes(key))) || ds.parent_key === parent_key){
                console.log(ds.parent_key);
                top_parents.push(key);
            }
        });
        */

        top_parents = [parent_key];

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

                issue = imap[tp];
                console.log(issue);
                //console.log("state", issue.state);
                if (showClosed === 1 || issue.status !== 'Closed') {
                    newHTML += childrenToHTML(tp, imap, keynames, 0);
                }
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
