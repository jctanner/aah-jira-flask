/*
<div id="description-rendered">
{{ issue_description | safe }}
</div>

<div id="description-raw" class="hidden">
<pre>
{{ issue_description_raw }}
</pre>
<button id="description-toggle" class="btn btn-secondary" onClick="toggleDescription();">raw</button>
*/

function toggleDescription() {

    // get the toogle button
    let button = document.getElementById('description-toggle');
    let buttonText = button.textContent;

    // get the raw div
    let raw = document.getElementById('description-raw');

    // get the formatted div
    let formatted = document.getElementById('description-rendered');

    if (buttonText === 'raw') {
        console.log('show raw ...');
        button.textContent = 'rendered';
        //formatted.classList.remove("hidden");
        //1raw.classList.remove("hidden");
        formatted.style.display = "none";
        raw.style.display = "block";
    } else {
        console.log('show formatted ...');
        button.textContent = 'raw';
        //raw.classList.remove("hidden");
        //formatted.classList.remove("hidden");
        formatted.style.display = "block";
        raw.style.display = "none";
    }

    //formatted.classList.toggle("hidden");
    //raw.classList.toggle("hidden");

}

function setRenderedDescription() {
    // get the toogle button
    let button = document.getElementById('description-toggle');
    let buttonText = button.textContent;

    // get the raw div
    let raw = document.getElementById('description-raw');

    // get the formatted div
    let formatted = document.getElementById('description-rendered');

    console.log('show formatted ...');
    button.textContent = 'raw';
    //raw.classList.remove("hidden");
    //formatted.classList.remove("hidden");
    formatted.style.display = "block";
    raw.style.display = "none";

}

function onLoad() {

    // hide the raw issue description by default if the div exists ...
    let button = document.getElementById('description-toggle');
    if (button) {
        setRenderedDescription();
    }

}
