// Define a custom date adapter
//class CustomDateAdapter extends Chart._adapters._date.adapters._date {
class CustomDateAdapter extends Chart._adapters._date {
  constructor(options) {
	super(options);
  }

  format(timestamp, format) {
	const date = new Date(timestamp);
	const year = date.getFullYear();
	const month = String(date.getMonth() + 1).padStart(2, '0');
	const day = String(date.getDate()).padStart(2, '0');

	return `${year}-${month}-${day}`;
  }

  parse(timestamp) {
	const [year, month, day] = timestamp.split('-').map(Number);

	return new Date(year, month - 1, day);
  }

  add(timestamp, amount, unit) {
	const date = new Date(timestamp);
	const adjustedDate = new Date(date.getTime());

	switch (unit) {
	  case 'day':
		adjustedDate.setDate(date.getDate() + amount);
		break;
	  // Add support for other units if needed
	}

	return adjustedDate;
  }

  diff(a, b, unit) {
	const diff = a.getTime() - b.getTime();

	switch (unit) {
	  case 'day':
		return Math.round(diff / (24 * 60 * 60 * 1000));
	  // Add support for other units if needed
	}

	return null;
  }
}

// Register the custom date adapter
//Chart.register(CustomDateAdapter);

function onLoad() {

    queryString = window.location.search;
    const urlParams = new URLSearchParams(queryString);
    let projects = urlParams.getAll("project");
    let fields = urlParams.getAll("field");
    let start = urlParams.get("start");
    let end = urlParams.get("end");

    if (projects.length === 0) {
        const url = new URL(window.location.href);
        url.searchParams.set("project", null);
        history.replaceState(null, '', url.toString());
        projects = [];
    }

    document.getElementById('churn-chart').innerHTML = '<div class="spinner"></div>';

    const apiParams = new URLSearchParams();
    projects.forEach(value => {
        apiParams.append("project", value);
    });
    fields.forEach(value => {
        apiParams.append("field", value);
    });
    if ( start !== null ) {
        apiParams.append("start", start);
    }
    if ( end !== null ) {
        apiParams.append("end", end);
    }
    const apiString = apiParams.toString();
    const apiUrl = `/api/tickets_churn/?${apiString}`;

    fetch(apiUrl, {
        method: "GET",
        headers: {'Content-Type': 'application/json'}, 
    }).then(res => res.json()).then(res => {
        console.log("Request complete! response:", res, typeof res);

        let newHTML = "";
        newHTML += '<h1>' + projects.join("/") + ' CHURN' + '</h1>';
        document.getElementById('churn-chart').innerHTML = newHTML;

        /*
        const labels = Object.keys(res);
		console.log(labels);
        const values = Object.values(res);
		console.log(values);
        */

		const ctx = document.getElementById('barChart').getContext('2d');

        let labels = [];
        let datasets = [];
        Object.keys(res).forEach(key => {
            labels.push(key);
            labels = [];
            let vals = res[key];

            Object.keys(vals).forEach(key2 => {
                labels.push(key2);
            });

            let ds = {
                label: key,
                data: vals
            };
            datasets.push(ds);
        });

        const lineChart = new Chart(ctx, {
            type: 'bar',
            options: {
                responsive: true
            },
            data: {
                labels: labels,
                datasets: datasets
            }
		});

        console.log("done building churn");
    });
};
